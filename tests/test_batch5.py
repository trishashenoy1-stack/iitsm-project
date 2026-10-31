from datetime import datetime, timezone
from types import SimpleNamespace

import pytest

from domain.assignment import AssignmentService, LoadBasedStrategy
from domain.category import CategoryRegistry
from domain.clock import FakeClock
from domain.enums import Impact, Status, Urgency
from domain.events import SYSTEM, EventBus, SLABreached, SLAWarning
from domain.exceptions import (
    InvalidStateTransitionError,
    UnauthorizedActionError,
    ValidationError,
)
from domain.factory import IncidentFactory
from domain.incident import Incident
from domain.priority import MatrixPriorityStrategy
from domain.service import ITService
from domain.sla import SLAEvent, SLAPolicy
from domain.sla_monitor import SLAMonitor
from domain.users import Administrator, Employee, Technician

BASE = datetime(2026, 11, 1, 10, 0, tzinfo=timezone.utc)


def setup():
    clock = FakeClock(BASE)
    c = SimpleNamespace(
        clock=clock,
        asha=Employee("E1", "Asha"),
        bob=Employee("E2", "Bob"),
        ravi=Technician("T1", "Ravi", {"network"}),
        meera=Technician("T2", "Meera", {"network"}),
        priya=Administrator("A1", "Priya"),
    )
    c.inc = Incident("INC1", "Payment app down", clock=clock, reporter=c.asha)
    return c


def work(c):
    c.inc.assign(actor=c.priya, technician=c.ravi)
    c.inc.acknowledge(actor=c.ravi)
    c.inc.start_work(actor=c.ravi)


def resolved(c, text=None):
    work(c)
    c.inc.resolve(actor=c.ravi, resolution=text)


def closed(c):
    resolved(c)
    c.inc.verify(actor=c.asha)
    c.inc.close(actor=c.priya)


# ---------- categories ----------
def test_default_categories_exist_and_lookup_ignores_case():
    registry = CategoryRegistry.default()
    assert registry.get("network").name == "NETWORK"


def test_admin_can_add_a_new_category():
    registry = CategoryRegistry.default()
    registry.add("Printing")
    assert "PRINTING" in [c.name for c in registry.active()]


def test_duplicate_category_is_rejected():
    registry = CategoryRegistry.default()
    with pytest.raises(ValidationError):
        registry.add("NETWORK")


def test_unknown_category_is_rejected():
    with pytest.raises(ValidationError):
        CategoryRegistry.default().get("Nope")


def test_deactivated_category_is_not_listed():
    registry = CategoryRegistry.default()
    registry.deactivate("Cloud")
    assert "CLOUD" not in [c.name for c in registry.active()]


def test_empty_category_name_is_rejected():
    with pytest.raises(ValidationError):
        CategoryRegistry().add("   ")


# ---------- workload release ----------
def test_closing_releases_the_technicians_capacity():
    c = setup()
    AssignmentService(LoadBasedStrategy()).assign(c.inc, [c.ravi], actor=c.priya)
    assert c.ravi.active_count == 1
    c.inc.acknowledge(actor=c.ravi)
    c.inc.start_work(actor=c.ravi)
    c.inc.resolve(actor=c.ravi)
    assert c.ravi.active_count == 1
    c.inc.verify(actor=c.asha)
    c.inc.close(actor=c.priya)
    assert c.ravi.active_count == 0


# ---------- notes ----------
def test_assigned_technician_can_add_a_note():
    c = setup()
    work(c)
    c.inc.add_note("Restarted the gateway", actor=c.ravi)
    assert len(c.inc.notes) == 1
    assert c.inc.notes[0].text == "Restarted the gateway"
    assert c.inc.notes[0].author_id == "T1"
    assert c.inc.notes[0].created_at == BASE


def test_other_technician_cannot_add_a_note():
    c = setup()
    work(c)
    with pytest.raises(UnauthorizedActionError):
        c.inc.add_note("hi", actor=c.meera)


def test_employee_cannot_add_a_note():
    c = setup()
    work(c)
    with pytest.raises(UnauthorizedActionError):
        c.inc.add_note("hi", actor=c.asha)


def test_empty_note_is_rejected():
    c = setup()
    work(c)
    with pytest.raises(ValidationError):
        c.inc.add_note("   ", actor=c.ravi)


def test_no_notes_on_a_closed_incident():
    c = setup()
    closed(c)
    with pytest.raises(InvalidStateTransitionError):
        c.inc.add_note("late note", actor=c.ravi)


def test_notes_cannot_be_edited_from_outside():
    c = setup()
    work(c)
    c.inc.add_note("one", actor=c.ravi)
    assert isinstance(c.inc.notes, tuple)


# ---------- resolution text ----------
def test_resolution_text_is_stored():
    c = setup()
    resolved(c, "  Restarted the payment gateway  ")
    assert c.inc.resolution == "Restarted the payment gateway"


def test_empty_resolution_text_is_rejected_and_status_unchanged():
    c = setup()
    work(c)
    with pytest.raises(ValidationError):
        c.inc.resolve(actor=c.ravi, resolution="   ")
    assert c.inc.status == Status.IN_PROGRESS


