"""Fixes from the pre-demo audit (19 Nov): escalation access, auto-classification,
priority override, resubmission, database errors and audit wording."""

from __future__ import annotations

from collections.abc import Callable
from pathlib import Path
from typing import Any

import pytest
from sqlalchemy.exc import OperationalError

from app.bootstrap import _email_env
from tests.p2.conftest import World, make_settings

case = pytest.mark.case


def history(w: World, headers: dict[str, str], incident_id: str) -> list[dict[str, Any]]:
    r = w.client.get(f"/api/incidents/{incident_id}", headers=headers)
    assert r.status_code == 200, r.text
    return list(r.json()["history"])


def set_level(w: World, admin: dict[str, str], user_id: str, level: int) -> None:
    r = w.client.patch(f"/api/admin/users/{user_id}", headers=admin,
                       json={"escalationLevel": level})
    assert r.status_code == 200, r.text


@case(id="TC-P2-29", category="authorization",
      desc="A technician team lead opens an incident escalated to them",
      expected="The lead gets 200; an unrelated employee still gets 404")
def test_escalated_team_lead_can_open_incident(world_factory: Callable[..., World]) -> None:
    w = world_factory(with_p4=True)
    admin, emp = w.login("admin@corp.test"), w.login("asha@corp.test")
    set_level(w, admin, "A102", 2)
    set_level(w, admin, "T102", 1)  # T102 (network) is now the team lead
    incident = w.report(emp)  # APPLICATION -> T101
    assert incident["technician"]["id"] == "T101"
    w.clock.advance(minutes=6)
    assert w.backend.p4.scheduler.run_now("escalation").actions["escalated"] == 1

    lead = w.login("neha@corp.test")
    seen = w.client.get(f"/api/incidents/{incident['id']}", headers=lead)
    assert seen.status_code == 200
    assert "Escalated to T102 (level 1)" in [h["description"] for h in seen.json()["history"]]
    outsider = w.client.get(f"/api/incidents/{incident['id']}",
                            headers=w.login("bilal@corp.test"))
    assert outsider.status_code == 404


@case(id="TC-P2-30", category="business-rule",
      desc="Escalation skips the level that is the incident's own technician",
      expected="Escalated to the next level up, never to the assignee")
def test_escalation_skips_current_assignee(world_factory: Callable[..., World]) -> None:
    w = world_factory(with_p4=True)
    admin = w.login("admin@corp.test")
    set_level(w, admin, "A102", 2)
    set_level(w, admin, "T101", 1)  # the lead also takes ordinary assignments
    incident = w.report(w.login("asha@corp.test"))
    assert incident["technician"]["id"] == "T101"
    w.clock.advance(minutes=6)
    w.backend.p4.scheduler.run_now("escalation")
    texts = [h["description"] for h in history(w, admin, incident["id"])]
    assert "Escalated to A102 (level 2)" in texts
    assert not any("Escalated to T101" in t for t in texts)


@case(id="TC-P2-31", category="business-rule",
      desc="A 'Not sure' report is classified by the categorizer before assignment",
      expected="Category DATABASE, status passes through CLASSIFIED, skill-based picks T101")
def test_not_sure_report_is_auto_classified(w: World) -> None:
    w.backend.incidents.set_category_predictor(lambda text: ("database", 0.91))
    incident = w.report(w.login("asha@corp.test"), category=None,
                        description="Reporting queries time out on the core database")
    assert incident["category"] == "DATABASE"
    assert incident["technician"]["id"] == "T101"  # the database-skilled technician
    texts = [h["description"] for h in incident["history"]]
    assert "Classified as DATABASE automatically (91% confident)" in texts
    assert "Assigned to T101 by skill-based strategy" in texts


@case(id="TC-P2-32", category="exception",
      desc="Categorizer unsure, naming an unknown category, or crashing",
      expected="The report still succeeds, unclassified; nothing is guessed")
def test_auto_classification_never_blocks_a_report(w: World) -> None:
    emp = w.login("asha@corp.test")
    predictors: list[Callable[[str], Any]] = [
        lambda text: None,                 # unsure
        lambda text: ("PLUMBING", 0.99),   # not a category we have
        lambda text: 1 / 0,                # the model itself fails
    ]
    for n, predictor in enumerate(predictors):
        w.backend.incidents.set_category_predictor(predictor)
        incident = w.report(emp, category=None, description=f"Something odd happened #{n}")
        assert incident["category"] == "UNCLASSIFIED"
        assert incident["status"] == "ASSIGNED"


@case(id="TC-P2-33", category="normal",
      desc="Admin overrides the calculated priority with a reason",
      expected="Priority P3, audited with the reason; the SLA deadline moves")
