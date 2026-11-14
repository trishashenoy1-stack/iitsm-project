import threading
from abc import ABC, abstractmethod

from notifications.models import Notification


class NotificationRepository(ABC):
    """Stores notification history so it survives refreshes and offline periods."""

    @abstractmethod
    def save(self, notification: Notification) -> Notification:
        """Store it and return a copy carrying its new, increasing ID."""

    @abstractmethod
    def list_for_user(self, user_id: str, limit: int = 50) -> list[Notification]:
        """Newest first."""

    @abstractmethod
    def since(self, user_id: str, after_id: int) -> list[Notification]:
        """Oldest first. Used to replay what a reconnecting client missed."""

    @abstractmethod
    def mark_read(self, user_id: str, notification_id: int) -> bool:
        """False when the notification does not exist or belongs to someone else."""

    @abstractmethod
    def mark_all_read(self, user_id: str) -> None:
        ...


class InMemoryNotificationRepository(NotificationRepository):
    """Used until the backend provides a database-backed repository."""

    def __init__(self):
        self._items: list[Notification] = []
        self._lock = threading.Lock()

    def save(self, notification):
        with self._lock:
            saved = notification.with_id(len(self._items) + 1)
            self._items.append(saved)
            return saved

    def list_for_user(self, user_id, limit=50):
        with self._lock:
            mine = [n for n in self._items if n.user_id == user_id]
        return list(reversed(mine))[:limit]

    def since(self, user_id, after_id):
        with self._lock:
            return [n for n in self._items if n.user_id == user_id and n.id > after_id]

    def mark_read(self, user_id, notification_id):
        with self._lock:
            for index, item in enumerate(self._items):
                if item.id == notification_id and item.user_id == user_id:
                    self._items[index] = item.marked_read()
                    return True
        return False

    def mark_all_read(self, user_id):
        with self._lock:
            self._items = [
                n.marked_read() if n.user_id == user_id else n for n in self._items
            ]
