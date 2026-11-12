# P4 placeholders: what's still pending

Every stand-in is named `PENDING_...`; `grep -rn PENDING_ app scripts tests` lists every use.
The Protocols live in `app/p4_contracts.py`. Delete a row once its item lands.

Updated 12 Nov after P1's answers (checked against P1's code in `domain/`).

## Settled by P1, now used directly

| Was | Now |
|---|---|
| `PENDING_P1_Status` and the status sets | `domain.enums.Status` / `Priority`; `DONE_STATUSES`, `UNACKNOWLEDGED_STATUSES` in contracts |
| `PENDING_P1_EventBus`, `PENDING_G7_*` events | `domain.events.EventBus`, `IncidentCreated`, `StatusChanged` (filtered on `new_status == RESOLVED`) |
| P4's own SLA evaluator (`sla_policy.py`) | **Deleted.** The job now drives `domain.sla_monitor.SLAMonitor`; the SLA rules are P1's |
| G3 paused-clock rule | Confirmed by P1; covered by `test_paused_incident_does_not_breach_resolution` and `test_resume_extends_deadline` |
| G9 breach vs warning | P1's tracker: a breach suppresses its warning; same as proposed |
| UUID ids | Strings (`"INC1001"`, `"SYSTEM"`) |

## Asked of P1 (they offered to add these before 14 Nov)

| Placeholder | Gap | Needed for |
|---|---|---|
| `PENDING_G13_created_at` | G13 | Escalation timer, duplicate window, seed. Today only `SLATracker._created_at` holds it, privately |
| `PENDING_G1_resolved_at` | G1 | Auto-close ("N days after resolution") |
| `PENDING_G15_escalation_level`, `PENDING_G15_escalate(to_user_id, level)` | G15 | Escalation: SYSTEM-only, allowed only before acknowledgment, emits an `IncidentEscalated` event (already listed in PROJECT.md 7.1) |
| `PENDING_G2_last_escalated_at` | G2 | The escalation timer restarts from the last escalation |
| `PENDING_G4_mark_escalation_exhausted()` → bool | G4 | Flag the end of the chain once, with an event |
| Roles TEAM_LEAD / SYSTEM_ADMIN / IT_MANAGER | G17 | The escalation chain. `Role` only has EMPLOYEE / TECHNICIAN / ADMIN |
| `PENDING_G16_close_unverified` (interim: `verify()` + `close()`) | G16 | Ask for a SYSTEM-only `auto_close()` RESOLVED → CLOSED (spec 8.1). With the interim, the audit trail claims a verification that never happened |
| `Incident.restore(...)` + SLA state snapshot | G20 | **Team-critical.** Without it P2 can't load incidents in their real state, and SLA warnings re-fire after every restart |
| `PENDING_G14_title` | G14 | Embedder input is "title. description". Works without it (description only) |
| `SLA_WARNING_FRACTION` passed to `SLATracker(warning_ratio=...)` | G19 | The factory hardcodes 0.8, so the config value has no effect |

## P2 (persistence)

| Placeholder | Gap | Ask |
|---|---|---|
| `PENDING_P2_UnitOfWork` | | Session wrapper exposing `incidents`, `intelligence`, `escalation_directory`, `embeddings`, `commit/rollback/close` |
| `IncidentRepository.open_incidents()` | | Returns P1 `Incident`s (needs G20). Replaces the spec's `open_with_deadline_before` |
| `PENDING_G5_get_for_update(id)` | G5 | Load with `SELECT ... FOR UPDATE` (escalation/auto-close vs a concurrent acknowledge/verify) |
| `PENDING_G6_EmbeddingStore` | G6 | `incident_embeddings` table: `save`, `get_many` |
| `open_since(t, exclude_id)` | G8 | Duplicate candidates |
| `PENDING_G10_related_links_since` | G10 | Links table + `GET /reports/clusters` |
| `PENDING_G11_open_unacknowledged(priorities)` | G11 | Escalation candidates |
| `PENDING_G12_EscalationTarget` from `next_in_chain` | G12 | Must return `(user_id, level)` |
| `IntelligenceSink.link_related` / `set_suggested_category` | | Stored + audited by P2 (they aren't lifecycle transitions) |
| `PENDING_G18_*` retry in `listeners.py` | G18 | P1's factory publishes `IncidentCreated` before P2 saves. Ask P2 to dispatch domain events **after commit**; then delete the retry |
| `PENDING_P2_apply_seed_plan` | | Replay the plan through P1's factory using a `FakeClock` set in the past (see `scripts/seed.py`) |
| `PENDING_P2_real_repository` / `_real_directory` | | Swap into `tests/contract/` |
| `app/main.py` | | Real app factory; lifespan snippet in `app/p4_wiring.py` |

## Routes P4 needs P2 to expose (all call into `app.state.p4`)

- `POST /admin/jobs/{name}/run` → `scheduler.run_now(name)`, for the demo
- `GET /incidents/{id}/suggestions` → `suggest_resolutions(id)` (technician role only, ownership check)
- `GET /reports/clusters` → `clusters()`
- `GET /health/p4` → `health()`
