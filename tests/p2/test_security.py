"""Authentication, roles and ownership (P2)."""

from __future__ import annotations

from datetime import UTC, datetime, timedelta

import jwt
import pytest

from tests.p2.conftest import PASSWORD, World

case = pytest.mark.case


@case(id="TC-P2-01", category="normal", desc="Employee registers, then signs in",
      expected="201 with a token; /auth/me returns the new EMPLOYEE")
def test_register_then_login(w: World) -> None:
    r = w.client.post("/api/auth/register",
                      json={"name": "Zara", "email": "Zara@Corp.test", "password": PASSWORD})
    assert r.status_code == 201
    assert r.json()["user"]["role"] == "EMPLOYEE"
    headers = w.login("zara@corp.test")
    assert w.client.get("/api/auth/me", headers=headers).json()["email"] == "zara@corp.test"


@case(id="TC-P2-02", category="invalid-input", desc="Register with a 5-character password",
      expected="422 INVALID_INPUT, no account created")
def test_short_password_rejected(w: World) -> None:
    r = w.client.post("/api/auth/register",
                      json={"name": "Zara", "email": "z@corp.test", "password": "short"})
    assert (r.status_code, r.json()["code"]) == (422, "INVALID_INPUT")


@case(id="TC-P2-03", category="invalid-input", desc="Register with an email already used",
      expected="409 EMAIL_TAKEN")
def test_duplicate_email(w: World) -> None:
    r = w.client.post("/api/auth/register",
                      json={"name": "Copy", "email": "asha@corp.test", "password": PASSWORD})
    assert (r.status_code, r.json()["code"]) == (409, "EMAIL_TAKEN")


@case(id="TC-P2-04", category="authorization", desc="Sign in with the wrong password",
      expected="401 INVALID_LOGIN, same message as for an unknown email")
def test_wrong_password(w: World) -> None:
    wrong = w.client.post("/api/auth/login", json={"email": "asha@corp.test", "password": "x"})
    unknown = w.client.post("/api/auth/login", json={"email": "no@corp.test", "password": "x"})
    assert wrong.status_code == unknown.status_code == 401
    assert wrong.json() == unknown.json()


def test_passwords_are_argon2_hashes(w: World) -> None:
    with w.backend.session_factory() as s:
        from app.db.models import UserRecord

        stored = s.get(UserRecord, "E101").password_hash
    assert stored.startswith("$argon2id$") and PASSWORD not in stored


@case(id="TC-P2-05", category="authorization", desc="Tampered, expired and missing tokens",
      expected="401 NOT_AUTHENTICATED in every case")
def test_bad_tokens(w: World) -> None:
    good = w.login("asha@corp.test")["Authorization"].split()[1]
    now = datetime.now(UTC)
    forged = jwt.encode({"sub": "A101", "role": "ADMIN", "iat": now,
                         "exp": now + timedelta(hours=1)}, "x" * 40, "HS256")
    expired = w.backend.tokens.issue("E101", "EMPLOYEE", now - timedelta(days=1))
    for headers in ({"Authorization": f"Bearer {forged}"},
                    {"Authorization": f"Bearer {expired}"},
                    {"Authorization": f"Bearer {good}x"}, {}):
        r = w.client.get("/api/incidents", headers=headers)
        assert r.status_code == 401, headers


@case(id="TC-P2-06", category="authorization", desc="Deactivated user keeps an old token",
      expected="Token stops working at once; signing in again gives 403")
def test_deactivation_is_immediate(w: World) -> None:
    employee, admin = w.login("asha@corp.test"), w.login("admin@corp.test")
    assert w.client.patch("/api/admin/users/E101", headers=admin,
                          json={"active": False}).status_code == 200
    assert w.client.get("/api/incidents", headers=employee).status_code == 401
    r = w.client.post("/api/auth/login", json={"email": "asha@corp.test", "password": PASSWORD})
    assert r.status_code == 403


@case(id="TC-P2-07", category="authorization", desc="Employee calls admin endpoints",
      expected="403 UNAUTHORIZED_ACTION on every /api/admin route")
def test_employee_cannot_use_admin_routes(w: World) -> None:
    employee = w.login("asha@corp.test")
    for path in ("users", "technicians", "services", "sla-policies", "audit-log",
                 "reports/overview", "assignment-strategy"):
        assert w.client.get(f"/api/admin/{path}", headers=employee).status_code == 403
    r = w.client.patch("/api/admin/sla-policies/P1", headers=employee,
                       json={"responseMinutes": 1})
    assert r.status_code == 403


@case(id="TC-P2-08", category="authorization",
      desc="IDOR: employee B requests employee A's incident by id",
      expected="404 (existence not revealed); B's list doesn't include it")
def test_employee_cannot_see_others_incidents(w: World) -> None:
    a, b = w.login("asha@corp.test"), w.login("bilal@corp.test")
    incident = w.report(a)
    assert w.client.get(f"/api/incidents/{incident['id']}", headers=b).status_code == 404
    assert w.client.get("/api/incidents", headers=b).json() == []
    r = w.client.post(f"/api/incidents/{incident['id']}/information", headers=b,
                      json={"text": "me too"})
    assert r.status_code == 404


@case(id="TC-P2-09", category="authorization",
      desc="A technician acts on an incident assigned to someone else",
      expected="404 for the read; the incident is unchanged")
def test_unassigned_technician_cannot_act(w: World) -> None:
    incident = w.report(w.login("asha@corp.test"))
    assert incident["technician"]["id"] == "T101"
    other = w.login("neha@corp.test")
    assert w.act(other, incident["id"], "acknowledge").status_code == 404
    admin = w.login("admin@corp.test")
    status = w.client.get(f"/api/incidents/{incident['id']}", headers=admin).json()["status"]
    assert status == "ASSIGNED"


def test_unknown_body_fields_are_rejected(w: World) -> None:
    r = w.client.post("/api/auth/register", json={"name": "Eve", "email": "eve@corp.test",
                                                  "password": PASSWORD, "role": "ADMIN"})
    assert (r.status_code, r.json()["code"]) == (422, "INVALID_INPUT")


def test_production_refuses_to_start_without_secret() -> None:
    from app.security import TokenService

    with pytest.raises(RuntimeError):
        TokenService.from_settings("", 60, production=True)
    with pytest.raises(ValueError):
        TokenService("too-short", 60)
