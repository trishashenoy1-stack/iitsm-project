"""Repositories: map database rows to and from P1's domain classes (P2).

Each repository belongs to one UnitOfWork and shares its session. Nothing here commits;
the unit of work does, once, for everything that changed.
"""

from __future__ import annotations

from collections.abc import Iterable, Mapping
from dataclasses import dataclass
from datetime import datetime, timedelta
from typing import TYPE_CHECKING, Any

import numpy as np
from sqlalchemy import func, or_, select

from app.db.models import (
    CategoryRecord,
    EmbeddingRecord,
    IncidentEventRecord,
    IncidentLinkRecord,
    IncidentRecord,
    ServiceRecord,
    SettingRecord,
    SlaPolicyRecord,
    TechnicianRecord,
    UserRecord,
)
from app.errors import IncidentNotFoundError, UserNotFoundError
from app.p4_contracts import DONE_STATUSES, UNACKNOWLEDGED_STATUSES, Vector
from app.persistence.journal import Step
from app.persistence.replay import IncidentInputs, PersistedIncident, rebuild, sla_facts
from domain.category import Category, CategoryRegistry
from domain.enums import Impact, Priority, Role, Status, Urgency
from domain.exceptions import ServiceNotFoundError
from domain.service import ITService
from domain.sla import SLAPolicy
from domain.users import Administrator, Employee, Technician, User

if TYPE_CHECKING:
    from sqlalchemy.orm import Session

    from app.persistence.uow import UnitOfWork

DONE_VALUES = [s.value for s in DONE_STATUSES]


# ======================================================================================
# Users and technicians
# ======================================================================================
class UserRepository:
    def __init__(self, session: Session) -> None:
        self._session = session
        self._cache: dict[str, User] = {}

    def record(self, user_id: str) -> UserRecord:
        row = self._session.get(UserRecord, user_id)
        if row is None:
            raise UserNotFoundError(f"User {user_id} doesn't exist")
        return row

    def by_email(self, email: str) -> UserRecord | None:
        return self._session.scalar(select(UserRecord).where(UserRecord.email == email))

    def all(self) -> list[UserRecord]:
        return list(self._session.scalars(select(UserRecord).order_by(UserRecord.id)))

    def technicians(self) -> list[UserRecord]:
        return list(self._session.scalars(
            select(UserRecord).where(UserRecord.role == Role.TECHNICIAN.value)
            .order_by(UserRecord.id)
        ))

    def lock_technicians(self) -> None:
        """Row-lock technician profiles, so two assignments can't both take the last slot."""
        self._session.execute(select(TechnicianRecord).with_for_update()).all()

    def add(self, row: UserRecord) -> UserRecord:
        self._session.add(row)
        self._session.flush()
        return row

    def next_id(self, role: Role) -> str:
        prefix = {Role.EMPLOYEE: "E", Role.TECHNICIAN: "T", Role.ADMIN: "A"}[role]
        ids = self._session.scalars(select(UserRecord.id).where(UserRecord.id.like(f"{prefix}%")))
        numbers = [int(i[1:]) for i in ids if i[1:].isdigit()]
        return f"{prefix}{max(numbers, default=100) + 1:03d}"

    def active_counts(self) -> dict[str, int]:
        """Open incidents per technician. P1 frees capacity only on close, so we count
        everything not closed."""
        rows = self._session.execute(
            select(IncidentRecord.technician_id, func.count())
            .where(IncidentRecord.technician_id.is_not(None),
                   IncidentRecord.status != Status.CLOSED.value)
            .group_by(IncidentRecord.technician_id)
        )
        return {tech: count for tech, count in rows}

    def domain(self, user_id: str, fresh: bool = False) -> User:
        """The P1 object for a user. Cached per unit of work, so every incident sees the
        same Technician and capacity checks add up."""
        if not fresh and user_id in self._cache:
            return self._cache[user_id]
        row = self.record(user_id)
        user = self._build(row, self.active_counts().get(user_id, 0))
        if not fresh:
            self._cache[user_id] = user
        return user

    def domain_technicians(self) -> list[Technician]:
        counts = self.active_counts()
        result = []
        for row in self.technicians():
            if row.id not in self._cache:
                self._cache[row.id] = self._build(row, counts.get(row.id, 0))
            user = self._cache[row.id]
            if isinstance(user, Technician):
                result.append(user)
        return result

    @staticmethod
    def _build(row: UserRecord, active_count: int) -> User:
        user: User
        if row.role == Role.TECHNICIAN.value:
            profile = row.technician or TechnicianRecord(
                skills=[], experience_years=0, max_workload=5, available=True
            )
            tech = Technician(row.id, row.name, profile.skills or [],
                              experience_years=profile.experience_years,
                              max_workload=profile.max_workload)
            # Rebuild the workload with P1's own method. Capped at capacity: if an
            # admin lowered the limit below the open count, the technician is just full.
            for _ in range(min(active_count, tech.max_workload)):
                tech.take_incident()
            tech.set_available(profile.available)
            user = tech
        elif row.role == Role.ADMIN.value:
            user = Administrator(row.id, row.name)
        else:
            user = Employee(row.id, row.name)
        if not row.active:
            user.deactivate()
        return user


