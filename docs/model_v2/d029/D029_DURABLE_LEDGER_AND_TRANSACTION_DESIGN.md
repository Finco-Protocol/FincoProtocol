# D-029 ledger and transaction design

`model_run_intents` stores unique scoped intent, reservation ID, submitted/frozen SHA256 bindings, version/hash,
state, generation, unguessable owner nonce, database-clock lease/timestamps, terminal code and unique history ID.
Additive `install_schema(connection)` is repeatable and refuses to run inside a financial transaction.
`verify_schema` fails closed on missing/mismatched unique constraints, CHECKs or immutable-state triggers.
No migration is connected to `db._init_schema` yet, so production behavior and schema initialization are unchanged.

States: RESERVED -> RUNNING -> COMMITTED, or RESERVED/RUNNING -> FAILED.
Explicit expired RESERVED/RUNNING recovery increments generation and changes owner nonce, returning RESERVED.
COMMITTED and FAILED records cannot be updated/deleted. There is no cleanup or key reuse operation.
Short BEGIN IMMEDIATE transactions own claims; no ledger transaction spans engine execution or waits.
WAL, connection timeout/busy handling and existing DB authority are reused. The SQLite unique constraint is cross-process authority.

Required hook: in `v2_atomic_run_commit`'s EXISTING BEGIN EXCLUSIVE transaction, verify the permit before
financial writes and preserve final CAS/integrity checks. Capture `history_id = _append_history(cur, payload)`;
call `finalize_cursor(cur, permit, history_id)` before existing COMMIT. Propagate every failure into existing
rollback. Finalize validates scoped history actor/project/version/composite identity and current unexpired generation.
The helper neither inserts financial/history rows nor commits. No post-commit second writer is permitted.

Writer inventory: canonical V2 router and protected-reference initialization use `v2_atomic_run_commit`.
Legacy runtime persistence also passes run_history_payload into `save_workspace_state`, whose two branches
append via the SAME `append_run_history_cursor`. That cursor function is the sole SQL INSERT implementation
found for model_run_history. Legacy/no-key callers and reference seeding retain released semantics.
Idempotency guarantee cannot be claimed until the canonical hook is wired and demonstrated with real Runs.

## Status boundary

Implemented: isolated reservation, lookup/reconciliation, schema audit, fencing and cursor finalization helpers.
Proven: the executed persistence-only and released-baseline checks listed in `evidence/D029_LOCAL_TEST_RESULTS.json`.
Proposed policy: `D029_OWNER_DECISION_REGISTER.md`; no production rollout is enabled.
Deferred integration: canonical HTTP Run, financial commit hook, startup migration and real clients, after FIN-VAL #383 merges.
Owner decisions: retention, expiration/retry and compatibility semantics remain open.
Residual risk: the currently released Run route still permits duplicate commits; isolated tests do not prove end-to-end idempotency.
