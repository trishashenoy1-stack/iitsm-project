"""Escalation job: Technician -> Team Lead -> System Admin -> IT Manager.

The state change is P1's domain method (G15), which emits IncidentEscalated for audit
and notifications. The race with acknowledgment is prevented by loading the incident
with a row lock (G5) and re-checking before escalating.
"""

from __future__ import annotations

from collections.abc import Iterable, Iterator
from datetime import datetime
from typing import Any

from app.config import Settings
from app.jobs.base import BatchJob, JobResult
from app.jobs.escalation_policy import EscalationPolicy
from app.p4_contracts import EscalationDirectory, IncidentRepository


class EscalationJob(BatchJob[Any]):
    name = "escalation"

    def __init__(
        self,
        repo: IncidentRepository,
        directory: EscalationDirectory,
        policy: EscalationPolicy,
    ) -> None:
        self._repo = repo
        self._directory = directory
        self._policy = policy

    def select(self, now: datetime) -> Iterable[Any]:
        candidates = self._repo.PENDING_G11_open_unacknowledged(self._policy.priorities)
        return [i for i in candidates if self._policy.is_due(i, now)]

    def process(self, item: Any, now: datetime) -> Iterator[str]:
        fresh = self._repo.PENDING_G5_get_for_update(item.incident_id)
        if not self._policy.is_due(fresh, now):
            return  # acknowledged (or escalated) since select()

        target = self._directory.next_in_chain(fresh.PENDING_G15_escalation_level)
        if target is None:
            if fresh.PENDING_G4_mark_escalation_exhausted():
                yield "chain_exhausted"
            return

        fresh.PENDING_G15_escalate(target.user_id, target.level)
        yield "escalated"


def build_escalation(
    repo: IncidentRepository, directory: EscalationDirectory, cfg: Settings
) -> EscalationJob:
    return EscalationJob(repo, directory, EscalationPolicy(cfg.ESCALATION_AFTER_MINUTES))


def run_escalation(
    now: datetime, repo: IncidentRepository, directory: EscalationDirectory, cfg: Settings
) -> JobResult:
    return build_escalation(repo, directory, cfg).run(now)
