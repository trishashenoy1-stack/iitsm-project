import asyncio
import json
import socket
import threading
import time
from dataclasses import dataclass
from datetime import datetime, timezone

import httpx
import pytest
import uvicorn
from fastapi import FastAPI, Header, HTTPException
from fastapi.testclient import TestClient

from notifications.api import create_router
from notifications.broker import SseBroker
from notifications.models import Notification
from notifications.repository import InMemoryNotificationRepository

NOW = datetime(2026, 11, 1, 10, 0, tzinfo=timezone.utc)


@dataclass
class User:
    user_id: str


def fake_auth(authorization: str | None = Header(default=None)):
    if not authorization:
        raise HTTPException(401, "Sign in first")
    return User(authorization.removeprefix("Bearer "))


def note(user_id="E1", message="Hello"):
    return Notification(user_id, "INC1", "Subject", message, "StatusChanged", NOW)


def make_app(repository, broker, heartbeat=15.0):
    app = FastAPI()
    app.include_router(create_router(repository, broker, fake_auth, heartbeat), prefix="/api")
    return app


@pytest.fixture
def api():
    repository = InMemoryNotificationRepository()
    client = TestClient(make_app(repository, SseBroker()))
    return repository, client


AS_E1 = {"Authorization": "Bearer E1"}
AS_E2 = {"Authorization": "Bearer E2"}


def test_every_route_needs_a_signed_in_user(api):
    _, client = api
    assert client.get("/api/notifications").status_code == 401
    assert client.get("/api/notifications/stream").status_code == 401
    assert client.post("/api/notifications/read-all").status_code == 401
    assert client.post("/api/notifications/1/read").status_code == 401


def test_history_matches_the_frontend_contract(api):
    repository, client = api
    repository.save(note())
    body = client.get("/api/notifications", headers=AS_E1).json()
    assert body == [{"id": "1", "incidentId": "INC1", "message": "Hello", "createdAt": NOW.isoformat(), "read": False}]


def test_history_only_shows_your_own(api):
    repository, client = api
    repository.save(note("E1"))
    assert client.get("/api/notifications", headers=AS_E2).json() == []


def test_mark_one_read(api):
    repository, client = api
    saved = repository.save(note())
    assert client.post(f"/api/notifications/{saved.id}/read", headers=AS_E1).status_code == 204
    assert repository.list_for_user("E1")[0].read is True


def test_you_cannot_mark_someone_elses_notification(api):
    repository, client = api
    saved = repository.save(note("E1"))
    assert client.post(f"/api/notifications/{saved.id}/read", headers=AS_E2).status_code == 404
    assert repository.list_for_user("E1")[0].read is False


def test_read_all_only_touches_your_own(api):
    repository, client = api
    repository.save(note("E1"))
    repository.save(note("E2"))
    assert client.post("/api/notifications/read-all", headers=AS_E1).status_code == 204
    assert repository.list_for_user("E1")[0].read is True
    assert repository.list_for_user("E2")[0].read is False


# ---------- broker ----------


def test_broker_wakes_a_waiting_stream_from_another_thread():
    async def scenario():
        broker = SseBroker()
        subscription = broker.subscribe("E1")
        saved = note().with_id(1)
        # The stream must already be asleep, or a non-thread-safe put goes unnoticed.
        threading.Timer(0.1, broker.publish, args=(saved,)).start()
        started = time.perf_counter()
        received = await asyncio.wait_for(subscription.queue.get(), 2)
        return received, saved, time.perf_counter() - started

    received, saved, elapsed = asyncio.run(scenario())
    assert received == saved
    assert elapsed < 1


def test_broker_only_reaches_the_right_user():
    async def scenario():
        broker = SseBroker()
        other = broker.subscribe("E2")
        broker.publish(note("E1").with_id(1))
        await asyncio.sleep(0.05)
        return other.queue.qsize()

    assert asyncio.run(scenario()) == 0


