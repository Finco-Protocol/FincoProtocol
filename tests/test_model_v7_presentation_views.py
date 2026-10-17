"""Coherent, authorized read-only presentation snapshots; no financial execution."""
from unittest import mock

import pytest
import test_model_insight_q3_route as q3

env = q3.env


@pytest.mark.parametrize('template', ['generic_solar_reference', 'generic_wind_reference'])
def test_lazy_statements_and_coherent_refresh_preserve_persisted_results(env, template):
    from app.persistence.workspace_repository import get_workspace_state
    owner = 'v7-views-' + template
    rec = q3._project(env, owner, template, 'Presentation views')
    q3._run(env, owner, rec)
    before = get_workspace_state(owner, rec.project_id)
    with mock.patch('app.v2.router._build_financial_statements_ctx', side_effect=AssertionError('eager FS')):
        page = q3._get(env, owner, rec)
    assert page.status_code == 200
    assert 'data-model-view-state="pending"' in page.text
    content_hash, _ = q3._tokens(page.text)
    params = {'project': rec.project_code, 'content_hash': content_hash, 'presentation_only': '1'}
    with mock.patch('app.api.project_runner.run_project', side_effect=AssertionError('read runs engine')):
        for sheet in ('fs', 'returns', 'investor', 'debt', 'run_history', 'capex', 'opex', 'revenue', 'tax', 'inputs', 'project_setup'):
            response = env.client.get('/v2/workbook/grid/sheet', params={**params, 'sheet': sheet}, cookies=env.cookie(owner))
            assert response.status_code == 200, (sheet, response.text[:200])
            assert response.headers['X-Finco-View-Hash'] == content_hash
            assert {part.strip() for part in response.headers['Cache-Control'].split(',')} == {'no-store'}
        with mock.patch('app.v2.router._build_returns_ctx', side_effect=AssertionError('hidden Returns rebuilt')):
            grid = env.client.get('/v2/workbook/grid/panel', params={**params, 'refresh_state': '1'}, cookies=env.cookie(owner))
        assert grid.status_code == 200
        for target in ('v2-input-grid', 'model-workspace-header', 'v2-sheet-overview', 'v2-model-health', 'v2-sheet-scenarios'):
            assert f'id="{target}"' in grid.text
        assert 'id="v2-sheet-returns"' not in grid.text
        with mock.patch('app.v2.post_run_ui.build_post_save_ui_state', side_effect=AssertionError('shared state already rendered')):
            grid_only = env.client.get('/v2/workbook/grid/panel', params={**params, 'refresh_state': '1', 'grid_only': '1'}, cookies=env.cookie(owner))
        assert grid_only.status_code == 200 and grid_only.headers['X-Finco-View-Hash'] == content_hash
        assert 'id="v2-input-grid"' in grid_only.text and 'id="v2-sheet-overview"' not in grid_only.text
    assert get_workspace_state(owner, rec.project_id) == before


def test_presentation_scope_and_final_coherence_fail_closed(env):
    from app.v2.post_run_context import PostRunContextChanged
    owner = 'v7-views-scope'
    rec = q3._project(env, owner, 'generic_solar_reference', 'Coherent views')
    content_hash, _ = q3._tokens(q3._get(env, owner, rec).text)
    params = {'project': rec.project_code, 'sheet': 'fs', 'presentation_only': '1', 'content_hash': content_hash}
    for invalid_hash in ('', 'obsolete-content-hash'):
        response = env.client.get('/v2/workbook/grid/sheet', params={**params, 'content_hash': invalid_hash}, cookies=env.cookie(owner))
        assert response.status_code == 409
        assert 'X-Finco-View-Hash' not in response.headers
    response = env.client.get('/v2/workbook/grid/sheet', params=params, cookies=env.cookie('v7-other-owner'))
    assert response.status_code == 404
    with mock.patch('app.v2.post_run_context.PostRunRequestContext.validate_current', side_effect=PostRunContextChanged('changed during render')):
        response = env.client.get('/v2/workbook/grid/sheet', params=params, cookies=env.cookie(owner))
        grid = env.client.get('/v2/workbook/grid/panel', params={**params, 'refresh_state': '1'}, cookies=env.cookie(owner))
    assert response.status_code == grid.status_code == 409
    assert 'X-Finco-View-Hash' not in response.headers
    assert 'X-Finco-View-Hash' not in grid.headers


def test_reference_refresh_remains_readonly_and_preserves_evidence(env):
    from app.persistence.projects_repository import get_reference_by_template_source
    from app.persistence.workspace_repository import get_workspace_state
    owner = 'v7-reference-viewer'
    q3._project(env, owner, 'generic_solar_reference', 'Reference read check')
    rec = get_reference_by_template_source('generic_solar_reference')
    page = q3._get(env, owner, rec)
    content_hash, _ = q3._tokens(page.text)
    before = get_workspace_state(rec.user_id, rec.project_id)
    response = env.client.get('/v2/workbook/grid/panel', params={'project': rec.project_code,
        'content_hash': content_hash, 'refresh_state': '1'}, cookies=env.cookie(owner))
    assert response.status_code == 200
    assert 'data-editable="false"' in response.text
    assert 'Reference project' in response.text
    assert get_workspace_state(rec.user_id, rec.project_id) == before
