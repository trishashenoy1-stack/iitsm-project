"""Write P4's seed plan (scripts/seed.py) into the database (P2).

Reference data is upserted by natural key. Incidents are not inserted as rows: each
one is replayed through the same services the API uses, with a FakeClock set to the
plan's past times. So seeded incidents have a real audit trail, real SLA deadlines
from P1's tracker, and go through P1's permission and transition checks.
Running it twice creates nothing new (incidents are keyed by ``seed_key``).
"""

from __future__ import annotations

import logging
import os
from collections.abc import Iterable
from datetime import datetime, timedelta
from typing import Any

from sqlalchemy import select

from app.bootstrap import Backend
from app.db.models import (
    CategoryRecord,
    IncidentRecord,
    ServiceRecord,
    SlaPolicyRecord,
    TechnicianRecord,
    UserRecord,
)
from app.persistence.uow import UnitOfWorkFactory
from app.services.incidents import IncidentService, NewIncident
from domain.category import CategoryRegistry
from domain.clock import FakeClock
from domain.enums import Impact, Priority, Role, Urgency
from domain.events import EventBus
from domain.priority import MatrixPriorityStrategy

log = logging.getLogger(__name__)

CRITICALITY = {"HIGH": 5, "MEDIUM": 3, "LOW": 2}
ESCALATION_LEVEL = {"TEAM_LEAD": 1, "SYSTEM_ADMIN": 2, "IT_MANAGER": 3}
ORDER = ["ASSIGNED", "ACKNOWLEDGED", "IN_PROGRESS", "AWAITING_INFO", "RESOLVED", "VERIFIED",
         "CLOSED"]


def seed_password(production: bool) -> str:
    password = os.environ.get("SEED_PASSWORD", "")
    if not password:
        if production:
            raise RuntimeError("Set SEED_PASSWORD to seed a production database.")
        password = "demo1234"
    return password


def primary_role(roles: Iterable[str]) -> Role:
    roles = set(roles)
    if "TECHNICIAN" in roles:
        return Role.TECHNICIAN
    if roles & {"ADMIN", "SYSTEM_ADMIN", "IT_MANAGER"}:
        return Role.ADMIN
    return Role.EMPLOYEE


def levels_for(priority: Priority, criticality: int) -> tuple[Impact, Urgency, int] | None:
    """Impact, urgency and affected users that P1's matrix turns into ``priority``."""
    strategy = MatrixPriorityStrategy()
    for users in (5, 60):
        for impact in Impact:
            for urgency in Urgency:
                if strategy.calculate(impact, urgency, criticality, users) == priority:
                    return impact, urgency, users
    return None


def _next_user_id(session: Any, role: Role) -> str:
    prefix = {Role.EMPLOYEE: "E", Role.TECHNICIAN: "T", Role.ADMIN: "A"}[role]
    taken = session.scalars(select(UserRecord.id).where(UserRecord.id.like(f"{prefix}%")))
    numbers = [int(i[1:]) for i in taken if i[1:].isdigit()]
    return f"{prefix}{max(numbers, default=100) + 1:03d}"


def apply_seed_plan(plan: Any, backend: Backend | None = None) -> dict[str, int]:
    from app.config import get_settings

    backend = backend or Backend.build(get_settings(), with_p4=False)
    production = backend.settings.APP_ENV == "production"
    created = {"users": 0, "services": 0, "incidents": 0}
    ids: dict[str, str] = {}
    services: dict[str, ServiceRecord] = {}

    with backend.session_factory() as session:
        password_hash = backend.passwords.hash(seed_password(production))
        for user in plan.users:
            row = session.scalar(select(UserRecord).where(UserRecord.email == user.email))
            if row is None:
                role = primary_role(user.roles)
                row = UserRecord(
                    id=_next_user_id(session, role), email=user.email, name=user.name,
                    password_hash=password_hash, role=role.value, active=user.active,
                    escalation_level=next((ESCALATION_LEVEL[r] for r in user.roles
                                           if r in ESCALATION_LEVEL), None),
                    created_at=backend.clock.now(),
                )
                if role == Role.TECHNICIAN:
                    row.technician = TechnicianRecord(
                        skills=[s.lower() for s in user.skills],
                        experience_years=user.experience_years,
                        max_workload=max(user.capacity, 1), available=True,
                    )
                session.add(row)
                session.flush()
                created["users"] += 1
            ids[user.email] = row.id

        for number, service in enumerate(plan.services, start=1):
            row = session.scalar(select(ServiceRecord).where(ServiceRecord.name == service.name))
            if row is None:
                row = ServiceRecord(id=f"SVC-{number}", name=service.name,
                                    criticality=CRITICALITY[service.criticality], active=True)
                session.add(row)
                created["services"] += 1
            services[service.name] = row

        for name in CategoryRegistry.DEFAULT_NAMES:
            if session.get(CategoryRecord, name.upper()) is None:
                session.add(CategoryRecord(name=name.upper(), description="", active=True))

        for policy in plan.sla_policies:
            if session.get(SlaPolicyRecord, policy.priority) is None:
                session.add(SlaPolicyRecord(priority=policy.priority,
                                            response_minutes=policy.response_minutes,
                                            resolution_minutes=policy.resolution_minutes))
                session.flush()
        session.commit()
        existing = set(session.scalars(select(IncidentRecord.seed_key)
                                       .where(IncidentRecord.seed_key.is_not(None))))

    admin_id = next(ids[u.email] for u in plan.users if "ADMIN" in u.roles)
    new_ids = []
    for item in sorted(plan.incidents, key=lambda i: i.created_at):
        if item.key in existing:
            continue
        new_ids.append(_replay(backend, item, ids, services, admin_id))
        created["incidents"] += 1
    _run_intelligence(backend, new_ids)
    log.info("seeded %s", created)
    return created


