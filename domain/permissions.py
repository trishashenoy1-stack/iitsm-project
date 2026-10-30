from domain.enums import Role
from domain.events import SYSTEM
from domain.exceptions import UnauthorizedActionError

_STAFF = frozenset({Role.TECHNICIAN, Role.ADMIN})
_TECHNICIAN = frozenset({Role.TECHNICIAN})

ROLE_RULES = {
    "classify": _STAFF,
    "assign": _STAFF,
    "close": _STAFF,
    "set_priority": _STAFF,
    "acknowledge": _TECHNICIAN,
    "start_work": _TECHNICIAN,
    "request_info": _TECHNICIAN,
    "resolve": _TECHNICIAN,
}

# only the technician assigned to the incident may do these
ASSIGNED_TECHNICIAN_ONLY = {"acknowledge", "start_work", "request_info", "resolve"}

# only the person who reported the incident may do these
REPORTER_ONLY = {"provide_info", "verify", "reject_resolution"}


def _same_user(a, b):
    return b is not None and a.user_id == b.user_id


def check_permission(action, actor, incident):
    """Raise UnauthorizedActionError unless the actor may perform the action."""
    if actor is SYSTEM:
        return
    if not actor.is_active:
        raise UnauthorizedActionError(f"{actor.name} is deactivated")

    if action in REPORTER_ONLY:
        if not _same_user(actor, incident.reporter):
            raise UnauthorizedActionError(
                f"Only the reporter can {action.replace('_', ' ')} this incident"
            )
        return

    allowed = ROLE_RULES.get(action)
    if allowed is None:
        # fail closed: an action with no rule is never allowed
        raise UnauthorizedActionError(f"No permission rule for '{action}'")
    if not any(actor.has_role(role) for role in allowed):
        raise UnauthorizedActionError(
            f"{actor.name} is not allowed to {action.replace('_', ' ')}"
        )
    if action in ASSIGNED_TECHNICIAN_ONLY and incident.technician is not None:
        if not _same_user(actor, incident.technician):
            raise UnauthorizedActionError(
                "Only the assigned technician can do this"
            )