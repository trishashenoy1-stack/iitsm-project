"""Incident use cases (P2): report, act, note, inform, feedback, assign, read.

Each method is one transaction. The rules themselves are P1's: this layer finds the
objects, calls the domain method, records the detail P1's events don't carry (note
text, resolution text, the information request) and commits.
"""

from __future__ import annotations

from collections.abc import Callable, Mapping
from dataclasses import dataclass
from typing import Any

from app.db.models import IncidentRecord, UserRecord
from app.errors import IncidentNotFoundError
from app.persistence.journal import Step
from app.persistence.replay import PersistedIncident
from app.persistence.uow import UnitOfWork
from app.services import views
from app.services.assignment import AssignmentPolicy
from domain.enums import Impact, Priority, Role, Status, Urgency
from domain.events import SYSTEM
from domain.exceptions import (
    InvalidStateTransitionError,
    NoEligibleTechnicianError,
    UnauthorizedActionError,
    ValidationError,
)
from domain.factory import IncidentFactory
from domain.priority import MatrixPriorityStrategy
from domain.users import Technician

ACTIONS = ("acknowledge", "start_work", "request_info", "provide_info", "resolve",
           "verify", "reject_resolution", "close")
# The brief needs text with these. P1's request_info()/provide_info() take none (yet),
# so the text is kept in the audit step and on the incident's read model.
NEEDS_MESSAGE = {"resolve": "Add the resolution details before resolving.",
                 "request_info": "Write your question for the reporter first.",
                 "provide_info": "Write your reply first."}


@dataclass(frozen=True)
class NewIncident:
    description: str
    service_id: str
    category: str | None
    impact: str
    urgency: str
    affected_users: int


def can_view(user: UserRecord, incident: IncidentRecord) -> bool:
    """Ownership check on every incident read and write (the IDOR rule)."""
    return (user.role == Role.ADMIN.value or incident.reporter_id == user.id
            or incident.technician_id == user.id)


