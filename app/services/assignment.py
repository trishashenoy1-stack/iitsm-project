"""Which of P1's assignment strategies is active, and running it (P2).

The admin switches strategy at runtime; the choice and the round-robin pointer are
stored in the settings table, so they survive restarts.
"""

from __future__ import annotations

from collections.abc import Callable
from typing import Any

from app.persistence.repositories import SettingsRepository
from domain.assignment import (
    AssignmentService,
    AssignmentStrategy,
    LoadBasedStrategy,
    RoundRobinStrategy,
    SkillBasedStrategy,
)
from domain.events import SYSTEM
from domain.exceptions import ValidationError

STRATEGY_KEY = "assignment_strategy"
ROUND_ROBIN_KEY = "round_robin_last_id"
DEFAULT_STRATEGY = "SKILL"

OPTIONS: list[dict[str, str]] = [
    {"id": "SKILL", "label": "Skill-based",
     "description": "Most experienced technician with the matching skill."},
    {"id": "LOAD", "label": "Load-based",
     "description": "Whoever has the fewest active incidents."},
    {"id": "ROUND_ROBIN", "label": "Round-robin",
     "description": "Technicians take turns in ID order."},
]

STRATEGIES: dict[str, tuple[Callable[[], AssignmentStrategy], str]] = {
    "SKILL": (SkillBasedStrategy, "skill-based strategy"),
    "LOAD": (LoadBasedStrategy, "load-based strategy"),
    "ROUND_ROBIN": (RoundRobinStrategy, "round-robin strategy"),
}


class AssignmentPolicy:
    def __init__(self, settings: SettingsRepository) -> None:
        self._settings = settings

    @property
    def current(self) -> str:
        value = self._settings.get(STRATEGY_KEY, DEFAULT_STRATEGY)
        return value if value in STRATEGIES else DEFAULT_STRATEGY

    def set_current(self, strategy_id: str) -> None:
        if strategy_id not in STRATEGIES:
            raise ValidationError("Choose a valid strategy.")
        self._settings.set(STRATEGY_KEY, strategy_id)

    def describe(self) -> dict[str, Any]:
        return {"current": self.current, "options": OPTIONS}

    def assign(self, incident: Any, technicians: list[Any]) -> tuple[Any, str]:
        """Assign with the active strategy; returns (technician, how it was chosen).

        Raises NoEligibleTechnicianError when nobody has capacity at all.
        """
        build, label = STRATEGIES[self.current]
        strategy = build()
        if isinstance(strategy, RoundRobinStrategy):
            strategy.set_state(self._settings.get(ROUND_ROBIN_KEY))
        skill = incident.category.name if incident.category is not None else None
        if isinstance(strategy, SkillBasedStrategy) and skill is None:
            # P1's skill strategy raises ValidationError without a skill ("Not sure"
            # category) instead of falling back. Use load-based straight away.
            strategy, label = LoadBasedStrategy(), "load-based strategy (no category)"

        technician = AssignmentService(strategy).assign(
            incident, technicians, required_skill=skill, actor=SYSTEM
        )
        if isinstance(strategy, SkillBasedStrategy) and not technician.has_skill(skill or ""):
            label = "load-based fallback (no skilled technician free)"
        if isinstance(strategy, RoundRobinStrategy):
            self._settings.set(ROUND_ROBIN_KEY, strategy.get_state())
        return technician, label
