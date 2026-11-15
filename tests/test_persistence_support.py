import json
from datetime import datetime, timedelta, timezone
from types import SimpleNamespace

import pytest

from domain.assignment import SkillBasedStrategy
from domain.clock import FakeClock
from domain.enums import Impact, Priority, Status, Urgency
from domain.events import DomainEvent, EventBus
from domain.exceptions import InvalidStateTransitionError, ValidationError
from domain.factory import IncidentFactory
from domain.incident import Feedback, Incident, InfoRequest, Note
from domain.priority import MatrixPriorityStrategy
from domain.service import ITService
from domain.sla import SLAEvent, SLAPolicy, SLATracker
from domain.users import Administrator, Employee, Technician

BASE = datetime(2026, 11, 1, 10, 0, tzinfo=timezone.utc)


def sla(priority=Priority.P1):
    clock = FakeClock(BASE)
    return clock, SLATracker(clock.now(), priority, SLAPolicy.default(), clock)


def reload(tracker, clock):
    """Pretend the app restarted: a new clock at the same moment, and a tracker
    rebuilt from its stored (JSON) snapshot."""
    fresh_clock = FakeClock(clock.now())
    data = json.loads(json.dumps(tracker.snapshot()))
    return fresh_clock, SLATracker.restore(data, SLAPolicy.default(), fresh_clock)


# ---------- Incident.restore ----------
@pytest.mark.parametrize("status", list(Status))
def test_restore_rebuilds_every_status(status):
    inc = Incident.restore("INC1", "Payment app down", status)
    assert inc.status == status


def test_restore_accepts_the_status_as_text():
    assert Incident.restore("INC1", "d", "RESOLVED").status == Status.RESOLVED


def test_restore_rejects_unknown_status():
    with pytest.raises(ValidationError):
        Incident.restore("INC1", "d", "BOGUS")


def test_restore_publishes_no_events():
    clock = FakeClock(BASE)
    bus = EventBus()
    seen = []
    bus.subscribe(DomainEvent, seen.append)
    Incident.restore(
        "INC1", "d", Status.IN_PROGRESS, bus=bus, clock=clock, created_at=BASE
    )
    assert seen == []


def test_restore_keeps_all_saved_values():
    asha = Employee("E1", "Asha")
    ravi = Technician("T1", "Ravi", {"network"})
    pay = ITService("S1", "Payment", 5)
    note = Note("T1", "Restarted gateway", BASE)
    feedback = Feedback(5, "Fast fix", BASE)
    asked = InfoRequest("Which browser?", "T1", BASE, "Chrome", "E1", BASE)
    resolved_at = BASE + timedelta(minutes=20)
    inc = Incident.restore(
        "INC9",
        "Payment app down",
        Status.RESOLVED,
        reporter=asha,
        service=pay,
        impact=Impact.HIGH,
        urgency=Urgency.HIGH,
        affected_users=120,
        priority=Priority.P1,
        technician=ravi,
        notes=[note],
        resolution="Restarted gateway",
        feedback=feedback,
        info_requests=[asked],
        created_at=BASE,
        resolved_at=resolved_at,
    )
    assert inc.incident_id == "INC9"
    assert inc.reporter is asha
    assert inc.service is pay
    assert inc.impact == Impact.HIGH
    assert inc.urgency == Urgency.HIGH
    assert inc.affected_users == 120
    assert inc.priority == Priority.P1
    assert inc.technician is ravi
    assert inc.notes == (note,)
    assert inc.resolution == "Restarted gateway"
    assert inc.feedback is feedback
    assert inc.info_requests == (asked,)
    assert inc.created_at == BASE
    assert inc.resolved_at == resolved_at
    assert inc.closed_at is None


def test_restored_incident_keeps_following_the_rules():
    inc = Incident.restore("INC1", "d", Status.IN_PROGRESS)
    inc.resolve(resolution="Restarted gateway")
    assert inc.status == Status.RESOLVED
    closed = Incident.restore("INC2", "d", Status.CLOSED)
    with pytest.raises(InvalidStateTransitionError):
        closed.assign()


def test_restore_rejects_naive_timestamps():
    with pytest.raises(ValidationError):
        Incident.restore("INC1", "d", Status.NEW, created_at=datetime(2026, 11, 1, 10, 0))


