"""BatchJob: Template Method base for every background job.

`run()` is the fixed algorithm: select candidates, process each one, catch errors per
item, collect a JobResult. Subclasses supply only `select()` and `process()`.
"""

from __future__ import annotations

import logging
from abc import ABC, abstractmethod
from collections import Counter
from collections.abc import Iterable
from dataclasses import dataclass, field
from datetime import UTC, datetime
from typing import ClassVar, Generic, Protocol, TypeVar

log = logging.getLogger(__name__)


def utc_now() -> datetime:
    return datetime.now(UTC)


def require_aware(now: datetime) -> None:
    if now.tzinfo is None or now.utcoffset() is None:
        raise ValueError("naive datetime passed to a job; use timezone-aware UTC")


class HasId(Protocol):
    @property
    def incident_id(self) -> str: ...


T = TypeVar("T", bound=HasId)


@dataclass
class JobResult:
    job: str
    started_at: datetime
    scanned: int = 0
    actions: Counter[str] = field(default_factory=Counter)
    errors: list[tuple[str, str]] = field(default_factory=list)

    @property
    def ok(self) -> bool:
        return not self.errors


class BatchJob(ABC, Generic[T]):
    name: ClassVar[str]

    def run(self, now: datetime) -> JobResult:
        """Template method. Do not override."""
        require_aware(now)
        result = JobResult(job=self.name, started_at=now)
        for item in self.select(now):
            result.scanned += 1
            try:
                for action in self.process(item, now):
                    result.actions[action] += 1
            except Exception as exc:  # one bad incident must not abort the batch
                log.exception("job=%s incident=%s failed", self.name, item.incident_id)
                result.errors.append((item.incident_id, repr(exc)))
        log.info(
            "job=%s scanned=%d actions=%s errors=%d",
            self.name, result.scanned, dict(result.actions), len(result.errors),
        )
        return result

    @abstractmethod
    def select(self, now: datetime) -> Iterable[T]:
        """Return the candidates for this tick."""

    @abstractmethod
    def process(self, item: T, now: datetime) -> Iterable[str]:
        """Handle one candidate; yield a label for each action actually taken."""
