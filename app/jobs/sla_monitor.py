"""SLA monitor job: schedules P1's domain SLAMonitor.

All SLA rules (deadlines, pause, warn/breach once) live in P1's domain.sla. This job only:
  * picks the open incidents each tick,
  * calls SLAMonitor.check() per incident, so one bad incident can't abort the batch
    (P1's check_all() has no per-incident error handling),
  * reports what fired.
SLAWarning/SLABreached events are published on the bus by P1's monitor; audit and
notification listeners react to them.
"""

from __future__ import annotations

from collections.abc import Iterable, Iterator
from datetime import datetime
from typing import Any

from app.jobs.base import BatchJob, JobResult
from app.p4_contracts import IncidentRepository


class SLAMonitorJob(BatchJob[Any]):
    name = "sla_monitor"

    def __init__(self, repo: IncidentRepository, monitor: Any) -> None:
        self._repo = repo
        self._monitor = monitor  # domain.sla_monitor.SLAMonitor

    def select(self, now: datetime) -> Iterable[Any]:
        return self._repo.open_incidents()

    def process(self, item: Any, now: datetime) -> Iterator[str]:
        # P1's tracker reads its own clock; `now` is only for the JobResult.
        for sla_event in self._monitor.check(item):
            yield str(sla_event.value).lower()  # e.g. "response_breach"


def run_sla_monitor(now: datetime, repo: IncidentRepository, monitor: Any) -> JobResult:
    return SLAMonitorJob(repo, monitor).run(now)
