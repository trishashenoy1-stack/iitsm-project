"""End to end through wire_p4: real P1 EventBus and events in, sink calls out."""

from __future__ import annotations

from collections.abc import Iterator
from datetime import datetime, timedelta

import pytest

from app.config import Settings
from app.intelligence.features import FeatureRegistry
from app.p4_wiring import P4Runtime, wire_p4
from domain.clock import FakeClock
from domain.enums import Status
from domain.events import SYSTEM, EventBus, IncidentCreated, StatusChanged
from tests.fakes.in_memory import (
    FakeIncidentRepository,
    FakeIntelligenceSink,
    FakeUnitOfWork,
    make_incident,
)


@pytest.fixture
def runtime(settings: Settings, bus: EventBus, uow: FakeUnitOfWork,
            clock: FakeClock) -> Iterator[P4Runtime]:
    rt = wire_p4(settings, bus, lambda: uow, clock=clock, start_scheduler=False)
    rt.listener._retry_delay = 0  # no sleeping in tests
    yield rt
    rt.shutdown()


def _created(incident_id: str, t: datetime) -> IncidentCreated:
    return IncidentCreated(incident_id=incident_id, occurred_at=t, actor=SYSTEM)


def test_wiring_starts_with_missing_model(runtime: P4Runtime) -> None:
    assert not runtime.features.is_enabled(FeatureRegistry.CATEGORIZER)
    assert runtime.scheduler.job_names == ["sla_monitor", "escalation", "auto_close"]


def test_created_event_embeds_and_links(runtime: P4Runtime, bus: EventBus,
                                        repo: FakeIncidentRepository,
                                        sink: FakeIntelligenceSink, uow: FakeUnitOfWork,
                                        t0: datetime) -> None:
    a = make_incident(PENDING_G14_title="Payment gateway down",
                      description="Checkout fails with errors")
    b = make_incident(PENDING_G14_title="Payment gateway down",
                      description="Checkout fails with errors",
                      PENDING_G13_created_at=t0 + timedelta(minutes=2))
    repo.add(a)
    bus.publish(_created(a.incident_id, t0))
    repo.add(b)
    bus.publish(_created(b.incident_id, t0))
    assert set(uow.embeddings.vectors) == {a.incident_id, b.incident_id}
    links = sink.calls_to("link_related")
    assert len(links) == 1 and links[0][1:3] == (b.incident_id, a.incident_id)


def test_event_before_commit_is_retried(runtime: P4Runtime, bus: EventBus,
                                        repo: FakeIncidentRepository, uow: FakeUnitOfWork,
                                        t0: datetime) -> None:
    """G18: P1 publishes IncidentCreated before P2 saves; a short retry covers that."""
    inc = make_incident()
    repo.add(inc)
    attempts = {"n": 0}
    real_get = repo.get

    def flaky_get(incident_id: str) -> object:
        attempts["n"] += 1
        if attempts["n"] == 1:
            raise KeyError(incident_id)  # not committed yet
        return real_get(incident_id)

    repo.get = flaky_get  # type: ignore[method-assign]
    bus.publish(_created(inc.incident_id, t0))
    assert inc.incident_id in uow.embeddings.vectors


def test_failing_step_does_not_break_other_steps(runtime: P4Runtime, bus: EventBus,
                                                 repo: FakeIncidentRepository,
                                                 t0: datetime) -> None:
    inc = make_incident()
    repo.add(inc)

    def broken(*_a: object, **_kw: object) -> None:
        raise RuntimeError("db down")

    repo.open_since = broken  # type: ignore[method-assign]
    bus.publish(_created(inc.incident_id, t0))  # must not raise
    st = runtime.features.snapshot()[FeatureRegistry.DUPLICATES]
    assert st.last_error and "db down" in st.last_error
    assert FeatureRegistry.EMBEDDINGS in runtime.features.snapshot()  # embed step still ran


def test_resolved_status_change_feeds_suggestions(runtime: P4Runtime, bus: EventBus,
                                                  repo: FakeIncidentRepository,
                                                  t0: datetime) -> None:
    done = make_incident(PENDING_G14_title="Disk full on server",
                         description="No space left on device", status=Status.RESOLVED,
                         resolution="Rotated logs and cleared temp files")
    repo.add(done)
    bus.publish(StatusChanged(incident_id=done.incident_id, occurred_at=t0, actor=SYSTEM,
                              previous_status=Status.IN_PROGRESS, new_status=Status.RESOLVED))
    new = make_incident(PENDING_G14_title="Disk full on server",
                        description="No space left on device again")
    repo.add(new)
    hits = runtime.suggest_resolutions(new.incident_id)
    assert hits and hits[0].incident_id == done.incident_id


def test_other_status_changes_ignored(runtime: P4Runtime, bus: EventBus,
                                      repo: FakeIncidentRepository, t0: datetime) -> None:
    inc = make_incident(resolution="x")
    repo.add(inc)
    bus.publish(StatusChanged(incident_id=inc.incident_id, occurred_at=t0, actor=SYSTEM,
                              previous_status=Status.ASSIGNED, new_status=Status.ACKNOWLEDGED))
    assert len(runtime.resolution_index) == 0
