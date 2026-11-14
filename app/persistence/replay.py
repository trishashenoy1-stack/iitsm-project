"""Rebuild a P1 Incident from its stored audit trail (P2).

P1 has no Incident.restore() yet (gap G20). Instead of writing P1's private fields,
the repository creates a fresh Incident and replays every recorded step through P1's
own public methods, at the time it originally happened:

    created -> set_priority -> classify -> assign -> acknowledge -> ...

So the state machine, SLA pause/resume and "warn/breach once" flags all come out the
way P1's code computes them, and there is only one copy of the lifecycle rules. Every
step is replayed as the SYSTEM actor because the permission check already passed when
the step first happened.

When P1 ships restore(), only this module changes.
"""

from __future__ import annotations

from collections.abc import Callable, Iterable
from dataclasses import dataclass
from datetime import datetime, timedelta
from typing import Any

from app.p4_contracts import UNACKNOWLEDGED_STATUSES
from app.persistence.events import (
    EscalationExhausted,
    IncidentEscalated,
    ReplayClock,
    TransactionalEventBus,
)
from app.persistence.journal import Step, ordered
from domain.clock import Clock
from domain.enums import Impact, Priority, Status, Urgency
from domain.events import SYSTEM
from domain.exceptions import InvalidStateTransitionError
from domain.incident import Incident
from domain.sla import SLAPolicy, SLATracker

LIFECYCLE_ACTIONS = frozenset({
    "classify", "acknowledge", "start_work", "request_info", "provide_info",
    "verify", "reject_resolution", "close",
})


class ReplayError(RuntimeError):
    """The stored trail can't be replayed (a bug, or the data was edited by hand)."""


@dataclass(frozen=True)
class IncidentInputs:
    """The fields set once, when the incident was reported."""

    incident_id: str
    description: str
    created_at: datetime
    reporter: Any
    service: Any
    category: Any
    impact: Impact
    urgency: Urgency
    affected_users: int


class PersistedIncident:
    """P1's Incident plus the facts only the database knows (Proxy).

    Everything P1 defines (status, assign(), resolve(), ...) is forwarded unchanged.
    The extra properties are the ones P4 asked P1 for (PENDING_G1/G2/G13/G14/G15);
    they live here until P1 adds them to Incident.
    """

    def __init__(self, incident: Incident, created_at: datetime, clock: Clock,
                 bus: TransactionalEventBus) -> None:
        self._incident = incident
        self._created_at = created_at
        self._clock = clock
        self._bus = bus
        self._resolved_at: datetime | None = None
        self._escalation_level = 0
        self._last_escalated_at: datetime | None = None
        self._escalation_exhausted = False

    @property
    def domain(self) -> Incident:
        return self._incident

    def __getattr__(self, name: str) -> Any:
        # Only reached for names not defined on this class: forward them to P1's Incident.
        return getattr(self._incident, name)

    # ---- facts requested from P1 (see PLACEHOLDERS.md) -----------------------------
    @property
    def PENDING_G13_created_at(self) -> datetime:
        return self._created_at

    @property
    def PENDING_G1_resolved_at(self) -> datetime | None:
        return self._resolved_at

    @property
    def PENDING_G14_title(self) -> str | None:
        return None  # the brief's incidents have a description only

    @property
    def PENDING_G15_escalation_level(self) -> int:
        return self._escalation_level

    @property
    def PENDING_G2_last_escalated_at(self) -> datetime | None:
        return self._last_escalated_at

    @property
    def escalation_exhausted(self) -> bool:
        return self._escalation_exhausted

    # ---- lifecycle calls that also move the facts above ----------------------------
    def resolve(self, actor: Any = None, resolution: str | None = None) -> None:
        self._incident.resolve(actor=actor, resolution=resolution)
        self._resolved_at = self._clock.now()

    def reject_resolution(self, actor: Any = None) -> None:
        self._incident.reject_resolution(actor=actor)
        self._resolved_at = None

    # ---- interim escalation, until P1 delivers G15/G4 ------------------------------
    def PENDING_G15_escalate(self, to_user_id: str, level: int) -> None:
        if self.status not in UNACKNOWLEDGED_STATUSES:
            raise InvalidStateTransitionError(
                f"Cannot escalate an incident that is {self.status.value}"
            )
        self._escalation_level = level
        self._last_escalated_at = self._clock.now()
        self._bus.publish(IncidentEscalated(
            incident_id=self.incident_id, occurred_at=self._clock.now(), actor=SYSTEM,
            to_user_id=to_user_id, level=level,
        ))

    def PENDING_G4_mark_escalation_exhausted(self) -> bool:
        if self._escalation_exhausted:
            return False
        self._escalation_exhausted = True
        self._bus.publish(EscalationExhausted(
            incident_id=self.incident_id, occurred_at=self._clock.now(), actor=SYSTEM,
        ))
        return True

    # ---- used by replay only --------------------------------------------------------
    def _replay_escalation(self, step: Step) -> None:
        if step.action == "escalated":
            self._escalation_level = int(step.payload.get("level", 0))
            self._last_escalated_at = step.at
        elif step.action == "escalation_exhausted":
            self._escalation_exhausted = True


