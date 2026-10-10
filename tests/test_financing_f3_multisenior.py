"""Independent facility recomputation and real canonical multi-Senior runs."""
from dataclasses import asdict, replace
from datetime import timedelta
import json

import pytest

from app import project_factories as factories
from finco_core.inputs import SponsorFundingMode, DebtServiceReserveSupportMode, hash_inputs_for_cache, project_inputs_to_dict, project_inputs_from_dict
from finco_core.inputs.financing_instruments import (
    FinancingCollection, FinancingInstrument, InstrumentType, InterestTerms, RateMode,
    RepaymentTerms, RepaymentMode, MaturityAuthority, DrawdownEntry, FeeTerm, FeeKind, FinancingError,
)
from finco_core.inputs.multisenior import activate_collection, deactivate_collection
from financial_engine.financing.multisenior import build_facility_schedules


def case(kind="solar", *, mode=RepaymentMode.LEVEL_PRINCIPAL):
    from financial_engine.adapters.project_inputs import from_project_inputs
    from financial_engine.orchestrator import run_operating_model
    pi = getattr(factories, f"create_generic_{kind}_reference")()
    pi = replace(pi, financing=replace(pi.financing, sponsor_funding_mode=SponsorFundingMode.EQUITY_ONLY,
        dsra_support_mode=DebtServiceReserveSupportMode.NONE, dsra_months=0, debt_service_reserve_requirement_keur=0.))
    periods = run_operating_model(from_project_inputs(pi)).periods
    op = [p for p in periods if p.is_operation]
    construction = [p for p in periods if p.is_construction]
    # Independently specified facility fractions, not a desired output or sizing anchor.
    a = pi.capex.hard_capex_keur * .06
    b = pi.capex.hard_capex_keur * .04
    first = construction[0].period_start
    later = construction[1 if len(construction) > 1 else 0].period_start + timedelta(days=1)
    instruments = tuple(FinancingInstrument(instrument_id=identity, instrument_type=InstrumentType.SENIOR_TERM_LOAN,
        name=name, commitment_keur=amount, drawdowns=(DrawdownEntry(draw, amount),),
        interest=InterestTerms(RateMode.FIXED, fixed_rate=rate),
        repayment=RepaymentTerms(mode, grace_months=grace, maturity_authority=MaturityAuthority.EXPLICIT_DATE,
            maturity_date=op[maturity - 1].period_end),
        fees=(FeeTerm(FeeKind.UPFRONT, .01), FeeTerm(FeeKind.COMMITMENT, .005, "UNDRAWN")))
        for identity, name, amount, draw, rate, grace, maturity in (
            ("senior-a", "Senior A", a, first, .04, 0, 16),
            ("senior-b", "Senior B", b, later, .07, 12, 20)))
    return activate_collection(pi, FinancingCollection(instruments)), periods


@pytest.mark.parametrize("kind", ["solar", "wind", "data_center", "ev_charging"])
def test_activation_roundtrip_and_absence_preserve_exact_payload_and_hash(kind):
    active, _ = case(kind)
    original = deactivate_collection(active)
    payload = project_inputs_to_dict(original)
    key = hash_inputs_for_cache(original)
    assert "financing_activation" not in payload
    assert project_inputs_to_dict(deactivate_collection(active)) == payload
    assert hash_inputs_for_cache(deactivate_collection(active)) == key
    encoded = project_inputs_to_dict(active)
    restored = project_inputs_from_dict(json.loads(json.dumps(encoded)))
    assert restored == active
    assert hash_inputs_for_cache(restored) == hash_inputs_for_cache(active) != key


