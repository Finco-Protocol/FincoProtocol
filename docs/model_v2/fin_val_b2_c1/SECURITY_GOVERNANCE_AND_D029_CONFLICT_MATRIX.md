# Security, governance and D-029 conflict matrix

## Preserved
SEC-01/SEC-02: operation-bound mutation tokens (`workbook-update`, `grid-save`), composite-hash CAS, ownership and protected-reference guards are *reused unchanged*. The recovery page and the React recovery payload only *issue* the existing tokens; the repair posts to the existing, unchanged `/v2/workbook/update` and `/v2/workbook/grid/save` handlers. No new write route, no CSRF exemption, no change to `app/workbook/mutation_csrf.py` (its pinned blob is untouched), the Run endpoint, Clone or Capital Stack.

## OPEN GOVERNANCE DEPENDENCY — SEC-02 successor inventory pins (SECURITY-GOVERNANCE DEPENDENCY)
`tests/model_mutation_security_successor.py` pins 112 reviewed blobs. Six of them are changed by this PR, so these checks fail at the PR head until an exact-path successor is ratified:

| Path | Pinned blob (main) | New blob | Reason for change |
|---|---|---|---|
| `app/v2/router.py` | `cbff734453400269589d9fcc5cec702cbc239b55` | recorded in the PR | SC-3 recovery gate, OPEX authority context |
| `app/v2/react_workspace_router.py` | `84a41c2e95975a4ab77e31da8b4428651bbfd462` | recorded in the PR | typed 409 recovery payload |
| `app/templates/v2/partials/sheet_opex.html` | `8a84abaa862abbd9400cec2ce1813297fab69f0b` | recorded in the PR | read-only authority branch |
| `frontend/src/app/WorkspaceView.tsx` | `19614dd386d76b3bf4edbe929c8e045bfe41bd2c` | recorded in the PR | recovery panel integration |
| `frontend/src/app/types.ts` | `57af23a933828889583765243e347b9739875b48` | recorded in the PR | recovery types |
| `static/react/finco-react.js` | `c5a8a5ed17326a4ec275ba9e4f573bd47f630486` | recorded in the PR | rebuilt bundle |

Failing tests: `tests/test_model_mutation_security_successor.py::test_exact_implementation_source_and_immutable_ancestry` and `::test_browser_layer_preserves_all_original_pins_and_historical_contract` ("unreviewed blob" for the six paths). The operation-gate AST checks themselves still pass (the gates are unchanged).

**Decision taken:** the protected inventory was **not edited** by this PR — editing a security pin file requires explicit exact-path authorisation, and the automated permission guard refused the attempt. The proposed resolution is an *additive* successor layer, following the precedent of commits `6b779fb5` and `2ada48e5`: keep `SOURCE_HEAD` and all 112 original pins immutable, add an exact `FINVAL_B2C1_SUCCESSORS` map for the six paths (new blob values from the table above at the final PR head), verify the parent blob at `SOURCE_HEAD`, and add tests that (i) the map covers exactly these six paths, (ii) any further byte of drift fails, (iii) the token module and operation gates stay byte-pinned. This needs reviewer/owner authorisation for exactly those paths, then a one-file follow-up commit on this branch.

## D-029 conflict matrix
| D-029 element | Touched by B2/C1? | Note |
|---|---|---|
| Run reservation / idempotency / lease fencing | No | no change to `/v2/workbook/run`, `project_runner`, or any Run state |
| Run commit / history | No | Parity run shows one history row per Run, identical to main |
| Implicit Run after Save or recovery | No | recovery and R-1 refusal never run; Chromium check: 0 Runs |
| Canonical Run endpoint | Unchanged | no new orchestration path |
