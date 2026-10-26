# D-029 lease fencing and recovery

Leases use SQLite's clock (milliseconds), not unrelated process clocks. Generation is monotonic integer;
owner nonce changes on takeover. Scope/fingerprint/created identity stay immutable. No reset to generation 1.
Generation overflow refuses recovery. Recovery policy is explicit, unused by the application, and not automatic.

`require_owner_cursor` requires an active transaction, current schema, state, generation, owner nonce,
frozen fingerprint and unexpired lease. The same check runs at finalization. BEGIN IMMEDIATE/EXCLUSIVE
prevents another connection from taking over in the middle of the commit transaction.

Executed: an independent OS process A claims then remains alive/stalled; a controlled lease fault expires A;
B takes generation 2; A resumes and is refused both before and after B's commit in separate test cases.
Exactly one synthetic history row remains. Additional real process exits cover after-reservation, before
COMMIT (after history/finalization writes) and after COMMIT. Restart sees rollback or original committed ID.

These are real SQLite/process fence tests, not actual five HTTP server workers running the financial engine.
Recovery MAY recompute while old physical calculation is still alive. No exactly-once engine claim is made.
An adequate lease must cover released execution timeout plus commit grace; worker admission/cancellation stay unchanged.
No new heartbeat daemon or polling service is introduced. Explicit recovery and timeout/failure policy need owner review.

## Status boundary

Implemented: isolated reservation, lookup/reconciliation, schema audit, fencing and cursor finalization helpers.
Proven: the executed persistence-only and released-baseline checks listed in `evidence/D029_LOCAL_TEST_RESULTS.json`.
Proposed policy: `D029_OWNER_DECISION_REGISTER.md`; no production rollout is enabled.
Deferred integration: canonical HTTP Run, financial commit hook, startup migration and real clients, after FIN-VAL #383 merges.
Owner decisions: retention, expiration/retry and compatibility semantics remain open.
Residual risk: the currently released Run route still permits duplicate commits; isolated tests do not prove end-to-end idempotency.
