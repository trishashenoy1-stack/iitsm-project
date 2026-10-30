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


class Incident:
    def __init__(
        self,
        incident_id,
        description,
        bus=None,
        clock=None,
        reporter=None,
        service=None,
    ):
        if bus is not None and clock is None:
            raise ValidationError("A clock is required when an event bus is used")
        self._incident_id = incident_id
        self._description = description
        self._bus = bus
        self._clock = clock
        self._reporter = reporter
        self._service = service
        self._state = NewState()
        self._sla = None
        self._priority = None
        self._technician = None

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

    def resolve(self, actor=None):
        self._act("resolve", actor)

    def verify(self, actor=None):
        self._act("verify", actor)

    def reject_resolution(self, actor=None):
        self._act("reject_resolution", actor)

    def close(self, actor=None):
        self._act("close", actor)

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