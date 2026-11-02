# WF-06B exact-source successor — measured plan (NOT yet implemented)

Why this document exists: the owner asked for a bounded authenticated WF-06B successor. Source work was done first; this is what a measured
look at the existing cohort architecture shows is required, so the successor can be built without weakening any predecessor.

## 1. Measured state of this branch

`tests.fin_v2_cohorts.cohorts()` registers 12 cohorts. `exact_blobs_ok()` on the current tree: TRUE for `fin_v2_3`, `fin_v2_ci`, `fin_v2_d01`,
`fin_v2_r1`, `fin_v2_pr394_corr`; FALSE for `fin_v2_rcux`, `wsv2_core`, `fin_v2_wsv2`, `wf04`, `wf03_lifecycle`, `fin_v2_wf06a`,
`fin_v2_integration_409`. The checks themselves take well under a second; the 9-minute cost is the cohort test files (synthetic tamper
repositories), so the successor can be iterated quickly and the heavy suites run once at the end.

## 2. What changed and where it is pinned today (old blob -> manifests that pin it)

| Changed existing path | Pinned in |
|---|---|
| `app/v2/react_workspace_router.py` | fin_truth_b1, rc_ux_completion, wf03_project_lifecycle, wsv2_editing manifests |
| `frontend/src/app/editing/CostLinesGridView.tsx`, `frontend/src/styles/ws2-editing.css` | wf06a_ux manifest (and the wsv2 cohort's owned list) |
| `frontend/src/app/workflow/WorkflowBar.tsx` | wf04_debt_metrics, wsv2_core manifests |
| `static/react/finco-react.{js,css}` | wf04, wf03, wf06a, wsv2_core manifests |
| `frontend/src/app/types.ts` | historical reports only (no live pin found) |

Any scope module edited to register or hook the successor is itself pinned: `tests/fin_v2_cohorts.py` (r1, wf04, 409, wf03, wf06a, wsv2_core
manifests), `tests/wsv2_core_scope.py`, `tests/wf04_scope.py`, `tests/wf03_lifecycle_scope.py`, `tests/fin_v2_wf06a_scope.py` and the #409 seal module
(409 and wf06a manifests). The manifests form a DAG (409 -> wf06a -> wf03 -> wf04 / wsv2_core -> fin_truth_b1 / rc_ux_completion / wsv2_editing), so a
pin change must be applied leaves-first and verified.

## 3. Design that preserves history (to implement last, after source is frozen)

1. New low-level cohort `tests/wf06b_scope.py` (no import of other cohorts, no recursion), registered in `fin_v2_cohorts.COHORT_MODULES`:
   literal `BASE = b7bfc4ed0fd224618e42f80dcacb3e1076e772ff`, `BASE_TREE = 32cf0ea11d06147fa339729d7dc855fcf13564ce`, ancestry check, a literal finite
   `OWNED_PATHS`, one exact blob pin per owned path, a literal `REPIN` table of predecessor manifests, and "nothing else changed since BASE; protected
   prefixes (`financial_engine/`, `finco_core/`, `domain/`, `.github/`) never move".
2. Predecessor manifests change ONLY in the current-source pin value of paths WF-06B owns (structural JSON diff against BASE: every other key, every
   `historical_source_blobs` entry and the whole `path_ledger` prefix must be byte-identical). New current-pin values must equal the blob in the tree.
3. A bounded `_wf06b_allows` hook (same shape as the existing `_wf06a_allows` / `_int409_allows`) in the modules that use hard-coded successor hooks
   (`wsv2_core_scope`, `wf04_scope`, `wf03_lifecycle_scope`, the #409 seal's step 3/6), each delegating only while the WF-06B cohort is itself exact. The
   modules that use the generic hub (`rcux`, `wsv2`) need no code change.
4. Negative controls: one flipped byte in each owned file, forged pin, missing/extra path, forged lineage/base, untracked executable, a predecessor manifest
   with any non-pin edit, a pin that does not match the file.
5. No global cache, no blanket `except`, no `return True`. F01's three tests are then expected to pass because they ask the composite hub, which becomes valid;
   they must not be edited.

## 4. Coordination

The prompt names a parallel ON-09B governance workstream that may edit the same protected tests. At the last preflight no PR other than dependabot bumps and old
drafts (#318, #321, #322, #324, #327, #328) was open and `main` was still `b7bfc4e`; re-check live before building the successor and never edit another branch.
