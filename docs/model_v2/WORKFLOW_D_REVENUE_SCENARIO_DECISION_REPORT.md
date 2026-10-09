# Workflow D: Revenue, Scenario Intelligence and Tender Pricing

## Provenance and boundaries

- Starting main: `521ee0f4589b7163dd1bd0b39642b57556669a18`, after PR #224.
- Integrated main: `bc9652b0cb620d07ed51df2e4fa329efccea7c13`, after PR #225.
- Branch: `feat/model-v2-revenue-scenario-decision-ux`.
- Integration uses a normal merge, not rebase, squash or cherry-pick.
- One consolidated Draft PR. No merge or deployment authorized.
- No financial-kernel, solver, executor, schema, atomic Run/CAS, history or
  certificate authority changes. Correction A extends the pure scenario
  snapshot resolver and the canonical export input adapter narrowly for tariff
  binding; export authority selection and serialization remain unchanged.
- No changes to the shared workbook shell, field editor, post-run OOB builder,
  global workbook assets or any of PR #225's 16 files.

## Capability inventory

| Area | Existing capability / works | UX gap addressed | Authority gap / deferred |
| --- | --- | --- | --- |
| Revenue | Registry-backed tariff, tenor, indexation, share, balancing, certificates and calendar-year merchant JSON; persisted revenue derivation and periods | Commercial grouping, Working versus Last Run evidence, finite structured curve editing, correct persisted top-level evidence source | No V2 typed editable stepped-PPA contract; no reconstructed price-times-generation result |
| Scenarios | CRUD, override/reset, canonical selection/CAS, immutable run summaries, up-to-three comparison | Run metrics in list; Base reference; pp/x/kEUR deltas; meaningful relative amount variance; separate Working and run-bound overrides | Nested CAPEX/OPEX override blobs are not expanded into new causal attribution |
| Sensitivity | Canonical five-point admitted runner; resolved scenario inputs; existing tornado-data formatter | Explicit scenario, input and driver; units and deltas; actual observed IRR response; all existing DC selectors; finite failed states | No V2 EV driver execution; no typed combined-driver matrix orchestration; no interpolated breakeven |
| Tender | Existing bounded tariff solver, three return targets, typed terminal statuses, canonical explicit Apply | Required price, starting price, absolute/relative movement, exact accepted-value handling, honest vertical and scenario boundary | Scalar Working Copy analysis is not a complete active-scenario solve; no service-price, DSCR/debt-target or auction solve |

## D1: Revenue and commercial pricing

The registry remains the input authority. Existing fields are grouped as
Contracted Revenue, Merchant Adjustments & Other Revenue, and Merchant Curve.
The existing period evidence and `revenue_derivation` remain the output authority.
The top-level evidence previously consulted a missing `runtime_summary.revenue`
key; it now reads already-formatted `revenue_derivation` strings verbatim.
No display string is parsed or used to reconstruct a financial result.

The isolated merchant editor serializes exactly the existing
`[{year, price_eur_mwh}]` JSON contract through `/v2/workbook/update` with
canonical project, field, workbook-version and content-hash tokens.
It sorts years, rejects duplicates, gaps, malformed/non-finite/negative prices
and fractional/out-of-range years, supports add/remove and native Enter submit,
and has idempotent initialization across HTMX swaps.
Backend validation and CAS remain final authority; local text is editing
feedback, not a claimed saved/runtime status. Invalid and stale saves retain the
existing HTMX `workbook-field-error` transport and do not write the workspace.

Data Center keeps service-revenue controls and EV keeps charging controls.
Renewable PPA previews and scenario tariff controls are not presented as EV
capabilities. No pricing schedule is synthesized from formatted runtime outputs.
The existing 13 post-Run OOB fragments are unchanged; Revenue's detailed
Last Run panel is refreshed by reopening/reloading the workbook, not by a
new independent runtime assembly.

## D2: Scenario intelligence

