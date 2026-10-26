# WF-REACT-3 financial capability and source matrix

The JSON layer reads immutable `app.persistence.run_history_repository` entries after resolving project access. Every selected column carries the actual history, snapshot, composite, scenario, engine and workbook identity. One to three explicit unique Run IDs are required. A scenario without a persisted successful Run has no result column; its status is **No committed Run exists for this scenario.** Historical values never inherit another scenario's results or the active Working Copy's assumptions.

`runtime_summary`, schedules and integrity evidence in this table mean fields on that same selected history entry, never the current workspace result. `output_metric_projection.KPI_CATALOG` owns metric units and display precision; `scenario_kpi_projection` owns supported comparison deltas. Percentage display units carry raw fractions; coverage units `x` carry raw ratios. `kEUR` values remain thousands of euros. Aggregate metrics have period `AGGREGATE`; timeline cells retain canonical persisted period indices and dates.

| Metric / evidence | Canonical source | Unit | Run identity | Historical availability | Scenario availability | React exposure | Missing authority / restriction |
|---|---|---|---|---|---|---|---|
| Project IRR | `runtime_summary.project_irr`; `output_metric_projection` | % (raw fraction) | Selected history/snapshot | When persisted | Own committed Run only | KPI, comparison, returns | No IRR solver or reconstruction |
| Pure Equity IRR | `runtime_summary.equity_irr`; `returns_projection` | % (raw fraction) | Selected history/snapshot | When persisted | Own committed Run only | KPI, comparison, returns | Unavailable when canonical equity status publishes no value |
| Total Sponsor IRR | `sponsor_schedule.summary.total_sponsor_xirr`; explicit `SPONSOR_SUMMARY_SOURCE_KEYS` | % (raw fraction) | Selected history/snapshot | When persisted | Own committed Run only | KPI, comparison, returns | Never replaced by Equity IRR or same-named unrelated runtime scalar |
| Pure Equity / Sponsor MOIC | `sponsor_schedule.summary.pure_equity_moic` / `total_sponsor_moic` | x | Selected history/snapshot | When persisted | Own committed Run only | KPI, comparison; sponsor MOIC in returns | Explicit distinct schedule fields only |
| Project / Equity NPV | `runtime_summary.project_npv_keur` / `equity_npv_keur` | kEUR | Selected history/snapshot | When persisted | Own committed Run only | KPI, comparison | No discount rate or NPV calculation introduced |
| Minimum / Average DSCR | `runtime_summary.min_dscr` / `avg_dscr`; `credit_decision_projection` | x | Selected history/snapshot | When persisted | Own committed Run only | KPI, credit, comparison | Canonical observed financial result; not a covenant by itself |
| Target DSCR | `run_history_projection._enriched_kpis`: persisted runtime scalar, otherwise `debt_schedule.summary.target_dscr` | x | Selected history/snapshot | When persisted | Own committed Run only | KPI, credit, comparison | Sizing target is not a contractual covenant |
| Minimum LLCR | Same-row `runtime_summary.min_llcr`, otherwise `debt_schedule.summary.min_llcr` | x | Selected history/snapshot | When persisted | Own committed Run only | KPI, credit, comparison | Missing discount basis / coverage case stays unavailable; no cash-flow derivation |
| PLCR | Existing `credit_decision_projection` unavailable classification | x | Selected history/snapshot | Unavailable | Unavailable | Explicit unavailable metric / credit finding | No approved persisted PLCR source |
| Senior debt | `runtime_summary.senior_debt_keur`; credit financing evidence | kEUR | Selected history/snapshot | When persisted | Own committed Run only | KPI, credit, comparison | Facility role/aggregate distinctions remain canonical |
| DSCR debt capacity / gearing debt capacity / final commitment | `runtime_summary.financing_evidence.bankability`; `credit_decision_projection` | kEUR | Selected history/snapshot | When persisted | Own committed Run only | Credit evidence | No sizing calculation in JSON or React |
| Binding constraint | Same persisted bankability evidence | Text | Selected history/snapshot | When persisted | Own committed Run only | Credit evidence | No inference from displayed debt amounts |
| Gearing | `credit_decision_projection` committed financing structure / evidence | % (raw fraction) | Selected history/snapshot | When supported by canonical evidence | Own committed Run only | Credit evidence | No ratio reconstructed by React |
| CAPEX / revenue / EBITDA / CFADS totals | `runtime_summary.total_capex_keur`, `total_revenue_keur`, `total_ebitda_keur`, `total_cfads_keur` | kEUR | Selected history/snapshot | When persisted | Own committed Run only | KPI, comparison | Missing total CFADS scalar remains unavailable even when a timeline exists |
| Period CFADS / debt service / interest / principal | `credit_decision_projection` over `integrity_evidence.senior_debt.periods` and approved persisted schedules | kEUR | Selected history/snapshot + original period index/date | When canonical period evidence exists | Own committed Run only | Model-period timeline and accessible table | No annual aggregation; no interpolated missing intervals |
| Reported DSCR / sizing target series | Canonical credit timeline over persisted `reported_dscr` / `target_dscr` | x | Selected history/snapshot + original period index/date | When persisted | Own committed Run only | Model-period timeline and table | No LLCR / PLCR series; no browser coverage calculation |
| Critical periods / credit findings | `credit_decision_projection.build_credit_decision`, existing integrity checks | Canonical check-specific units/status | Finding identifies selected history | Persisted evidence / approved checks | Own committed Run only | Credit findings and risk evidence | No new thresholds, ratings or risk scores |
| Solver convergence / feasibility | Persisted financing convergence and existing Credit Decision `CD-F2` / `QM-SD-007` | Text/status, x | Selected history/snapshot | When persisted | Own committed Run only | Distinct credit evidence | `CONVERGED` does not imply feasibility, compliance or bankability |
| Reserves / DSRA / DSRF | Canonical credit projection over persisted financing, reserve and debt evidence | kEUR / canonical text | Selected history/snapshot/period | Committed evidence only | Own committed Run only | Credit evidence / supported timeline rows | Live Working Copy regime bound only to CURRENT Last Run; historical regime may be unavailable |
| Equity investment / shareholder-loan funded / distributions | `returns_projection` using sponsor summary explicit contribution/distribution fields | kEUR | Selected history/snapshot | When persisted | Own committed Run only | Sponsor panel and persisted schedules | Legal-equity distributions are not total sponsor cash flow |
| Sponsor net cash flow | `returns_projection` explicit unavailable metric | kEUR | Selected history/snapshot | Unavailable as scalar | Unavailable as scalar | Explicit unavailable | Not persisted by canonical sponsor schedule; no substitute from distributions |
| Sponsor and distribution period schedules | `returns_projection` passes through `sponsor_schedule.periods` / `distribution_schedule.periods` | Persisted column-specific units | Selected history/snapshot/period | When persisted | Own committed Run only | Evidence disclosure / existing historical statement links | No new waterfall engine |
| Contractual covenant / default / cash sweep | Existing Credit Decision classifications and unavailable reasons | Canonical status | Selected history/snapshot | Only genuine supported evidence | Own committed Run only | Findings / explicit unavailable states | No invented contractual thresholds or events |
| Historical status / integrity / version metadata | `run_history_projection`, `run_workspace_v3_projection`, Run History row, canonical runtime freshness | IDs/text/status | Exact stored identity | Immutable | Exact persisted scenario ID | History selector, provenance, comparison | Older Runs remain HISTORICAL; Working Copy STALE does not rewrite historical evidence |
| Comparison changes | `scenario_kpi_projection.build_compare_rows` | pp for rates, x for ratios, kEUR for amounts | Ordered explicitly selected Run columns | 1–3 supported Runs | Different committed scenarios or historical Runs | Canonical comparison table | Missing operands yield unavailable deltas; relative amount change requires approved positive base |

