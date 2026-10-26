# D-029 / FIN-VAL B2/C1 conflict matrix (resolved)

#383 merged (`36edeeb5d9a1`); main was forward-merged normally into this branch.

| Surface | Resolution |
|---|---|
| `app/v2/router.py` | Run handler extended on top of the FIN-VAL B2/C1 state; new blob admitted by `D029_RUN_INTENT_SUCCESSORS` |
| `static/react/finco-react.js` | Rebuilt from reviewed sources (deterministic build verified against the previous bundle first); new blob in the same layer; CSS unchanged |
| `frontend/src/app/api.ts`, `workflow/WorkflowBar.tsx`, new `runIntent.ts` | Not pinned; changed |
| `workspace_repository.py` | Not pinned; additive `run_intent` parameter |
| `db.py` / `trust_readiness/registry.py` | Startup schema + `data.run_intents` inventory (relayed authorization) |
| SEC-02 / FIN-VAL pins | All 112 original pins and the six FIN-VAL B2/C1 successors preserved verbatim (test); D-029 layer is additive, 2 paths, never a repin; historical blobs remain individually admitted |
| `tests/test_model_workspace_consolidation_browser.py` | Pinned; NOT modified. Wrappers prepared, awaiting exact-path authorization |

## Status boundary

Release state: **RELEASE CLOSED**. See the release-state matrix in `D029_EXECUTIVE_REVIEW.md`.
Implemented and tested on PR #384 head: the canonical `POST /v2/workbook/run` intent lifecycle, the single-transaction
commit, startup schema, the React and Legacy clients and the governance successor. Not owner-approved, not activated:
the owner policies in `D029_OWNER_DECISION_REGISTER.md` remain candidates, `RELEASE_POLICY.enabled` is false, nothing is
deployed or merged. A request without `run_intent_id` keeps the released, non-idempotent behaviour.