# ======================================================================================
# Reference data
# ======================================================================================
class ServiceRepository:
    def __init__(self, session: Session) -> None:
        self._session = session

    def all(self) -> list[ServiceRecord]:
        return list(self._session.scalars(select(ServiceRecord).order_by(ServiceRecord.id)))

    def record(self, service_id: str) -> ServiceRecord:
        row = self._session.get(ServiceRecord, service_id)
        if row is None:
            raise ServiceNotFoundError(f"Service {service_id} doesn't exist")
        return row

    def by_name(self, name: str) -> ServiceRecord | None:
        return self._session.scalar(
            select(ServiceRecord).where(func.lower(ServiceRecord.name) == name.lower())
        )

    def domain(self, service_id: str) -> ITService:
        row = self.record(service_id)
        service = ITService(row.id, row.name, row.criticality)
        if not row.active:
            service.deactivate()
        return service

    def add(self, row: ServiceRecord) -> ServiceRecord:
        self._session.add(row)
        self._session.flush()
        return row


class CategoryRepository:
    def __init__(self, session: Session) -> None:
        self._session = session

    def all(self) -> list[CategoryRecord]:
        return list(self._session.scalars(select(CategoryRecord).order_by(CategoryRecord.name)))

    def record(self, name: str) -> CategoryRecord | None:
        return self._session.get(CategoryRecord, name.strip().upper())

    def registry(self) -> CategoryRegistry:
        registry = CategoryRegistry()
        for row in self.all():
            registry.add(row.name, row.description)
            if not row.active:
                registry.deactivate(row.name)
        return registry

    def add(self, row: CategoryRecord) -> CategoryRecord:
        self._session.add(row)
        self._session.flush()
        return row


