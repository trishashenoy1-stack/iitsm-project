"""Generate synthetic labelled incidents and duplicate pairs (fixed seed, reproducible).

Method (document this in the report):
  * 9 categories x 3 "problems" each; every problem has 3+ hand-written paraphrases.
  * An incident = random paraphrase + random context phrase + random service from the
    category's plausible services.
  * Duplicate pairs:
      positive       two different paraphrases of the same problem, same service
      hard negative  same service, different problem
      easy negative  different category
  * Pairs are split 50/50 into dev (threshold tuning) and test (reported numbers).

Run:  python -m scripts.gen_synthetic [--per-category 80] [--pairs 600]
"""

from __future__ import annotations

import argparse
import json
import random
from pathlib import Path

PROBLEMS: dict[str, dict[str, list[tuple[str, str]]]] = {
    "Hardware": {
        "laptop_no_boot": [
            ("Laptop will not turn on", "My laptop does not power on even when plugged in"),
            ("Machine dead on power button", "Pressing the power button does nothing, no lights"),
            ("Notebook fails to boot", "The notebook shows a black screen and never starts"),
        ],
        "printer_jam": [
            ("Printer paper jam", "The office printer keeps jamming on every page"),
            ("Printing stuck on floor 3", "Printer reports a paper jam and will not print"),
            ("Cannot print, jam error", "Shared printer shows jam error even after clearing it"),
        ],
        "monitor_flicker": [
            ("Monitor flickering", "External monitor flickers and goes blank every few seconds"),
            ("Screen keeps blinking", "My display blinks on and off constantly"),
            ("Display flicker on dock", "Second screen flickers when connected through the dock"),
        ],
    },
    "Software": {
        "office_crash": [
            ("Excel crashes on open", "Excel closes immediately when I open any spreadsheet"),
            ("Spreadsheet app keeps crashing", "Office spreadsheet application crashes on start"),
            ("Excel not responding", "Excel freezes and then crashes when opening files"),
        ],
        "license_expired": [
            ("Software license expired", "Design tool says my license has expired"),
            ("Licence activation failed", "Application asks to activate license and rejects key"),
            ("License error on startup", "Getting a license invalid message when launching"),
        ],
        "update_failed": [
            ("Update fails to install", "System update fails with an error at 80 percent"),
            ("Patch installation error", "Latest patch will not install, rolls back each time"),
            ("Cannot apply software update", "Software update keeps failing and retrying"),
        ],
    },
    "Network": {
        "wifi_down": [
            ("WiFi not working", "Office wireless network is not connecting on any device"),
            ("No wireless connectivity", "Cannot connect to corporate wifi since morning"),
            ("Wireless network down", "Wifi drops immediately after connecting"),
        ],
        "vpn_fail": [
            ("VPN cannot connect", "VPN client times out when connecting from home"),
            ("Remote VPN failure", "Unable to establish VPN tunnel, authentication times out"),
            ("VPN keeps disconnecting", "VPN connects then disconnects after a minute"),
        ],
        "slow_network": [
            ("Network extremely slow", "Internet and intranet pages take minutes to load"),
            ("Very slow connection", "Network speed has dropped, downloads crawl"),
            ("Latency issues on LAN", "High latency and packet loss on the office network"),
        ],
    },
    "Database": {
        "db_down": [
            ("Database server unreachable", "Applications cannot connect to the main database"),
            ("DB connection refused", "Connection refused errors from the production database"),
            ("Primary database down", "Database is not accepting connections"),
        ],
        "slow_queries": [
            ("Reports query very slow", "Database queries for reports take over ten minutes"),
            ("DB performance degraded", "Queries are timing out, database CPU is at 100"),
            ("Slow database response", "Database responses are very slow since the migration"),
        ],
        "replication_lag": [
            ("Replica lag high", "Read replica is hours behind the primary database"),
            ("Replication delay", "Database replication is lagging, stale data in reports"),
            ("Replica out of sync", "Standby database is not in sync with primary"),
        ],
    },
    "Cloud": {
        "vm_down": [
            ("Cloud VM not responding", "Our cloud virtual machine is unreachable over ssh"),
            ("Instance stopped unexpectedly", "Cloud instance shut down by itself"),
            ("Virtual machine offline", "Cloud server shows as stopped in the console"),
        ],
        "cost_spike": [
            ("Cloud bill spike", "Cloud costs increased five times this week"),
            ("Unexpected cloud charges", "Billing alert for unusual cloud spending"),
            ("Cloud spend anomaly", "Cost dashboard shows a huge jump in compute charges"),
        ],
        "deploy_fail": [
            ("Deployment pipeline failing", "Cloud deployment fails at the container push step"),
            ("Cannot deploy to cloud", "Release deploy to the cloud cluster errors out"),
            ("Cluster rollout failed", "Kubernetes rollout stuck and pods crash looping"),
        ],
    },
    "Security": {
        "phishing": [
            ("Phishing email received", "Got a suspicious email asking for my password"),
            ("Suspicious email link", "Email with a fake login link sent to the whole team"),
            ("Possible phishing attempt", "Received mail impersonating IT asking for credentials"),
        ],
        "malware": [
            ("Malware detected", "Antivirus flagged a trojan on my workstation"),
            ("Virus alert on laptop", "Security software reports infected files"),
            ("Ransomware warning", "Files renamed with strange extensions and ransom note"),
        ],
        "unauthorized_access": [
            ("Unauthorized login alert", "Alert of login to my account from another country"),
            ("Suspicious account activity", "Someone accessed my account without permission"),
            ("Unknown access to server", "Audit log shows unknown user accessing a server"),
        ],
    },
    "Authentication": {
        "password_reset": [
            ("Cannot reset password", "Password reset link is not arriving in my inbox"),
            ("Password reset broken", "Reset password page gives an error"),
            ("Forgot password flow failing", "Unable to complete forgot password process"),
        ],
        "account_locked": [
            ("Account locked out", "My account is locked after a few login attempts"),
            ("Locked out of account", "Cannot log in, says account is locked"),
            ("User account lockout", "Several users locked out of their accounts"),
        ],
        "sso_fail": [
            ("SSO login failing", "Single sign on redirects back to the login page"),
            ("Cannot sign in with SSO", "SSO shows an invalid assertion error"),
            ("Single sign-on broken", "Login through the identity provider fails"),
        ],
    },
    "Application": {
        "payment_down": [
            ("Payment application unavailable", "Users cannot complete transactions on payments"),
            ("Payment gateway down", "Checkout fails, payment gateway returns errors"),
            ("Transactions failing", "Customers are unable to pay, payment service is down"),
        ],
        "app_500": [
            ("Portal returns 500 errors", "Employee portal shows internal server error"),
            ("HR app server error", "HR application throws 500 on every page"),
            ("Web app internal error", "Internal web application failing with error 500"),
        ],
        "app_slow": [
            ("CRM very slow", "CRM application takes a long time to load records"),
            ("Application performance poor", "Business app pages load slowly for everyone"),
            ("Sluggish internal app", "Internal tool is extremely slow since yesterday"),
        ],
    },
    "Storage": {
        "disk_full": [
            ("Disk full on server", "Server disk usage at 100 percent, services failing"),
            ("Out of disk space", "No space left on device errors on the file server"),
            ("Storage volume full", "Storage volume has run out of space"),
        ],
        "share_unavailable": [
            ("Shared drive not accessible", "Cannot open the department shared drive"),
            ("Network share missing", "Mapped network share disappeared from my computer"),
            ("File share down", "Team file share is unavailable"),
        ],
        "backup_failed": [
            ("Backup job failed", "Nightly backup job failed with a storage error"),
            ("Backups not completing", "Scheduled backups have not completed for two days"),
            ("Backup error", "Backup system reports failure writing to storage"),
        ],
    },
}

