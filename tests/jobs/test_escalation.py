"""Escalation job. Uses FakeIncident because P1 hasn't built escalation yet (G15)."""

from __future__ import annotations

from datetime import datetime

import pytest

from app.config import Settings
from app.jobs.escalation import build_escalation, run_escalation
from domain.clock import FakeClock
from domain.enums import Priority, Status
from tests.conftest import IT_MANAGER, SYS_ADMIN, TEAM_LEAD
from tests.fakes.in_memory import (
    FakeEscalationDirectory,
    FakeIncident,
    FakeIncidentRepository,
    make_incident,
    minutes,
)


def _inc(clock: FakeClock, **kw: object) -> FakeIncident:
    return make_incident(clock=clock.now, **kw)


@pytest.mark.case(id="TC-P4-08", category="business-rule",
                  desc="P1 unacknowledged beyond the escalation time",
                  expected="Escalated to the next level via the domain method (audited)")
def test_escalates_to_next_level(repo: FakeIncidentRepository,
                                 directory: FakeEscalationDirectory, settings: Settings,
                                 clock: FakeClock) -> None:
    inc = _inc(clock)
    repo.add(inc)
    clock.advance(minutes=6)
    result = run_escalation(clock.now(), repo, directory, settings)
    assert result.actions["escalated"] == 1
    assert inc.calls == [("escalate", TEAM_LEAD, 1)]


def test_timer_restarts_after_each_escalation(repo: FakeIncidentRepository,
                                              directory: FakeEscalationDirectory,
                                              settings: Settings, clock: FakeClock) -> None:
    inc = _inc(clock)
    repo.add(inc)
    for step in (6, 2, 4):  # t=6 due; t=8 too soon after the last escalation; t=12 due
        clock.advance(minutes=step)
        run_escalation(clock.now(), repo, directory, settings)
    assert [c[1] for c in inc.calls] == [TEAM_LEAD, SYS_ADMIN]


@pytest.mark.case(id="TC-P4-09", category="boundary",
                  desc="Incident acknowledged between the query and the escalation",
                  expected="Not escalated")
def test_acknowledged_during_run_not_escalated(repo: FakeIncidentRepository,
                                               directory: FakeEscalationDirectory,
                                               settings: Settings, t0: datetime) -> None:
    inc = make_incident()
    repo.add(inc)
    job = build_escalation(repo, directory, settings)
    selected = list(job.select(t0 + minutes(6)))
    inc.status = Status.ACKNOWLEDGED  # technician acknowledges meanwhile
    job.select = lambda now: selected  # type: ignore[method-assign]
    assert job.run(t0 + minutes(6)).actions["escalated"] == 0
    assert inc.calls == []


@pytest.mark.case(id="TC-P4-10", category="boundary",
                  desc="Escalation chain exhausted",
                  expected="Flagged once; no further escalation")
def test_chain_exhausted_flagged_once(repo: FakeIncidentRepository,
                                      directory: FakeEscalationDirectory, settings: Settings,
                                      t0: datetime) -> None:
    inc = make_incident(PENDING_G15_escalation_level=3)
    repo.add(inc)
    r1 = run_escalation(t0 + minutes(10), repo, directory, settings)
    r2 = run_escalation(t0 + minutes(20), repo, directory, settings)
    assert (r1.actions["chain_exhausted"], r2.actions["chain_exhausted"]) == (1, 0)
    assert inc.calls == [("exhausted",)]


@pytest.mark.case(id="TC-P4-11", category="business-rule",
                  desc="Inactive user in the escalation chain",
                  expected="Skipped to the next active user")
def test_inactive_user_skipped(repo: FakeIncidentRepository, settings: Settings,
                               clock: FakeClock) -> None:
    directory = FakeEscalationDirectory([(TEAM_LEAD, False), (SYS_ADMIN, True), (IT_MANAGER, True)])
    inc = _inc(clock)
    repo.add(inc)
    clock.advance(minutes=6)
    run_escalation(clock.now(), repo, directory, settings)
    clock.advance(minutes=6)
    run_escalation(clock.now(), repo, directory, settings)
    # The level jumps to 2, so the next escalation goes to the IT Manager (G12).
    assert inc.calls == [("escalate", SYS_ADMIN, 2), ("escalate", IT_MANAGER, 3)]


@pytest.mark.parametrize("priority", [Priority.P3, Priority.P4])
def test_low_priority_never_escalates(priority: Priority, repo: FakeIncidentRepository,
                                      directory: FakeEscalationDirectory, settings: Settings,
                                      t0: datetime) -> None:
    inc = make_incident(priority=priority)
    repo.add(inc)
    run_escalation(t0 + minutes(600), repo, directory, settings)
    assert inc.calls == []
