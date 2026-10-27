# GAP-R2 / GAP-R3 — Analysis: Sensitivity and Goal Seek, and parity with Legacy

## Sensitivity (`app/v2/react_analysis.py`)

* `GET …/analysis/sensitivity/catalog` — drivers for the vertical (`DRIVERS`), metrics (`supported_metrics`), limits.
* `GET …/strip` — **one driver, 3–5 levels (default 5)**, every headline KPI per point: Project IRR, Pure Equity IRR, Total Sponsor IRR,
  Min/Avg DSCR, Min LLCR, Project/Equity NPV, Sponsor MOIC; baseline, per-point deltas, the driver input before → after, status per point.
* `GET …/matrix` — **two drivers, 3×3 (9 evaluations) or 5×5 (25)**, one metric, optional user threshold (PASS/FAIL as text, labelled "not a
  lender covenant"), bracket notes; the canonical `build_matrix` view model.
* Budget (re-verified in source): `MAX_CELLS = 25`, `MAX_SENSITIVITY_EVALUATIONS = 49` (a matrix without a zero cell costs one extra base
  evaluation, i.e. ≤ 26 for 5×5); an oversize request is refused (422) before any engine work.
* Execution: the same service the Legacy matrix uses — scenario basis, field/typed shocks, CAPEX/OPEX sub-line fold, financing
  materialisation, **rate-lock gate** (a scalar rate shock is refused when a calibrated schedule owns the rate) — evaluated by the original
  `run_project` in `run_model_process` (bounded executor, busy → typed 429, timeout → typed per-point error). No local interpolation.
* Provenance shown on screen and in the payload: *computed now, not a committed Run, nothing saved*; scenario, evaluation count, seconds,
  Working-Copy hash prefix. If the Working Copy changes afterwards the result is flagged **OUTDATED**. Result is discarded if the workspace
  changes during the run (`MATRIX_CONTEXT_CHANGED`).
* Unsupported cases fail closed: reference models (409), non-Solar/Wind/Data Center verticals, contracted-price revenue (typed refusal), Data
  Center is available but flagged PREVIEW.
* UI: tabs *Last Run charts · Sensitivity · Goal Seek* (the existing analysis view is unchanged as the first tab); copy (TSV) and CSV export of the
  **displayed** strings only; Cancel aborts the request; busy engine is reported once, never retried automatically.

## Goal Seek (`app/v2/react_goal_seek.py`)

* `GET …/catalog` — metrics = `GOAL_SEEK_METRICS` (Project IRR, Pure Equity IRR, Total Sponsor IRR), the tariff solve variable (Solar/Wind
  only), current tariff, the solver budgets (≤ 60 iterations, ≤ 40 model evaluations, 0.01 pp tolerance), the CAS binding.
* `GET …/solve` — **PREVIEW**: candidate tariff, movement, achieved metric, target error, iterations, evaluations, explored range, typed status
  (`SOLVED`, `TARGET_ALREADY_MET`, unreachable/invalid/failed → no Apply). Mutates nothing; never a Run; discarded if the identity changed.
* `POST …/apply` — **the only write**: body validated (`extra=forbid`), CSRF signed over session + project (`react-goal-seek-apply-v1`) checked
  before project resolution, then protected-reference gate, the solve-variable field allow-list, finite positive value, and
  `WorkbookUpdateService.apply_draft_update` with the composite-hash and workbook-version CAS. Returns the new hash and the **actual** freshness
  state. Stale hash/version → 409 with "NOT applied"; an exception after the writer may have run → `APPLY_OUTCOME_UNKNOWN` (500).
* UI: an explicit two-step *Apply to Working Copy…* → *Confirm apply*; disabled while this workspace has unsaved edits or a change in progress;
  an unknown outcome locks Apply and offers *Reload the workspace*; Save and Run stay separate.

## Parity evidence (Python 3.12, same process/runtime, real engine)

| Claim | Proof |
|---|---|
| Strip equals the Legacy one-driver route | `test_strip_equals_the_legacy_one_driver_route_for_tariff`: Project IRR of all five points equals the Legacy HTML result to display precision |
| Matrix equals the Legacy matrix route | `test_matrix_equals_the_legacy_matrix_route`: all nine cells, by `(a,b)` index |
| Solve equals Legacy Goal Seek | `test_solved_tariff_equals_the_legacy_route_for_the_same_target`: solved tariff (2 dp), achieved metric (4 dp) and the number of model evaluations are equal |
| Apply equals Legacy Apply | `test_apply_equals_the_legacy_apply_on_a_twin_project`: the entire draft snapshot is equal (apart from names/ids) |
| Apply → STALE → Run | Python and Chromium: Apply changes only the draft, records no Run (`last_runtime_snapshot_id` unchanged), freshness `CURRENT → STALE`; the deliberate Run is `CURRENT` and the committed Project IRR is within 0.015 pp of the target |
| Preview mutates nothing | draft, saved snapshot, dirty flag and last-run id compared before/after (Python + Chromium) |
| UI figures are the canonical figures | Chromium compares every displayed KPI cell with the adapter response for the same request |

Samples: `api_contracts/sensitivity_*.json`, `goal_seek_*.json`.

## Limits

Data Center and EV Charging have no Goal Seek solve variable in V1 (typed refusal). Revenue V2 contracted-price projects refuse tariff shocks
(canonical guard). The Legacy one-driver sensitivity route itself is unchanged and still available in the classic workbook.
