# I-ITSM — Intelligent IT Service Management & Incident Resolution System

CS F213 OOP course project, Semester I 2026–27. Team of 4. Primary language: Python.
Hard deadline: report PDF + recorded demo video (15–20 min) by **22 Nov 2026**. Team target: 20 Nov.
Video file name: `<GroupNo>_OOP_S1_2025-2026_Project`. Every member introduces themselves and explains a module.

This file is the shared background for the whole project. Read it before writing code. Role-specific detail lives in `P1_SPEC.md` … `P4_SPEC.md`.

---

## 1. Problem

Organizations run many IT services (payments, auth, databases, network, cloud storage…). When one fails, someone must report it and the IT team must classify, prioritize, assign, investigate, resolve and close it. Done manually at scale this causes slow response, wrong priorities, overloaded technicians, SLA violations, duplicate reports, missing history and invisible recurring problems.

The system manages the full incident lifecycle:

**Report → Classify → Prioritize → Assign → Investigate → Resolve → Verify → Close**

Reference scenario: an employee reports "Payment application unavailable, users cannot complete transactions". The system creates the incident, classifies it, identifies the service and its business impact, computes priority, applies the SLA, picks and assigns a technician, notifies people, tracks investigation, monitors SLA compliance, audits every action, closes it, and includes it in reports.

The course grades **object-oriented design** heavily. A working app with anemic models and logic in route handlers will lose marks. Every design choice must be justifiable.

## 2. Grading rubric (120 marks)

| Criterion | Marks | What it means for us |
|---|---|---|
| System design & architecture | 10 | Clear architecture, problem understanding |
| Functionality (MVP) | 60 | **Half the grade.** Every MVP item must work end to end |
| User experience | 10 | SLA, security, extensibility, intelligent features |
| Technical depth | 15 | Code quality, third-party API integration, scalability |
| Testing & validation | 5 | Unit/integration tests, edge cases, exceptions |
| Innovation | 10 | Beyond-MVP features (see §11) |
| Documentation & presentation | 10 | Report completeness, demo quality |

Priority rule: MVP complete and solid before any extra.

## 3. MVP checklist (all mandatory)

- [ ] Users: Employee, Technician, Administrator (register/login, role-based UI)
- [ ] Incidents: create, view, update, assign, resolve, close
- [ ] Priority from impact, urgency, business criticality
- [ ] ≥2 technician assignment strategies, switchable at runtime
- [ ] SLA calculation, deadline tracking, violation detection
- [ ] ≥2 notification mechanisms (real or simulated)
- [ ] Complete audit trail per incident
- [ ] ≥5 search/filter criteria + reports/dashboard
- [ ] ≥2 intelligent/automated features
- [ ] Persistent storage
- [ ] ≥2 design patterns (we implement more, see §7)
- [ ] ≥15 documented test cases

## 4. Users and capabilities

**Employee / Customer**: register/login, report incident, view own incidents, track status, add information, respond to info requests, view resolution, verify or reject resolution, give feedback (once, after resolution).

**Technician**: view assigned incidents, acknowledge, investigate, add notes, update status, request information from reporter, record resolution, resolve, view own workload, see suggested resolutions.

**Administrator / IT Manager**: manage users, technicians, IT services, SLA policies, categories, assignment strategy; monitor incidents and SLA violations; view reports and audit logs.

**Extra roles in the escalation chain**: Team Lead, System Admin, IT Manager.

Design note: a technician can also report incidents, so roles are composed (`User` has a set of `Role`). `Technician` subclasses `User` because it carries real extra state (skills, capacity, availability, experience) — a genuine is-a relationship.

## 5. Architecture

Layered monolith, containerized. Justification: the scope and team size don't warrant microservices; layering gives clean separation and testability. Scaling path (for the report): stateless API replicas behind a load balancer, Celery + Redis for jobs, read replicas, pgvector for embeddings.

