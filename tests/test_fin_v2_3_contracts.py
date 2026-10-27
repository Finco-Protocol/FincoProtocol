from dataclasses import replace
from datetime import date
import copy
import json

import pytest

from app.project_factories import create_generic_solar_reference, create_generic_wind_reference
from app.workbook.financial_core_config import apply_config, canonical_json, parse_config
from finco_core.inputs.serialization import project_inputs_from_dict, project_inputs_to_dict
from finco_core.inputs.shl_timing import ShlTimingBasis
from app.services.production_financial_authority import run_clean_production
from app.services.financial_core_evidence import build_financial_core_evidence, from_runtime_summary
from tests.fin_v2_3_support import config_json, isolated_debt_contract


@pytest.mark.parametrize('pct', [.056,.56,5.60,9.00])
def test_percentage_contract_is_single_conversion_and_round_trips(pct):
    raw=config_json(rate=pct)
    pi=apply_config(create_generic_solar_reference(),raw)
    assert pi.valuation.coverage.annual_discount_rate == pct/100
    assert project_inputs_from_dict(project_inputs_to_dict(pi)) == pi
    assert apply_config(create_generic_solar_reference(),canonical_json(raw)) == pi


@pytest.mark.parametrize('mutation', [
    lambda c:c.update(rate_unit='ratio'),
    lambda c:c.update(schema_version='unknown'),
    lambda c:c.update(shl_timing_basis='AUTO'),
    lambda c:c['coverage'].update(discount_rate_pct=True),
    lambda c:c['coverage'].update(discount_rate_pct=float('nan')),
    lambda c:c['coverage'].update(discount_rate_pct=-100),
    lambda c:c['coverage'].update(discount_rate_pct=1001),
    lambda c:c['coverage'].update(authority_label='RESEARCH_ONLY'),
    lambda c:c['project'].update(explicit_valuation_date='bad-date',valuation_date_policy='EXPLICIT_DATE'),
    lambda c:c['coverage'].update(discount_convention='CONTINUOUS'),
    lambda c:c['coverage'].update(unknown='surprise'),
])
def test_invalid_unit_authority_dates_rates_fail_closed(mutation):
    c=json.loads(config_json());mutation(c)
    with pytest.raises(ValueError):parse_config(json.dumps(c))


def test_duplicate_keys_and_historical_defaults():
    with pytest.raises(ValueError,match='DUPLICATE'):parse_config('{"rate_unit":1,"rate_unit":2}')
    pi=create_generic_solar_reference();encoded=project_inputs_to_dict(pi)
    assert 'shl_timing_basis' not in encoded['financing']
    assert project_inputs_from_dict(encoded).financing.shl_timing_basis is ShlTimingBasis.ABSOLUTE_INDEX
    assert from_runtime_summary({})['status']=='NOT_PERSISTED'


@pytest.mark.parametrize('factory', [create_generic_solar_reference,create_generic_wind_reference])
@pytest.mark.parametrize('months',[7,12,14,18,24])
@pytest.mark.parametrize('horizon',[20,25])
def test_opt_in_calendar_resolution_and_unchanged_strict_maturity(factory,months,horizon):
    from dateutil.relativedelta import relativedelta
    pi=factory()
    pi=replace(pi,info=replace(pi.info,construction_months=months,horizon_years=horizon,
               cod_date=pi.info.financial_close+relativedelta(months=months)))
    pi=apply_config(pi,config_json(timing='COD_RELATIVE'))
    run=run_clean_production(pi)
    g=run.g2c_result;m=g.financing_result.project_model_result
    assert g.return_summary.terminal.shareholder_loan.contractual_maturity_period_index==[p.period_index for p in m.periods if p.is_operation][-1]


def test_absolute_drift_is_visible_and_economics_not_reinterpreted():
    from dateutil.relativedelta import relativedelta
    pi=create_generic_solar_reference()
    pi=replace(pi,info=replace(pi.info,construction_months=24,cod_date=pi.info.financial_close+relativedelta(months=24)))
    run=run_clean_production(pi)
    core=build_financial_core_evidence(run)
    assert core['shl_timing']['issues']==['SHL_MATURITY_NOT_AT_MODEL_END']
    assert core['shl_timing']['maturity_period_index']==pi.financing.shl_maturity_period_index
    from app.api.project_runner import run_project
    payload=run_project('Solar','Base',project_inputs_override=pi)
    assert any('SHL_MATURITY_NOT_AT_MODEL_END' in str(message) for message in payload['messages'])


