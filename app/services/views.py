"""Turn rows into the JSON the frontend reads (frontend/src/api/types.ts) (P2).

Reads never rebuild domain objects: they use the read-model columns plus the audit
steps, so listing 500 incidents is a couple of queries.
"""

from __future__ import annotations

from collections.abc import Iterable
from datetime import datetime, timedelta
from typing import Any

from app.db.models import IncidentRecord, UserRecord
from app.persistence.journal import Step
from domain.enums import Role, Status

DONE = {Status.RESOLVED.value, Status.VERIFIED.value, Status.CLOSED.value}
WARNING_REMAINING_RATIO = 0.2  # matches frontend/src/lib/sla.ts and P1's 0.8 warning
# Steps that are audit noise for the person who reported the incident.
HIDDEN_FROM_EMPLOYEES = {"add_note", "rejected", "possible_duplicate", "suggested_category",
                         "escalated", "escalation_exhausted"}


def iso(moment: datetime | None) -> str | None:
    return None if moment is None else moment.isoformat().replace("+00:00", "Z")


def person(users: dict[str, UserRecord], user_id: str | None) -> dict[str, str] | None:
    if user_id is None:
        return None
    row = users.get(user_id)
    return {"id": user_id, "name": row.name if row else user_id}


def user_out(row: UserRecord) -> dict[str, Any]:
    return {"id": row.id, "name": row.name, "email": row.email, "role": row.role}


def sla_out(row: IncidentRecord, now: datetime) -> dict[str, Any]:
    paused = row.paused_at is not None and row.status == Status.AWAITING_INFO.value
    extra = timedelta(seconds=row.paused_seconds or 0)
    if paused and row.paused_at is not None:
        extra += now - row.paused_at
    deadline = row.created_at + timedelta(seconds=row.resolution_target_seconds) + extra
    resolved_at = row.resolved_at if row.status in DONE else None
    stopped_at = resolved_at or (now if paused else None)
    return {
        "responseDeadline": iso(row.created_at + timedelta(seconds=row.response_target_seconds)),
        "resolutionDeadline": iso(deadline),
        "resolutionTargetSeconds": row.resolution_target_seconds,
        "isPaused": paused,
        "respondedAt": iso(row.responded_at),
        "resolvedAt": iso(resolved_at),
        "frozenRemainingSeconds": None if stopped_at is None
        else round((deadline - stopped_at).total_seconds()),
    }


def sla_bucket(row: IncidentRecord, now: datetime) -> str:
    """Same buckets as the frontend's SLA filter: ok, warning, breached, paused, met."""
    sla = sla_out(row, now)
    if sla["resolvedAt"]:
        return "breached" if (sla["frozenRemainingSeconds"] or 0) < 0 else "met"
    if sla["isPaused"]:
        return "paused"
    deadline = datetime.fromisoformat(sla["resolutionDeadline"].replace("Z", "+00:00"))
    left = (deadline - now).total_seconds()
    if left <= 0:
        return "breached"
    return "warning" if left / row.resolution_target_seconds <= WARNING_REMAINING_RATIO else "ok"


def history_out(steps: Iterable[Step], viewer_role: str) -> list[dict[str, Any]]:
    visible = [s for s in steps if not (viewer_role == Role.EMPLOYEE.value
                                        and (s.internal or s.action in HIDDEN_FROM_EMPLOYEES))]
    visible.sort(key=lambda s: s.seq, reverse=True)
    return [{
        "at": iso(s.at), "actorId": s.actor_id, "action": s.action,
        "description": s.description, "previousStatus": s.previous_status,
        "newStatus": s.new_status,
    } for s in visible]


def incident_out(row: IncidentRecord, steps: list[Step], viewer: UserRecord,
                 users: dict[str, UserRecord], service_names: dict[str, str],
                 duplicates: list[dict[str, Any]], now: datetime) -> dict[str, Any]:
    feedback = None if row.feedback_rating is None else {
        "rating": row.feedback_rating, "comment": row.feedback_comment or "",
    }
    return {
        "id": row.id,
        "description": row.description,
        "status": row.status,
        "priority": row.priority,
        "category": row.category or "UNCLASSIFIED",
        "service": service_names.get(row.service_id, row.service_id),
        "impact": row.impact,
        "urgency": row.urgency,
        "affectedUsers": row.affected_users,
        "reporter": person(users, row.reporter_id),
        "technician": person(users, row.technician_id),
        "createdAt": iso(row.created_at),
        "sla": sla_out(row, now),
        "resolution": row.resolution,
        "infoRequest": row.info_request,
        "feedback": feedback,
        "history": history_out(steps, viewer.role),
        "possibleDuplicates": [] if viewer.role == Role.EMPLOYEE.value else duplicates,
        "suggestedCategory": row.suggested_category,
    }
