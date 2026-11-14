"""Event plumbing between P1's domain and the database (P2).

Two problems this file solves:

1. P1's IncidentFactory publishes IncidentCreated before anything is saved (gap G18),
   so listeners that load the incident by id would miss it. Each unit of work gives
   its incidents a TransactionalEventBus: events are recorded in the audit journal
   straight away, but only reach the application bus after the database commit.

2. P1 has no Incident.restore() yet (gap G20). The repository rebuilds an incident by
   replaying its audit trail through P1's own methods. While that happens the bus is
   muted and a ReplayClock reports the original time of each step.
"""

from __future__ import annotations

import threading
from collections.abc import Iterator
from contextlib import contextmanager
from dataclasses import dataclass
from datetime import datetime
from typing import Any

from domain.clock import Clock
from domain.events import DomainEvent, EventBus


@dataclass(frozen=True)
class IncidentEscalated(DomainEvent):
    """Interim, until P1 adds escalation to the domain (gap G15)."""

    to_user_id: str
    level: int


@dataclass(frozen=True)
class EscalationExhausted(DomainEvent):
    """The escalation chain ran out (gap G4). Published once per incident."""


class ReplayClock(Clock):
    """Reports a fixed past time while replaying, then the live clock."""

    def __init__(self, live: Clock) -> None:
        self._live = live
        self._fixed: datetime | None = None

    def now(self) -> datetime:
        return self._fixed if self._fixed is not None else self._live.now()

    def set(self, moment: datetime) -> None:
        self._fixed = moment

    def go_live(self) -> None:
        self._fixed = None


class TransactionalEventBus(EventBus):
    """Local subscribers (the audit journal) run immediately; everything else gets the
    event from ``flush_to`` once the transaction has committed."""

    def __init__(self) -> None:
        super().__init__()
        self._outbox: list[Any] = []
        self._muted = 0

    @contextmanager
    def muted(self) -> Iterator[None]:
        self._muted += 1
        try:
            yield
        finally:
            self._muted -= 1

    def publish(self, event: Any) -> None:
        if self._muted:
            return
        super().publish(event)
        self._outbox.append(event)

    def flush_to(self, bus: EventBus) -> None:
        events, self._outbox = self._outbox, []
        for event in events:
            bus.publish(event)

    def discard(self) -> None:
        self._outbox = []


class AmbientUnitOfWork:
    """Which unit of work is open on this thread, if any.

    P1's SLAMonitor publishes SLA events on the application bus, not on the incident's
    own bus. The SLA listener uses this to put those events into the journal of the
    unit of work that is checking the incident, so they commit together.
    """

    _local = threading.local()

    @classmethod
    def push(cls, uow: Any) -> None:
        stack = getattr(cls._local, "stack", None)
        if stack is None:
            stack = cls._local.stack = []
        stack.append(uow)

    @classmethod
    def pop(cls, uow: Any) -> None:
        stack = getattr(cls._local, "stack", [])
        if uow in stack:
            stack.remove(uow)

    @classmethod
    def current(cls) -> Any | None:
        stack = getattr(cls._local, "stack", None)
        return stack[-1] if stack else None
