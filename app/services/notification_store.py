"""Database-backed pieces P3's notification module asks the backend for (P2).

Both run on the notification worker thread, so each call opens its own session.
"""

from __future__ import annotations

from sqlalchemy import select, update
from sqlalchemy.orm import sessionmaker

from app.db.models import IncidentRecord, NotificationRecord, UserRecord
from domain.enums import Role
from notifications.directory import IncidentParties, RecipientDirectory
from notifications.models import Contact, Notification
from notifications.repository import NotificationRepository


def _notification(row: NotificationRecord) -> Notification:
    return Notification(user_id=row.user_id, incident_id=row.incident_id or "",
                        subject=row.subject, message=row.message, event_type=row.event_type,
                        created_at=row.created_at, read=row.read, id=row.id)


class SqlNotificationRepository(NotificationRepository):
    def __init__(self, session_factory: sessionmaker) -> None:
        self._sessions = session_factory

    def save(self, notification: Notification) -> Notification:
        with self._sessions() as session:
            row = NotificationRecord(
                user_id=notification.user_id, incident_id=notification.incident_id or None,
                subject=notification.subject, message=notification.message,
                event_type=notification.event_type, created_at=notification.created_at,
                read=notification.read,
            )
            session.add(row)
            session.commit()
            return notification.with_id(row.id)

    def list_for_user(self, user_id: str, limit: int = 50) -> list[Notification]:
        with self._sessions() as session:
            rows = session.scalars(select(NotificationRecord)
                                   .where(NotificationRecord.user_id == user_id)
                                   .order_by(NotificationRecord.id.desc()).limit(limit))
            return [_notification(r) for r in rows]

    def since(self, user_id: str, after_id: int) -> list[Notification]:
        with self._sessions() as session:
            rows = session.scalars(select(NotificationRecord)
                                   .where(NotificationRecord.user_id == user_id,
                                          NotificationRecord.id > after_id)
                                   .order_by(NotificationRecord.id))
            return [_notification(r) for r in rows]

    def mark_read(self, user_id: str, notification_id: int) -> bool:
        with self._sessions() as session:
            result = session.execute(update(NotificationRecord)
                                     .where(NotificationRecord.id == notification_id,
                                            NotificationRecord.user_id == user_id)
                                     .values(read=True))
            session.commit()
            return bool(result.rowcount)

    def mark_all_read(self, user_id: str) -> None:
        with self._sessions() as session:
            session.execute(update(NotificationRecord)
                            .where(NotificationRecord.user_id == user_id)
                            .values(read=True))
            session.commit()


class SqlRecipientDirectory(RecipientDirectory):
    def __init__(self, session_factory: sessionmaker) -> None:
        self._sessions = session_factory

    @staticmethod
    def _contact(row: UserRecord | None) -> Contact | None:
        if row is None or not row.active:
            return None
        return Contact(user_id=row.id, name=row.name, email=row.email)

    def parties_for(self, incident_id: str) -> IncidentParties:
        with self._sessions() as session:
            incident = session.get(IncidentRecord, incident_id)
            if incident is None:
                return IncidentParties()
            reporter = session.get(UserRecord, incident.reporter_id)
            technician = (session.get(UserRecord, incident.technician_id)
                          if incident.technician_id else None)
            return IncidentParties(self._contact(reporter), self._contact(technician))

    def contact(self, user_id: str) -> Contact | None:
        with self._sessions() as session:
            return self._contact(session.get(UserRecord, user_id))

    def administrators(self) -> list[Contact]:
        with self._sessions() as session:
            rows = session.scalars(select(UserRecord).where(UserRecord.role == Role.ADMIN.value,
                                                            UserRecord.active.is_(True)))
            return [c for c in (self._contact(r) for r in rows) if c is not None]
