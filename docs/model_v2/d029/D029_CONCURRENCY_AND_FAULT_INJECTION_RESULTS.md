# D-029 concurrency and fault-injection results (real HTTP route, real engine, real SQLite)

All in `tests/test_d029_run_idempotency_http.py` unless stated. Each asserts engine executions, history rows and Last Run.

| Case | Result |
|---|---|
| Same key twice | 1 engine run, 1 history row, replay returns the original `history_id` / `runtime_snapshot_id` |
| 5 concurrent OS processes, same key | exactly 1 COMMITTED, others IN_PROGRESS/REPLAYED, 1 engine run (counter file), 1 history row |
| Real uvicorn server, 2 workers, 5 client processes | same |
| Lost response, then retry | REPLAYED, 1 run |
| Restart (schema cache + executor reset) | REPLAYED from the durable ledger |
| Replay after edit / newer Run | original history row returned; Last Run never overwritten |
| Conflicting binding, same key | CONFLICT 409, no run |
| Different keys | released admission/CAS; every committed intent bound to its own history row |
| Fault in `finalize_cursor` / history append (before COMMIT) | everything rolled back: no history, Last Run unchanged, intent FAILED, terminal |
| Crash after COMMIT before response | intent COMMITTED, retry REPLAYED |
| Stale owner (lease expired, takeover) | fenced: no history, Last Run unchanged, new owner's claim untouched |
| Expired active intent | typed EXPIRED, nothing runs |
| Missing / malformed / foreign history | HISTORY_UNAVAILABLE, never recalculated, foreign id never returned |
| Schema corruption | RUN_INTENT_SCHEMA_INVALID, engine never starts |
| Security | CSRF missing/forged/contradictory/cross-session, cross-actor (404), cross-project, protected reference, invalid UUID |
| Real Chromium (7 cases in the mandatory consolidation role) | React 4 + Legacy 3, all pass locally; includes a genuine committed edit before resuming the original intent |

## Status boundary

Release state: **RELEASE CLOSED**. See the release-state matrix in `D029_EXECUTIVE_REVIEW.md`.
Implemented and tested on PR #384 head: the canonical `POST /v2/workbook/run` intent lifecycle, the single-transaction
commit, startup schema, the React and Legacy clients and the governance successor. Not owner-approved, not activated:
the owner policies in `D029_OWNER_DECISION_REGISTER.md` remain candidates, `RELEASE_POLICY.enabled` is false, nothing is
deployed or merged. A request without `run_intent_id` keeps the released, non-idempotent behaviour.