```
Frontend (React + Vite, or Jinja2 + HTMX)
        │  REST / JSON, JWT; SSE for live notifications
API layer (FastAPI routers, Pydantic schemas, auth dependencies)
        │
Application services (use cases: ReportIncident, AssignIncident, ResolveIncident …)
        │  publish domain events
Domain layer (pure Python: entities, value objects, State, Strategies, exceptions)
        │                      ▲
Event bus (Observer) ──► AuditListener, NotificationListener, SLAListener, IntelligenceListener
        │
Repositories (interfaces in domain, SQLAlchemy implementations in infrastructure)
        │
PostgreSQL          Background jobs (APScheduler): SLA monitor, escalation, auto-close
```

Rules:
- The **domain layer imports nothing** from FastAPI or SQLAlchemy. It is unit-testable without a DB.
- Routes are thin: validate input → call application service → return schema.
- Every state change goes through an application service, so audit and notification events always fire.
- SQLAlchemy models ≠ domain classes. Repositories map between them.

## 6. Technology stack

| Concern | Choice | Reason |
|---|---|---|
| Language | Python 3.11+ | Team proficiency, ML ecosystem for intelligent features. OOP via `abc.ABC`/`Protocol`, `@property`, frozen dataclasses; mypy strict for type contracts |
| Backend | FastAPI | Async, Pydantic validation, auto OpenAPI docs for the demo |
| ORM / migrations | SQLAlchemy 2.0, Alembic | Mature, typed, supports Repository pattern cleanly |
| Database | PostgreSQL 16 (SQLite only in unit tests) | Relational data, row locking (`SELECT … FOR UPDATE`) for assignment races, JSON columns where needed |
| Auth | Argon2 hashing, JWT (PyJWT), role dependencies; optional Google OAuth | Standard, explainable |
| Jobs | APScheduler (in-process) | Enough for scope; Celery named as scaling path |
| Real-time | Server-Sent Events | One-directional server→client is all we need |
| Email | SMTP (Gmail / Mailtrap) behind Adapter | Real third-party integration for Technical Depth marks |
| Intelligence | sentence-transformers (all-MiniLM-L6-v2), scikit-learn | Local, free, small |
| Frontend | React + Vite + component library (or Jinja2 + HTMX) | Role-differentiated UIs |
| Testing | pytest, httpx TestClient, time-machine/freezegun | Time must be frozen for SLA tests |
| DevOps | Docker, docker-compose, GitHub Actions; optional Render/Railway | Reproducible runs, CI |
| Quality | ruff, mypy | Enforced in CI |

## 7. Object-oriented design

### 7.1 Core domain classes (P1 owns; names are the contract)

| Class | Kind | Responsibility |
|---|---|---|
| `User` | Entity | Identity, credentials hash, roles, active flag |
| `Technician(User)` | Entity | Skills (categories), capacity, availability, experience, service history |
| `ITService` | Entity | Name, business criticality, active flag |
| `Category` | Entity/config | Incident category; admin-configurable, new ones added without code changes |
| `Incident` | Aggregate root | All incident data; owns its `IncidentState`, notes, links; enforces transitions |
| `IncidentState` (+ subclasses) | State pattern | Allowed transitions and actions per state, per role |
| `Priority` | Value object (frozen) | P1–P4 + score; comparable |
| `Impact`, `Urgency` | Enums | Inputs to priority |
| `SLAPolicy` | Value object | Response and resolution targets per service × priority |
| `SLAClock` | Domain service | Deadlines, pause/resume, breach checks |
| `PriorityStrategy` | Interface | `calculate(incident, service) -> Priority` |
| `AssignmentStrategy` | Interface | `select(incident, technicians) -> Technician` |
| `NotificationChannel` | Interface | `send(recipient, message)` |
| `AuditRecord` | Value object | Immutable log entry |
| `DomainEvent` (+ subclasses) | Value objects | `IncidentCreated`, `IncidentAssigned`, `StatusChanged`, `PriorityChanged`, `SLAWarning`, `SLABreached`, `IncidentEscalated`, `IncidentResolved`, `IncidentClosed` |
| `EventBus` | Observer subject | `subscribe(event_type, listener)`, `publish(event)` |
| Repositories | Interfaces | `IncidentRepository`, `UserRepository`, `ServiceRepository`, `SLAPolicyRepository`, `AuditRepository` |

