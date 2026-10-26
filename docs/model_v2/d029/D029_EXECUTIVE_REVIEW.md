# D-029 executive review

**Disposition: READY_FOR_INDEPENDENT_REVIEW — RELEASE CLOSED** (subject to the exact-head CI receipt in `D029_EXACT_HEAD_CI_REPORT.md`
and to the one open authorization request listed under *Open items*).

PR #384, branch `codex/d029-run-idempotency-v1`, forward-merged with main after #383 (`36edeeb5d9a1`). No rebase,
squash, cherry-pick, force push, self-merge, deploy, staging mutation or feature activation.

## What the PR now does

`POST /v2/workbook/run` accepts an optional `run_intent_id` (UUIDv4). Order, enforced by a structural validator
(`d029_run_order_violations`): authenticate -> resolve project -> ownership -> purpose-bound Run CSRF (contradictory dual
tokens fail) -> validate key -> reconcile an existing intent by its ORIGINAL submitted binding (actor = workspace owner,
project, workbook version, content hash) -> only for a new intent: version/CAS/scenario, materialize effective inputs,
freeze the fingerprint, durable reservation -> bounded executor -> final CAS + fence -> ONE transaction that checks the
fence, appends exactly one history row, calls `finalize_cursor` and COMMITs -> typed response read back from the exact
`history_id`. An intent id is never authorization; protected references are refused before any ledger access.

## Release-state matrix

| Capability | IMPLEMENTED | TESTED | OWNER-APPROVED | ACTIVATED |
|---|---|---|---|---|
| Durable intent ledger, fencing, immutable identity | yes | yes (34 ledger + HTTP tests) | no | no |
| Route integration (decide / reserve / typed outcomes) | yes | yes (real engine, HTTP) | no | no |
| Atomic commit: fence + one history row + finalize before COMMIT | yes | yes (fault injection, rollback proof) | no | no |
| Startup schema (additive, repeatable, fail-closed, concurrent-safe) + trust inventory | yes | yes | no | no |
| React client (UUIDv4, resume with original binding, typed outcomes, exact history reconcile) | yes | yes (real Chromium) | no | no |
| Legacy/HTMX client (one id across queue/lost response/OOB/reload) | yes | yes (real Chromium) | no | no |
| Missing key => optional, non-idempotent | yes | yes | NO (candidate) | no |
| Committed immutable / IN_PROGRESS typed / FAILED terminal / HISTORY_UNAVAILABLE / expired fails closed / no auto-retention | yes | yes | NO (candidates) | no |
| Required keys, retention/tombstone, automatic recovery of expired intents | NO | NO | NO | no |
| SEC-02 / FIN-VAL successor layer (two paths, original pins preserved) | yes | yes | authorization relayed in thread, not independently verified | no |
| Wrappers in the mandatory Browser Acceptance role | no (see Open items) | local only | - | no |

`RELEASE_POLICY.enabled` stays false. Nothing here activates or requires a key.

## Open items

1. `tests/test_model_workspace_consolidation_browser.py` is a pinned SEC-02 path and also the only file the mandatory
   Browser Acceptance role executes. The seven D-029 Chromium checks are written (`tests/model_d029_run_intent_browser_acceptance.py`)
   and pass locally, but wiring them into that role needs exact-path owner authorization for that file (plus a successor
   entry). Until then they are local evidence, not CI evidence. Prepared patch is not applied.
2. Owner decisions in the register remain PENDING.
3. Authorization for `app/v2/router.py`, the React bundle, `workflow/WorkflowBar.tsx`, `trust_readiness/registry.py` and
   `persistence/db.py` was relayed by the requester ("Imam odobrenje ownera"); it is recorded here as relayed, not verified.

## Status boundary

Release state: **RELEASE CLOSED**. See the release-state matrix in `D029_EXECUTIVE_REVIEW.md`.
Implemented and tested on PR #384 head: the canonical `POST /v2/workbook/run` intent lifecycle, the single-transaction
commit, startup schema, the React and Legacy clients and the governance successor. Not owner-approved, not activated:
the owner policies in `D029_OWNER_DECISION_REGISTER.md` remain candidates, `RELEASE_POLICY.enabled` is false, nothing is
deployed or merged. A request without `run_intent_id` keeps the released, non-idempotent behaviour.
