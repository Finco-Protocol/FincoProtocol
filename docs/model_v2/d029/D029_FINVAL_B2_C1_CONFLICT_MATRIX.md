# D-029 / FIN-VAL B2/C1 conflict matrix

User confirmed another agent is working B2/C1, then provided [PR #383](https://github.com/Finco-Protocol/FincoProtocol/pull/383).
Live receipt: Draft OPEN at `8422adbeca843ada3fb6f476ce06b1ef7b519e99`, base main `8944aca...`, 25 changed paths.
No instruction or approval is inferred from the other agent's PR body. It is dependency evidence only.

| Surface | #383 evidence / D-029 need | Resolution |
|---|---|---|
| app/v2/router.py | B2/C1 recovery/Save; D-029 replay ordering/Run claim | Do not edit before independent merge |
| frontend/src/app/api.ts | Direct shared file; D-029 exact intent submission/replay | Defer wiring |
| react_workspace_router, WorkspaceView, types, static React bundle | Recovery projections/client changes; D-029 Run contract/UI | Defer overlapping integration |
| workspace_repository.py | Not changed by current #383; shared persistence contract requested by prompt | Preserve until post-merge canonical hook |
| db.py / trust-readiness inventory | D-029 startup/schema/data-store migration | Explicit migration isolated now; startup deferred |
| new run_intent_repository/service + D-029 tests/reports | D-029-only new files, no #383 overlap | Implemented and locally validated |
| SEC-02 successor inventory | #383 reports six changed pinned sources needing reconciliation | Preserve historical pins; integrate after successor authority settles |

After #383 is independently merged: fetch main, normal forward merge (no rebase/cherry-pick), re-audit exact
path/blob and security order, wire existing handler/commit authority, finish both clients, update narrow successor
recognition and run all acceptance cases. Use this SAME D-029 Draft PR. No alternate Run handler or second writer.

## Status boundary

Implemented: isolated reservation, lookup/reconciliation, schema audit, fencing and cursor finalization helpers.
Proven: the executed persistence-only and released-baseline checks listed in `evidence/D029_LOCAL_TEST_RESULTS.json`.
Proposed policy: `D029_OWNER_DECISION_REGISTER.md`; no production rollout is enabled.
Deferred integration: canonical HTTP Run, financial commit hook, startup migration and real clients, after FIN-VAL #383 merges.
Owner decisions: retention, expiration/retry and compatibility semantics remain open.
Residual risk: the currently released Run route still permits duplicate commits; isolated tests do not prove end-to-end idempotency.
