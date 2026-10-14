# M3 — Two-driver sensitivity matrix and threshold bracketing V1

Base: `origin/main` `5058c6b4935168241d6923676cb32955cb903185`. Branch `feat/model-two-driver-sensitivity-v1`.
One Draft PR. No self-approval, merge or deployment.

ZERO changes to `financial_engine/`, `finco_core/`, `domain/`, CI workflows, tolerances, goldens, Revenue V2 schemas,
Developer Economics authority or Crypto/Radar. No new IRR, NPV, DSCR or debt solver. No new KPI catalog.

## 1. REUSE versus EXTEND

| Capability | Source | Treatment |
| --- | --- | --- |
| Scenario resolution (`resolve_active_scenario_runtime_snapshot`, Working Copy draft) | existing one-driver route | REUSED, same rules (re-expressed in `sensitivity_matrix.resolve_basis`, shared router untouched) |
| `ProjectInputSet.with_value` field drivers (tariff, yield, interest rate, gearing, DC drivers) | one-driver route | REUSED mechanism, same field ids |
| Typed CAPEX / OPEX / merchant shocks | `sensitivity_service._apply_shock` | REUSED verbatim (legacy tornado authority) |
| CAPEX / OPEX sub-line fold, fee authority, F3 `apply_state` | one-driver route / Goal Seek | REUSED in the same order of authority |
| Canonical runner and bounded executor | `run_sensitivity_points`, `run_model_process`, `MAX_SENSITIVITY_EVALUATIONS = 49` | REUSED unchanged: one request = one admitted ordered batch |
| KPI catalog and formatting | `output_metric_projection.KPI_CATALOG`, `_apply_fmt` | REUSED; no second catalog |
| Request-context stale rejection | `PostRunRequestContext.capture / validate_current` | REUSED |
| Goal Seek (precise 1-D tariff solve) | `app/services/goal_seek.py` | NOT duplicated; linked from the result when tariff is a driver |
| One-driver sensitivity, Tornado, Revenue Commercial Stress, Compare | existing | UNCHANGED |
| Two-driver grid, bounds, threshold classification, bracket detection, matrix UI | — | NEW: `app/v2/sensitivity_matrix_projection.py`, `app/services/sensitivity_matrix.py`, `app/v2/sensitivity_matrix_router.py`, two templates, one CSS file |

