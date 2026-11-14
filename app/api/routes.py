"""HTTP routes (P2). Thin: validate the body, call one service method, return JSON.

Paths and JSON shapes match frontend/src/api/client.ts and types.ts. Everything is
under /api (see main.py).
"""

from __future__ import annotations

from typing import Any

from fastapi import APIRouter, Depends, Query, Response, status
from pydantic import BaseModel, ConfigDict, Field

from app.api.deps import backend, current_user, require_admin, require_staff
from app.bootstrap import Backend
from app.db.models import UserRecord
from app.errors import NotFoundError
from app.services.incidents import NewIncident
from app.services.views import user_out
from domain.enums import Role
from domain.exceptions import UnauthorizedActionError

FILTER_KEYS = ("id", "status", "priority", "category", "service", "technician", "sla",
               "from", "to")


class Body(BaseModel):
    model_config = ConfigDict(extra="forbid", str_max_length=4000)


class LoginBody(Body):
    email: str = Field(max_length=255)
    password: str = Field(max_length=200)


class RegisterBody(LoginBody):
    name: str = Field(max_length=120)


class NewIncidentBody(Body):
    description: str
    serviceId: str = Field(max_length=32)
    category: str | None = Field(default=None, max_length=64)
    impact: str = Field(max_length=8)
    urgency: str = Field(max_length=8)
    affectedUsers: int = Field(ge=1, le=1_000_000)


class MessageBody(Body):
    message: str | None = None


class TextBody(Body):
    text: str


class FeedbackBody(Body):
    rating: int
    comment: str = ""


class AssignBody(Body):
    technicianId: str = Field(max_length=16)


class StrategyBody(Body):
    current: str


# Admin edits are partial: only the keys sent are changed (validated in AdminService).
class UserChanges(Body):
    name: str | None = None
    email: str | None = None
    role: str | None = None
    password: str | None = Field(default=None, max_length=200)
    active: bool | None = None
    escalationLevel: int | None = None


class TechnicianChanges(Body):
    skills: list[str] | None = None
    experienceYears: int | None = None
    maxWorkload: int | None = None
    available: bool | None = None


class ServiceChanges(Body):
    id: str | None = None
    name: str | None = None
    criticality: int | None = None
    active: bool | None = None


class CategoryChanges(Body):
    name: str | None = None
    description: str | None = None
    active: bool | None = None


class SlaChanges(Body):
    priority: str | None = None
    responseMinutes: int | None = None
    resolutionMinutes: int | None = None


def changes(body: BaseModel) -> dict[str, Any]:
    return body.model_dump(exclude_unset=True)


public = APIRouter(tags=["auth"])
api = APIRouter()
admin = APIRouter(prefix="/admin", tags=["admin"], dependencies=[Depends(require_admin)])


# ---- auth ----------------------------------------------------------------------------
@public.post("/auth/login")
def login(body: LoginBody, app: Backend = Depends(backend)) -> dict[str, Any]:
    return app.accounts.login(body.email, body.password)


@public.post("/auth/register", status_code=status.HTTP_201_CREATED)
def register(body: RegisterBody, app: Backend = Depends(backend)) -> dict[str, Any]:
    return app.accounts.register(body.name, body.email, body.password)


@api.get("/auth/me", tags=["auth"])
def me(user: UserRecord = Depends(current_user)) -> dict[str, Any]:
    return user_out(user)


# ---- reference data ---------------------------------------------------------------------
@api.get("/services", tags=["reference"])
def services(_: UserRecord = Depends(current_user),
             app: Backend = Depends(backend)) -> list[dict[str, Any]]:
    return [{"id": s["id"], "name": s["name"]} for s in app.admin.list_services(active_only=True)]


@api.get("/categories", tags=["reference"])
def categories(_: UserRecord = Depends(current_user),
               app: Backend = Depends(backend)) -> list[str]:
    return [c["name"] for c in app.admin.list_categories(active_only=True)]


@api.get("/me/workload", tags=["technician"])
def workload(user: UserRecord = Depends(current_user),
             app: Backend = Depends(backend)) -> dict[str, int]:
    return app.incidents.workload(user.id)