### 7.2 OOP concepts → where they appear (put this table in the report)

| Concept | Where |
|---|---|
| Encapsulation | `Incident` state only changes via methods (`assign()`, `acknowledge()`, `resolve()`); private attributes + read-only properties |
| Abstraction | Application services hide multi-step workflows; repositories hide persistence |
| Inheritance | `Technician(User)`; `IncidentState` subclasses; exception hierarchy |
| Polymorphism | Interchangeable `AssignmentStrategy`, `PriorityStrategy`, `NotificationChannel`, `IncidentState` |
| Interfaces | ABCs / Protocols for strategies, channels, repositories, embedder |
| Composition | `Incident` owns notes, state, SLA deadlines; `Technician` owns skills |
| Association / aggregation | Incident ↔ reporter, assigned technician, service; related-incident links |
| Exception handling | Custom hierarchy (§9), mapped to HTTP codes in one handler |
| Collections | Dict for transition tables, sets for skills/roles, deque for round-robin, heap for load-based selection |

### 7.3 Design patterns

| Pattern | Use |
|---|---|
| **Strategy** | Assignment (skill-based, load-based, round-robin); priority (matrix, weighted/multiplicative) |
| **State** | Incident lifecycle (states carry behaviour: SLA pause, per-role allowed actions) |
| **Observer** | Domain event bus → audit, notifications, SLA, intelligence listeners |
| **Repository** | Persistence |
| **Adapter** | Email/SMTP provider wrapped as a `NotificationChannel` |
| **Factory** | `NotificationChannelFactory`, `IncidentFactory` (defaults, validation) |

## 8. Business rules

### 8.1 Lifecycle

```
NEW → CLASSIFIED → ASSIGNED → ACKNOWLEDGED → IN_PROGRESS → RESOLVED → VERIFIED → CLOSED
                                               ↕
                                         AWAITING_INFO   (SLA clock paused)
RESOLVED → REOPENED → IN_PROGRESS               (reporter rejects resolution)
RESOLVED → CLOSED                               (auto-close after N days unverified, system actor)
ASSIGNED / ACKNOWLEDGED → ASSIGNED              (reassignment)
```

| Transition | Allowed actor |
|---|---|
| NEW → CLASSIFIED | System (auto) or Technician/Admin |
| CLASSIFIED → ASSIGNED | System (strategy) or Admin |
| ASSIGNED → ACKNOWLEDGED | Assigned technician |
| ACKNOWLEDGED → IN_PROGRESS | Assigned technician |
| IN_PROGRESS ↔ AWAITING_INFO | Assigned technician (→), reporter reply or technician (←) |
| IN_PROGRESS → RESOLVED | Assigned technician (resolution text required) |
| RESOLVED → VERIFIED | Reporter |
| RESOLVED → REOPENED | Reporter |
| VERIFIED → CLOSED | System or Admin |

Anything else raises `InvalidStateTransitionError` and the attempt is audited. NEW → CLOSED is never allowed.

### 8.2 Priority

Base priority from an ITIL-style Impact × Urgency matrix, then modifiers:

| Impact \ Urgency | High | Medium | Low |
|---|---|---|---|
| High | P1 | P2 | P3 |
| Medium | P2 | P3 | P4 |
| Low | P3 | P4 | P4 |

Modifiers: service business criticality HIGH → raise one level; affected users above a configured threshold → raise one level; never above P1. Reporter-supplied urgency is an input, not authority — technicians/admins can override, and overrides are audited.

Why not pure `Impact × Urgency × Criticality`: on 1–3 scales it yields only 10 distinct scores (1, 2, 3, 4, 6, 8, 9, 12, 18, 27), and one low factor drags a genuine outage down. Implemented anyway as an alternative `PriorityStrategy` to demonstrate polymorphism. Document this comparison in the report.

### 8.3 SLA

Default targets (admin-configurable per service × priority):

| Priority | Response | Resolution |
|---|---|---|
| P1 | 5 min | 30 min |
| P2 | 15 min | 2 h |
| P3 | 1 h | 8 h |
| P4 | 4 h | 24 h |

