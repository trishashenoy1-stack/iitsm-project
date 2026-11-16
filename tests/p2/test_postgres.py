"""Postgres-only checks (P2): migrations and row locking. Run with ``pytest -m integration``
and DATABASE_URL pointing at an empty Postgres database (CI provides one)."""

from __future__ import annotations

import os
import threading
from datetime import UTC, datetime

import pytest
from alembic.config import Config
from sqlalchemy import inspect, text

from alembic import command
from app.bootstrap import Backend
from app.db.models import Base, TechnicianRecord
from app.db.session import build_engine
from app.services.incidents import NewIncident
from domain.clock import SystemClock
from tests.p2.conftest import add_people, make_settings

URL = os.environ.get("DATABASE_URL", "")
pytestmark = [
    pytest.mark.integration,
    pytest.mark.skipif(not URL.startswith("postgresql"), reason="needs DATABASE_URL=postgres"),
]


@pytest.fixture
def migrated() -> str:
    engine = build_engine(URL)
    with engine.begin() as conn:
        Base.metadata.drop_all(conn)
        conn.execute(text("DROP TABLE IF EXISTS alembic_version"))
    engine.dispose()
    command.upgrade(Config("alembic.ini"), "head")
    return URL


@pytest.mark.case(id="TC-P2-26", category="normal", desc="Alembic migrations on Postgres",
                  expected="Every table the models define exists after upgrade head")
def test_migrations_create_the_schema(migrated: str) -> None:
    engine = build_engine(migrated)
    tables = set(inspect(engine).get_table_names())
    engine.dispose()
    assert set(Base.metadata.tables) <= tables


@pytest.mark.case(id="TC-P2-27", category="business-rule",
                  desc="Two incidents reported at the same moment, one free technician slot",
                  expected="Row lock: exactly one is assigned, the other waits for an admin")
def test_concurrent_assignment_respects_capacity(migrated: str) -> None:
    settings = make_settings(migrated, CREATE_TABLES_ON_START=False)
    backend = Backend.build(settings, clock=SystemClock(), with_p4=False)
    add_people(backend)
    with backend.session_factory() as s:
        for profile in s.query(TechnicianRecord):
            profile.max_workload = 1
        s.query(TechnicianRecord).filter(TechnicianRecord.user_id == "T102").update(
            {"available": False})
        s.commit()

    barrier = threading.Barrier(2)
    results: list[str] = []

    def report() -> None:
        barrier.wait()
        results.append(backend.incidents.report("E101", NewIncident(
            f"Payment down {datetime.now(UTC).isoformat()}", "SVC-PAY", "APPLICATION",
            "HIGH", "HIGH", 10)))

    threads = [threading.Thread(target=report) for _ in range(2)]
    for t in threads:
        t.start()
    for t in threads:
        t.join()
    statuses = sorted(backend.incidents.get("A101", i)["status"] for i in results)
    backend.stop()
    assert statuses == ["ASSIGNED", "CLASSIFIED"]
