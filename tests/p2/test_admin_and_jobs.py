"""Assignment, admin settings, seeding, P4's jobs and notifications on the real DB (P2)."""

from __future__ import annotations

import time
from collections.abc import Callable

import pytest

from app.seeding import apply_seed_plan
from scripts.seed import build_seed_plan
from tests.p2.conftest import World

case = pytest.mark.case


@case(id="TC-P2-18", category="business-rule",
      desc="Admin switches the assignment strategy from skill-based to round-robin",
      expected="The next incidents go to technicians in turn, without a restart")
def test_strategy_switch_at_runtime(w: World) -> None:
    emp, admin = w.login("asha@corp.test"), w.login("admin@corp.test")
    assert w.report(emp)["technician"]["id"] == "T101"  # skill: APPLICATION
    r = w.client.patch("/api/admin/assignment-strategy", headers=admin,
                       json={"current": "ROUND_ROBIN"})
    assert r.json()["current"] == "ROUND_ROBIN"
    turns = [w.report(emp)["technician"]["id"] for _ in range(3)]
    assert turns == ["T101", "T102", "T101"]
    bad = w.client.patch("/api/admin/assignment-strategy", headers=admin,
                         json={"current": "RANDOM"})
    assert bad.status_code == 422


@case(id="TC-P2-19", category="boundary",
      desc="Every technician is at full capacity when an incident is reported",
      expected="The incident stays NEW and unassigned; the audit says why")
def test_no_capacity_leaves_incident_unassigned(w: World) -> None:
    emp, admin = w.login("asha@corp.test"), w.login("admin@corp.test")
    for tech in ("T101", "T102"):
        w.client.patch(f"/api/admin/technicians/{tech}", headers=admin, json={"maxWorkload": 1})
    w.report(emp)
    w.report(emp, category="NETWORK")
    third = w.report(emp)
    assert third["status"] == "CLASSIFIED" and third["technician"] is None
    assert third["history"][0]["action"] == "assign_failed"
    manual = w.client.post(f"/api/incidents/{third['id']}/assign", headers=admin,
                           json={"technicianId": "T102"})
    assert (manual.status_code, manual.json()["code"]) == (409, "TECHNICIAN_WORKLOAD_EXCEEDED")


@case(id="TC-P2-20", category="boundary", desc="Report with category 'Not sure' (none)",
      expected="Assigned by load instead of failing (P1's skill strategy needs a skill)")
def test_no_category_uses_load_based(w: World) -> None:
    incident = w.report(w.login("asha@corp.test"), category=None)
    assert incident["status"] == "ASSIGNED"
    assert "load-based" in incident["history"][0]["description"]


def test_admin_manual_assignment_and_reference_data(w: World) -> None:
    admin, emp = w.login("admin@corp.test"), w.login("asha@corp.test")
    w.client.patch("/api/admin/technicians/T101", headers=admin, json={"available": False})
    w.client.patch("/api/admin/technicians/T102", headers=admin, json={"available": False})
    iid = w.report(emp)["id"]
    w.client.patch("/api/admin/technicians/T102", headers=admin, json={"available": True})
    r = w.client.post(f"/api/incidents/{iid}/assign", headers=admin, json={"technicianId": "T102"})
    assert r.json()["technician"]["id"] == "T102"
    assert w.client.post(f"/api/incidents/{iid}/assign", headers=emp,
                         json={"technicianId": "T101"}).status_code == 403

    svc = w.client.post("/api/admin/services", headers=admin,
                        json={"name": "VPN", "criticality": 4}).json()
    assert svc["active"]
    assert w.client.post("/api/admin/services", headers=admin,
                         json={"name": "vpn", "criticality": 4}).status_code == 409
    assert w.client.post("/api/admin/services", headers=admin,
                         json={"name": "X", "criticality": 9}).status_code == 422
    w.client.patch(f"/api/admin/services/{svc['id']}", headers=admin, json={"active": False})
    assert "VPN" not in [s["name"] for s in w.client.get("/api/services", headers=emp).json()]


def test_reporting_against_inactive_service_fails(w: World) -> None:
    admin, emp = w.login("admin@corp.test"), w.login("asha@corp.test")
    w.client.patch("/api/admin/services/SVC-MAIL", headers=admin, json={"active": False})
    r = w.client.post("/api/incidents", headers=emp, json={
        "description": "Mail is slow", "serviceId": "SVC-MAIL", "category": None,
        "impact": "LOW", "urgency": "LOW", "affectedUsers": 1})
    assert (r.status_code, r.json()["code"]) == (404, "SERVICE_NOT_FOUND")


@case(id="TC-P2-21", category="business-rule",
      desc="Admin shortens the P1 resolution target",
      expected="New incidents use it; a response target >= resolution is refused")
def test_sla_policy_update(w: World) -> None:
    admin = w.login("admin@corp.test")
    r = w.client.patch("/api/admin/sla-policies/P1", headers=admin, json={"resolutionMinutes": 20})
    assert r.json() == {"priority": "P1", "responseMinutes": 5, "resolutionMinutes": 20}
    incident = w.report(w.login("asha@corp.test"))
    assert incident["sla"]["resolutionTargetSeconds"] == 20 * 60
    bad = w.client.patch("/api/admin/sla-policies/P1", headers=admin, json={"responseMinutes": 30})
    assert bad.status_code == 422


