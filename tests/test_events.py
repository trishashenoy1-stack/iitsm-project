from dataclasses import FrozenInstanceError
from datetime import datetime, timezone

import pytest

from domain.clock import FakeClock
from domain.enums import Priority, Status
from domain.events import (
    SYSTEM,
    DomainEvent,
    EventBus,
    IncidentAssigned,
    PriorityChanged,
    StatusChanged,
    TransitionRejected,
)
from domain.exceptions import InvalidStateTransitionError, ValidationError
from domain.incident import Incident
from domain.sla import SLAPolicy, SLATracker
from domain.users import Technician

BASE = datetime(2026, 11, 1, 10, 0, tzinfo=timezone.utc)


def make():
    clock = FakeClock(BASE)
    bus = EventBus()
    seen = []
    bus.subscribe(DomainEvent, seen.append)
    inc = Incident("INC1", "Payment app down", bus=bus, clock=clock)
    return clock, bus, seen, inc


def test_status_change_is_published():
    _, _, seen, inc = make()
    inc.assign()
    assert len(seen) == 1
    event = seen[0]
    assert isinstance(event, StatusChanged)
    assert event.previous_status == Status.NEW
    assert event.new_status == Status.ASSIGNED
    assert event.incident_id == "INC1"
    assert event.occurred_at == BASE


def test_default_actor_is_the_system():
    _, _, seen, inc = make()
    inc.assign()
    assert seen[0].actor is SYSTEM


def test_given_actor_is_recorded():
    _, _, seen, inc = make()
    ravi = Technician("T1", "Ravi", {"network"})
    inc.assign(actor=ravi)
    assert seen[0].actor is ravi


def test_rejected_transition_is_published_and_still_raises():
    _, _, seen, inc = make()
    with pytest.raises(InvalidStateTransitionError):
        inc.acknowledge()
    assert len(seen) == 1
    event = seen[0]
    assert isinstance(event, TransitionRejected)
    assert event.attempted_action == "acknowledge"
    assert event.current_status == Status.NEW


def test_assigning_to_a_technician_publishes_two_events_in_order():
    _, _, seen, inc = make()
    ravi = Technician("T1", "Ravi", {"network"})
    inc.assign(technician=ravi)
    assert [type(e) for e in seen] == [StatusChanged, IncidentAssigned]
    assert seen[1].technician_id == "T1"
    assert inc.technician is ravi


def test_subscribers_only_get_the_events_they_asked_for():
    _, bus, seen, inc = make()
    only_status = []
    bus.subscribe(StatusChanged, only_status.append)
    inc.assign(technician=Technician("T1", "Ravi", {"network"}))
    assert len(only_status) == 1
    assert len(seen) == 2


def test_a_failing_handler_does_not_stop_the_others_or_the_incident():
    _, bus, _, inc = make()

    def bad(event):
        raise RuntimeError("boom")

    later = []
    bus.subscribe(DomainEvent, bad)
    bus.subscribe(DomainEvent, later.append)
    inc.assign()
    assert inc.status == Status.ASSIGNED
    assert len(later) == 1


def test_incident_works_without_a_bus():
    inc = Incident("INC1", "Payment app down")
    inc.set_priority(Priority.P1)
    inc.assign()
    assert inc.status == Status.ASSIGNED
    assert inc.priority == Priority.P1


def test_bus_without_a_clock_is_rejected():
    with pytest.raises(ValidationError):
        Incident("INC1", "Payment app down", bus=EventBus())


def test_priority_change_is_published_with_reason():
    _, _, seen, inc = make()
    ravi = Technician("T1", "Ravi", {"network"})
    inc.set_priority(Priority.P1, actor=ravi, reason="Payment outage")
    event = seen[0]
    assert isinstance(event, PriorityChanged)
    assert event.previous_priority is None
    assert event.new_priority == Priority.P1
    assert event.reason == "Payment outage"
    assert event.actor is ravi


def test_same_priority_publishes_nothing():
    _, _, seen, inc = make()
    inc.set_priority(Priority.P2)
    inc.set_priority(Priority.P2)
    assert len(seen) == 1


def test_changing_priority_updates_the_sla():
    clock, _, _, inc = make()
    tracker = SLATracker(clock.now(), Priority.P4, SLAPolicy.default(), clock)
    inc.attach_sla(tracker)
    inc.set_priority(Priority.P1)
    assert tracker.priority == Priority.P1


def test_events_are_immutable():
    _, _, seen, inc = make()
    inc.assign()
    with pytest.raises(FrozenInstanceError):
        seen[0].incident_id = "HACKED"