"""Pure escalation decision logic."""

from __future__ import annotations

from collections.abc import Mapping
from datetime import datetime, timedelta

from app.jobs.base import require_aware
from app.p4_contracts import UNACKNOWLEDGED_STATUSES, IncidentView
from domain.enums import Priority


class EscalationPolicy:
    def __init__(self, after_minutes: Mapping[str, int]) -> None:
        """after_minutes is keyed by priority name ("P1", "P2"), as in config."""
        if any(m <= 0 for m in after_minutes.values()):
            raise ValueError("escalation thresholds must be positive")
        self._after = {Priority[p]: timedelta(minutes=m) for p, m in after_minutes.items()}

    @property
    def priorities(self) -> frozenset[Priority]:
        return frozenset(self._after)

    def is_due(self, incident: IncidentView, now: datetime) -> bool:
        require_aware(now)
        if incident.priority is None:
            return False
        threshold = self._after.get(incident.priority)
        if threshold is None:
            return False
        # Status is authoritative: ASSIGNED -> ACKNOWLEDGED is the acknowledgment.
        if incident.status not in UNACKNOWLEDGED_STATUSES:
            return False
        since = incident.PENDING_G2_last_escalated_at or incident.PENDING_G13_created_at
        return now - since >= threshold
