import smtplib
import threading
import time
from datetime import datetime, timezone

import pytest

from domain.clock import FakeClock
from domain.enums import Impact, Priority, Status, Urgency
from domain.events import (
    SYSTEM,
    EventBus,
    IncidentAssigned,
    IncidentCreated,
    PriorityChanged,
    SLABreached,
    SLAWarning,
    StatusChanged,
    TransitionRejected,
)
from domain.exceptions import ValidationError
from domain.factory import IncidentFactory
from domain.priority import MatrixPriorityStrategy
from domain.service import ITService
from domain.sla import SLAEvent, SLAPolicy
from domain.sla_monitor import SLAMonitor
from domain.users import Employee, Technician
from notifications.channels import (
    EMAIL,
    IN_APP,
    ChannelDependencies,
    EmailChannel,
    InAppChannel,
    NotificationChannel,
    NotificationChannelFactory,
)
from notifications.directory import IncidentParties, RecipientDirectory
from notifications.dispatcher import BackgroundDispatcher, ImmediateDispatcher
from notifications.email_gateway import SimulatedEmailGateway, SmtpEmailAdapter, SmtpSettings
from notifications.broker import SseBroker
from notifications.models import Contact, Notification, NotificationDeliveryError
from notifications.repository import InMemoryNotificationRepository
from notifications.rules import DEFAULT_RULES, Audience, Delivery, NotificationRule
from notifications.service import NotificationService

NOW = datetime(2026, 11, 1, 10, 0, tzinfo=timezone.utc)
REPORTER = Contact("E1", "Priya", "priya@example.test")
TECH = Contact("T1", "Arjun", "arjun@example.test")
ADMIN = Contact("A1", "Meera", "meera@example.test")


class FakeDirectory(RecipientDirectory):
    def __init__(self, technician=TECH):
        self.technician = technician

    def parties_for(self, incident_id):
        return IncidentParties(reporter=REPORTER, technician=self.technician)

    def contact(self, user_id):
        return {"E1": REPORTER, "T1": TECH, "A1": ADMIN}.get(user_id)

    def administrators(self):
        return [ADMIN]


class Recorder(NotificationChannel):
    def __init__(self, name, log):
        self.name = name
        self.log = log

    def send(self, notification, recipient):
        self.log.append((self.name, recipient.user_id, notification.message))


def harness(directory=None, rules=DEFAULT_RULES):
    log = []
    service = NotificationService(
        rules,
        directory or FakeDirectory(),
        {IN_APP: Recorder(IN_APP, log), EMAIL: Recorder(EMAIL, log)},
        ImmediateDispatcher(),
    )
    return service, log


def actor(user_id):
    return Contact(user_id)


def status_change(old, new, by="T1"):
    return StatusChanged("INC1", NOW, actor(by), previous_status=old, new_status=new)


def who(log):
    return sorted((channel, user) for channel, user, _ in log)


# ---------- the approved notification table ----------


def test_created_tells_the_reporter_in_app_even_though_they_are_the_actor():
    service, log = harness()
    service.handle(IncidentCreated("INC1", NOW, actor("E1")))
    assert who(log) == [(IN_APP, "E1")]


def test_assigned_tells_technician_by_both_and_reporter_in_app():
    service, log = harness()
    service.handle(IncidentAssigned("INC1", NOW, SYSTEM, technician_id="T1"))
    assert who(log) == [(EMAIL, "T1"), (IN_APP, "E1"), (IN_APP, "T1")]


def test_priority_change_tells_technician_and_reporter_in_app():
    service, log = harness()
    service.handle(PriorityChanged("INC1", NOW, actor("A1"), previous_priority=Priority.P3, new_priority=Priority.P1, reason="x"))
    assert who(log) == [(IN_APP, "E1"), (IN_APP, "T1")]
    assert "P3 to P1" in log[0][2]


def test_first_priority_calculation_at_creation_is_silent():
    service, log = harness()
    service.handle(PriorityChanged("INC1", NOW, SYSTEM, previous_priority=None, new_priority=Priority.P1, reason="x"))
    assert log == []


@pytest.mark.parametrize(
    "old, new, expected",
    [
        (Status.IN_PROGRESS, Status.AWAITING_INFO, [(EMAIL, "E1"), (IN_APP, "E1")]),
        (Status.IN_PROGRESS, Status.RESOLVED, [(EMAIL, "E1"), (IN_APP, "E1")]),
        (Status.VERIFIED, Status.CLOSED, [(IN_APP, "E1")]),
    ],
)
def test_status_changes_for_the_reporter(old, new, expected):
    service, log = harness()
    service.handle(status_change(old, new, by="T1"))
    assert who(log) == expected


