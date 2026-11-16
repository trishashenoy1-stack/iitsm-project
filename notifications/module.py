import os
from collections.abc import Callable

from fastapi import APIRouter

from domain.events import EventBus
from notifications.api import create_router
from notifications.broker import SseBroker
from notifications.channels import (
    EMAIL,
    IN_APP,
    ChannelDependencies,
    NotificationChannelFactory,
)
from notifications.directory import RecipientDirectory
from notifications.dispatcher import BackgroundDispatcher
from notifications.email_gateway import (
    EmailGateway,
    SimulatedEmailGateway,
    SmtpEmailAdapter,
    SmtpSettings,
)
from notifications.repository import InMemoryNotificationRepository, NotificationRepository
from notifications.rules import DEFAULT_RULES
from notifications.service import NotificationService


def email_gateway_from_env(env=os.environ) -> EmailGateway:
    """Simulated unless EMAIL_BACKEND=smtp."""
    if env.get("EMAIL_BACKEND", "simulated").lower() == "smtp":
        return SmtpEmailAdapter(SmtpSettings.from_env(env))
    return SimulatedEmailGateway()


class NotificationModule:
    """Wires the parts together. The backend calls start() and stop() on app lifespan."""

    def __init__(
        self,
        bus: EventBus,
        directory: RecipientDirectory,
        repository: NotificationRepository | None = None,
        email_gateway: EmailGateway | None = None,
        factory: NotificationChannelFactory | None = None,
        channel_names: tuple[str, ...] = (IN_APP, EMAIL),
        rules=DEFAULT_RULES,
    ):
        self.repository = repository or InMemoryNotificationRepository()
        self.broker = SseBroker()
        self.dispatcher = BackgroundDispatcher()
        factory = factory or NotificationChannelFactory.with_defaults()
        dependencies = ChannelDependencies(
            self.repository, self.broker, email_gateway or email_gateway_from_env()
        )
        self.service = NotificationService(
            rules,
            directory,
            {name: factory.create(name, dependencies) for name in channel_names},
            self.dispatcher,
        )
        self.service.register(bus)

    def start(self) -> None:
        self.dispatcher.start()

    def stop(self) -> None:
        self.dispatcher.stop()

    def router(self, current_user: Callable, **options) -> APIRouter:
        return create_router(self.repository, self.broker, current_user, **options)