- Response time = creation → first acknowledgment.
- Resolution time = creation → RESOLVED, minus time in AWAITING_INFO.
- Priority change mid-flight: deadlines recomputed from the **original creation time**.
- Clock runs 24×7 (business-hours calendars = future work).
- Missing policy for a service × priority → fall back to default policy, log it.
- Warning before deadline; breach recorded once; both are audited and notified.
- All timestamps stored as timezone-aware UTC; UI displays IST.

### 8.4 Assignment

- Strategies: skill-based (category in skills, then least loaded), load-based (fewest active weighted by priority), round-robin (persisted pointer). Active strategy set by admin at runtime.
- Only active, available technicians under capacity are candidates.
- No candidate → incident stays in unassigned queue, admin alerted. Never fail silently.
- Deterministic tiebreak (experience, then ID).
- Assignment locks the incident row to prevent double assignment.
- Deactivated technician → their open incidents are reassigned.

### 8.5 Escalation

Unacknowledged P1/P2 beyond configured time: Technician → Team Lead → System Admin → IT Manager. Skip inactive users. End of chain → flag once, stop.

### 8.6 Data integrity

- Audit records are append-only. No update/delete endpoint.
- Users, technicians, services are soft-deleted (incidents and audit keep references).
- System actions (auto-close, escalation, SLA breach) use a dedicated system actor.
- Feedback: reporter only, once, after RESOLVED.

## 9. Exceptions

```
ITSMError
├── AuthenticationError            → 401   invalid login, bad/expired token
├── AuthorizationError             → 403   wrong role, not owner of incident
├── ValidationError                → 422   invalid input
├── NotFoundError                  → 404
│   ├── IncidentNotFoundError
│   ├── ServiceNotFoundError
│   └── UserNotFoundError
├── InvalidStateTransitionError    → 409
├── DuplicateIncidentError         → 409   (only for exact resubmission; similar ones are linked, not rejected)
├── AssignmentError                → 409
│   ├── TechnicianUnavailableError
│   └── TechnicianWorkloadExceededError
├── SLAConfigurationError          → logged, default applied
└── ExternalServiceError           → 502/logged  (email, DB connectivity)
```

One FastAPI exception handler maps these to HTTP responses. Domain code raises; it never returns error codes.

## 10. Security

Authentication (JWT, short expiry), Argon2 password hashing, role-based authorization as FastAPI dependencies, **ownership checks on every incident read/write** (employees only see their own — this is the IDOR bug evaluators look for), Pydantic input validation, allowlisted sort/filter fields, parameterized queries via ORM, CORS restricted to frontend origin, secrets in `.env` only. Document anything not implemented as future work.

## 11. Intelligent and innovation features

| Feature | Approach | Counts as |
|---|---|---|
| SLA risk detection + automatic escalation | Rule-based scheduler jobs | Intelligent #1 |
| Duplicate detection + correlation | MiniLM embeddings, cosine similarity in time window, same-service bonus; suggest links, never auto-merge; clusters per service | Intelligent #2, Innovation |
| Auto-categorization | Embeddings + logistic regression on synthetic labelled data; confidence threshold; user can override | Intelligent #3 |
| Suggested resolution | kNN over resolved incidents' embeddings | Innovation (drop first if late) |
| Real-time notifications (SSE), Google OAuth, cloud deployment, dashboard analytics | — | Innovation / Technical depth |

Report measured metrics only (precision/recall for duplicates, F1 for categorization). State that training data is synthetic.

## 12. Search, filters, reports

Filters (≥5): incident ID, date range, status, priority, category, service, technician, SLA status.
Reports: overview (total, open, critical, resolved, SLA violations), technician workload, incidents per service, SLA compliance over time, duplicate clusters.

## 13. Repository layout