def rebuild(
    inputs: IncidentInputs,
    steps: Iterable[Step],
    technician: Callable[[str], Any],
    policy: SLAPolicy,
    live_clock: Clock,
    bus: TransactionalEventBus,
) -> PersistedIncident:
    """Replay ``steps`` and return an incident ready for new actions."""
    clock = ReplayClock(live_clock)
    trail = ordered(steps)
    first_priority = next(
        (Priority[s.payload["priority"]] for s in trail if s.action == "set_priority"), None
    )
    if first_priority is None:
        raise ReplayError(f"{inputs.incident_id} has no priority in its audit trail")

    with bus.muted():
        clock.set(inputs.created_at)
        incident = Incident(
            inputs.incident_id, inputs.description, bus=bus, clock=clock,
            reporter=inputs.reporter, service=inputs.service, category=inputs.category,
            impact=inputs.impact, urgency=inputs.urgency,
            affected_users=inputs.affected_users,
        )
        incident.attach_sla(SLATracker(inputs.created_at, first_priority, policy, clock))
        result = PersistedIncident(incident, inputs.created_at, clock, bus)
        for step in trail:
            clock.set(step.at)
            try:
                _apply(result, step, technician)
            except Exception as error:
                raise ReplayError(
                    f"{inputs.incident_id}: step {step.action} at {step.at} failed: {error}"
                ) from error
    clock.go_live()
    return result


def _apply(incident: PersistedIncident, step: Step,
           technician: Callable[[str], Any]) -> None:
    action, p = step.action, step.payload
    if action == "set_priority":
        incident.set_priority(Priority[p["priority"]], actor=SYSTEM)
    elif action == "assign":
        incident.assign(actor=SYSTEM, technician=technician(p["technician_id"]))
    elif action == "resolve":
        incident.resolve(actor=SYSTEM, resolution=p.get("resolution") or None)
    elif action == "reject_resolution":
        incident.reject_resolution(actor=SYSTEM)
    elif action in LIFECYCLE_ACTIONS:
        getattr(incident, action)(actor=SYSTEM)
    elif action == "add_note":
        incident.add_note(p.get("text", ""), actor=SYSTEM)
    elif action == "submit_feedback":
        incident.submit_feedback(SYSTEM, int(p["rating"]), p.get("comment", ""))
    elif action in ("sla_warning", "sla_breach"):
        if incident.sla is not None:
            incident.sla.evaluate()  # sets the "already reported" flags
    elif action in ("escalated", "escalation_exhausted"):
        incident._replay_escalation(step)
    # Everything else (created, rejected, add_information, ...) is audit only.


@dataclass(frozen=True)
class SlaFacts:
    """SLA times for the read model and the API, derived from the trail."""

    responded_at: datetime | None
    resolved_at: datetime | None
    paused_at: datetime | None
    paused_seconds: int
    info_request: str | None
    response_breached: bool
    resolution_breached: bool


def sla_facts(steps: Iterable[Step]) -> SlaFacts:
    responded = resolved = paused_at = None
    paused = timedelta(0)
    info: str | None = None
    response_breached = resolution_breached = False
    for step in ordered(steps):
        if step.action == "acknowledge" and responded is None:
            responded = step.at
        elif step.action == "resolve":
            resolved = step.at
        elif step.action == "reject_resolution":
            resolved = None
        elif step.action == "request_info":
            paused_at, info = step.at, step.payload.get("message") or None
        elif step.action == "provide_info" and paused_at is not None:
            paused += step.at - paused_at
            paused_at, info = None, None
        elif step.action == "sla_breach":
            kind = step.payload.get("sla_event", "")
            response_breached |= kind.startswith("RESPONSE")
            resolution_breached |= kind.startswith("RESOLUTION")
    return SlaFacts(responded, resolved, paused_at, int(paused.total_seconds()), info,
                    response_breached, resolution_breached)


def is_open(status: Status) -> bool:
    return status not in (Status.RESOLVED, Status.VERIFIED, Status.CLOSED)
