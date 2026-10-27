from dataclasses import replace
from datetime import date
import hashlib
import json
from pathlib import Path

import pytest

from app import project_factories as pf
from app.services.production_financial_authority import run_clean_production
from app.services.financial_core_evidence import build_financial_core_evidence
from app.services.clean_presentation_adapter import build_clean_sponsor_schedule
from app.workbook.financial_core_config import apply_config
from tests.fin_v2_3_oracle import npv, xirr, float_leaves
from tests.fin_v2_3_support import config_json, isolated_debt_contract

KINDS = ('solar', 'wind', 'data_center', 'ev_charging')


@pytest.fixture(scope='module', params=KINDS)
def reference(request):
    pi = getattr(pf, 'create_generic_' + request.param + '_reference')()
    return request.param, pi, run_clean_production(pi)


def test_existing_full_float_baseline_is_bit_identical(reference):
    kind, _, run = reference
    expected = json.loads((Path(__file__).parent/'fixtures/fin_v2_3_baseline.json').read_text())[kind]
    leaves = float_leaves(run.g2c_result)
    digest = hashlib.sha256(json.dumps(leaves, sort_keys=True, separators=(',', ':')).encode()).hexdigest()
    assert len(leaves) == expected['float_paths']
    assert digest == expected['float_hex_sha256']


def test_sponsor_dated_flow_identities_and_decimal_xirr(reference):
    _, _, run = reference
    g = run.g2c_result
    evidence = build_clean_sponsor_schedule(run)
    rows = evidence['periods']
    assert evidence['contract_version'] == 'SPONSOR_PERIOD_EVIDENCE_V1'
    assert {'CONSTRUCTION','OPERATING'} <= {r['axis_kind'] for r in rows}
    dates = [date.fromisoformat(r['date']) for r in rows]
    for r in rows:
        equity = sum(r[k] for k in ('share_capital_contribution_keur','share_premium_contribution_keur',
                                    'other_committed_equity_contribution_keur','additional_equity_contribution_keur'))
        assert r['pure_equity_net_cashflow_keur'] == pytest.approx(r['legal_equity_distribution_keur']-equity, abs=1e-6)
        expected = (r['pure_equity_net_cashflow_keur']-r['shl_cash_contribution_keur']
                    +r['shl_cash_interest_receipt_keur']+r['shl_principal_receipt_keur'])
        assert r['total_sponsor_net_cashflow_keur'] == pytest.approx(expected, abs=1e-6)
    for r in evidence['loan_balance_periods']:
        assert r['shl_opening_keur']+r['shl_draw_keur']+r['shl_pik_keur']-r['shl_principal_keur'] == pytest.approx(r['shl_closing_keur'], abs=1e-6)
    assert sum(r['shl_cash_contribution_keur'] for r in rows) == pytest.approx(g.total_shl_cash_contributed_keur,abs=1e-6)
    funding = g.financing_result.construction_funding.periods
    assert sum(p.total_sponsor_cash_draw_keur for p in funding) == pytest.approx(g.total_sponsor_contributed_keur,abs=1e-6)
    for key, actual in [('pure_equity_net_cashflow_keur',g.pure_equity_xirr),('total_sponsor_net_cashflow_keur',g.total_sponsor_xirr)]:
        oracle = xirr(dates, [r[key] for r in rows])
        assert actual == pytest.approx(float(oracle), abs=1e-12)


@pytest.mark.parametrize('case', ['BASE','BANK'])
@pytest.mark.parametrize('periodic', [False, True])
def test_every_new_valuation_against_independent_decimal(reference, case, periodic):
    _, pi, baseline = reference
    configured = apply_config(pi, config_json(case, periodic, rate=2.75 if periodic else 5.5))
    run = run_clean_production(configured)
    core = build_financial_core_evidence(run, isolated_debt_contract(run))
    assert core['loan_life_coverage']['status'] == 'OK', core['loan_life_coverage']
    before, after = float_leaves(baseline.g2c_result), float_leaves(run.g2c_result)
    assert {k:v for k,v in before.items() if not k.startswith('.valuation_summary')} == {
        k:v for k,v in after.items() if not k.startswith('.valuation_summary')}
    m = run.g2c_result.financing_result.project_model_result
    by_idx = {p.period_index:p for p in m.periods}
    cfads_values = m.tax_and_cfads.cfads_keur if case=='BASE' else m.debt_sizing.bank_cfads_keur
    cfads = dict(zip(m.tax_and_cfads.period_indices, cfads_values))
    rate = configured.valuation.coverage.annual_discount_rate
    coverage = core['loan_life_coverage']
    for o in [coverage['contractual'], coverage['actual_repayment'], coverage['plcr'], *coverage['rolling']]:
        selected = [p for p in m.periods if p.is_operation and o['period_index']<=p.period_index<=o['horizon_end_period_index']]
        oracle = npv([p.period_end for p in selected], [cfads[p.period_index] for p in selected], rate,
                     date.fromisoformat(o['observation_date']), periodic)
        assert o['ratio'] == pytest.approx(float(oracle)/o['opening_senior_balance_keur'], rel=1e-12)
    assert core['min_rolling_llcr'] == min(o['ratio'] for o in coverage['rolling'])
    assert core['plcr'] == pytest.approx(coverage['plcr']['ratio'], rel=1e-12)
    sponsor_rows=run.g2c_result.waterfall_periods
    oracle=npv([p.cashflow_date for p in sponsor_rows], [p.total_sponsor_net_cashflow_keur for p in sponsor_rows],
               configured.valuation.sponsor.annual_discount_rate, sponsor_rows[0].cashflow_date)
    assert core['sponsor_npv_keur'] == pytest.approx(float(oracle), rel=1e-12)
    project=run.g2c_result.return_summary.project
    project_rows=project.cashflows
    oracle=npv([p.cashflow_date for p in project_rows], [p.net_unlevered_project_cashflow_keur for p in project_rows],
               configured.valuation.project.annual_discount_rate, project_rows[0].cashflow_date, periodic)
    assert core['project_npv_keur'] == pytest.approx(float(oracle), rel=1e-12)


@pytest.mark.parametrize('kind', KINDS)
def test_missing_or_tampered_senior_debt_contract_still_fails_closed(kind):
    # A persisted positive Senior schedule is necessary but not sufficient.
    # FIN-V2-3 must refuse missing/forged FIN-V2-2 maturity/payoff evidence;
    # the integration test must never turn those cases into a false OK.
    pi = getattr(pf, 'create_generic_' + kind + '_reference')()
    configured = apply_config(pi, config_json())
    run = run_clean_production(configured)
    missing = build_financial_core_evidence(run, None)['loan_life_coverage']
    assert missing['status'] == 'DEBT_EVIDENCE_NOT_AVAILABLE'
    assert missing['contractual'] is None
    correct = isolated_debt_contract(run)
    positive = build_financial_core_evidence(run, correct)['loan_life_coverage']
    assert positive['status'] == 'OK'
    tampered = json.loads(json.dumps(correct))
    tampered['llcr_inputs']['loan_life_end_candidates']['actual_payoff_date'] = '1900-01-01'
    refused = build_financial_core_evidence(run, tampered)['loan_life_coverage']
    assert refused['status'] == 'DEBT_EVIDENCE_MISMATCH'
    assert refused['actual_repayment'] is None