@pytest.mark.parametrize("kind", ["solar", "wind", "data_center", "ev_charging"])
def test_real_two_senior_canonical_run_balances_and_interest_handoff(kind, tmp_path):
    from app.services.production_financial_authority import run_clean_production
    from app.run_integrity import build_run_integrity_evidence, run_integrity_checks
    from financial_engine.financing.generic_product_policy import build_sources_and_uses
    pi, periods = case(kind)
    run = run_clean_production(pi)
    fin = run.g2c_result.financing_result
    assert len(fin.facility_schedules) == 2
    senior = fin.project_model_result.senior_debt
    for field, facility_field in (("senior_interest_keur", "interest_keur"),
        ("senior_principal_keur", "principal_keur"), ("senior_debt_closing_keur", "closing_keur")):
        maps = [dict(zip(f.period_indices, getattr(f, facility_field))) for f in fin.facility_schedules]
        for i, value in zip(senior.period_indices, getattr(senior, field)):
            assert value == pytest.approx(sum(m.get(i, 0.) for m in maps), abs=1e-9)
    report = run_integrity_checks(build_run_integrity_evidence(run)).to_dict()
    assert report["overall"] == "PASS", report
    assert build_sources_and_uses(fin).difference_keur == 0.
    assert senior.senior_debt_closing_keur[-1] == pytest.approx(0., abs=1e-9)
    interest = dict(zip(senior.period_indices, senior.senior_interest_keur))
    tax = fin.project_model_result.tax_and_cfads
    assert all(value == 0. for value in tax.shl_gross_interest_audit_keur)
    assert fin.project_model_result.shareholder_loan is None
    for row in run.financial_statements_result.income_statement_periods:
        if not row.is_construction:
            assert row.senior_interest_expense_keur == interest.get(row.period_index, 0.)
            assert row.shl_interest_expense_keur == 0.
    for year in tax.annual_results:
        # Calendar-tax-year splitting is owned by the tax engine; total interest
        # over the complete horizon must equal facility cash interest, once.
        assert year.disallowed_interest_keur >= 0.
    assert sum(y.total_interest_keur for y in tax.annual_results) == pytest.approx(sum(interest.values()), abs=1e-8)
    costs = sum(sum(f.construction_idc_keur) + sum(f.construction_commitment_fees_keur)
                + sum(f.upfront_fees_keur) for f in fin.facility_schedules)
    assert fin.project_uses.explicit_financing_cost_uses_keur == pytest.approx(costs, abs=1e-9)
    assert fin.project_uses.total_project_uses_keur == pytest.approx(pi.capex.hard_capex_keur + costs, abs=1e-9)
    (tmp_path / f"multi-{kind}.json").write_text(json.dumps(asdict(run), default=str), encoding="utf-8")


def test_independent_construction_and_operating_recomputation():
    pi, periods = case()
    facilities = build_facility_schedules(pi, periods)
    op = {p.period_index: p for p in periods if p.is_operation}
    denominator = 360 if pi.financing.senior_debt_interest_config.day_count.value == "act_360" else 365
    for instrument, facility in zip(pi.financing_collection.instruments, facilities):
        opening = instrument.commitment_keur
        from dateutil.relativedelta import relativedelta
        grace_end = min(p.period_start for p in op.values()) + relativedelta(months=instrument.repayment.grace_months)
        eligible_count = sum(p.period_start >= grace_end and p.period_end <= instrument.repayment.maturity_date for p in op.values())
        expected_principal = opening / eligible_count
        for i, actual_open, interest, principal, service, closing in zip(facility.period_indices,
                facility.opening_keur, facility.interest_keur, facility.principal_keur,
                facility.debt_service_keur, facility.closing_keur):
            assert actual_open == pytest.approx(opening, abs=1e-10)
            expected_interest = opening * instrument.interest.fixed_rate * (op[i].period_end - op[i].period_start).days / denominator
            assert interest == pytest.approx(expected_interest, abs=1e-10)
            if principal:
                assert principal == pytest.approx(expected_principal, abs=1e-10)
            assert service == pytest.approx(expected_interest + principal, abs=1e-10)
            assert (principal > 0) == (op[i].period_start >= grace_end)
            opening -= principal
            assert closing == pytest.approx(opening, abs=1e-10)
        draw = instrument.drawdowns[0]
        cod = min(p.period_start for p in periods if p.is_operation)
        expected_idc = draw.amount_keur * instrument.interest.fixed_rate * (cod - draw.draw_date).days / denominator
        assert sum(facility.construction_idc_keur) == pytest.approx(expected_idc, abs=1e-10)
        fc = min(p.period_start for p in periods if p.is_construction)
        expected_fee = instrument.commitment_keur * .005 * (draw.draw_date - fc).days / denominator
        assert sum(facility.construction_commitment_fees_keur) == pytest.approx(expected_fee, abs=1e-10)
        assert sum(facility.upfront_fees_keur) == instrument.commitment_keur * .01


