# D-029 executive review

**PARTIAL IMPLEMENTATION — INTEGRATION / OWNER DECISION REQUIRED**

Base: `8944aca351ef89c81a8a9bf715ab352629c35624`, tree `3448aeb245ff118fde0907541dfe40ace42a86d8`.
Merged dependencies #381/#382 are recorded in `evidence/D029_PREFLIGHT.json`.
The supplied Stage A ZIP was independently checked and current-main duplicate commits reproduced.

Four additive source/test/diagnostic files implement a durable, SQLite-unique intent, immutable submitted binding,
frozen effective fingerprint, explicit takeover with generation/owner fencing, original-history reconciliation,
and an atomic-finalization helper. No application endpoint imports them. No financial/history writer was added.
The migration is explicit and unused by normal application startup. `RELEASE_POLICY.enabled` is false.

Do not merge this foundation as the complete D-029 fix. FIN-VAL B2/C1 #383 owns shared Run-adjacent source.
After its independent merge, forward-merge main normally into the SAME D-029 branch/PR, finish the hooks,
append narrow governance succession, then run all end-to-end/financial/CI requirements. No rebase,
cherry-pick, force push, deployment, activation or self-approval is authorized.

Evidence tables distinguish actual canonical baseline Runs from synthetic persistence fault injection.
The final published commit/tree and exact-head CI receipt must be read from the review package/live Draft PR.

## Status boundary

Implemented: isolated reservation, lookup/reconciliation, schema audit, fencing and cursor finalization helpers.
Proven: the executed persistence-only and released-baseline checks listed in `evidence/D029_LOCAL_TEST_RESULTS.json`.
Proposed policy: `D029_OWNER_DECISION_REGISTER.md`; no production rollout is enabled.
Deferred integration: canonical HTTP Run, financial commit hook, startup migration and real clients, after FIN-VAL #383 merges.
Owner decisions: retention, expiration/retry and compatibility semantics remain open.
Residual risk: the currently released Run route still permits duplicate commits; isolated tests do not prove end-to-end idempotency.
