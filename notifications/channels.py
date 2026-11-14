from abc import ABC, abstractmethod
from collections.abc import Callable
from dataclasses import dataclass

from domain.exceptions import ValidationError
from notifications.broker import SseBroker
from notifications.email_gateway import EmailGateway
from notifications.models import Contact, Notification
from notifications.repository import NotificationRepository

IN_APP = "in_app"
EMAIL = "email"


class NotificationChannel(ABC):
    """One way of reaching a person. New mechanisms implement this interface."""

    @abstractmethod
    def send(self, notification: Notification, recipient: Contact) -> None:
        ...


class InAppChannel(NotificationChannel):
    """Saves to history first, then pushes to any open SSE connections."""

    def __init__(self, repository: NotificationRepository, broker: SseBroker):
        self._repository = repository
        self._broker = broker

    def send(self, notification, recipient):
        self._broker.publish(self._repository.save(notification))


class EmailChannel(NotificationChannel):
    def __init__(self, gateway: EmailGateway):
        self._gateway = gateway

    def send(self, notification, recipient):
        if recipient.email:
            self._gateway.send(
                recipient.email, notification.subject, notification.message
            )


@dataclass(frozen=True)
class ChannelDependencies:
    repository: NotificationRepository
    broker: SseBroker
    email_gateway: EmailGateway


ChannelBuilder = Callable[[ChannelDependencies], NotificationChannel]


class NotificationChannelFactory:
    """Factory: builds channels by name, so adding one needs only a registration."""

    def __init__(self):
        self._builders: dict[str, ChannelBuilder] = {}

    def register(self, name: str, builder: ChannelBuilder) -> None:
        self._builders[name] = builder

    def create(self, name: str, dependencies: ChannelDependencies) -> NotificationChannel:
        if name not in self._builders:
            raise ValidationError(f"Unknown notification channel '{name}'")
        return self._builders[name](dependencies)

    @classmethod
    def with_defaults(cls) -> "NotificationChannelFactory":
        factory = cls()
        factory.register(IN_APP, lambda d: InAppChannel(d.repository, d.broker))
        factory.register(EMAIL, lambda d: EmailChannel(d.email_gateway))
        return factory
