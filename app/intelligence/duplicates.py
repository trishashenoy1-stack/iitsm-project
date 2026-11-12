"""Duplicate detection (pure) and correlation clustering (pure).

Matches are suggestions only: the caller links them via IncidentService.link_related.
Nothing is ever merged or closed automatically.
"""

from __future__ import annotations

from collections import defaultdict
from collections.abc import Callable, Iterable, Mapping
from dataclasses import dataclass
from datetime import datetime, timedelta
from enum import StrEnum

import numpy as np

from app.config import Settings
from app.p4_contracts import (
    DONE_STATUSES,
    IncidentRepository,
    IncidentView,
    Vector,
    category_name_of,
    service_id_of,
)


class MatchReason(StrEnum):
    SIMILARITY = "similarity"
    FALLBACK = "fallback"  # short description: same service + same category in window


@dataclass(frozen=True)
class DuplicateMatch:
    other_id: str
    score: float
    reason: MatchReason


@dataclass(frozen=True)
class DuplicateConfig:
    threshold: float
    same_service_bonus: float
    min_chars: int
    window: timedelta

    @classmethod
    def from_settings(cls, s: Settings) -> DuplicateConfig:
        return cls(
            threshold=s.DUP_THRESHOLD,
            same_service_bonus=s.DUP_SAME_SERVICE_BONUS,
            min_chars=s.DUP_MIN_CHARS,
            window=timedelta(hours=s.DUP_WINDOW_HOURS),
        )


class DuplicateDetector:
    def __init__(self, cfg: DuplicateConfig) -> None:
        self._cfg = cfg

    @property
    def config(self) -> DuplicateConfig:
        return self._cfg

    def score(self, a: Vector, b: Vector, same_service: bool) -> float:
        sim = float(np.dot(a, b))
        return sim + (self._cfg.same_service_bonus if same_service else 0.0)

    def is_short(self, incident: IncidentView) -> bool:
        return len((incident.description or "").strip()) < self._cfg.min_chars

    def find_matches(
        self,
        new: IncidentView,
        new_vec: Vector | None,
        candidates: Iterable[IncidentView],
        vectors: Mapping[str, Vector],
    ) -> list[DuplicateMatch]:
        new_at = new.PENDING_G13_created_at
        earliest = new_at - self._cfg.window
        use_fallback = new_vec is None or self.is_short(new)
        new_service, new_category = service_id_of(new), category_name_of(new)
        matches: list[DuplicateMatch] = []

        for c in candidates:
            if c.incident_id == new.incident_id or c.status in DONE_STATUSES:
                continue
            if not (earliest <= c.PENDING_G13_created_at <= new_at):
                continue
            same_service = new_service is not None and service_id_of(c) == new_service
            other_vec = vectors.get(c.incident_id)

            if use_fallback or other_vec is None:
                if same_service and new_category is not None \
                        and category_name_of(c) == new_category:
                    matches.append(
                        DuplicateMatch(c.incident_id, self._cfg.threshold, MatchReason.FALLBACK)
                    )
                continue

            assert new_vec is not None
            s = self.score(new_vec, other_vec, same_service)
            if s >= self._cfg.threshold:
                matches.append(DuplicateMatch(c.incident_id, s, MatchReason.SIMILARITY))

        return sorted(matches, key=lambda m: m.score, reverse=True)


class Correlator:
    """Connected components over related-incident links, grouped by service."""

    @staticmethod
    def components(links: Iterable[tuple[str, str]]) -> list[frozenset[str]]:
        parent: dict[str, str] = {}

        def find(x: str) -> str:
            parent.setdefault(x, x)
            while parent[x] != x:
                parent[x] = parent[parent[x]]  # path halving
                x = parent[x]
            return x

        for a, b in links:
            ra, rb = find(a), find(b)
            if ra != rb:
                parent[max(ra, rb)] = min(ra, rb)  # deterministic root

        groups: dict[str, set[str]] = defaultdict(set)
        for node in parent:
            groups[find(node)].add(node)
        return [frozenset(g) for g in groups.values() if len(g) >= 2]

    def clusters_by_service(
        self,
        links: Iterable[tuple[str, str]],
        service_of: Callable[[str], str],
    ) -> dict[str, list[frozenset[str]]]:
        out: dict[str, list[frozenset[str]]] = defaultdict(list)
        for comp in self.components(links):
            # A component can span services; it is filed under its most common service.
            services = [service_of(i) for i in comp]
            dominant = max(set(services), key=lambda s: (services.count(s), str(s)))
            out[dominant].append(comp)
        return dict(out)


def PENDING_G10_clusters_for_dashboard(
    repo: IncidentRepository, now: datetime, window: timedelta
) -> dict[str, list[frozenset[str]]]:
    """G10: P2 calls this from GET /reports/clusters (or tells us the shape they want)."""
    links = [(a, b) for a, b, _score in repo.PENDING_G10_related_links_since(now - window)]
    return Correlator().clusters_by_service(
        links, lambda i: service_id_of(repo.get(i)) or "unknown"
    )