@pytest.mark.parametrize(
    "old, new",
    [
        (Status.AWAITING_INFO, Status.IN_PROGRESS),
        (Status.RESOLVED, Status.VERIFIED),
        (Status.RESOLVED, Status.REOPENED),
    ],
)
def test_reporter_actions_tell_the_technician(old, new):
    service, log = harness()
    service.handle(status_change(old, new, by="E1"))
    assert who(log) == [(IN_APP, "T1")]


def test_ordinary_progress_is_silent():
    service, log = harness()
    service.handle(status_change(Status.ASSIGNED, Status.ACKNOWLEDGED))
    service.handle(status_change(Status.ACKNOWLEDGED, Status.IN_PROGRESS))
    assert log == []


def test_rejected_transition_notifies_nobody():
    service, log = harness()
    service.handle(TransitionRejected("INC1", NOW, actor("T1"), attempted_action="close", current_status=Status.NEW, reason="no"))
    assert log == []


def test_sla_warning_tells_the_technician_by_both():
    service, log = harness()
    service.handle(SLAWarning("INC1", NOW, SYSTEM, sla_event=SLAEvent.RESOLUTION_WARNING))
    assert who(log) == [(EMAIL, "T1"), (IN_APP, "T1")]
    assert "resolution deadline" in log[0][2]


def test_sla_warning_on_unassigned_incident_goes_to_admins():
    service, log = harness(FakeDirectory(technician=None))
    service.handle(SLAWarning("INC1", NOW, SYSTEM, sla_event=SLAEvent.RESPONSE_WARNING))
    assert who(log) == [(EMAIL, "A1"), (IN_APP, "A1")]
    assert "response deadline" in log[0][2]


def test_sla_breach_tells_technician_and_admins():
    service, log = harness()
    service.handle(SLABreached("INC1", NOW, SYSTEM, sla_event=SLAEvent.RESOLUTION_BREACH))
    assert who(log) == [(EMAIL, "A1"), (EMAIL, "T1"), (IN_APP, "A1"), (IN_APP, "T1")]


# ---------- recipients ----------


def test_people_are_not_told_about_their_own_actions():
    service, log = harness()
    service.handle(status_change(Status.RESOLVED, Status.VERIFIED, by="T1"))
    assert log == []


def test_someone_in_two_audiences_is_notified_once():
    directory = FakeDirectory(technician=ADMIN)
    service, log = harness(directory)
    service.handle(SLABreached("INC1", NOW, SYSTEM, sla_event=SLAEvent.RESOLUTION_BREACH))
    assert who(log) == [(EMAIL, "A1"), (IN_APP, "A1")]


def test_a_missing_channel_does_not_stop_the_others():
    log = []
    service = NotificationService(DEFAULT_RULES, FakeDirectory(), {IN_APP: Recorder(IN_APP, log)}, ImmediateDispatcher())
    service.handle(status_change(Status.IN_PROGRESS, Status.RESOLVED))
    assert who(log) == [(IN_APP, "E1")]


def test_one_failing_channel_does_not_stop_the_others():
    class Broken(NotificationChannel):
        def send(self, notification, recipient):
            raise NotificationDeliveryError("mail server down")

    log = []
    service = NotificationService(DEFAULT_RULES, FakeDirectory(), {EMAIL: Broken(), IN_APP: Recorder(IN_APP, log)}, ImmediateDispatcher())
    service.handle(status_change(Status.IN_PROGRESS, Status.RESOLVED))
    assert who(log) == [(IN_APP, "E1")]


# ---------- channels, adapter and factory ----------


def draft(user_id="E1"):
    return Notification(user_id, "INC1", "Subject", "Body", "StatusChanged", NOW)


def test_in_app_channel_saves_before_publishing():
    repository = InMemoryNotificationRepository()
    seen = []

    class SpyBroker:
        def publish(self, notification):
            seen.append((notification.id, len(repository.list_for_user("E1"))))

    InAppChannel(repository, SpyBroker()).send(draft(), REPORTER)
    assert seen == [(1, 1)]


