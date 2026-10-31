# WF-06A Correction A — implementation evidence

Label: **WF06A_BLOCKED_PROTECTED_SOURCE**. The functional work is implemented, built and browser-verified. It cannot pass the protected exact-source guards with the Owner-authorised paths alone. This PR is a Draft for review. **Do not merge.**

Base: `main` = `ebf1f15113ec95d69d29e8aa4e4635686dd1f39a` (verified live; unchanged during the session). Open PRs touch no `frontend/src/app` path (#328, #327, #324, #322, #321, #318, #184 and dependabot).

## Defects and resolutions
| Item | Evidence | Resolution |
|---|---|---|
| A. Save guide | `InputsGuide.tsx` said "there is no global Save" and "each editor saves on its own". The server advertises `save_all` (`app/v2/react_workspace_router.py`: sections `cells`, `contracts`, `cost_lines`; excluded `debt.financing.instruments`). | The guide now explains Save All, its server-capability gate, what it carries, the excluded collections, that it is refused as a whole when a staged change cannot be carried, that individual Saves remain, that nothing autosaves and that no Save runs the model. The required phrases of the existing F04 browser check are kept. The guide table is now in a scroll region (the page overflowed horizontally at 768/390/320 with the guide open). |
| B. DSCR unit | **No defect established.** `TimeSeriesChart` takes the axis and tooltip unit from the series format (`x`). `reportMetric`/`reportCell` keep `x`/`%` and never add a money suffix. Values below 1 are never rounded up to `1.00x`. | `FinancialOverview.tsx` unchanged. Added pure tests and a browser check. **Separate finding, not fixed (`FinancialResults.tsx` is outside the authorised paths):** the chart tooltip text appends `unitText` after `show()`, which already ends in `x`, so it reads `1.25x x`. |
| C. Run failure | The typed envelope has `error_code` in {ADMISSION_REFUSED, ENGINE_TIMEOUT, ENGINE_FAILED, FINANCIAL_REFUSED, FINAL_CAS_CONFLICT, CANCELLED}. Domain refusal wording (SHL, F3, period grid) arrives only in `message`. | `classifyRunFailure` gives SHL, timeline, financing, inputs, transient, conflict, refused and execution categories. Only transient/conflict categories say a retry is safe. Constraint refusals never offer a blind retry. The Last Run is stated as preserved. Every link was verified against workspace anchors (`#inputs`, `#inputs/project`, `#financing`, `#diagnostics`). Covenant/DSCR findings are not a failure kind. |
| D. Cost lines | Real seeded Solar/Wind/Data-centre/EV projects (`create_reference_seeded_project`): the grid showed bare line labels with no group. "Project Controls" exists in both C.09 and C.12 (Data-centre, EV). The Manager shows the raw code `C.13` for the calculated Contingency group. Wind taxonomy is C.01 Production Units "Wind Turbines…", and OPEX B.01 to B.07. | Group heading rows (presentation only; keyboard navigation uses `data-r/data-c`, so it is unchanged). `C.13`/`B.13` are named (same names as the backend catalogue). Table density: the label column yields, headers/totals wrap, so label, amount and OPEX inflation fit with no sideways scroll at 1440/1280/768/390/320. Classification codes, line identity and totals are untouched. |
| **Backend-owned findings (not changed)** | EV-charging OPEX seeds Wind wording ("Meteorological / Weather Forecast Service", "SCADA / Monitoring Platform"). Wind CAPEX has the label "Flow Parts". | Persisted taxonomy; recorded as a backend-owner gap. Nothing hardcoded. |

## Changed paths (old blob → new blob, 12 chars)
| Path | Old | New |
|---|---|---|
| `frontend/src/app/InputsGuide.tsx` | 675cc1ce553d | 884aaa79b029 |
| `frontend/src/app/RunFailureNotice.tsx` | a011339033d2 | 83adb17a55c5 |
| `frontend/src/app/editing/CostLinesGridView.tsx` | bebb185cfaee | a31c064ec04c |
| `frontend/src/app/workflow/CostLineManager.tsx` | dcbf29cc6e26 | 438e881eb950 |
| `frontend/src/styles/ws2-editing.css` | ef7a200a5f6a | f8a58bf4871c |
| `static/react/finco-react.js` | 097f07e6810c | 4330ed0751a3 |
| `static/react/finco-react.css` | 0568204f30a7 | 4634e51e1707 |
| `frontend/src/app/__tests__/wf06a.test.mjs` (new) | — | 964b2b8c05ba |
| `tests/model_react_wf06a_acceptance.py` (new) | — | 1f0fa52de2ff |
| wf03 / wsv2_core / wf04 `SOURCE_SUCCESSOR.json` | bundle pins moved to the new bundle blobs only; the manifest-of-manifest pins re-derived; historical maps untouched | |

## Deterministic build
`npm ci --ignore-scripts` with the committed lockfile (no dependency change), `npm run typecheck`, `npm run build`. Rebuilding twice from the committed source leaves `static/react` byte-identical (`git status` clean), and the build on unmodified `main` also reproduced the committed bundle.

## Why the protected guards stay red (exact paths and failures)
The successor architecture in the authorisation (a new cohort plus manifests plus `fin_v2_cohorts.py`) is not enough. The older cohort modules hard-code closed lists of admissible changed paths, with no registry hook:
1. `tests/wsv2_core_scope.py::_exact_blobs_ok` rejects every changed path that is not in its `OWNED_PATHS` or admitted by the hard-coded WF03, WS2 and WF04 allowances. Rejected: `frontend/src/app/InputsGuide.tsx`, `frontend/src/app/workflow/CostLineManager.tsx`, `frontend/src/app/__tests__/wf06a.test.mjs`, `tests/model_react_wf06a_acceptance.py`. Any new WF-06A path (`tests/fin_v2_wf06a_scope.py`, `tests/test_fin_v2_wf06a_scope.py`, the new manifest and this document) is rejected the same way. Its manifest pin for `RunFailureNotice.tsx` (a011339…) no longer matches.
2. `tests/wf03_lifecycle_scope.py::_historical_maps_ok` / `historical_pin_successor` only allow a predecessor manifest pin to move for a path in WF03 `OWNED_PATHS`. `RunFailureNotice.tsx` is not one, so its pin in the wsv2_core manifest cannot move.
3. `tests/wf04_scope.py::_exact_blobs_ok` rejects (via `_downstream_allows`) the changed paths `InputsGuide.tsx`, `RunFailureNotice.tsx`, `CostLinesGridView.tsx`, `CostLineManager.tsx`, `ws2-editing.css` and the new WF-06A paths.

Paths that need Owner authorisation to make this successor admissible: `tests/wsv2_core_scope.py`, `tests/wf03_lifecycle_scope.py`, `tests/wf04_scope.py`. Each is exact-pinned in the WF-03 manifest, which would then follow. The tests `tests/test_wsv2_core_scope.py`, `tests/test_wf03_lifecycle_scope.py` and `tests/test_wf04_scope.py` would also need the matching additive negatives. Result with the authorised paths only: `wf03 exact = True`, `wf04 exact = False`, `wsv2_core exact = False`, composite `valid() = False`.

## Verification performed (local)
- Node tests: `wf06a.test.mjs` plus the existing `productLanguage`, `editing` and `reportFormatting` suites: 40/40 pass.
- Real Chromium (`tests/model_react_wf06a_acceptance.py`, run locally against a live server with `FINCO_MODEL_REACT_V1=1`): 7/7 pass, twice. Covered: Save guide matches the server capability; group rows, keyboard Tab/Enter and a staged-edit-then-discard probe for Solar/Wind/Data-centre/EV CAPEX and OPEX at 1440/1280/768/390/320 with no sideways scrolling; typed failure fault-injection (SHL, transient, F3); Overview DSCR/IRR units after a real Run.
- Existing F04 save-scope browser check: passes.
- `tests/test_cost_editing_ux_v2_browser.py`: 5 failures that are identical on unmodified `main` in this environment (legacy page, Python 3.13), so inherited.
- Not run: full exact-head CI (F01, eight-worker V3, browser roles), because the protected guards are red; no staging or deploy. Screenshots exist locally only (adding binary files would hit the same closed-world rejection).
