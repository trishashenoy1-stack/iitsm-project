"""Administrator use cases and reports (P2)."""

from __future__ import annotations

from collections import Counter
from collections.abc import Callable
from datetime import datetime, timedelta
from typing import Any

from sqlalchemy import select

from app.db.models import (
    CategoryRecord,
    IncidentRecord,
    ServiceRecord,
    TechnicianRecord,
    UserRecord,
)
from app.errors import ConflictError, NotFoundError
from app.persistence.uow import UnitOfWork
from app.security import PasswordService
from app.services.accounts import check_password, normalise_email
from app.services.assignment import AssignmentPolicy
from app.services.clocking import DISPLAY_TZ
from app.services.views import DONE, iso, sla_out, user_out
from domain.enums import Priority, Role, Status
from domain.exceptions import ValidationError


def _criticality(value: Any) -> int:
    if isinstance(value, bool) or not isinstance(value, int) or not 1 <= value <= 5:
        raise ValidationError("Criticality must be a whole number from 1 to 5.")
    return value


def _whole(value: Any, minimum: int, message: str) -> int:
    if isinstance(value, bool) or not isinstance(value, int) or value < minimum:
        raise ValidationError(message)
    return value


def technician_out(row: UserRecord, active: int) -> dict[str, Any]:
    profile = row.technician
    return {
        "id": row.id, "name": row.name,
        "skills": [s.upper() for s in (profile.skills if profile else [])],
        "experienceYears": profile.experience_years if profile else 0,
        "maxWorkload": profile.max_workload if profile else 5,
        "available": profile.available if profile else False,
        "activeCount": active,
    }


def service_out(row: ServiceRecord) -> dict[str, Any]:
    return {"id": row.id, "name": row.name, "criticality": row.criticality, "active": row.active}


def category_out(row: CategoryRecord) -> dict[str, Any]:
    return {"name": row.name, "description": row.description, "active": row.active}


