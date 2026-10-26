"""Real authorized snapshots: lazy exclusion, exact findings and no financial writes."""
from tests.model_mutation_csrf import post_valid_mutation

import json
import re
from unittest import mock

import pytest
import test_model_insight_q3_route as q3

env = q3.env


def _payload(response):
    return json.loads(re.search(r'data-md-payload>(.*?)</script>', response.text, re.S).group(1))


@pytest.mark.parametrize('template', q3.VERTICALS.values())
def test_lazy_open_and_full_read_preserve_all_findings_and_financial_evidence(env, template):
    from app.persistence.workspace_repository import get_workspace_state
    from app.v2.router import _build_pis_with_composite_identity, _templates
    from app.v2.insight_quality_projection import build_quality_insight
    owner = 'v7-lazy-' + template
    rec = q3._project(env, owner, template, 'Lazy diagnostics')
    q3._run(env, owner, rec)
    before = get_workspace_state(owner, rec.project_id)
    with mock.patch('app.v2.diagnostics_projection.build_diagnostics', side_effect=AssertionError('eager diagnostics')) as projection:
        page = q3._get(env, owner, rec)
    projection.assert_not_called()
    assert page.status_code == 200
    assert 'data-diagnostics-load-state="pending"' in page.text
    assert 'data-md-payload' not in page.text and 'data-md-row' not in page.text
    assert 'id="v2-model-health"' in page.text and 'data-q3-check' in page.text
    pis = _build_pis_with_composite_identity(before, rec, owner)
    common = dict(run_state='CURRENT', project_inputs=pis.to_projectinputs(),
                  active_scenario_id=before.active_scenario_id, scenario_name='Base Case')
    full = build_quality_insight(before, include_diagnostics=True, **common)['diagnostics']
    summary = build_quality_insight(before, include_diagnostics_summary=True, **common)['diagnostics']
    health = _templates.get_template('partials/_model_health.html')
    assert health.render(diagnostics=summary) == health.render(diagnostics=full)
    with mock.patch('app.api.project_runner.run_project', side_effect=AssertionError('read must not run engine')):
        response = env.client.get('/v2/workbook/diagnostics', params={'project': rec.project_code}, cookies=env.cookie(owner))
        direct = env.client.get('/v2/workbook', params={'project':rec.project_code, 'sheet':'diagnostics'}, cookies=env.cookie(owner))
    data = _payload(response)
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
    assert _payload(direct) == data
    assert get_workspace_state(owner, rec.project_id) == before
    # Compare with the pre-V7 eager/full JSON contract, not the already compact direct view.
    from jinja2.utils import htmlsafe_json_dumps
    legacy_bytes = len(direct.content) - len(re.search(r'data-md-payload>(.*?)</script>', direct.text, re.S).group(1).encode())
    legacy_bytes += len(str(htmlsafe_json_dumps(full, sort_keys=True)).encode())
    assert len(page.content) < legacy_bytes * .5


def test_not_run_and_concurrent_read_fail_closed(env):
    from app.v2.post_run_context import PostRunContextChanged
    owner = 'v7-empty'
    rec = q3._project(env, owner, 'generic_solar_reference', 'Empty checks')
    response = env.client.get('/v2/workbook/diagnostics', params={'project':rec.project_code}, cookies=env.cookie(owner))
    assert 'data-state="NOT_RUN"' in response.text and 'data-md-payload' not in response.text
    q3._run(env, owner, rec)
    with mock.patch('app.v2.post_run_context.PostRunRequestContext.validate_current', side_effect=PostRunContextChanged('concurrent edit')):
        changed = env.client.get('/v2/workbook/diagnostics', params={'project':rec.project_code}, cookies=env.cookie(owner))
    assert changed.status_code == 200 and 'data-state="UNAVAILABLE"' in changed.text
    assert 'data-md-payload' not in changed.text


def test_save_invalidates_without_full_projection_and_preserves_run(env):
    from app.persistence.workspace_repository import get_workspace_state
    owner = 'v7-save'
    rec = q3._project(env, owner, 'generic_solar_reference', 'Save checks')
    q3._run(env, owner, rec)
    before = get_workspace_state(owner, rec.project_id)
    h, v = q3._tokens(q3._get(env, owner, rec).text)
    with mock.patch('app.v2.diagnostics_projection.build_diagnostics', side_effect=AssertionError('Save must not evaluate periods')) as projection:
        saved = post_valid_mutation(env.client, '/v2/workbook/update', data={'project':rec.project_code,
            'field_id':'project_setup.technical.p50_hours', 'value':'1501', 'sheet_id':'project_setup',
            'content_hash':h, 'workbook_version':v}, cookies=env.cookie(owner), headers={'HX-Request':'true'})
    projection.assert_not_called()
    assert saved.status_code == 200 and 'data-diagnostics-load-state="pending"' in saved.text
    assert 'data-md-payload' not in saved.text
    after = get_workspace_state(owner, rec.project_id)
    for name in ('last_runtime_snapshot_id', 'last_runtime_composite_hash', 'last_financial_statements',
                 'last_integrity_evidence', 'last_runtime_summary', 'last_runtime_at'):
        assert getattr(before, name) == getattr(after, name)
    response = env.client.get('/v2/workbook/diagnostics', params={'project':rec.project_code}, cookies=env.cookie(owner))
    assert _payload(response)['state'] == 'STALE'
