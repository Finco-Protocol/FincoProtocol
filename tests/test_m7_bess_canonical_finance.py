"""Independent native BESS receipts/expenses through real canonical finance."""
from dataclasses import replace
from datetime import date
from decimal import Decimal
import json
import pytest


def candidate(monkeypatch):
    from app.workbook import bess_config
    from domain.bess.synthetic import example
    monkeypatch.setattr(bess_config, "ACTIVATION_ENABLED", True)
    p = bess_config.native_base_inputs()
    p = replace(p, info=replace(p.info, financial_close=date(2027, 1, 1), construction_months=12, cod_date=date(2028, 1, 1), horizon_years=2),
                capex=replace(p.capex, epc_contract=replace(p.capex.epc_contract, amount_keur=25),
                              production_units=replace(p.capex.production_units, amount_keur=5), epc_other=replace(p.capex.epc_other, amount_keur=5)),
                opex=(replace(p.opex[0], y1_amount_keur=1, annual_inflation=0),),
                financing=replace(p.financing, share_capital_keur=1, senior_tenor_years=2, gearing_ratio=.5, senior_debt_interest_config=None))
    from finco_core.engine.period_engine import PeriodEngine
    periods = tuple(q for q in PeriodEngine(p.info.financial_close, 12, 2, 0, cod_date=p.info.cod_date).periods() if q.is_operation)
    raw = {"version": 1, "configuration": example(periods[0].start_date.isoformat() + 'T00:00:00Z',
            periods[-1].end_date.isoformat() + 'T00:00:00Z'), "variable_om_eur_per_dc_mwh": 1}
    return bess_config.apply_config(p, json.dumps(raw)), raw


def test_gross_sales_and_all_purchases_feed_canonical_ebitda_and_tax(monkeypatch):
    from financial_engine.adapters.project_inputs import from_project_inputs
    from financial_engine.orchestrator import run_operating_model
    project, raw = candidate(monkeypatch)
    result = run_operating_model(from_project_inputs(project))
    for p in result.periods:
        if not p.is_operation:
            assert p.revenue_keur == p.opex_keur == 0
            continue
        days = Decimal((p.period_end - p.period_start).days)
        sales = days * Decimal('.081')
        variable_costs = days * (Decimal('.04') + Decimal('.0096') + Decimal('.00248') + Decimal('.00081') + Decimal('.0018'))
        fixed = Decimal(str(p.day_fraction))
        assert p.revenue_keur == pytest.approx(float(sales), abs=1e-10)
        assert p.opex_keur == pytest.approx(float(fixed + variable_costs), abs=1e-10)
        assert p.ebitda_keur == pytest.approx(p.revenue_keur - p.opex_keur, abs=1e-10)
        assert p.book_depreciation_keur > 0
    rows = [json.loads(v) for e in result.provenance.derivation_evidence if e.output_path.endswith('revenue_keur') for v in e.notes]
    assert len(rows) == 4
    assert sum(int(r['hours']) for r in rows) == sum((p.period_end - p.period_start).days * 24 for p in result.periods if p.is_operation)
    assert max(Decimal(r['max_energy_residual_mwh']) for r in rows) == 0


