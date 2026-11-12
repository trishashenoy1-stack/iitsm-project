"""SchedulerManager: runs BatchJobs on intervals, one fresh unit of work per tick.

APScheduler's BackgroundScheduler (thread pool) is used instead of AsyncIOScheduler
because the job code is synchronous (SQLAlchemy sync sessions); running it on the event
loop would block requests. Note for the report: multi-replica deployments need
SCHEDULER_ENABLED=true on exactly one replica, or a leader lock / Celery beat.
"""

from __future__ import annotations

import logging
import threading
from collections.abc import Callable
from dataclasses import dataclass
from datetime import datetime
from typing import Any

from app.config import Settings
from app.jobs.base import BatchJob, JobResult, utc_now
from app.p4_contracts import PENDING_P2_UnitOfWork, UnitOfWorkFactory

log = logging.getLogger(__name__)

JobFactory = Callable[[PENDING_P2_UnitOfWork], BatchJob[Any]]


@dataclass(frozen=True)
class _Registration:
    name: str
    factory: JobFactory
    interval_seconds: int


class SchedulerManager:
    def __init__(
        self,
        settings: Settings,
        uow_factory: UnitOfWorkFactory,
        clock: Callable[[], datetime] = utc_now,
    ) -> None:
        self._settings = settings
        self._uow_factory = uow_factory
        self._clock = clock
        self._jobs: dict[str, _Registration] = {}
        self._last: dict[str, JobResult] = {}
        self._lock = threading.Lock()
        self._scheduler: Any = None

    # --- registration ---------------------------------------------------------------
    def register(self, name: str, factory: JobFactory, interval_seconds: int) -> None:
        if name in self._jobs:
            raise ValueError(f"job {name!r} already registered")
        if interval_seconds <= 0:
            raise ValueError("interval must be positive")
        self._jobs[name] = _Registration(name, factory, interval_seconds)

    @property
    def job_names(self) -> list[str]:
        return list(self._jobs)

    # --- lifecycle ------------------------------------------------------------------
    def start(self) -> None:
        if not self._settings.SCHEDULER_ENABLED:
            log.info("scheduler disabled (SCHEDULER_ENABLED=false)")
            return
        from apscheduler.schedulers.background import BackgroundScheduler

        sched = BackgroundScheduler(timezone="UTC")
        for reg in self._jobs.values():
            sched.add_job(
                self._safe_tick,
                "interval",
                args=[reg.name],
                id=reg.name,
                seconds=reg.interval_seconds,
                max_instances=1,
                coalesce=True,
                misfire_grace_time=reg.interval_seconds,
            )
        sched.start()
        self._scheduler = sched
        log.info("scheduler started with jobs %s", self.job_names)

    def shutdown(self) -> None:
        if self._scheduler is not None:
            self._scheduler.shutdown(wait=False)
            self._scheduler = None

    # --- execution ------------------------------------------------------------------
    def run_now(self, name: str) -> JobResult:
        """Run one job immediately (demo/admin endpoint, integration tests). Raises."""
        reg = self._jobs[name]
        uow = self._uow_factory()
        try:
            result = reg.factory(uow).run(self._clock())
            uow.commit()
        except Exception:
            uow.rollback()
            raise
        finally:
            uow.close()
        with self._lock:
            self._last[name] = result
        return result

    def _safe_tick(self, name: str) -> None:
        try:
            self.run_now(name)
        except Exception:
            log.exception("scheduled job %s crashed", name)

    def last_results(self) -> dict[str, JobResult]:
        with self._lock:
            return dict(self._last)
