import asyncio
import logging
import threading
from collections import defaultdict
from dataclasses import dataclass

from notifications.models import Notification

log = logging.getLogger(__name__)

DEFAULT_QUEUE_SIZE = 100


@dataclass(eq=False)
class Subscription:
    user_id: str
    queue: asyncio.Queue
    loop: asyncio.AbstractEventLoop


class SseBroker:
    """Hands notifications from the worker thread to open SSE connections.

    ``publish`` runs on a normal thread while each connection's queue belongs
    to the asyncio event loop, so every hand-over uses ``call_soon_threadsafe``.

    Connections are held in this process, so the API must run with one worker.
    """

    def __init__(self, queue_size: int = DEFAULT_QUEUE_SIZE):
        self._queue_size = queue_size
        self._subscriptions: dict[str, set[Subscription]] = defaultdict(set)
        self._lock = threading.Lock()

    def subscribe(self, user_id: str) -> Subscription:
        """Must be called from the event loop that will read the subscription."""
        subscription = Subscription(
            user_id, asyncio.Queue(self._queue_size), asyncio.get_running_loop()
        )
        with self._lock:
            self._subscriptions[user_id].add(subscription)
        return subscription

    def unsubscribe(self, subscription: Subscription) -> None:
        with self._lock:
            group = self._subscriptions.get(subscription.user_id)
            if group is None:
                return
            group.discard(subscription)
            if not group:
                del self._subscriptions[subscription.user_id]

    def connection_count(self, user_id: str) -> int:
        with self._lock:
            return len(self._subscriptions.get(user_id, ()))

    def publish(self, notification: Notification) -> None:
        with self._lock:
            targets = list(self._subscriptions.get(notification.user_id, ()))
        for subscription in targets:
            try:
                subscription.loop.call_soon_threadsafe(
                    self._offer, subscription, notification
                )
            except RuntimeError:
                # The event loop has closed, so this connection is already gone.
                self.unsubscribe(subscription)

    @staticmethod
    def _offer(subscription: Subscription, notification: Notification) -> None:
        try:
            subscription.queue.put_nowait(notification)
        except asyncio.QueueFull:
            # A stuck client: end its stream. It reconnects with Last-Event-ID
            # and replays from history, so nothing is lost.
            log.warning("SSE queue full for %s; closing stream", subscription.user_id)
            while not subscription.queue.empty():
                subscription.queue.get_nowait()
            subscription.queue.put_nowait(None)
