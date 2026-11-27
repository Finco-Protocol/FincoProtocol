"""Real authorized snapshots: lazy exclusion, exact findings and no financial writes."""
from tests.model_mutation_csrf import post_valid_mutation

import json
import re
from unittest import mock

import pytest
import test_model_insight_q3_route as q3
from tests.model_react_test_helpers import react_workbook_tokens, react_workspace_payload

env = q3.env


@pytest.mark.parametrize('template', q3.VERTICALS.values())
def test_lazy_open_and_full_read_preserve_all_findings_and_financial_evidence(env, template):
    from app.persistence.workspace_repository import get_workspace_state
    from app.v2.router import _build_pis_with_composite_identity
    from app.v2.insight_quality_projection import build_quality_insight
    owner = 'v7-lazy-' + template
    rec = q3._project(env, owner, template, 'Lazy diagnostics')
    q3._run(env, owner, rec)
    before = get_workspace_state(owner, rec.project_id)
    with mock.patch('app.v2.diagnostics_projection.build_diagnostics', side_effect=AssertionError('eager diagnostics')) as projection:
        ws_payload = react_workspace_payload(env.client, rec.project_code, cookies=env.cookie(owner))
    projection.assert_not_called()
    assert ws_payload['ok'] is True and ws_payload['freshness']['state'] == 'CURRENT'
    pis = _build_pis_with_composite_identity(before, rec, owner)
    common = dict(run_state='CURRENT', project_inputs=pis.to_projectinputs(),
                  active_scenario_id=before.active_scenario_id, scenario_name='Base Case')
    full = build_quality_insight(before, include_diagnostics=True, **common)['diagnostics']
    with mock.patch('app.api.project_runner.run_project', side_effect=AssertionError('read must not run engine')):
        response = env.client.get('/v2/model-react/diagnostics', params={'project': rec.project_code}, cookies=env.cookie(owner))
    assert response.status_code == 200
    data = response.json()['diagnostics']
    assert data['client_schema'] == 'diagnostics_client_v1'
    assert data['state'] == 'CURRENT' and len(data['checks']) == len(full['checks']) == 30
    assert data['score'] == full['score'] and data['integrity'] == full['integrity']
    for original, compact in zip(full['checks'], data['checks'], strict=True):
        assert {k:v for k,v in compact.items() if k != 'periods'} == {k:v for k,v in original.items() if k != 'periods'}
        for expected, period in zip(original['periods'], compact['periods'], strict=True):
            restored = {'check_id':compact['check_id'], 'snapshot_id':data['identity']['snapshot_id'],
                        'run_identity':data['identity'], 'evidence_source':compact['evidence_source'], **period}
            assert restored == expected
    for key, value in data['v2'].items():
        assert value == full['v2'][key]
    assert get_workspace_state(owner, rec.project_id) == before


def test_not_run_and_concurrent_read_fail_closed(env):
    from app.v2.post_run_context import PostRunContextChanged
    owner = 'v7-empty'
    rec = q3._project(env, owner, 'generic_solar_reference', 'Empty checks')
    response = env.client.get('/v2/model-react/diagnostics', params={'project':rec.project_code}, cookies=env.cookie(owner))
    assert response.status_code == 200
    assert response.json()['diagnostics']['state'] == 'NOT_RUN' and response.json()['diagnostics']['checks'] == []
    q3._run(env, owner, rec)
    with mock.patch('app.v2.post_run_context.PostRunRequestContext.validate_current', side_effect=PostRunContextChanged('concurrent edit')):
        changed = env.client.get('/v2/model-react/diagnostics', params={'project':rec.project_code}, cookies=env.cookie(owner))
    assert changed.status_code == 503 and changed.json()['ok'] is False


def test_save_invalidates_without_full_projection_and_preserves_run(env):
    from app.persistence.workspace_repository import get_workspace_state
    owner = 'v7-save'
    rec = q3._project(env, owner, 'generic_solar_reference', 'Save checks')
    q3._run(env, owner, rec)
    before = get_workspace_state(owner, rec.project_id)
    tok = react_workbook_tokens(env.client, rec.project_code, cookies=env.cookie(owner))
    h, v = tok['content_hash'], tok['workbook_version']
    with mock.patch('app.v2.diagnostics_projection.build_diagnostics', side_effect=AssertionError('Save must not evaluate periods')) as projection:
        saved = post_valid_mutation(env.client, '/v2/workbook/update', data={'project':rec.project_code,
            'field_id':'project_setup.technical.p50_hours', 'value':'1501', 'sheet_id':'project_setup',
            'content_hash':h, 'workbook_version':v}, cookies=env.cookie(owner), headers={'HX-Request':'true'})
    projection.assert_not_called()
    assert saved.status_code == 200
    after = get_workspace_state(owner, rec.project_id)
    for name in ('last_runtime_snapshot_id', 'last_runtime_composite_hash', 'last_financial_statements',
                 'last_integrity_evidence', 'last_runtime_summary', 'last_runtime_at'):
        assert getattr(before, name) == getattr(after, name)
    response = env.client.get('/v2/model-react/diagnostics', params={'project':rec.project_code}, cookies=env.cookie(owner))
    assert response.json()['diagnostics']['state'] == 'STALE'
