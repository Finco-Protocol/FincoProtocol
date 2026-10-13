"""Independent Decimal oracles and canonical financial composition acceptance."""
from dataclasses import replace
from decimal import Decimal, localcontext
from math import fsum

import pytest

from app.services.production_financial_authority import run_clean_production
from finco_core.inputs.financing_instruments import FinancingCollection, FinancingError, RepaymentMode
from financial_engine.financing.junior_debt import contractual_schedules, run_junior_financing
from tests.test_financing_f3_junior_contract import case


@pytest.mark.parametrize("kind", ["solar", "wind", "data_center", "ev_charging"])
def test_canonical_junior_financial_statements_and_cash(kind):
    pi, _ = case(kind)
    run = run_clean_production(pi)
    fin = run.g2c_result.financing_result
    j = fin.junior_facility
    assert fin.junior_or_other_main_project_funding_keur == j.commitment_keur
    assert fin.construction_funding.total_audit_residual_keur == pytest.approx(0., abs=1e-7)
    assert fin.project_uses.total_project_uses_keur == pytest.approx(
        pi.capex.hard_capex_keur + fin.construction_financing.total_capitalized_financing_keur, abs=1e-7)
    expected = {i: (it, pr, cl) for i, it, pr, cl in zip(j.period_indices, j.interest_keur, j.principal_keur, j.closing_keur)}
    statements = run.financial_statements_result
    assert statements.income_statement_status.value == "OK"
    assert statements.balance_sheet_status.value == "OK"
    from app.run_integrity import build_run_integrity_evidence, run_integrity_checks
    report = run_integrity_checks(build_run_integrity_evidence(run)).to_dict()
    assert report["overall"] == "PASS", report
    for row in statements.income_statement_periods:
        it, _, _ = expected.get(row.period_index, (0., 0., 0.))
        assert row.junior_interest_expense_keur == it
        assert row.net_financial_result_keur == pytest.approx(
            row.financing_income_keur - row.senior_interest_expense_keur - it, abs=1e-9)
    for row in statements.balance_sheet_periods:
        _, _, cl = expected.get(row.period_index, (0., 0., 0.))
        assert row.junior_debt_balance_keur == cl
        if row.balance_check_keur is not None:
            assert row.balance_check_keur == pytest.approx(0., abs=1e-7)
    for row in run.g2c_result.waterfall_periods:
        assert row.signed_post_junior_keur == pytest.approx(
            row.signed_post_senior_keur - row.junior_interest_keur - row.junior_principal_keur, abs=1e-9)
        assert row.distribution_account_inflow_keur == pytest.approx(row.signed_post_junior_keur, abs=1e-9)
    tax = fin.project_model_result.tax_and_cfads
    assert fsum(y.total_interest_keur for y in tax.annual_results) == pytest.approx(
        fsum(j.interest_keur) + fsum(fin.senior_facility.interest_keur), abs=1e-8)
    assert run.g2c_result.return_summary.terminal.junior.status.value == "REPAID"


@pytest.mark.parametrize("kind", ["solar", "wind"])
def test_unlevered_project_return_independent_of_junior_financing(kind):
    pi, _ = case(kind)
    baseline = run_clean_production(pi)
    s, j = pi.financing_collection.instruments
    changed = replace(pi, financing_collection=FinancingCollection((s, replace(j,
        interest=replace(j.interest, fixed_rate=.12)))),
        junior_debt_policy=replace(pi.junior_debt_policy, idc_book_life_years=11))
    candidate = run_clean_production(changed)
    project = candidate.g2c_result.return_summary.project
    original = baseline.g2c_result.return_summary.project
    assert project.excluded_financing_cost_uses_keur == candidate.g2c_result.financing_result.project_uses.explicit_financing_cost_uses_keur
    assert replace(project, excluded_financing_cost_uses_keur=original.excluded_financing_cost_uses_keur) == original
    assert candidate.g2c_result.return_summary.legal_equity != baseline.g2c_result.return_summary.legal_equity


