import pytest
from domain.users import Employee, Technician
from domain.service import ITService
from domain.enums import Role
from domain.exceptions import (
    ValidationError,
    TechnicianUnavailableError,
    TechnicianWorkloadExceededError,
)


def test_technician_is_also_an_employee():
    tech = Technician("T1", "Ravi", {"network"})
    assert tech.has_role(Role.EMPLOYEE)
    assert tech.has_role(Role.TECHNICIAN)


def test_employee_is_not_a_technician():
    assert not Employee("E1", "Asha").has_role(Role.TECHNICIAN)


def test_empty_name_is_rejected():
    with pytest.raises(ValidationError):
        Employee("E1", "  ")


def test_skills_are_case_insensitive():
    assert Technician("T1", "Ravi", {"Network"}).has_skill("network")


def test_workload_limit_is_enforced():
    tech = Technician("T1", "Ravi", {"network"}, max_workload=1)
    tech.take_incident()
    with pytest.raises(TechnicianWorkloadExceededError):
        tech.take_incident()


def test_releasing_frees_capacity():
    tech = Technician("T1", "Ravi", {"network"}, max_workload=1)
    tech.take_incident()
    tech.release_incident()
    assert tech.can_take_more()


def test_unavailable_technician_cannot_take_incidents():
    tech = Technician("T1", "Ravi", {"network"})
    tech.set_available(False)
    with pytest.raises(TechnicianUnavailableError):
        tech.take_incident()


def test_deactivated_technician_is_unavailable():
    tech = Technician("T1", "Ravi", {"network"})
    tech.deactivate()
    assert not tech.is_available


def test_service_criticality_must_be_1_to_5():
    with pytest.raises(ValidationError):
        ITService("S1", "Payment", 6)


def test_service_stores_its_details():
    svc = ITService("S1", "Payment", 5)
    assert svc.name == "Payment"
    assert svc.criticality == 5