List metrics are canonical `OutputMetricProjection` values from the scenario's
persisted `last_run_summary.kpis`, never from another scenario or a fresh solve.
Unavailable raw values, strings, booleans and non-finite values remain unavailable.
Base Case is ordered as the reference when selected; without it, the first
selected alternative is explicitly labelled as reference. Duplicate IDs and
archived scenarios are excluded. Existing stale-state policy is reused.

Example controlled three-scenario evidence:

- Project IRR `0.076 -> 0.082`: `+0.60 pp`, not `+0.60%`.
- Minimum DSCR `1.20 -> 1.30`: `+0.10x`.
- Revenue `100000 -> 105000 kEUR`: `+5000 kEUR`, `+5.0%`.
- Relative amount variance is unavailable for missing, zero or negative bases.

Working override values and `scenario_overrides_at_run` are independent columns.
Absent run-bound evidence is labelled unavailable; current inputs are not
substituted for it. The comparison reports association, not isolated causality.

Compare and analysis-control GETs reuse the authorized immutable V6
`PostRunRequestContext`, with a final coherence check. Concurrent edits/selections
fail closed with 409 and no-store, not a mixed-snapshot success. These read paths
do not grant authorization, cache across requests or invoke the financial engine.
Sensitivity and Tender refresh their controls on tab entry without modifying
global navigation or introducing client-side financial state.

## D3: Sensitivity and risk analysis

| Vertical | Existing execution drivers presented |
| --- | --- |
| Solar / Wind | Tariff, generation, Senior interest rate, gearing |
| Data Center | Service price, occupancy, IT MW, PUE, electricity price, Senior interest rate, gearing |
| EV Charging | Explicitly unavailable in this V2 execution route |
| Protected reference | Create an editable working copy; execution controls hidden |

Each of the five points still uses the existing canonical candidate runner.
The selected scenario is resolved through the existing scenario authority,
including CAPEX/OPEX folds. No Last Run, history or scenario is written.
The response shows the actual driver input, mode, scenario, result units,
and differences against the unshocked analytical case. That unshocked case is
not mislabeled as the project's Base Case when an alternative was selected.
If it fails, no baseline, deltas or chart are inferred from neighboring points.

`build_tornado_data` is reused over finite already-evaluated Project IRR deltas.
The display is explicitly a single-driver observed range, not a multi-driver
ranking. Low/high labels refer to actual observed results. Failed/non-finite
points are excluded from bars, remain unavailable in the table, and are not zero.
Chart-coordinate scaling and scalar display deltas are presentation only.

2D remains deferred: the V2 path has no existing typed combined-driver grid
contract, per-cell orchestration and admission/budget/error projection. The
worker's general batch limit is not such a contract. No pseudo-3x3 execution,
extra multi-driver loop or interpolation was added. Breakeven links to the
supported bounded tariff solver instead of extrapolating sensitivity points.

## D4: Tender / Goal Seek

The existing solver remains unchanged: Solar/Wind scalar tariff, Project IRR,
Pure Equity IRR and Total Sponsor IRR; maximum 40 evaluations / 60 iterations,
with existing bracket, timeout, busy and typed failure behavior.

Only `SOLVED` or `TARGET_ALREADY_MET` with a finite actual solved value receives
accepted-price presentation. Required EUR/MWh, starting tariff, absolute change,
percentage change, target, achieved metric, error, bounds and counters use the
existing typed result. Other statuses retain their real explanatory message
and cannot display a fabricated accepted price or Apply button.
The exact evaluated float, not rounded display text, remains the Apply payload.

**Important existing boundary:** the tariff solver constructs its scalar inputs
from Working Copy; it does not resolve the full active scenario's scalar
overrides. The existing Apply writes the Working Copy tariff, not a scenario
tariff override. This is now visible guidance, not an invented scenario-aware
solver. Browser Apply acceptance therefore explicitly selects Base Case.
Scenario-aware tariff solving needs a separate reviewed authority extension.

### Independently observed pre-existing scalar-override gap, closed by Correction A

