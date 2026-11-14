"""The audit journal: one Step per thing that happened to an incident (P2).

Steps come from two places:
  * domain events (StatusChanged, IncidentAssigned, PriorityChanged, ...), turned into
    steps by ``IncidentJournal.record``;
  * actions P1's events don't describe in full (note text, resolution text, feedback,
    the text of an information request), added by the application services.

The same steps are the audit trail shown to admins, the history shown on an incident,
and the input the repository replays to rebuild an incident (replay.py).
"""

from __future__ import annotations

from collections.abc import Iterable
from dataclasses import dataclass, field
from datetime import datetime
from typing import Any

from app.db.models import IncidentEventRecord
from app.persistence.events import EscalationExhausted, IncidentEscalated
from domain.enums import Status
from domain.events import (
    IncidentAssigned,
    IncidentCreated,
    PriorityChanged,
    SLABreached,
    SLAWarning,
    StatusChanged,
    TransitionRejected,
)

# P1's StatusChanged doesn't name the action, but each (from, to) pair has exactly one.
ACTION_FOR_TRANSITION: dict[tuple[Status | None, Status], str] = {
    (Status.NEW, Status.CLASSIFIED): "classify",
    (Status.NEW, Status.ASSIGNED): "assign",
    (Status.CLASSIFIED, Status.ASSIGNED): "assign",
    (Status.ASSIGNED, Status.ACKNOWLEDGED): "acknowledge",
    (Status.ACKNOWLEDGED, Status.IN_PROGRESS): "start_work",
    (Status.REOPENED, Status.IN_PROGRESS): "start_work",
    (Status.IN_PROGRESS, Status.AWAITING_INFO): "request_info",
    (Status.AWAITING_INFO, Status.IN_PROGRESS): "provide_info",
    (Status.IN_PROGRESS, Status.RESOLVED): "resolve",
    (Status.RESOLVED, Status.VERIFIED): "verify",
    (Status.RESOLVED, Status.REOPENED): "reject_resolution",
    (Status.VERIFIED, Status.CLOSED): "close",
}

# Entries that are written even when the transaction that produced them rolls back.
SURVIVES_ROLLBACK = frozenset({"rejected"})


@dataclass
class Step:
    incident_id: str | None
    at: datetime
    actor_id: str
    action: str
    previous_status: str | None = None
    new_status: str | None = None
    internal: bool = False
    payload: dict[str, Any] = field(default_factory=dict)
    seq: int = 0  # database id once stored; orders steps that share a timestamp

    @property
    def description(self) -> str:
        return describe(self)

    @classmethod
    def of(cls, record: IncidentEventRecord) -> Step:
        return cls(
            incident_id=record.incident_id,
            at=record.at,
            actor_id=record.actor_id,
            action=record.action,
            previous_status=record.previous_status,
            new_status=record.new_status,
            internal=record.internal,
            payload=dict(record.payload or {}),
            seq=record.id,
        )

    def to_record(self) -> IncidentEventRecord:
        return IncidentEventRecord(
            incident_id=self.incident_id,
            at=self.at,
            actor_id=self.actor_id,
            action=self.action,
            description=self.description,
            previous_status=self.previous_status,
            new_status=self.new_status,
            internal=self.internal,
            payload=self.payload,
        )


def ordered(steps: Iterable[Step]) -> list[Step]:
    """Insertion order (database id), not timestamps: a clock that steps back (NTP) or
    two steps in the same microsecond must never reorder an incident's history."""
    return sorted(steps, key=lambda s: s.seq)


def _actor_id(actor: Any) -> str:
    return getattr(actor, "user_id", None) or "SYSTEM"


