from dataclasses import dataclass, replace
from datetime import datetime

from domain.exceptions import ITSMError


class NotificationDeliveryError(ITSMError):
    """A channel could not deliver a notification."""


@dataclass(frozen=True)
class Contact:
    """Someone who can receive a notification."""

    user_id: str
    name: str = ""
    email: str | None = None


@dataclass(frozen=True)
class Notification:
    """One message for one user. The repository assigns ``id`` when it is saved."""

    user_id: str
    incident_id: str
    subject: str
    message: str
    event_type: str
    created_at: datetime
    read: bool = False
    id: int | None = None

    def with_id(self, notification_id: int) -> "Notification":
        return replace(self, id=notification_id)

    def marked_read(self) -> "Notification":
        return replace(self, read=True)
