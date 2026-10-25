# WF-React-2 — Capability matrix (implementation authority)

Base: `origin/main` `7e0cf17fdd7e0535303230c296ddee59ee285735` (tree `dfcf6a1e01d751be373b558e1cc70a7bcf2562a6`, includes #375 and #376).
Branch: `feat/model-wf-react-2-workflows`. PR #377 (WF-React-1) is open/draft and **not** an input to this branch.

Classes: **A** fully supported canonical backend · **B** partially supported (supported subset exposed, restriction labelled) ·
**C** backend unavailable for React (unavailable state, never simulated) · **D** release-closed (never activated here).

Evidence gap: the private *Internal MVP Deep Audit V2* artifact was not accessible in this environment. The defects D-016..D-021 and
D-028 are therefore **not** cited by their audit text; each workflow below was verified independently against the source at the base
commit, and the coverage matrix in the PR names the verified gap instead.

## 1. Feature matrix

| # | Workflow | Class | Canonical GET projection | Canonical mutation | Auth / ownership | CSRF domain | CAS / version | Validation authority | Persistence | Run impact | Existing tests | Remaining limitations |
|---|---|---|---|---|---|---|---|---|---|---|---|---|
| 1 | Open Reference / create Working Copy | A | `GET /v2/model-react/library` | `POST /library/clone/{source_project_id}` | session; `resolve_accessible_project`; canonical reference only | `library-clone-v1` (bound to session + project) | none (creates a new project) | `get_canonical_reference_by_id`, name checks in route | `create_working_copy` | none | `test_rc_sec_csrf_successor`, `test_react_mvp_rc_sec`, library browser tests | Reference-based only. **No React-callable blank-project route** (`POST /projects/create` is a legacy HTML form) → C for blank creation. Library presentation is owned by #377. |
| 2 | Open / continue an existing Working Copy | A | `GET /v2/model-react/workspace` | n/a | session + ownership | n/a | n/a | n/a | n/a | none | workspace browser tests | — |
| 3 | Project setup metadata | B | `GET /v2/model-react/fields/project_setup` | `POST /v2/workbook/update` (per field) | session + ownership; protected reference refused (403) | **none for ordinary fields** (the route validates a token only for `debt.financing.instruments`) | `workbook_version` + `content_hash` (stale → redirect with `v2_err`) | registry `FieldSpec` + `update` handler | workspace draft snapshot | marks STALE, never runs | `test_react_mvp_*`, workbook update tests | only fields labelled `bound` are editable; `partial`, `display-only`, `template-locked` stay read-only. One field per Save (route contract). |
| 4 | Inputs workspace (scalar grid) | A | `GET /v2/model-react/inputs` | `POST /v2/workbook/grid/save` (≤50 cells, atomic) | session + ownership | grid token | `workbook_version` + `content_hash` + `scenario_id` | grid projection + `validate` | draft snapshot | STALE, never runs | grid tests, `test_model_react_*` | Only fields the canonical grid marks editable. No generic JSON mutation exists or is added. |
| 5 | CAPEX line edit (label / amount / notes) | A | `GET /v2/model-react/costlines?sheet=capex` | `POST /v2/workbook/grid/cost-lines/save` (atomic batch) | session + ownership | grid token | `workbook_version` + `content_hash` + per-row `row_version` | `cost_batch_commands` | `capex_sub_lines` | STALE | cost batch tests | amounts in kEUR only; spending profiles and milestone timing are **not** in the line contract (see 7). |
| 6 | OPEX line edit (label / amount / inflation / notes) | A | `GET …/costlines?sheet=opex` | same batch writer | same | grid token | same | `cost_batch_commands` | `opex_sub_lines` | STALE | same | Fixed / Variable / Step structures, effective dates and escalation beyond `inflation_pct` are not in the line contract → C. |
| 7 | CAPEX line add / deactivate / reactivate | B | line list + `eligible_groups` (added) | `POST /v2/capex/line/{add,deactivate,reactivate}` | session + ownership; protected reference refused | **none in the canonical route (pre-existing, inventoried gap)** | `workbook_version` + `content_hash` (+ `row_version` for deactivate/reactivate) | `capex_commands` (group eligibility, finite amount) | `capex_sub_lines` | STALE | capex command/router tests | Route has no CSRF token; React does not change that (no protected-source edit is made). Only deactivation (soft-delete) exists — **no hard delete**. Spending-profile **save** is a legacy HTMX route → C. Contingency is derived (C.13), not editable here. |
| 8 | OPEX line add / deactivate / reactivate | B | line list + `eligible_groups` (added) | `POST /v2/opex/line/{add,deactivate,reactivate}` | same | **none (same gap)** | same | `opex_commands` | `opex_sub_lines` | STALE | opex tests | derived group B.13 refused by the server. |
| 9 | Revenue / PPA — Fixed, Indexed, Scheduled | B | `GET /v2/model-react/revenue` | `POST /v2/workbook/revenue/contracts` | session + ownership; protected reference 409 | plain grid token (`validate_csrf_token`) | `content_hash` (409 `RevenueContractConflict`) | `domain.revenue.multistream_runtime.parse_config` (V1/V2) | workspace snapshot / scenario override | STALE | revenue V2 / PPA-01 suites | Guided editor covers V1/V2 payload fields: contract identity, share, dates, price, indexation rate, **explicit price curve** (schedule points). Contractual index series, indexation timing and price rounding are shown **read-only** and preserved byte-for-byte. V3 advanced products: **D** (release-closed, `ACTIVATION_ENABLED`) → read-only. Floors/caps are not part of the V2 stream schema → C. |
| 10 | Financing fields (senior, equity, fees, DSRA…) | B | `GET …/fields/debt` | `POST /v2/workbook/update` (per field; bound financing token for `debt.financing.instruments`) | session + ownership | none for ordinary fields (inventoried gap); bound `capital-stack-save-v1` token only for `debt.financing.instruments` | `workbook_version` + `content_hash` | registry specs | draft snapshot | STALE | financing F3 suites, `test_financing_f35b_csrf` | per-field Save only (no atomic multi-field financing batch exists). **`debt.financing.instruments` and `debt.bankability.configuration` are structured JSON documents with their own typed editors → shown read-only (C), never as free text.** Multi-tranche / junior / mezzanine / BESS facilities stay under their own release gates → D. |
| 11 | Tax and depreciation fields | B | `GET …/fields/tax` | `POST /v2/workbook/update` | same | grid token | same | registry | draft snapshot | STALE | tax suites | bound fields only (same writer and gap as row 3). |
| 12 | Scenario create / select / rename / archive | A | `GET /v2/model-react/scenarios` | `POST /v2/workbook/scenarios/{create,select,rename,archive}` | session + ownership; base case / reference protected | **none in the canonical routes (inventoried gap)** | none (scenario identity) | scenarios repository | scenarios table | none — **never** runs | scenario tests, `test_ux07_*` | rename route takes `new_name` (the projection’s `fields` hint says `scenario_name` — corrected in this PR). |
| 13 | Scenario override editor | B | `GET /v2/model-react/scenario-overrides` (added, read-only) | `POST /v2/workbook/scenarios/update-overrides`, `…/remove-override` | session + ownership; base case / reference 409 | **none (gap)** | none | `scenario_override_authority` | scenario overrides | none | RC-5 override suites | The canonical Run applies only the overrides in `supported_editor_fields()` (PPA tariff today); any other key is refused 422 `UNBOUND`. The editor lists exactly those fields. |
| 14 | Scenario assumption compare | A | `GET /v2/model-react/scenario-compare` | n/a | session + ownership | n/a | n/a | `resolve_scenario_snapshot` | n/a | none | RC-5 compare tests | — |
| 15 | Scenario KPI comparison | C | none for React. The legacy compare page is HTML | n/a | – | – | – | – | – | – | `scenario_kpi_projection` is HTML-only | No JSON projection of per-scenario committed KPIs exists. React shows **KPI comparison unavailable**; no KPI is computed in the browser. Backend dependency: a read-only JSON projection over committed Run History per scenario. |
| 16 | Run (explicit) | A | `GET /v2/model-react/runs` | `POST /v2/workbook/run` | session + ownership | `workbook-run-v1` | `content_hash` + `workbook_version`; composite CAS | engine | Run History + Last Run | **the only mutation that runs the model** | #376 suites | unknown outcome reconciles against Run History, never retries. |
| 17 | Results / statements | A (owned by #377 for presentation) | `GET …/statements` | n/a | session | – | – | – | – | none | – | not modified here. |
| 18 | Export — Last Run XLSX | A | `GET /v2/model-react/runs` (identity) | `POST /v2/workbook/export` (read-only download) | session + ownership | none (read-only, no state change) | canonical *last committed Run* authority | `build_canonical_last_run_institutional_workbook_export` | none | none | export suites | exports the last committed Run, **not** unsaved or newer Working Copy edits; the UI says so and shows the Run identity and CURRENT/STALE. |
| 19 | Export — historical Run XLSX | A | run history rows | `GET /v2/workbook/run-history/export?project=&history_id=` | session + ownership | none (read-only) | immutable history row | `build_historical_run_workbook_export` | none | none | Reporting V3 suite | — |
| 20 | Sensitivity | C | HTML only | `POST /v2/workbook/scenarios/sensitivity/run` (HTMX, executes engine batches) | – | none | – | – | – | **runs the engine** | legacy suites | React unavailable state with a pointer to the legacy workbook. No uncontrolled model batches. |
| 21 | Goal Seek | C | HTML only | `POST /v2/workbook/goal-seek/{run,apply}` (HTMX) | – | none | – | – | – | runs the engine | legacy suites | No JSON contract; no browser solver. |
| 22 | BESS, advanced debt products, V3 revenue products | D | – | – | – | – | – | – | – | – | release-closed suites | never activated. |

## 2. Boundaries this PR respects

* No change to `financial_engine`, golden tests, accepted tolerances or any protected-source test; the trust CSRF inventory
  (`tests/test_trust_readiness_controls.py`) is **not** edited. Routes that currently carry no CSRF token (rows 7, 8, 12, 13) are
  consumed as-is and listed as a known limitation; adding tokens there requires an exact-path Financial Owner approval.
* Save, scenario select, override edit and compare never execute the model. Run is the single explicit action.
* Ambiguous mutation outcomes (lost response, unexpected redirect) are reconciled against a fresh projection and never retried.

## 3. Verified gaps and how this PR covers them

The private audit (D-016..D-021, D-028) was not accessible, so these are the gaps verified directly in the source at the base commit.
Mapping them onto audit identifiers is left to the independent reviewer who holds that artifact.

| Gap verified at base `7e0cf17` | Coverage | Evidence |
|---|---|---|
| Revenue/PPA edited as a raw JSON textarea | Guided typed editor (Fixed / Indexed / Scheduled), field-level errors, unknown keys preserved byte-for-byte, V3 read-only | `PPAEditorView.tsx`, `workflowValidation.test.mjs`, `test_guided_ppa_editor_*` |
| CAPEX/OPEX lines could be edited but not added or retired | Add / deactivate / reactivate over the canonical line routes, CAS + reconciliation, no hard delete | `CostLineManager.tsx`, `test_capex_add_deactivate_reactivate_*` |
| No project-setup or tax editing in React | `SheetFieldsEditor` over the registry projection, typed controls and bounds | `test_end_to_end_supported_workflow_*` |
| Financing exposed structured JSON documents as free-text boxes | Structured payload fields read-only with the reason; typed fields grouped by registry section with units | `test_end_to_end_*` (financing step) |
| Scenario rename used `window.prompt`; archive had no confirmation; override editing absent; the projection named the wrong rename field | Accessible dialogs, override editor limited to fields the Run applies, corrected hint | `ScenarioWorkspace.tsx`, `test_scenario_*` |
| Run was reachable only inside Results; no unsaved-changes signal | One status bar: CURRENT / STALE / NOT RUN, unsaved count, Reload, the single Run action (blocked while edits are unsaved) | `WorkflowBar.tsx`, `test_end_to_end_*` |
| No export from React | Last Run and historical XLSX over the canonical read-only routes; availability computed with the export route's own resolver (an active scenario without a committed Run is not offered) | `ModelExportView.tsx`, `test_cost_line_management_scenarios_*` |
| KPI comparison per scenario | Explicitly unavailable (no persisted projection) | `data-kpi-compare="unavailable"` |
| "Design prototype" banner and demo origin chip in the live shell | **Not addressed here** - owned by WF-React-1 (#377), which already changes `FincoShell.tsx` | dependency below |

## 4. Gated or unavailable (not implemented, by design)

Blank-project creation (no React-callable route), spending-profile save, OPEX Fixed/Variable/Step structures and effective dates,
PPA floors/caps, contractual index series editing, price rounding editing, V3 advanced products, multi-tranche / mezzanine / BESS
facilities, Sensitivity, Goal Seek, per-scenario KPI comparison, atomic multi-field financing save.

## 5. Remaining dependencies

* `WorkspaceView.tsx`, `adapters.ts` and `FincoShell.tsx` are also changed by #377. This branch keeps its edits to `WorkspaceView.tsx`
  localized; reconcile through an ordinary forward merge of main after #377 lands, then rebuild the bundle from source.
* The CAPEX/OPEX line routes, scenario routes, registry-field writer (ordinary fields) and export carry no CSRF token on main. Adding
  tokens changes protected sources and needs an exact-path Financial Owner approval.
* The browser acceptance and the `.mjs` unit tests are not part of any CI selection (a CI-role change is governance-protected); they are run locally.