```
app/
  domain/            # P1 — entities, value objects, states, strategies, events, exceptions, repo interfaces
  services/          # P1/P2 — application services (use cases)
  api/               # P2 — routers, schemas, deps (auth, roles, ownership)
  infrastructure/
    db/              # P2 — SQLAlchemy models, session, repository implementations
    notifications/   # P3 — channels (in-app, email adapter), factory, SSE
  intelligence/      # P4
  jobs/              # P4 — scheduler, SLA monitor, escalation, auto-close
  config.py          # pydantic-settings (shared)
  main.py            # app factory, lifespan (scheduler start/stop), exception handler
frontend/            # P3
alembic/             # P2
scripts/             # P4 — seed, synthetic data, evaluation
tests/
  unit/              # domain, strategies, states (no DB)
  integration/       # API + Postgres
docs/                # diagrams, report sources
Dockerfile
docker-compose.yml
.github/workflows/ci.yml
.env.example
```

## 14. Team split

| Member | Owns | Report sections | Demo |
|---|---|---|---|
| **P1 — Domain & OOP core** | Domain classes, State lifecycle, priority & assignment strategies, SLA clock, event bus, exceptions | Class diagram, state diagram, OOP concepts table, patterns, priority/SLA rationale | Workflow 1 |
| **P2 — Backend, persistence, security** | FastAPI routes, auth/RBAC/ownership, SQLAlchemy models, repositories, migrations, search & report queries, audit persistence | ER diagram, schema, sample data, security, technology selection report | Admin features |
| **P3 — Frontend & notifications** | Three role UIs, dashboard, SSE in-app notifications, email adapter, notification factory | Use case diagram, problem analysis, requirements, UI, final report assembly | Workflow 2; edits video |
| **P4 — Intelligence, jobs, DevOps, test lead** | Scheduler jobs, intelligent features, Docker, CI, deploy, seed/synthetic data | Architecture diagram, intelligent features + metrics, testing chapter | Workflow 3 |

Every member must understand the whole system. Team dry run on 18 Nov: each person explains a workflow they did not build.

## 15. Demo workflows (video)

1. Employee reports payment outage → auto-classified → priority computed → technician assigned → notifications sent.
2. Technician acknowledges → requests info (SLA paused) → resolves → reporter notified → verifies → closed. SLA monitor visible.
3. Several similar reports → flagged as related/clustered → unacknowledged P1 escalates through the chain.

## 16. Report deliverables (one PDF)

1. Problem analysis (problem, stakeholders, challenges, solution, assumptions)
2. Requirements (functional, non-functional, roles, business rules)
3. Architecture diagram
4. UML: use case diagram, class diagram (classes, attributes, methods, interfaces, inheritance, associations, composition/aggregation); state diagram recommended
5. Technology stack + selection report (answer all 9 questions in the brief: language, frontend, backend, DB, architecture choices, alternatives, pros/cons, OOP support, scaling)
6. Source code link (GitHub)
7. Database design (ER, schema, relationships, sample data)
8. Testing (≥15 documented cases: normal, boundary, invalid input, exceptions, authorization, business rules)
9. Demo video link

## 17. Conventions

- Branches: `feature/<owner>-<short-name>`; PR into `main`; green CI + one review required. P2 reviews P1's PRs.
- ruff + mypy pass before PR. Type hints everywhere.
- Timestamps: `datetime.now(timezone.utc)` only; never naive datetimes. Inject `now` into time-dependent functions for testing.
- No magic numbers: thresholds, intervals, SLA defaults in `config.py` or DB config tables.
- Never write to DB from routes directly; go through services → repositories.
- Never put secrets in code or commits.
- Commit seed data scripts, not database dumps.

## 18. Schedule

| Date | Milestone |
|---|---|
| By 10 Nov | Repo, Docker, CI green; domain interfaces + API contract (OpenAPI with mocks) agreed |
| 11–14 Nov | Core MVP end to end via API: auth, incidents, lifecycle, priority, SLA, assignment, audit, persistence |
| 13–16 Nov | SLA monitor, escalation, notifications, search/reports, role UIs, intelligent features |
| **17 Nov** | **Feature freeze** |
| 17–19 Nov | Test sweep (edge cases in §8–§10), bug fixes, deploy, seed demo data; dry run 18 Nov |
| 20–21 Nov | Report PDF, record and upload video |
| 22 Nov | Hard deadline — buffer only |
