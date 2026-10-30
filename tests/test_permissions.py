from datetime import datetime, timezone
from types import SimpleNamespace

import pytest

from domain.clock import FakeClock
from domain.enums import Priority, Status
from domain.events import DomainEvent, EventBus, TransitionRejected
from domain.exceptions import UnauthorizedActionError
from domain.incident import Incident
from domain.permissions import check_permission
from domain.users import Administrator, Employee, Technician

BASE = datetime(2026, 11, 1, 10, 0, tzinfo=timezone.utc)


def make():
    clock = FakeClock(BASE)
    bus = EventBus()
    seen = []
    bus.subscribe(DomainEvent, seen.append)
    asha = Employee("E1", "Asha")
    bob = Employee("E2", "Bob")
    ravi = Technician("T1", "Ravi", {"network"})
    meera = Technician("T2", "Meera", {"network"})
    priya = Administrator("A1", "Priya")
    inc = Incident("INC1", "Payment app down", bus=bus, clock=clock, reporter=asha)
    return SimpleNamespace(
        inc=inc, seen=seen, asha=asha, bob=bob, ravi=ravi, meera=meera, priya=priya
    )


def to_resolved(c):
    c.inc.assign(actor=c.priya, technician=c.ravi)
    c.inc.acknowledge(actor=c.ravi)
    c.inc.start_work(actor=c.ravi)
    c.inc.resolve(actor=c.ravi)


def test_employee_cannot_classify():
    c = make()
    with pytest.raises(UnauthorizedActionError):
        c.inc.classify(actor=c.asha)
    assert c.inc.status == Status.NEW


def test_unauthorized_attempt_is_published_for_the_audit_log():
    c = make()
    with pytest.raises(UnauthorizedActionError):
        c.inc.classify(actor=c.asha)
    assert isinstance(c.seen[-1], TransitionRejected)
    assert c.seen[-1].attempted_action == "classify"
    assert c.seen[-1].actor is c.asha


def test_technician_and_admin_can_classify():
    c = make()
    c.inc.classify(actor=c.ravi)
    assert c.inc.status == Status.CLASSIFIED
    c2 = make()
    c2.inc.classify(actor=c2.priya)
    assert c2.inc.status == Status.CLASSIFIED


def test_employee_cannot_assign_but_admin_can():
    c = make()
    with pytest.raises(UnauthorizedActionError):
        c.inc.assign(actor=c.asha, technician=c.ravi)
    c.inc.assign(actor=c.priya, technician=c.ravi)
    assert c.inc.status == Status.ASSIGNED


def test_admin_cannot_acknowledge():
    c = make()
    c.inc.assign(actor=c.priya, technician=c.ravi)
    with pytest.raises(UnauthorizedActionError):
        c.inc.acknowledge(actor=c.priya)


def test_only_the_assigned_technician_can_acknowledge():
    c = make()
    c.inc.assign(actor=c.priya, technician=c.ravi)
    with pytest.raises(UnauthorizedActionError):
        c.inc.acknowledge(actor=c.meera)
    c.inc.acknowledge(actor=c.ravi)
    assert c.inc.status == Status.ACKNOWLEDGED


def test_technician_cannot_verify_their_own_resolution():
    c = make()
    to_resolved(c)
    with pytest.raises(UnauthorizedActionError):
        c.inc.verify(actor=c.ravi)


def test_other_employee_cannot_verify():
    c = make()
    to_resolved(c)
    with pytest.raises(UnauthorizedActionError):
        c.inc.verify(actor=c.bob)


def test_reporter_verifies_and_admin_closes():
    c = make()
    to_resolved(c)
    c.inc.verify(actor=c.asha)
    c.inc.close(actor=c.priya)
    assert c.inc.status == Status.CLOSED


def test_reporter_can_reject_resolution_and_work_restarts():
    c = make()
    to_resolved(c)
    c.inc.reject_resolution(actor=c.asha)
    assert c.inc.status == Status.REOPENED
    c.inc.start_work(actor=c.ravi)
    assert c.inc.status == Status.IN_PROGRESS


def test_other_employee_cannot_reject_resolution():
    c = make()
    to_resolved(c)
    with pytest.raises(UnauthorizedActionError):
        c.inc.reject_resolution(actor=c.bob)


def test_reporter_provides_info_but_technician_cannot():
    c = make()
    c.inc.assign(actor=c.priya, technician=c.ravi)
    c.inc.acknowledge(actor=c.ravi)
    c.inc.start_work(actor=c.ravi)
    c.inc.request_info(actor=c.ravi)
    with pytest.raises(UnauthorizedActionError):
        c.inc.provide_info(actor=c.ravi)
    c.inc.provide_info(actor=c.asha)
    assert c.inc.status == Status.IN_PROGRESS


def test_deactivated_technician_cannot_act():
    c = make()
    c.inc.assign(actor=c.priya, technician=c.ravi)
    c.ravi.deactivate()
    with pytest.raises(UnauthorizedActionError):
        c.inc.acknowledge(actor=c.ravi)


def test_employee_cannot_change_priority_but_technician_can():
    c = make()
    with pytest.raises(UnauthorizedActionError):
        c.inc.set_priority(Priority.P1, actor=c.asha)
    c.inc.set_priority(Priority.P1, actor=c.ravi, reason="Payment outage")
    assert c.inc.priority == Priority.P1


def test_system_can_do_automatic_actions():
    c = make()
    to_resolved(c)
    c.inc.verify(actor=c.asha)
    c.inc.close()  # no actor means the system, e.g. auto-close
    assert c.inc.status == Status.CLOSED


def test_unknown_action_fails_closed():
    c = make()
    with pytest.raises(UnauthorizedActionError):
        check_permission("fly", c.asha, c.inc)


def test_incident_without_reporter_denies_reporter_only_actions():
    inc = Incident("X", "no reporter")
    with pytest.raises(UnauthorizedActionError):
        inc.verify(actor=Employee("E1", "Asha"))


def test_users_are_matched_by_id_not_by_object_identity():
    c = make()
    to_resolved(c)
    same_person_reloaded = Employee("E1", "Asha")
    c.inc.verify(actor=same_person_reloaded)
    assert c.inc.status == Status.VERIFIED