import pytest

from domain.enums import Impact, Priority, Urgency
from domain.exceptions import ValidationError
from domain.priority import (
    MatrixPriorityStrategy,
    MultiplicativePriorityStrategy,
    PriorityStrategy,
)

matrix = MatrixPriorityStrategy()
mult = MultiplicativePriorityStrategy()


def test_matrix_high_high_is_p1():
    assert matrix.calculate(Impact.HIGH, Urgency.HIGH, 1) == Priority.P1


def test_matrix_high_medium_is_p2():
    assert matrix.calculate(Impact.HIGH, Urgency.MEDIUM, 1) == Priority.P2


def test_matrix_low_low_is_p4():
    assert matrix.calculate(Impact.LOW, Urgency.LOW, 1) == Priority.P4


def test_matrix_criticality_bumps_one_level():
    assert matrix.calculate(Impact.MEDIUM, Urgency.MEDIUM, 4) == Priority.P2


def test_matrix_many_users_bumps_one_level():
    assert matrix.calculate(Impact.MEDIUM, Urgency.MEDIUM, 1, 100) == Priority.P2


def test_matrix_both_bumps_stack():
    assert matrix.calculate(Impact.MEDIUM, Urgency.MEDIUM, 5, 100) == Priority.P1


def test_matrix_never_goes_above_p1():
    assert matrix.calculate(Impact.HIGH, Urgency.HIGH, 5, 100) == Priority.P1


def test_inflated_urgency_is_clamped():
    # LOW impact + HIGH urgency would be P3 unclamped; clamped to MEDIUM it is P4
    assert matrix.calculate(Impact.LOW, Urgency.HIGH, 1) == Priority.P4


def test_matrix_rejects_bad_criticality():
    with pytest.raises(ValidationError):
        matrix.calculate(Impact.HIGH, Urgency.HIGH, 0)


def test_matrix_rejects_negative_users():
    with pytest.raises(ValidationError):
        matrix.calculate(Impact.HIGH, Urgency.HIGH, 3, -1)


def test_multiplicative_big_outage_is_p1():
    assert mult.calculate(Impact.HIGH, Urgency.HIGH, 5) == Priority.P1


def test_multiplicative_boundary_27_is_p1():
    assert mult.calculate(Impact.HIGH, Urgency.HIGH, 3) == Priority.P1


def test_multiplicative_boundary_12_is_p2():
    assert mult.calculate(Impact.MEDIUM, Urgency.MEDIUM, 3) == Priority.P2


def test_multiplicative_just_below_12_is_p3():
    assert mult.calculate(Impact.MEDIUM, Urgency.MEDIUM, 2) == Priority.P3


def test_multiplicative_boundary_5_is_p3():
    assert mult.calculate(Impact.LOW, Urgency.LOW, 5) == Priority.P3


def test_multiplicative_just_below_5_is_p4():
    assert mult.calculate(Impact.LOW, Urgency.LOW, 4) == Priority.P4


def test_multiplicative_low_urgency_drags_a_big_outage_down():
    # the weakness to mention in the report: one low factor tanks the score
    assert mult.calculate(Impact.HIGH, Urgency.LOW, 5) == Priority.P2


def test_both_strategies_are_interchangeable():
    for strategy in (matrix, mult):
        assert isinstance(strategy, PriorityStrategy)
        assert isinstance(strategy.calculate(Impact.HIGH, Urgency.HIGH, 5), Priority)