def test_broker_reaches_every_open_tab():
    async def scenario():
        broker = SseBroker()
        first, second = broker.subscribe("E1"), broker.subscribe("E1")
        broker.publish(note().with_id(1))
        await asyncio.sleep(0.05)
        return first.queue.qsize(), second.queue.qsize()

    assert asyncio.run(scenario()) == (1, 1)


def test_broker_closes_a_stuck_client_instead_of_growing():
    async def scenario():
        broker = SseBroker(queue_size=2)
        subscription = broker.subscribe("E1")
        for index in range(3):
            broker.publish(note().with_id(index + 1))
        await asyncio.sleep(0.05)
        return await subscription.queue.get()

    assert asyncio.run(scenario()) is None


def test_unsubscribe_forgets_the_connection():
    async def scenario():
        broker = SseBroker()
        subscription = broker.subscribe("E1")
        broker.unsubscribe(subscription)
        return broker.connection_count("E1")

    assert asyncio.run(scenario()) == 0


# ---------- the stream over a real socket ----------


@pytest.fixture
def live_server():
    repository = InMemoryNotificationRepository()
    broker = SseBroker()
    app = make_app(repository, broker, heartbeat=0.2)
    with socket.socket() as probe:
        probe.bind(("127.0.0.1", 0))
        port = probe.getsockname()[1]
    server = uvicorn.Server(uvicorn.Config(app, host="127.0.0.1", port=port, log_level="error"))
    thread = threading.Thread(target=server.run, daemon=True)
    thread.start()
    for _ in range(100):
        if server.started:
            break
        time.sleep(0.02)
    yield repository, broker, f"http://127.0.0.1:{port}/api/notifications/stream"
    server.should_exit = True
    server.force_exit = True
    thread.join(5)


def read_frames(url, headers, wanted, trigger=None):
    """Collect SSE data frames until ``wanted`` arrive."""
    frames = []
    deadline = time.monotonic() + 5
    with httpx.stream("GET", url, headers=headers, timeout=5) as response:
        assert response.status_code == 200
        assert response.headers["content-type"].startswith("text/event-stream")
        for line in response.iter_lines():
            # Heartbeats keep the socket busy, so a socket timeout alone would never fire.
            assert time.monotonic() < deadline, f"only received {len(frames)} of {wanted} frames"
            if line == ": connected" and trigger:
                trigger()
            if line.startswith("data: "):
                frames.append(json.loads(line[6:]))
                if len(frames) == wanted:
                    return frames
    return frames


def publish_saved(repository, broker, message):
    broker.publish(repository.save(note(message=message)))


def wait_for_connection(broker):
    for _ in range(200):
        if broker.connection_count("E1"):
            return
        time.sleep(0.01)
    raise AssertionError("client never connected")


def test_stream_pushes_a_notification_published_from_a_worker_thread(live_server):
    repository, broker, url = live_server

    def trigger():
        threading.Thread(target=lambda: (wait_for_connection(broker), publish_saved(repository, broker, "Live"))).start()

    frames = read_frames(url, AS_E1, 1, trigger)
    assert frames[0]["message"] == "Live"
    assert frames[0]["incidentId"] == "INC1"


def test_reconnecting_client_replays_what_it_missed_without_duplicates(live_server):
    repository, broker, url = live_server
    for message in ["one", "two", "three"]:
        repository.save(note(message=message))

    frames = read_frames(url, {**AS_E1, "Last-Event-ID": "1"}, 2)
    assert [f["message"] for f in frames] == ["two", "three"]


def test_stream_releases_the_connection_when_the_client_leaves(live_server):
    repository, broker, url = live_server

    def trigger():
        threading.Thread(target=lambda: (wait_for_connection(broker), publish_saved(repository, broker, "Bye"))).start()

    read_frames(url, AS_E1, 1, trigger)
    for _ in range(200):
        if broker.connection_count("E1") == 0:
            return
        time.sleep(0.02)
    raise AssertionError("connection was never released")
