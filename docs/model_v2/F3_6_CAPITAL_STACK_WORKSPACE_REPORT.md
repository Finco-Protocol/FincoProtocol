# F3.6 Capital Stack Workspace V1 (Senior workspace; Junior integration pending PR #253)

Base: `main` 95283b7. Branch `feat/model-f3-6-capital-stack-workspace`. UI / application workflow only.

## H. Dependency status
PR #253 (F3.5-A Senior + Junior authority) is **open / draft / unmerged** (head de8f0f0). Per the brief nothing was
imported or cherry-picked from it and no Junior code exists on this branch. Junior is shown only as an
UNSUPPORTED catalogue entry. When #253 merges: normal merge of main, then add a Junior proposal/readiness row
(activation stays CLOSED: `junior_debt_config.ACTIVATION_ENABLED=False`) and run the F3.5 governance tests.
Final exact-head CI was intentionally not run before the dependency is resolved.

## A. Existing capability matrix (from code on main)
| Capability | Where | Status |
| --- | --- | --- |
| F3.1 typed proposal persistence, stable IDs, digest-bound activation | `app/workbook/multisenior_config.py` | DONE (reused) |
| Two-Senior activation, engine, Last Run facility schedules | `financial_engine/financing/multisenior.py` | DONE (untouched) |
| Writer: `/v2/workbook/update` field `debt.financing.instruments`, composite CAS, scenario scope | router + `workbook_identity` | DONE (reused; no new writer) |
| STALE/CURRENT freshness | `runtime_authority.resolve_runtime_freshness` | DONE (reused) |
| Per-instrument form editor | `_financing_multisenior.html`, `model_multisenior.js` | PARTIAL (disconnected per-instrument forms, no status labels, no summary) |
| Compact cell-first Capital Stack table, backend status labels, working-vs-last-run summary, unsupported catalogue | -- | MISSING -> implemented |
| Junior typed proposal / readiness | PR #253 | MISSING on main (dependency) |

## B. Changed files
- `app/v2/capital_stack_projection.py` (new): read-only projection; no engine/persistence imports (tested).
- `app/v2/router.py`: adds `capital_stack` to the existing Senior Debt context (8 lines).
- `app/templates/v2/partials/_financing_multisenior.html`: table workspace over the same form/payload; state-labelled summary.
- `static/js/model_multisenior.js`: dirty markers, Enter/arrow/Escape navigation, expand/collapse (presentation only; payload serialiser unchanged).
- `static/css/model_capital_stack.css` (new).
- Tests: `tests/test_capital_stack_projection_v1.py`, `tests/test_capital_stack_workspace_browser_v1.py`; adapted `test_model_financing_f3_workspace.py` (template now needs the projection) and the two F3 manual acceptance scripts (rows are collapsed by default).
- No change to `financial_engine/`, `finco_core/`, F3.5 blobs, CI workflows, tolerances or governance mappings.

## D. Supported / unsupported financing
| Structure | Status |
| --- | --- |
| Senior term loan x2, fixed rate, level principal / bullet, grace, dated draws, fees | supported; DRAFT -> SAVED PROPOSAL -> ACTIVE (digest-bound activation, existing release flag) |
| Junior / Mezzanine / PIK, 3rd Senior, floating rate, DSRA/DSRF, active SHL | UNSUPPORTED (listed with reason, never editable, never an amount) |
Labels derive from persisted state: no saved scope entry = DRAFT; saved without activation = SAVED PROPOSAL; digest-bound activation = ACTIVE.
A proposal never shows Last Run schedules or totals as results.

## E. Scenario / CAS / Last Run
Save goes through the existing composite-CAS writer (scenario-scoped entry, stable IDs, cross-scenario write rejected inside the transaction).
Browser tests: Save -> workbook dirty, `last_runtime_snapshot_id` unchanged (no Run, no Run History write); backend rejection
(`F3_INVALID_TERM`) shown in the alert and nothing persisted; reload shows saved values; a non-CURRENT Last Run is labelled and
carries an explicit "previous run" notice. Last Run exports are not touched.

## F. Tests (local)
New 18 (1 skipped until F3.5 exists); F3 workspace/multisenior/canonical-legacy/governance/AI-import: 183 passed, 11 skipped in the combined run.
Manual F3 Q3 acceptance 45/45; F3 browser acceptance (two-Senior Save/Reload/Run/STALE/immutability) passes.
Real Chromium: Solar, Wind, Data Center, EV render + DRAFT + unsupported list; Solar/Wind save/reload; light/dark 1440, light/dark 390 without page overflow.

## G. Financial parity
Inactive and two-Senior numerical paths are unchanged: no engine, core or persistence-schema file was touched; the Save payload serialiser and
backend validation are byte-identical; existing two-Senior Save -> Run -> export tests pass.

## Limitations
Screenshots are local evidence (`artifacts/` is git-ignored). Junior row, F3.5 governance run and exact-head CI await #253.
Instrument ordering follows the persisted collection (unchanged behaviour).