# ---- incidents ----------------------------------------------------------------------
@api.get("/incidents", tags=["incidents"])
def list_incidents(
    user: UserRecord = Depends(current_user), app: Backend = Depends(backend),
    id: str | None = Query(None, max_length=32), status: str | None = None,
    priority: str | None = None, category: str | None = None, service: str | None = None,
    technician: str | None = None, sla: str | None = None,
    from_: str | None = Query(None, alias="from"), to: str | None = None,
) -> list[dict[str, Any]]:
    values = {"id": id, "status": status, "priority": priority, "category": category,
              "service": service, "technician": technician, "sla": sla, "from": from_,
              "to": to}
    return app.incidents.list(user.id, {k: v for k, v in values.items() if v})


@api.post("/incidents", status_code=status.HTTP_201_CREATED, tags=["incidents"])
def report_incident(body: NewIncidentBody, user: UserRecord = Depends(current_user),
                    app: Backend = Depends(backend)) -> dict[str, Any]:
    incident_id = app.incidents.report(user.id, NewIncident(
        description=body.description, service_id=body.serviceId, category=body.category,
        impact=body.impact, urgency=body.urgency, affected_users=body.affectedUsers,
    ))
    return app.incidents.get(user.id, incident_id)


@api.get("/incidents/{incident_id}", tags=["incidents"])
def get_incident(incident_id: str, user: UserRecord = Depends(current_user),
                 app: Backend = Depends(backend)) -> dict[str, Any]:
    return app.incidents.get(user.id, incident_id)


@api.post("/incidents/{incident_id}/actions/{action}", tags=["incidents"])
def act(incident_id: str, action: str, body: MessageBody,
        user: UserRecord = Depends(current_user),
        app: Backend = Depends(backend)) -> dict[str, Any]:
    app.incidents.act(user.id, incident_id, action, body.message)
    return app.incidents.get(user.id, incident_id)


@api.post("/incidents/{incident_id}/notes", tags=["incidents"])
def add_note(incident_id: str, body: TextBody, user: UserRecord = Depends(current_user),
             app: Backend = Depends(backend)) -> dict[str, Any]:
    app.incidents.add_note(user.id, incident_id, body.text)
    return app.incidents.get(user.id, incident_id)


@api.post("/incidents/{incident_id}/information", tags=["incidents"])
def add_information(incident_id: str, body: TextBody, user: UserRecord = Depends(current_user),
                    app: Backend = Depends(backend)) -> dict[str, Any]:
    app.incidents.add_information(user.id, incident_id, body.text)
    return app.incidents.get(user.id, incident_id)


@api.post("/incidents/{incident_id}/feedback", tags=["incidents"])
def feedback(incident_id: str, body: FeedbackBody, user: UserRecord = Depends(current_user),
             app: Backend = Depends(backend)) -> dict[str, Any]:
    app.incidents.submit_feedback(user.id, incident_id, body.rating, body.comment)
    return app.incidents.get(user.id, incident_id)


@api.post("/incidents/{incident_id}/assign", tags=["incidents"])
def assign(incident_id: str, body: AssignBody, user: UserRecord = Depends(require_staff),
           app: Backend = Depends(backend)) -> dict[str, Any]:
    app.incidents.assign(user.id, incident_id, body.technicianId)
    return app.incidents.get(user.id, incident_id)


@api.get("/incidents/{incident_id}/suggestions", tags=["intelligence"])
def suggestions(incident_id: str, user: UserRecord = Depends(require_staff),
                app: Backend = Depends(backend)) -> list[dict[str, Any]]:
    """P4's suggested resolutions: technicians and admins, on incidents they can see."""
    incident = app.incidents.get(user.id, incident_id)  # ownership check
    assigned = (incident["technician"] or {}).get("id")
    if user.role == Role.TECHNICIAN.value and assigned != user.id:
        raise UnauthorizedActionError("Only the assigned technician can see suggestions.")
    if app.p4 is None:
        return []
    return [{"incidentId": s.incident_id, "similarity": round(s.similarity, 3),
             "category": s.category, "resolution": s.resolution_text}
            for s in app.p4.suggest_resolutions(incident_id)]


# ---- admin ----------------------------------------------------------------------------
@admin.get("/users")
def list_users(app: Backend = Depends(backend)) -> list[dict[str, Any]]:
    return app.admin.list_users()


@admin.post("/users", status_code=status.HTTP_201_CREATED)
def create_user(body: UserChanges, app: Backend = Depends(backend)) -> dict[str, Any]:
    return app.admin.create_user(changes(body))


