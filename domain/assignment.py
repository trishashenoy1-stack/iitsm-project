from abc import ABC, abstractmethod

from domain.exceptions import NoEligibleTechnicianError, ValidationError


class AssignmentStrategy(ABC):
    @abstractmethod
    def select(self, technicians, required_skill=None):
        """Return the chosen technician, or raise NoEligibleTechnicianError."""

    @staticmethod
    def _eligible(technicians):
        return [t for t in technicians if t.can_take_more()]


class SkillBasedStrategy(AssignmentStrategy):
    """Skilled technicians only; most experienced first, then lighter load, then id."""

    def select(self, technicians, required_skill=None):
        if not required_skill:
            raise ValidationError("SkillBasedStrategy needs a required_skill")
        candidates = [
            t for t in self._eligible(technicians) if t.has_skill(required_skill)
        ]
        if not candidates:
            raise NoEligibleTechnicianError(
                f"No available technician with skill '{required_skill}'"
            )
        return min(
            candidates, key=lambda t: (-t.experience_years, t.active_count, t.user_id)
        )


class LoadBasedStrategy(AssignmentStrategy):
    """Least busy first, then most experienced, then id (deterministic)."""

    def select(self, technicians, required_skill=None):
        candidates = self._eligible(technicians)
        if not candidates:
            raise NoEligibleTechnicianError("No technician has spare capacity")
        return min(
            candidates, key=lambda t: (t.active_count, -t.experience_years, t.user_id)
        )


class RoundRobinStrategy(AssignmentStrategy):
    """Takes turns in id order. The pointer is the last chosen id, so it
    survives restarts (get_state/set_state) and a changing technician list."""

    def __init__(self):
        self._last_id = None

    def get_state(self):
        return self._last_id

    def set_state(self, last_id):
        self._last_id = last_id

    def select(self, technicians, required_skill=None):
        candidates = sorted(self._eligible(technicians), key=lambda t: t.user_id)
        if not candidates:
            raise NoEligibleTechnicianError("No technician has spare capacity")
        chosen = candidates[0]
        if self._last_id is not None:
            for t in candidates:
                if t.user_id > self._last_id:
                    chosen = t
                    break
        self._last_id = chosen.user_id
        return chosen


class AssignmentService:
    """Picks a technician with the current strategy and assigns the incident.
    The strategy can be swapped at runtime."""

    def __init__(self, strategy, fallback=None):
        self._strategy = strategy
        self._fallback = fallback if fallback is not None else LoadBasedStrategy()

    @property
    def strategy(self):
        return self._strategy

    def set_strategy(self, strategy):
        self._strategy = strategy

    def assign(self, incident, technicians, required_skill=None, actor=None):
        try:
            technician = self._strategy.select(technicians, required_skill)
        except NoEligibleTechnicianError:
            # fall back to load-based; raises again if nobody at all can take it
            technician = self._fallback.select(technicians, required_skill)
        incident.assign(actor=actor, technician=technician)
        technician.take_incident()
        return technician