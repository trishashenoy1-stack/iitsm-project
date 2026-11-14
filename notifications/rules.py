from collections.abc import Callable
from dataclasses import dataclass
from enum import Enum, auto

from domain.enums import Status
from domain.events import (
    DomainEvent,
    IncidentAssigned,
    IncidentCreated,
    PriorityChanged,
    SLABreached,
    SLAWarning,
    StatusChanged,
)
from domain.sla import SLAEvent
from notifications.channels import EMAIL, IN_APP


class Audience(Enum):
    REPORTER = auto()
    TECHNICIAN = auto()
    ASSIGNED_TECHNICIAN = auto()  # the technician named on the event itself
    ADMINISTRATORS = auto()
    TECHNICIAN_OR_ADMINISTRATORS = auto()  # admins cover unassigned incidents
    TARGET_USER = auto()  # the user named in the event's ``to_user_id`` (escalation)


@dataclass(frozen=True)
class Delivery:
    audience: Audience
    channels: tuple[str, ...]


@dataclass(frozen=True)
class NotificationRule:
    applies: Callable[[DomainEvent], bool]
    subject: Callable[[DomainEvent], str]
    message: Callable[[DomainEvent], str]
    deliveries: tuple[Delivery, ...]
    notify_actor: bool = False


BOTH = (IN_APP, EMAIL)
APP_ONLY = (IN_APP,)


def _is(event_type):
    return lambda event: isinstance(event, event_type)


def _became(status, came_from=None):
    def check(event):
        return (
            isinstance(event, StatusChanged)
            and event.new_status == status
            and (came_from is None or event.previous_status == came_from)
        )

    return check


def _text(template):
    return lambda event: template.format(id=event.incident_id)


def _reprioritised(event):
    # IncidentFactory also publishes this for the first calculation at creation.
    return isinstance(event, PriorityChanged) and event.previous_priority is not None


def _sla_target(event):
    is_response = event.sla_event in (SLAEvent.RESPONSE_WARNING, SLAEvent.RESPONSE_BREACH)
    return "response" if is_response else "resolution"


def _priority_message(event):
    old, new = event.previous_priority.name, event.new_priority.name
    return f"{event.incident_id} changed from {old} to {new}"


DEFAULT_RULES = (
    NotificationRule(
        _is(IncidentCreated),
        _text("We received {id}"),
        _text("We received {id}."),
        (Delivery(Audience.REPORTER, APP_ONLY),),
        notify_actor=True,
    ),
    NotificationRule(
        _is(IncidentAssigned),
        _text("{id} was assigned to you"),
        _text("{id} was assigned to you."),
        (Delivery(Audience.ASSIGNED_TECHNICIAN, BOTH),),
    ),
    NotificationRule(
        _is(IncidentAssigned),
        _text("{id} has a technician"),
        _text("A technician was assigned to {id}."),
        (Delivery(Audience.REPORTER, APP_ONLY),),
    ),
    NotificationRule(
        _reprioritised,
        _text("Priority changed on {id}"),
        _priority_message,
        (Delivery(Audience.TECHNICIAN, APP_ONLY), Delivery(Audience.REPORTER, APP_ONLY)),
    ),
    NotificationRule(
        _became(Status.AWAITING_INFO),
        _text("{id} needs more information"),
        _text("{id} needs more information from you."),
        (Delivery(Audience.REPORTER, BOTH),),
    ),
    NotificationRule(
        _became(Status.RESOLVED),
        _text("{id} was resolved"),
        _text("{id} was resolved. Check the fix and confirm."),
        (Delivery(Audience.REPORTER, BOTH),),
    ),
    NotificationRule(
        _became(Status.CLOSED),
        _text("{id} was closed"),
        _text("{id} was closed."),
        (Delivery(Audience.REPORTER, APP_ONLY),),
    ),
    NotificationRule(
        _became(Status.IN_PROGRESS, came_from=Status.AWAITING_INFO),
        _text("The reporter replied on {id}"),
        _text("The reporter replied on {id}."),
        (Delivery(Audience.TECHNICIAN, APP_ONLY),),
    ),
    NotificationRule(
        _became(Status.VERIFIED),
        _text("The fix on {id} was confirmed"),
        _text("The reporter confirmed the fix on {id}."),
        (Delivery(Audience.TECHNICIAN, APP_ONLY),),
    ),
    NotificationRule(
        _became(Status.REOPENED),
        _text("{id} is still broken"),
        _text("The reporter says {id} is still broken."),
        (Delivery(Audience.TECHNICIAN, APP_ONLY),),
    ),
    NotificationRule(
        _is(SLAWarning),
        _text("SLA warning on {id}"),
        lambda e: f"The {_sla_target(e)} deadline for {e.incident_id} is approaching.",
        (Delivery(Audience.TECHNICIAN_OR_ADMINISTRATORS, BOTH),),
    ),
    NotificationRule(
        _is(SLABreached),
        _text("SLA breached on {id}"),
        lambda e: f"The {_sla_target(e)} deadline for {e.incident_id} was missed.",
        (Delivery(Audience.TECHNICIAN, BOTH), Delivery(Audience.ADMINISTRATORS, BOTH)),
    ),
)
