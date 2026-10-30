import pytest
from domain.incident import Incident
from domain.enums import Status
from domain.exceptions import InvalidStateTransitionError


def test_new_incident_stores_its_details():
    inc = Incident("INC1", "Payment app down")
    assert inc.incident_id == "INC1"
    assert inc.description == "Payment app down"


def test_new_incident_starts_as_new():
    inc = Incident("INC1", "Payment app down")
    assert inc.status == Status.NEW


def test_assign_changes_status_to_assigned():
    inc = Incident("INC1", "Payment app down")
    inc.assign()
    assert inc.status == Status.ASSIGNED


def test_cannot_assign_twice():
    inc = Incident("INC1", "Payment app down")
    inc.assign()
    with pytest.raises(InvalidStateTransitionError):
        inc.assign()


def test_unknown_status_text_is_rejected():
    with pytest.raises(ValueError):
        Status("NEWW")