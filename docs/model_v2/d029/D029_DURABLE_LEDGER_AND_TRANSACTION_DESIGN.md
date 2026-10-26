# D-029 durable ledger and transaction design

Table `model_run_intents`: unique `(actor_id, project_id, run_intent_id)`; states RESERVED/RUNNING/FAILED/COMMITTED with CHECK
constraints; immutable identity trigger; delete-refusal trigger; generation + `owner_nonce` fencing; lease expiry.

Startup: `db._init_schema` calls `run_intent_repository.ensure_schema`: fresh database => `install_schema` (single
`BEGIN IMMEDIATE` script, `IF NOT EXISTS`, concurrent starters serialize and the later one only verifies); any pre-existing
object => `verify_schema` (normalized SQL comparison) which raises `RUN_INTENT_SCHEMA_INVALID` instead of repairing. Additive
and repeatable; no financial table is touched. Trust-readiness inventory entry: `data.run_intents`.

Commit: `workspace_repository.v2_atomic_run_commit(..., run_intent=reservation)` inside the existing BEGIN EXCLUSIVE:
`require_owner_cursor` after the final CAS and before any write; `_append_history` returns the `history_id`;
`finalize_cursor(cur, reservation, history_id)` runs BEFORE COMMIT. Any exception rolls back Last Run promotion, the history row
and the intent together (tests inject faults at finalize and at history append and prove nothing persists).

## Status boundary

Release state: **RELEASE CLOSED**. See the release-state matrix in `D029_EXECUTIVE_REVIEW.md`.
Implemented and tested on PR #384 head: the canonical `POST /v2/workbook/run` intent lifecycle, the single-transaction
commit, startup schema, the React and Legacy clients and the governance successor. Not owner-approved, not activated:
the owner policies in `D029_OWNER_DECISION_REGISTER.md` remain candidates, `RELEASE_POLICY.enabled` is false, nothing is
deployed or merged. A request without `run_intent_id` keeps the released, non-idempotent behaviour.
