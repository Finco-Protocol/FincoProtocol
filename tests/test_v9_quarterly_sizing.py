"""Execute the existing sizing-sensitive quarterly case without assuming equal financing costs."""
from datetime import date
from decimal import Decimal

import rc7c_frequency_reconciliation as rec
from financial_engine.adapters.project_inputs import from_project_inputs
from tests.test_rc7b_quarterly_funding_statements import FUNDING_TOL, OPERATING_TOL


def test_solar_eight_year_sizing_depreciation_uses_each_frequency_actual_basis():
    case = rec.Case("solar", date(2031, 3, 31), tenor=8)
    runs = {}
    for frequency, policy in (("S", None), ("Q", rec.V2)):
        pi, run = rec.run(case, frequency, policy)
        financing = run.g2c_result.financing_result
        runs[frequency] = financing
        rows = (rec.six_month_rows(pi.info, int(pi.revenue.ppa_term_years)) if frequency == "S"
                else rec.oracle.operating_rows(pi.info, int(pi.revenue.ppa_term_years)))
        dep = from_project_inputs(pi).depreciation
        expected = rec.oracle.depreciation(financing.book_depreciable_asset_basis.components,
            dep.financial_cost_useful_life_years, pi.info.horizon_years, rows)
        actual = [p for p in financing.project_model_result.periods if p.is_operation]
        assert len(actual) == len(expected)
        for period, value in zip(actual, expected, strict=True):
            assert abs(Decimal(repr(period.book_depreciation_keur)) - value) <= OPERATING_TOL
    semi, quarter = runs["S"], runs["Q"]
    assert semi.final_senior_commitment_keur != quarter.final_senior_commitment_keur
    uses_delta = Decimal(repr(quarter.project_uses.total_project_uses_keur)) - Decimal(repr(semi.project_uses.total_project_uses_keur))
    costs_delta = Decimal(repr(quarter.project_uses.explicit_financing_cost_uses_keur)) - Decimal(repr(semi.project_uses.explicit_financing_cost_uses_keur))
    assert abs(uses_delta - costs_delta) <= Decimal(repr(FUNDING_TOL))