def test_missing_policy_no_senior_negative_cfads_and_bad_debt_authority():
    from financial_engine.valuation.loan_life import calculate_loan_life_coverage
    pi=create_generic_solar_reference();run=run_clean_production(apply_config(pi,config_json()))
    g=run.g2c_result;m=g.financing_result.project_model_result;t=g.return_summary.terminal.senior
    policy=run.project_inputs.valuation.coverage
    debt=isolated_debt_contract(run)
    assert calculate_loan_life_coverage(m,None,debt,t).status.value=='NOT_CONFIGURED'
    assert calculate_loan_life_coverage(m,policy,None,t).status.value=='DEBT_EVIDENCE_NOT_AVAILABLE'
    ambiguous=copy.deepcopy(debt);ambiguous['authority']='AMBIGUOUS'
    assert calculate_loan_life_coverage(m,policy,ambiguous,t).status.value=='DEBT_EVIDENCE_NOT_AVAILABLE'
    assert calculate_loan_life_coverage(replace(m,senior_debt=None),policy,debt,t).status.value=='NOT_APPLICABLE_NO_SENIOR'
    invalid=copy.deepcopy(debt);invalid['llcr_inputs']['loan_life_end_candidates']['actual_payoff_date']='1900-01-01'
    assert calculate_loan_life_coverage(m,policy,invalid,t).status.value=='DEBT_EVIDENCE_MISMATCH'
    cfads=replace(m.tax_and_cfads,cfads_keur=tuple(-abs(x) for x in m.tax_and_cfads.cfads_keur))
    negative=calculate_loan_life_coverage(replace(m,tax_and_cfads=cfads),policy,debt,t)
    assert negative.status.value=='OK' and negative.minimum.ratio<0
    cfads=replace(cfads,period_indices=tuple(reversed(cfads.period_indices)))
    assert calculate_loan_life_coverage(replace(m,tax_and_cfads=cfads),policy,debt,t).status.value=='PERIOD_AXIS_MISMATCH'


def test_sponsor_edge_cases_use_typed_status_and_signed_npv():
    from financial_engine.valuation.sponsor import calculate_total_sponsor_npv
    from types import SimpleNamespace as S
    policy=apply_config(create_generic_solar_reference(),config_json()).valuation.sponsor
    rows=[S(cashflow_date=date(2030,1,1),total_sponsor_net_cashflow_keur=0.,
            share_capital_contribution_keur=0.,share_premium_contribution_keur=0.,
            other_committed_equity_contribution_keur=0.,additional_equity_contribution_keur=0.,
            shl_cash_contribution_keur=0.,legal_equity_distribution_keur=0.,
            shl_cash_interest_receipt_keur=0.,actual_shl_principal_paid_keur=0.)]
    assert calculate_total_sponsor_npv(rows,None).status.value=='NOT_CONFIGURED'
    assert calculate_total_sponsor_npv([],policy).status.value=='CASHFLOW_EVIDENCE_UNAVAILABLE'
    assert calculate_total_sponsor_npv(rows,policy,True).npv_keur is None
    assert calculate_total_sponsor_npv(rows,policy,financial_close=date(2030,1,1)).npv_keur==0
    del rows[0].shl_cash_contribution_keur
    assert calculate_total_sponsor_npv(rows,policy,financial_close=date(2030,1,1)).status.value=='CASHFLOW_EVIDENCE_UNAVAILABLE'


def test_missing_rates_stay_unconfigured_and_existing_maturity_refusal_survives():
    from dateutil.relativedelta import relativedelta
    from app.input_adapter import _set_financing_tenor
    pi=create_generic_solar_reference()
    config=json.loads(config_json())
    for k in ('project','coverage','sponsor'):config[k]['discount_rate_pct']=None
    run=run_clean_production(apply_config(pi,json.dumps(config)))
    core=build_financial_core_evidence(run)
    assert core['project_npv_keur'] is None and core['sponsor_npv_keur'] is None
    assert core['valuation_summary']['project_npv']['status']=='NOT_CONFIGURED'
    assert core['sponsor_npv']['status']=='NOT_CONFIGURED'
    assert core['loan_life_coverage']['status']=='NOT_CONFIGURED'
    pi=_set_financing_tenor(pi,14)
    pi=replace(pi,info=replace(pi.info,horizon_years=15))
    pi=apply_config(pi,config_json(timing='COD_RELATIVE'))
    from app.services.production_financial_authority import CleanProductionRunUnavailable
    with pytest.raises(CleanProductionRunUnavailable,match='SHL_MATURITY_RESIDUAL_FAILS_CLOSED'):
        run_clean_production(pi)


def test_zero_contribution_no_negative_and_nonconvergent_xirr_are_typed(monkeypatch):
    from financial_engine.sponsor_returns import model
    dates=[date(2030,1,1),date(2031,1,1)]
    values=model.compute_gated_sponsor_return_metrics(dates,[0.,10.],[0.,10.],0.,0.)
    assert values[1].value=='NO_NEGATIVE_CASHFLOW' and values[3].value=='ZERO_CONTRIBUTION'
    monkeypatch.setattr(model,'robust_xirr',lambda *args:None)
    values=model.compute_gated_sponsor_return_metrics(dates,[-10.,20.],[-10.,20.],10.,10.)
    assert values[0] is None and values[1].value=='NON_CONVERGENT'
