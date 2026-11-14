"""Builds P2's real repository and directory for P4's contract tests (tests/contract/).

The contract tests describe incidents as FakeIncidents (status, created_at, resolved_at).
Here each one is created for real through the API services, with a FakeClock at its
times, and the real repository's answers are mapped back to the fake ids.
"""

from __future__ import annotations

from datetime import timedelta
from typing import Any

from app.bootstrap import Backend
from app.db.models import UserRecord
from app.persistence.uow import UnitOfWork, UnitOfWorkFactory
from app.services.incidents import IncidentService, NewIncident
from domain.clock import FakeClock
from domain.enums import Status
from domain.events import EventBus
from tests.p2.conftest import T0, add_people, make_settings

STEPS = {
    Status.ASSIGNED: [],
    Status.RESOLVED: ["acknowledge", "start_work", "resolve"],
    Status.CLOSED: ["acknowledge", "start_work", "resolve", "verify", "close"],
}


def _backend() -> Backend:
    backend = Backend.build(make_settings("sqlite://"), clock=FakeClock(T0), with_p4=False)
    add_people(backend)
    return backend


class MappedRepository:
    """The real IncidentRepository, answering with the contract test's fake ids."""

    def __init__(self, uow: UnitOfWork, real_to_fake: dict[str, str]) -> None:
        self._uow = uow
        self._fake = real_to_fake
        self._real = {v: k for k, v in real_to_fake.items()}

    def _map(self, incidents: Any) -> list[Any]:
        return [_Renamed(i, self._fake[i.incident_id]) for i in incidents]

    def open_incidents(self) -> list[Any]:
        return self._map(self._uow.incidents.open_incidents())

    def open_since(self, t: Any, exclude_id: str | None = None) -> list[Any]:
        return self._map(self._uow.incidents.open_since(
            t, exclude_id=self._real.get(exclude_id or "")))

    def resolved_before(self, t: Any) -> list[Any]:
        return self._map(self._uow.incidents.resolved_before(t))


class _Renamed:
    def __init__(self, incident: Any, fake_id: str) -> None:
        self._incident, self.incident_id = incident, fake_id

    def __getattr__(self, name: str) -> Any:
        return getattr(self._incident, name)


def real_repository(fakes: list[Any]) -> MappedRepository:
    backend = _backend()
    mapping: dict[str, str] = {}
    for fake in fakes:
        created = fake.PENDING_G13_created_at
        # Start before the resolve time the fake asks for, so time only moves forward.
        start = min(created, fake.PENDING_G1_resolved_at or created)
        clock = FakeClock(start)
        flow = IncidentService(UnitOfWorkFactory(backend.session_factory, EventBus(), clock))
        real_id = flow.report("E101", NewIncident(fake.description, "SVC-PAY", "APPLICATION",
                                                  "HIGH", "HIGH", 10))
        for action in STEPS[fake.status]:
            actor = {"verify": "E101", "close": "A101"}.get(action, "T101")
            target = fake.PENDING_G1_resolved_at if action == "resolve" else None
            if target is not None and target > clock.now():
                clock.advance(seconds=(target - clock.now()).total_seconds())
            flow.act(actor, real_id, action, "Fixed" if action == "resolve" else None)
        mapping[real_id] = fake.incident_id
    return MappedRepository(backend.uow_factory(), mapping)


def real_directory(chain: list[tuple[str, bool]]) -> Any:
    backend = _backend()
    with backend.session_factory() as s:
        s.query(UserRecord).filter(UserRecord.escalation_level.is_not(None)).update(
            {"escalation_level": None})
        for level, (user_id, active) in enumerate(chain, start=1):
            s.add(UserRecord(id=user_id, email=f"{user_id.lower()}@corp.test", name=user_id,
                             password_hash="x", role="ADMIN", escalation_level=level,
                             active=active, created_at=T0 - timedelta(days=1)))
        s.commit()
    return backend.uow_factory().escalation_directory
