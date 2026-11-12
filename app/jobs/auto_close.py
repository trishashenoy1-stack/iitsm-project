"""Auto-close job: RESOLVED and unverified for AUTO_CLOSE_DAYS -> CLOSED (system actor)."""

from __future__ import annotations

from collections.abc import Iterable, Iterator
from datetime import datetime, timedelta
from typing import Any

from app.config import Settings
from app.jobs.base import BatchJob, JobResult
from app.p4_contracts import AutoClosableIncident, IncidentRepository
from domain.enums import Status


def PENDING_G16_close_unverified(incident: AutoClosableIncident) -> None:
    """G16: interim, using what P1 has today: verify() then close(), both as SYSTEM.

    The downside: the audit trail will say the incident was VERIFIED, which the
    reporter never did. Asked P1 for a system-only RESOLVED -> CLOSED transition
    (spec 8.1). When it lands, replace this body with: incident.auto_close()
    """
    incident.verify()
    incident.close()


class AutoCloseJob(BatchJob[Any]):
    name = "auto_close"

    def __init__(self, repo: IncidentRepository, after: timedelta) -> None:
        self._repo = repo
        self._after = after

    def select(self, now: datetime) -> Iterable[Any]:
        return self._repo.resolved_before(now - self._after)

    def process(self, item: Any, now: datetime) -> Iterator[str]:
        fresh = self._repo.PENDING_G5_get_for_update(item.incident_id)
        resolved_at = fresh.PENDING_G1_resolved_at
        if fresh.status != Status.RESOLVED or resolved_at is None:
            return  # verified or reopened meanwhile
        if now - resolved_at < self._after:
            return
        PENDING_G16_close_unverified(fresh)
        yield "auto_closed"


def build_auto_close(repo: IncidentRepository, cfg: Settings) -> AutoCloseJob:
    return AutoCloseJob(repo, timedelta(days=cfg.AUTO_CLOSE_DAYS))


def run_auto_close(now: datetime, repo: IncidentRepository, cfg: Settings) -> JobResult:
    return build_auto_close(repo, cfg).run(now)