def test_email_channel_sends_through_the_gateway():
    gateway = SimulatedEmailGateway()
    EmailChannel(gateway).send(draft(), REPORTER)
    assert gateway.sent == [("priya@example.test", "Subject", "Body")]


def test_email_channel_skips_people_without_an_address():
    gateway = SimulatedEmailGateway()
    EmailChannel(gateway).send(draft(), Contact("E2", "No Email"))
    assert gateway.sent == []


class FakeSmtp:
    instances = []
    fail_with = None

    def __init__(self, host, port, timeout):
        self.host, self.port, self.timeout = host, port, timeout
        self.calls = []
        self.message = None
        FakeSmtp.instances.append(self)

    def __enter__(self):
        if FakeSmtp.fail_with:
            raise FakeSmtp.fail_with
        return self

    def __exit__(self, *args):
        return False

    def starttls(self):
        self.calls.append("starttls")

    def login(self, username, password):
        self.calls.append(("login", username, password))

    def send_message(self, message):
        self.calls.append("send")
        self.message = message


@pytest.fixture
def fake_smtp():
    FakeSmtp.instances = []
    FakeSmtp.fail_with = None
    return FakeSmtp


def test_smtp_adapter_uses_tls_login_and_builds_the_message(fake_smtp):
    settings = SmtpSettings("mail.test", "itsm@example.test", username="u", password="p")
    SmtpEmailAdapter(settings, fake_smtp).send("a@example.test", "Hello", "World")
    client = fake_smtp.instances[0]
    assert client.calls == ["starttls", ("login", "u", "p"), "send"]
    assert client.timeout == 10
    assert client.message["To"] == "a@example.test"
    assert client.message["Subject"] == "Hello"


def test_smtp_adapter_skips_tls_and_login_when_not_configured(fake_smtp):
    settings = SmtpSettings("localhost", "itsm@example.test", port=1025, use_tls=False)
    SmtpEmailAdapter(settings, fake_smtp).send("a@example.test", "Hello", "World")
    assert fake_smtp.instances[0].calls == ["send"]


@pytest.mark.parametrize("error", [smtplib.SMTPAuthenticationError(535, b"bad"), ConnectionRefusedError()])
def test_smtp_failures_become_a_delivery_error_without_secrets(fake_smtp, error):
    fake_smtp.fail_with = error
    settings = SmtpSettings("mail.test", "itsm@example.test", username="u", password="s3cret")
    with pytest.raises(NotificationDeliveryError) as caught:
        SmtpEmailAdapter(settings, fake_smtp).send("a@example.test", "Hello", "World")
    assert "s3cret" not in str(caught.value)


def test_factory_rejects_unknown_channels():
    dependencies = ChannelDependencies(InMemoryNotificationRepository(), SseBroker(), SimulatedEmailGateway())
    with pytest.raises(ValidationError):
        NotificationChannelFactory.with_defaults().create("pigeon", dependencies)


def test_new_channel_plugs_in_without_changing_existing_code():
    log = []

    class SmsChannel(NotificationChannel):
        def send(self, notification, recipient):
            log.append(("sms", recipient.user_id))

    factory = NotificationChannelFactory.with_defaults()
    factory.register("sms", lambda dependencies: SmsChannel())
    dependencies = ChannelDependencies(InMemoryNotificationRepository(), SseBroker(), SimulatedEmailGateway())
    rule = NotificationRule(
        lambda event: isinstance(event, IncidentCreated),
        lambda event: "s",
        lambda event: "m",
        (Delivery(Audience.REPORTER, ("sms",)),),
        notify_actor=True,
    )
    service = NotificationService([rule], FakeDirectory(), {"sms": factory.create("sms", dependencies)}, ImmediateDispatcher())
    service.handle(IncidentCreated("INC1", NOW, actor("E1")))
    assert log == [("sms", "E1")]


# ---------- repository ----------


def test_repository_scopes_everything_to_the_user():
    repository = InMemoryNotificationRepository()
    mine = repository.save(draft("E1"))
    theirs = repository.save(draft("E2"))
    assert [n.id for n in repository.list_for_user("E1")] == [mine.id]
    assert repository.mark_read("E1", theirs.id) is False
    assert repository.list_for_user("E2")[0].read is False
    assert repository.mark_read("E1", mine.id) is True
    assert repository.list_for_user("E1")[0].read is True


