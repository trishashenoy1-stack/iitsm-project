"""Passwords and access tokens (P2).

Argon2id for passwords (the current OWASP recommendation), HS256 JWTs for sessions.
The signing secret only ever comes from the environment.
"""

from __future__ import annotations

import logging
import secrets
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta

import jwt
from argon2 import PasswordHasher
from argon2.exceptions import InvalidHashError, VerificationError, VerifyMismatchError

from app.errors import AuthenticationError

log = logging.getLogger(__name__)

ALGORITHM = "HS256"
MIN_SECRET_LENGTH = 32


class PasswordService:
    def __init__(self, hasher: PasswordHasher | None = None) -> None:
        self._hasher = hasher or PasswordHasher()

    def hash(self, password: str) -> str:
        return self._hasher.hash(password)

    def verify(self, password_hash: str, password: str) -> bool:
        try:
            return self._hasher.verify(password_hash, password)
        except (VerifyMismatchError, VerificationError, InvalidHashError):
            return False


@dataclass(frozen=True)
class TokenClaims:
    user_id: str
    role: str


class TokenService:
    def __init__(self, secret: str, expires_minutes: int) -> None:
        if len(secret) < MIN_SECRET_LENGTH:
            raise ValueError(f"JWT_SECRET must be at least {MIN_SECRET_LENGTH} characters")
        self._secret = secret
        self._lifetime = timedelta(minutes=expires_minutes)

    @classmethod
    def from_settings(cls, secret: str, expires_minutes: int, production: bool) -> TokenService:
        if not secret:
            if production:
                raise RuntimeError("JWT_SECRET is not set. Refusing to start in production.")
            # Development only: tokens stop working when the server restarts.
            log.warning("JWT_SECRET not set; using a random secret for this process")
            secret = secrets.token_urlsafe(48)
        return cls(secret, expires_minutes)

    def issue(self, user_id: str, role: str, now: datetime | None = None) -> str:
        # Wall-clock time, not the domain clock: token expiry is real-world security
        # (and PyJWT rejects tokens issued "in the future").
        now = now or datetime.now(UTC)
        payload = {"sub": user_id, "role": role, "iat": now, "exp": now + self._lifetime}
        return jwt.encode(payload, self._secret, algorithm=ALGORITHM)

    def read(self, token: str) -> TokenClaims:
        try:
            payload = jwt.decode(token, self._secret, algorithms=[ALGORITHM],
                                 options={"require": ["sub", "exp", "iat"]})
        except jwt.ExpiredSignatureError as error:
            raise AuthenticationError("Your session expired. Sign in again.") from error
        except jwt.InvalidTokenError as error:
            raise AuthenticationError("Your session is not valid. Sign in again.") from error
        return TokenClaims(str(payload["sub"]), str(payload.get("role", "")))