def _run_intelligence(backend: Backend, incident_ids: list[str]) -> None:
    """Seeding uses a private bus (no notifications), so P4's listener never sees the
    new incidents. Run it here, so seeded duplicates are linked and embedded."""
    if not incident_ids:
        return
    try:
        from app.p4_wiring import wire_p4

        settings = backend.settings.model_copy(update={"INTELLIGENCE_ASYNC": False})
        runtime = wire_p4(settings, bus=EventBus(), uow_factory=backend.uow_factory,
                          clock=backend.clock, start_scheduler=False)
    except Exception:
        log.exception("P4 unavailable; seeded incidents are not checked for duplicates")
        return
    try:
        for incident_id in incident_ids:
            runtime.listener.handle_created(incident_id)
    finally:
        runtime.shutdown()


def _replay(backend: Backend, item: Any, ids: dict[str, str],
            services: dict[str, ServiceRecord], admin_id: str) -> str:
    clock = FakeClock(item.created_at)
    # A private bus: seeding must not send anyone notifications or e-mails.
    flow = IncidentService(UnitOfWorkFactory(backend.session_factory, EventBus(), clock))
    service = services[item.service]
    target = Priority[item.priority]
    levels = levels_for(target, service.criticality) or (Impact.LOW, Urgency.LOW, 1)
    reporter = ids[item.reporter]
    incident_id = flow.report(reporter, NewIncident(
        description=item.description, service_id=service.id, category=item.category,
        impact=levels[0].name, urgency=levels[1].name, affected_users=levels[2],
    ), seed_key=item.key, auto_assign=False)

    def at(moment: datetime | None, fallback: timedelta) -> None:
        wanted = moment or (clock.now() + fallback)
        if wanted > clock.now():
            clock.advance(seconds=(wanted - clock.now()).total_seconds())

    if levels_for(target, service.criticality) is None:
        at(None, timedelta(seconds=30))
        flow.set_priority(admin_id, incident_id, target.name,
                          "Seed data: set by the service desk")
    reached = ORDER.index(item.status) if item.status in ORDER else -1
    if item.assigned_to is None or reached < 0:
        return incident_id
    technician = ids[item.assigned_to]
    at(None, timedelta(minutes=1))
    flow.assign(admin_id, incident_id, technician)
    if reached >= ORDER.index("ACKNOWLEDGED"):
        at(item.acknowledged_at, timedelta(minutes=2))
        flow.act(technician, incident_id, "acknowledge", None)
    if reached >= ORDER.index("IN_PROGRESS"):
        at(None, timedelta(minutes=1))
        flow.act(technician, incident_id, "start_work", None)
    if item.status == "AWAITING_INFO":
        at(None, timedelta(minutes=2))
        flow.act(technician, incident_id, "request_info",
                 "Can you send a screenshot of the error?")
        return incident_id
    if reached >= ORDER.index("RESOLVED"):
        at(item.resolved_at, timedelta(minutes=30))
        flow.act(technician, incident_id, "resolve",
                 item.resolution_text or "Fixed and confirmed working.")
    if reached >= ORDER.index("VERIFIED"):
        at(None, timedelta(minutes=10))
        flow.act(reporter, incident_id, "verify", None)
    if reached >= ORDER.index("CLOSED"):
        at(None, timedelta(minutes=10))
        flow.act(admin_id, incident_id, "close", None)
    return incident_id
