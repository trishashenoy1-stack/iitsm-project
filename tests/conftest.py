"""Shared fixtures + the @pytest.mark.case catalogue hook (used by scripts/export_test_cases.py).

Formal test cases for the report are tagged like this:

    @pytest.mark.case(id="TC-P4-01", category="business-rule",
                      desc="...", expected="...")

Categories: normal, boundary, invalid-input, exception, authorization, business-rule.
"""

from __future__ import annotations

import json
from collections.abc import Callable
from datetime import datetime
from pathlib import Path
from types import SimpleNamespace
from typing import Any

import pytest

from app.config import Settings
from domain.clock import FakeClock
from domain.events import EventBus
from domain.factory import IncidentFactory
from domain.priority import MatrixPriorityStrategy
from domain.sla import SLAPolicy
from domain.users import Employee, Technician
from tests.fakes.in_memory import (
    PAYMENTS,
    T0,
    FakeEmbeddingStore,
    FakeEscalationDirectory,
    FakeIncident,
    FakeIncidentRepository,
    FakeIntelligenceSink,
    FakeUnitOfWork,
    make_incident,
)

CASE_CATEGORIES = {"normal", "boundary", "invalid-input", "exception", "authorization",
                   "business-rule"}

TEAM_LEAD = "U-LEAD"
SYS_ADMIN = "U-SYSADMIN"
IT_MANAGER = "U-MANAGER"


# ---------------------------------------------------------------- case catalogue hook
def pytest_addoption(parser: pytest.Parser) -> None:
    parser.addoption("--cases-out", default=None, help="write @case metadata+outcomes as JSON")


_CASES: dict[str, dict[str, Any]] = {}


def pytest_configure(config: pytest.Config) -> None:
    config.addinivalue_line("markers", "case(id, category, desc, expected): formal test case")
    _CASES.clear()


def pytest_collection_modifyitems(config: pytest.Config, items: list[pytest.Item]) -> None:
    seen: dict[str, str] = {}
    for item in items:
        m = item.get_closest_marker("case")
        if m is None:
            continue
        meta = dict(m.kwargs)
        missing = {"id", "category", "desc", "expected"} - meta.keys()
        if missing:
            raise pytest.UsageError(f"{item.nodeid}: @case missing {sorted(missing)}")
        if meta["category"] not in CASE_CATEGORIES:
            raise pytest.UsageError(f"{item.nodeid}: unknown case category {meta['category']}")
        if meta["id"] in seen:
            raise pytest.UsageError(f"duplicate case id {meta['id']}: {seen[meta['id']]}")
        seen[meta["id"]] = item.nodeid
        _CASES[item.nodeid] = {**meta, "nodeid": item.nodeid, "outcome": "not run"}


def pytest_runtest_logreport(report: pytest.TestReport) -> None:
    case = _CASES.get(report.nodeid)
    if case is None:
        return
    # The "call" phase decides; setup/teardown only matter when they fail or skip.
    if report.when == "call" or report.outcome != "passed":
        case["outcome"] = report.outcome


def pytest_sessionfinish(session: pytest.Session) -> None:
    out = session.config.getoption("--cases-out")
    if out:
        Path(out).parent.mkdir(parents=True, exist_ok=True)
        Path(out).write_text(json.dumps(list(_CASES.values()), indent=2), encoding="utf-8")


# ---------------------------------------------------------------- fixtures
@pytest.fixture
def t0() -> datetime:
    return T0


@pytest.fixture
def settings(tmp_path: Path) -> Settings:
    return Settings(
        SCHEDULER_ENABLED=False,
        EMBEDDER_BACKEND="hashing",
        INTELLIGENCE_ASYNC=False,
        CATEGORIZER_MODEL_PATH=tmp_path / "missing.joblib",
        ESCALATION_AFTER_MINUTES={"P1": 5, "P2": 15},
        AUTO_CLOSE_DAYS=3,
    )


@pytest.fixture
def incident_factory() -> Callable[..., FakeIncident]:
    return make_incident


@pytest.fixture
def clock() -> FakeClock:
    return FakeClock(T0)


@pytest.fixture
def bus() -> EventBus:
    return EventBus()


@pytest.fixture
def world(clock: FakeClock, bus: EventBus) -> SimpleNamespace:
    """Real P1 domain objects: factory, people, service, plus every event published."""
    events: list[Any] = []
    from domain.events import DomainEvent

    bus.subscribe(DomainEvent, events.append)
    factory = IncidentFactory(clock, bus, MatrixPriorityStrategy(), SLAPolicy.default())
    return SimpleNamespace(
        clock=clock, bus=bus, events=events, factory=factory, service=PAYMENTS,
        reporter=Employee("E1", "Asha"), tech=Technician("T1", "Ravi", {"application"}),
    )


@pytest.fixture
def repo() -> FakeIncidentRepository:
    return FakeIncidentRepository()


@pytest.fixture
def sink(repo: FakeIncidentRepository, clock: FakeClock) -> FakeIntelligenceSink:
    return FakeIntelligenceSink(repo, clock=clock.now)


@pytest.fixture
def directory() -> FakeEscalationDirectory:
    return FakeEscalationDirectory([(TEAM_LEAD, True), (SYS_ADMIN, True), (IT_MANAGER, True)])


@pytest.fixture
def store() -> FakeEmbeddingStore:
    return FakeEmbeddingStore()


@pytest.fixture
def uow(repo: FakeIncidentRepository, sink: FakeIntelligenceSink,
        directory: FakeEscalationDirectory, store: FakeEmbeddingStore) -> FakeUnitOfWork:
    return FakeUnitOfWork(repo, sink, directory, store)
