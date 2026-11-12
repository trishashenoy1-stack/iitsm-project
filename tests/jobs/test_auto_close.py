from __future__ import annotations

from datetime import datetime, timedelta
from types import SimpleNamespace

import pytest

from app.config import Settings
from app.jobs.auto_close import PENDING_G16_close_unverified, build_auto_close, run_auto_close
from domain.enums import Impact, Status, Urgency
from domain.events import SYSTEM, StatusChanged
from tests.fakes.in_memory import FakeIncidentRepository, make_incident


@pytest.mark.case(id="TC-P4-12", category="business-rule",
                  desc="Unverified RESOLVED incident past AUTO_CLOSE_DAYS",
                  expected="Auto-closed by the system actor")
def test_auto_close_after_days(repo: FakeIncidentRepository, settings: Settings,
                               t0: datetime) -> None:
    old = make_incident(status=Status.RESOLVED, PENDING_G1_resolved_at=t0)
    recent = make_incident(status=Status.RESOLVED, PENDING_G1_resolved_at=t0 + timedelta(days=2))
    repo.add(old, recent)
    result = run_auto_close(t0 + timedelta(days=3, minutes=1), repo, settings)
    assert result.actions["auto_closed"] == 1
    assert (old.status, recent.status) == (Status.CLOSED, Status.RESOLVED)


def test_verified_meanwhile_not_closed(repo: FakeIncidentRepository, settings: Settings,
                                       t0: datetime) -> None:
    inc = make_incident(status=Status.RESOLVED, PENDING_G1_resolved_at=t0)
    repo.add(inc)
    job = build_auto_close(repo, settings)
    selected = list(job.select(t0 + timedelta(days=4)))
    inc.status = Status.VERIFIED  # reporter verifies between select and process
    job.select = lambda now: selected  # type: ignore[method-assign]
    assert job.run(t0 + timedelta(days=4)).actions["auto_closed"] == 0


def test_interim_close_works_on_real_p1_incident(world: SimpleNamespace) -> None:
    """G16 interim: verify() + close() as SYSTEM is accepted by P1's real lifecycle."""
    inc = world.factory.create(world.reporter, world.service, "Payment app down",
                               Impact.HIGH, Urgency.HIGH)
    inc.assign(technician=world.tech)
    inc.acknowledge()
    inc.start_work()
    inc.resolve(resolution="Restarted gateway")
    PENDING_G16_close_unverified(inc)
    assert inc.status == Status.CLOSED
    changes = [e for e in world.events if isinstance(e, StatusChanged)][-2:]
    assert [e.new_status for e in changes] == [Status.VERIFIED, Status.CLOSED]
    assert all(e.actor is SYSTEM for e in changes)
