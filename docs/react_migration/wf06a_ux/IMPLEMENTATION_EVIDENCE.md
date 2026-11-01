# WF-06A — implementation evidence (PR #406, Correction A + Correction B)

Status label: see "Final outcome" at the end. This PR is a Draft. **Do not merge, deploy or activate.**

Base `main` = `ebf1f15113ec95d69d29e8aa4e4635686dd1f39a` (tree `45e8efdd7e8b0fa8df6497c4e9510a7a27815f85`), verified live before every change. Open PRs touch no `frontend/src/app` path.

## 1. UX defects and resolutions (Correction A, unchanged) + Run row (Correction B)
| Item | Evidence | Resolution |
|---|---|---|
| A. Save guide | The guide said "there is no global Save"; the server advertises `save_all` (`cells`, `contracts`, `cost_lines`; excluded `debt.financing.instruments`). | Rewritten to explain the server-gated Save All, what it carries, what is excluded, refusal as a whole, individual Saves, no autosave, no Save runs the model. |
| A2. Run row (Correction B) | The row said Run "calculates new results from what is already saved". `POST /v2/workbook/run` materialises the workspace `draft_snapshot` (the state every Save writes), enforces the pre-run composite identity and promotes draft to saved only on a committed Run. `WorkflowBar` disables Run while edits are unsaved (`Save or cancel your N unsaved edits before running`). | Smallest accurate wording (`RUN_SCOPE_TEXT`): Run calculates from the project's current inputs, the working draft that Saves write; on success the result becomes the Last Run; text still unsaved in an editor is not used and Run is unavailable until it is saved or cancelled. Node test + Chromium assertion (`[data-run-scope-row]`). No Run API or model change. |
| B. DSCR unit | No defect: chart unit follows the series format; `reportMetric`/`reportCell` never add a money suffix; sub-1 values are never rounded up to `1.00x`. | `FinancialOverview.tsx` unchanged; tests only. **Follow-up, not changed:** `FinancialResults.tsx` shows the chart tooltip as `1.25x x` (file not authorised). |
| C. Run failure | Typed envelope `error_code` in {ADMISSION_REFUSED, ENGINE_TIMEOUT, ENGINE_FAILED, FINANCIAL_REFUSED, FINAL_CAS_CONFLICT, CANCELLED}; domain wording only in `message`. | `classifyRunFailure`: SHL, timeline, financing, inputs, transient, conflict, refused, execution. Only transient/conflict say a retry is safe. Links verified against workspace anchors. |
| D. Cost lines | Real seeded Solar/Wind/Data-centre/EV projects: bare labels without group; "Project Controls" in both C.09 and C.12; raw `C.13` shown by the Manager. | Group heading rows, `C.13`/`B.13` named, density fixes (label column yields; header, total and group cells wrap). No identity, code or total changed. |
| Backend-owned | EV OPEX seeds Wind wording; Wind CAPEX label "Flow Parts". | Recorded, not changed. |

## 2. Governance successor (Correction B)
Why Correction A alone was red (reproduced locally on HEAD `9822216b` before the repair):
`tests/test_finval_f01_fixture_integrity.py::test_authority_mock_has_only_its_missing_unit_added`, `tests/test_finval_f01_scope.py::test_current_scope_is_exact_and_history_required` and `tests/test_finval_rate_successor.py::test_exactly_one_projection_successor_and_historical_layers_unchanged` all failed because the composite cohort closure (`tests/fin_v2_cohorts.valid()`) was False: `wsv2_core` and `wf04` rejected the WF-06A changed paths and the `RunFailureNotice.tsx` pin could not move. The 13 "unreviewed blobs" of the third test are not 13 #406 edits: they are WF-03-owned sources (`app/library/router.py`, routers, bundle, ...) that are recognised only through a valid composite, so they appeared unreviewed once the composite broke. Nothing there was changed by #406.

