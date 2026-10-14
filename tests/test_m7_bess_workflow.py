"""Actual Reference clone, canonical writer/Run/CAS, immutable scenario history."""
from copy import deepcopy
import json
import re
import pytest

from tests.test_model_decision_workspace_v2 import env, tokens  # noqa: F401
from tests.test_model_financing_f2 import run


@pytest.fixture
def storage(env, monkeypatch):
    from app.workbook import bess_config
    from app.services.project_library_service import ensure_reference_models, create_working_copy
    from app.persistence.projects_repository import get_reference_by_template_source
    from app.persistence.workspace_repository import get_workspace_state, save_workspace_state
    from app.runtime.model_execution import ModelExecutor, ModelExecutionConfig, reset_model_executor_for_tests
    monkeypatch.setattr(bess_config, 'ACTIVATION_ENABLED', True)
    executor = ModelExecutor(ModelExecutionConfig(mode='thread'))
    reset_model_executor_for_tests(executor)
    ensure_reference_models()
    reference = get_reference_by_template_source('generic_storage_reference')
    before = deepcopy(reference.baseline_snapshot)
    record = create_working_copy('decision-user', reference.project_id, 'Synthetic native battery')
    assert get_reference_by_template_source('generic_storage_reference').baseline_snapshot == before
    ws = get_workspace_state('decision-user', record.project_id)
    snapshot = dict(ws.draft_snapshot)
    snapshot.update(cod_date='2028-01-01', construction_months='12', horizon_years='2', tariff_eur_mwh='0',
                    ppa_term_years='0', p50_hours='0', total_capex_keur='1000', opex_y1_keur='1',
                    gearing_pct='50', interest_rate_pct='5.5', tenor_years='2', target_dscr='1.2')
    save_workspace_state(user_id='decision-user', project_id=record.project_id, project_code=record.project_code,
        draft_snapshot=snapshot, saved_snapshot=snapshot, last_runtime_snapshot={}, last_runtime_summary={}, governance_state={})
    yield record
    assert executor.shutdown_and_join() == []
    reset_model_executor_for_tests()


def form(env, record):
    from bs4 import BeautifulSoup
    response = env.client.get('/v2/workbook/bess/inputs', params={'project': record.project_code})
    assert response.status_code == 200, response.text
    parsed = BeautifulSoup(response.text, 'html.parser')
    return {k: parsed.select_one('input[name="' + k + '"]')['value'] for k in ('project', 'content_hash', 'csrf_token', 'workbook_version', 'configuration')}


def save(env, record, data=None):
    return env.client.post('/v2/workbook/bess/save', data=data or form(env, record), follow_redirects=False)


def test_full_native_save_run_stale_reopen_scenario_history(env, storage):
    from app.persistence.workspace_repository import get_workspace_state
    from app.persistence.run_history_repository import get_run_history
    from app.persistence.scenarios_repository import list_scenarios, duplicate_scenario, select_scenario
    from app.workbook.runtime_authority import resolve_runtime_freshness
    from app.workbook.service import WorkbookService
    response = save(env, storage)
    assert response.status_code == 303, response.text
    first, rr = run(env, storage)
    from app.run_integrity import run_integrity_checks
    integrity = run_integrity_checks(first.last_integrity_evidence).to_dict()
    assert integrity['overall'] == 'PASS', [r for r in integrity['checks'] if r['status'] != 'PASS']
    assert first.last_runtime_summary['bess_operating_audit']
    assert first.last_runtime_summary['bess_input_contract']
    original = deepcopy(get_run_history('decision-user', storage.project_id))
    data = form(env, storage)
    contract = json.loads(data['configuration'])
    contract['configuration']['dispatch'][20]['sell_price_eur_mwh'] = 120
    data['configuration'] = json.dumps(contract)
    assert save(env, storage, data).status_code == 303
    dirty = get_workspace_state('decision-user', storage.project_id)
    assert dirty.dirty and dirty.last_runtime_summary == first.last_runtime_summary
    assert 'STALE' in env.client.get('/v2/workbook', params={'project': storage.project_code}).text
    second, result = run(env, storage)
    assert second.last_runtime_summary['bess_input_contract'] != first.last_runtime_summary['bess_input_contract']
    assert second.last_runtime_summary['bess_operating_audit'][0]['gross_sale_revenue_keur'] != first.last_runtime_summary['bess_operating_audit'][0]['gross_sale_revenue_keur']
    history = get_run_history('decision-user', storage.project_id)
    prior = next(h for h in history if h.runtime_snapshot_id == first.last_runtime_snapshot_id)
    assert prior.runtime_summary == original[0].runtime_summary
    base = next(s for s in list_scenarios('decision-user', storage.project_id) if s.is_base_case)
    child = duplicate_scenario('decision-user', base.scenario_id, 'Battery downside')
    assert select_scenario('decision-user', storage.project_id, child.scenario_id)
    data = form(env, storage)
    contract = json.loads(data['configuration'])
    contract['configuration']['dispatch'][20]['sell_price_eur_mwh'] = 90
    data['configuration'] = json.dumps(contract)
    assert save(env, storage, data).status_code == 303
    child_run, child_rr = run(env, storage)
    assert child_run.last_runtime_scenario_id == child.scenario_id
    assert select_scenario('decision-user', storage.project_id, base.scenario_id)
    restored = get_workspace_state('decision-user', storage.project_id)
    assert restored.last_runtime_summary == second.last_runtime_summary
    assert restored.last_runtime_snapshot_id == second.last_runtime_snapshot_id


