import pytest
from domain.incident import Incident
from domain.enums import Status
from domain.exceptions import InvalidStateTransitionError

ALL_ACTIONS = [
    "classify", "assign", "acknowledge", "start_work", "request_info",
    "provide_info", "resolve", "verify", "reject_resolution", "close",
]

PATHS = {
    Status.NEW: [],
    Status.CLASSIFIED: ["classify"],
    Status.ASSIGNED: ["assign"],
    Status.ACKNOWLEDGED: ["assign", "acknowledge"],
    Status.IN_PROGRESS: ["assign", "acknowledge", "start_work"],
    Status.AWAITING_INFO: ["assign", "acknowledge", "start_work", "request_info"],
    Status.RESOLVED: ["assign", "acknowledge", "start_work", "resolve"],
    Status.VERIFIED: ["assign", "acknowledge", "start_work", "resolve", "verify"],
    Status.CLOSED: ["assign", "acknowledge", "start_work", "resolve", "verify", "close"],
    Status.REOPENED: ["assign", "acknowledge", "start_work", "resolve", "reject_resolution"],
}

LEGAL = {
    Status.NEW: {"classify", "assign"},
    Status.CLASSIFIED: {"assign"},
    Status.ASSIGNED: {"acknowledge"},
    Status.ACKNOWLEDGED: {"start_work"},
    Status.IN_PROGRESS: {"request_info", "resolve"},
    Status.AWAITING_INFO: {"provide_info"},
    Status.RESOLVED: {"verify", "reject_resolution"},
    Status.VERIFIED: {"close"},
    Status.CLOSED: set(),
    Status.REOPENED: {"start_work"},
}


def incident_in(status):
    inc = Incident("INC1", "Payment app down")
    for action in PATHS[status]:
        getattr(inc, action)()
    assert inc.status == status
    return inc


def test_full_happy_path():
    inc = Incident("INC1", "Payment app down")
    for action in ["classify", "assign", "acknowledge", "start_work",
                   "resolve", "verify", "close"]:
        getattr(inc, action)()
    assert inc.status == Status.CLOSED


def test_awaiting_info_round_trip():
    inc = incident_in(Status.IN_PROGRESS)
    inc.request_info()
    assert inc.status == Status.AWAITING_INFO
    inc.provide_info()
    assert inc.status == Status.IN_PROGRESS


def test_rejected_resolution_reopens_and_can_restart():
    inc = incident_in(Status.RESOLVED)
    inc.reject_resolution()
    assert inc.status == Status.REOPENED
    inc.start_work()
    assert inc.status == Status.IN_PROGRESS


def test_every_illegal_transition_is_refused():
    for status in Status:
        for action in ALL_ACTIONS:
            if action in LEGAL[status]:
                continue
            inc = incident_in(status)
            with pytest.raises(InvalidStateTransitionError):
                getattr(inc, action)()
            assert inc.status == status


def test_every_legal_transition_works():
    for status in Status:
        for action in LEGAL[status]:
            inc = incident_in(status)
            getattr(inc, action)()
            assert inc.status != status


def test_new_cannot_jump_to_closed():
    inc = Incident("INC1", "Payment app down")
    with pytest.raises(InvalidStateTransitionError):
        inc.close()


def test_error_message_names_the_current_stage():
    inc = Incident("INC1", "Payment app down")
    with pytest.raises(InvalidStateTransitionError) as error:
        inc.acknowledge()
    assert "NEW" in str(error.value)