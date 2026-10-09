"""F2 atomic configuration, canonical economics and authorized lifecycle acceptance."""
from dataclasses import replace
import json
from pathlib import Path

import pytest

from app.workbook.bankability_config import FIELD_ID, SNAPSHOT_KEY, apply_config, build_view, parse_config
from tests.test_model_decision_workspace_v2 import env, tokens


@pytest.mark.parametrize("raw", ['[]', '{"version":true}', '{"version":2}', '{"version":1,"x":1}',
    '{"version":1,"version":1}', '{"version":1,"rates_pct":[NaN]}',
    '{"version":1,"sizing_mode":"minimum_dscr_sculpted"}', '{"version":1,"lender_case":"P75"}',
    '{"version":1,"targets":[0.9]}', '{"version":1,"rates_pct":[-1]}',
    '{"version":1,"day_count":"30_360"}', '{"version":1,"target_scalar":1.2}'])
def test_invalid_payload_fails_closed(raw):
    with pytest.raises(ValueError):
        parse_config(raw)


def config(**kwargs):
    return json.dumps(dict(version=1, **kwargs))


def project(kind):
    from app import project_factories
    return getattr(project_factories, 'create_generic_' + kind + '_reference')()


@pytest.mark.parametrize("kind", ['solar', 'wind', 'data_center', 'ev_charging'])
def test_absent_config_preserves_existing_authority_and_view_has_actual_axis(kind):
    pi = project(kind)
    assert apply_config(pi, None) is pi
    view = build_view(pi, None, project_type=kind.title())
    assert view['available']
    assert len(view['periods']) == pi.financing.senior_tenor_years * 2
    assert view['periods'][0]['number'] == 1
    assert view['renewable'] == (kind in ('solar', 'wind'))


@pytest.mark.parametrize("kind", ['solar', 'wind'])
def test_exact_period_target_rate_mapping_and_operating_case_separation(kind):
    pi = project(kind)
    n = pi.financing.senior_tenor_years * 2
    targets = [1.2] * 10 + [1.45] * (n - 10)
    rates = [5.5] * 10 + [6.0] * (n - 10)
    result = apply_config(pi, config(lender_case='P_50', targets=targets, rates_pct=rates,
        day_count='act_365'), project_type=kind.title())
    assert result.financing.senior_sculpting_config.target_dscr_schedule == tuple(targets)
    assert result.financing.senior_debt_interest_config.rate_schedule.explicit_all_in_rates == tuple(x / 100 for x in rates)
    assert result.financing.debt_sizing_case.production_yield_scenario.value == 'P_50'
    assert result.revenue == pi.revenue and result.technical == pi.technical
    with pytest.raises(ValueError):
        apply_config(pi, config(targets=[1.2]), project_type=kind.title())
    with pytest.raises(ValueError):
        apply_config(pi, config(rates_pct=[5.5]), project_type=kind.title())
    with pytest.raises(ValueError):
        apply_config(pi, config(sizing_mode='gearing_cap', targets=targets), project_type=kind.title())


@pytest.mark.parametrize('kind', ['data_center', 'ev_charging'])
def test_nonrenewable_lender_cases_rejected(kind):
    with pytest.raises(ValueError, match='Solar and Wind only'):
        apply_config(project(kind), config(lender_case='P_50'), project_type=kind.title())


def save(env, record, raw, *, field=FIELD_ID, stale_tokens=None):
    page = env.client.get('/v2/workbook', params={'project': record.project_code})
    return env.client.post('/v2/workbook/update', headers={'HX-Request': 'true'}, data=dict(
        project=record.project_code, field_id=field, value=raw, sheet_id='debt',
        **(stale_tokens or tokens(page.text))))


def run(env, record):
    from app.persistence.workspace_repository import get_workspace_state
    from app.workbook.service import WorkbookService
    page = env.client.get('/v2/workbook', params={'project': record.project_code})
    response = env.client.post('/v2/workbook/run', headers={'HX-Request': 'true'}, data=dict(
        project=record.project_code, **tokens(page.text)))
    assert response.status_code == 200
    ws = get_workspace_state('decision-user', record.project_id)
    assert ws.last_runtime_summary, response.text[:1500]
    assert not ws.dirty
    return ws, WorkbookService.get_runtime_result(ws)


