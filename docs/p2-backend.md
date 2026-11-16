# P2 backend: how it fits together

## Run it

```bash
pip install -e ".[dev]"
python -m scripts.seed          # demo data; password from SEED_PASSWORD (dev default: demo1234)
uvicorn app.main:app --port 8000
```

Then run the frontend against it: `VITE_USE_MOCK=false npm --prefix frontend run dev`.
The API docs are at `/api/docs`. Docker (`make up`) runs the Alembic migrations first.

Production needs `APP_ENV=production`, a `JWT_SECRET` of at least 32 characters and a
`SEED_PASSWORD`. The app refuses to start without the secret.

## Layers

| Layer | Where | Job |
|---|---|---|
| Routes | `app/api/routes.py` | Validate the body, call one service method, return JSON shaped like `frontend/src/api/types.ts` |
| Services | `app/services/` | One transaction per use case. Call P1's domain methods; add the detail P1's events don't carry |
| Unit of work | `app/persistence/uow.py` | One transaction: repositories, audit journal, events published **after** commit |
| Repositories | `app/persistence/repositories.py` | Map rows to and from P1's classes |
| Tables | `app/db/models.py`, `alembic/` | SQLAlchemy 2 models, migrations |
| Domain | `domain/` (P1) | Every business rule |

## Decisions worth explaining in the report

- **Incidents are rebuilt by replaying their audit trail** through P1's own methods
  (`app/persistence/replay.py`). P1 has no `Incident.restore()` yet. Replay keeps one
  copy of the lifecycle rules, and SLA pauses and "warn once" flags come out exactly as
  P1 computes them. When P1 adds `restore()`, only `replay.py` changes.
- **The audit trail is append-only.** The ORM refuses updates and deletes, and the
  repository has no such methods. Refused actions are audited even though their
  transaction rolls back.
- **Events go out after the commit** (`TransactionalEventBus`), so notifications and P4's
  listeners can always load what an event is about (gap G18).
- **Row locks** (`SELECT … FOR UPDATE`) on technician profiles and the incident counter.
  Two reports at the same moment can't both take a technician's last slot, and can't
  both get the same number (`tests/p2/test_postgres.py`).
- **Ownership check on every incident read and write.** Someone who can't see an
  incident gets 404, not 403, so its existence isn't revealed. Employees never see
  internal notes.
- **Argon2id passwords, HS256 JWTs.** The user is re-read on every request, so
  deactivation takes effect at once. Login takes the same time for unknown emails and
  wrong passwords.

## Interim pieces, until P1 delivers

| Gap | Interim | Where |
|---|---|---|
| G20 `restore()` | Replay of the audit trail | `replay.py` |
| G13/G1/G2/G14/G15 timestamps and escalation | `PersistedIncident` proxy adds them | `replay.py` |
| G17 escalation roles | `users.escalation_level` (1 team lead, 2 system admin, 3 IT manager) | `EscalationDirectory` |
| Text on `request_info` / `provide_info` | Stored in the audit step and `incidents.info_request` | `services/incidents.py` |
| Reporter adds information | Audit step only | `IncidentService.add_information` |
| "Not sure" category | Load-based assignment straight away | `services/assignment.py` |

## Tests

`pytest tests/p2` runs on SQLite. `P2_TEST_DATABASE_URL=postgresql+psycopg://… pytest tests/p2`
runs the same tests on Postgres. `pytest -m integration` with a Postgres `DATABASE_URL`
also runs the migration and locking tests. The cases tagged `TC-P2-01` to `TC-P2-27`
feed the report's test catalogue.

## Not done (future work)

- Reassigning a deactivated technician's open incidents (P1 only allows assignment from
  NEW or CLASSIFIED).
- SLA targets per service × priority (they are per priority now).
- Running more than one API process (SSE and the scheduler are in-memory).