Design (one closed cohort, no wildcard, no recursion):
- `tests/fin_v2_wf06a_scope.py` (new): BASE = main post-#405 authenticated by ancestry and tree; literal `OWNED_PATHS`; exact blob pins in `docs/react_migration/wf06a_ux/SOURCE_SUCCESSOR.json`; `FOLLOWED_MOVES` (the only pins of four predecessor manifests that may differ from BASE; each must equal this cohort's own pin; every other pin/key/history is byte-identical to BASE); `predecessor_pins` records the BASE value of each moved pin and is re-verified against git. Low level: reads git and its manifest only, never an older cohort or the registry.
- Bounded hooks (call the cohort; the cohort never calls back): `wsv2_core_scope._wf06a_allows`, `wf03_lifecycle_scope._wf06a_repin` / `_wf06a_allows` (one literal pair: `RunFailureNotice.tsx` in the WS-V2 core manifest), `wf04_scope._wf06a` / `_downstream_allows` / `_downstream_pin`. A missing, forged, newer or altered cohort widens nothing.
- `tests/fin_v2_cohorts.py` registers exactly the new cohort. Its pin moved in `fin_v2_r1`, `wf04`, `wf03` and `wsv2_core` manifests (mechanical).
- F01 expectations, `FINVAL_RATE_SUCCESSORS` and every historical map are untouched.

### Changed-path ledger (final)
| Path | Role | Old blob (main) | New blob (12 chars) |
|---|---|---|---|
| `docs/financial_validation/fin_v2_r1/SOURCE_SUCCESSOR.json` | predecessor manifest (pins follow) | 430e09a4eb20 | sealed in the cohort manifest |
| `docs/financial_validation/wf04_debt_metrics/SOURCE_SUCCESSOR.json` | predecessor manifest (pins follow) | 46a3935141ad | sealed in the cohort manifest |
| `docs/react_migration/wf03_project_lifecycle/SOURCE_SUCCESSOR.json` | predecessor manifest (pins follow) | 2bd6a5b0d327 | sealed in the cohort manifest |
| `docs/react_migration/wf06a_ux/IMPLEMENTATION_EVIDENCE.md` | test/doc | (new) | this file (sealed in the cohort manifest) |
| `docs/react_migration/wsv2_core/SOURCE_SUCCESSOR.json` | predecessor manifest (pins follow) | 619ac4be6e5c | sealed in the cohort manifest |
| `frontend/src/app/InputsGuide.tsx` | presentation | 675cc1ce553d | 946efda60cef |
| `frontend/src/app/RunFailureNotice.tsx` | presentation | a011339033d2 | 83adb17a55c5 |
| `frontend/src/app/__tests__/wf06a.test.mjs` | test/doc | (new) | 39a5b7b779a2 |
| `frontend/src/app/editing/CostLinesGridView.tsx` | presentation | bebb185cfaee | a31c064ec04c |
| `frontend/src/app/workflow/CostLineManager.tsx` | presentation | dcbf29cc6e26 | 438e881eb950 |
| `frontend/src/styles/ws2-editing.css` | presentation | ef7a200a5f6a | f8a58bf4871c |
| `static/react/finco-react.css` | presentation | 0568204f30a7 | 4634e51e1707 |
| `static/react/finco-react.js` | presentation | 097f07e6810c | a8e42da398fd |
| `tests/fin_v2_cohorts.py` | governance | baae671c7fd2 | 17c97498d0cf |
| `tests/fin_v2_wf06a_scope.py` | governance | (new) | 62939bf66247 |
| `tests/model_react_wf06a_acceptance.py` | test/doc | (new) | 0ee620589964 |
| `tests/test_fin_v2_wf06a_scope.py` | test/doc | (new) | 18e0c9603bcb |
| `tests/test_wf03_lifecycle_scope.py` | governance | cf2921b7258d | 0c0f0efbc945 |
| `tests/test_wf04_scope.py` | governance | 60ce0963903f | a3738a45a74d |
| `tests/test_wsv2_core_scope.py` | governance | 493738c3ea0b | 09cbb920b7b1 |
| `tests/wf03_lifecycle_scope.py` | governance | 9c767c3f87ee | 70606a7d5a0f |
| `tests/wf04_scope.py` | governance | b96d4c27f921 | 4432d4ae2586 |
| `tests/wsv2_core_scope.py` | governance | 9af504bbc5ef | 6ca3afa6771a |
| `docs/react_migration/wf06a_ux/SOURCE_SUCCESSOR.json` | cohort manifest | (new) | the seal itself |

