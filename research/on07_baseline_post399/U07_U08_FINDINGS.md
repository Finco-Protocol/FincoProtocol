# ON07_UNVERIFIED_ASSUMPTIONS re-check on main db504f6 (labels: CONFIRMED / CHANGED_SINCE_ON07 / NOT_REPRODUCED / NOT_TESTED)
Method: one-input-at-a-time probes through `ProjectInputsSchema -> build_projectinputs -> run_project` (v1 path, 22 fields, `ON07_V1_API_BINDING_PROBE.csv`), plus the workbook route for the four fixtures (`ON07_FIXTURE_BINDING_AUDIT.csv`). No source modified.
| ID | Claim | Label | Evidence (executed unless noted) |
|---|---|---|---|
| U-05 | Contractual DSCR / covenant not available until #399 | **CHANGED_SINCE_ON07** | #399 merged (`db504f6`): registry fields `debt.contract.min_dscr_eod`, `debt.contract.contractual_dscr`, `app/workbook/dscr_contract_terms.py`; evaluator executed on real captures (WF04_VERIFICATION.md) |
| U-06 | #400 unmerged | CONFIRMED (still Draft `21d3ad8f`) | GitHub, 2026-10-30 |
| U-07 | v1 `revenue.degradation_pct` silently dropped | **CONFIRMED** | `_schema_to_dict` omits it; ProjectInputs == baseline and all KPIs identical at 3.0%; `_set_technical_degradation` has 0 call sites (grep app/financial_engine/tests) |
| U-08 | v1 `opex.inflation_pct` silently dropped; single-line hardcoded 2% | **CONFIRMED** | same probe at 8%; `_set_opex_inflation` 0 call sites; all OPEX `annual_inflation=0.02` |
| U-09 | v1 P50 override re-derives P90=0.9·P50, P99=0.8·P50 | **CONFIRMED** | factory Solar 1500/1400/None; `p50_hours=1500` alone -> 1500/1350/1200 and KPIs change. On the workbook route with explicit P90 the effective P90 reads back 1350/1305/2970 (MATCH) and P99 = P50·0.8 as stated |
| U-10 | currency display-only | CONFIRMED (registry `binding_status=PARTIAL`) | registry read |
| U-11 | no seasonality input | **PARTIALLY_REPRODUCED** | no production seasonality input found; `app/model_opex/profiles_candidate.py` mentions seasonality (candidate OPEX module; wiring NOT_TESTED). Fixtures keep it EXCLUDED |
| U-12 | no working-capital/dividend-policy inputs | CONFIRMED (grep) | only a reporting stub `change_in_working_capital_keur=0.0` |
| U-13 | CAPEX composition engine-derived from total | **CHANGED/EXTENDED** | resolver rescales to the snapshot total BEFORE the Run-route fold; the fold then replaces CAPEX/OPEX with seeded sub-lines (see NEW below) |
| NEW-1 | Run-route sub-line fold overrides snapshot CAPEX/OPEX totals | **CONFIRMED (new)** | SOL-01 effective CAPEX 30,937.5 vs intended 45,600; OPEX 356.25 vs 760 (all 4 fixtures, ON07_FIXTURE_BINDING_AUDIT.csv) |
| NEW-2 | other v1 API fields accepted but unbound | CONFIRMED | `revenue.ppa_term_years`, `debt.senior_debt_keur`, `project_name` (no KPI effect); `country_iso` bound with no KPI effect |
| NEW-3 | v1 `gearing_pct`/`capex` overrides can fail closed on factory Solar | CONFIRMED | `SHL_MATURITY_RESIDUAL_FAILS_CLOSED` (REFUSED_FAIL_CLOSED rows in the probe CSV) |
## Recommended minimal corrections (later PR; none made here)
1. `app/input_adapter.py` `_schema_to_dict` + `_resolve_user_inputs`: pass `degradation_pct`, `inflation_pct` (%->fraction) to the existing setters, or make `app/input_schema.py` reject them until bound (fail closed, not accept-and-drop). Same for `ppa_term_years`, `senior_debt_keur`.
2. `input_adapter.py:758-760`: do not overwrite factory P90/P99 when P50 is supplied unchanged; surface derived values in `messages`.
3. Surface effective CAPEX/OPEX totals (post-fold) next to the entered totals in the workbook UI/Run payload, or reject a grid total that the fold will replace.
4. Regression test per field: one-input change => model input differs AND a KPI differs (`tests/test_input_binding_closure.py`, new).
