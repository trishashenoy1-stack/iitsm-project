from domain.events import SYSTEM, SLABreached, SLAWarning
from domain.sla import SLAEvent

_WARNINGS = {SLAEvent.RESPONSE_WARNING, SLAEvent.RESOLUTION_WARNING}


class SLAMonitor:
    """Checks incidents and publishes SLA warnings/breaches on the event bus.
    A scheduler (backend) calls check_all() every 30-60 seconds."""

    def __init__(self, bus, clock):
        self._bus = bus
        self._clock = clock

    def check(self, incident):
        if incident.sla is None:
            return []
        events = incident.sla.evaluate()
        for sla_event in events:
            event_class = SLAWarning if sla_event in _WARNINGS else SLABreached
            self._bus.publish(
                event_class(
                    incident_id=incident.incident_id,
                    occurred_at=self._clock.now(),
                    actor=SYSTEM,
                    sla_event=sla_event,
                )
            )
        return events

    def check_all(self, incidents):
        found = []
        for incident in incidents:
            found.extend(self.check(incident))
        return found