## Route and ownership boundaries

- `GET /v2/model-react/insights/history?project=...` lists the bounded canonical history and scenario commitment status.
- `GET /v2/model-react/insights?project=...&run=...` requires explicit selection; repeat `run` for comparison, at most three unique Runs.
- Both routes require authentication, project access and non-protected working models. Foreign project/Run references fail closed. Unsupported identity parameters are rejected instead of ignored. Responses use `Cache-Control: private, no-store`.
- GET reads do not Save, Clone, Run, select a scenario or alter workspace/history persistence. There is no analytics POST mutation route.
- Existing historical statement/detail links remain bound to the same history ID. No tokens are exposed in analytical evidence.
- Components live under `frontend/src/app/insights/`. Shared shell integration and the combined React bundle depend on forward integration with WF-React-2 / PR #378. Independent components and JSON availability do not imply the served React navigation is integrated.

## Validation and integration scope

`tests/test_model_react_insights_v1.py` creates real Solar and Wind working copies from existing local reference fixture authority, executes the existing canonical local Run workflow, and reads actual isolated SQLite history. It asserts exact same-Run/snapshot/period values against persisted fields and canonical projections, including source-defined display formatting, unavailable values, convergence versus feasibility, Sponsor versus Pure Equity definitions, historical immutability, explicit selection limits, ownership and complete logical database snapshots around GETs. No new financial tolerances or protected golden changes are used. Browser geometry, monetary display, responsive usability and served-shell exposure require separate browser evidence.

Shared-shell navigation, scenario override editing and release acceptance are outside this isolated package. No feature is claimed user-visible before forward integration with #378 and independent acceptance.

## Reproducible local validation

```sh
python -m pytest tests/test_model_react_insights_v1.py
npm --prefix frontend run typecheck
node frontend/src/app/insights/__tests__/insights.test.mjs
python tests/browser/react_insights_acceptance.py --output /tmp/wf-react-3-proof
```

The explicit browser script requires Chromium/Playwright and fails if they are
unavailable; it is not a collection-skipped pytest module. It creates isolated
local SQLite Solar/Wind histories through existing canonical fixture authority,
serves the real read-only API, builds components into a temporary harness, and
checks exact approved display rounding, persisted numerical chart geometry,
keyboard interaction, comparison deltas, responsive layout and unchanged DB
state. No shared bundle is regenerated or activated by this harness.

The API router is composed through `react_poc_router.py` before its project-page
catch-all. The exact-content Run/Clone router, security pins, existing financial
projection implementations and shared editor files remain unchanged.
