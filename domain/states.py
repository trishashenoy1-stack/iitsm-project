from domain.enums import Status
from domain.exceptions import InvalidStateTransitionError


class IncidentState:
    """Base state: every action is refused unless a subclass allows it."""

    status = None

    def on_enter(self, incident):
        pass

    def on_exit(self, incident):
        pass

    def classify(self, incident):
        self._refuse("classify")

    def assign(self, incident):
        self._refuse("assign")

    def acknowledge(self, incident):
        self._refuse("acknowledge")

    def start_work(self, incident):
        self._refuse("start work on")

    def request_info(self, incident):
        self._refuse("request info on")

    def provide_info(self, incident):
        self._refuse("provide info for")

    def resolve(self, incident):
        self._refuse("resolve")

    def verify(self, incident):
        self._refuse("verify")

    def reject_resolution(self, incident):
        self._refuse("reject the resolution of")

    def close(self, incident):
        self._refuse("close")

    def _refuse(self, action):
        raise InvalidStateTransitionError(
            f"Cannot {action} an incident that is {self.status.value}"
        )


class NewState(IncidentState):
    status = Status.NEW

    def classify(self, incident):
        incident._set_state(ClassifiedState())

    def assign(self, incident):
        incident._set_state(AssignedState())


class ClassifiedState(IncidentState):
    status = Status.CLASSIFIED

    def assign(self, incident):
        incident._set_state(AssignedState())


class AssignedState(IncidentState):
    status = Status.ASSIGNED

    def acknowledge(self, incident):
        if incident.sla is not None:
            incident.sla.record_acknowledged()
        incident._set_state(AcknowledgedState())


class AcknowledgedState(IncidentState):
    status = Status.ACKNOWLEDGED

    def start_work(self, incident):
        incident._set_state(InProgressState())


class InProgressState(IncidentState):
    status = Status.IN_PROGRESS

    def request_info(self, incident):
        incident._set_state(AwaitingInfoState())

    def resolve(self, incident):
        if incident.sla is not None:
            incident.sla.record_resolved()
        incident._set_state(ResolvedState())


class AwaitingInfoState(IncidentState):
    status = Status.AWAITING_INFO

    def on_enter(self, incident):
        if incident.sla is not None:
            incident.sla.pause()

    def on_exit(self, incident):
        if incident.sla is not None:
            incident.sla.resume()

    def provide_info(self, incident):
        incident._set_state(InProgressState())


class ResolvedState(IncidentState):
    status = Status.RESOLVED

    def verify(self, incident):
        incident._set_state(VerifiedState())

    def reject_resolution(self, incident):
        incident._set_state(ReopenedState())


class VerifiedState(IncidentState):
    status = Status.VERIFIED

    def close(self, incident):
        incident._set_state(ClosedState())


class ClosedState(IncidentState):
    status = Status.CLOSED


class ReopenedState(IncidentState):
    status = Status.REOPENED

    def on_enter(self, incident):
        if incident.sla is not None:
            incident.sla.record_reopened()

    def start_work(self, incident):
        incident._set_state(InProgressState())