class IncidentService:
    def __init__(self, uow_factory: Callable[[], UnitOfWork]) -> None:
        self._uow_factory = uow_factory

    # ---- writes -----------------------------------------------------------------
    def report(self, actor_id: str, data: NewIncident, seed_key: str | None = None,
               auto_assign: bool = True) -> str:
        with self._uow_factory() as uow:
            reporter = uow.users.domain(actor_id)
            service = uow.services.domain(data.service_id)
            impact, urgency = _level(Impact, data.impact), _level(Urgency, data.urgency)
            factory = IncidentFactory(
                uow.clock, uow.bus, MatrixPriorityStrategy(), uow.sla.policy(),
                first_number=uow.incidents.next_number(),
                category_registry=uow.categories.registry(),
            )
            created_at = uow.clock.now()
            domain = factory.create(reporter, service, data.description, impact, urgency,
                                    affected_users=data.affected_users,
                                    category=data.category or None)
            incident = PersistedIncident(domain, created_at, uow.clock, uow.bus)
            uow.incidents.add(incident, seed_key=seed_key)
            if domain.category is not None:
                domain.classify(actor=SYSTEM)
                uow.journal.annotate(domain.incident_id, "classify",
                                     category=domain.category.name)
            if auto_assign:
                self._auto_assign(uow, incident)
            uow.commit()
            return str(domain.incident_id)

    def set_priority(self, actor_id: str, incident_id: str, priority: str, reason: str) -> None:
        """Staff override of the calculated priority. P1 audits it (PriorityChanged) and
        moves the SLA deadlines, still counted from the original creation time."""
        try:
            level = Priority[priority]
        except KeyError as error:
            raise ValidationError("Priority must be P1, P2, P3 or P4.") from error
        with self._uow_factory() as uow:
            incident = self._for_write(uow, actor_id, incident_id)
            incident.set_priority(level, actor=uow.users.domain(actor_id),
                                  reason=(reason or "").strip() or "Changed by staff")
            uow.commit()

    def _auto_assign(self, uow: UnitOfWork, incident: PersistedIncident) -> None:
        policy = AssignmentPolicy(uow.settings)
        uow.users.lock_technicians()
        technicians = uow.users.domain_technicians()
        try:
            _technician, via = policy.assign(incident.domain, technicians)
        except NoEligibleTechnicianError:
            # Never fail silently: it stays unassigned, visible in the admin queue.
            uow.journal.add(Step(incident.incident_id, uow.clock.now(), "SYSTEM",
                                 "assign_failed"))
            return
        uow.journal.annotate(incident.incident_id, "assign", via=via)

    def act(self, actor_id: str, incident_id: str, action: str, message: str | None) -> None:
        if action not in ACTIONS:
            raise ValidationError(f"Unknown action '{action}'")
        text = (message or "").strip()
        if action in NEEDS_MESSAGE and not text:
            raise ValidationError(NEEDS_MESSAGE[action])
        with self._uow_factory() as uow:
            incident = self._for_write(uow, actor_id, incident_id)
            actor = uow.users.domain(actor_id)
            if action == "resolve":
                incident.resolve(actor=actor, resolution=text)
                uow.journal.annotate(incident_id, "resolve", resolution=incident.resolution)
            else:
                getattr(incident, action)(actor=actor)
                if action in NEEDS_MESSAGE:
                    uow.journal.annotate(incident_id, action, message=text)
            uow.commit()

    def add_note(self, actor_id: str, incident_id: str, text: str) -> None:
        with self._uow_factory() as uow:
            incident = self._for_write(uow, actor_id, incident_id)
            incident.add_note(text, actor=uow.users.domain(actor_id))
            uow.journal.add(Step(incident_id, uow.clock.now(), actor_id, "add_note",
                                 internal=True, payload={"text": incident.notes[-1].text}))
            uow.commit()

    def add_information(self, actor_id: str, incident_id: str, text: str) -> None:
        """The reporter adds detail at any time (brief: "add information").

        Not in P1's domain yet (only the technician can add notes there), so it is an
        audit step only; it doesn't change the incident's state.
        """
        text = (text or "").strip()
        if not text:
            raise ValidationError("Write the extra information first.")
        with self._uow_factory() as uow:
            row = self._visible(uow, actor_id, incident_id)
            if row.reporter_id != actor_id:
                raise UnauthorizedActionError("Only the reporter can add information.")
            if row.status == Status.CLOSED.value:
                raise InvalidStateTransitionError("This incident is closed.")
            uow.journal.add(Step(incident_id, uow.clock.now(), actor_id, "add_information",
                                 payload={"text": text}))
            uow.commit()

    def submit_feedback(self, actor_id: str, incident_id: str, rating: int, comment: str) -> None:
        with self._uow_factory() as uow:
            incident = self._for_write(uow, actor_id, incident_id)
            incident.submit_feedback(uow.users.domain(actor_id), rating, comment)
            uow.journal.add(Step(incident_id, uow.clock.now(), actor_id, "submit_feedback",
                                 payload={"rating": rating,
                                          "comment": incident.feedback.comment}))
            uow.commit()

    def assign(self, actor_id: str, incident_id: str, technician_id: str) -> None:
        """Manual assignment by staff. P1 checks the role and the state."""
        with self._uow_factory() as uow:
            incident = self._for_write(uow, actor_id, incident_id)
            uow.users.lock_technicians()
            technician = uow.users.domain(technician_id)
            if not isinstance(technician, Technician):
                raise ValidationError(f"{technician_id} is not a technician")
            actor = uow.users.domain(actor_id)
            incident.assign(actor=actor, technician=technician)
            technician.take_incident()  # raises if unavailable or full
            uow.journal.annotate(incident_id, "assign", via=actor_id)
            uow.commit()

    # ---- reads ------------------------------------------------------------------
    def get(self, viewer_id: str, incident_id: str) -> dict[str, Any]:
        with self._uow_factory() as uow:
            row = self._visible(uow, viewer_id, incident_id)
            return self._serialize(uow, uow.users.record(viewer_id), [row],
                                   with_duplicates=True)[0]

    def list(self, viewer_id: str, filters: Mapping[str, str]) -> list[dict[str, Any]]:
        with self._uow_factory() as uow:
            viewer = uow.users.record(viewer_id)
            rows = uow.incidents.search(filters, viewer=viewer)
            if filters.get("sla"):
                now = uow.clock.now()
                rows = [r for r in rows if views.sla_bucket(r, now) == filters["sla"]]
            return self._serialize(uow, viewer, rows)

    def workload(self, user_id: str) -> dict[str, int]:
        with self._uow_factory() as uow:
            row = uow.users.record(user_id)
            if row.role != Role.TECHNICIAN.value:
                raise UnauthorizedActionError("Only technicians have a workload.")
            active = uow.users.active_counts().get(user_id, 0)
            maximum = row.technician.max_workload if row.technician else 5
            return {"active": active, "max": maximum}

    # ---- helpers ------------------------------------------------------------------
    def _visible(self, uow: UnitOfWork, user_id: str, incident_id: str) -> IncidentRecord:
        row = uow.incidents.record(incident_id)
        if not can_view(uow.users.record(user_id), row):
            # 404, not 403: don't confirm to an outsider that the incident exists.
            raise IncidentNotFoundError(f"Incident {incident_id} doesn't exist")
        return row

    def _for_write(self, uow: UnitOfWork, user_id: str, incident_id: str) -> PersistedIncident:
        self._visible(uow, user_id, incident_id)
        return uow.incidents.get_for_update(incident_id)

    @staticmethod
    def _serialize(uow: UnitOfWork, viewer: UserRecord, rows: list[IncidentRecord],
                   with_duplicates: bool = False) -> list[dict[str, Any]]:
        if not rows:
            return []
        steps = uow.audit.for_incidents(r.id for r in rows)
        users = {u.id: u for u in uow.users.all()}
        services = {s.id: s.name for s in uow.services.all()}
        descriptions = {r.id: r.description for r in rows}
        now = uow.clock.now()
        result = []
        for row in rows:
            duplicates = []
            if with_duplicates and viewer.role != Role.EMPLOYEE.value:
                for other, score in uow.intelligence.duplicates_of(row.id):
                    if other not in descriptions:
                        descriptions[other] = uow.incidents.record(other).description
                    duplicates.append({"id": other, "description": descriptions[other],
                                       "similarity": round(score, 3)})
            result.append(views.incident_out(row, steps.get(row.id, []), viewer, users,
                                             services, duplicates, now))
        return result


def _level(enum: Any, value: str) -> Any:
    try:
        return enum[(value or "").upper()]
    except KeyError as error:
        raise ValidationError(f"'{value}' must be LOW, MEDIUM or HIGH") from error
