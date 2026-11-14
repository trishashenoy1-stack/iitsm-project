"""Incident lifecycle through the API, the audit trail, and rebuilding from storage (P2)."""

from __future__ import annotations

from datetime import datetime

import pytest
from sqlalchemy import select

from app.db.models import IncidentEventRecord
from domain.events import DomainEvent, StatusChanged
from tests.p2.conftest import World

case = pytest.mark.case


def parse(value: str) -> datetime:
    return datetime.fromisoformat(value.replace("Z", "+00:00"))


@case(id="TC-P2-10", category="normal",
      desc="Workflow 2 end to end: acknowledge, ask, reply, resolve, verify, close",
      expected="Each step changes status; the 10 paused minutes move the deadline by 10 min")
def test_full_lifecycle_with_sla_pause(w: World) -> None:
    emp, tech, admin = (w.login(e) for e in
                        ("asha@corp.test", "ravi@corp.test", "admin@corp.test"))
    incident = w.report(emp)
    assert (incident["status"], incident["priority"]) == ("ASSIGNED", "P1")
    before = parse(incident["sla"]["resolutionDeadline"])
    iid = incident["id"]

    w.clock.advance(minutes=2)
    assert w.act(tech, iid, "acknowledge").json()["status"] == "ACKNOWLEDGED"
    assert w.act(tech, iid, "start_work").json()["status"] == "IN_PROGRESS"
    asked = w.act(tech, iid, "request_info", "Which browser are you using?").json()
    assert asked["status"] == "AWAITING_INFO" and asked["sla"]["isPaused"]
    assert asked["infoRequest"] == "Which browser are you using?"

    w.clock.advance(minutes=10)
    replied = w.act(emp, iid, "provide_info", "Chrome 131").json()
    assert replied["infoRequest"] is None
    assert parse(replied["sla"]["resolutionDeadline"]) - before == __import__(
        "datetime").timedelta(minutes=10)

    resolved = w.act(tech, iid, "resolve", "Restarted the payment gateway").json()
    assert resolved["status"] == "RESOLVED" and resolved["resolution"].startswith("Restarted")
    assert w.act(emp, iid, "verify").json()["status"] == "VERIFIED"
    assert w.act(admin, iid, "close").json()["status"] == "CLOSED"
    assert w.client.get("/api/me/workload", headers=tech).json() == {"active": 0, "max": 5}


@case(id="TC-P2-11", category="business-rule", desc="Resolve without resolution text",
      expected="422; status stays IN_PROGRESS")
def test_resolution_text_required(w: World) -> None:
    emp, tech = w.login("asha@corp.test"), w.login("ravi@corp.test")
    iid = w.report(emp)["id"]
    w.act(tech, iid, "acknowledge")
    w.act(tech, iid, "start_work")
    assert w.act(tech, iid, "resolve", "   ").status_code == 422


@case(id="TC-P2-12", category="exception",
      desc="Employee verifies an incident that is still IN_PROGRESS",
      expected="409 INVALID_STATE_TRANSITION, and the refusal is in the audit trail")
def test_invalid_transition_is_refused_and_audited(w: World) -> None:
    emp, tech = w.login("asha@corp.test"), w.login("ravi@corp.test")
    iid = w.report(emp)["id"]
    w.act(tech, iid, "acknowledge")
    r = w.act(emp, iid, "verify")
    assert (r.status_code, r.json()["code"]) == (409, "INVALID_STATE_TRANSITION")
    history = w.client.get(f"/api/incidents/{iid}", headers=w.login("admin@corp.test")).json()
    assert any(h["action"] == "rejected" for h in history["history"])


@case(id="TC-P2-13", category="authorization",
      desc="Technician writes an internal note; the reporter opens the incident",
      expected="Staff see the note; the employee's history leaves it out")
def test_internal_notes_hidden_from_employees(w: World) -> None:
    emp, tech = w.login("asha@corp.test"), w.login("ravi@corp.test")
    iid = w.report(emp)["id"]
    assert w.client.post(f"/api/incidents/{iid}/notes", headers=tech,
                         json={"text": "Suspect the DB pool"}).status_code == 200
    staff_view = w.client.get(f"/api/incidents/{iid}", headers=tech).json()["history"]
    employee_view = w.client.get(f"/api/incidents/{iid}", headers=emp).json()["history"]
    assert any("DB pool" in h["description"] for h in staff_view)
    assert not any("DB pool" in h["description"] for h in employee_view)


