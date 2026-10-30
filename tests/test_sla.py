from datetime import datetime, timedelta, timezone

import pytest

from domain.clock import FakeClock
from domain.enums import Priority
from domain.exceptions import (
    InvalidStateTransitionError,
    MissingSLAError,
    ValidationError,
)
from domain.incident import Incident
from domain.sla import SLAEvent, SLAPolicy, SLATracker

BASE = datetime(2026, 11, 1, 10, 0, tzinfo=timezone.utc)


def make(priority=Priority.P1, policy=None):
    clock = FakeClock(BASE)
    tracker = SLATracker(clock.now(), priority, policy or SLAPolicy.default(), clock)
    return clock, tracker


def test_p1_deadlines():
    _, t = make()
    assert t.response_deadline() == BASE + timedelta(minutes=5)
    assert t.resolution_deadline() == BASE + timedelta(minutes=30)


def test_no_events_at_creation():
    _, t = make()
    assert t.evaluate() == []


def test_response_warning_at_80_percent():
    clock, t = make()
    clock.advance(minutes=4)
    assert t.evaluate() == [SLAEvent.RESPONSE_WARNING]


def test_response_breach_after_deadline():
    clock, t = make()
    clock.advance(minutes=6)
    assert t.evaluate() == [SLAEvent.RESPONSE_BREACH]


def test_events_fire_only_once():
    clock, t = make()
    clock.advance(minutes=4)
    assert t.evaluate() == [SLAEvent.RESPONSE_WARNING]
    assert t.evaluate() == []


def test_late_evaluation_catches_up():
    clock, t = make()
    clock.advance(minutes=31)
    assert set(t.evaluate()) == {SLAEvent.RESPONSE_BREACH, SLAEvent.RESOLUTION_BREACH}
    assert t.evaluate() == []


def test_acknowledging_in_time_stops_response_events():
    clock, t = make()
    clock.advance(minutes=2)
    t.record_acknowledged()
    clock.advance(minutes=10)
    assert t.evaluate() == []


def test_acknowledging_late_is_a_breach():
    clock, t = make()
    clock.advance(minutes=6)
    t.record_acknowledged()
    assert t.is_response_breached()
    assert t.evaluate() == [SLAEvent.RESPONSE_BREACH]


def test_resolution_warning_at_80_percent():
    clock, t = make()
    t.record_acknowledged()
    clock.advance(minutes=24)
    assert t.evaluate() == [SLAEvent.RESOLUTION_WARNING]


def test_resolution_breach_after_deadline():
    clock, t = make()
    t.record_acknowledged()
    clock.advance(minutes=31)
    assert t.is_resolution_breached()
    assert t.evaluate() == [SLAEvent.RESOLUTION_BREACH]


def test_pause_and_resume_extend_the_deadline():
    clock, t = make()
    t.record_acknowledged()
    clock.advance(minutes=10)
    t.pause()
    clock.advance(minutes=20)
    t.resume()
    assert t.resolution_deadline() == BASE + timedelta(minutes=50)


def test_no_breach_while_paused():
    clock, t = make()
    t.record_acknowledged()
    clock.advance(minutes=10)
    t.pause()
    clock.advance(minutes=60)
    assert t.evaluate() == []
    assert not t.is_resolution_breached()


def test_pausing_twice_is_an_error():
    _, t = make()
    t.pause()
    with pytest.raises(InvalidStateTransitionError):
        t.pause()


def test_resuming_when_not_paused_is_an_error():
    _, t = make()
    with pytest.raises(InvalidStateTransitionError):
        t.resume()


def test_priority_change_recomputes_from_creation_time():
    clock, t = make(Priority.P4)
    t.record_acknowledged()
    clock.advance(hours=1)
    t.change_priority(Priority.P1)
    assert t.resolution_deadline() == BASE + timedelta(minutes=30)
    assert t.evaluate() == [SLAEvent.RESOLUTION_BREACH]


def test_missing_policy_falls_back_to_default():
    policy = SLAPolicy({Priority.P2: (timedelta(minutes=15), timedelta(hours=2))})
    _, t = make(Priority.P1, policy)
    assert t.used_default_policy
    assert t.response_deadline() == BASE + timedelta(minutes=5)


def test_policy_without_a_priority_raises():
    policy = SLAPolicy({})
    with pytest.raises(MissingSLAError):
        policy.targets_for(Priority.P1)


def test_naive_datetime_is_rejected():
    clock = FakeClock(BASE)
    with pytest.raises(ValidationError):
        SLATracker(datetime(2026, 11, 1, 10, 0), Priority.P1, SLAPolicy.default(), clock)


def test_resolved_incident_stops_resolution_events():
    clock, t = make()
    t.record_acknowledged()
    clock.advance(minutes=10)
    t.record_resolved()
    clock.advance(minutes=60)
    assert t.evaluate() == []
    assert not t.is_resolution_breached()


def test_awaiting_info_pauses_and_resumes_the_sla():
    clock, t = make()
    inc = Incident("INC1", "Payment app down")
    inc.attach_sla(t)
    inc.assign()
    inc.acknowledge()
    inc.start_work()
    inc.request_info()
    assert t.is_paused
    clock.advance(minutes=20)
    inc.provide_info()
    assert not t.is_paused
    assert t.resolution_deadline() == BASE + timedelta(minutes=50)


def test_reopened_incident_keeps_counting():
    clock, t = make()
    inc = Incident("INC1", "Payment app down")
    inc.attach_sla(t)
    inc.assign()
    inc.acknowledge()
    inc.start_work()
    clock.advance(minutes=10)
    inc.resolve()
    inc.reject_resolution()
    clock.advance(minutes=30)
    assert t.evaluate() == [SLAEvent.RESOLUTION_BREACH]