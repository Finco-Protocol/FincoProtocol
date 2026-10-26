# D-029 security and CAS ordering

Required canonical order after #383 integration: authenticate -> resolve accessible immutable project ->
protected-reference refusal -> validate released session/project/purpose Run CSRF -> validate/scope key ->
look up original submitted binding -> replay ORIGINAL committed history or classify in-progress/failure.
Only a genuinely new/recoverable intent continues through current version/CAS/canonical materialization,
fingerprint/reservation and existing admission/engine/final CAS/integrity/atomic commit pipeline.

Never execute a protected reference because a key exists; never disclose a key/history through unauthorized access.
Run CSRF remains purpose `workbook-run-v1`, with released dual-field contradiction refusal unchanged.
The service is NOT an access-control boundary and must not be exposed directly as a public capability.

Committed replay must not restore Last Run, clear dirty, refresh certificates or return today's newer result.
`reconcile` queries the exact immutable history ID with actor/project scope. Missing historical evidence returns
HISTORY_UNAVAILABLE without reopening the successful key. Persisted malformed history remains a fail-closed read error.

All existing governed paths and historical pins remain byte-identical in this foundation; see source blob receipt.
Future integration must append an exact-path/blob successor after #383's successor reconciliation, retaining
historical ancestor pins and their semantic checks. Do not repin old authority or suppress failing tests.
Startup migration must additionally classify the new table in trust-readiness/data-retention inventory.

## Status boundary

Implemented: isolated reservation, lookup/reconciliation, schema audit, fencing and cursor finalization helpers.
Proven: the executed persistence-only and released-baseline checks listed in `evidence/D029_LOCAL_TEST_RESULTS.json`.
Proposed policy: `D029_OWNER_DECISION_REGISTER.md`; no production rollout is enabled.
Deferred integration: canonical HTTP Run, financial commit hook, startup migration and real clients, after FIN-VAL #383 merges.
Owner decisions: retention, expiration/retry and compatibility semantics remain open.
Residual risk: the currently released Run route still permits duplicate commits; isolated tests do not prove end-to-end idempotency.