def test_restored_awaiting_info_incident_resumes_its_restored_sla():
    clock, tracker = sla()
    tracker.record_acknowledged()
    clock.advance(minutes=10)
    tracker.pause()
    clock.advance(minutes=20)
    fresh_clock, restored = reload(tracker, clock)
    inc = Incident.restore(
        "INC1", "d", Status.AWAITING_INFO,
        sla=restored, clock=fresh_clock, created_at=BASE,
    )
    inc.provide_info()
    assert not restored.is_paused
    assert restored.resolution_deadline() == BASE + timedelta(minutes=50)


# ---------- timestamps ----------
def test_created_at_comes_from_the_clock():
    assert Incident("INC1", "d", clock=FakeClock(BASE)).created_at == BASE


def test_incident_without_a_clock_has_no_timestamps():
    inc = Incident("INC1", "d")
    assert inc.created_at is None
    assert inc.resolved_at is None
    assert inc.closed_at is None


def test_resolved_and_closed_timestamps():
    clock = FakeClock(BASE)
    inc = Incident("INC1", "d", clock=clock)
    inc.assign()
    inc.acknowledge()
    inc.start_work()
    assert inc.resolved_at is None
    clock.advance(minutes=10)
    inc.resolve()
    assert inc.resolved_at == BASE + timedelta(minutes=10)
    inc.reject_resolution()
    assert inc.resolved_at is None
    inc.start_work()
    inc.resolve()
    inc.verify()
    clock.advance(minutes=5)
    inc.close()
    assert inc.closed_at == BASE + timedelta(minutes=15)


# ---------- text on info requests ----------
def info_incident():
    clock = FakeClock(BASE)
    asha = Employee("E1", "Asha")
    ravi = Technician("T1", "Ravi", {"network"})
    priya = Administrator("A1", "Priya")
    inc = Incident("INC1", "Payment app down", clock=clock, reporter=asha)
    inc.assign(actor=priya, technician=ravi)
    inc.acknowledge(actor=ravi)
    inc.start_work(actor=ravi)
    return SimpleNamespace(inc=inc, asha=asha, ravi=ravi)


def test_question_and_answer_are_stored():
    c = info_incident()
    c.inc.request_info(actor=c.ravi, question="  Which browser?  ")
    assert c.inc.status == Status.AWAITING_INFO
    request = c.inc.info_requests[0]
    assert request.question == "Which browser?"
    assert request.asked_by_id == "T1"
    assert request.asked_at == BASE
    assert request.answer is None

    c.inc.provide_info(actor=c.asha, answer="Chrome")
    assert c.inc.status == Status.IN_PROGRESS
    answered = c.inc.info_requests[0]
    assert answered.question == "Which browser?"
    assert answered.answer == "Chrome"
    assert answered.answered_by_id == "E1"


def test_info_requests_work_without_text_as_before():
    c = info_incident()
    c.inc.request_info(actor=c.ravi)
    c.inc.provide_info(actor=c.asha)
    assert c.inc.info_requests == ()


def test_blank_question_is_rejected_and_status_unchanged():
    c = info_incident()
    with pytest.raises(ValidationError):
        c.inc.request_info(actor=c.ravi, question="   ")
    assert c.inc.status == Status.IN_PROGRESS


def test_non_text_question_is_rejected():
    c = info_incident()
    with pytest.raises(ValidationError):
        c.inc.request_info(actor=c.ravi, question=42)
    assert c.inc.status == Status.IN_PROGRESS


def test_blank_answer_is_rejected_and_status_unchanged():
    c = info_incident()
    c.inc.request_info(actor=c.ravi, question="Which browser?")
    with pytest.raises(ValidationError):
        c.inc.provide_info(actor=c.asha, answer="  ")
    assert c.inc.status == Status.AWAITING_INFO


def test_answer_without_an_open_question_is_still_recorded():
    c = info_incident()
    c.inc.request_info(actor=c.ravi)
    c.inc.provide_info(actor=c.asha, answer="Chrome")
    assert len(c.inc.info_requests) == 1
    assert c.inc.info_requests[0].question == ""
    assert c.inc.info_requests[0].answer == "Chrome"