def change_facility(pi, index=0, **terms):
    instruments = list(pi.financing_collection.instruments)
    instruments[index] = replace(instruments[index], **terms)
    return replace(pi, financing_collection=FinancingCollection(tuple(instruments)))


def test_multiple_dated_draws_accrue_independently_on_act_360():
    from finco_core.inputs.senior_rate_schedule import SeniorDayCountConvention
    pi, periods = case()
    pi = replace(pi, financing=replace(pi.financing, senior_debt_interest_config=replace(
        pi.financing.senior_debt_interest_config, day_count=SeniorDayCountConvention.ACT_360)))
    instrument = pi.financing_collection.instruments[0]
    first = instrument.drawdowns[0].draw_date
    entries = (DrawdownEntry(first, instrument.commitment_keur / 2),
               DrawdownEntry(first + timedelta(days=17), instrument.commitment_keur / 2))
    pi = change_facility(pi, drawdowns=entries)
    facility = build_facility_schedules(pi, periods)[0]
    cod = min(p.period_start for p in periods if p.is_operation)
    assert sum(facility.construction_idc_keur) == pytest.approx(
        sum(d.amount_keur * instrument.interest.fixed_rate * (cod - d.draw_date).days / 360 for d in entries), abs=1e-10)
    assert sum(facility.construction_commitment_fees_keur) == pytest.approx(
        sum(d.amount_keur * .005 * (d.draw_date - first).days / 360 for d in entries), abs=1e-10)


@pytest.mark.parametrize('invalid', ['authority', 'schema', 'extra_key', 'digest_shape'])
def test_active_serialization_cannot_silently_downgrade_to_legacy(invalid):
    pi, _ = case()
    payload = project_inputs_to_dict(pi)
    entry = payload['financing_activation']
    if invalid == 'authority':
        entry['authority'] = 'unknown'
    elif invalid == 'schema':
        entry['collection']['schema_version'] = 'future'
    elif invalid == 'extra_key':
        entry['unexpected'] = True
    else:
        entry['collection'] = []
    with pytest.raises((ValueError, TypeError)):
        project_inputs_from_dict(payload)


@pytest.mark.parametrize("kind", ["solar", "wind"])
def test_bullet_has_no_early_principal_and_no_fake_maturity_cash(kind):
    from app.services.production_financial_authority import run_clean_production
    pi, _ = case(kind, mode=RepaymentMode.BULLET)
    # Small contractual commitments, chosen independently of model outputs.
    for index, instrument in enumerate(pi.financing_collection.instruments):
        amount = instrument.commitment_keur / 100
        pi = change_facility(pi, index, commitment_keur=amount,
            drawdowns=(replace(instrument.drawdowns[0], amount_keur=amount),))
    result = run_clean_production(pi).g2c_result.financing_result
    for facility in result.facility_schedules:
        assert facility.principal_keur[:-1] == (0.,) * (len(facility.principal_keur) - 1)
        assert facility.principal_keur[-1] == facility.commitment_keur
        assert facility.closing_keur[-1] == 0.


