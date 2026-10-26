# D-029 concurrency and fault injection results

Executed isolated ledger suite: **34 passed**. Evidence uses disposable real SQLite WAL and actual history
payload validation/cursor append with clearly synthetic empty financial outputs; no fake financial result is served.

| Boundary | Executed evidence | Scope |
|---|---|---|
| Sequential repeat / mismatch | same reservation; typed binding/fingerprint refusal | Ledger |
| Five spawned processes, independent connections | one claim, one history ID/row | Ledger + real history writer |
| Alive expired A, takeover B | stale A refused before AND after B commit | Two OS processes, real SQL fence |
| Reservation/precommit/postcommit process exit | durable reservation / rolled back writes / original committed ID | Real abrupt process exits |
| Failed finalization / injected precommit crash | no committed phantom history | Transaction fault injection |
| Missing unique constraint or fence trigger | explicit schema refusal, zero new claim | Negative controls |
| Incompatible migration schema | new DDL objects rolled back on refusal | Migration transaction |
| Second start on RUNNING reservation | no additional execution permit | Ledger |
| Wrong history identity / no transaction | finalization refused | Ledger |
| New key / same inputs | independent deliberate intent | Ledger |
| Older replay after newer key | original history ID, no extra row | Reconciliation helper |
| Missing history | HISTORY_UNAVAILABLE, committed key remains closed | Fault-injected read loss |
| Busy writer | no reservation/false success; later legitimate acquisition | SQLite contention |
| Terminal failure classes | no history pointer, same key closed, new key available | Ledger |

Current-main canonical baseline additionally covers real Save-during-Run CAS, stale CAS, admission 429,
postcommit response loss, wrong/missing/session-invalid Run CSRF, protected reference refusal and injected
engine timeout/failure. These do not yet prove their combination with idempotency-enabled HTTP.

Still required after #383: five independent ASGI application workers with same-key real financial Run,
all live disconnect boundaries, financial refusal/final CAS combined with ledger, no-key compatibility,
real React/Legacy exact-ID replay, original Last Run/certificate preservation, and full browser-role acceptance.
No unexecuted case is marked PASS. Commands and counts are in the local test and exact-head reports.

## Status boundary

Implemented: isolated reservation, lookup/reconciliation, schema audit, fencing and cursor finalization helpers.
Proven: the executed persistence-only and released-baseline checks listed in `evidence/D029_LOCAL_TEST_RESULTS.json`.
Proposed policy: `D029_OWNER_DECISION_REGISTER.md`; no production rollout is enabled.
Deferred integration: canonical HTTP Run, financial commit hook, startup migration and real clients, after FIN-VAL #383 merges.
Owner decisions: retention, expiration/retry and compatibility semantics remain open.
Residual risk: the currently released Run route still permits duplicate commits; isolated tests do not prove end-to-end idempotency.
