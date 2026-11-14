import asyncio
import json
from collections.abc import Callable

from fastapi import APIRouter, Depends, Header, HTTPException, status
from fastapi.concurrency import run_in_threadpool
from fastapi.responses import StreamingResponse
from pydantic import BaseModel

from notifications.broker import SseBroker
from notifications.models import Notification
from notifications.repository import NotificationRepository

HEARTBEAT_SECONDS = 15.0


class NotificationOut(BaseModel):
    """Matches AppNotification in frontend/src/api/types.ts."""

    id: str
    incidentId: str | None
    message: str
    createdAt: str
    read: bool

    @classmethod
    def of(cls, notification: Notification) -> "NotificationOut":
        return cls(
            id=str(notification.id),
            incidentId=notification.incident_id,
            message=notification.message,
            createdAt=notification.created_at.isoformat(),
            read=notification.read,
        )


def _sse_frame(notification: Notification) -> str:
    payload = NotificationOut.of(notification).model_dump()
    return f"id: {notification.id}\nevent: notification\ndata: {json.dumps(payload)}\n\n"


def _parse_last_id(value: str | None) -> int | None:
    try:
        return int(value) if value else None
    except ValueError:
        return None


def create_router(
    repository: NotificationRepository,
    broker: SseBroker,
    current_user: Callable,
    heartbeat_seconds: float = HEARTBEAT_SECONDS,
) -> APIRouter:
    """``current_user`` is the backend's auth dependency. It returns an object with ``user_id``."""

    router = APIRouter(prefix="/notifications", tags=["notifications"])

    @router.get("", response_model=list[NotificationOut])
    def history(user=Depends(current_user)):
        return [NotificationOut.of(n) for n in repository.list_for_user(user.user_id)]

    @router.post("/read-all", status_code=status.HTTP_204_NO_CONTENT)
    def read_all(user=Depends(current_user)):
        repository.mark_all_read(user.user_id)

    @router.post("/{notification_id}/read", status_code=status.HTTP_204_NO_CONTENT)
    def read_one(notification_id: int, user=Depends(current_user)):
        if not repository.mark_read(user.user_id, notification_id):
            raise HTTPException(status.HTTP_404_NOT_FOUND, "Notification not found")

    @router.get("/stream")
    async def stream(
        user=Depends(current_user),
        last_event_id: str | None = Header(default=None, alias="Last-Event-ID"),
    ):
        async def events():
            # Subscribe before replaying, so nothing falls between the two.
            subscription = broker.subscribe(user.user_id)
            last_sent = _parse_last_id(last_event_id)
            try:
                yield ": connected\n\n"
                if last_sent is not None:
                    missed = await run_in_threadpool(
                        repository.since, user.user_id, last_sent
                    )
                    for notification in missed:
                        last_sent = notification.id
                        yield _sse_frame(notification)
                while True:
                    try:
                        item = await asyncio.wait_for(
                            subscription.queue.get(), heartbeat_seconds
                        )
                    except TimeoutError:
                        yield ": keep-alive\n\n"
                        continue
                    if item is None:
                        return
                    if last_sent is not None and item.id <= last_sent:
                        continue
                    last_sent = item.id
                    yield _sse_frame(item)
            finally:
                broker.unsubscribe(subscription)

        return StreamingResponse(
            events(),
            media_type="text/event-stream",
            headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no"},
        )

    return router