@admin.patch("/users/{user_id}")
def update_user(user_id: str, body: UserChanges, user: UserRecord = Depends(current_user),
                app: Backend = Depends(backend)) -> dict[str, Any]:
    return app.admin.update_user(user.id, user_id, changes(body))


@admin.get("/technicians")
def list_technicians(app: Backend = Depends(backend)) -> list[dict[str, Any]]:
    return app.admin.list_technicians()


@admin.patch("/technicians/{user_id}")
def update_technician(user_id: str, body: TechnicianChanges,
                      app: Backend = Depends(backend)) -> dict[str, Any]:
    return app.admin.update_technician(user_id, changes(body))


@admin.get("/services")
def list_services(app: Backend = Depends(backend)) -> list[dict[str, Any]]:
    return app.admin.list_services()


@admin.post("/services", status_code=status.HTTP_201_CREATED)
def create_service(body: ServiceChanges, app: Backend = Depends(backend)) -> dict[str, Any]:
    return app.admin.create_service(changes(body))


@admin.patch("/services/{service_id}")
def update_service(service_id: str, body: ServiceChanges,
                   app: Backend = Depends(backend)) -> dict[str, Any]:
    return app.admin.update_service(service_id, changes(body))


@admin.get("/categories")
def list_admin_categories(app: Backend = Depends(backend)) -> list[dict[str, Any]]:
    return app.admin.list_categories()


@admin.post("/categories", status_code=status.HTTP_201_CREATED)
def create_category(body: CategoryChanges, app: Backend = Depends(backend)) -> dict[str, Any]:
    return app.admin.create_category(changes(body))


@admin.patch("/categories/{name}")
def update_category(name: str, body: CategoryChanges,
                    app: Backend = Depends(backend)) -> dict[str, Any]:
    return app.admin.update_category(name, changes(body))


@admin.get("/sla-policies")
def list_sla(app: Backend = Depends(backend)) -> list[dict[str, Any]]:
    return app.admin.list_sla_policies()


@admin.patch("/sla-policies/{priority}")
def update_sla(priority: str, body: SlaChanges,
               app: Backend = Depends(backend)) -> dict[str, Any]:
    return app.admin.update_sla_policy(priority, changes(body))


@admin.get("/assignment-strategy")
def assignment(app: Backend = Depends(backend)) -> dict[str, Any]:
    return app.admin.assignment()


@admin.patch("/assignment-strategy")
def set_assignment(body: StrategyBody, app: Backend = Depends(backend)) -> dict[str, Any]:
    return app.admin.set_assignment(body.current)


@admin.get("/audit-log")
def audit_log(app: Backend = Depends(backend),
              incident_id: str | None = Query(None, alias="incidentId"),
              limit: int = Query(500, ge=1, le=5000)) -> list[dict[str, Any]]:
    return app.admin.audit(incident_id, limit)


@admin.get("/sla-violations")
def sla_violations(app: Backend = Depends(backend)) -> list[dict[str, Any]]:
    return app.admin.violations()


@admin.get("/reports/overview")
def overview(app: Backend = Depends(backend)) -> dict[str, Any]:
    return app.admin.overview()


@admin.get("/reports/clusters", tags=["intelligence"])
def clusters(app: Backend = Depends(backend)) -> dict[str, list[list[str]]]:
    if app.p4 is None:
        return {}
    return {service: [sorted(c) for c in groups]
            for service, groups in app.p4.clusters().items()}


@admin.post("/jobs/{name}/run", tags=["jobs"])
def run_job(name: str, app: Backend = Depends(backend)) -> dict[str, Any]:
    """Run one background job now (for the demo)."""
    if app.p4 is None or name not in app.p4.scheduler.job_names:
        raise NotFoundError(f"No job called {name}")
    result = app.p4.scheduler.run_now(name)
    return {"job": result.job, "scanned": result.scanned, "actions": dict(result.actions),
            "errors": [list(e) for e in result.errors]}


@api.get("/health/p4", tags=["health"])
def health_p4(_: UserRecord = Depends(require_admin),
              app: Backend = Depends(backend)) -> dict[str, Any]:
    return {"enabled": False} if app.p4 is None else app.p4.health()


def no_content() -> Response:
    return Response(status_code=status.HTTP_204_NO_CONTENT)
