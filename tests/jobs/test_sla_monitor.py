"""SLA monitor job, run against P1's REAL domain objects (factory, SLATracker, SLAMonitor)."""

from __future__ import annotations

from datetime import datetime, timedelta
from types import SimpleNamespace
from typing import Any

import pytest

from app.jobs.sla_monitor import run_sla_monitor
from domain.enums import Impact, Status, Urgency
from domain.events import SLABreached, SLAWarning
from domain.sla_monitor import SLAMonitor
from tests.fakes.in_memory import EMAIL, FakeIncidentRepository


def _create(world: SimpleNamespace, *, p3: bool = False) -> Any:
    if p3:  # Email (criticality 3), medium x medium -> P3: response 1 h, resolution 8 h
        inc = world.factory.create(world.reporter, EMAIL, "Mail sync slow",
                                   Impact.MEDIUM, Urgency.MEDIUM)
    else:  # Payments (criticality 5), high x high -> P1: response 5 min, resolution 30 min
        inc = world.factory.create(world.reporter, world.service, "Payment app down",
                                   Impact.HIGH, Urgency.HIGH)
    inc.assign(technician=world.tech)
    return inc


def _sla_events(world: SimpleNamespace) -> list[Any]:
    return [e for e in world.events if isinstance(e, (SLAWarning, SLABreached))]


def _run(world: SimpleNamespace, repo: FakeIncidentRepository) -> Any:
    return run_sla_monitor(world.clock.now(), repo, SLAMonitor(world.bus, world.clock))


@pytest.mark.case(id="TC-P4-01", category="business-rule",
                  desc="Open P1, past response deadline, not acknowledged",
                  expected="Exactly one response breach event")
def test_response_breach_recorded(world: SimpleNamespace, repo: FakeIncidentRepository) -> None:
    repo.add(_create(world))
    world.clock.advance(minutes=6)
    result = _run(world, repo)
    assert result.actions["response_breach"] == 1
    assert [type(e) for e in _sla_events(world)] == [SLABreached]


@pytest.mark.case(id="TC-P4-02", category="business-rule",
                  desc="SLA monitor runs twice on the same state",
                  expected="No duplicate warning/breach events")
def test_monitor_is_idempotent(world: SimpleNamespace, repo: FakeIncidentRepository) -> None:
    repo.add(_create(world), _create(world))
    world.clock.advance(minutes=6)
    first = _run(world, repo)
    second = _run(world, repo)
    assert sum(first.actions.values()) > 0
    assert sum(second.actions.values()) == 0


@pytest.mark.case(id="TC-P4-03", category="boundary",
                  desc="Scheduler down across a deadline, then restarts",
                  expected="Breach caught on the first run after restart")
def test_missed_ticks_are_caught_up(world: SimpleNamespace,
                                    repo: FakeIncidentRepository) -> None:
    repo.add(_create(world))
    world.clock.advance(hours=6)
    result = _run(world, repo)
    assert result.actions["response_breach"] == 1
    assert result.actions["resolution_breach"] == 1


@pytest.mark.case(id="TC-P4-04", category="boundary",
                  desc="Incident inside the warning window",
                  expected="Exactly one warning, no breach")
def test_single_warning(world: SimpleNamespace, repo: FakeIncidentRepository) -> None:
    repo.add(_create(world, p3=True))
    world.clock.advance(minutes=50)  # past 80% of the 60-min response target
    _run(world, repo)
    world.clock.advance(minutes=5)
    _run(world, repo)
    assert [type(e) for e in _sla_events(world)] == [SLAWarning]


@pytest.mark.case(id="TC-P4-05", category="business-rule",
                  desc="Acknowledged incident past its response deadline",
                  expected="No response breach")
def test_acknowledged_no_response_breach(world: SimpleNamespace,
                                         repo: FakeIncidentRepository) -> None:
    inc = _create(world)
    world.clock.advance(minutes=2)
    inc.acknowledge()
    repo.add(inc)
    world.clock.advance(minutes=8)
    assert _run(world, repo).actions["response_breach"] == 0


@pytest.mark.case(id="TC-P4-06", category="business-rule",
                  desc="Resolved incident past its resolution deadline",
                  expected="No breach")
def test_resolved_no_breach(world: SimpleNamespace, repo: FakeIncidentRepository) -> None:
    inc = _create(world)
    world.clock.advance(minutes=1)
    inc.acknowledge()
    inc.start_work()
    inc.resolve(resolution="Restarted gateway")
    repo.add(inc)
    world.clock.advance(hours=2)
    _run(world, repo)
    assert _sla_events(world) == []


@pytest.mark.case(id="TC-P4-07", category="exception",
                  desc="One incident raises during a monitor run",
                  expected="Others still processed; error logged")
def test_one_failure_does_not_abort_batch(world: SimpleNamespace, repo: FakeIncidentRepository,
                                          caplog: pytest.LogCaptureFixture) -> None:
    def explode() -> None:
        raise RuntimeError("corrupt SLA state")

    bad = SimpleNamespace(incident_id="INC-BAD", status=Status.ASSIGNED,
                          sla=SimpleNamespace(evaluate=explode))
    good = _create(world)
    repo.add(bad, good)
    world.clock.advance(minutes=6)
    result = _run(world, repo)
    assert result.actions["response_breach"] == 1
    assert [e[0] for e in result.errors] == ["INC-BAD"]
    assert "failed" in caplog.text


def test_paused_incident_does_not_breach_resolution(world: SimpleNamespace,
                                                    repo: FakeIncidentRepository) -> None:
    inc = _create(world)
    world.clock.advance(minutes=1)
    inc.acknowledge()
    inc.start_work()
    world.clock.advance(minutes=10)
    inc.request_info()  # AWAITING_INFO: P1 pauses the resolution clock
    repo.add(inc)
    world.clock.advance(hours=1)
    assert _run(world, repo).actions["resolution_breach"] == 0


def test_naive_datetime_rejected(world: SimpleNamespace, repo: FakeIncidentRepository) -> None:
    with pytest.raises(ValueError):
        run_sla_monitor(datetime(2026, 11, 12, 10, 0), repo, SLAMonitor(world.bus, world.clock))


def test_resume_extends_deadline(world: SimpleNamespace) -> None:
    """Documents P1's paused-clock rule that P4 relies on (G3, confirmed 12 Nov)."""
    inc = _create(world)
    before = inc.sla.resolution_deadline()
    world.clock.advance(minutes=1)
    inc.acknowledge()
    inc.start_work()
    inc.request_info()
    world.clock.advance(minutes=20)
    inc.provide_info()
    assert inc.sla.resolution_deadline() - before == timedelta(minutes=20)