@pytest.mark.parametrize("tamper", ["digest", "cash", "life", "missing_period", "nonfinite"])
def test_funded_idc_tampering_rejected(tamper):
    from dataclasses import fields
    from finco_core.inputs.junior_debt import JuniorFundedCapex, JuniorCapitalizedCashInterest
    from financial_engine.financing.project_uses import compute_project_uses
    pi, _ = case()
    fin = run_junior_financing(pi)
    cfr = fin.construction_financing
    cost = cfr.junior_cash_idc
    if tamper == "cash":
        cost = JuniorCapitalizedCashInterest.from_funded_ledger(cost.instrument_id, cost.collection_digest,
            tuple(v + 1 for v in cost.capitalized_cash_by_period_keur), cost.book_life_years)
    elif tamper == "life":
        cost = JuniorCapitalizedCashInterest.from_funded_ledger(cost.instrument_id, cost.collection_digest,
            cost.capitalized_cash_by_period_keur, cost.book_life_years + 1)
    else:
        cost = replace(cost, **{"digest": {"evidence_digest": "0" * 64},
            "missing_period": {"capitalized_cash_by_period_keur": ()},
            "nonfinite": {"capitalized_cash_by_period_keur": (float("nan"),)}}[tamper])
    capex = JuniorFundedCapex(**{f.name: getattr(pi.capex, f.name) for f in fields(type(pi.capex))}, junior_cash_idc=cost)
    with pytest.raises(ValueError):
        compute_project_uses(replace(pi, capex=capex))


@pytest.mark.parametrize("conflict", ["shl", "reserve", "vat", "tax", "period", "idc_tax"])
def test_out_of_slice_economics_rejected(conflict):
    from finco_core.inputs import SponsorFundingMode, PeriodFrequency
    pi, _ = case()
    if conflict == "shl":
        pi = replace(pi, financing=replace(pi.financing, sponsor_funding_mode=SponsorFundingMode.SHARE_CAPITAL_THEN_SHL))
    elif conflict == "reserve":
        pi = replace(pi, financing=replace(pi.financing, dsrf_commitment_fee_rate_pa=.01))
    elif conflict == "vat":
        pi = replace(pi, capex=replace(pi.capex, vat_facility_idc_keur=1.))
    elif conflict == "tax":
        pi = replace(pi, tax=replace(pi.tax, atad_enabled=True))
    elif conflict == "period":
        pi = replace(pi, info=replace(pi.info, period_frequency=PeriodFrequency.ANNUAL))
    else:
        pi = replace(pi, junior_debt_policy=replace(pi.junior_debt_policy, idc_tax_treatment="BOOK_BASED_POLICY"))
    with pytest.raises(FinancingError):
        run_junior_financing(pi)


@pytest.mark.parametrize("kind", ["solar", "wind"])
@pytest.mark.parametrize("dc", ["act_360", "act_365"])
def test_decimal_dated_interest_idc_and_principal(kind, dc):
    pi, periods = case(kind, day_count=dc)
    senior, junior = contractual_schedules(pi, periods)
    instrument = next(i for i in pi.financing_collection.instruments if i.seniority_rank == 2)
    op = {p.period_index: p for p in periods if p.is_operation}
    denominator = Decimal(360 if dc == "act_360" else 365)
    opening = Decimal(str(instrument.commitment_keur))
    rate = Decimal(str(instrument.interest.fixed_rate))
    from dateutil.relativedelta import relativedelta
    grace_end = op[junior.period_indices[0]].period_start + relativedelta(months=instrument.repayment.grace_months)
    eligible = [i for i in junior.period_indices if op[i].period_start >= grace_end]
    installment = opening / Decimal(len(eligible))
    for idx, actual_open, it, pr, cl in zip(junior.period_indices, junior.opening_keur,
            junior.interest_keur, junior.principal_keur, junior.closing_keur):
        p = op[idx]
        expected = opening * rate * Decimal((p.period_end - p.period_start).days) / denominator
        assert actual_open == pytest.approx(float(opening), abs=1e-9)
        assert it == pytest.approx(float(expected), abs=1e-9)
        assert pr == pytest.approx(float(installment) if idx in eligible else 0., abs=1e-9)
        opening -= Decimal(str(pr))
        assert cl == pytest.approx(float(opening), abs=1e-9)
    cod = min(p.period_start for p in op.values())
    expected_idc = sum(Decimal(str(d.amount_keur)) * rate * Decimal((cod - d.draw_date).days)
                       / denominator for d in instrument.drawdowns)
    assert fsum(junior.construction_idc_keur) == pytest.approx(float(expected_idc), abs=1e-9)
    assert junior.closing_keur[-1] == pytest.approx(0., abs=1e-9)