Real Solar Base/Upside/Downside runs expose another upstream boundary:
the scenario editor stores the legacy `tariff_eur_mwh` key, while snapshots can
also contain canonical `rev_ppa_base_tariff`. `app/input_adapter.py` explicitly
prioritizes the canonical key. With canonical price 50 and legacy overrides
85 or 45, `_snapshot_to_dict` returns effective price 50 in both cases.
The authenticated comparison consequently shows unchanged canonical metrics,
not a fabricated scenario effect. Working/run-bound overrides remain visible
as submitted evidence; they do not prove the effective tariff changed.

Correction A explicitly authorizes the narrow application-layer binding fix.
`bind_scenario_tariff` copies the input snapshot and maps only an explicitly
admitted `tariff_eur_mwh` scenario override onto `rev_ppa_base_tariff` when that
canonical key exists. Legacy-only snapshots retain their existing shape.
The global adapter precedence is unchanged; no override still means canonical
Working Copy authority. Finite non-negative values, including genuine zero,
are required. DC/EV tariff injection is rejected before persistence.

The existing pure `resolve_scenario_snapshot` delegates this one alias binding,
so scenario snapshots and selected-scenario sensitivity use the same policy.
V2 Run applies it explicitly to its Working Copy scalar input before the
existing CAPEX/OPEX folds and engine call. It does not write the Working Copy,
change other scenarios, activate the legacy ScenarioManager or change CAS.
No other scalar-override semantics are redesigned in this correction.

Each new Solar/Wind Run records `scenario_revenue_input` from the actual
materialized `ProjectInputs.revenue.ppa_base_tariff`, with the scenario ID.
It is persisted in the canonical runtime summary/history and scenario summary.
Compare separately displays this effective Run tariff; older Runs without
the evidence explicitly say that stored overrides alone do not prove pricing.

Canonical export reconstructs the tariff from the immutable Run identity's
override, only for Runs carrying this new materialized-input evidence.
It verifies both scenario binding and actual reconstructed tariff, and fails
closed on inconsistency. It never reads the live scenario tariff, reruns the
engine, or retroactively reinterprets older Runs. Freshness still compares the
unmodified Working snapshot and composite identity, not the effective overlay.

Real Solar/Wind acceptance covers Base, Upside 85 and Downside 45 EUR/MWh:
persisted revenues and IRRs move in the same economic order; actual effective
tariffs, submitted and run-bound overrides agree; Working Copy is unchanged.
After editing Downside to 46, Last Run export remains 45 and is correctly stale.
Scenario restore, reset/inheritance and immutable existing history are verified.
Exact economics and corrected browser evidence are recorded in the PR report.

Solve alone does not write workspace, Last Run or Run History. Apply remains one
explicit guarded canonical write; it marks the workspace stale until a normal
Run, and reload retains the exact input. No automatic Apply was introduced.
Browser acceptance found that the existing Apply response omitted post-save
Run-token refresh: the input persisted but the next click submitted an old CAS
hash. The scoped correction reuses `build_post_save_ui_state` with its existing
banner/controls refresh. No shared helper, CAS/write protocol or engine execution
mechanism is changed.
The focused regression proves Last Run/history remain unchanged by Apply and
the first normal Run accepts the refreshed canonical tokens.

## Validation and visual evidence

- Pre-integration baseline focused ring: 217 passed, normal process exit.
- Pre-integration expanded candidate ring: 294 passed, normal process exit.
- Final Revenue and correction A/B/C ring: 81 passed, normal process exit.
- Integrated cross-workflow ring: 418 passed, normal process exit (828.11s).
- Isolated final presentation/no-JS-calculation ring: 34 passed, normal exit.
- Final Apply-response regression plus existing Goal Seek V1: 79 passed,
  normal process exit (340.76s); 35 new Workflow D cases in the final file.
- Final combined authenticated browser run: 66 checks passed, normal exit:
  64 vertical/surface/theme/viewport views plus two complete economic journeys.
- Solar: target Project IRR 13.39%, actual rerun 13.388630211088598%, exact
  persisted applied tariff `51.640625` EUR/MWh.
