# D-029 financial regression and performance

All existing financial sources, canonical router/commit/schema, security validators and deployed clients are
byte-identical to merged main; source blob receipt verifies selected integration/governance files independently.
The real canonical baseline exercises released financial calculation. New persistence tests use synthetic
outputs and do NOT establish integrated financial bit identity, complete certificates or whole-Run latency.
Existing FIN-VAL B1, Golden Flow and Run Certificate regression command/results are recorded in local evidence.

Windows local WAL, 40 synthetic persistence iterations; includes normal get_connection/schema-guard costs.

| Operation | Median ms | p95 ms | Max ms |
|---|---:|---:|---:|
| reservation_ms | 10.536 | 14.311 | 19.794 |
| lookup_ms | 5.176 | 8.243 | 9.523 |
| start_ms | 12.159 | 16.222 | 22.518 |
| history_and_finalize_commit_ms | 11.213 | 15.894 | 16.855 |
| reconcile_ms | 7.661 | 12.851 | 14.059 |

`history_and_finalize_commit_ms` includes synthetic canonical history append and commit, not a financial Run.
`reconcile_ms` is exact-history helper lookup, not network replay latency. Five-process contention is proven
functionally by the spawned-process test; production five-worker HTTP throughput remains unmeasured.
Normal real Run latency before/after and Solar/Wind/DC/EV bit-identical output/certificate comparison are
DEFERRED until actual integration. No formula/native-kernel/solver/tolerance changes were made.

## Status boundary

Release state: **RELEASE CLOSED**. See the release-state matrix in `D029_EXECUTIVE_REVIEW.md`.
Implemented and tested on PR #384 head: the canonical `POST /v2/workbook/run` intent lifecycle, the single-transaction
commit, startup schema, the React and Legacy clients and the governance successor. Not owner-approved, not activated:
the owner policies in `D029_OWNER_DECISION_REGISTER.md` remain candidates, `RELEASE_POLICY.enabled` is false, nothing is
deployed or merged. A request without `run_intent_id` keeps the released, non-idempotent behaviour.
