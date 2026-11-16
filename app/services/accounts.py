"""Sign-up, sign-in and the current user (P2)."""

from __future__ import annotations

from collections.abc import Callable
from typing import Any

from app.db.models import UserRecord
from app.errors import AuthenticationError, ConflictError, InvalidLoginError
from app.persistence.uow import UnitOfWork
from app.security import PasswordService, TokenService
from app.services.views import user_out
from domain.enums import Role
from domain.exceptions import UnauthorizedActionError, ValidationError

MIN_PASSWORD_LENGTH = 8


def normalise_email(email: str) -> str:
    value = (email or "").strip().lower()
    if "@" not in value or value.startswith("@") or value.endswith("@") or " " in value:
        raise ValidationError("Enter a valid email address.")
    return value


def check_password(password: str) -> None:
    if len(password or "") < MIN_PASSWORD_LENGTH:
        raise ValidationError(f"Use a password of at least {MIN_PASSWORD_LENGTH} characters.")


class AccountService:
    def __init__(self, uow_factory: Callable[[], UnitOfWork], passwords: PasswordService,
                 tokens: TokenService) -> None:
        self._uow_factory = uow_factory
        self._passwords = passwords
        self._tokens = tokens
        # Verified against when the email is unknown, so both cases take the same time.
        self._dummy_hash = passwords.hash("not-a-real-password")

    def register(self, name: str, email: str, password: str) -> dict[str, Any]:
        """Self sign-up always creates an employee. Staff accounts come from an admin."""
        name = (name or "").strip()
        if not name:
            raise ValidationError("Enter your name.")
        email = normalise_email(email)
        check_password(password)
        with self._uow_factory() as uow:
            if uow.users.by_email(email) is not None:
                raise ConflictError("An account with that email already exists. Sign in instead.",
                                    code="EMAIL_TAKEN")
            row = uow.users.add(UserRecord(
                id=uow.users.next_id(Role.EMPLOYEE), email=email, name=name,
                password_hash=self._passwords.hash(password), role=Role.EMPLOYEE.value,
                active=True, created_at=uow.clock.now(),
            ))
            uow.commit()
            return self._session(row, uow)

    def login(self, email: str, password: str) -> dict[str, Any]:
        with self._uow_factory() as uow:
            row = uow.users.by_email((email or "").strip().lower())
            if row is None:
                self._passwords.verify(self._dummy_hash, password or "")
                raise InvalidLoginError("That email and password don't match. Try again.")
            if not self._passwords.verify(row.password_hash, password or ""):
                raise InvalidLoginError("That email and password don't match. Try again.")
            if not row.active:
                raise UnauthorizedActionError(
                    "This account has been deactivated. Contact your administrator."
                )
            return self._session(row, uow)

    def current_user(self, token: str) -> UserRecord:
        """The signed-in user, re-read on every request so deactivation is immediate."""
        claims = self._tokens.read(token)
        with self._uow_factory() as uow:
            row = uow.session.get(UserRecord, claims.user_id)
            if row is None or not row.active:
                raise AuthenticationError("Your session expired. Sign in again.")
            return row

    def _session(self, row: UserRecord, uow: UnitOfWork) -> dict[str, Any]:
        return {"token": self._tokens.issue(row.id, row.role),
                "user": user_out(row)}