Predecessor pins moved (BASE value recorded in the manifest `predecessor_pins`, re-verified against git on every check):

- `docs/financial_validation/fin_v2_r1/SOURCE_SUCCESSOR.json`: 1 pin(s): `fin_v2_cohorts.py`
- `docs/financial_validation/wf04_debt_metrics/SOURCE_SUCCESSOR.json`: 9 pin(s): `SOURCE_SUCCESSOR.json`, `SOURCE_SUCCESSOR.json`, `finco-react.css`, `finco-react.js`, `fin_v2_cohorts.py`, `test_wf04_scope.py`, `test_wsv2_core_scope.py`, `wf04_scope.py`, `wsv2_core_scope.py`
- `docs/react_migration/wf03_project_lifecycle/SOURCE_SUCCESSOR.json`: 12 pin(s): `SOURCE_SUCCESSOR.json`, `SOURCE_SUCCESSOR.json`, `SOURCE_SUCCESSOR.json`, `finco-react.css`, `finco-react.js`, `fin_v2_cohorts.py`, `test_wf03_lifecycle_scope.py`, `test_wf04_scope.py`, `test_wsv2_core_scope.py`, `wf03_lifecycle_scope.py`, `wf04_scope.py`, `wsv2_core_scope.py`
- `docs/react_migration/wsv2_core/SOURCE_SUCCESSOR.json`: 7 pin(s): `SOURCE_SUCCESSOR.json`, `RunFailureNotice.tsx`, `finco-react.css`, `finco-react.js`, `fin_v2_cohorts.py`, `test_wsv2_core_scope.py`, `wsv2_core_scope.py`


## 3. Required negative controls (tests/test_fin_v2_wf06a_scope.py and additive tests in the three older scope tests)
One-byte change and deletion of every owned path; forged blob/pin; missing/extra manifest pin; wrong base; wrong tree; swapped parent/ancestry; modified historical map; extra manifest key; unowned pin moved; moved pin that is not the cohort's own; wrong or dropped `predecessor_pins`; unrelated predecessor manifest repin; unreviewed changed path; untracked executable; unregistered cohort; cohort that raises; older guards refuse when the cohort check is false; delegation limited to one literal (manifest, path) pair; future unrelated files cannot use the hooks.

## 4. CI V3 worker diagnostics at HEAD `9822216b` (workflow run 41184238106, attempt 1)
The outer wrapper (`tools.ci_v3_schema.ContractError: worker failure or cleanup failure`, `tools/ci_v3_production.py:282`) hides the cause. The per-worker `ci-v3-diagnostic-worker-N-attempt-1` artifacts were downloaded and their `native.xml` JUnit inspected. Worker 0 passed. In every failing worker the pytest return code was 1 and **every failed original node is a governance / exact-source guard**; no test of a financial, UI, security or CI behaviour failed.

| Worker | Tests | Failed | Failing families (first failing node) |
|---|---|---|---|
| 1 | 2853 | 12 | `test_model_mutation_security_successor` (8), `test_ppa01_candidate_authority`, `test_rc7b_quarterly_csrf_successor`, `test_wf04_numeric_precision_governance`; first: `test_exact_implementation_source_and_immutable_ancestry` ("unreviewed blob") |
| 2 | 2160 | 12 | `test_fin_v2_pr394_corr_scope`, `test_finance_integrity_governance`, `test_financing_f3_governance`, `test_finval_rate_successor`, `test_rcm_governance`; first: `test_the_cohort_is_registered_valid_and_owns_no_financial_namespace` |
| 3 | 2908 | 36 | `test_fin_v2_ci_scope`, `test_fin_v2_rcux_scope`, `test_finval_f01_scope`, `test_wf03_lifecycle_scope`, `test_v9p2a_odr_successor`, ...; first: `test_exact_cohort_requires_history_and_never_touches_the_engine` |
| 4 | 3037 | 18 | `test_finv2_d01_governance`, `test_rc7c_candidate_successor`, `test_rc3_post_merge_authority_states`, `test_v11_stage3_successor`, ...; first: `test_layer_is_exactly_one_additive_path_and_the_current_router_is_admitted` |
| 5 | 2885 | 75 | `test_fin_v2_d01_scope`, `test_fin_v2_wsv2_scope`, `test_wf04_scope`, `test_finval_f01_fixture_integrity`, ...; first: `test_exact_cohort_requires_history_and_never_touches_the_engine` |
| 6 | 4326 | 7 | `test_rcux_governance`, `test_rc3_integration_inventory`, `test_m7_bess_boundaries`; first: `test_exact_candidate_manifest_is_not_a_release_and_mutations_fail` |
| 7 | 2971 | 110 | `test_fin_v2_3_scope`, `test_fin_v2_r1_scope`, `test_wsv2_core_scope`, `test_trust_readiness_registry`, ...; first: `test_exact_cohort_requires_history_and_does_not_activate_native` |