SERVICES: dict[str, list[str]] = {
    "Hardware": ["End-User Devices", "Printing"],
    "Software": ["Office Suite", "Desktop Apps"],
    "Network": ["Corporate Network", "VPN"],
    "Database": ["Core Database", "Reporting DB"],
    "Cloud": ["Cloud Platform", "CI/CD"],
    "Security": ["Security Operations", "Email"],
    "Authentication": ["Identity & SSO", "Directory"],
    "Application": ["Payments", "Employee Portal", "CRM"],
    "Storage": ["File Storage", "Backup"],
}

CONTEXT = [
    "", "since this morning", "for the whole team", "urgent please help",
    "started after lunch", "affecting several users", "in the Hyderabad office",
    "happening again", "since yesterday evening", "blocking my work",
]


def _incident(rng: random.Random, category: str, problem: str) -> dict[str, str]:
    title, desc = rng.choice(PROBLEMS[category][problem])
    ctx = rng.choice(CONTEXT)
    return {
        "title": title,
        "description": f"{desc} {ctx}".strip(),
        "category": category,
        "problem": problem,
        "service": rng.choice(SERVICES[category]),
    }


def generate_incidents(rng: random.Random, per_category: int) -> list[dict[str, str]]:
    rows = []
    for category, problems in PROBLEMS.items():
        names = list(problems)
        for _ in range(per_category):
            rows.append(_incident(rng, category, rng.choice(names)))
    rng.shuffle(rows)
    return rows


def generate_pairs(rng: random.Random, n: int) -> list[dict[str, object]]:
    cats = list(PROBLEMS)
    pairs: list[dict[str, object]] = []
    kinds = ["positive", "hard_negative", "easy_negative"]
    for i in range(n):
        kind = kinds[i % 3]
        cat = rng.choice(cats)
        prob = rng.choice(list(PROBLEMS[cat]))
        a = _incident(rng, cat, prob)
        if kind == "positive":
            choices = [p for p in PROBLEMS[cat][prob] if p[0] != a["title"]]
            title, desc = rng.choice(choices)
            b = {**a, "title": title, "description": f"{desc} {rng.choice(CONTEXT)}".strip()}
        elif kind == "hard_negative":
            other = rng.choice([p for p in PROBLEMS[cat] if p != prob])
            b = {**_incident(rng, cat, other), "service": a["service"]}
        else:
            other_cat = rng.choice([c for c in cats if c != cat])
            b = _incident(rng, other_cat, rng.choice(list(PROBLEMS[other_cat])))
        pairs.append({
            "a": a, "b": b, "label": int(kind == "positive"), "kind": kind,
            "split": "dev" if rng.random() < 0.5 else "test",
        })
    return pairs


def write_jsonl(path: Path, rows: list[dict[str, object]] | list[dict[str, str]]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", encoding="utf-8") as f:
        for r in rows:
            f.write(json.dumps(r, ensure_ascii=False) + "\n")


def main(argv: list[str] | None = None) -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--per-category", type=int, default=80)
    ap.add_argument("--pairs", type=int, default=600)
    ap.add_argument("--seed", type=int, default=42)
    ap.add_argument("--out-dir", type=Path, default=Path("data"))
    args = ap.parse_args(argv)

    rng = random.Random(args.seed)
    incidents = generate_incidents(rng, args.per_category)
    pairs = generate_pairs(rng, args.pairs)
    write_jsonl(args.out_dir / "synthetic_incidents.jsonl", incidents)
    write_jsonl(args.out_dir / "duplicate_pairs.jsonl", pairs)
    print(f"wrote {len(incidents)} incidents and {len(pairs)} pairs to {args.out_dir}")


if __name__ == "__main__":
    main()
