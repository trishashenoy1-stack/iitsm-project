# I-ITSM — P4 Spec: Intelligence, Background Jobs, DevOps, Test Lead

Owner: P4 (Sid). Language: Python 3.11+. Feature freeze: 17 Nov. Submission: 22 Nov (target 20 Nov).

## 1. Scope

P4 owns:
1. Background jobs: SLA monitor, SLA warnings, automatic escalation, auto-close of unverified RESOLVED incidents.
2. Intelligent features: duplicate detection + correlation, auto-categorization, suggested resolution.
3. DevOps: Dockerfile, docker-compose (app + Postgres), GitHub Actions CI, deployment.
4. Data: seed script, synthetic labelled incident dataset.
5. Test lead: test infrastructure, testing chapter (15+ formal cases).

P4 does NOT own: domain rules (P1), DB models/repositories/API routes (P2), UI and notification channels (P3).
Rule: P4 code calls P1 domain logic and P2 repositories. It never reimplements state transitions, SLA math, or priority rules.

Priority order if time runs short (MVP first):
1. SLA monitor + warnings (MVP, mandatory)
2. Escalation (counts as intelligent feature #1)
3. Duplicate detection (intelligent feature #2)
4. Auto-categorization
5. Suggested resolution (drop first)

## 2. Directory layout (P4-owned parts)

```
app/
  intelligence/
    __init__.py
    embedder.py          # Embedder interface + MiniLM implementation
    duplicates.py        # DuplicateDetector, correlation grouping
    categorizer.py       # IncidentCategorizer (embeddings + LogisticRegression)
    resolution.py        # ResolutionSuggester (kNN over resolved incidents)
    listeners.py         # Event-bus listeners: on IncidentCreated -> embed, detect dupes, suggest category
  jobs/
    __init__.py
    scheduler.py         # APScheduler setup, start/stop hooks for FastAPI lifespan
    sla_monitor.py       # breach + warning detection
    escalation.py        # escalation chain
    auto_close.py        # RESOLVED -> CLOSED after N days without verification
  config.py              # pydantic-settings: thresholds, intervals, model names (shared with P2)
scripts/
  seed.py                # users, technicians, services, SLA policies, sample incidents
  gen_synthetic.py       # labelled incidents for categorizer + duplicate eval
  eval_duplicates.py     # precision/recall report
data/
  synthetic_incidents.jsonl
  duplicate_pairs.jsonl
models/                  # trained categorizer artifact (joblib), gitignored except a README
tests/
  conftest.py            # fixtures: db session, time freezing, factories
  jobs/
  intelligence/
Dockerfile
docker-compose.yml
.github/workflows/ci.yml
```

## 3. Contracts P4 depends on

These are what P4 needs from P1/P2. Confirm names with them; until delivered, code against these Protocols and use in-memory fakes in tests.

```python
# app/intelligence/contracts.py  (temporary; replace with real imports when P1/P2 land)
from datetime import datetime
from typing import Protocol, Iterable
from uuid import UUID

class IncidentView(Protocol):
    id: UUID
    title: str
    description: str
    category: str | None
    service_id: UUID
    priority: str            # "P1".."P4"
    status: str
    created_at: datetime     # tz-aware UTC
    acknowledged_at: datetime | None
    response_deadline: datetime
    resolution_deadline: datetime
    resolution_text: str | None
    assigned_technician_id: UUID | None
    escalation_level: int

class IncidentRepository(Protocol):
    def get(self, incident_id: UUID) -> IncidentView: ...
    def open_with_deadline_before(self, t: datetime) -> Iterable[IncidentView]: ...
    def open_since(self, t: datetime, service_id: UUID | None = None) -> Iterable[IncidentView]: ...
    def resolved_with_text(self) -> Iterable[IncidentView]: ...
    def resolved_before(self, t: datetime) -> Iterable[IncidentView]: ...

class IncidentService(Protocol):        # P1/P2 application service; enforces rules + audit
    def mark_sla_warning(self, incident_id: UUID, kind: str) -> bool: ...   # returns False if already warned
    def mark_sla_breach(self, incident_id: UUID, kind: str) -> bool: ...    # idempotent
    def escalate(self, incident_id: UUID, to_user_id: UUID, level: int) -> None: ...
    def auto_close(self, incident_id: UUID) -> None: ...
    def link_related(self, a: UUID, b: UUID, score: float) -> None: ...
    def set_suggested_category(self, incident_id: UUID, category: str, confidence: float) -> None: ...

class EscalationDirectory(Protocol):
    def next_in_chain(self, level: int) -> UUID | None: ...   # None = end of chain (skip inactive users inside)
```

Required from P2: a column/table recording warnings and breaches already sent (for idempotency), and the system actor user for audit entries.

## 4. Background jobs

Scheduler: APScheduler `AsyncIOScheduler`, started in FastAPI lifespan. Disabled in tests (`SCHEDULER_ENABLED=false`); tests call job functions directly.

Each job is a plain function taking `now: datetime` and its dependencies, so it is testable with frozen time:

```python
def run_sla_monitor(now: datetime, repo: IncidentRepository, svc: IncidentService, cfg: Settings) -> MonitorResult: ...
```

### 4.1 SLA monitor (`sla_monitor.py`)
- Interval: `SLA_MONITOR_INTERVAL_SECONDS` (must be well under the smallest response target; P1 response target is 5 min).
- Breach: incident open AND deadline < now AND not already flagged → `mark_sla_breach`. Check response (not acknowledged) and resolution separately.
- Warning: deadline − now <= `SLA_WARNING_FRACTION` × (deadline − created_at), not yet warned → `mark_sla_warning`.
- Paused incidents (AWAITING_INFO): deadlines are owned by P1's SLA clock; the monitor reads current deadlines only.
- Catch-up: uses `deadline < now`, never equality, so missed ticks (downtime) are processed on the next run.
- Idempotent: running twice on the same state produces no duplicate warnings, breaches, or audit rows.
- One failing incident must not abort the batch: catch per-incident, log, continue.

### 4.2 Escalation (`escalation.py`)
- Trigger: P1/P2 incident not acknowledged within `ESCALATION_AFTER_MINUTES[priority]` of creation or of last escalation.
- Chain: Technician → Team Lead → System Admin → IT Manager, via `EscalationDirectory.next_in_chain`.
- Re-read incident state inside the job before escalating (race with acknowledgment).
- End of chain: stop, flag once, no loop.
- Each escalation goes through `IncidentService.escalate` (audit + notification events fire from there).

### 4.3 Auto-close (`auto_close.py`)
- RESOLVED and not verified for `AUTO_CLOSE_DAYS` → `auto_close` with the system actor.

## 5. Intelligent features

Shared embedder:

```python
class Embedder(ABC):
    @abstractmethod
    def encode(self, texts: list[str]) -> np.ndarray: ...   # L2-normalised rows

class MiniLMEmbedder(Embedder):  # sentence-transformers "all-MiniLM-L6-v2", loaded once (lazy singleton)
```

Text fed to the embedder: `f"{title}. {description}"`, stripped and lowercased. Store embeddings (P2: `incident_embeddings` table, or pgvector if adopted) so they are computed once at creation.

### 5.1 Duplicate detection + correlation (`duplicates.py`)
- On IncidentCreated: compare with open incidents created within `DUP_WINDOW_HOURS`.
- Score = cosine similarity, plus `DUP_SAME_SERVICE_BONUS` if same service.
- Score >= `DUP_THRESHOLD` → `link_related` (suggestion only; never auto-merge or auto-close).
- Skip descriptions shorter than `DUP_MIN_CHARS` for similarity (fall back to same-service + same-category within window).
- Correlation: connected components over related links within the window → "incident cluster" per service, exposed for the dashboard.
- Thresholds start as config defaults and are tuned with `scripts/eval_duplicates.py` on `data/duplicate_pairs.jsonl`. Report precision, recall and the chosen threshold in the report. Do not report numbers that were not measured.

### 5.2 Auto-categorization (`categorizer.py`)
- Train: embeddings → `LogisticRegression(class_weight="balanced")` on `data/synthetic_incidents.jsonl`; stratified train/test split; save with joblib to `models/categorizer.joblib`.
- Predict on creation → `set_suggested_category(category, confidence)`.
- If max probability < `CAT_MIN_CONFIDENCE`: suggest nothing; the user/technician picks.
- The user or technician can always override; the override is audited (P1/P2).
- If the model file is missing: feature disables itself with a logged warning, the app still runs.
- Report: per-class precision/recall/F1 and confusion matrix from the held-out split. State that training data is synthetic and how it was generated.

### 5.3 Suggested resolution (`resolution.py`)
- Index: embeddings of RESOLVED/CLOSED incidents with non-empty resolution text.
- Query: top `RES_TOP_K` by cosine, filtered to similarity >= `RES_MIN_SIM`; prefer same category.
- Returned to the technician view via an API P2 exposes; read-only.
- Rebuild the index on startup and when an incident is resolved (event listener). Brute-force numpy is enough at this scale.

## 6. Config (`app/config.py`)

All thresholds live here, read from environment. Values below are starting points to be tuned, not results.

```python
class Settings(BaseSettings):
    DATABASE_URL: str
    SCHEDULER_ENABLED: bool = True
    SLA_MONITOR_INTERVAL_SECONDS: int = 30
    SLA_WARNING_FRACTION: float = 0.2
    ESCALATION_AFTER_MINUTES: dict[str, int] = {"P1": 5, "P2": 15}
    AUTO_CLOSE_DAYS: int = 3
    EMBEDDING_MODEL: str = "sentence-transformers/all-MiniLM-L6-v2"
    DUP_WINDOW_HOURS: int = 24
    DUP_THRESHOLD: float = 0.75
    DUP_SAME_SERVICE_BONUS: float = 0.05
    DUP_MIN_CHARS: int = 15
    CAT_MIN_CONFIDENCE: float = 0.5
    RES_TOP_K: int = 3
    RES_MIN_SIM: float = 0.6
```

## 7. Data scripts

- `gen_synthetic.py`: incidents per category (Hardware, Software, Network, Database, Cloud, Security, Authentication, Application, Storage), varied phrasing, plus labelled duplicate / non-duplicate pairs including hard negatives (same service, different problem). Fixed random seed. Document generation method in the report.
- `seed.py`: idempotent (safe to run twice). Creates admin, team lead, IT manager, technicians with differing skills and capacities, employees, services with criticality, SLA policies for every service × priority, and a spread of incidents across states, including some near or past SLA deadlines so the demo shows warnings and breaches.

## 8. DevOps

- `Dockerfile`: python:3.11-slim, non-root user, deps installed before copying source (layer caching). Download the embedding model at build time so the container runs offline.
- `docker-compose.yml`: `app`, `db` (postgres:16 with healthcheck), app waits for a healthy db, runs `alembic upgrade head` then uvicorn. Named volume for Postgres data.
- `.github/workflows/ci.yml`: on push/PR → install, ruff, mypy (domain + intelligence + jobs), pytest with a Postgres service container. Main branch protected: PR + green CI + one review.
- `.env.example` committed; `.env` gitignored. No secrets in the repo.

## 9. Tests (P4-owned)

Use `time-machine` (or freezegun) for all time-dependent tests. Fakes for repo/service in unit tests; real Postgres in integration tests.

| # | Test | Expected |
|---|---|---|
| 1 | Open P1 incident, now past response deadline, not acknowledged | One response breach recorded |
| 2 | Run monitor twice on same state | No duplicate breach/warning/audit rows |
| 3 | Scheduler "down" across a deadline, then runs | Breach caught on first run after restart |
| 4 | Incident within warning window | Exactly one warning |
| 5 | Acknowledged incident past response deadline | No response breach |
| 6 | Resolved incident past resolution deadline | No breach |
| 7 | One incident raises during monitor run | Others still processed; error logged |
| 8 | P1 unacknowledged beyond escalation time | Escalated to next level, audited |
| 9 | Incident acknowledged between query and escalation | Not escalated |
| 10 | Escalation chain exhausted | Flagged once, no further escalation |
| 11 | Inactive user in chain | Skipped to next active |
| 12 | Unverified RESOLVED past AUTO_CLOSE_DAYS | Auto-closed by system actor |
| 13 | Two paraphrased reports of same outage within window | Linked as related |
| 14 | Same text but outside window | Not linked |
| 15 | Very short description | Similarity skipped, fallback rule used |
| 16 | Unrelated incidents on same service | Not linked (hard negative) |
| 17 | Categorizer low confidence | No suggestion set |
| 18 | Categorizer model file missing | App starts, feature disabled, warning logged |
| 19 | Resolution suggester with empty history | Returns empty list, no error |
| 20 | Seed script run twice | No duplicate rows |

## 10. Schedule (from 9 Nov)

| Date | Done means |
|---|---|
| 9–10 Nov | Docker + compose + CI green (if not already done); contracts.py agreed with P1/P2; config.py |
| 11–12 Nov | SLA monitor + warnings + auto-close with tests 1–7, 12 |
| 13 Nov | Escalation with tests 8–11 |
| 14 Nov | Embedder + duplicate detection + gen_synthetic + eval script; tests 13–16 |
| 15–16 Nov | Categorizer trained + evaluated; suggested resolution; seed script; tests 17–20 |
| 17 Nov | Feature freeze. Integrated with real P1/P2 code, all CI green |
| 18–19 Nov | Deploy, testing chapter (collect 15+ formal cases from all members), intelligent-features section with measured metrics |

## 11. Definition of done (per feature)

- Runs in docker-compose against Postgres, not just locally.
- Unit + integration tests pass in CI.
- No hardcoded thresholds; all in config.
- Every state change goes through the P1/P2 service layer, so audit and notifications fire.
- Failure of the feature (model missing, embedder error) degrades gracefully; core incident flow unaffected.
- Report section written with measured numbers only.