def test_unfundable_junior_fails_without_manufactured_maturity_cash():
    pi, periods = case()
    s, j = pi.financing_collection.instruments
    first = next(p.period_end for p in periods if p.is_operation)
    j = replace(j, repayment=replace(j.repayment, mode=RepaymentMode.BULLET, grace_months=0, maturity_date=first))
    pi = replace(pi, financing_collection=FinancingCollection((s, j)))
    from app.services.production_financial_authority import CleanProductionRunUnavailable
    with pytest.raises(CleanProductionRunUnavailable, match="F35_CONTRACTUAL_SERVICE_CASH_SHORTFALL"):
        run_clean_production(pi)


def test_separate_total_debt_cap_is_not_senior_resizing():
    pi, _ = case(maximum_total_debt_gearing=.01)
    with pytest.raises(FinancingError, match="F35_TOTAL_DEBT_GEARING_CAP_EXCEEDED"):
        run_junior_financing(pi)


@pytest.mark.parametrize("kind", ["solar", "wind", "data_center", "ev_charging"])
@pytest.mark.parametrize("book_tax", [False, True])
def test_decimal_tax_cash_sponsor_and_book_basis(kind, book_tax):
    from finco_core.inputs import ASSET_CLASS_USEFUL_LIFE, AssetClass
    pi, _ = case(kind)
    pi = replace(pi, tax=replace(pi.tax, tax_dep_basis_source_owned=book_tax),
        junior_debt_policy=replace(pi.junior_debt_policy,
            idc_tax_treatment="BOOK_BASED_POLICY" if book_tax else "EXCLUDED_BY_EXISTING_POLICY"))
    run = run_clean_production(pi)
    fin = run.g2c_result.financing_result
    basis = fin.book_depreciable_asset_basis
    junior = [c for c in basis.components if c.code == "junior_cash_idc"]
    assert len(junior) == 1
    assert junior[0].useful_life_override == pi.junior_debt_policy.idc_book_life_years
    assert junior[0].amount_keur == fin.construction_financing.junior_cash_idc.amount_keur
    dec = lambda v: Decimal(str(v))
    for p in fin.project_model_result.periods:
        if not p.is_operation:
            continue
        annual = Decimal(0)
        annual_tax = Decimal(0)
        for c in basis.components:
            cls = AssetClass(c.asset_class_code)
            life = c.useful_life_override or (pi.financing.senior_tenor_years
                if cls is AssetClass.FINANCIAL_COSTS else ASSET_CLASS_USEFUL_LIFE.get(cls, 14))
            if p.year_index <= life:
                annual += dec(c.amount_keur) / dec(life)
                if book_tax or cls is not AssetClass.FINANCIAL_COSTS:
                    annual_tax += dec(c.amount_keur) / dec(life)
        assert p.book_depreciation_keur == pytest.approx(float(annual * dec(p.day_fraction)), abs=1e-9)
        assert p.tax_depreciation_keur == pytest.approx(float(annual_tax * dec(p.day_fraction)), abs=1e-9)
    for tax in fin.project_model_result.tax_and_cfads.annual_results:
        before = dec(tax.ebitda_keur) + dec(tax.financing_income_keur) - dec(tax.tax_depreciation_keur)
        before -= dec(tax.total_interest_keur)
        before += dec(tax.other_fiscal_reintegration_keur)
        assert tax.deductible_interest_keur == tax.total_interest_keur
        assert tax.taxable_income_before_lcf_keur == pytest.approx(float(before), abs=1e-9)
        after = max(Decimal(0), before - dec(tax.loss_used_keur))
        assert tax.current_tax_liability_keur == pytest.approx(float(after * dec(pi.tax.corporate_rate)), abs=1e-9)
    flows = run.g2c_result.waterfall_periods
    for p in flows:
        contributions = sum((dec(getattr(p, name)) for name in ("share_capital_contribution_keur",
            "share_premium_contribution_keur", "other_committed_equity_contribution_keur",
            "additional_equity_contribution_keur")), Decimal(0))
        expected = dec(p.legal_equity_distribution_keur) - contributions
        assert p.pure_equity_net_cashflow_keur == pytest.approx(float(expected), abs=1e-9)
        assert p.total_sponsor_net_cashflow_keur == p.pure_equity_net_cashflow_keur
    # Independent discounted cash recomputation, not the application's XIRR solver.
    with localcontext() as ctx:
        ctx.prec = 40
        rate = dec(run.g2c_result.pure_equity_xirr)
        origin = min(p.cashflow_date for p in flows)
        discounted = sum((dec(p.pure_equity_net_cashflow_keur) /
            ((Decimal(1) + rate).ln() * dec((p.cashflow_date - origin).days) / Decimal(365)).exp()
            for p in flows), Decimal(0))
    assert float(discounted) == pytest.approx(0., abs=1e-7)


