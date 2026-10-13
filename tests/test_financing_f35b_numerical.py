"""Independent dated funding/fee and both-facility amortization acceptance."""
from dataclasses import replace
from datetime import timedelta
from decimal import Decimal
from math import fsum

import pytest

from app.services.production_financial_authority import run_clean_production
from finco_core.inputs.financing_instruments import DrawdownEntry, FinancingCollection, RepaymentMode
from tests.test_financing_f3_junior_contract import case


@pytest.mark.parametrize("kind", ["solar", "wind"])
@pytest.mark.parametrize("day_count", ["act_360", "act_365"])
@pytest.mark.parametrize("mode", [RepaymentMode.LEVEL_PRINCIPAL, RepaymentMode.BULLET])
def test_staggered_draws_both_facilities_and_fees_reconcile(kind, day_count, mode, record_property):
    pi, periods = case(kind, day_count=day_count)
    construction = [p for p in periods if p.is_construction]
    facilities = tuple(replace(i, drawdowns=(
        DrawdownEntry(construction[0].period_start + timedelta(days=3), i.commitment_keur * .4),
        DrawdownEntry(construction[1].period_start + timedelta(days=5), i.commitment_keur * .6)),
        repayment=replace(i.repayment, mode=mode, grace_months=0)) for i in pi.financing_collection.instruments)
    pi = replace(pi, financing_collection=FinancingCollection(facilities))
    result = run_clean_production(pi)
    fin = result.g2c_result.financing_result
    op = {p.period_index: p for p in fin.project_model_result.periods if p.is_operation}
    cod = min(p.period_start for p in op.values())
    dec = lambda value: Decimal(str(value))
    residuals = []

    def equal(actual, expected, tolerance=1e-9):
        residuals.append(abs(float(dec(actual) - expected)))
        assert actual == pytest.approx(float(expected), abs=tolerance, rel=0)

    expected_costs = Decimal(0)
    start = construction[0].period_start
    for instrument, schedule in zip(facilities, (fin.senior_facility, fin.junior_facility)):
        dc = day_count if instrument.seniority_rank == 2 else pi.financing.senior_debt_interest_config.day_count.value
        denominator = Decimal(360 if dc == "act_360" else 365)
        commitment = dec(instrument.commitment_keur)
        rate = dec(instrument.interest.fixed_rate)
        idc = sum((dec(d.amount_keur) * rate * Decimal((cod - d.draw_date).days) / denominator
                   for d in instrument.drawdowns), Decimal(0))
        equal(fsum(schedule.construction_draws_keur), commitment)
        equal(fsum(schedule.construction_idc_keur), idc)
        fee_rate = next((dec(f.rate) for f in instrument.fees if f.kind == "COMMITMENT"), Decimal(0))
        # Undrawn cash exposure integrates each contractual draw date, not a
        # recomputation from the runtime's fee vector.
        commitment_fee = fee_rate * sum((dec(d.amount_keur) * Decimal((d.draw_date - start).days) / denominator
                                        for d in instrument.drawdowns), Decimal(0))
        upfront = commitment * sum((dec(f.rate) for f in instrument.fees if f.kind == "UPFRONT"), Decimal(0))
        equal(fsum(schedule.construction_commitment_fees_keur), commitment_fee)
        equal(fsum(schedule.upfront_fees_keur), upfront)
        expected_costs += idc + commitment_fee + upfront
        opening = commitment
        installment = commitment / Decimal(len(schedule.period_indices))
        for index, actual_open, interest, principal, closing, service in zip(
                schedule.period_indices, schedule.opening_keur, schedule.interest_keur,
                schedule.principal_keur, schedule.closing_keur, schedule.debt_service_keur):
            p = op[index]
            expected_interest = opening * rate * Decimal((p.period_end - p.period_start).days) / denominator
            expected_principal = (commitment if index == schedule.maturity_period_index else Decimal(0)) if mode is RepaymentMode.BULLET else installment
            equal(actual_open, opening)
            equal(interest, expected_interest)
            equal(principal, expected_principal)
            equal(service, expected_interest + expected_principal)
            opening -= expected_principal
            equal(closing, opening)
        equal(schedule.closing_keur[-1], Decimal(0))
    equal(fin.project_uses.total_project_uses_keur, dec(pi.capex.hard_capex_keur) + expected_costs, 1e-7)
    equal(fin.construction_funding.total_audit_residual_keur, Decimal(0), 1e-7)
    for p in result.g2c_result.waterfall_periods:
        equal(p.signed_post_junior_keur, dec(p.signed_post_senior_keur) - dec(p.junior_interest_keur) - dec(p.junior_principal_keur))
        if not p.is_construction:
            assert p.signed_post_junior_keur >= -1e-7
    from app.run_integrity import build_run_integrity_evidence, run_integrity_checks
    assert run_integrity_checks(build_run_integrity_evidence(result)).to_dict()["overall"] == "PASS"
    record_property("maximum_actual_residual_keur", max(residuals))
