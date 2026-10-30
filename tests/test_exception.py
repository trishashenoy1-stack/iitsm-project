from domain.exceptions import ITSMError, InvalidStateTransitionError


def test_specific_errors_are_kinds_of_itsm_error():
    assert issubclass(InvalidStateTransitionError, ITSMError)


def test_error_carries_its_message():
    error = InvalidStateTransitionError("bad move")
    assert str(error) == "bad move"