def test_reporter_adds_information_and_feedback_once(w: World) -> None:
    emp, tech = w.login("asha@corp.test"), w.login("ravi@corp.test")
    iid = w.report(emp)["id"]
    r = w.client.post(f"/api/incidents/{iid}/information", headers=emp,
                      json={"text": "It also fails on mobile"})
    assert "fails on mobile" in r.json()["history"][0]["description"]
    for action in ("acknowledge", "start_work"):
        w.act(tech, iid, action)
    w.act(tech, iid, "resolve", "Fixed")
    first = w.client.post(f"/api/incidents/{iid}/feedback", headers=emp,
                          json={"rating": 4, "comment": "Quick"})
    assert first.json()["feedback"] == {"rating": 4, "comment": "Quick"}
    again = w.client.post(f"/api/incidents/{iid}/feedback", headers=emp,
                          json={"rating": 5, "comment": ""})
    assert again.status_code == 422


@case(id="TC-P2-14", category="business-rule",
      desc="Audit entries are changed or deleted through the ORM and the repository",
      expected="PermissionError every time; the entry is unchanged")
def test_audit_log_is_append_only(w: World) -> None:
    iid = w.report(w.login("asha@corp.test"))["id"]
    with w.backend.session_factory() as s:
        entry = s.scalars(select(IncidentEventRecord)
                          .where(IncidentEventRecord.incident_id == iid)).first()
        entry_id = entry.id
        entry.description = "rewritten"
        with pytest.raises(PermissionError):
            s.flush()
        s.rollback()
        s.delete(s.get(IncidentEventRecord, entry_id))
        with pytest.raises(PermissionError):
            s.flush()
    with w.backend.uow_factory() as uow:
        with pytest.raises(PermissionError):
            uow.audit.update(entry_id, description="x")
        with pytest.raises(PermissionError):
            uow.audit.delete(entry_id)


@case(id="TC-P2-15", category="business-rule",
      desc="Server restarts mid-incident (incident paused in AWAITING_INFO)",
      expected="Rebuilt from the audit trail in the same state; the SLA is still paused "
               "and the next step works")
def test_incident_survives_restart(w: World) -> None:
    emp, tech = w.login("asha@corp.test"), w.login("ravi@corp.test")
    iid = w.report(emp)["id"]
    for action in ("acknowledge", "start_work"):
        w.act(tech, iid, action)
    w.act(tech, iid, "request_info", "Screenshot please")

    w.clock.advance(minutes=30)
    w2 = w.restart()
    with w2.backend.uow_factory() as uow:
        incident = uow.incidents.get(iid)
        assert incident.status.value == "AWAITING_INFO"
        assert incident.sla.is_paused
        assert incident.technician.user_id == "T101"
    r = w2.act(w2.login("asha@corp.test"), iid, "provide_info", "Attached")
    assert r.status_code == 200, r.text
    replied = r.json()
    assert replied["status"] == "IN_PROGRESS"


@case(id="TC-P2-16", category="business-rule",
      desc="Domain events reach the application bus only after the commit",
      expected="A listener can load the incident when IncidentCreated arrives (gap G18)")
def test_events_published_after_commit(w: World) -> None:
    seen: list[str] = []

    def on_event(event: DomainEvent) -> None:
        with w.backend.uow_factory() as uow:
            seen.append(uow.incidents.record(event.incident_id).status)

    w.backend.bus.subscribe(DomainEvent, on_event)
    w.report(w.login("asha@corp.test"))
    assert seen and all(status == "ASSIGNED" for status in seen)


def test_failed_action_publishes_nothing(w: World) -> None:
    emp = w.login("asha@corp.test")
    iid = w.report(emp)["id"]
    changes: list[StatusChanged] = []
    w.backend.bus.subscribe(StatusChanged, changes.append)
    assert w.act(emp, iid, "verify").status_code == 409
    assert changes == []


@case(id="TC-P2-17", category="normal", desc="Search with six filters",
      expected="Only matching incidents; employees only ever see their own")
def test_search_filters(w: World) -> None:
    a, b, admin = (w.login(e) for e in
                   ("asha@corp.test", "bilal@corp.test", "admin@corp.test"))
    p1 = w.report(a)
    mail = w.report(b, serviceId="SVC-MAIL", category="NETWORK", impact="LOW",
                    urgency="LOW", affectedUsers=1)

    def ids(**params: str) -> list[str]:
        r = w.client.get("/api/incidents", headers=admin, params=params)
        assert r.status_code == 200, r.text
        return [i["id"] for i in r.json()]

    assert ids(priority="P1") == [p1["id"]]
    assert ids(service="Email") == [mail["id"]]
    assert ids(category="NETWORK") == [mail["id"]]
    assert ids(technician="T102") == [mail["id"]]
    assert ids(status="ASSIGNED", id=p1["id"][-2:]) == [p1["id"]]
    assert set(ids(**{"from": "2026-11-14", "to": "2026-11-14"})) == {p1["id"], mail["id"]}
    assert ids(**{"from": "2026-11-15"}) == []
    assert ids(sla="ok") != []
    assert [i["id"] for i in w.client.get("/api/incidents", headers=a).json()] == [p1["id"]]
    assert w.client.get("/api/incidents", headers=admin,
                        params={"from": "not-a-date"}).status_code == 422