@pytest.mark.parametrize('kind', ['solar', 'wind'])
def test_real_save_reload_stale_run_current_last_run_immutability(env, kind):
    from app.persistence.workspace_repository import get_workspace_state
    from app.workbook.input_set import ProjectInputSet
    from app.workbook.runtime_authority import resolve_runtime_freshness
    record = env.create(kind)
    before, old = run(env, record)
    old_summary = dict(old.runtime_summary)
    n = ProjectInputSet.from_snapshot(before.draft_snapshot).to_projectinputs().financing.senior_tenor_years * 2
    raw = config(lender_case='P_50', targets=[1.4] * n, rates_pct=[6.5] * n)
    response = save(env, record, raw)
    assert response.status_code == 200 and 'field-error-banner' not in response.text
    ws = get_workspace_state('decision-user', record.project_id)
    assert ws.draft_snapshot[SNAPSHOT_KEY] == raw
    assert ws.last_runtime_summary == before.last_runtime_summary
    assert ws.last_runtime_snapshot_id == before.last_runtime_snapshot_id
    assert ws.dirty
    from app.services.export_service import resolve_canonical_last_run_from_workspace
    export = resolve_canonical_last_run_from_workspace(record, 'decision-user', ws)
    assert export.project_inputs.financing.senior_debt_interest_config.rate_schedule.explicit_all_in_rates[0] != .065
    pis = ProjectInputSet.from_snapshot(ws.draft_snapshot)
    assert pis.to_projectinputs().financing.senior_debt_interest_config.rate_schedule.explicit_all_in_rates[0] == .065
    assert 'bankability-workspace' in env.client.get('/v2/workbook', params={'project': record.project_code}).text
    _, new = run(env, record)
    assert new.runtime_summary['senior_debt_keur'] != old_summary['senior_debt_keur']
    assert dict(old.runtime_summary) == old_summary
    assert new.snapshot_id != old.snapshot_id
    latest = get_workspace_state('decision-user', record.project_id)
    export = resolve_canonical_last_run_from_workspace(record, 'decision-user', latest)
    assert export.project_inputs.financing.senior_debt_interest_config.rate_schedule.explicit_all_in_rates[0] == .065


def test_atomic_validation_scalar_lock_and_stale_cas_do_not_write(env):
    from app.persistence.workspace_repository import get_workspace_state
    record = env.create()
    page = env.client.get('/v2/workbook', params={'project': record.project_code})
    original = get_workspace_state('decision-user', record.project_id)
    assert 'exactly' in save(env, record, config(targets=[1.2])).text
    assert get_workspace_state('decision-user', record.project_id) == original
    n = 30
    assert save(env, record, config(rates_pct=[6.0] * n)).status_code == 200
    before = get_workspace_state('decision-user', record.project_id)
    assert 'owns this input' in save(env, record, '7', field='debt.senior.interest_rate_pct').text
    assert 'exactly' in save(env, record, '10', field='debt.senior.tenor_years').text
    save(env, record, config(lender_case='P_50'), stale_tokens=tokens(page.text))
    assert get_workspace_state('decision-user', record.project_id) == before
    save(env, record, '')
    assert not get_workspace_state('decision-user', record.project_id).draft_snapshot[SNAPSHOT_KEY]


