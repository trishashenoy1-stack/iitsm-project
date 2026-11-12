"""Suggested resolution: kNN over embeddings of resolved incidents (brute-force numpy)."""

from __future__ import annotations

import threading
from collections.abc import Iterable
from dataclasses import dataclass

import numpy as np

from app.p4_contracts import Vector


@dataclass(frozen=True)
class ResolvedEntry:
    incident_id: str
    vector: Vector
    category: str | None
    resolution_text: str


@dataclass(frozen=True)
class ResolutionSuggestion:
    incident_id: str
    similarity: float
    category: str | None
    resolution_text: str


class ResolutionIndex:
    def __init__(self) -> None:
        self._lock = threading.RLock()
        self._entries: list[ResolvedEntry] = []
        self._matrix: np.ndarray | None = None

    def __len__(self) -> int:
        return len(self._entries)

    def rebuild(self, entries: Iterable[ResolvedEntry]) -> None:
        with self._lock:
            self._entries = [e for e in entries if e.resolution_text.strip()]
            self._matrix = (
                np.vstack([e.vector for e in self._entries]) if self._entries else None
            )

    def add(self, entry: ResolvedEntry) -> None:
        if not entry.resolution_text.strip():
            return
        with self._lock:
            # Replace if this incident is already indexed (reopened, then resolved again).
            self._entries = [e for e in self._entries if e.incident_id != entry.incident_id]
            self._entries.append(entry)
            self._matrix = np.vstack([e.vector for e in self._entries])

    def query(
        self,
        vector: Vector,
        k: int,
        min_sim: float,
        category: str | None = None,
        exclude_id: str | None = None,
    ) -> list[ResolutionSuggestion]:
        with self._lock:
            if self._matrix is None or k <= 0:
                return []
            sims = self._matrix @ np.asarray(vector, dtype=np.float32)
            hits = [
                ResolutionSuggestion(e.incident_id, float(s), e.category, e.resolution_text)
                for e, s in zip(self._entries, sims, strict=True)
                if s >= min_sim and e.incident_id != exclude_id
            ]
        # Prefer the same category, then higher similarity.
        hits.sort(key=lambda h: (category is not None and h.category == category, h.similarity),
                  reverse=True)
        return hits[:k]


class ResolutionSuggester:
    """Read-only suggestions for the technician view (P2 exposes it through an API)."""

    def __init__(self, index: ResolutionIndex, k: int, min_sim: float) -> None:
        self._index = index
        self._k = k
        self._min_sim = min_sim

    def suggest(
        self, incident_id: str, vector: Vector, category: str | None
    ) -> list[ResolutionSuggestion]:
        return self._index.query(vector, self._k, self._min_sim, category, exclude_id=incident_id)
