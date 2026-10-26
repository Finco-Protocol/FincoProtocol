# D-029 owner decision register

Engineering authorization does not decide retention/API or financial policy. The feature remains release-closed.
Every row below is a CANDIDATE implemented so the behaviour can be reviewed; none is approved and none is activated.

| Decision | Candidate (implemented behaviour) | Where / test | Owner disposition |
|---|---|---|---|
| Optional vs required keys | Missing or blank key => released, explicitly non-idempotent path | `test_invalid_key_and_missing_key` | PENDING |
| Committed key | Immutable; replay returns the ORIGINAL history row, never recalculates, never restores Last Run | `test_replay_after_edit_newer_run_never_overwrites_last_run` | PENDING |
| In-progress | Immediate typed `IN_PROGRESS` (HTTP 409); no waiting, no daemon | `test_in_progress_second_request_does_not_start_a_second_engine` | PENDING (transport UX) |
| Failed attempt | Terminal for that key (`FAILED`); deliberate retry uses a NEW key | `test_failed_engine_attempt_is_terminal...`, commit-fault tests | PENDING |
| Missing history for a committed key | Typed `HISTORY_UNAVAILABLE`; key never reopens | `test_missing_or_malformed_history...`, `test_foreign_history_id...` | PENDING |
| Expired active attempt | Typed `EXPIRED`, fails closed; takeover is explicit `recover()` only, NOT routed | `test_expired_active_intent_fails_closed...`, `test_stale_owner_is_fenced...` | PENDING (lease values, recovery policy) |
| Different keys overlapping | Released admission/CAS semantics unchanged; each committed intent binds its own history row | `test_different_keys_keep_released_admission...` | PENDING |
| Retention / cleanup | No automatic deletion; a trigger refuses DELETE; inventoried in trust-readiness (`data.run_intents`) | schema + registry | PENDING; no retention period approved |
| Ledger actor for shared projects | Ledger `actor_id` is the workspace OWNER (history rows and `finalize_cursor` are keyed to the owner), so collaborators share the owner's key space | `run_intent_service.decide` call in the route | PENDING (trade-off) |
| Corrupted ledger schema | Startup and every ledger call raise `RUN_INTENT_SCHEMA_INVALID` (fail closed). Blast radius: the application refuses connections until repaired | `test_schema_corruption_fails_closed_before_any_run` | PENDING (availability vs strictness) |
| Lease length | `LEASE_MS` = (900 + 120) s: executor cap plus margin | `run_intent_service.LEASE_MS` | PENDING |
| Protected-reference order | The released handler validates CSRF before the protected-reference gate (RC-SEC pinned); the ledger is never read for a protected project | `test_protected_reference_is_refused_even_with_a_key` | PENDING (confirm order) |

No numerical result or protected-reference permission depends on these candidates. Missing decisions are not consent.

## Status boundary

Release state: **RELEASE CLOSED**. See the release-state matrix in `D029_EXECUTIVE_REVIEW.md`.
Implemented and tested on PR #384 head: the canonical `POST /v2/workbook/run` intent lifecycle, the single-transaction
commit, startup schema, the React and Legacy clients and the governance successor. Not owner-approved, not activated:
the owner policies in `D029_OWNER_DECISION_REGISTER.md` remain candidates, `RELEASE_POLICY.enabled` is false, nothing is
deployed or merged. A request without `run_intent_id` keeps the released, non-idempotent behaviour.
