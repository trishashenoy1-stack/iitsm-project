"""Composition root (P2): builds every long-lived object exactly once.

main.py calls ``Backend.build(settings)`` on start-up; tests build one with an
in-memory database and a FakeClock. Nothing else constructs services.
"""

from __future__ import annotations

import logging
import os
from dataclasses import dataclass
from typing import Any

from sqlalchemy.engine import Engine
from sqlalchemy.orm import sessionmaker

from app.config import Settings
from app.db.models import Base
from app.db.session import build_engine, build_session_factory
from app.persistence.uow import SlaEventRecorder, UnitOfWorkFactory
from app.security import PasswordService, TokenService
from app.services.accounts import AccountService
from app.services.admin import AdminService
from app.services.incidents import IncidentService
from app.services.notification_rules import BACKEND_RULES
from app.services.notification_store import SqlNotificationRepository, SqlRecipientDirectory
from domain.clock import Clock, SystemClock
from domain.events import EventBus
from notifications.module import NotificationModule, email_gateway_from_env

log = logging.getLogger(__name__)


@dataclass
class Backend:
    settings: Settings
    engine: Engine
    session_factory: sessionmaker
    bus: EventBus
    clock: Clock
    uow_factory: UnitOfWorkFactory
    passwords: PasswordService
    tokens: TokenService
    accounts: AccountService
    incidents: IncidentService
    admin: AdminService
    notifications: NotificationModule
    p4: Any = None

    @classmethod
    def build(cls, settings: Settings, clock: Clock | None = None,
              engine: Engine | None = None, with_p4: bool = True) -> Backend:
        clock = clock or SystemClock()
        engine = engine or build_engine(settings.DATABASE_URL)
        if settings.CREATE_TABLES_ON_START:
            Base.metadata.create_all(engine)
        session_factory = build_session_factory(engine)
        bus = EventBus()  # the application bus: notifications, P4, SLA audit
        uow_factory = UnitOfWorkFactory(session_factory, bus, clock)
        SlaEventRecorder(uow_factory).subscribe(bus)
        _ensure_counter(session_factory)

        passwords = PasswordService()
        tokens = TokenService.from_settings(settings.JWT_SECRET, settings.JWT_EXPIRE_MINUTES,
                                            production=settings.APP_ENV == "production")
        notifications = NotificationModule(
            bus, SqlRecipientDirectory(session_factory),
            repository=SqlNotificationRepository(session_factory), rules=BACKEND_RULES,
            email_gateway=email_gateway_from_env(_email_env(settings)),
        )
        backend = cls(
            settings=settings, engine=engine, session_factory=session_factory, bus=bus,
            clock=clock, uow_factory=uow_factory, passwords=passwords, tokens=tokens,
            accounts=AccountService(uow_factory, passwords, tokens),
            incidents=IncidentService(
                uow_factory, resubmit_window_seconds=settings.DUPLICATE_RESUBMIT_SECONDS),
            admin=AdminService(uow_factory, passwords),
            notifications=notifications,
        )
        if with_p4:
            backend.p4 = _wire_p4(settings, bus, uow_factory, clock)
            backend._connect_p4()
        return backend

    def start_p4(self) -> None:
        if self.p4 is None:
            self.p4 = _wire_p4(self.settings, self.bus, self.uow_factory, self.clock)
            self._connect_p4()

    def _connect_p4(self) -> None:
        """Hand P4's categorizer to the report use case, so "Not sure" reports are
        classified before a technician is chosen."""
        if self.p4 is not None:
            self.incidents.set_category_predictor(self.p4.predict_category)

    def start(self) -> None:
        self.notifications.start()

    def stop(self) -> None:
        self.notifications.stop()
        if self.p4 is not None:
            self.p4.shutdown()
        self.engine.dispose()


def _email_env(settings: Settings) -> dict[str, str]:
    """EMAIL_BACKEND and SMTP_* from the process environment, falling back to .env.

    pydantic-settings reads .env for Settings only, so without this a local
    `uvicorn app.main:app` silently ignored EMAIL_BACKEND=smtp in .env. Tests
    (APP_ENV=test) never read .env, so they can't send real mail.
    """
    env: dict[str, str] = {}
    if settings.APP_ENV != "test":
        from dotenv import dotenv_values

        env_file = settings.model_config.get("env_file") or ".env"
        env = {k: v for k, v in dotenv_values(str(env_file)).items() if v is not None}
    env.update(os.environ)
    return env


def _wire_p4(settings: Settings, bus: EventBus, uow_factory: UnitOfWorkFactory,
             clock: Clock) -> Any:
    """P4's lifespan snippet from app/p4_wiring.py. If P4's optional ML pieces can't
    load, the API still runs and /api/health/p4 says what is off."""
    try:
        from app.p4_wiring import wire_p4

        return wire_p4(settings, bus=bus, clock=clock, uow_factory=uow_factory,
                       start_scheduler=settings.SCHEDULER_ENABLED)
    except Exception:
        log.exception("P4 components failed to start; continuing without them")
        return None


def _ensure_counter(session_factory: sessionmaker) -> None:
    """Create the incident-number counter row once, so first reports never race to insert it."""
    from sqlalchemy import func, select
    from sqlalchemy.exc import IntegrityError, OperationalError, ProgrammingError

    from app.db.models import IncidentRecord, SettingRecord
    from app.persistence.repositories import IncidentRepository

    with session_factory() as session:
        try:
            if session.get(SettingRecord, IncidentRepository.COUNTER_KEY) is None:
                highest = session.scalar(select(func.max(IncidentRecord.number))) or 1000
                session.add(SettingRecord(key=IncidentRepository.COUNTER_KEY, value=highest))
                session.commit()
        except (IntegrityError, OperationalError, ProgrammingError):
            # Another process created it first, or the tables don't exist yet (migrations
            # not run): next_number() creates it on first use.
            session.rollback()
