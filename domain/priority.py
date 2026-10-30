from abc import ABC, abstractmethod

from domain.enums import Impact, Priority, Urgency
from domain.exceptions import ValidationError


def _validate(criticality, affected_users):
    if not 1 <= criticality <= 5:
        raise ValidationError("criticality must be between 1 and 5")
    if affected_users < 0:
        raise ValidationError("affected_users cannot be negative")


def clamp_urgency(impact, urgency):
    """Reporters inflate urgency, so it can be at most one level above impact."""
    return Urgency(min(urgency.value, impact.value + 1))


def _raise_priority(priority, levels):
    return Priority(max(Priority.P1.value, priority.value - levels))


class PriorityStrategy(ABC):
    @abstractmethod
    def calculate(self, impact, urgency, criticality, affected_users=0):
        ...


class MatrixPriorityStrategy(PriorityStrategy):
    """ITIL-style impact x urgency matrix, plus modifiers."""

    _MATRIX = {
        (Impact.HIGH, Urgency.HIGH): Priority.P1,
        (Impact.HIGH, Urgency.MEDIUM): Priority.P2,
        (Impact.HIGH, Urgency.LOW): Priority.P3,
        (Impact.MEDIUM, Urgency.HIGH): Priority.P2,
        (Impact.MEDIUM, Urgency.MEDIUM): Priority.P3,
        (Impact.MEDIUM, Urgency.LOW): Priority.P4,
        (Impact.LOW, Urgency.HIGH): Priority.P3,
        (Impact.LOW, Urgency.MEDIUM): Priority.P4,
        (Impact.LOW, Urgency.LOW): Priority.P4,
    }

    def __init__(self, criticality_threshold=4, users_threshold=50):
        self._criticality_threshold = criticality_threshold
        self._users_threshold = users_threshold

    def calculate(self, impact, urgency, criticality, affected_users=0):
        _validate(criticality, affected_users)
        urgency = clamp_urgency(impact, urgency)
        priority = self._MATRIX[(impact, urgency)]
        bump = 0
        if criticality >= self._criticality_threshold:
            bump += 1
        if affected_users >= self._users_threshold:
            bump += 1
        return _raise_priority(priority, bump)


class MultiplicativePriorityStrategy(PriorityStrategy):
    """Score = impact x urgency x criticality (max 3 x 3 x 5 = 45)."""

    _THRESHOLDS = [(27, Priority.P1), (12, Priority.P2), (5, Priority.P3)]

    def calculate(self, impact, urgency, criticality, affected_users=0):
        _validate(criticality, affected_users)
        urgency = clamp_urgency(impact, urgency)
        score = impact.value * urgency.value * criticality
        for minimum, priority in self._THRESHOLDS:
            if score >= minimum:
                return priority
        return Priority.P4