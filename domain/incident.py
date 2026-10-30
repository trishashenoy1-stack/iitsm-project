from domain.states import NewState


class Incident:
    def __init__(self, incident_id, description):
        self._incident_id = incident_id
        self._description = description
        self._state = NewState()
        self._sla = None

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

    def attach_sla(self, tracker):
        self._sla = tracker

    def classify(self):
        self._state.classify(self)

    def assign(self):
        self._state.assign(self)

    def acknowledge(self):
        self._state.acknowledge(self)

    def start_work(self):
        self._state.start_work(self)

    def request_info(self):
        self._state.request_info(self)

    def provide_info(self):
        self._state.provide_info(self)

    def resolve(self):
        self._state.resolve(self)

    def verify(self):
        self._state.verify(self)

    def reject_resolution(self):
        self._state.reject_resolution(self)

    def close(self):
        self._state.close(self)

    def _set_state(self, new_state):
        self._state.on_exit(self)
        self._state = new_state
        new_state.on_enter(self)