def test_real_g2c_statements_debt_tax_and_returns_are_not_a_second_engine(monkeypatch):
    from app.services.production_financial_authority import run_clean_production
    p, raw = candidate(monkeypatch)
    clean = run_clean_production(p, project_type="Storage")
    assert clean.financial_statements_result is not None
    assert clean.authority_metadata['calculation_count'] == 1
    assert clean.g2c_result is not None
    fr = clean.g2c_result.financing_result
    model = fr.project_model_result
    assert fr.final_senior_commitment_keur > 0
    assert abs(fr.final_senior_commitment_keur + fr.share_capital_keur + fr.share_premium_keur
               + fr.other_equity_funding_before_shl_keur + fr.additional_equity_keur
               - fr.project_uses.total_project_uses_keur) <= 1e-7
    for ebitda, tax, cfads in zip(model.operating_schedules.ebitda_keur,
            model.tax_and_cfads.corporate_tax_cash_keur, model.tax_and_cfads.cfads_keur, strict=True):
        assert Decimal(str(ebitda)) - Decimal(str(tax)) == pytest.approx(Decimal(str(cfads)), abs=Decimal('1e-10'))
    fs = clean.financial_statements_result
    assert fs.balance_sheet_status.value == 'OK'
    operating_indices = {row.period_index for row in model.periods if row.is_operation}
    for row in fs.balance_sheet_periods:
        if row.period_index in operating_indices:
            assert row.balance_check_keur is not None and abs(row.balance_check_keur) <= 1e-7
        else:
            assert row.balance_check_keur is None  # Existing statement authority is COD/operating-only.
    assert clean.g2c_result.pure_equity_xirr is not None
    assert clean.g2c_result.total_sponsor_xirr is not None
    assert clean.g2c_result.return_summary.project.project_xirr is not None
    from app.run_integrity import build_run_integrity_evidence, run_integrity_checks, evidence_digest
    from copy import deepcopy
    evidence = build_run_integrity_evidence(clean)
    assert run_integrity_checks(evidence).overall.value == 'PASS'
    for fault in ('missing-equity', 'altered-equity', 'altered-irr', 'missing-return-authority'):
        bad = deepcopy(evidence)
        row = next(r for r in bad['balance_sheet'] if r['period_index'] in operating_indices)
        if fault == 'missing-equity': row.pop('additional_equity')
        elif fault == 'altered-equity': row['additional_equity'] += 1
        elif fault == 'altered-irr': bad['sponsor']['reported']['pure_equity_xirr'] += .01
        else: bad.pop('return_calculation_authority')
        bad['digest'] = evidence_digest(bad)
        assert run_integrity_checks(bad).overall.value != 'PASS'


def test_zero_dispatch_zero_revenue_has_no_manufactured_return(monkeypatch):
    from app.workbook.bess_config import apply_config
    from app.services.production_financial_authority import run_clean_production, CleanProductionRunUnavailable
    from financial_engine.adapters.project_inputs import from_project_inputs
    from financial_engine.orchestrator import run_operating_model
    p, raw = candidate(monkeypatch)
    for hour in raw['configuration']['dispatch']:
        hour['charge_mw'] = hour['discharge_mw'] = hour['auxiliary_grid_mw'] = 0
    p = replace(p, opex=())
    p = apply_config(p, json.dumps(raw))
    model = run_operating_model(from_project_inputs(p))
    assert not any(model.operating_schedules.production_mwh)
    assert not any(model.operating_schedules.revenue_keur)
    assert not any(model.operating_schedules.opex_keur)
    # Existing canonical financing refuses a no-debt-capacity result; no fake
    # successful financial Run/IRR is manufactured to bypass that authority.
    with pytest.raises(CleanProductionRunUnavailable, match='NO_DEBT_CAPACITY'):
        run_clean_production(p, project_type='Storage')


@pytest.mark.parametrize('fault', ['release', 'augmentation', 'inventory', 'hybrid', 'missing-hour', 'axis'])
def test_invalid_native_contract_fails_before_canonical_run(monkeypatch, fault):
    from app.workbook import bess_config
    p, raw = candidate(monkeypatch)
    if fault == 'release': monkeypatch.setattr(bess_config, 'ACTIVATION_ENABLED', False)
    elif fault == 'augmentation':
        from tests.test_m7_bess_physics import event
        raw['configuration']['events'] = [event()]
    elif fault == 'inventory': raw['configuration']['battery']['terminal_energy_mwh'] = .1
    elif fault == 'hybrid': p = replace(p, technical=replace(p.technical, operating_hours_p50=1))
    elif fault == 'missing-hour': raw['configuration']['dispatch'].pop()
    elif fault == 'axis': raw['configuration']['end'] = '2029-01-01T00:00:00Z'
    with pytest.raises(ValueError): bess_config.apply_config(p, json.dumps(raw))
