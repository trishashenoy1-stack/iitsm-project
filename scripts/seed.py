"""Seed demo data, idempotently (safe to run twice).

Split in two so the useful part works now:
  build_seed_plan(now)          PURE: what to create, with timestamps relative to `now`
                                so the demo always shows live warnings, breaches and
                                escalations. Ready now.
  PENDING_P2_apply_seed_plan()  writes the plan. Needs P2 to persist.
                                P1 (12 Nov): incidents are seeded by REPLAYING lifecycle
                                steps through IncidentFactory (no restore() yet). To get
                                past created_at times, build the factory with a FakeClock
                                set to plan.created_at and advance it between steps:
                                  clock = FakeClock(inc.created_at)
                                  i = factory.create(reporter, service, desc, impact, urgency)
                                  clock.advance(minutes=2); i.assign(technician=tech); ...
                                Idempotency: upsert by natural key (email, service name,
                                service x priority, incident key).

Run:  python -m scripts.seed [--dry-run]
"""

from __future__ import annotations

import argparse
import json
from dataclasses import asdict, dataclass, field
from datetime import UTC, datetime, timedelta


@dataclass(frozen=True)
class SeedUser:
    email: str
    name: str
    roles: tuple[str, ...]
    # Technicians only
    skills: tuple[str, ...] = ()
    capacity: int = 0
    experience_years: int = 0
    active: bool = True


@dataclass(frozen=True)
class SeedService:
    name: str
    criticality: str  # HIGH / MEDIUM / LOW


@dataclass(frozen=True)
class SeedSLAPolicy:
    service: str
    priority: str
    response_minutes: int
    resolution_minutes: int


@dataclass(frozen=True)
class SeedIncident:
    key: str  # natural key for idempotency (stored as e.g. external_ref, or title)
    title: str
    description: str
    reporter: str
    service: str
    category: str
    priority: str
    status: str
    created_at: datetime
    assigned_to: str | None = None
    acknowledged_at: datetime | None = None
    resolved_at: datetime | None = None
    resolution_text: str | None = None
    demo_purpose: str = ""


@dataclass
class SeedPlan:
    users: list[SeedUser] = field(default_factory=list)
    services: list[SeedService] = field(default_factory=list)
    sla_policies: list[SeedSLAPolicy] = field(default_factory=list)
    incidents: list[SeedIncident] = field(default_factory=list)


DEFAULT_SLA = {"P1": (5, 30), "P2": (15, 120), "P3": (60, 480), "P4": (240, 1440)}


