"""In-memory fakes for what P1/P2 have NOT delivered yet.

Where P1's code exists (EventBus, Clock, IncidentFactory, SLAMonitor, Incident
lifecycle), tests use the real thing. FakeIncident stands in only for incident
features P1 hasn't built (escalation, timestamps, title).
"""

from __future__ import annotations

from collections.abc import Callable, Iterable, Mapping
from dataclasses import dataclass, field
from datetime import UTC, datetime, timedelta
from itertools import count
from typing import Any

from app.p4_contracts import DONE_STATUSES, UNACKNOWLEDGED_STATUSES, Vector
from domain.category import Category
from domain.enums import Priority, Status
from domain.service import ITService

T0 = datetime(2026, 11, 12, 10, 0, tzinfo=UTC)
PAYMENTS = ITService("S1", "Payments", 5)
EMAIL = ITService("S2", "Email", 3)
APPLICATION = Category("Application")

_ids = count(1)


@dataclass
class FakeIncident:
    """Mirrors domain.incident.Incident plus the PENDING_ fields P4 asked P1 for."""

    incident_id: str = field(default_factory=lambda: f"INC{next(_ids):04d}")
    description: str = "Users cannot complete transactions"
    status: Status = Status.ASSIGNED
    priority: Priority | None = Priority.P1
    category: Any = APPLICATION
    service: Any = PAYMENTS
    resolution: str | None = None
    sla: Any = None
    PENDING_G14_title: str | None = "Payment application unavailable"
    PENDING_G13_created_at: datetime = T0
    PENDING_G1_resolved_at: datetime | None = None
    PENDING_G15_escalation_level: int = 0
    PENDING_G2_last_escalated_at: datetime | None = None
    clock: Callable[[], datetime] = lambda: T0
    calls: list[tuple[Any, ...]] = field(default_factory=list)
    exhausted: bool = False

    # --- behaviour P1 is being asked to add (G15, G4) -----------------------------
    def PENDING_G15_escalate(self, to_user_id: str, level: int) -> None:
        if self.status not in UNACKNOWLEDGED_STATUSES:
            raise RuntimeError("cannot escalate an acknowledged incident")
        self.calls.append(("escalate", to_user_id, level))
        self.PENDING_G15_escalation_level = level
        self.PENDING_G2_last_escalated_at = self.clock()

    def PENDING_G4_mark_escalation_exhausted(self) -> bool:
        if self.exhausted:
            return False
        self.exhausted = True
        self.calls.append(("exhausted",))
        return True

    # --- the existing P1 lifecycle methods used by auto-close ------------------------
    def verify(self, actor: Any = None) -> None:
        assert self.status == Status.RESOLVED
        self.calls.append(("verify",))
        self.status = Status.VERIFIED

    def close(self, actor: Any = None) -> None:
        assert self.status == Status.VERIFIED
        self.calls.append(("close",))
        self.status = Status.CLOSED


def make_incident(**kw: Any) -> FakeIncident:
    return FakeIncident(**kw)


class FakeIncidentRepository:
    """Holds FakeIncidents and/or real P1 Incidents, keyed by incident_id."""

    def __init__(self, incidents: Iterable[Any] = ()) -> None:
        self.items: dict[str, Any] = {i.incident_id: i for i in incidents}
        self.links: list[tuple[str, str, float, datetime]] = []
        self.fail_get: set[str] = set()

    def add(self, *incidents: Any) -> None:
        for i in incidents:
            self.items[i.incident_id] = i

    def _open(self) -> list[Any]:
        return [i for i in self.items.values() if i.status not in DONE_STATUSES]

    def get(self, incident_id: str) -> Any:
        if incident_id in self.fail_get:
            raise KeyError(incident_id)
        return self.items[incident_id]

    def PENDING_G5_get_for_update(self, incident_id: str) -> Any:
        return self.get(incident_id)

    def open_incidents(self) -> list[Any]:
        return self._open()

    def open_since(self, t: datetime, exclude_id: str | None = None) -> list[Any]:
        return [i for i in self._open()
                if i.PENDING_G13_created_at >= t and i.incident_id != exclude_id]

    def resolved_with_text(self) -> list[Any]:
        return [i for i in self.items.values()
                if i.status in DONE_STATUSES and (i.resolution or "").strip()]

    def resolved_before(self, t: datetime) -> list[Any]:
        return [i for i in self.items.values()
                if i.status == Status.RESOLVED
                and i.PENDING_G1_resolved_at is not None and i.PENDING_G1_resolved_at < t]

    def PENDING_G11_open_unacknowledged(self, priorities: Iterable[Priority]) -> list[Any]:
        ps = set(priorities)
        return [i for i in self._open()
                if i.status in UNACKNOWLEDGED_STATUSES and i.priority in ps]

    def PENDING_G10_related_links_since(self, t: datetime) -> list[tuple[str, str, float]]:
        return [(a, b, s) for a, b, s, at in self.links if at >= t]


class FakeIntelligenceSink:
    def __init__(self, repo: FakeIncidentRepository,
                 clock: Callable[[], datetime] = lambda: T0) -> None:
        self.repo = repo
        self.clock = clock
        self.calls: list[tuple[Any, ...]] = []

    def link_related(self, a: str, b: str, score: float) -> None:
        self.calls.append(("link_related", a, b, score))
        self.repo.links.append((a, b, score, self.clock()))

    def set_suggested_category(self, incident_id: str, category: str, confidence: float) -> None:
        self.calls.append(("set_suggested_category", incident_id, category, confidence))

    def calls_to(self, name: str) -> list[tuple[Any, ...]]:
        return [c for c in self.calls if c[0] == name]


@dataclass(frozen=True)
class EscalationTarget:
    user_id: str
    level: int


class FakeEscalationDirectory:
    """chain[i] = (user_id, active) is the person at level i+1."""

    def __init__(self, chain: list[tuple[str, bool]]) -> None:
        self.chain = chain

    def next_in_chain(self, level: int) -> EscalationTarget | None:
        for idx in range(level, len(self.chain)):
            user_id, active = self.chain[idx]
            if active:
                return EscalationTarget(user_id, idx + 1)
        return None


class FakeEmbeddingStore:
    def __init__(self) -> None:
        self.vectors: dict[str, Vector] = {}

    def save(self, incident_id: str, vector: Vector) -> None:
        self.vectors[incident_id] = vector

    def get_many(self, incident_ids: Iterable[str]) -> Mapping[str, Vector]:
        return {i: self.vectors[i] for i in incident_ids if i in self.vectors}


class FakeUnitOfWork:
    def __init__(self, repo: FakeIncidentRepository, sink: FakeIntelligenceSink,
                 directory: FakeEscalationDirectory, store: FakeEmbeddingStore) -> None:
        self.incidents = repo
        self.intelligence = sink
        self.escalation_directory = directory
        self.embeddings = store
        self.commits = 0
        self.rollbacks = 0
        self.closed = 0

    def commit(self) -> None:
        self.commits += 1

    def rollback(self) -> None:
        self.rollbacks += 1

    def close(self) -> None:
        self.closed += 1


def minutes(n: float) -> timedelta:
    return timedelta(minutes=n)