# ---------- feedback ----------
def test_reporter_can_give_feedback_after_resolution():
    c = setup()
    resolved(c)
    c.inc.submit_feedback(c.asha, 5, "Fast fix")
    assert c.inc.feedback.rating == 5
    assert c.inc.feedback.comment == "Fast fix"


def test_feedback_before_resolution_is_rejected():
    c = setup()
    work(c)
    with pytest.raises(InvalidStateTransitionError):
        c.inc.submit_feedback(c.asha, 5)


def test_feedback_can_only_be_given_once():
    c = setup()
    resolved(c)
    c.inc.submit_feedback(c.asha, 4)
    with pytest.raises(ValidationError):
        c.inc.submit_feedback(c.asha, 5)


def test_other_people_cannot_give_feedback():
    c = setup()
    resolved(c)
    with pytest.raises(UnauthorizedActionError):
        c.inc.submit_feedback(c.bob, 5)
    with pytest.raises(UnauthorizedActionError):
        c.inc.submit_feedback(c.ravi, 5)


def test_feedback_needs_an_actor():
    c = setup()
    resolved(c)
    with pytest.raises(UnauthorizedActionError):
        c.inc.submit_feedback(None, 5)


@pytest.mark.parametrize("bad", [0, 6, -1, 3.5, "5", True])
def test_bad_ratings_are_rejected(bad):
    c = setup()
    resolved(c)
    with pytest.raises(ValidationError):
        c.inc.submit_feedback(c.asha, bad)


# ---------- factory stores the new fields ----------
def make_factory(registry=None):
    clock = FakeClock(BASE)
    bus = EventBus()
    factory = IncidentFactory(
        clock, bus, MatrixPriorityStrategy(), SLAPolicy.default(),
        category_registry=registry,
    )
    return clock, bus, factory


def test_factory_stores_category_impact_urgency_and_users():
    _, _, factory = make_factory(CategoryRegistry.default())
    inc = factory.create(
        Employee("E1", "Asha"),
        ITService("S1", "Payment", 5),
        "Payment app down",
        Impact.HIGH,
        Urgency.HIGH,
        120,
        category="application",
    )
    assert inc.category.name == "APPLICATION"
    assert inc.impact == Impact.HIGH
    assert inc.urgency == Urgency.HIGH
    assert inc.affected_users == 120


def test_factory_rejects_unknown_category():
    _, _, factory = make_factory(CategoryRegistry.default())
    with pytest.raises(ValidationError):
        factory.create(
            Employee("E1", "Asha"), ITService("S1", "P", 5), "x",
            Impact.LOW, Urgency.LOW, category="Nope",
        )


def test_factory_rejects_inactive_category():
    registry = CategoryRegistry.default()
    registry.deactivate("Cloud")
    _, _, factory = make_factory(registry)
    with pytest.raises(ValidationError):
        factory.create(
            Employee("E1", "Asha"), ITService("S1", "P", 5), "x",
            Impact.LOW, Urgency.LOW, category="Cloud",
        )


def test_factory_rejects_a_category_without_a_registry():
    _, _, factory = make_factory(None)
    with pytest.raises(ValidationError):
        factory.create(
            Employee("E1", "Asha"), ITService("S1", "P", 5), "x",
            Impact.LOW, Urgency.LOW, category="Cloud",
        )


# ---------- SLA monitor ----------
def monitored():
    clock, bus, factory = make_factory()
    seen = []
    bus.subscribe(SLAWarning, seen.append)
    bus.subscribe(SLABreached, seen.append)
    inc = factory.create(
        Employee("E1", "Asha"),
        ITService("S1", "Payment", 5),
        "Payment app down",
        Impact.HIGH,
        Urgency.HIGH,
    )
    return clock, seen, inc, SLAMonitor(bus, clock)


def test_monitor_publishes_a_warning_once():
    clock, seen, inc, monitor = monitored()
    clock.advance(minutes=4)
    assert monitor.check(inc) == [SLAEvent.RESPONSE_WARNING]
    assert monitor.check(inc) == []
    assert len(seen) == 1
    assert isinstance(seen[0], SLAWarning)
    assert seen[0].actor is SYSTEM
    assert seen[0].incident_id == inc.incident_id


def test_monitor_publishes_a_breach():
    clock, seen, inc, monitor = monitored()
    clock.advance(minutes=6)
    monitor.check(inc)
    assert isinstance(seen[0], SLABreached)
    assert seen[0].sla_event == SLAEvent.RESPONSE_BREACH


def test_monitor_ignores_incidents_without_an_sla():
    clock, seen, _, monitor = monitored()
    assert monitor.check(Incident("X", "no sla")) == []
    assert seen == []


def test_monitor_check_all_covers_every_incident():
    clock, seen, inc, monitor = monitored()
    clock.advance(minutes=6)
    assert monitor.check_all([inc, inc]) == [SLAEvent.RESPONSE_BREACH]