Root cause: the composite cohort registry was invalid at that HEAD (see section 2), which every one of these guards consults. Remedy: the closed WF-06A cohort. No timeout, worker count, node assignment or filter was changed.

## 5. Local verification
- Reproduced on `9822216b` before the repair: the three F01 tests above failed (`F.valid()` False; `matches('tests/test_model_workspace_productivity_v1.py', ...)` False; 13 unreviewed blobs).
- After the repair (committed HEAD, full git history fetched): `tests/test_finval_f01_fixture_integrity.py`, `tests/test_finval_f01_scope.py`, `tests/test_finval_rate_successor.py` and `test_trust_successor_preserves_the_actual_ws2_parent_byte_content`: 28 passed. `tests/test_fin_v2_wf06a_scope.py` + the three older scope tests: all pass (635 tests).
- The union of every test file that failed in workers 1 to 7 (45 files) was re-run in four shards. Failures that remain are identical on an unmodified `main` worktree in this environment (Python 3.13 here; CI uses 3.12): `test_rc_sec_csrf_successor` (2), `test_trust_readiness_controls::test_known_gap_state_changing_posts_have_no_csrf_token`, `test_wf09_csrf_successor::test_inventory_admits_the_router_only_while_the_successor_holds`. Nodes that failed only while the new cohort was uncommitted were guards that evaluate the composite at the committed `HEAD` (for example `v11_violations` calls `fin_v2_valid(root, ref=head)`); they pass once the cohort is committed.
- `tests/test_cost_editing_ux_v2_browser.py` (Correction A item): on an unmodified `main` worktree the same command fails 5 of 26 (`test_stale_composite_hash_is_rejected_when_a_different_row_changed`, `test_stale_row_version_is_rejected_and_rolls_everything_back`, `test_cross_project_foreign_line_and_protected_reference_are_denied`, `test_scenario_switch_with_staged_edits_offers_save_discard_or_stay`, `test_scroll_and_focus_survive_a_keyboard_save`; HTTP 403 on the legacy mutation routes and two legacy selectors not visible). With `FINCO_MODEL_REACT_V1=1` the same worktree fails 6 of 26. They are inherited and unrelated to React presentation files.
- Frontend: `npm ci --ignore-scripts`, `npm run typecheck`, `npm run build`; rebuilding gives byte-identical `static/react`. Node tests (`wf06a.test.mjs` plus existing suites) pass. Real Chromium WF-06A acceptance passes at 1440/1280/768/390/320 for Solar, Wind, Data-centre and EV, plus the Run-row assertion.
- Exact-head GitHub CI (F01, eight-worker CI V3 with aggregate and mandatory evidence, browser, governance, compile, security) is reported in the PR description against the pushed HEAD, so this sealed file does not change the pinned blobs.

## 6. Non-regression statement
No change to `financial_engine/`, `finco_core/`, `domain/`, `app/`, `.github/`, `main_web.py`, Run admission, CSRF, CAS, persistence, authorisation or tenancy. F01 expectations are unchanged. No test was skipped, disabled or weakened; every historical pin map and negative control is unchanged (the followed manifests differ from BASE only at the recorded pins).

## 7. Final outcome
See the PR description (latest exact-head CI status).

