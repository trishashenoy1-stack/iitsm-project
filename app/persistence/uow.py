"""Unit of Work: one database transaction, its repositories and its events (P2).

    with uow_factory() as uow:
        incident = uow.incidents.get("INC1024")
        incident.acknowledge(actor=technician)     # P1's method, nothing else
        uow.commit()

On commit, in this order:
  1. every incident loaded or created through ``uow.incidents`` is written back,
  2. the audit steps collected during the transaction are appended,
  3. the database transaction commits,
  4. only then are the domain events published on the application bus, so
     notifications and P4's listeners can always load what the event is about (G18).

Implements app.p4_contracts.PENDING_P2_UnitOfWork, so P4's scheduler uses it as is.
"""

from __future__ import annotations

import logging
from typing import Any

from sqlalchemy.orm import Session, sessionmaker

from app.persistence.events import AmbientUnitOfWork, TransactionalEventBus
from app.persistence.journal import IncidentJournal, Step
from app.persistence.repositories import (
    AuditRepository,
    CategoryRepository,
    EmbeddingStore,
    EscalationDirectory,
    IncidentRepository,
    IntelligenceStore,
    ServiceRepository,
    SettingsRepository,
    SlaPolicyRepository,
    UserRepository,
)
from domain.clock import Clock
from domain.events import DomainEvent, EventBus

log = logging.getLogger(__name__)


class UnitOfWork:
    def __init__(self, session_factory: sessionmaker, bus: EventBus, clock: Clock) -> None:
        self._session_factory = session_factory
        self.session: Session = session_factory()
        self.app_bus = bus
        self.clock = clock
        self.journal = IncidentJournal()
        self.bus = TransactionalEventBus()
        self.bus.subscribe(DomainEvent, self.journal.record)

        self.users = UserRepository(self.session)
        self.services = ServiceRepository(self.session)
        self.categories = CategoryRepository(self.session)
        self.sla = SlaPolicyRepository(self.session)
        self.settings = SettingsRepository(self.session)
        self.audit = AuditRepository(self.session)
        self.incidents = IncidentRepository(self)
        self.intelligence = IntelligenceStore(self)
        self.embeddings = EmbeddingStore(self.session)
        self.escalation_directory = EscalationDirectory(self.session)
        self._closed = False
        AmbientUnitOfWork.push(self)

    def __enter__(self) -> UnitOfWork:
        return self

    def __exit__(self, exc_type: Any, *_rest: Any) -> None:
        if exc_type is not None:
            self.rollback()
        self.close()

    def tracks(self, incident_id: str) -> bool:
        return any(i.incident_id == incident_id for i in self.incidents.tracked())

    def commit(self) -> None:
        try:
            self.incidents.write_read_models()
            self.session.flush()  # incident rows first: audit steps point at them
            self.session.add_all(step.to_record() for step in self.journal.take_all())
            self.session.commit()
        except Exception:
            self.rollback()
            raise
        self.bus.flush_to(self.app_bus)

    def rollback(self) -> None:
        self.session.rollback()
        self.bus.discard()
        self.incidents.forget()
        surviving = self.journal.take_surviving()
        if surviving:
            self._write_after_rollback(surviving)

    def _write_after_rollback(self, steps: list[Step]) -> None:
        """Refused actions are still audited (business rule 8.1), in their own transaction."""
        session = self._session_factory()
        try:
            session.add_all(s.to_record() for s in steps if s.incident_id is not None)
            session.commit()
        except Exception:
            session.rollback()
            log.exception("could not audit %d refused actions", len(steps))
        finally:
            session.close()

    def close(self) -> None:
        if self._closed:
            return
        self._closed = True
        AmbientUnitOfWork.pop(self)
        self.session.close()


class UnitOfWorkFactory:
    """The callable P4's wiring takes (``uow_factory``)."""

    def __init__(self, session_factory: sessionmaker, bus: EventBus, clock: Clock) -> None:
        self.session_factory = session_factory
        self.bus = bus
        self.clock = clock

    def __call__(self) -> UnitOfWork:
        return UnitOfWork(self.session_factory, self.bus, self.clock)


class SlaEventRecorder:
    """Puts SLA warnings and breaches into the audit trail.

    P1's SLAMonitor publishes them on the application bus while a unit of work (the
    SLA job's) is checking the incident; the step joins that transaction. If no unit
    of work on this thread has the incident, it is written in a transaction of its own.
    """

    def __init__(self, uow_factory: UnitOfWorkFactory) -> None:
        self._uow_factory = uow_factory

    def subscribe(self, bus: EventBus) -> None:
        from domain.events import SLABreached, SLAWarning

        bus.subscribe(SLAWarning, self.on_sla_event)
        bus.subscribe(SLABreached, self.on_sla_event)

    def on_sla_event(self, event: Any) -> None:
        current = AmbientUnitOfWork.current()
        if current is not None and current.tracks(event.incident_id):
            current.journal.record(event)
            return
        uow = self._uow_factory()
        try:
            uow.journal.record(event)
            uow.commit()
        finally:
            uow.close()