@pytest.mark.parametrize('kind', ['solar', 'wind'])
def test_canonical_economic_matrix(kind, tmp_path):
    from app.services.production_financial_authority import run_clean_production
    from financial_engine.financing.generic_product_policy import build_sources_and_uses
    pi = project(kind)
    pi = replace(pi, financing=replace(pi.financing, gearing_ratio=.95))
    n = pi.financing.senior_tenor_years * 2
    cases = {
        'baseline': {},
        'p50': dict(lender_case='P_50'),
        'scalar': dict(targets=[], target_scalar=1.5),
        'period_targets': dict(targets=[1.2] * 10 + [1.45] * (n - 10)),
        'rates': dict(rates_pct=[6.5] * n),
        'gearing': dict(sizing_mode='gearing_cap'),
        'fees': dict(fees=dict(commitment_pct=2, structuring_pct=2, arrangement_pct=1)),
        'none': dict(reserve=dict(mode='none', months=0, requirement_keur=0, commitment_keur=0, fee_pct=0)),
        'cash': dict(reserve=dict(mode='cash_fixed', months=0, requirement_keur=500, commitment_keur=0, fee_pct=0)),
        'dsrf': dict(reserve=dict(mode='dsrf', months=0, requirement_keur=500, commitment_keur=500, fee_pct=.75)),
        'peak': dict(reserve=dict(mode='automatic_peak', months=12, requirement_keur=0, commitment_keur=0, fee_pct=0)),
    }
    results = {}
    for name, changes in cases.items():
        effective = apply_config(pi, config(**changes) if changes else None, project_type=kind.title())
        output = run_clean_production(effective, 'Base', project_type=kind)
        financing = output.g2c_result.financing_result
        uses = build_sources_and_uses(financing)
        senior = financing.project_model_result.senior_debt
        # Clean project_adapter uses 1e-4 kEUR convergence, not a fabricated zero.
        assert senior.senior_debt_closing_keur[-1] == pytest.approx(0, abs=1e-4)
        assert senior.diagnostics['converged'] and senior.diagnostics['is_authoritative']
        assert uses.total_sources_keur == pytest.approx(uses.total_uses_keur, abs=1e-5)
        results[name] = dict(senior=uses.senior_debt_keur, uses=uses.total_uses_keur,
            idc=uses.capitalized_idc_keur, fees=uses.structuring_fee_keur,
            dsra=uses.initial_dsra_funding_keur, interest=sum(senior.senior_interest_keur),
            service=sum(senior.senior_debt_service_keur),
            min_dscr=min(x for x in senior.senior_dscr if x is not None),
            avg_dscr=sum(x for x in senior.senior_dscr if x is not None) / len([x for x in senior.senior_dscr if x is not None]),
            bank_min_dscr=min(x for x in financing.project_model_result.debt_sizing.bank_sizing_dscr if x is not None),
            solver=senior.diagnostics['termination_reason'], binding=senior.binding_constraint,
            dsrf_fee=output.g2c_result.total_dsrf_commitment_fee_keur,
            project_irr=output.g2c_result.return_summary.project.project_xirr,
            equity_irr=output.g2c_result.pure_equity_xirr,
            sponsor_irr=output.g2c_result.total_sponsor_xirr,
            min_llcr=output.g2c_result.valuation_summary.lender_coverage.minimum_llcr,
            requested_gearing=effective.financing.gearing_ratio,
            terminal_balance=senior.senior_debt_closing_keur[-1])
        if name == 'period_targets':
            bank = financing.project_model_result.debt_sizing
            for target, ratio in zip(changes['targets'], [x for x in bank.bank_sizing_dscr if x is not None], strict=True):
                assert ratio >= target - 1e-6
    assert results['p50']['senior'] != results['baseline']['senior']
    assert results['scalar']['senior'] != results['baseline']['senior']
    assert results['period_targets']['senior'] != results['baseline']['senior']
    assert results['rates']['interest'] != results['baseline']['interest']
    assert results['fees']['fees'] / results['fees']['senior'] == pytest.approx(.03)
    assert results['none']['dsra'] == 0
    assert results['cash']['dsra'] == 500
    assert results['dsrf']['dsra'] == 0
    assert results['dsrf']['dsrf_fee'] > 0
    assert results['peak']['dsra'] > results['baseline']['dsra']
    (tmp_path / (kind + '-financial-matrix.json')).write_text(json.dumps(results, indent=2), encoding='utf-8')


def test_browser_script_is_serialization_not_solver():
    source = (Path(__file__).resolve().parents[1] / 'static/js/model_bankability.js').read_text(encoding='utf-8')
    assert 'JSON.stringify' in source and 'htmx:configRequest' in source
    for forbidden in ('Math.pow', 'Math.exp', 'debt_service', 'cfads', 'irr(', 'npv('):
        assert forbidden not in source


def test_cross_owner_rejection_and_get_does_not_execute_solver(env, monkeypatch):
    from app.runtime import model_execution
    from app.auth import COOKIE_NAME, create_session_token
    record = env.create()
    def forbidden(*args, **kwargs):
        raise AssertionError('Opening/editing a sheet must not run the model')
    monkeypatch.setattr(model_execution, 'run_model_process', forbidden)
    page = env.client.get('/v2/workbook', params={'project': record.project_code, 'sheet': 'debt'})
    assert page.status_code == 200 and 'bankability-workspace' in page.text
    assert save(env, record, config(lender_case='P_50')).status_code == 200
    env.client.cookies.set(COOKIE_NAME, create_session_token(user_id='f2-other-owner', username='admin'))
    response = env.client.post('/v2/workbook/update', data=dict(project=record.project_code,
        field_id=FIELD_ID, value=config(lender_case='P90-10y'), sheet_id='debt', **tokens(page.text)))
    assert response.status_code == 404


def test_protected_template_and_context_contract():
    from app.v2.router import _templates
    view = build_view(project('solar'), None, project_type='Solar')
    html = _templates.get_template('partials/_financing_bankability.html').render(
        bankability=view, project_editable=False)
    assert 'read-only' in html and 'data-f2-form' not in html
    assert _templates.get_template('partials/_financing_bankability.html').render() == ''


