"""Capital Stack CSRF is actor/session/project bound without replacing CAS."""
import json
from types import SimpleNamespace

from bs4 import BeautifulSoup
import pytest

from app import auth
from app.workbook import financing_csrf, multisenior_config as config
from tests.test_model_decision_workspace_v2 import env, tokens  # noqa: F401
from tests.test_financing_f3_junior_workspace import state, working_case


def page_and_data(env, record):
    page = env.client.get('/v2/workbook', params={'project': record.project_code, 'sheet': 'debt'})
    assert page.status_code == 200
    form = BeautifulSoup(page.text, 'html.parser').select_one('[data-f3-form]')
    assert form is not None
    data = {i['name']: i.get('value', '') for i in form.select('input[type="hidden"][name]')}
    from app.persistence.workspace_repository import get_workspace_state
    proposal = json.loads(state(working_case(get_workspace_state('decision-user', record.project_id))))
    proposal['scopes']['base']['activation'] = None
    data['value'] = json.dumps(proposal)
    assert data['csrf_token']
    return page, data


def saved_state(record):
    from app.persistence.workspace_repository import get_workspace_state
    from app.persistence.db import get_connection
    with get_connection() as connection:
        history = [tuple(r) for r in connection.execute(
            'SELECT * FROM model_run_history WHERE project_id=?', (record.project_id,))]
    return get_workspace_state('decision-user', record.project_id), history


@pytest.mark.parametrize('bad', ['missing', 'invalid', 'forged', 'unicode', 'expired', 'other_session', 'other_project'])
def test_rejected_token_never_mutates_working_copy_or_history(env, monkeypatch, bad):
    record = env.create()
    _, data = page_and_data(env, record)
    if bad == 'missing':
        data.pop('csrf_token')
    elif bad == 'invalid':
        data['csrf_token'] = 'invalid'
    elif bad == 'forged':
        data['csrf_token'] = data['csrf_token'][:-1] + ('0' if data['csrf_token'][-1] != '0' else '1')
    elif bad == 'unicode':
        data['csrf_token'] = 'payload.' + chr(233) * 64
    elif bad == 'expired':
        import itsdangerous.timed
        with monkeypatch.context() as old_clock:
            old_clock.setattr(itsdangerous.timed.TimestampSigner, 'get_timestamp', lambda self: 1)
            expired = auth.generate_csrf_token()
        with monkeypatch.context() as expired_form:
            expired_form.setattr(auth, 'generate_csrf_token', lambda: expired)
            _, data = page_and_data(env, record)
    elif bad == 'other_session':
        env.client.cookies.set(auth.COOKIE_NAME, auth.create_session_token(user_id='decision-user', username='new-session'))
    else:
        other = env.create('wind')
        _, other_data = page_and_data(env, other)
        data['csrf_token'] = other_data['csrf_token']
    before = saved_state(record)
    response = env.client.post('/v2/workbook/update', data=data, headers={'HX-Request': 'true'})
    assert response.status_code == 403
    assert saved_state(record) == before


def test_valid_token_real_save_htmx_rerender_and_stale_cas(env):
    from app.persistence.workspace_repository import get_workspace_state
    record = env.create()
    _, data = page_and_data(env, record)
    response = env.client.post('/v2/workbook/update', data=data, headers={'HX-Request': 'true'})
    assert response.status_code == 200 and 'field-error-banner' not in response.text
    ws = get_workspace_state('decision-user', record.project_id)
    assert config.parse_state(ws.draft_snapshot[config.SNAPSHOT_KEY]) == config.parse_state(data['value'])
    assert ws.dirty
    form = BeautifulSoup(response.text, 'html.parser').select_one('[data-f3-form]')
    rerender = {i['name']: i.get('value', '') for i in form.select('input[type="hidden"][name]')}
    assert rerender['csrf_token'] and rerender['csrf_token'] != data['csrf_token']
    rerender['value'] = data['value']
    second = env.client.post('/v2/workbook/update', data=rerender, headers={'HX-Request': 'true'})
    assert second.status_code == 200 and 'field-error-banner' not in second.text
    before = saved_state(record)
    conflict = env.client.post('/v2/workbook/update', data=data, headers={'HX-Request': 'true'})
    assert conflict.status_code == 200 and 'field-error-banner' in conflict.text
    assert saved_state(record) == before


def test_owner_and_protected_reference_checks_not_replaced_by_csrf(env, monkeypatch):
    record = env.create()
    _, data = page_and_data(env, record)
    before = saved_state(record)
    with monkeypatch.context() as protected:
        protected.setattr('app.services.project_library_service.is_protected_reference', lambda r: True)
        response = env.client.post('/v2/workbook/update', data=data)
        assert response.status_code == 403 and 'protected reference' in response.text
    env.client.cookies.set(auth.COOKIE_NAME, auth.create_session_token(user_id='other-owner', username='admin'))
    assert env.client.post('/v2/workbook/update', data=data).status_code == 404
    assert saved_state(record) == before


def test_binding_requires_real_session_and_supports_existing_demo_resolution():
    cookie = auth.create_session_token(user_id='unit-owner', username='admin')
    request = SimpleNamespace(cookies={auth.COOKIE_NAME: cookie}, state=SimpleNamespace())
    token = financing_csrf.issue_token(request, 'project')
    assert auth.validate_csrf_token(financing_csrf.extract_bound_token(request, 'project', token))
    assert not financing_csrf.extract_bound_token(request, 'other-project', token)
    assert financing_csrf.issue_token(None, 'project') == ''
    assert financing_csrf.issue_token(SimpleNamespace(cookies={}, state=SimpleNamespace()), 'project') == ''
    demo = auth.create_demo_session_token('demo-unit-owner')
    demo_request = SimpleNamespace(cookies={auth.COOKIE_NAME: 'invalid', auth.DEMO_COOKIE_NAME: demo}, state=SimpleNamespace())
    demo_token = financing_csrf.issue_token(demo_request, 'project')
    assert auth.validate_csrf_token(financing_csrf.extract_bound_token(demo_request, 'project', demo_token))
    first_request = SimpleNamespace(cookies={}, state=SimpleNamespace(demo_session_token=demo))
    assert financing_csrf.extract_bound_token(first_request, 'project', demo_token)