# ---------- SLA snapshot / restore ----------
def test_sla_snapshot_is_plain_json_data():
    _, tracker = sla()
    json.dumps(tracker.snapshot())


def test_paused_sla_survives_a_restart():
    clock, tracker = sla()
    tracker.record_acknowledged()
    clock.advance(minutes=10)
    tracker.pause()
    clock.advance(minutes=20)
    _, restored = reload(tracker, clock)
    assert restored.is_paused
    assert restored.resolution_deadline() == tracker.resolution_deadline()
    restored.resume()
    assert not restored.is_paused


def test_fired_warnings_do_not_fire_again_after_a_restart():
    clock, tracker = sla()
    clock.advance(minutes=4)
    assert tracker.evaluate() == [SLAEvent.RESPONSE_WARNING]
    fresh, restored = reload(tracker, clock)
    assert restored.evaluate() == []
    fresh.advance(minutes=2)
    assert restored.evaluate() == [SLAEvent.RESPONSE_BREACH]
    fresh2, again = reload(restored, fresh)
    assert again.evaluate() == []


def test_acknowledged_response_time_survives_a_restart():
    clock, tracker = sla()
    clock.advance(minutes=2)
    tracker.record_acknowledged()
    fresh, restored = reload(tracker, clock)
    fresh.advance(minutes=10)
    assert restored.evaluate() == []
    assert not restored.is_response_breached()


def test_restore_rejects_a_snapshot_with_missing_data():
    clock, tracker = sla()
    data = tracker.snapshot()
    del data["priority"]
    with pytest.raises(ValidationError):
        SLATracker.restore(data, SLAPolicy.default(), clock)


def test_restore_rejects_unknown_flags():
    clock, tracker = sla()
    data = tracker.snapshot()
    data["flags"] = ["NOT_A_FLAG"]
    with pytest.raises(ValidationError):
        SLATracker.restore(data, SLAPolicy.default(), clock)


def test_restore_rejects_a_naive_paused_at():
    clock, tracker = sla()
    data = tracker.snapshot()
    data["paused_at"] = "2026-11-01T10:00:00"
    with pytest.raises(ValidationError):
        SLATracker.restore(data, SLAPolicy.default(), clock)


def test_restore_rejects_negative_paused_time():
    clock, tracker = sla()
    data = tracker.snapshot()
    data["paused_total_seconds"] = -5
    with pytest.raises(ValidationError):
        SLATracker.restore(data, SLAPolicy.default(), clock)


# ---------- smaller changes ----------
def test_skill_based_falls_back_to_least_loaded_when_no_skill_is_given():
    a = Technician("A", "A", {"network"})
    a.take_incident()
    b = Technician("B", "B", {"database"})
    assert SkillBasedStrategy().select([a, b], None) is b
    assert SkillBasedStrategy().select([a, b], "") is b


def test_factory_warning_ratio_is_configurable():
    clock = FakeClock(BASE)
    factory = IncidentFactory(
        clock, EventBus(), MatrixPriorityStrategy(), SLAPolicy.default(),
        warning_ratio=0.5,
    )
    inc = factory.create(
        Employee("E1", "Asha"), ITService("S1", "Payment", 5), "x",
        Impact.HIGH, Urgency.HIGH,
    )
    clock.advance(minutes=3)
    assert inc.sla.evaluate() == [SLAEvent.RESPONSE_WARNING]


def test_factory_rejects_a_bad_warning_ratio():
    with pytest.raises(ValidationError):
        IncidentFactory(
            FakeClock(BASE), EventBus(), MatrixPriorityStrategy(),
            SLAPolicy.default(), warning_ratio=1.5,
        )


def test_technician_state_can_be_restored():
    tech = Technician("T1", "Ravi", {"network"}, max_workload=2)
    tech.restore_state(active_count=2, available=True, active=True)
    assert not tech.can_take_more()
    tech.restore_state(active_count=0, available=False, active=True)
    assert not tech.is_available


def test_technician_restore_rejects_negative_load():
    tech = Technician("T1", "Ravi", {"network"})
    with pytest.raises(ValidationError):
        tech.restore_state(-1)