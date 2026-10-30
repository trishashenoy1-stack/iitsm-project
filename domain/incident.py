from dataclasses import dataclass

from domain.enums import Status
from domain.events import (
    SYSTEM,
    IncidentAssigned,
    PriorityChanged,
    StatusChanged,
    TransitionRejected,
)
from domain.exceptions import (
    InvalidStateTransitionError,
    UnauthorizedActionError,
    ValidationError,
)
from domain.permissions import check_permission
from domain.states import NewState


@dataclass(frozen=True)
class Note:
    author_id: str
    text: str
    created_at: object


@dataclass(frozen=True)
class Feedback:
    rating: int
    comment: str
    created_at: object


class Incident:
    def __init__(
        self,
        incident_id,
        description,
        bus=None,
        clock=None,
        reporter=None,
        service=None,
        category=None,
        impact=None,
        urgency=None,
        affected_users=0,
    ):
        if bus is not None and clock is None:
            raise ValidationError("A clock is required when an event bus is used")
        self._incident_id = incident_id
        self._description = description
        self._bus = bus
        self._clock = clock
        self._reporter = reporter
        self._service = service
        self._category = category
        self._impact = impact
        self._urgency = urgency
        self._affected_users = affected_users
        self._state = NewState()
        self._sla = None
        self._priority = None
        self._technician = None
        self._notes = []
        self._resolution = None
        self._feedback = None

    # ---------- reading ----------
    @property
    def incident_id(self):
        return self._incident_id

    @property
    def description(self):
        return self._description

    @property
    def status(self):
        return self._state.status

    @property
    def sla(self):
        return self._sla

    @property
    def priority(self):
        return self._priority

    @property
    def technician(self):
        return self._technician

    @property
    def reporter(self):
        return self._reporter

    @property
    def service(self):
        return self._service

    @property
    def category(self):
        return self._category

    @property
    def impact(self):
        return self._impact

    @property
    def urgency(self):
        return self._urgency

    @property
    def affected_users(self):
        return self._affected_users

    @property
    def notes(self):
        return tuple(self._notes)

    @property
    def resolution(self):
        return self._resolution

    @property
    def feedback(self):
        return self._feedback

    # ---------- setup ----------
    def attach_sla(self, tracker):
        self._sla = tracker

    def set_priority(self, priority, actor=None, reason=""):
        actor = actor if actor is not None else SYSTEM
        self._authorize("set_priority", actor)
        previous = self._priority
        if self._sla is not None:
            self._sla.change_priority(priority)
        self._priority = priority
        if previous != priority:
            self._emit(
                PriorityChanged,
                actor,
                previous_priority=previous,
                new_priority=priority,
                reason=reason,
            )

    # ---------- lifecycle actions ----------
    def classify(self, actor=None):
        self._act("classify", actor)

    def assign(self, actor=None, technician=None):
        actor = actor if actor is not None else SYSTEM
        self._act("assign", actor)
        if technician is not None:
            self._technician = technician
            self._emit(IncidentAssigned, actor, technician_id=technician.user_id)

    def acknowledge(self, actor=None):
        self._act("acknowledge", actor)

    def start_work(self, actor=None):
        self._act("start_work", actor)

    def request_info(self, actor=None):
        self._act("request_info", actor)

    def provide_info(self, actor=None):
        self._act("provide_info", actor)

    def resolve(self, actor=None, resolution=None):
        text = None
        if resolution is not None:
            text = resolution.strip()
            if not text:
                raise ValidationError("Resolution text cannot be empty")
        self._act("resolve", actor)
        if text:
            self._resolution = text

    def verify(self, actor=None):
        self._act("verify", actor)

    def reject_resolution(self, actor=None):
        self._act("reject_resolution", actor)

    def close(self, actor=None):
        self._act("close", actor)
        # closing frees the technician's capacity (close is only legal once)
        if self._technician is not None:
            self._technician.release_incident()

    # ---------- notes and feedback ----------
    def add_note(self, text, actor=None):
        actor = actor if actor is not None else SYSTEM
        self._authorize("add_note", actor)
        text = (text or "").strip()
        if not text:
            raise ValidationError("Note text is required")
        if self.status == Status.CLOSED:
            raise InvalidStateTransitionError("Cannot add notes to a closed incident")
        created = self._clock.now() if self._clock is not None else None
        self._notes.append(Note(actor.user_id, text, created))

    def submit_feedback(self, actor, rating, comment=""):
        if actor is None:
            raise UnauthorizedActionError("Feedback must come from the reporter")
        self._authorize("submit_feedback", actor)
        if self.status not in (Status.RESOLVED, Status.VERIFIED, Status.CLOSED):
            raise InvalidStateTransitionError(
                f"Cannot give feedback on an incident that is {self.status.value}"
            )
        if self._feedback is not None:
            raise ValidationError("Feedback has already been submitted")
        if isinstance(rating, bool) or not isinstance(rating, int) or not 1 <= rating <= 5:
            raise ValidationError("Rating must be a whole number from 1 to 5")
        created = self._clock.now() if self._clock is not None else None
        self._feedback = Feedback(rating, (comment or "").strip(), created)

    # ---------- internals ----------
    def _authorize(self, action, actor):
        try:
            check_permission(action, actor, self)
        except UnauthorizedActionError as error:
            self._emit(
                TransitionRejected,
                actor,
                attempted_action=action,
                current_status=self.status,
                reason=str(error),
            )
            raise

    def _act(self, action, actor):
        actor = actor if actor is not None else SYSTEM
        self._authorize(action, actor)
        previous = self.status
        try:
            getattr(self._state, action)(self)
        except InvalidStateTransitionError as error:
            self._emit(
                TransitionRejected,
                actor,
                attempted_action=action,
                current_status=previous,
                reason=str(error),
            )
            raise
        self._emit(
            StatusChanged, actor, previous_status=previous, new_status=self.status
        )

    def _set_state(self, new_state):
        self._state.on_exit(self)
        self._state = new_state
        new_state.on_enter(self)

    def _emit(self, event_class, actor, **fields):
        if self._bus is None:
            return
        self._bus.publish(
            event_class(
                incident_id=self._incident_id,
                occurred_at=self._clock.now(),
                actor=actor,
                **fields,
            )
        )