import logging
from collections.abc import Mapping, Sequence

from domain.events import DomainEvent, EventBus
from notifications.channels import NotificationChannel
from notifications.directory import IncidentParties, RecipientDirectory
from notifications.dispatcher import Dispatcher
from notifications.models import Contact, Notification
from notifications.rules import Audience, NotificationRule

log = logging.getLogger(__name__)


class NotificationService:
    """Observer of the domain event bus.

    The handler only queues work. Finding recipients and delivering happen on
    the dispatcher, and one failing channel never stops the others.
    """

    def __init__(
        self,
        rules: Sequence[NotificationRule],
        directory: RecipientDirectory,
        channels: Mapping[str, NotificationChannel],
        dispatcher: Dispatcher,
    ):
        self._rules = tuple(rules)
        self._directory = directory
        self._channels = dict(channels)
        self._dispatcher = dispatcher

    def register(self, bus: EventBus) -> None:
        bus.subscribe(DomainEvent, self.handle)

    def handle(self, event: DomainEvent) -> None:
        self._dispatcher.submit(lambda: self._process(event))

    def _process(self, event: DomainEvent) -> None:
        for rule in self._rules:
            if rule.applies(event):
                self._apply(rule, event)

    def _apply(self, rule: NotificationRule, event: DomainEvent) -> None:
        parties = self._directory.parties_for(event.incident_id)
        actor_id = getattr(event.actor, "user_id", None)

        # One entry per person, even if they appear in several audiences.
        targets: dict[str, tuple[Contact, list[str]]] = {}
        for delivery in rule.deliveries:
            for contact in self._resolve(delivery.audience, event, parties):
                if contact.user_id == actor_id and not rule.notify_actor:
                    continue
                _, channels = targets.setdefault(contact.user_id, (contact, []))
                channels.extend(c for c in delivery.channels if c not in channels)

        for contact, channels in targets.values():
            notification = Notification(
                user_id=contact.user_id,
                incident_id=event.incident_id,
                subject=rule.subject(event),
                message=rule.message(event),
                event_type=type(event).__name__,
                created_at=event.occurred_at,
            )
            for name in channels:
                self._deliver(name, notification, contact)

    def _resolve(
        self, audience: Audience, event: DomainEvent, parties: IncidentParties
    ) -> list[Contact]:
        if audience is Audience.REPORTER:
            return [parties.reporter] if parties.reporter else []
        if audience is Audience.TECHNICIAN:
            return [parties.technician] if parties.technician else []
        if audience is Audience.ASSIGNED_TECHNICIAN:
            contact = self._directory.contact(event.technician_id)
            return [contact] if contact else []
        if audience is Audience.ADMINISTRATORS:
            return self._directory.administrators()
        if parties.technician:
            return [parties.technician]
        return self._directory.administrators()

    def _deliver(self, name: str, notification: Notification, contact: Contact) -> None:
        channel = self._channels.get(name)
        if channel is None:
            log.error("No channel registered as '%s'", name)
            return
        try:
            channel.send(notification, contact)
        except Exception:
            log.exception(
                "Channel '%s' failed for %s", name, notification.incident_id
            )