def test_staff_priority_override(w: World) -> None:
    admin = w.login("admin@corp.test")
    incident = w.report(w.login("asha@corp.test"))
    assert incident["priority"] == "P1"
    r = w.client.post(f"/api/incidents/{incident['id']}/priority", headers=admin,
                      json={"priority": "P3", "reason": "Only the test site is affected"})
    assert r.status_code == 200, r.text
    body = r.json()
    assert body["priority"] == "P3"
    assert body["sla"]["resolutionDeadline"] > incident["sla"]["resolutionDeadline"]
    assert "Priority set to P3 (Only the test site is affected)" in [
        h["description"] for h in body["history"]]


@case(id="TC-P2-34", category="authorization",
      desc="Employee tries to change priority; staff send an invalid priority",
      expected="Employee 403; invalid value 422; priority unchanged")
def test_priority_override_is_staff_only(w: World) -> None:
    emp, admin = w.login("asha@corp.test"), w.login("admin@corp.test")
    incident_id = w.report(emp)["id"]
    url = f"/api/incidents/{incident_id}/priority"
    assert w.client.post(url, headers=emp, json={"priority": "P4"}).status_code == 403
    assert w.client.post(url, headers=admin, json={"priority": "P9"}).status_code == 422
    assert w.client.get(f"/api/incidents/{incident_id}", headers=admin).json()["priority"] == "P1"


@case(id="TC-P2-35", category="exception",
      desc="Same reporter submits the same report twice within 5 minutes",
      expected="Second is 409 DUPLICATE_INCIDENT; another person, or later, is accepted")
def test_exact_resubmission_is_refused(world_factory: Callable[..., World]) -> None:
    w = world_factory(DUPLICATE_RESUBMIT_SECONDS=300)
    asha, bilal = w.login("asha@corp.test"), w.login("bilal@corp.test")
    first = w.report(asha)["id"]
    body = {"description": "  payment APP down, users cannot complete transactions ",
            "serviceId": "SVC-PAY", "category": "APPLICATION", "impact": "HIGH",
            "urgency": "HIGH", "affectedUsers": 120}
    again = w.client.post("/api/incidents", headers=asha, json=body)
    assert again.status_code == 409
    assert again.json()["code"] == "DUPLICATE_INCIDENT" and first in again.json()["message"]
    assert w.client.post("/api/incidents", headers=bilal, json=body).status_code == 201
    w.clock.advance(minutes=6)
    assert w.client.post("/api/incidents", headers=asha, json=body).status_code == 201


@case(id="TC-P2-36", category="exception",
      desc="The database is unreachable during a request",
      expected="503 with code DATABASE_UNAVAILABLE as JSON, not a raw 500")
def test_database_failure_is_reported_cleanly(
    w: World, monkeypatch: pytest.MonkeyPatch
) -> None:
    headers = w.login("asha@corp.test")

    def down(*_args: Any, **_kwargs: Any) -> Any:
        raise OperationalError("SELECT 1", {}, ConnectionError("connection refused"))

    monkeypatch.setattr(w.backend.incidents, "list", down)
    r = w.client.get("/api/incidents", headers=headers)
    assert r.status_code == 503
    assert r.json()["code"] == "DATABASE_UNAVAILABLE"


@case(id="TC-P2-37", category="business-rule",
      desc="A refused action and an auto-close as they appear in the audit trail",
      expected="Refusal keeps its status in both columns; auto-close never claims a "
               "verification by the reporter")
def test_audit_wording_for_refusals_and_auto_close(world_factory: Callable[..., World]) -> None:
    w = world_factory(with_p4=True)
    emp, tech, admin = (w.login(e) for e in
                        ("asha@corp.test", "ravi@corp.test", "admin@corp.test"))
    incident_id = w.report(emp)["id"]
    assert w.act(admin, incident_id, "close").status_code == 409
    refused = next(h for h in history(w, admin, incident_id) if h["action"] == "rejected")
    assert refused["previousStatus"] == refused["newStatus"] == "ASSIGNED"

    for action in ("acknowledge", "start_work"):
        w.act(tech, incident_id, action)
    w.act(tech, incident_id, "resolve", "Restarted gateway")
    w.clock.advance(days=4)
    w.backend.p4.scheduler.run_now("auto_close")
    texts = [h["description"] for h in history(w, admin, incident_id)]
    assert "Resolution verified by SYSTEM" not in texts
    assert any("auto-close" in t for t in texts)


def test_email_settings_are_read_from_dotenv(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.chdir(tmp_path)
    monkeypatch.delenv("EMAIL_BACKEND", raising=False)
    (tmp_path / ".env").write_text("EMAIL_BACKEND=smtp\nSMTP_HOST=mail.example.test\n")
    dev = make_settings("sqlite://").model_copy(update={"APP_ENV": "development"})
    assert _email_env(dev)["EMAIL_BACKEND"] == "smtp"
    # Tests never pick up a developer's real mail settings.
    assert "EMAIL_BACKEND" not in _email_env(make_settings("sqlite://"))
    monkeypatch.setenv("EMAIL_BACKEND", "simulated")
    assert _email_env(dev)["EMAIL_BACKEND"] == "simulated"  # the environment wins
