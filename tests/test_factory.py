from datetime import datetime, timedelta, timezone

import pytest

from domain.assignment import AssignmentService, SkillBasedStrategy
from domain.clock import FakeClock
from domain.enums import Impact, Priority, Status, Urgency
from domain.events import (
    SYSTEM,
    DomainEvent,
    EventBus,
    IncidentAssigned,
    IncidentCreated,
    PriorityChanged,
    StatusChanged,
)
from domain.exceptions import (
    ServiceNotFoundError,
    UnauthorizedActionError,
    ValidationError,
)
from domain.factory import IncidentFactory
from domain.priority import MatrixPriorityStrategy, MultiplicativePriorityStrategy
from domain.service import ITService
from domain.sla import SLAPolicy
from domain.users import Administrator, Employee, Technician

BASE = datetime(2026, 11, 1, 10, 0, tzinfo=timezone.utc)


def make(strategy=None):
    clock = FakeClock(BASE)
    bus = EventBus()
    seen = []
    bus.subscribe(DomainEvent, seen.append)
    factory = IncidentFactory(
        clock, bus, strategy or MatrixPriorityStrategy(), SLAPolicy.default()
    )
    return clock, seen, factory


def test_creates_a_new_incident_with_details():
    _, _, factory = make()
    asha = Employee("E1", "Asha")
    pay = ITService("S1", "Payment", 5)
    inc = factory.create(asha, pay, "Payment app down", Impact.HIGH, Urgency.HIGH)
    assert inc.incident_id == "INC1001"
    assert inc.status == Status.NEW
    assert inc.reporter is asha
    assert inc.service is pay


def test_priority_is_calculated_automatically():
    _, _, factory = make()
    inc = factory.create(
        Employee("E1", "Asha"),
        ITService("S1", "Payment", 5),
        "Payment app down",
        Impact.HIGH,
        Urgency.HIGH,
    )
    assert inc.priority == Priority.P1


def test_sla_is_attached_with_the_right_deadlines():
    _, _, factory = make()
    inc = factory.create(
        Employee("E1", "Asha"),
        ITService("S1", "Payment", 5),
        "Payment app down",
        Impact.HIGH,
        Urgency.HIGH,
    )
    assert inc.sla.response_deadline() == BASE + timedelta(minutes=5)
    assert inc.sla.resolution_deadline() == BASE + timedelta(minutes=30)


def test_ids_are_sequential():
    _, _, factory = make()
    asha = Employee("E1", "Asha")
    pay = ITService("S1", "Payment", 5)
    first = factory.create(asha, pay, "one", Impact.LOW, Urgency.LOW)
    second = factory.create(asha, pay, "two", Impact.LOW, Urgency.LOW)
    assert (first.incident_id, second.incident_id) == ("INC1001", "INC1002")


def test_created_then_priority_events_are_published_in_order():
    _, seen, factory = make()
    asha = Employee("E1", "Asha")
    factory.create(
        asha,
        ITService("S1", "Payment", 5),
        "Payment app down",
        Impact.HIGH,
        Urgency.HIGH,
    )
    assert [type(e) for e in seen] == [IncidentCreated, PriorityChanged]
    assert seen[0].actor is asha
    assert seen[1].new_priority == Priority.P1
    assert seen[1].actor is SYSTEM


def test_inactive_service_is_rejected_and_no_id_is_used_up():
    _, _, factory = make()
    asha = Employee("E1", "Asha")
    dead = ITService("S9", "Old", 3)
    dead.deactivate()
    with pytest.raises(ServiceNotFoundError):
        factory.create(asha, dead, "x", Impact.LOW, Urgency.LOW)
    ok = factory.create(
        asha, ITService("S1", "Payment", 5), "x", Impact.LOW, Urgency.LOW
    )
    assert ok.incident_id == "INC1001"


def test_missing_service_is_rejected():
    _, _, factory = make()
    with pytest.raises(ServiceNotFoundError):
        factory.create(Employee("E1", "Asha"), None, "x", Impact.LOW, Urgency.LOW)


def test_inactive_reporter_is_rejected():
    _, _, factory = make()
    asha = Employee("E1", "Asha")
    asha.deactivate()
    with pytest.raises(UnauthorizedActionError):
        factory.create(
            asha, ITService("S1", "Payment", 5), "x", Impact.LOW, Urgency.LOW
        )


@pytest.mark.parametrize("bad", ["", "   ", None, "x" * 2001])
def test_bad_descriptions_are_rejected(bad):
    _, _, factory = make()
    with pytest.raises(ValidationError):
        factory.create(
            Employee("E1", "Asha"),
            ITService("S1", "Payment", 5),
            bad,
            Impact.LOW,
            Urgency.LOW,
        )


def test_description_at_the_limit_is_accepted_and_trimmed():
    _, _, factory = make()
    asha = Employee("E1", "Asha")
    pay = ITService("S1", "Payment", 5)
    assert factory.create(asha, pay, "x" * 2000, Impact.LOW, Urgency.LOW)
    inc = factory.create(asha, pay, "  Payment app down  ", Impact.LOW, Urgency.LOW)
    assert inc.description == "Payment app down"


def test_wrong_impact_type_is_rejected():
    _, _, factory = make()
    with pytest.raises(ValidationError):
        factory.create(
            Employee("E1", "Asha"),
            ITService("S1", "Payment", 5),
            "x",
            "HIGH",
            Urgency.HIGH,
        )


def test_priority_strategy_can_be_swapped():
    _, _, factory = make()
    asha = Employee("E1", "Asha")
    billing = ITService("S2", "Billing", 3)
    first = factory.create(asha, billing, "x", Impact.MEDIUM, Urgency.MEDIUM)
    assert first.priority == Priority.P3
    factory.set_priority_strategy(MultiplicativePriorityStrategy())
    second = factory.create(asha, billing, "x", Impact.MEDIUM, Urgency.MEDIUM)
    assert second.priority == Priority.P2


def test_many_affected_users_raise_the_priority():
    _, _, factory = make()
    asha = Employee("E1", "Asha")
    svc = ITService("S3", "Wiki", 1)
    few = factory.create(asha, svc, "x", Impact.HIGH, Urgency.MEDIUM, 0)
    many = factory.create(asha, svc, "x", Impact.HIGH, Urgency.MEDIUM, 100)
    assert few.priority == Priority.P2
    assert many.priority == Priority.P1


def test_full_report_to_assignment_workflow():
    _, seen, factory = make()
    asha = Employee("E102", "Asha")
    priya = Administrator("A1", "Priya")
    ravi = Technician("T205", "Ravi", {"payment"}, 6)
    inc = factory.create(
        asha,
        ITService("S1", "Payment", 5),
        "Payment app unavailable",
        Impact.HIGH,
        Urgency.HIGH,
        120,
    )
    inc.classify()
    chosen = AssignmentService(SkillBasedStrategy()).assign(
        inc, [ravi], "payment", actor=priya
    )
    assert chosen is ravi
    assert inc.status == Status.ASSIGNED
    assert ravi.active_count == 1
    assert [type(e) for e in seen] == [
        IncidentCreated,
        PriorityChanged,
        StatusChanged,
        StatusChanged,
        IncidentAssigned,
    ]