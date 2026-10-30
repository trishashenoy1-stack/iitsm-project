import itertools

from domain.enums import Impact, Urgency
from domain.events import IncidentCreated
from domain.exceptions import (
    ServiceNotFoundError,
    UnauthorizedActionError,
    ValidationError,
)
from domain.incident import Incident
from domain.sla import SLATracker

MAX_DESCRIPTION_LENGTH = 2000


class IncidentFactory:
    """Creates fully set-up incidents: validated, prioritised, with an SLA."""

    def __init__(self, clock, bus, priority_strategy, sla_policy, first_number=1001):
        self._clock = clock
        self._bus = bus
        self._priority_strategy = priority_strategy
        self._sla_policy = sla_policy
        self._counter = itertools.count(first_number)

    def set_priority_strategy(self, strategy):
        self._priority_strategy = strategy

    def create(
        self, reporter, service, description, impact, urgency, affected_users=0
    ):
        if reporter is None or not reporter.is_active:
            raise UnauthorizedActionError("Only active users can report incidents")
        if service is None or not service.is_active:
            raise ServiceNotFoundError("The affected service does not exist")
        description = (description or "").strip()
        if not description:
            raise ValidationError("Description is required")
        if len(description) > MAX_DESCRIPTION_LENGTH:
            raise ValidationError(
                f"Description is longer than {MAX_DESCRIPTION_LENGTH} characters"
            )
        if not isinstance(impact, Impact) or not isinstance(urgency, Urgency):
            raise ValidationError("impact and urgency must be Impact / Urgency values")

        # calculate first, so a failed creation never uses up an ID
        priority = self._priority_strategy.calculate(
            impact, urgency, service.criticality, affected_users
        )

        incident_id = f"INC{next(self._counter)}"
        incident = Incident(
            incident_id,
            description,
            bus=self._bus,
            clock=self._clock,
            reporter=reporter,
            service=service,
        )
        incident.attach_sla(
            SLATracker(self._clock.now(), priority, self._sla_policy, self._clock)
        )

        if self._bus is not None:
            self._bus.publish(
                IncidentCreated(
                    incident_id=incident_id,
                    occurred_at=self._clock.now(),
                    actor=reporter,
                )
            )
        incident.set_priority(
            priority,
            reason=(
                f"Calculated from impact={impact.name}, urgency={urgency.name}, "
                f"criticality={service.criticality}, affected users={affected_users}"
            ),
        )
        return incident