def test_repository_lists_newest_first_and_replays_oldest_first():
    repository = InMemoryNotificationRepository()
    for _ in range(3):
        repository.save(draft())
    assert [n.id for n in repository.list_for_user("E1")] == [3, 2, 1]
    assert [n.id for n in repository.since("E1", 1)] == [2, 3]


# ---------- the request must never wait for delivery ----------


def test_slow_delivery_does_not_block_the_publisher():
    finished = threading.Event()

    class SlowChannel(NotificationChannel):
        def send(self, notification, recipient):
            time.sleep(0.4)
            finished.set()

    dispatcher = BackgroundDispatcher()
    dispatcher.start()
    bus = EventBus()
    NotificationService(DEFAULT_RULES, FakeDirectory(), {IN_APP: SlowChannel()}, dispatcher).register(bus)
    try:
        started = time.perf_counter()
        bus.publish(status_change(Status.IN_PROGRESS, Status.RESOLVED))
        assert time.perf_counter() - started < 0.1
        assert finished.wait(2)
    finally:
        dispatcher.stop()


def test_background_dispatcher_survives_a_failing_job():
    dispatcher = BackgroundDispatcher()
    dispatcher.start()
    ran = []

    def boom():
        raise RuntimeError("boom")

    dispatcher.submit(boom)
    dispatcher.submit(lambda: ran.append(1))
    dispatcher.wait_until_idle()
    dispatcher.stop()
    assert ran == [1]


# ---------- real domain objects, real event bus ----------


class RealDirectory(RecipientDirectory):
    def __init__(self):
        self.incidents = {}

    def parties_for(self, incident_id):
        incident = self.incidents[incident_id]
        convert = lambda u: Contact(u.user_id, u.name, f"{u.user_id}@example.test") if u else None
        return IncidentParties(convert(incident.reporter), convert(incident.technician))

    def contact(self, user_id):
        return Contact(user_id, user_id, f"{user_id}@example.test")

    def administrators(self):
        return [ADMIN]


def test_full_lifecycle_through_p1s_real_domain():
    clock = FakeClock(NOW)
    bus = EventBus()
    directory = RealDirectory()
    repository = InMemoryNotificationRepository()
    gateway = SimulatedEmailGateway()
    channels = {IN_APP: InAppChannel(repository, SseBroker()), EMAIL: EmailChannel(gateway)}
    NotificationService(DEFAULT_RULES, directory, channels, ImmediateDispatcher()).register(bus)

    reporter = Employee("E1", "Priya")
    technician = Technician("T1", "Arjun", ["APPLICATION"])
    factory = IncidentFactory(clock, bus, MatrixPriorityStrategy(), SLAPolicy.default())

    # Creation publishes before the caller holds the incident, so stub the lookup.
    original = directory.parties_for
    directory.parties_for = lambda incident_id: IncidentParties(reporter=Contact("E1", "Priya", "E1@example.test"))
    incident = factory.create(reporter, ITService("S1", "Payment", 5), "Payment down", Impact.HIGH, Urgency.HIGH, 10)
    directory.parties_for = original
    directory.incidents[incident.incident_id] = incident
    id_ = incident.incident_id

    incident.assign(technician=technician)
    incident.acknowledge(actor=technician)
    incident.start_work(actor=technician)
    incident.request_info(actor=technician)
    incident.provide_info(actor=reporter)

    clock.advance(minutes=25)
    SLAMonitor(bus, clock).check(incident)

    incident.resolve(actor=technician, resolution="Fixed")
    incident.verify(actor=reporter)
    incident.close(actor=technician)

    employee = [n.message for n in reversed(repository.list_for_user("E1"))]
    assert employee == [
        f"We received {id_}.",
        f"A technician was assigned to {id_}.",
        f"{id_} needs more information from you.",
        f"{id_} was resolved. Check the fix and confirm.",
        f"{id_} was closed.",
    ]
    technician_messages = [n.message for n in reversed(repository.list_for_user("T1"))]
    assert technician_messages[0] == f"{id_} was assigned to you."
    assert f"The reporter replied on {id_}." in technician_messages
    assert f"The resolution deadline for {id_} is approaching." in technician_messages
    assert technician_messages[-1] == f"The reporter confirmed the fix on {id_}."

    emailed = [(to, subject) for to, subject, _ in gateway.sent]
    assert ("T1@example.test", f"{id_} was assigned to you") in emailed
    assert ("E1@example.test", f"{id_} was resolved") in emailed