- Wind: target Project IRR 14.35%, actual rerun 14.355176234459458%, exact
  persisted applied tariff `61.546875` EUR/MWh.
- The rings overlap; their counts must not be summed as unique tests.
- Full unchanged public safety scanner: PASS. Final updated-file scan: PASS.
  `py_compile`, diff hygiene, frozen namespaces and PR #225 overlap: PASS/zero.
- `tests/test_model_decision_workspace_v2.py`: exact three-scenario raw deltas,
  non-finite evidence, failed baseline, accepted tariff handling, route/context
  capability matrix, canonical merchant validation/CAS, coherent lazy controls,
  concurrency fail-closed, cross-owner isolation and real non-persisting
  five-point sensitivity.
- `python -m tests.model_decision_workspace_browser`: authenticated isolated
  database, real canonical Solar/Wind/DC/EV Runs, Revenue/Scenarios/Sensitivity/
  Tender across 1440/390 widths and light/dark, plus Solar/Wind economic journeys.
- Screenshot and JSON evidence: `artifacts/model-decision-workspace/` (ignored,
  not committed). Final evidence: `acceptance.json`, `visual-acceptance.json`,
  `final-browser.log`; economic screens include `solar-compare.png`,
  `wind-compare.png`, `solar-sensitivity.png`, `wind-sensitivity.png`,
  `solar-tender.png` and `wind-tender.png`.
  Test logs: `artifacts/workflow-d-integrated-tests.log` and
  `artifacts/workflow-d-apply-tests.log`.
- Browser harness waits for HTMX completion before later economic actions;
  receiving a response alone is not evidence that OOB CAS tokens have settled.
- Frozen namespaces and PR #225 changed-file overlap must both remain zero.
- Five exact-head GitHub workflows are final CI authority. The PR report records
  their final conclusions, full pytest process exit and artifact upload.

## Changed files

Seven owned partials: `sheet_revenue.html`, `sheet_scenarios.html`,
`sheet_compare.html`, `sheet_sensitivity.html`, `sheet_sensitivity_results.html`,
`sheet_goal_seek.html`, `goal_seek_results.html`.

Application presentation: `app/v2/router.py` (scoped read/render sections),
`app/v2/scenario_presentation.py`, `app/v2/scenario_kpi_projection.py`,
`app/v2/decision_workspace.py`.

Scoped assets: `static/css/model_decision_workspace.css`,
`static/js/model_merchant_curve.js`.

Tests: `tests/test_model_decision_workspace_v2.py`,
`tests/model_decision_workspace_browser.py`, and Correction A's
`tests/test_scenario_tariff_authority_v2.py`. This report is the only new document.

Correction A also changes only the pure resolver in
`app/persistence/scenarios_repository.py`, canonical input reconstruction in
`app/services/export_service.py`, and adds
`app/workbook/scenario_revenue_authority.py`. These are the minimum required
application-boundary additions for effective tariff and Run/Export parity.
No SQL/write protocol, export lineage, financial equation or engine changed.

## Correction A: CI root causes and guard compatibility

The original exact-head Public Safety run `37856359890` ended normally with
`8519 passed, 50 skipped, 2 failed`, exit code 1 and uploaded JUnit evidence.
The only failures required the literal `{% if not is_data_center %}` guard;
the combined DC/EV expression was behaviorally restrictive but broke that
established source contract. Genuine nested DC then EV guards now wrap the
entire renewable Revenue sections and scenario tariff/P50 controls.
No inert comment, skipped test or weakened assertion is used. Four-vertical
render tests prove both exclusions and preserve generic financing controls.

PR #227's integration is a normal main merge after its independent merge;
all Workflow C-owned files remain untouched by Workflow D.

## Remaining upstream work

Typed editable stepped-PPA schedules; V2 EV candidate drivers; bounded combined
driver matrices; multi-driver tornado execution; fully scenario-resolved tariff
solving/applying; typed DC/EV service-price solves; DSCR/debt/equity-funding target
solves; expanded nested cost-override audit attribution. None are represented
as implemented here. No financial or persistence boundary was bypassed to add them.
