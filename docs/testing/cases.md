# Test cases

48 documented cases, 48 passing. By category: authorization 7, boundary 10, business-rule 18, exception 3, invalid-input 2, normal 8

| ID | Category | Description | Expected | Result | Test |
|---|---|---|---|---|---|
| TC-P2-01 | normal | Employee registers, then signs in | 201 with a token; /auth/me returns the new EMPLOYEE | passed | `tests/p2/test_security.py::test_register_then_login` |
| TC-P2-02 | invalid-input | Register with a 5-character password | 422 INVALID_INPUT, no account created | passed | `tests/p2/test_security.py::test_short_password_rejected` |
| TC-P2-03 | invalid-input | Register with an email already used | 409 EMAIL_TAKEN | passed | `tests/p2/test_security.py::test_duplicate_email` |
| TC-P2-04 | authorization | Sign in with the wrong password | 401 INVALID_LOGIN, same message as for an unknown email | passed | `tests/p2/test_security.py::test_wrong_password` |
| TC-P2-05 | authorization | Tampered, expired and missing tokens | 401 NOT_AUTHENTICATED in every case | passed | `tests/p2/test_security.py::test_bad_tokens` |
| TC-P2-06 | authorization | Deactivated user keeps an old token | Token stops working at once; signing in again gives 403 | passed | `tests/p2/test_security.py::test_deactivation_is_immediate` |
| TC-P2-07 | authorization | Employee calls admin endpoints | 403 UNAUTHORIZED_ACTION on every /api/admin route | passed | `tests/p2/test_security.py::test_employee_cannot_use_admin_routes` |
| TC-P2-08 | authorization | IDOR: employee B requests employee A's incident by id | 404 (existence not revealed); B's list doesn't include it | passed | `tests/p2/test_security.py::test_employee_cannot_see_others_incidents` |
| TC-P2-09 | authorization | A technician acts on an incident assigned to someone else | 404 for the read; the incident is unchanged | passed | `tests/p2/test_security.py::test_unassigned_technician_cannot_act` |
| TC-P2-10 | normal | Workflow 2 end to end: acknowledge, ask, reply, resolve, verify, close | Each step changes status; the 10 paused minutes move the deadline by 10 min | passed | `tests/p2/test_incidents.py::test_full_lifecycle_with_sla_pause` |
| TC-P2-11 | business-rule | Resolve without resolution text | 422; status stays IN_PROGRESS | passed | `tests/p2/test_incidents.py::test_resolution_text_required` |
| TC-P2-12 | exception | Employee verifies an incident that is still IN_PROGRESS | 409 INVALID_STATE_TRANSITION, and the refusal is in the audit trail | passed | `tests/p2/test_incidents.py::test_invalid_transition_is_refused_and_audited` |
| TC-P2-13 | authorization | Technician writes an internal note; the reporter opens the incident | Staff see the note; the employee's history leaves it out | passed | `tests/p2/test_incidents.py::test_internal_notes_hidden_from_employees` |
| TC-P2-14 | business-rule | Audit entries are changed or deleted through the ORM and the repository | PermissionError every time; the entry is unchanged | passed | `tests/p2/test_incidents.py::test_audit_log_is_append_only` |
| TC-P2-15 | business-rule | Server restarts mid-incident (incident paused in AWAITING_INFO) | Rebuilt from the audit trail in the same state; the SLA is still paused and the next step works | passed | `tests/p2/test_incidents.py::test_incident_survives_restart` |
| TC-P2-16 | business-rule | Domain events reach the application bus only after the commit | A listener can load the incident when IncidentCreated arrives (gap G18) | passed | `tests/p2/test_incidents.py::test_events_published_after_commit` |
| TC-P2-17 | normal | Search with six filters | Only matching incidents; employees only ever see their own | passed | `tests/p2/test_incidents.py::test_search_filters` |
| TC-P2-18 | business-rule | Admin switches the assignment strategy from skill-based to round-robin | The next incidents go to technicians in turn, without a restart | passed | `tests/p2/test_admin_and_jobs.py::test_strategy_switch_at_runtime` |
| TC-P2-19 | boundary | Every technician is at full capacity when an incident is reported | The incident stays NEW and unassigned; the audit says why | passed | `tests/p2/test_admin_and_jobs.py::test_no_capacity_leaves_incident_unassigned` |
| TC-P2-20 | boundary | Report with category 'Not sure' (none) | Assigned by load instead of failing (P1's skill strategy needs a skill) | passed | `tests/p2/test_admin_and_jobs.py::test_no_category_uses_load_based` |
| TC-P2-21 | business-rule | Admin shortens the P1 resolution target | New incidents use it; a response target >= resolution is refused | passed | `tests/p2/test_admin_and_jobs.py::test_sla_policy_update` |
| TC-P2-22 | normal | Seed script run twice | Second run creates no users, services or incidents | passed | `tests/p2/test_admin_and_jobs.py::test_seed_is_idempotent` |
| TC-P2-23 | business-rule | P4's SLA monitor runs twice on the real database, then the server restarts | Breach recorded once; not re-reported after the restart | passed | `tests/p2/test_admin_and_jobs.py::test_sla_monitor_reports_once_across_restart` |
| TC-P2-24 | business-rule | Unacknowledged P1 escalates; acknowledged one doesn't | Escalated to the level-1 user once, then the chain is flagged exhausted | passed | `tests/p2/test_admin_and_jobs.py::test_escalation_job` |
| TC-P2-25 | normal | Incident assigned while the server runs (notification worker on) | Technician and reporter get stored in-app notifications | passed | `tests/p2/test_admin_and_jobs.py::test_notifications_are_stored` |
| TC-P2-26 | normal | Alembic migrations on Postgres | Every table the models define exists after upgrade head | passed | `tests/p2/test_postgres.py::test_migrations_create_the_schema` |
| TC-P2-27 | business-rule | Two incidents reported at the same moment, one free technician slot | Row lock: exactly one is assigned, the other waits for an admin | passed | `tests/p2/test_postgres.py::test_concurrent_assignment_respects_capacity` |
| TC-P2-28 | business-rule | Unacknowledged P1 escalates, then runs out of people to escalate to | The team lead is notified of the escalation; admins of the exhausted chain | passed | `tests/p2/test_admin_and_jobs.py::test_escalation_notifies_target_and_admins` |
| TC-P4-01 | business-rule | Open P1, past response deadline, not acknowledged | Exactly one response breach event | passed | `tests/jobs/test_sla_monitor.py::test_response_breach_recorded` |
| TC-P4-02 | business-rule | SLA monitor runs twice on the same state | No duplicate warning/breach events | passed | `tests/jobs/test_sla_monitor.py::test_monitor_is_idempotent` |
| TC-P4-03 | boundary | Scheduler down across a deadline, then restarts | Breach caught on the first run after restart | passed | `tests/jobs/test_sla_monitor.py::test_missed_ticks_are_caught_up` |
| TC-P4-04 | boundary | Incident inside the warning window | Exactly one warning, no breach | passed | `tests/jobs/test_sla_monitor.py::test_single_warning` |
| TC-P4-05 | business-rule | Acknowledged incident past its response deadline | No response breach | passed | `tests/jobs/test_sla_monitor.py::test_acknowledged_no_response_breach` |
| TC-P4-06 | business-rule | Resolved incident past its resolution deadline | No breach | passed | `tests/jobs/test_sla_monitor.py::test_resolved_no_breach` |
| TC-P4-07 | exception | One incident raises during a monitor run | Others still processed; error logged | passed | `tests/jobs/test_sla_monitor.py::test_one_failure_does_not_abort_batch` |
| TC-P4-08 | business-rule | P1 unacknowledged beyond the escalation time | Escalated to the next level via the domain method (audited) | passed | `tests/jobs/test_escalation.py::test_escalates_to_next_level` |
| TC-P4-09 | boundary | Incident acknowledged between the query and the escalation | Not escalated | passed | `tests/jobs/test_escalation.py::test_acknowledged_during_run_not_escalated` |
| TC-P4-10 | boundary | Escalation chain exhausted | Flagged once; no further escalation | passed | `tests/jobs/test_escalation.py::test_chain_exhausted_flagged_once` |
| TC-P4-11 | business-rule | Inactive user in the escalation chain | Skipped to the next active user | passed | `tests/jobs/test_escalation.py::test_inactive_user_skipped` |
| TC-P4-12 | business-rule | Unverified RESOLVED incident past AUTO_CLOSE_DAYS | Auto-closed by the system actor | passed | `tests/jobs/test_auto_close.py::test_auto_close_after_days` |
| TC-P4-13 | normal | Two paraphrased reports of the same outage within the window | Linked as related | passed | `tests/intelligence/test_duplicates.py::test_paraphrases_linked` |
| TC-P4-14 | boundary | Same text but created outside the duplicate window | Not linked | passed | `tests/intelligence/test_duplicates.py::test_outside_window_not_linked` |
| TC-P4-15 | boundary | Very short description | Similarity skipped; same service + category fallback used | passed | `tests/intelligence/test_duplicates.py::test_short_description_uses_fallback` |
| TC-P4-16 | business-rule | Unrelated incidents on the same service (hard negative) | Not linked | passed | `tests/intelligence/test_duplicates.py::test_hard_negative_not_linked` |
| TC-P4-17 | boundary | Categorizer prediction below CAT_MIN_CONFIDENCE | No suggestion is set | passed | `tests/intelligence/test_categorizer.py::test_low_confidence_returns_none` |
| TC-P4-18 | exception | Categorizer model file missing | App starts; feature disabled; warning logged | passed | `tests/intelligence/test_categorizer.py::test_missing_model_disables_feature` |
| TC-P4-19 | boundary | Resolution suggester with an empty history | Returns an empty list, no error | passed | `tests/intelligence/test_resolution.py::test_empty_history` |
| TC-P4-20 | normal | Seed script run twice | No duplicate rows | passed | `tests/scripts/test_seed_and_data.py::test_seed_twice_no_duplicates` |
