from domain.enums import Status
from domain.exceptions import InvalidStateTransitionError


class Incident:
    def __init__(self, incident_id, description):
        self.incident_id = incident_id
        self.description = description
        self.status = Status.NEW

    def assign(self):
        if self.status != Status.NEW:
            raise InvalidStateTransitionError(
                f"Cannot assign an incident that is {self.status.value}"
            )
        self.status = Status.ASSIGNED