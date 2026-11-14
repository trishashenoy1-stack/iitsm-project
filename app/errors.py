"""Errors the backend adds to P1's ITSMError hierarchy, and their HTTP mapping (P2).

Domain and service code only raise. One FastAPI handler (app/api/errors.py) turns
any ITSMError into ``{"code", "message"}`` with the status below, which is the error
shape the frontend reads (ApiErrorBody in frontend/src/api/types.ts).
"""

from __future__ import annotations

from domain.exceptions import (
    DuplicateIncidentError,
    InvalidIncidentError,
    InvalidStateTransitionError,
    ITSMError,
    MissingSLAError,
    NoEligibleTechnicianError,
    ServiceNotFoundError,
    TechnicianUnavailableError,
    TechnicianWorkloadExceededError,
    UnauthorizedActionError,
    ValidationError,
)


class AuthenticationError(ITSMError):
    """Missing, invalid or expired credentials."""

    code = "NOT_AUTHENTICATED"


class InvalidLoginError(AuthenticationError):
    code = "INVALID_LOGIN"


class NotFoundError(ITSMError):
    code = "NOT_FOUND"


class IncidentNotFoundError(NotFoundError):
    code = "INCIDENT_NOT_FOUND"


class UserNotFoundError(NotFoundError):
    code = "USER_NOT_FOUND"


class ConflictError(ITSMError):
    """The request is valid but clashes with existing data."""

    def __init__(self, message: str, code: str = "CONFLICT") -> None:
        super().__init__(message)
        self.code = code


# Most specific first: the first matching class wins.
HTTP_STATUS: list[tuple[type[Exception], int, str]] = [
    (InvalidLoginError, 401, "INVALID_LOGIN"),
    (AuthenticationError, 401, "NOT_AUTHENTICATED"),
    (UnauthorizedActionError, 403, "UNAUTHORIZED_ACTION"),
    (IncidentNotFoundError, 404, "INCIDENT_NOT_FOUND"),
    (ServiceNotFoundError, 404, "SERVICE_NOT_FOUND"),
    (NotFoundError, 404, "NOT_FOUND"),
    (InvalidIncidentError, 404, "INCIDENT_NOT_FOUND"),
    (ValidationError, 422, "INVALID_INPUT"),
    (InvalidStateTransitionError, 409, "INVALID_STATE_TRANSITION"),
    (TechnicianUnavailableError, 409, "TECHNICIAN_UNAVAILABLE"),
    (TechnicianWorkloadExceededError, 409, "TECHNICIAN_WORKLOAD_EXCEEDED"),
    (NoEligibleTechnicianError, 409, "NO_ELIGIBLE_TECHNICIAN"),
    (DuplicateIncidentError, 409, "DUPLICATE_INCIDENT"),
    (ConflictError, 409, "CONFLICT"),
    (MissingSLAError, 500, "SLA_NOT_CONFIGURED"),
]


def http_status_for(error: Exception) -> tuple[int, str]:
    for cls, status, code in HTTP_STATUS:
        if isinstance(error, cls):
            return status, getattr(error, "code", None) or code
    return 500, "INTERNAL_ERROR"