class AdminService:
    def __init__(self, uow_factory: Callable[[], UnitOfWork], passwords: PasswordService) -> None:
        self._uow_factory = uow_factory
        self._passwords = passwords

    # ---- users ----------------------------------------------------------------------
    def list_users(self) -> list[dict[str, Any]]:
        with self._uow_factory() as uow:
            return [{**user_out(u), "active": u.active} for u in uow.users.all()]

    def create_user(self, data: dict[str, Any]) -> dict[str, Any]:
        name = (data.get("name") or "").strip()
        if not name:
            raise ValidationError("Name is required.")
        email = normalise_email(data.get("email") or "")
        try:
            role = Role(data.get("role"))
        except ValueError as error:
            raise ValidationError("Choose a role.") from error
        password = data.get("password") or ""
        check_password(password)
        with self._uow_factory() as uow:
            if uow.users.by_email(email) is not None:
                raise ConflictError("An account with that email already exists.",
                                    code="EMAIL_TAKEN")
            row = UserRecord(id=uow.users.next_id(role), email=email, name=name,
                             password_hash=self._passwords.hash(password), role=role.value,
                             active=True, created_at=uow.clock.now())
            if role == Role.TECHNICIAN:
                row.technician = TechnicianRecord(skills=[], experience_years=0,
                                                  max_workload=5, available=True)
            uow.users.add(row)
            uow.commit()
            return {**user_out(row), "active": True}

    def update_user(self, actor_id: str, user_id: str, changes: dict[str, Any]) -> dict[str, Any]:
        with self._uow_factory() as uow:
            row = uow.users.record(user_id)
            if "name" in changes:
                name = (changes["name"] or "").strip()
                if not name:
                    raise ValidationError("Name is required.")
                row.name = name
            if "active" in changes:
                if changes["active"] is False and user_id == actor_id:
                    raise ConflictError("You can't deactivate your own account.")
                row.active = bool(changes["active"])
            if "escalationLevel" in changes:
                level = changes["escalationLevel"]
                row.escalation_level = None if level in (None, 0) else _whole(
                    level, 1, "Escalation level must be 1, 2 or 3.")
            uow.commit()
            return {**user_out(row), "active": row.active}

    # ---- technicians ----------------------------------------------------------------
    def list_technicians(self) -> list[dict[str, Any]]:
        with self._uow_factory() as uow:
            counts = uow.users.active_counts()
            return [technician_out(r, counts.get(r.id, 0)) for r in uow.users.technicians()]

    def update_technician(self, user_id: str, changes: dict[str, Any]) -> dict[str, Any]:
        with self._uow_factory() as uow:
            row = uow.users.record(user_id)
            if row.role != Role.TECHNICIAN.value:
                raise NotFoundError("That technician doesn't exist.")
            profile = row.technician or TechnicianRecord(user_id=row.id)
            if "skills" in changes:
                skills = changes["skills"] or []
                if not isinstance(skills, list):
                    raise ValidationError("Skills must be a list.")
                profile.skills = sorted({str(s).strip().lower() for s in skills if str(s).strip()})
            if "experienceYears" in changes:
                profile.experience_years = _whole(changes["experienceYears"], 0,
                                                  "Experience can't be negative.")
            if "maxWorkload" in changes:
                profile.max_workload = _whole(changes["maxWorkload"], 1,
                                              "Maximum workload must be at least 1.")
            if "available" in changes:
                profile.available = bool(changes["available"])
            row.technician = profile
            uow.commit()
            return technician_out(row, uow.users.active_counts().get(row.id, 0))

    # ---- services ---------------------------------------------------------------------
    def list_services(self, active_only: bool = False) -> list[dict[str, Any]]:
        with self._uow_factory() as uow:
            rows = [r for r in uow.services.all() if r.active or not active_only]
            return [service_out(r) for r in rows]

    def create_service(self, data: dict[str, Any]) -> dict[str, Any]:
        name = (data.get("name") or "").strip()
        if not name:
            raise ValidationError("Service name is required.")
        criticality = _criticality(data.get("criticality"))
        with self._uow_factory() as uow:
            if uow.services.by_name(name) is not None:
                raise ConflictError("A service with that name already exists.")
            row = uow.services.add(ServiceRecord(id=f"SVC-{len(uow.services.all()) + 1}",
                                                 name=name, criticality=criticality,
                                                 active=True))
            uow.commit()
            return service_out(row)

    def update_service(self, service_id: str, changes: dict[str, Any]) -> dict[str, Any]:
        with self._uow_factory() as uow:
            row = uow.services.record(service_id)
            if "name" in changes:
                name = (changes["name"] or "").strip()
                if not name:
                    raise ValidationError("Service name is required.")
                other = uow.services.by_name(name)
                if other is not None and other.id != row.id:
                    raise ConflictError("A service with that name already exists.")
                row.name = name
            if "criticality" in changes:
                row.criticality = _criticality(changes["criticality"])
            if "active" in changes:
                row.active = bool(changes["active"])
            uow.commit()
            return service_out(row)

    # ---- categories -------------------------------------------------------------------
    def list_categories(self, active_only: bool = False) -> list[dict[str, Any]]:
        with self._uow_factory() as uow:
            return [category_out(r) for r in uow.categories.all() if r.active or not active_only]

    def create_category(self, data: dict[str, Any]) -> dict[str, Any]:
        name = (data.get("name") or "").strip().upper()
        if not name:
            raise ValidationError("Category name is required.")
        with self._uow_factory() as uow:
            if uow.categories.record(name) is not None:
                raise ConflictError("That category already exists.")
            row = uow.categories.add(CategoryRecord(
                name=name, description=(data.get("description") or "").strip(), active=True))
            uow.commit()
            return category_out(row)

    def update_category(self, name: str, changes: dict[str, Any]) -> dict[str, Any]:
        with self._uow_factory() as uow:
            row = uow.categories.record(name)
            if row is None:
                raise NotFoundError("That category doesn't exist.")
            if "description" in changes:
                row.description = (changes["description"] or "").strip()
            if "active" in changes:
                row.active = bool(changes["active"])
            uow.commit()
            return category_out(row)

    # ---- SLA policies -----------------------------------------------------------------
    def list_sla_policies(self) -> list[dict[str, Any]]:
        with self._uow_factory() as uow:
            return [{"priority": r.priority, "responseMinutes": r.response_minutes,
                     "resolutionMinutes": r.resolution_minutes} for r in uow.sla.all()]

    def update_sla_policy(self, priority: str, changes: dict[str, Any]) -> dict[str, Any]:
        try:
            level = Priority[priority]
        except KeyError as error:
            raise NotFoundError("That priority doesn't exist.") from error
        with self._uow_factory() as uow:
            row = uow.sla.get_or_create(level)
            response = changes.get("responseMinutes", row.response_minutes)
            resolution = changes.get("resolutionMinutes", row.resolution_minutes)
            _whole(response, 1, "Targets must be greater than zero.")
            _whole(resolution, 1, "Targets must be greater than zero.")
            if response >= resolution:
                raise ValidationError(
                    "The response target must be shorter than the resolution target.")
            row.response_minutes, row.resolution_minutes = response, resolution
            uow.commit()
            return {"priority": row.priority, "responseMinutes": response,
                    "resolutionMinutes": resolution}

    # ---- assignment strategy ----------------------------------------------------------
    def assignment(self) -> dict[str, Any]:
        with self._uow_factory() as uow:
            return AssignmentPolicy(uow.settings).describe()

    def set_assignment(self, strategy_id: str) -> dict[str, Any]:
        with self._uow_factory() as uow:
            policy = AssignmentPolicy(uow.settings)
            policy.set_current(strategy_id)
            uow.commit()
            return policy.describe()

    # ---- audit and reports ------------------------------------------------------------
    def audit(self, incident_id: str | None = None, limit: int = 500) -> list[dict[str, Any]]:
        with self._uow_factory() as uow:
            return [{
                "incidentId": s.incident_id, "at": iso(s.at), "actorId": s.actor_id,
                "action": s.action, "description": s.description,
                "previousStatus": s.previous_status, "newStatus": s.new_status,
            } for s in uow.audit.latest(limit=limit, incident_id=incident_id)]

    def violations(self) -> list[dict[str, Any]]:
        with self._uow_factory() as uow:
            now = uow.clock.now()
            rows = uow.session.scalars(select(IncidentRecord)).all()
            found = [v for r in rows for v in _violations(r, now)]
            return sorted(found, key=lambda v: v["deadline"], reverse=True)

    def overview(self) -> dict[str, Any]:
        with self._uow_factory() as uow:
            now = uow.clock.now()
            rows = list(uow.session.scalars(select(IncidentRecord)))
            services = {s.id: s.name for s in uow.services.all()}
            open_rows = [r for r in rows if r.status not in DONE]
            counts = uow.users.active_counts()
            workload = sorted((technician_out(t, counts.get(t.id, 0))
                               for t in uow.users.technicians()),
                              key=lambda t: -t["activeCount"])
            per_service = Counter(services.get(r.service_id, r.service_id) for r in rows)
            today = now.astimezone(DISPLAY_TZ).replace(hour=0, minute=0, second=0, microsecond=0)
            days = [today - timedelta(days=13 - i) for i in range(14)]
            daily = [{"date": iso(start), "incidents": sum(
                1 for r in rows if start <= r.created_at < start + timedelta(days=1))}
                for start in days]
            return {
                "total": len(rows),
                "open": len(open_rows),
                "critical": sum(1 for r in open_rows if r.priority == Priority.P1.name),
                "resolved": len(rows) - len(open_rows),
                "slaViolations": sum(1 for r in rows if _violations(r, now)),
                "technicianWorkload": [{"id": t["id"], "name": t["name"],
                                        "active": t["activeCount"], "max": t["maxWorkload"]}
                                       for t in workload],
                "serviceAnalysis": [{"service": name, "incidents": n}
                                    for name, n in per_service.most_common()],
                "dailyCreated": daily,
            }


def _violations(row: IncidentRecord, now: datetime) -> list[dict[str, Any]]:
    sla = sla_out(row, now)
    found = []

    def add(kind: str, deadline: datetime, end: datetime) -> None:
        if end > deadline:
            found.append({
                "incidentId": row.id, "description": row.description,
                "priority": row.priority, "technicianId": row.technician_id, "type": kind,
                "deadline": iso(deadline), "overBySeconds": round((end - deadline).total_seconds()),
                "status": row.status,
            })

    add("Response", row.created_at + timedelta(seconds=row.response_target_seconds),
        row.responded_at or now)
    if row.status != Status.AWAITING_INFO.value:
        deadline = datetime.fromisoformat(sla["resolutionDeadline"].replace("Z", "+00:00"))
        end = row.resolved_at if row.status in DONE and row.resolved_at else now
        add("Resolution", deadline, end)
    return found