def test_first_save_after_scenario_selection_preserves_scenario_payload(env):
    from app.persistence.scenarios_repository import list_scenarios, get_scenario
    record = env.create()
    env.client.get('/v2/workbook', params={'project': record.project_code})
    response = env.client.post('/v2/workbook/scenarios/create', headers={'HX-Request': 'true'},
        data={'project': record.project_code, 'scenario_name': 'F2 alternate'})
    assert response.status_code == 200
    sc = next(s for s in list_scenarios('decision-user', record.project_id) if not s.is_base_case)
    response = env.client.post('/v2/workbook/scenarios/select', headers={'HX-Request': 'true'},
        data={'project': record.project_code, 'scenario_id': sc.scenario_id})
    assert response.status_code == 200
    original = get_scenario(sc.scenario_id, 'decision-user')
    assert save(env, record, config(lender_case='P_50')).status_code == 200
    assert get_scenario(sc.scenario_id, 'decision-user').overrides == original.overrides


@pytest.mark.parametrize('kind', ['solar', 'wind'])
def test_existing_tenor_editor_consumed_with_bankability_payload(env, kind):
    record = env.create(kind)
    assert save(env, record, config(lender_case='P_50')).status_code == 200
    assert save(env, record, '12', field='debt.senior.tenor_years').status_code == 200
    ws, rr = run(env, record)
    from app.workbook.input_set import ProjectInputSet
    pi = ProjectInputSet.from_snapshot(ws.draft_snapshot).to_projectinputs()
    assert pi.financing.senior_tenor_years == 12
    assert len(build_view(pi, ws.draft_snapshot[SNAPSHOT_KEY], project_type=kind.title())['periods']) == 24
    rows = rr.debt_schedule['periods']
    assert rr.runtime_summary['senior_debt_keur'] > 0
    principal = [p['senior_principal_keur'] for p in rows if p.get('senior_principal_keur') is not None]
    # Existing persisted UI schedule rounds each amount to 2 decimal places.
    # Raw solver terminal closure is separately checked in the economic matrix.
    rounding_bound = sum(x > 0 for x in principal) * .005 + 1e-4
    assert principal and sum(principal) == pytest.approx(rr.runtime_summary['senior_debt_keur'], abs=rounding_bound)


def test_protected_reference_save_rejected_before_cas(env):
    from app.persistence.workspace_repository import get_workspace_state
    from app.workbook.update_service import WorkbookUpdateService, ProtectedReferenceError
    from app.workbook.registry import WORKBOOK
    record = env.create()
    env.client.get('/v2/workbook', params={'project': record.project_code})
    ws = get_workspace_state('decision-user', record.project_id)
    with pytest.raises(ProtectedReferenceError):
        WorkbookUpdateService.apply_draft_update(ws=ws, project_record=replace(record, project_origin='factory_template'),
            field_id=FIELD_ID, raw_value=config(lender_case='P_50'), workbook_version=WORKBOOK.version,
            content_hash='irrelevant-before-cas')
    assert get_workspace_state('decision-user', record.project_id) == ws


def test_materialized_manual_fee_conflict_rejects_save_and_run_without_solver(env, monkeypatch):
    from app.services import capex_sub_lines_integration
    from app.runtime import model_execution
    from app.persistence.workspace_repository import get_workspace_state
    record = env.create()
    fees = dict(commitment_pct=2, structuring_pct=2, arrangement_pct=1)
    assert save(env, record, config(fees=fees)).status_code == 200
    before = get_workspace_state('decision-user', record.project_id)
    monkeypatch.setattr(capex_sub_lines_integration, 'apply_user_sub_lines_replacing_base',
        lambda capex, **kwargs: replace(capex, bank_fees_keur=100))
    def forbidden(*args, **kwargs):
        raise AssertionError('Conflicting fee authority must reject before solver execution')
    monkeypatch.setattr(model_execution, 'run_model_process', forbidden)
    assert 'no competing fee override' in save(env, record, config(fees=fees)).text
    page = env.client.get('/v2/workbook', params={'project': record.project_code})
    assert 'uncheck to remove' in page.text
    response = env.client.post('/v2/workbook/run', headers={'HX-Request': 'true'},
        data=dict(project=record.project_code, **tokens(page.text)))
    assert 'Remove the bankability fee override before Run' in response.text
    assert get_workspace_state('decision-user', record.project_id) == before
