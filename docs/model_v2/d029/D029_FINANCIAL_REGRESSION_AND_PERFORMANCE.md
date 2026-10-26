# D-029 financial regression and performance

All existing financial sources, canonical router/commit/schema, security validators and deployed clients are
byte-identical to merged main; source blob receipt verifies selected integration/governance files independently.
The real canonical baseline exercises released financial calculation. New persistence tests use synthetic
outputs and do NOT establish integrated financial bit identity, complete certificates or whole-Run latency.
Existing FIN-VAL B1, Golden Flow and Run Certificate regression command/results are recorded in local evidence.

Windows local WAL, 40 synthetic persistence iterations; includes normal get_connection/schema-guard costs.

| Operation | Median ms | p95 ms | Max ms |
|---|---:|---:|---:|
| reservation_ms | 9.773 | 11.195 | 16.026 |
| lookup_ms | 4.191 | 5.628 | 6.184 |
| start_ms | 10.504 | 12.430 | 14.080 |
| history_and_finalize_commit_ms | 10.128 | 12.613 | 16.839 |
| reconcile_ms | 7.103 | 8.336 | 9.052 |

`history_and_finalize_commit_ms` includes synthetic canonical history append and commit, not a financial Run.
`reconcile_ms` is exact-history helper lookup, not network replay latency. Five-process contention is proven
functionally by the spawned-process test; production five-worker HTTP throughput remains unmeasured.
Normal real Run latency before/after and Solar/Wind/DC/EV bit-identical output/certificate comparison are
DEFERRED until actual integration. No formula/native-kernel/solver/tolerance changes were made.

## Status boundary

Implemented: isolated reservation, lookup/reconciliation, schema audit, fencing and cursor finalization helpers.
Proven: the executed persistence-only and released-baseline checks listed in `evidence/D029_LOCAL_TEST_RESULTS.json`.
Proposed policy: `D029_OWNER_DECISION_REGISTER.md`; no production rollout is enabled.
Deferred integration: canonical HTTP Run, financial commit hook, startup migration and real clients, after FIN-VAL #383 merges.
Owner decisions: retention, expiration/retry and compatibility semantics remain open.
Residual risk: the currently released Run route still permits duplicate commits; isolated tests do not prove end-to-end idempotency.
