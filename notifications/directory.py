from abc import ABC, abstractmethod
from dataclasses import dataclass

from notifications.models import Contact


@dataclass(frozen=True)
class IncidentParties:
    """The people attached to an incident."""

    reporter: Contact | None = None
    technician: Contact | None = None


class RecipientDirectory(ABC):
    """Finds who to notify. Domain events only carry IDs.

    The backend implements this on top of its repositories. It is called from
    the background worker, so it must open its own database session.
    """

    @abstractmethod
    def parties_for(self, incident_id: str) -> IncidentParties:
        ...

    @abstractmethod
    def contact(self, user_id: str) -> Contact | None:
        ...

    @abstractmethod
    def administrators(self) -> list[Contact]:
        ...
