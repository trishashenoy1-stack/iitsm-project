import logging
import os
import smtplib
from abc import ABC, abstractmethod
from dataclasses import dataclass
from email.message import EmailMessage

from notifications.models import NotificationDeliveryError

log = logging.getLogger(__name__)

SMTP_TIMEOUT_SECONDS = 10


class EmailGateway(ABC):
    """What the email channel needs, independent of any mail library."""

    @abstractmethod
    def send(self, to: str, subject: str, body: str) -> None:
        ...


class SimulatedEmailGateway(EmailGateway):
    """Records emails instead of sending them. Used in development and tests."""

    def __init__(self):
        self.sent: list[tuple[str, str, str]] = []

    def send(self, to, subject, body):
        self.sent.append((to, subject, body))
        log.info("Simulated email: %s", subject)


@dataclass(frozen=True)
class SmtpSettings:
    host: str
    sender: str
    port: int = 587
    username: str | None = None
    password: str | None = None
    use_tls: bool = True

    @classmethod
    def from_env(cls, env=os.environ) -> "SmtpSettings":
        return cls(
            host=env["SMTP_HOST"],
            sender=env["SMTP_SENDER"],
            port=int(env.get("SMTP_PORT", "587")),
            username=env.get("SMTP_USERNAME"),
            password=env.get("SMTP_PASSWORD"),
            use_tls=env.get("SMTP_USE_TLS", "true").lower() != "false",
        )


class SmtpEmailAdapter(EmailGateway):
    """Adapter: presents Python's smtplib through the EmailGateway interface."""

    def __init__(self, settings: SmtpSettings, smtp_factory=smtplib.SMTP):
        self._settings = settings
        self._smtp_factory = smtp_factory

    def send(self, to, subject, body):
        message = EmailMessage()
        message["From"] = self._settings.sender
        message["To"] = to
        message["Subject"] = subject
        message.set_content(body)
        try:
            with self._smtp_factory(
                self._settings.host, self._settings.port, timeout=SMTP_TIMEOUT_SECONDS
            ) as client:
                if self._settings.use_tls:
                    client.starttls()
                if self._settings.username:
                    client.login(self._settings.username, self._settings.password)
                client.send_message(message)
        except (smtplib.SMTPException, OSError) as error:
            raise NotificationDeliveryError(
                f"Could not send email through {self._settings.host}: "
                f"{type(error).__name__}"
            ) from error
