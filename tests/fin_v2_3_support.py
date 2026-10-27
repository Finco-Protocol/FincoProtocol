"""Synthetic configured policies and isolated schedule fixtures, never defaults."""
import json


def config_json(case="BASE", periodic=False, timing="ABSOLUTE_INDEX", rate=5.5):
    common = {"authority_label": "FINANCIAL_OWNER:synthetic acceptance fixture",
              "discount_convention": "PERIODIC_COMPOUNDING" if periodic else "ACT_365_FIXED"}
    periodic_policy = ({"periodic_rate_conversion": "AS_QUOTED_PER_MODEL_PERIOD",
                        "periods_per_year": 2, "first_cashflow_timing": "END_OF_FIRST_PERIOD"} if periodic else {})
    return json.dumps({"schema_version": "FIN_V2_3_POLICY_V1", "rate_unit": "human_percent_v1",
        "shl_timing_basis": timing,
        "project": {**common, **periodic_policy, "discount_rate_pct": 8.0,
                    "valuation_date_policy": "FIRST_PROJECT_CASHFLOW_DATE", "explicit_valuation_date": None},
        "coverage": {**common, **periodic_policy, "discount_rate_pct": rate, "cfads_case": case,
                     "calculation_date_policy": "FIRST_SENIOR_PERIOD_OPENING",
                     "llcr_cashflow_basis": "RAW_SELECTED_CFADS", "plcr_cashflow_basis": "RAW_SELECTED_CFADS",
                     "denominator_basis": "SENIOR_OPENING_BALANCE", "rolling_loan_life": "ACTUAL_REPAYMENT"},
        "sponsor": {"authority_label": common["authority_label"], "discount_convention": "ACT_365_FIXED",
                    "discount_rate_pct": 12.0, "valuation_date_policy": "FINANCIAL_CLOSE",
                    "explicit_valuation_date": None}})


def isolated_debt_contract(clean_run):
    """Test-only canonical schedule fixture until FIN-V2-2 is integrated.

    Not a production maturity authority. The actual FIN-V2-2 module must be
    tested in the combined RC. Boundaries use its documented V1 wire schema.
    """
    g = clean_run.g2c_result
    m = g.financing_result.project_model_result
    s = m.senior_debt
    by_index = {p.period_index: p for p in m.periods}
    candidates = [i for i, b in zip(s.period_indices, s.senior_debt_opening_keur) if b > 1e-4]
    actual = candidates[-1]
    maturity = g.return_summary.terminal.senior.contractual_maturity_period_index
    return {"schema_version": "SENIOR_DEBT_EVIDENCE_V1", "status": "RECORDED", "llcr_inputs": {
        "loan_life_end_candidates": {"contractual_maturity_period_index": maturity,
             "contractual_maturity_date": by_index[maturity].period_end.isoformat(),
             "actual_payoff_period_index": actual, "actual_payoff_date": by_index[actual].period_end.isoformat()}}}