class SlaPolicyRepository:
    def __init__(self, session: Session) -> None:
        self._session = session

    def all(self) -> list[SlaPolicyRecord]:
        rows = {r.priority: r for r in self._session.scalars(select(SlaPolicyRecord))}
        defaults = SLAPolicy.default()
        result = []
        for priority in Priority:
            row = rows.get(priority.name)
            if row is None:
                response, resolution = defaults.targets_for(priority)
                row = SlaPolicyRecord(priority=priority.name,
                                      response_minutes=int(response.total_seconds() // 60),
                                      resolution_minutes=int(resolution.total_seconds() // 60))
            result.append(row)
        return result

    def get_or_create(self, priority: Priority) -> SlaPolicyRecord:
        row = self._session.get(SlaPolicyRecord, priority.name)
        if row is None:
            row = next(r for r in self.all() if r.priority == priority.name)
            self._session.add(row)
        return row

    def policy(self) -> SLAPolicy:
        return SLAPolicy({
            Priority[r.priority]: (timedelta(minutes=r.response_minutes),
                                   timedelta(minutes=r.resolution_minutes))
            for r in self.all()
        })


class SettingsRepository:
    def __init__(self, session: Session) -> None:
        self._session = session

    def get(self, key: str, default: Any = None) -> Any:
        row = self._session.get(SettingRecord, key)
        return default if row is None else row.value

    def set(self, key: str, value: Any) -> None:
        row = self._session.get(SettingRecord, key)
        if row is None:
            self._session.add(SettingRecord(key=key, value=value))
        else:
            row.value = value


# ======================================================================================
# Audit trail (append-only)
# ======================================================================================
class AuditRepository:
    """Read access to the journal. There is deliberately no update or delete."""

    def __init__(self, session: Session) -> None:
        self._session = session

    def for_incidents(self, incident_ids: Iterable[str]) -> dict[str, list[Step]]:
        ids = list(incident_ids)
        result: dict[str, list[Step]] = {i: [] for i in ids}
        if not ids:
            return result
        rows = self._session.scalars(
            select(IncidentEventRecord).where(IncidentEventRecord.incident_id.in_(ids))
            .order_by(IncidentEventRecord.id)
        )
        for row in rows:
            result[row.incident_id or ""].append(Step.of(row))
        return result

    def latest(self, limit: int = 500, incident_id: str | None = None) -> list[Step]:
        query = select(IncidentEventRecord).order_by(IncidentEventRecord.id.desc()).limit(limit)
        if incident_id:
            query = query.where(IncidentEventRecord.incident_id == incident_id)
        return [Step.of(r) for r in self._session.scalars(query)]

    def update(self, *_args: Any, **_kwargs: Any) -> None:
        raise PermissionError("Audit entries are append-only and cannot be changed")

    def delete(self, *_args: Any, **_kwargs: Any) -> None:
        raise PermissionError("Audit entries are append-only and cannot be deleted")


# ======================================================================================
# Incidents
# ======================================================================================
@dataclass
class _Tracked:
    record: IncidentRecord
    incident: PersistedIncident
    stored_steps: list[Step]


class IncidentRepository:
    """Loads P1 Incidents (rebuilt from their audit trail) and saves them on commit.

    Implements app.p4_contracts.IncidentRepository for P4's jobs and listeners.
    Incidents loaded through it are tracked: whatever P1 methods are called on them,
    the unit of work writes the result back when it commits.
    """

    def __init__(self, uow: UnitOfWork) -> None:
        self._uow = uow
        self._session: Session = uow.session
        self._tracked: dict[str, _Tracked] = {}

    # ---- loading ---------------------------------------------------------------------
    def get(self, incident_id: str) -> PersistedIncident:
        return self._load(incident_id, lock=False)

    def get_for_update(self, incident_id: str) -> PersistedIncident:
        return self._load(incident_id, lock=True)

    PENDING_G5_get_for_update = get_for_update

    def record(self, incident_id: str) -> IncidentRecord:
        row = self._session.get(IncidentRecord, incident_id)
        if row is None:
            raise IncidentNotFoundError(f"Incident {incident_id} doesn't exist")
        return row

    def _load(self, incident_id: str, lock: bool) -> PersistedIncident:
        if incident_id in self._tracked:
            if lock:
                self._session.execute(
                    select(IncidentRecord.id).where(IncidentRecord.id == incident_id)
                    .with_for_update()
                )
            return self._tracked[incident_id].incident
        query = select(IncidentRecord).where(IncidentRecord.id == incident_id)
        if lock:
            query = query.with_for_update()
        row = self._session.scalar(query)
        if row is None:
            raise IncidentNotFoundError(f"Incident {incident_id} doesn't exist")
        return self._rebuild(row)

    def _rebuild(self, row: IncidentRecord) -> PersistedIncident:
        steps = self._uow.audit.for_incidents([row.id])[row.id]
        users = self._uow.users
        closed = row.status == Status.CLOSED.value
        registry = self._uow.categories.registry()
        category = None
        if row.category:
            try:
                category = registry.get(row.category)
            except Exception:
                category = Category(row.category)
        inputs = IncidentInputs(
            incident_id=row.id, description=row.description, created_at=row.created_at,
            reporter=users.domain(row.reporter_id),
            service=self._uow.services.domain(row.service_id),
            category=category, impact=Impact[row.impact], urgency=Urgency[row.urgency],
            affected_users=row.affected_users,
        )
        incident = rebuild(
            inputs, steps,
            # A closed incident's replay ends with close(), which frees capacity on the
            # technician object; give it a private copy so live counts aren't touched.
            technician=lambda tid: users.domain(tid, fresh=closed),
            policy=self._uow.sla.policy(), live_clock=self._uow.clock, bus=self._uow.bus,
        )
        self._tracked[row.id] = _Tracked(row, incident, steps)
        return incident

    def _many(self, query: Any) -> list[PersistedIncident]:
        return [self._tracked[r.id].incident if r.id in self._tracked else self._rebuild(r)
                for r in self._session.scalars(query.order_by(IncidentRecord.created_at))]

    # ---- queries P4 needs (app.p4_contracts.IncidentRepository) ---------------------
    def open_incidents(self) -> list[PersistedIncident]:
        return self._many(select(IncidentRecord).where(IncidentRecord.status.not_in(DONE_VALUES)))

    def open_since(self, t: datetime, exclude_id: str | None = None) -> list[PersistedIncident]:
        query = select(IncidentRecord).where(
            IncidentRecord.status.not_in(DONE_VALUES), IncidentRecord.created_at >= t
        )
        if exclude_id:
            query = query.where(IncidentRecord.id != exclude_id)
        return self._many(query)

    def resolved_with_text(self) -> list[PersistedIncident]:
        return self._many(select(IncidentRecord).where(
            IncidentRecord.status.in_(DONE_VALUES), IncidentRecord.resolution.is_not(None),
            IncidentRecord.resolution != "",
        ))

    def resolved_before(self, t: datetime) -> list[PersistedIncident]:
        return self._many(select(IncidentRecord).where(
            IncidentRecord.status == Status.RESOLVED.value, IncidentRecord.resolved_at < t
        ))

    def PENDING_G11_open_unacknowledged(
        self, priorities: Iterable[Priority]
    ) -> list[PersistedIncident]:
        return self._many(select(IncidentRecord).where(
            IncidentRecord.status.in_([s.value for s in UNACKNOWLEDGED_STATUSES]),
            IncidentRecord.priority.in_([p.name for p in priorities]),
            IncidentRecord.escalation_exhausted.is_(False),
        ))

    def PENDING_G10_related_links_since(self, t: datetime) -> list[tuple[str, str, float]]:
        rows = self._session.scalars(
            select(IncidentLinkRecord).where(IncidentLinkRecord.created_at >= t)
        )
        return [(r.incident_a, r.incident_b, r.score) for r in rows]

    # ---- creating and saving -------------------------------------------------------
    COUNTER_KEY = "incident_counter"

    def next_number(self) -> int:
        """Next incident number, under a row lock held until commit, so two reports at
        the same moment can't both get INC1001."""
        counter = self._session.scalar(
            select(SettingRecord).where(SettingRecord.key == self.COUNTER_KEY).with_for_update()
        )
        highest = self._session.scalar(select(func.max(IncidentRecord.number))) or 1000
        if counter is None:
            counter = SettingRecord(key=self.COUNTER_KEY, value=highest)
            self._session.add(counter)
        number = max(int(counter.value), highest) + 1
        counter.value = number
        self._session.flush()
        return number

    def add(self, incident: PersistedIncident, seed_key: str | None = None) -> None:
        """Track a new incident from P1's IncidentFactory. Inserted on commit."""
        domain = incident.domain
        row = IncidentRecord(
            id=domain.incident_id, number=int(domain.incident_id.removeprefix("INC")),
            description=domain.description, reporter_id=domain.reporter.user_id,
            service_id=domain.service.service_id,
            category=domain.category.name if domain.category else None,
            impact=domain.impact.name, urgency=domain.urgency.name,
            affected_users=domain.affected_users, created_at=incident.PENDING_G13_created_at,
            seed_key=seed_key, paused_seconds=0, escalation_level=0,
        )
        self._tracked[domain.incident_id] = _Tracked(row, incident, [])
        self._session.add(row)

    def tracked(self) -> list[PersistedIncident]:
        return [t.incident for t in self._tracked.values()]

    def steps(self, incident_id: str) -> list[Step]:
        """Stored plus not-yet-committed steps of a tracked incident."""
        tracked = self._tracked.get(incident_id)
        stored = tracked.stored_steps if tracked else []
        return stored + self._uow.journal.pending_for(incident_id)

    def write_read_models(self) -> None:
        policy = self._uow.sla.policy()
        defaults = SLAPolicy.default()
        for incident_id, tracked in self._tracked.items():
            row, incident = tracked.record, tracked.incident
            domain = incident.domain
            facts = sla_facts(self.steps(incident_id))
            targets = (policy if policy.has_targets_for(domain.priority) else defaults) \
                .targets_for(domain.priority)
            row.status = domain.status.value
            row.priority = domain.priority.name
            row.technician_id = domain.technician.user_id if domain.technician else None
            row.category = domain.category.name if domain.category else row.category
            row.resolution = domain.resolution
            row.feedback_rating = domain.feedback.rating if domain.feedback else None
            row.feedback_comment = domain.feedback.comment if domain.feedback else None
            row.response_target_seconds = int(targets[0].total_seconds())
            row.resolution_target_seconds = int(targets[1].total_seconds())
            row.responded_at = facts.responded_at
            row.resolved_at = facts.resolved_at
            row.paused_at = facts.paused_at
            row.paused_seconds = facts.paused_seconds
            row.info_request = facts.info_request
            # Monotonic: an SLA breach recorded elsewhere is never un-set here.
            row.response_breached = bool(row.response_breached) or facts.response_breached
            row.resolution_breached = bool(row.resolution_breached) or facts.resolution_breached
            row.escalation_level = incident.PENDING_G15_escalation_level
            row.last_escalated_at = incident.PENDING_G2_last_escalated_at
            row.escalation_exhausted = incident.escalation_exhausted
            row.updated_at = self._uow.clock.now()

    def forget(self) -> None:
        self._tracked.clear()

    # ---- reads for the API (plain rows, no replay) -----------------------------------
    def search(self, filters: Mapping[str, str], viewer: UserRecord | None = None,
               limit: int | None = None) -> list[IncidentRecord]:
        query = select(IncidentRecord)
        if viewer is not None and viewer.role != Role.ADMIN.value:
            query = query.where(or_(IncidentRecord.reporter_id == viewer.id,
                                    IncidentRecord.technician_id == viewer.id))
        f = {k: (v or "").strip() for k, v in filters.items()}
        if f.get("id"):
            query = query.where(IncidentRecord.id.ilike(f"%{f['id']}%"))
        if f.get("status"):
            query = query.where(IncidentRecord.status == f["status"])
        if f.get("priority"):
            query = query.where(IncidentRecord.priority == f["priority"])
        if f.get("category"):
            query = query.where(IncidentRecord.category == f["category"].upper())
        if f.get("service"):
            query = query.join(ServiceRecord, ServiceRecord.id == IncidentRecord.service_id) \
                .where(or_(ServiceRecord.name == f["service"], ServiceRecord.id == f["service"]))
        if f.get("technician"):
            query = query.where(IncidentRecord.technician_id == f["technician"])
        if f.get("from"):
            query = query.where(IncidentRecord.created_at >= _day_start(f["from"]))
        if f.get("to"):
            query = query.where(IncidentRecord.created_at < _day_start(f["to"]) + timedelta(days=1))
        query = query.order_by(IncidentRecord.created_at.desc())
        if limit:
            query = query.limit(limit)
        return list(self._session.scalars(query))


def _day_start(value: str) -> datetime:
    from app.services.clocking import DISPLAY_TZ

    try:
        day = datetime.fromisoformat(value)
    except ValueError as error:
        from domain.exceptions import ValidationError

        raise ValidationError(f"'{value}' is not a date (use YYYY-MM-DD)") from error
    return day.replace(tzinfo=DISPLAY_TZ) if day.tzinfo is None else day


# ======================================================================================
# What P4 stores
# ======================================================================================
class IntelligenceStore:
    """app.p4_contracts.IntelligenceSink: duplicate links and suggested categories."""

    def __init__(self, uow: UnitOfWork) -> None:
        self._uow = uow

    def link_related(self, a: str, b: str, score: float) -> None:
        session = self._uow.session
        first, second = sorted((a, b))
        exists = session.scalar(select(IncidentLinkRecord).where(
            IncidentLinkRecord.incident_a == first, IncidentLinkRecord.incident_b == second
        ))
        if exists is None:
            session.add(IncidentLinkRecord(incident_a=first, incident_b=second, score=score,
                                           created_at=self._uow.clock.now()))
            self._uow.journal.add(Step(a, self._uow.clock.now(), "SYSTEM", "possible_duplicate",
                                       payload={"other_id": b, "score": score}))

    def set_suggested_category(self, incident_id: str, category: str, confidence: float) -> None:
        row = self._uow.incidents.record(incident_id)
        row.suggested_category = category
        row.suggested_category_confidence = confidence
        self._uow.journal.add(Step(incident_id, self._uow.clock.now(), "SYSTEM",
                                   "suggested_category",
                                   payload={"category": category, "confidence": confidence}))

    def duplicates_of(self, incident_id: str) -> list[tuple[str, float]]:
        rows = self._uow.session.scalars(select(IncidentLinkRecord).where(
            or_(IncidentLinkRecord.incident_a == incident_id,
                IncidentLinkRecord.incident_b == incident_id)
        ).order_by(IncidentLinkRecord.score.desc()))
        return [(r.incident_b if r.incident_a == incident_id else r.incident_a, r.score)
                for r in rows]


class EmbeddingStore:
    """app.p4_contracts.PENDING_G6_EmbeddingStore, as float32 bytes."""

    def __init__(self, session: Session) -> None:
        self._session = session

    def save(self, incident_id: str, vector: Vector) -> None:
        data = np.asarray(vector, dtype=np.float32)
        row = self._session.get(EmbeddingRecord, incident_id)
        if row is None:
            self._session.add(EmbeddingRecord(incident_id=incident_id, dim=data.size,
                                              vector=data.tobytes()))
        else:
            row.dim, row.vector = data.size, data.tobytes()

    def get_many(self, incident_ids: Iterable[str]) -> Mapping[str, Vector]:
        ids = list(incident_ids)
        if not ids:
            return {}
        rows = self._session.scalars(
            select(EmbeddingRecord).where(EmbeddingRecord.incident_id.in_(ids))
        )
        return {r.incident_id: np.frombuffer(r.vector, dtype=np.float32) for r in rows}


@dataclass(frozen=True)
class EscalationTarget:
    user_id: str
    level: int


class EscalationDirectory:
    """app.p4_contracts.EscalationDirectory over users.escalation_level.

    P1 has no TEAM_LEAD / SYSTEM_ADMIN / IT_MANAGER roles yet (G17), so the chain is a
    per-user level that admins set: 1 team lead, 2 system admin, 3 IT manager.
    """

    def __init__(self, session: Session) -> None:
        self._session = session

    def next_in_chain(self, level: int) -> EscalationTarget | None:
        row = self._session.scalar(
            select(UserRecord).where(UserRecord.escalation_level > level,
                                     UserRecord.active.is_(True))
            .order_by(UserRecord.escalation_level, UserRecord.id)
        )
        return None if row is None else EscalationTarget(row.id, int(row.escalation_level or 0))