def test_admin_reports(w: World) -> None:
    emp, admin = w.login("asha@corp.test"), w.login("admin@corp.test")
    w.report(emp)
    w.clock.advance(hours=1)  # P1 resolution target is 30 minutes
    overview = w.client.get("/api/admin/reports/overview", headers=admin).json()
    assert (overview["total"], overview["open"], overview["critical"]) == (1, 1, 1)
    assert overview["slaViolations"] == 1
    violations = w.client.get("/api/admin/sla-violations", headers=admin).json()
    assert {v["type"] for v in violations} == {"Response", "Resolution"}
    audit = w.client.get("/api/admin/audit-log", headers=admin).json()
    assert audit[0]["incidentId"] and {"created", "assign"} <= {a["action"] for a in audit}


@case(id="TC-P2-22", category="normal", desc="Seed script run twice",
      expected="Second run creates no users, services or incidents")
def test_seed_is_idempotent(w: World) -> None:
    plan = build_seed_plan(w.clock.now())
    first = apply_seed_plan(plan, backend=w.backend)
    second = apply_seed_plan(plan, backend=w.backend)
    assert first["incidents"] == len(plan.incidents) and first["users"] == len(plan.users)
    assert second == {"users": 0, "services": 0, "incidents": 0}
    with w.backend.uow_factory() as uow:
        paused = uow.incidents.get(
            next(r.id for r in uow.incidents.search({}) if r.seed_key == "demo-paused"))
        assert paused.status.value == "AWAITING_INFO" and paused.sla.is_paused


@case(id="TC-P2-23", category="business-rule",
      desc="P4's SLA monitor runs twice on the real database, then the server restarts",
      expected="Breach recorded once; not re-reported after the restart")
def test_sla_monitor_reports_once_across_restart(world_factory: Callable[..., World]) -> None:
    w = world_factory(with_p4=True)
    iid = w.report(w.login("asha@corp.test"))["id"]
    w.clock.advance(minutes=40)
    first = w.backend.p4.scheduler.run_now("sla_monitor")
    assert first.actions["response_breach"] == 1 and first.actions["resolution_breach"] == 1
    assert not w.backend.p4.scheduler.run_now("sla_monitor").actions
    restarted = w.restart()
    restarted.backend.start_p4()
    assert not restarted.backend.p4.scheduler.run_now("sla_monitor").actions
    history = w.client.get(f"/api/incidents/{iid}", headers=w.login("admin@corp.test")).json()
    assert [h["action"] for h in history["history"]].count("sla_breach") == 2


@case(id="TC-P2-24", category="business-rule",
      desc="Unacknowledged P1 escalates; acknowledged one doesn't",
      expected="Escalated to the level-1 user once, then the chain is flagged exhausted")
def test_escalation_job(world_factory: Callable[..., World]) -> None:
    w = world_factory(with_p4=True)
    emp, tech = w.login("asha@corp.test"), w.login("ravi@corp.test")
    waiting = w.report(emp)["id"]
    acked = w.report(emp)["id"]
    w.act(tech, acked, "acknowledge")
    w.clock.advance(minutes=6)
    run = w.backend.p4.scheduler.run_now("escalation")
    assert run.actions["escalated"] == 1 and not run.errors
    w.clock.advance(minutes=6)
    assert w.backend.p4.scheduler.run_now("escalation").actions["chain_exhausted"] == 1
    assert not w.backend.p4.scheduler.run_now("escalation").actions
    admin = w.login("admin@corp.test")
    actions = [h["action"] for h in
               w.client.get(f"/api/incidents/{waiting}", headers=admin).json()["history"]]
    assert actions.count("escalated") == 1 and "escalation_exhausted" in actions


def test_auto_close_and_duplicates(world_factory: Callable[..., World]) -> None:
    w = world_factory(with_p4=True)
    emp, tech, admin = (w.login(e) for e in
                        ("asha@corp.test", "ravi@corp.test", "admin@corp.test"))
    first = w.report(emp)["id"]
    second = w.report(emp, description="Payment app is down and users cannot complete "
                                       "transactions")
    assert first in [d["id"] for d in w.client.get(
        f"/api/incidents/{second['id']}", headers=admin).json()["possibleDuplicates"]]
    for action in ("acknowledge", "start_work"):
        w.act(tech, first, action)
    w.act(tech, first, "resolve", "Restarted gateway")
    w.clock.advance(days=4)
    assert w.backend.p4.scheduler.run_now("auto_close").actions["auto_closed"] == 1
    assert w.client.get(f"/api/incidents/{first}", headers=admin).json()["status"] == "CLOSED"
    clusters = w.client.get("/api/admin/reports/clusters", headers=admin)
    assert clusters.status_code == 200


@case(id="TC-P2-25", category="normal",
      desc="Incident assigned while the server runs (notification worker on)",
      expected="Technician and reporter get stored in-app notifications")
def test_notifications_are_stored(w: World) -> None:
    with w.client:  # runs the app lifespan, which starts the notification worker
        emp, tech = w.login("asha@corp.test"), w.login("ravi@corp.test")
        iid = w.report(emp)["id"]
        deadline = time.monotonic() + 5
        mine: list[dict[str, object]] = []
        while time.monotonic() < deadline and not mine:
            mine = w.client.get("/api/notifications", headers=tech).json()
            time.sleep(0.05)
        assert any(n["incidentId"] == iid for n in mine)
        assert w.client.post("/api/notifications/read-all", headers=tech).status_code == 204
        assert all(n["read"] for n in w.client.get("/api/notifications", headers=tech).json())


def test_round_robin_pointer_survives_restart(w: World) -> None:
    admin, emp = w.login("admin@corp.test"), w.login("asha@corp.test")
    w.client.patch("/api/admin/assignment-strategy", headers=admin, json={"current": "ROUND_ROBIN"})
    assert w.report(emp)["technician"]["id"] == "T101"
    w2 = w.restart()
    assert w2.report(w2.login("asha@corp.test"))["technician"]["id"] == "T102"
