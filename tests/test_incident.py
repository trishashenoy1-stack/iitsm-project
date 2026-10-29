import pytest
from domain.incident import Incident


def test_new_incident_starts_as_new():
    inc = Incident("INC1", "Payment app down")
    assert inc.status == "NEW"


def test_assign_changes_status():
    inc = Incident("INC1", "Payment app down")
    inc.assign()
    assert inc.status == "ASSIGNED"


def test_cannot_assign_twice():
    inc = Incident("INC1", "Payment app down")
    inc.assign()
    with pytest.raises(Exception):
        inc.assign()