def test_integrity_uses_actual_post_junior_cash_not_reconstructed_cash():
    from app.run_integrity import build_run_integrity_evidence, run_integrity_checks
    from app.run_integrity.evidence import evidence_digest
    pi, _ = case()
    run = run_clean_production(pi)
    rows = list(run.g2c_result.waterfall_periods)
    index = next(i for i, p in enumerate(rows) if not p.is_construction)
    rows[index] = replace(rows[index], signed_post_junior_keur=rows[index].signed_post_junior_keur + 1.)
    evidence = build_run_integrity_evidence(replace(run, g2c_result=replace(run.g2c_result, waterfall_periods=tuple(rows))))
    report = run_integrity_checks(evidence).to_dict()
    assert report["overall"] == "FAIL"
    del evidence["junior_debt"]
    evidence["digest"] = evidence_digest(evidence)
    assert run_integrity_checks(evidence).to_dict()["overall"] != "PASS"


@pytest.mark.parametrize("mode,grace", [(RepaymentMode.BULLET, 0), (RepaymentMode.LEVEL_PRINCIPAL, 12)])
def test_contractual_bullet_and_grace_are_actually_consumed(mode, grace):
    from dateutil.relativedelta import relativedelta
    pi, _ = case()
    if grace:
        from datetime import date
        from financial_engine.financing.generic_product_policy import derive_construction_financing
        pi = replace(pi, info=replace(pi.info, financial_close=date(2030, 10, 31), cod_date=date(2031, 12, 31)))
        construction = derive_construction_financing(pi)
        facilities = tuple(replace(i, drawdowns=(replace(i.drawdowns[0],
            draw_date=construction.periods[0].start_date),)) for i in pi.financing_collection.instruments)
        pi = replace(pi, financing_collection=FinancingCollection(facilities))
    s, j = pi.financing_collection.instruments
    j = replace(j, repayment=replace(j.repayment, mode=mode, grace_months=grace))
    run = run_clean_production(replace(pi, financing_collection=FinancingCollection((s, j))))
    fin = run.g2c_result.financing_result
    f = fin.junior_facility
    periods = {p.period_index: p for p in fin.project_model_result.periods if p.is_operation}
    grace_end = periods[f.period_indices[0]].period_start + relativedelta(months=grace)
    eligible = [i for i in f.period_indices if periods[i].period_start >= grace_end]
    for i, principal in zip(f.period_indices, f.principal_keur):
        expected = (j.commitment_keur if i == f.maturity_period_index else 0.) if mode is RepaymentMode.BULLET else (
            float(Decimal(str(j.commitment_keur)) / Decimal(len(eligible))) if i in eligible else 0.)
        assert principal == pytest.approx(expected, abs=1e-9)
    assert f.closing_keur[-1] == pytest.approx(0., abs=1e-9)


@pytest.mark.parametrize("grace", [1, 7, 999])
def test_grace_must_align_without_rounding(grace):
    pi, _ = case()
    s, j = pi.financing_collection.instruments
    j = replace(j, repayment=replace(j.repayment, grace_months=grace))
    with pytest.raises(FinancingError, match="F35_GRACE_NOT_ON_OPERATING_BOUNDARY"):
        run_junior_financing(replace(pi, financing_collection=FinancingCollection((s, j))))


def test_bullet_with_ambiguous_grace_rejected():
    pi, _ = case()
    s, j = pi.financing_collection.instruments
    j = replace(j, repayment=replace(j.repayment, mode=RepaymentMode.BULLET, grace_months=6))
    with pytest.raises(FinancingError, match="F35_BULLET_GRACE_CONFLICT"):
        replace(pi, financing_collection=FinancingCollection((s, j)))
