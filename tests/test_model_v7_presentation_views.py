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
        ws_resp = env.client.get(f'/v2/model-react/workspace?project={rec.project_code}', cookies=env.cookie(owner))
    assert ws_resp.status_code == 200
    assert ws_resp.json()['freshness']['state'] == 'CURRENT'
    content_hash, _ = q3._tokens(env, owner, rec)
    with mock.patch('app.api.project_runner.run_project', side_effect=AssertionError('read runs engine')):
        for endpoint in (
            f'/v2/model-react/statements?project={rec.project_code}',
            f'/v2/model-react/financing/studio?project={rec.project_code}',
            f'/v2/model-react/diagnostics?project={rec.project_code}',
            f'/v2/model-react/trust?project={rec.project_code}',
            f'/v2/model-react/inputs?project={rec.project_code}',
            f'/v2/model-react/revenue?project={rec.project_code}',
            f'/v2/model-react/costlines?project={rec.project_code}&sheet=capex',
            f'/v2/model-react/costlines?project={rec.project_code}&sheet=opex',
            f'/v2/model-react/fields/project_setup?project={rec.project_code}',
            f'/v2/model-react/fields/debt?project={rec.project_code}',
        ):
            response = env.client.get(endpoint, cookies=env.cookie(owner))
            assert response.status_code == 200, (endpoint, response.text[:200])
            assert response.json()['ok'] is True
            assert 'no-store' in {part.strip() for part in response.headers.get('Cache-Control', '').split(',')}
        ws_again = env.client.get(f'/v2/model-react/workspace?project={rec.project_code}', cookies=env.cookie(owner))
        assert ws_again.status_code == 200 and ws_again.json()['workbook']['composite_hash'] == content_hash
    assert get_workspace_state(owner, rec.project_id) == before


def test_presentation_scope_and_final_coherence_fail_closed(env):
    from app.v2.post_run_context import PostRunContextChanged
    owner = 'v7-views-scope'
    rec = q3._project(env, owner, 'generic_solar_reference', 'Coherent views')
    q3._run(env, owner, rec)
    other = env.cookie('v7-other-owner')
    for endpoint in (
        f'/v2/model-react/statements?project={rec.project_code}',
        f'/v2/model-react/financing/studio?project={rec.project_code}',
        f'/v2/model-react/diagnostics?project={rec.project_code}',
        f'/v2/model-react/trust?project={rec.project_code}',
    ):
        assert env.client.get(endpoint, cookies=other).status_code == 404
    with mock.patch('app.v2.post_run_context.PostRunRequestContext.validate_current', side_effect=PostRunContextChanged('changed during render')):
        studio = env.client.get(f'/v2/model-react/financing/studio?project={rec.project_code}', cookies=env.cookie(owner))
        diag = env.client.get(f'/v2/model-react/diagnostics?project={rec.project_code}', cookies=env.cookie(owner))
        trust = env.client.get(f'/v2/model-react/trust?project={rec.project_code}', cookies=env.cookie(owner))
    assert studio.status_code == diag.status_code == trust.status_code == 503
    assert not studio.json()['ok'] and not diag.json()['ok'] and not trust.json()['ok']


def test_reference_refresh_remains_readonly_and_preserves_evidence(env):
    from app.persistence.projects_repository import get_reference_by_template_source
    from app.persistence.workspace_repository import get_workspace_state
    owner = 'v7-reference-viewer'
    q3._project(env, owner, 'generic_solar_reference', 'Reference read check')
    rec = get_reference_by_template_source('generic_solar_reference')
    before = get_workspace_state(rec.user_id, rec.project_id)
    for endpoint in (
        f'/v2/model-react/workspace?project={rec.project_code}',
        f'/v2/model-react/inputs?project={rec.project_code}',
        f'/v2/model-react/diagnostics?project={rec.project_code}',
    ):
        response = env.client.get(endpoint, cookies=env.cookie(owner))
        assert response.status_code == 200
        assert response.json()['project']['protected_reference'] is True
    assert get_workspace_state(rec.user_id, rec.project_id) == before
