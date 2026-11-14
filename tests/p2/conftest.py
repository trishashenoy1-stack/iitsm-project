"""Fixtures for P2's tests: a real backend on a temporary SQLite file and a FakeClock.

Set P2_TEST_DATABASE_URL (e.g. the CI Postgres) to run the `integration` tests there.
"""

from __future__ import annotations

import os
from collections.abc import Callable, Iterator
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

import pytest
from fastapi.testclient import TestClient

from app.bootstrap import Backend
from app.config import Settings
from app.db.models import (
    Base,
    CategoryRecord,
    ServiceRecord,
    TechnicianRecord,
    UserRecord,
)
from app.db.session import build_engine
from app.main import create_app
from domain.category import CategoryRegistry
from domain.clock import FakeClock

PASSWORD = "correct-horse-battery"
T0 = datetime(2026, 11, 14, 10, 0, tzinfo=UTC)


def make_settings(url: str, **extra: Any) -> Settings:
    return Settings(DATABASE_URL=url, JWT_SECRET="t" * 40, APP_ENV="test",
                    SCHEDULER_ENABLED=False, EMBEDDER_BACKEND="hashing",
                    INTELLIGENCE_ASYNC=False, **extra)


def add_people(backend: Backend) -> None:
    pw = backend.passwords.hash(PASSWORD)
    now = backend.clock.now()

    def tech(user_id: str, email: str, skills: list[str], years: int, cap: int = 5) -> UserRecord:
        return UserRecord(id=user_id, email=email, name=f"Tech {user_id}", password_hash=pw,
                          role="TECHNICIAN", created_at=now,
                          technician=TechnicianRecord(skills=skills, experience_years=years,
                                                      max_workload=cap, available=True))

    with backend.session_factory() as s:
        s.add_all([
            UserRecord(id="E101", email="asha@corp.test", name="Asha", password_hash=pw,
                       role="EMPLOYEE", created_at=now),
            UserRecord(id="E102", email="bilal@corp.test", name="Bilal", password_hash=pw,
                       role="EMPLOYEE", created_at=now),
            tech("T101", "ravi@corp.test", ["application", "database"], 6),
            tech("T102", "neha@corp.test", ["network"], 3),
            UserRecord(id="A101", email="admin@corp.test", name="Meera", password_hash=pw,
                       role="ADMIN", created_at=now),
            UserRecord(id="A102", email="lead@corp.test", name="Lead", password_hash=pw,
                       role="ADMIN", created_at=now, escalation_level=1),
            ServiceRecord(id="SVC-PAY", name="Payment", criticality=5, active=True),
            ServiceRecord(id="SVC-MAIL", name="Email", criticality=2, active=True),
        ] + [CategoryRecord(name=n.upper(), description="", active=True)
             for n in CategoryRegistry.DEFAULT_NAMES])
        s.commit()


@dataclass
class World:
    backend: Backend
    client: TestClient
    clock: FakeClock
    url: str

    def login(self, email: str) -> dict[str, str]:
        r = self.client.post("/api/auth/login", json={"email": email, "password": PASSWORD})
        assert r.status_code == 200, r.text
        return {"Authorization": f"Bearer {r.json()['token']}"}

    def report(self, headers: dict[str, str], **overrides: Any) -> dict[str, Any]:
        body = {"description": "Payment app down, users cannot complete transactions",
                "serviceId": "SVC-PAY", "category": "APPLICATION", "impact": "HIGH",
                "urgency": "HIGH", "affectedUsers": 120, **overrides}
        r = self.client.post("/api/incidents", headers=headers, json=body)
        assert r.status_code == 201, r.text
        return r.json()

    def act(self, headers: dict[str, str], incident_id: str, action: str,
            message: str | None = None) -> Any:
        return self.client.post(f"/api/incidents/{incident_id}/actions/{action}",
                                headers=headers, json={"message": message})

    def restart(self) -> World:
        """A fresh backend on the same database, as after a server restart."""
        backend = Backend.build(make_settings(self.url), clock=self.clock, with_p4=False)
        return World(backend, TestClient(create_app(backend.settings, backend=backend)),
                     self.clock, self.url)


@pytest.fixture
def db_url(tmp_path: Path) -> str:
    url = os.environ.get("P2_TEST_DATABASE_URL")
    if not url:
        return f"sqlite+pysqlite:///{tmp_path / 'p2.db'}"
    # A real server: start every test from empty tables.
    engine = build_engine(url)
    Base.metadata.drop_all(engine)
    Base.metadata.create_all(engine)
    engine.dispose()
    return url


@pytest.fixture
def world_factory(db_url: str) -> Iterator[Callable[..., World]]:
    built: list[Backend] = []

    def build(with_p4: bool = False) -> World:
        clock = FakeClock(T0)
        backend = Backend.build(make_settings(db_url), clock=clock, with_p4=with_p4)
        built.append(backend)
        add_people(backend)
        return World(backend, TestClient(create_app(backend.settings, backend=backend)),
                     clock, db_url)

    yield build
    for backend in built:
        backend.engine.dispose()


@pytest.fixture
def w(world_factory: Callable[..., World]) -> World:
    return world_factory()