@pytest.mark.parametrize('fault', ['missing', 'forged', 'expired', 'owner', 'protected', 'cas', 'version', 'augmentation', 'unknown'])
def test_save_adversaries_are_atomic_and_have_no_engine_calls(env, storage, monkeypatch, fault):
    from app.persistence.workspace_repository import get_workspace_state
    from app.persistence.db import get_connection
    from app.auth import COOKIE_NAME, create_session_token
    data = form(env, storage)
    expected = 409
    if fault == 'missing': data['csrf_token'] = ''; expected = 403
    elif fault == 'forged': data['csrf_token'] += 'forged'; expected = 403
    elif fault == 'expired':
        from itsdangerous import URLSafeTimedSerializer, TimestampSigner
        from app.auth import CSRF_SECRET
        class Old(TimestampSigner):
            def get_timestamp(self): return super().get_timestamp() - 86401
        data['csrf_token'] = URLSafeTimedSerializer(CSRF_SECRET, signer=Old).dumps('a' * 48)
        expected = 403
    elif fault == 'owner': env.client.cookies.set(COOKIE_NAME, create_session_token(user_id='battery-other', username='other')); expected = 404
    elif fault == 'protected':
        conn = get_connection(); conn.execute('UPDATE projects SET is_protected=1 WHERE project_id=?', (storage.project_id,)); conn.commit(); conn.close()
        expected = 403
    elif fault == 'cas': data['content_hash'] = 'old'
    elif fault == 'version': data['workbook_version'] = 'old'
    else:
        raw = json.loads(data['configuration'])
        if fault == 'unknown': raw['unapproved'] = 1
        else:
            from tests.test_m7_bess_physics import event
            raw['configuration']['events'] = [event()]
        data['configuration'] = json.dumps(raw)
    before = get_workspace_state('decision-user', storage.project_id)
    monkeypatch.setattr('app.services.production_financial_authority.run_clean_production', lambda *a, **k: pytest.fail('No financial Run on Save'))
    response = save(env, storage, data)
    assert response.status_code == expected, response.text
    assert get_workspace_state('decision-user', storage.project_id) == before


def test_invalid_dispatch_run_preserves_last_run_and_history(env, storage):
    from app.persistence.workspace_repository import get_workspace_state
    from app.persistence.run_history_repository import get_run_history
    assert save(env, storage).status_code == 303
    first, rr = run(env, storage)
    original = deepcopy(get_run_history('decision-user', storage.project_id))
    data = form(env, storage)
    raw = json.loads(data['configuration'])
    raw['configuration']['dispatch'][0]['discharge_mw'] = .1
    data['configuration'] = json.dumps(raw)
    assert save(env, storage, data).status_code == 303
    page = env.client.get('/v2/workbook', params={'project': storage.project_code})
    response = env.client.post('/v2/workbook/run', data={'project': storage.project_code, **tokens(page.text)}, headers={'HX-Request': 'true'})
    assert 'role="alert"' in response.text
    assert 'previous Last Run is unchanged' in response.text
    after = get_workspace_state('decision-user', storage.project_id)
    assert after.last_runtime_summary == first.last_runtime_summary
    assert after.last_runtime_snapshot_id == first.last_runtime_snapshot_id
    assert len(get_run_history('decision-user', storage.project_id)) == len(original)
    assert after.dirty


def test_protected_reference_clone_endpoint_has_csrf_and_leaves_source_immutable(env, storage):
    from app.persistence.projects_repository import get_reference_by_template_source, list_project_records
    from app.auth import generate_csrf_token
    reference = get_reference_by_template_source('generic_storage_reference')
    before = deepcopy(reference.baseline_snapshot)
    data = {'project': reference.project_code, 'csrf_token': ''}
    response = env.client.post('/v2/workbook/bess/working-copy', data=data, follow_redirects=False)
    assert response.status_code == 403
    data['csrf_token'] = generate_csrf_token()
    response = env.client.post('/v2/workbook/bess/working-copy', data=data, follow_redirects=False)
    assert response.status_code == 303
    assert get_reference_by_template_source('generic_storage_reference').baseline_snapshot == before
    data['project'] = storage.project_code
    assert env.client.post('/v2/workbook/bess/working-copy', data=data).status_code == 409