def build_seed_plan(now: datetime) -> SeedPlan:
    if now.tzinfo is None:
        raise ValueError("now must be timezone-aware")
    p = SeedPlan()
    p.users = [
        SeedUser("admin@itsm.local", "Asha Admin", ("ADMIN",)),
        SeedUser("lead@itsm.local", "Tara Lead", ("TEAM_LEAD", "TECHNICIAN"),
                 ("Application", "Network"), 6, 8),
        SeedUser("sysadmin@itsm.local", "Sam Sysadmin", ("SYSTEM_ADMIN",)),
        SeedUser("manager@itsm.local", "Mira Manager", ("IT_MANAGER",)),
        SeedUser("tech.app@itsm.local", "Arjun App", ("TECHNICIAN",),
                 ("Application", "Database"), 5, 4),
        SeedUser("tech.net@itsm.local", "Neha Net", ("TECHNICIAN",),
                 ("Network", "Security", "Authentication"), 4, 6),
        SeedUser("tech.infra@itsm.local", "Ivan Infra", ("TECHNICIAN",),
                 ("Cloud", "Storage", "Hardware"), 3, 2),
        SeedUser("tech.off@itsm.local", "Omar Offline", ("TECHNICIAN",),
                 ("Software",), 3, 1, active=False),
        SeedUser("emp1@itsm.local", "Esha Employee", ("EMPLOYEE",)),
        SeedUser("emp2@itsm.local", "Ravi Reporter", ("EMPLOYEE",)),
    ]
    p.services = [
        SeedService("Payments", "HIGH"), SeedService("Identity & SSO", "HIGH"),
        SeedService("Core Database", "HIGH"), SeedService("Corporate Network", "MEDIUM"),
        SeedService("Employee Portal", "MEDIUM"), SeedService("File Storage", "LOW"),
    ]
    p.sla_policies = [
        SeedSLAPolicy(s.name, prio, r, res)
        for s in p.services for prio, (r, res) in DEFAULT_SLA.items()
    ]

    def ago(**kw: float) -> datetime:
        return now - timedelta(**kw)

    p.incidents = [
        SeedIncident("demo-p1-fresh", "Payment application unavailable",
                     "Users cannot complete transactions on the payment app", "emp1@itsm.local",
                     "Payments", "Application", "P1", "ASSIGNED", ago(minutes=1),
                     assigned_to="tech.app@itsm.local",
                     demo_purpose="Unacknowledged P1: escalates within minutes (workflow 3)"),
        SeedIncident("demo-dup-1", "Payment gateway down",
                     "Checkout fails, payment gateway returns errors", "emp2@itsm.local",
                     "Payments", "Application", "P1", "ASSIGNED", ago(minutes=3),
                     assigned_to="tech.app@itsm.local", demo_purpose="Duplicate cluster"),
        SeedIncident("demo-dup-2", "Transactions failing",
                     "Customers are unable to pay, payment service is down", "emp1@itsm.local",
                     "Payments", "Application", "P1", "CLASSIFIED", ago(minutes=2),
                     demo_purpose="Duplicate cluster"),
        SeedIncident("demo-warn", "VPN keeps disconnecting",
                     "VPN connects then disconnects after a minute", "emp2@itsm.local",
                     "Corporate Network", "Network", "P3", "ASSIGNED", ago(minutes=51),
                     assigned_to="tech.net@itsm.local",
                     demo_purpose="~85% through the 60-min response window: warning on next tick"),
        SeedIncident("demo-breached", "Shared drive not accessible",
                     "Cannot open the department shared drive", "emp1@itsm.local",
                     "File Storage", "Storage", "P2", "IN_PROGRESS", ago(hours=3),
                     assigned_to="tech.infra@itsm.local", acknowledged_at=ago(hours=2, minutes=50),
                     demo_purpose="Past 2h resolution deadline: breach"),
        SeedIncident("demo-paused", "Cannot sign in with SSO",
                     "SSO shows an invalid assertion error", "emp2@itsm.local",
                     "Identity & SSO", "Authentication", "P2", "AWAITING_INFO",
                     ago(minutes=40), assigned_to="tech.net@itsm.local",
                     acknowledged_at=ago(minutes=35), demo_purpose="SLA clock paused"),
        SeedIncident("demo-autoclose", "Excel crashes on open",
                     "Excel closes immediately when I open any spreadsheet", "emp1@itsm.local",
                     "Employee Portal", "Software", "P4", "RESOLVED", ago(days=5),
                     assigned_to="tech.app@itsm.local", acknowledged_at=ago(days=5),
                     resolved_at=ago(days=4), resolution_text="Repaired Office install.",
                     demo_purpose="Unverified > AUTO_CLOSE_DAYS: auto-closed on first tick"),
    ]
    p.incidents += _resolved_history(now)
    return p


def _resolved_history(now: datetime) -> list[SeedIncident]:
    """About 30 closed incidents with resolution text, so suggested resolutions have data."""
    history = [
        ("Payment gateway timeout", "Payments", "Application",
         "Restarted payment gateway pods and raised connection pool size."),
        ("Database connection refused", "Core Database", "Database",
         "Primary DB hit max_connections; killed idle sessions and raised the limit."),
        ("Account locked out", "Identity & SSO", "Authentication",
         "Unlocked account in directory and reset failed-attempt counter."),
        ("WiFi not working", "Corporate Network", "Network",
         "Rebooted wireless controller; firmware bug, scheduled upgrade."),
        ("Disk full on server", "File Storage", "Storage",
         "Rotated logs, cleared temp files, added log retention policy."),
        ("SSO login failing", "Identity & SSO", "Authentication",
         "Renewed expired SAML signing certificate on the IdP."),
    ]
    out = []
    for i in range(30):
        title, service, cat, fix = history[i % len(history)]
        created = now - timedelta(days=7 + i)
        out.append(SeedIncident(
            f"hist-{i:02d}", title, f"{title} reported by users (historic case {i})",
            "emp1@itsm.local" if i % 2 else "emp2@itsm.local", service, cat,
            ["P1", "P2", "P3", "P4"][i % 4], "CLOSED", created,
            assigned_to="tech.app@itsm.local", acknowledged_at=created + timedelta(minutes=4),
            resolved_at=created + timedelta(hours=1), resolution_text=fix,
            demo_purpose="history for suggested resolutions",
        ))
    return out


def apply_seed_plan(plan: SeedPlan) -> dict[str, int]:
    """Write `plan` through P2's services (app/seeding.py): upsert by natural key, so a
    second run creates no duplicate rows (spec test 20). Passwords come from
    SEED_PASSWORD and are hashed with Argon2. Deadlines come from P1's SLA tracker."""
    from app.seeding import apply_seed_plan as write

    return write(plan)


# Kept so existing imports keep working.
PENDING_P2_apply_seed_plan = apply_seed_plan


def main(argv: list[str] | None = None) -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--dry-run", action="store_true", help="print the plan, write nothing")
    args = ap.parse_args(argv)
    plan = build_seed_plan(datetime.now(UTC))
    if args.dry_run:
        print(json.dumps(asdict(plan), default=str, indent=2))
        return
    print(apply_seed_plan(plan))


if __name__ == "__main__":
    main()