class IncidentJournal:
    """Collects the steps of one unit of work until it commits."""

    def __init__(self) -> None:
        self._pending: list[Step] = []
        self._counter = 0

    @property
    def pending(self) -> list[Step]:
        return list(self._pending)

    def pending_for(self, incident_id: str) -> list[Step]:
        return [s for s in self._pending if s.incident_id == incident_id]

    def add(self, step: Step) -> Step:
        # Pending steps sort after stored ones that share a timestamp, in arrival order.
        self._counter += 1
        step.seq = 10**12 + self._counter
        self._pending.append(step)
        return step

    def annotate(self, incident_id: str, action: str, **payload: Any) -> None:
        """Add detail to the latest pending step of this action (e.g. resolution text)."""
        for step in reversed(self._pending):
            if step.incident_id == incident_id and step.action == action:
                step.payload.update(payload)
                return
        raise LookupError(f"No pending {action} step for {incident_id}")

    def take_all(self) -> list[Step]:
        steps, self._pending = self._pending, []
        return steps

    def take_surviving(self) -> list[Step]:
        steps = [s for s in self._pending if s.action in SURVIVES_ROLLBACK]
        self._pending = []
        return steps

    # ---- domain events -> steps --------------------------------------------------
    def record(self, event: Any) -> None:
        step = self._step_for(event)
        if step is not None:
            self.add(step)

    def _step_for(self, event: Any) -> Step | None:
        base = {"incident_id": event.incident_id, "at": event.occurred_at,
                "actor_id": _actor_id(event.actor)}
        if isinstance(event, IncidentCreated):
            return Step(**base, action="created", new_status=Status.NEW.value)
        if isinstance(event, StatusChanged):
            action = ACTION_FOR_TRANSITION.get((event.previous_status, event.new_status))
            return Step(**base, action=action or "status_changed",
                        previous_status=event.previous_status.value,
                        new_status=event.new_status.value)
        if isinstance(event, IncidentAssigned):
            # assign() publishes StatusChanged first, then this: attach the technician.
            try:
                self.annotate(event.incident_id, "assign", technician_id=event.technician_id)
            except LookupError:
                return Step(**base, action="assign", payload={"technician_id": event.technician_id})
            return None
        if isinstance(event, PriorityChanged):
            return Step(**base, action="set_priority", payload={
                "priority": event.new_priority.name,
                "previous": event.previous_priority.name if event.previous_priority else None,
                "reason": event.reason,
            })
        if isinstance(event, TransitionRejected):
            return Step(**base, action="rejected", payload={
                "attempted_action": event.attempted_action, "reason": event.reason,
                "status": event.current_status.value,
            })
        if isinstance(event, SLAWarning | SLABreached):
            kind = "sla_breach" if isinstance(event, SLABreached) else "sla_warning"
            return Step(**base, action=kind, payload={"sla_event": event.sla_event.value})
        if isinstance(event, IncidentEscalated):
            return Step(**base, action="escalated",
                        payload={"to_user_id": event.to_user_id, "level": event.level})
        if isinstance(event, EscalationExhausted):
            return Step(**base, action="escalation_exhausted")
        return None


_SLA_TEXT = {
    "RESPONSE_WARNING": "SLA warning: response deadline is close",
    "RESOLUTION_WARNING": "SLA warning: resolution deadline is close",
    "RESPONSE_BREACH": "SLA breached: no response in time",
    "RESOLUTION_BREACH": "SLA breached: not resolved in time",
}


def describe(step: Step) -> str:
    """The sentence shown in history and in the audit log."""
    p, who = step.payload, step.actor_id
    text = {
        "created": f"Created by {who}",
        "classify": f"Classified as {p.get('category') or 'uncategorised'}",
        "assign": f"Assigned to {p.get('technician_id', '?')}"
                  + (f" by {p['via']}" if p.get("via") else f" by {who}"),
        "acknowledge": f"Acknowledged by {who}",
        "start_work": "Investigation started",
        "request_info": f"Requested information: {p.get('message', '')}".strip(),
        "provide_info": f"{who} replied: {p.get('message', '')}".strip(),
        "resolve": f"Marked resolved: {p.get('resolution', '')}".strip(),
        "verify": f"Resolution verified by {who}",
        "reject_resolution": f"Resolution rejected by {who}",
        "close": f"Closed by {who}",
        "set_priority": f"Priority set to {p.get('priority')}"
                        + (f" ({p['reason']})" if p.get("reason") else ""),
        "add_note": f"Note: {p.get('text', '')}",
        "add_information": f"{who} added information: {p.get('text', '')}",
        "submit_feedback": f"Feedback submitted: {p.get('rating')} out of 5",
        "sla_warning": _SLA_TEXT.get(p.get("sla_event", ""), "SLA warning"),
        "sla_breach": _SLA_TEXT.get(p.get("sla_event", ""), "SLA breached"),
        "escalated": f"Escalated to {p.get('to_user_id')} (level {p.get('level')})",
        "escalation_exhausted": "Escalation chain exhausted",
        "rejected": f"Refused {p.get('attempted_action', 'action')}: {p.get('reason', '')}",
        "assign_failed": "No technician has spare capacity. Waiting for an administrator.",
        "possible_duplicate": f"Possible duplicate of {p.get('other_id')}"
                              f" ({round(100 * float(p.get('score', 0)))}% match)",
        "suggested_category": f"Suggested category {p.get('category')}"
                              f" ({round(100 * float(p.get('confidence', 0)))}% confident)",
    }.get(step.action)
    return text or step.action.replace("_", " ").capitalize()