Shared-file overlap (integration hooks only): `app/v2/router.py` (+4 lines: include the new router) and
`app/templates/v2/partials/sheet_sensitivity.html` (lazy matrix region; the stale "two-driver matrices are not
available" sentence was replaced). No overlap with `post_run_ui.py`, Diagnostics or Revenue V3 files.

## 2. Calculation contract

Every cell starts from the same resolved scenario state and applies BOTH shocks to canonical inputs:
(1) field drivers through `with_value`; (2) complete typed `ProjectInputs` and the CAPEX/OPEX sub-line fold;
(3) typed drivers through the existing shock service; (4) fee authority and F3 financing materialisation;
(5) the original `run_project`. A shock is never applied to a computed output; two single-driver deltas are never
summed. A shock that does not change the typed inputs (for example a merchant shock on a project without a merchant
curve) is a typed `SHOCK_NOT_APPLIED` cell failure, never the silent unshocked result.

## 3. Supported drivers, levels and metrics

| Vertical | Drivers (unit) |
| --- | --- |
| Solar, Wind | CAPEX (%), OPEX (%), PPA/tariff price (%), merchant price (%), yield/P50 hours (%), senior interest rate (bps), senior gearing (pp) |
| Data Center | CAPEX (%), OPEX (%), service price (%), stabilised occupancy (pp), IT load (%), PUE (%), electricity price (%), senior interest rate (bps), senior gearing (pp) |
| EV Charging | **Rejected** (the existing sensitivity workspace does not support it; no driver is substituted) |

3 to 5 distinct finite levels per axis, entered in the driver's unit, sorted ascending, each within a per-driver
bound (50 % for prices/CAPEX/OPEX, 30 % for yield/PUE, 500 bps, 20 pp).
**Default grid is 3 × 3 (9 evaluations: Base and the inner steps of the existing one-driver defaults); 5 × 5 (25
evaluations) is an explicit "Grid size" choice**, and explicit levels override either default. Maximum 25 cells;
Base/Base is reused when both axes contain 0, otherwise one extra Base evaluation: at most 26 evaluations, under the
existing ceiling of 49. Larger requests fail with `SENSITIVITY_GRID_TOO_LARGE` before any run. Executor timeouts are
unchanged.

**Metrics.** The worker returns the canonical `result["kpis"]`, plus the catalog metrics whose authoritative source is
the debt or sponsor schedule SUMMARY of the SAME run, projected through the existing source-key mapping (the one
`run_history_projection._enriched_kpis` uses): `min_llcr`, `target_dscr` from `debt_schedule.summary`;
`sponsor_moic`, `pure_equity_moic` (and `sponsor_irr`) from `sponsor_schedule.summary` via `SPONSOR_SUMMARY_SOURCE_KEYS`.
Nothing is computed. `total_cfads_keur` is a documented gap of the catalog itself (neither `kpis` nor the summaries of
a canonical run carry it) and is therefore NOT offered and rejected by the route. NPV and LLCR are offered but flagged
"only when … configured/produced": when the run yields none the cell is `UNAVAILABLE`, never zero.

## 4. Threshold and break-even semantics

Optional explicit user threshold, comparator `>=`, in display units. It is labelled user-provided and is never
presented as a lender covenant. Cells are PASS / FAIL / UNAVAILABLE (failed or unavailable calculations are never
classified). A bracket is an adjacent pair of cells (along either axis) with one PASS and one FAIL; the report states
that a crossing lies between them and infers no boundary value. No interpolation, no solver-exact claim.

## 5. Integrity

Read-only and ephemeral: no Working Copy, scenario, Last Run or Run History write (asserted by test); the response is
marked `EPHEMERAL`, never CURRENT; `Cache-Control: no-store`; owner/project/scenario identity is validated; a
workspace change during the batch discards the result (`409 MATRIX_CONTEXT_CHANGED`); protected references and
unauthenticated callers are refused.

## 6. Evidence

`tests/test_m3_two_driver_sensitivity.py`: 33 passed locally (Python 3.12).

| Requirement | Evidence |
| --- | --- |
| Both shocks truly applied; each cell equals an independently invoked combined-shock canonical Run | Real **Solar** CAPEX × PPA price and real **Wind** OPEX × yield: the four corners and Base/Base of a 3×3 grid equal an oracle that rebuilds the canonical Run input chain WITHOUT the matrix service (legacy typed shock service for CAPEX/OPEX/PPA, `with_value` for the P50 field) and calls `run_project`, within the 2-decimal display rounding (6e-5). Corners differ from both edge cells and from Base. |
| Zero/zero equals the base model | Base/Base cell equals an unshocked oracle run; the matrix reuses it as Base. |
| Input ordering does not change results | CAPEX×OPEX and interest-rate×gearing grids run as A×B and B×A give identical transposed values. |
| Field-driver path (interest rate bps, gearing pp) | +100 bps / −5 pp cell equals an oracle built with `with_value` on `debt.senior.*` and run directly. |
| Data Center | CAPEX × PUE runs (Base OK, ≥4 OK cells); engine fail-closed errors (`PR8_CLEAN_ENGINE_FAIL_CLOSED`, SHL maturity residual) surface per cell without blocking the others; renewable drivers are rejected for Data Center. |
| EV Charging, unsupported/duplicate drivers, level count/bounds/duplicates, bad metric/threshold, grid-size ceiling | Typed 422 before any run (executor never called). |
| One admitted batch, deterministic row-major order, no request storm | Faked executor records exactly one call per request with the expected batch size; a request without a 0/0 cell adds exactly one Base evaluation. |
| Failed/unavailable/timeout/busy handling | Failed and metric-less cells render FAILED/UNAVAILABLE without blocking valid cells; busy → 429 with Retry-After; timeout → per-cell `CALCULATION_TIMEOUT`; internal error text is not leaked. |
| Unapplied shock | Typed failure, never the unshocked value. |
| Stale request context | Workspace change during the batch → 409, results discarded. |
| Ownership, scenario isolation, authentication | Other user → 404, unknown scenario → 404, unauthenticated → 401 (executor never called). |
| No persistence / Last Run untouched / never CURRENT | Workspace draft, Last Run fields, row version and Run History identical before/after; response marked `EPHEMERAL`. |
| Thresholds, deltas, brackets | Pure tests: >= classification, pp / x / kEUR deltas, adjacent PASS/FAIL brackets only, unavailable cells never bracket, no threshold → no classification. |
| Neighbours unchanged | Existing one-driver sensitivity route still renders; no engine/CI file in the diff (asserted). |

Browser acceptance (real authenticated Chromium, live uvicorn server, disposable synthetic Solar working copy):
`tests/test_m3_two_driver_sensitivity_browser.py` — driver, scenario (a created scenario), grid, metric and threshold
selection; a real 3 × 3 run through the executor; threshold classification (a median threshold splits the grid into
PASS and FAIL, brackets listed with "no boundary value is inferred"); numeric value and status are text (readable
without colour); error messaging (duplicate driver, level count) swapped into the results area; 390 px layout (controls
inside the viewport, no horizontal page scroll); a run writes nothing but the analysis request. Screenshots were taken
locally and are not committed. The browser run found and fixed two real defects that the HTTP-level tests could not:
HTMX silently dropped 4xx error fragments (now swapped through a small marker-header handler, `static/js/sensitivity_matrix.js`),
and the form controls overflowed at 390 px.

## 7. Capacity, performance and limitations

* One admitted executor task runs the whole ordered batch. Locally a canonical evaluation took roughly 4 s on the
  development machine (9 evaluations in about 37 s), so a full 25-cell matrix needs roughly 100 s there. The executor
  timeout is 180 s per task; on slower hardware a full matrix can exceed it, in which case every cell is reported
  `CALCULATION_TIMEOUT` (partial results are not salvaged). Smaller grids (3×3 or 3×5) are the safe operating range
  until measured on target infrastructure. These are synthetic local timings, not production figures.
* The Revenue V2 explicit contract book has no scalar tariff authority: price drivers are rejected on those projects.
* With F3 explicit financing commitments, CAPEX shocks fail closed at financing materialisation rather than silently
  inconsistent funding.
* **Pre-existing defect in the one-driver sensitivity route (reported, NOT changed here).** Seeded Working Copies store
  `debt.senior.interest_rate_pct` as a ratio (0.055 = 5.5 %) whereas `with_value` and the Save path take percent. The
  existing one-driver route adds its ±1.0 / ±2.0 "percentage-point" steps to the raw snapshot value, so a "+100 bps"
  point becomes a 1.055 % rate and "−100 bps" is rejected as a negative rate. The matrix does not reuse that
  arithmetic: it reads the current rate from the typed Senior pricing authority (`senior_rate_authority`), shocks it in
  true basis points, refuses a calibrated non-uniform schedule and a bankability-owned rate (the Save-path gate), and
  is pinned by tests (+100 bps ⇒ typed rate 6.5 %). Fixing the one-driver route is a separate, governed change.
* Repeat runs of identical inputs can return in a fraction of a second (the existing canonical-run result reuse), so
  repeat timings are not representative; first-run figures above are the meaningful ones.
* Wind reference projects carry no stored gearing value: gearing cells fail with `BASE_VALUE_MISSING` rather than
  inventing a base.
* Revenue V3 drivers (M2) are out of scope; they can be added as a separate integration extension.
* Browser/visual acceptance: see section 6.