@pytest.mark.parametrize("invalid", ["maturity", "grace", "draw_date", "draw_total", "rate_mode", "repayment", "fee", "rank"])
def test_unsupported_or_inconsistent_facility_terms_fail_closed(invalid):
    pi, periods = case()
    instrument = pi.financing_collection.instruments[0]
    with pytest.raises(FinancingError):
        if invalid == "maturity":
            pi = change_facility(pi, repayment=replace(instrument.repayment,
                maturity_date=instrument.repayment.maturity_date - timedelta(days=1)))
        elif invalid == "grace":
            pi = change_facility(pi, repayment=replace(instrument.repayment, grace_months=10000))
        elif invalid == "draw_date":
            pi = change_facility(pi, drawdowns=(replace(instrument.drawdowns[0],
                draw_date=instrument.drawdowns[0].draw_date - timedelta(days=1)),))
        elif invalid == "draw_total":
            pi = change_facility(pi, drawdowns=(replace(instrument.drawdowns[0], amount_keur=1.),))
        elif invalid == "rate_mode":
            pi = change_facility(pi, interest=InterestTerms(RateMode.PERIOD_SCHEDULE))
        elif invalid == "repayment":
            pi = change_facility(pi, repayment=replace(instrument.repayment, mode=RepaymentMode.DSCR_SCULPTED))
        elif invalid == "fee":
            pi = change_facility(pi, fees=(FeeTerm(FeeKind.AGENCY, .01),))
        else:
            pi = change_facility(pi, seniority_rank=2)
        build_facility_schedules(pi, periods)


def test_period_overfunding_rejected_instead_of_negative_equity_or_prefunding():
    from financial_engine.financing.multisenior import run_multisenior_financing
    pi, periods = case()
    last = max(p.period_start for p in periods if p.is_construction)
    instrument = pi.financing_collection.instruments[1]
    pi = change_facility(pi, 1, drawdowns=(replace(instrument.drawdowns[0], draw_date=last),))
    with pytest.raises(FinancingError, match="F3_PERIOD_OVERFUNDING"):
        run_multisenior_financing(pi)


def test_unfundable_bullet_at_maturity_fails_closed_without_returns():
    from financial_engine.financing.multisenior import run_multisenior_financing
    pi, periods = case(mode=RepaymentMode.BULLET)
    first = next(p.period_end for p in periods if p.is_operation)
    for index, instrument in enumerate(pi.financing_collection.instruments):
        pi = change_facility(pi, index, repayment=replace(instrument.repayment,
            maturity_date=first, grace_months=0))
    with pytest.raises(FinancingError, match="F3_CONTRACTUAL_SERVICE_CASH_SHORTFALL"):
        run_multisenior_financing(pi)


def test_gearing_cap_is_constraint_not_a_resizing_authority():
    from financial_engine.financing.multisenior import run_multisenior_financing
    pi, _ = case()
    pi = replace(pi, financing=replace(pi.financing, gearing_ratio=.01))
    with pytest.raises(FinancingError, match="F3_AGGREGATE_GEARING_CAP_EXCEEDED"):
        run_multisenior_financing(pi)


@pytest.mark.parametrize("conflict", ["shl", "reserve", "manual_fee", "other_equity", "developer"])
def test_competing_project_economic_authorities_rejected(conflict):
    from financial_engine.financing.multisenior import validate_project_boundary, run_multisenior_financing
    pi, _ = case()
    if conflict == "shl":
        pi = replace(pi, financing=replace(pi.financing, sponsor_funding_mode=SponsorFundingMode.SHARE_CAPITAL_THEN_SHL))
    elif conflict == "reserve":
        pi = replace(pi, financing=replace(pi.financing, dsra_months=6))
    elif conflict == "manual_fee":
        pi = replace(pi, capex=replace(pi.capex, bank_fees_keur=1.))
    elif conflict == "other_equity":
        pi = replace(pi, financing=replace(pi.financing, other_equity_funding_before_shl_keur=1.))
    else:
        from finco_core.inputs.development import DevelopmentEconomicsInput
        pi = replace(pi, development_economics=DevelopmentEconomicsInput())
    with pytest.raises(FinancingError):
        validate_project_boundary(pi)
        run_multisenior_financing(pi)
