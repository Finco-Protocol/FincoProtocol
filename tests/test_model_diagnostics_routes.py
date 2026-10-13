"""Read-only authenticated refresh and Last Run lifecycle through real Model V2 routes."""
import json
import re
from unittest import mock

import pytest
import test_model_insight_q3_route as q3

env = q3.env


def payload(response):
    match = re.search(r'<script type="application/json" data-md-payload>(.*?)</script>', response.text, re.S)
    assert match, response.text[:200]
    return json.loads(match.group(1))


@pytest.mark.parametrize("template", q3.VERTICALS.values())
def test_refresh_no_engine_no_write_exact_scope(env, template):
    from app.persistence.workspace_repository import get_workspace_state
    owner = 'diagnostic-read-' + template
    rec = q3._project(env, owner, template, 'Diagnostics read')
    q3._run(env, owner, rec)
    before = get_workspace_state(owner, rec.project_id)
    with mock.patch('app.api.project_runner.run_project', side_effect=AssertionError('GET engine execution forbidden')):
        response = env.client.get('/v2/workbook/diagnostics', params={'project': rec.project_code}, cookies=env.cookie(owner))
    assert response.status_code == 200
    assert {v.strip() for v in response.headers['cache-control'].split(',')} == {'no-store'}
    data = payload(response)
    assert data['identity']['snapshot_id'] == before.last_runtime_snapshot_id
    assert data['state'] == 'CURRENT' and len(data['checks']) == 30
    assert 'id="v2-model-health" hx-swap-oob="true"' in response.text
    assert get_workspace_state(owner, rec.project_id) == before
    other = env.client.get('/v2/workbook/diagnostics', params={'project': rec.project_code}, cookies=env.cookie('intruder'))
    assert other.status_code == 404 and 'data-md-payload' not in other.text
    # Existing demo middleware provisions a signed isolated anonymous identity.
    # That identity is NOT this project owner; retain the canonical 404 boundary.
    env.client.cookies.clear()
    anonymous = env.client.get('/v2/workbook/diagnostics', params={'project': rec.project_code})
    assert anonymous.status_code == 404 and 'data-md-payload' not in anonymous.text
    with mock.patch('app.v2.router.resolve_request_session', return_value=None):
        unauth = env.client.get('/v2/workbook/diagnostics', params={'project': rec.project_code})
    assert unauth.status_code == 401 and 'data-md-payload' not in unauth.text


def test_failed_run_keeps_prior_successful_diagnostics(env):
    from app.persistence.workspace_repository import get_workspace_state
    owner = 'diagnostic-failed-run'
    rec = q3._project(env, owner, 'generic_solar_reference', 'Diagnostics failed Run')
    q3._run(env, owner, rec)
    before = get_workspace_state(owner, rec.project_id)
    h, v = q3._tokens(q3._get(env, owner, rec).text)
    with mock.patch('app.api.project_runner.run_project', side_effect=RuntimeError('synthetic failed Run')):
        env.client.post('/v2/workbook/run', data={'project':rec.project_code,'content_hash':h,'workbook_version':v},
                        cookies=env.cookie(owner), headers={'HX-Request':'true'})
    after = get_workspace_state(owner, rec.project_id)
    assert after.last_runtime_snapshot_id == before.last_runtime_snapshot_id
    assert after.last_integrity_evidence == before.last_integrity_evidence
    assert after.last_runtime_summary == before.last_runtime_summary
    data = payload(env.client.get('/v2/workbook/diagnostics', params={'project':rec.project_code}, cookies=env.cookie(owner)))
    assert data['identity']['snapshot_id'] == before.last_runtime_snapshot_id


def test_protected_reference_diagnostics_read_only(env):
    from app.services.project_library_service import ensure_reference_models
    ensure_reference_models()
    response = env.client.get('/v2/workbook/diagnostics', params={'project':'generic_solar_reference-reference'},
                              cookies=env.cookie('diagnostic-reference-reader'))
    assert response.status_code == 200
    assert 'v2-sheet-diagnostics' in response.text
    assert 'data-md-row' not in response.text  # no fabricated checks for NOT_RUN reference
    assert 'hx-post' not in response.text
