from __future__ import annotations

from datetime import datetime
from types import SimpleNamespace

import pytest

from app.config import Settings
from app.jobs.scheduler import SchedulerManager
from app.jobs.sla_monitor import SLAMonitorJob
from domain.enums import Impact, Urgency
from domain.sla_monitor import SLAMonitor
from tests.fakes.in_memory import FakeIncidentRepository, FakeUnitOfWork


def _manager(settings: Settings, uow: FakeUnitOfWork, world: SimpleNamespace) -> SchedulerManager:
    monitor = SLAMonitor(world.bus, world.clock)
    m = SchedulerManager(settings, lambda: uow, clock=world.clock.now)
    m.register("sla_monitor", lambda u: SLAMonitorJob(u.incidents, monitor), 30)
    return m


def test_run_now_commits_and_closes(settings: Settings, uow: FakeUnitOfWork,
                                    repo: FakeIncidentRepository,
                                    world: SimpleNamespace) -> None:
    inc = world.factory.create(world.reporter, world.service, "Payment app down",
                               Impact.HIGH, Urgency.HIGH)
    inc.assign(technician=world.tech)
    repo.add(inc)
    world.clock.advance(minutes=6)
    m = _manager(settings, uow, world)
    result = m.run_now("sla_monitor")
    assert result.actions["response_breach"] == 1
    assert (uow.commits, uow.rollbacks, uow.closed) == (1, 0, 1)
    assert m.last_results()["sla_monitor"] is result


def test_crash_rolls_back(settings: Settings, uow: FakeUnitOfWork, t0: datetime) -> None:
    m = SchedulerManager(settings, lambda: uow, clock=lambda: t0)

    def boom(_u: object) -> object:
        raise RuntimeError("factory failed")

    m.register("broken", boom, 30)  # type: ignore[arg-type]
    with pytest.raises(RuntimeError):
        m.run_now("broken")
    assert (uow.commits, uow.rollbacks, uow.closed) == (0, 1, 1)


def test_disabled_scheduler_does_not_start(settings: Settings, uow: FakeUnitOfWork,
                                           world: SimpleNamespace) -> None:
    m = _manager(settings, uow, world)
    m.start()  # SCHEDULER_ENABLED=False in the test settings
    m.shutdown()


def test_duplicate_registration_rejected(settings: Settings, uow: FakeUnitOfWork,
                                         world: SimpleNamespace) -> None:
    m = _manager(settings, uow, world)
    with pytest.raises(ValueError):
        m.register("sla_monitor", lambda u: None, 30)  # type: ignore[arg-type,return-value]
