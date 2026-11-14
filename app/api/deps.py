"""FastAPI dependencies: the backend container, the signed-in user, role checks (P2)."""

from __future__ import annotations

from collections.abc import Callable
from types import SimpleNamespace
from typing import Any

from fastapi import Depends, Request
from fastapi.concurrency import run_in_threadpool
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer

from app.bootstrap import Backend
from app.db.models import UserRecord
from app.errors import AuthenticationError
from domain.enums import Role
from domain.exceptions import UnauthorizedActionError

_bearer = HTTPBearer(auto_error=False)


def backend(request: Request) -> Backend:
    return request.app.state.backend


async def current_user(
    credentials: HTTPAuthorizationCredentials | None = Depends(_bearer),
    app: Backend = Depends(backend),
) -> UserRecord:
    if credentials is None or credentials.scheme.lower() != "bearer":
        raise AuthenticationError("Sign in to continue.")
    return await run_in_threadpool(app.accounts.current_user, credentials.credentials)


async def notification_user(user: UserRecord = Depends(current_user)) -> Any:
    """P3's notification router expects an object with ``user_id``."""
    return SimpleNamespace(user_id=user.id)


def require_role(*roles: Role) -> Callable[..., Any]:
    allowed = {r.value for r in roles}

    async def check(user: UserRecord = Depends(current_user)) -> UserRecord:
        if user.role not in allowed:
            raise UnauthorizedActionError("You don't have permission to do this.")
        return user

    return check


require_admin = require_role(Role.ADMIN)
require_staff = require_role(Role.ADMIN, Role.TECHNICIAN)
