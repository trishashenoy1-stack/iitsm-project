import logging
from dataclasses import dataclass
from datetime import datetime

from domain.enums import Priority, Status

log = logging.getLogger(__name__)


class SystemActor:
    """The 'user' for automatic actions (auto-close, escalation, SLA breach)."""

    user_id = "SYSTEM"
    name = "System"


SYSTEM = SystemActor()


@dataclass(frozen=True)
class DomainEvent:
    incident_id: str
    occurred_at: datetime
    actor: object


@dataclass(frozen=True)
class IncidentCreated(DomainEvent):
    pass


@dataclass(frozen=True)
class StatusChanged(DomainEvent):
    previous_status: Status
    new_status: Status


@dataclass(frozen=True)
class TransitionRejected(DomainEvent):
    attempted_action: str
    current_status: Status
    reason: str


@dataclass(frozen=True)
class IncidentAssigned(DomainEvent):
    technician_id: str


@dataclass(frozen=True)
class PriorityChanged(DomainEvent):
    previous_priority: Priority | None
    new_priority: Priority
    reason: str


class EventBus:
    """Synchronous publish/subscribe. A failing handler never breaks the others."""

    def __init__(self):
        self._handlers = []

    def subscribe(self, event_type, handler):
        self._handlers.append((event_type, handler))

    def publish(self, event):
        for event_type, handler in list(self._handlers):
            if isinstance(event, event_type):
                try:
                    handler(event)
                except Exception:
                    log.exception(
                        "Handler %r failed for %s", handler, type(event).__name__
                    )