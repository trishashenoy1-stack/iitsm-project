"""Contract tests: the SAME expectations run against the fakes and P2's real classes.

When P2 delivers, replace the PENDING_P2_* factories with real ones (backed by a
`pg_session` fixture). If a fake drifts from the real behaviour, CI fails here instead
of in docker on 17 Nov.
"""

from __future__ import annotations

from collections.abc import Callable
from datetime import datetime, timedelta
from typing import Any

import pytest

from domain.enums import Status
from tests.fakes.in_memory import FakeEscalationDirectory, FakeIncidentRepository, make_incident


def PENDING_P2_real_repository(incidents: list[Any]) -> Any:
    pytest.skip("PENDING_P2: SqlAlchemyIncidentRepository not delivered yet")


def PENDING_P2_real_directory(chain: list[tuple[str, bool]]) -> Any:
    pytest.skip("PENDING_P2: real EscalationDirectory not delivered yet")


REPOS: dict[str, Callable[[list[Any]], Any]] = {
    "fake": FakeIncidentRepository,
    "real": PENDING_P2_real_repository,
}
DIRECTORIES: dict[str, Callable[[list[tuple[str, bool]]], Any]] = {
    "fake": FakeEscalationDirectory,
    "real": PENDING_P2_real_directory,
}


@pytest.fixture(params=list(REPOS))
def make_repo(request: pytest.FixtureRequest) -> Callable[[list[Any]], Any]:
    return REPOS[request.param]


@pytest.fixture(params=list(DIRECTORIES))
def make_directory(request: pytest.FixtureRequest) -> Callable[[list[tuple[str, bool]]], Any]:
    return DIRECTORIES[request.param]


def test_open_incidents_excludes_done(make_repo: Any) -> None:
    live = make_incident()
    done = make_incident(status=Status.CLOSED)
    repo = make_repo([live, done])
    assert [i.incident_id for i in repo.open_incidents()] == [live.incident_id]


def test_open_since_excludes_given_id(make_repo: Any, t0: datetime) -> None:
    a = make_incident()
    b = make_incident(PENDING_G13_created_at=t0 + timedelta(minutes=1))
    repo = make_repo([a, b])
    assert {i.incident_id for i in repo.open_since(t0, exclude_id=b.incident_id)} == {a.incident_id}


def test_resolved_before_uses_resolved_at(make_repo: Any, t0: datetime) -> None:
    old = make_incident(status=Status.RESOLVED, PENDING_G1_resolved_at=t0)
    new = make_incident(status=Status.RESOLVED, PENDING_G1_resolved_at=t0 + timedelta(days=5))
    repo = make_repo([old, new])
    found = repo.resolved_before(t0 + timedelta(days=1))
    assert [i.incident_id for i in found] == [old.incident_id]


def test_directory_skips_inactive_and_reports_level(make_directory: Any) -> None:
    d = make_directory([("U1", False), ("U2", True), ("U3", True)])
    first = d.next_in_chain(0)
    assert (first.user_id, first.level) == ("U2", 2)
    assert d.next_in_chain(first.level).user_id == "U3"
    assert d.next_in_chain(3) is None
