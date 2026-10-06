# Model V2 Canonical Analytics — Contract (Workflow 06)

Status: run-bound, read-only productization of canonical outputs. Exact-path
authorized under `docs/model_v2/ACTIVE_EPIC_SCOPE.json`. Branch
`feat/model-v2-canonical-analytics` → `epic/model-saas-v2`. No engine,
persistence, Workflow 05B Revenue Runtime, or frozen-namespace code is
touched; `domain/analytics/**` remains frozen.

## What it is

`app/model_v2/canonical_analytics.py` exposes ONE typed snapshot —
`CanonicalAnalyticsSnapshot` — of the canonical outputs a successful clean
production run already calculated. Values are verbatim pass-throughs of the
Workflow 04 Calculation Trace (which itself passes the canonical G2C result
through verbatim) plus two direct G2C pass-throughs (MOIC pair). Analytics
answers "what is the canonical value/status/unit?"; Calculation Trace
answers "where did that value come from?".

## Status semantics

`CanonicalMetricStatus` (token spellings follow run-integrity):

- `AVAILABLE` — canonical value present; `value` is the verbatim authority
  value (a legitimate economic 0.0 stays `AVAILABLE 0.0`);
- `UNAVAILABLE` — authority exists but the canonical run statused the value
  unavailable; `value` is `None` and the engine status travels verbatim in
  `source_status` (e.g. `COVERAGE_CFADS_CASE_NOT_CONFIGURED`);
- `NOT_APPLICABLE` — the canonical authority itself statused the metric
  not-applicable for this run (source status contains `NOT_APPLICABLE`);
  distinct from UNAVAILABLE, never zero;
- `AUTHORITY_MISSING` — FINCO has no canonical authority for the metric at
  all (reserved future ids); `value` is `None`, `source_authority` is None.

MISSING ≠ ZERO and UNAVAILABLE ≠ ZERO are structural: deserialization
rejects any metric carrying a value with a non-AVAILABLE status, and any
AVAILABLE metric without a value.

## Run-bound semantics

A snapshot requires a complete Workflow 04 `RunIdentity` (snapshot id,
composite hash, workbook + engine versions, optional project/scenario ids)
— no alternative identity is invented. A supplied Calculation Trace must be
RUN_BOUND and carry the identical identity
(`ANALYTICS_TRACE_CONTEXT_MISMATCH` / `ANALYTICS_TRACE_IDENTITY_MISMATCH`
otherwise). Working Copy edits after a run never rewrite a historical
snapshot (immutable content). A failed run raises before any snapshot can
exist, so it cannot replace a prior successful snapshot.

## Authority matrix (active metrics)

| metric_id | canonical source | unit | status behavior | trace_ref | supported |
|---|---|---|---|---|---|
| project_xirr | G2C `return_summary.project.project_xirr` (via trace) | fraction | AVAILABLE or UNAVAILABLE (`project_xirr_status`) | project_xirr | yes |
| pure_equity_xirr | G2C `pure_equity_xirr` (via trace) | fraction | AVAILABLE / UNAVAILABLE (`pure_equity_xirr_status`) | pure_equity_xirr | yes |
| pure_equity_moic | G2C `pure_equity_moic` | multiple | AVAILABLE / UNAVAILABLE (`pure_equity_moic_status`) | — | yes |
| total_sponsor_xirr | G2C `total_sponsor_xirr` (via trace) | fraction | AVAILABLE / UNAVAILABLE | total_sponsor_xirr | yes |
| total_sponsor_moic | G2C `total_sponsor_moic` | multiple | AVAILABLE / UNAVAILABLE (`total_sponsor_moic_status`) | — | yes |
| project_npv_keur | G2C `valuation_summary.project_npv.npv_keur` (via trace) | kEUR | AVAILABLE / UNAVAILABLE (`NOT_CONFIGURED` on references) | project_npv_keur | yes |
| senior_debt_keur | G2C `financing_result.final_senior_commitment_keur` (via trace) | kEUR | AVAILABLE on production references | senior_debt_keur | yes |
| min_dscr | canonical presentation aggregation of `senior_debt.base_dscr` (via trace; the adapter computes it — analytics does not) | ratio | AVAILABLE on references | min_dscr | yes |
| min_llcr | G2C `valuation_summary.lender_coverage.llcr.ratio` (via trace) | ratio | UNAVAILABLE on references (`COVERAGE_CFADS_CASE_NOT_CONFIGURED`); `NOT_APPLICABLE_NO_SENIOR` maps to NOT_APPLICABLE | min_llcr | yes |
| min_plcr | G2C `valuation_summary.lender_coverage.plcr.ratio` (via trace) | ratio | as llcr | min_plcr | yes |
| total_revenue_keur | canonical presentation aggregation (via trace) | kEUR | AVAILABLE on references | total_revenue_keur | yes |
| total_opex_keur | canonical presentation aggregation (via trace) | kEUR | AVAILABLE on references | total_opex_keur | yes |
| total_ebitda_keur | canonical presentation aggregation (via trace) | kEUR | AVAILABLE on references | total_ebitda_keur | yes |
| total_tax_keur | canonical presentation aggregation of cash tax (via trace) | kEUR | AVAILABLE on references | total_tax_keur | yes |

## Intentionally unsupported today (AUTHORITY_MISSING, reserved ids)

| metric_id | unit | why |
|---|---|---|
| lcoe | EUR/MWh | no canonical production authority: `domain/analytics/lcoe.py` is a frozen orphaned extra (no production caller; its component helper is dead code) and `domain/analytics/scenarios.py` carries only a private presentation variant. Creating the formula here is forbidden; a reviewed canonical-authority decision is the future seam. |
| wacc | fraction | no canonical authority anywhere in the repository. |
| payback | years | only an ad-hoc private IC-report helper exists (`app/services/ic_report_service.py::_calc_payback`); not a canonical authority. |
| discounted_payback | years | no authority. |
| cash_yield | fraction | no authority. |

## No-recompute rule

The production layer contains no arithmetic on financial values and no
engine execution (structural AST test asserts zero banned calls, zero
`+ - * / **` operators and no `app.services` / `financial_engine` imports).
Aggregated headline totals come from the canonical read-only presentation
adapter via the Workflow 04 trace — never re-summed here.

## Determinism

Same canonical run → byte-identical serialized snapshot. The fingerprint is
a content-integrity helper recomputed from document content (an externally
comparable digest — never a run authority, never an embedded verification
field), mirroring the Workflow 04 principle. No timestamps enter the
economic content.
