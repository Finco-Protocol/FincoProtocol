"""Run/Clone reject unbound CSRF before engine execution or persistence."""
from types import SimpleNamespace

import pytest
from bs4 import BeautifulSoup

from app import auth
from app.workbook.financing_csrf import issue_token
from tests.test_model_react_ux040506_v1 import env, flag_on, OWNER


def state(record):
    from app.persistence.workspace_repository import get_workspace_state
    from app.persistence.db import get_connection
    with get_connection() as connection:
        history = [tuple(row) for row in connection.execute(
            'SELECT * FROM model_run_history WHERE project_id=?', (record.project_id,))]
        projects = [tuple(row) for row in connection.execute('SELECT * FROM projects ORDER BY project_id')]
    return get_workspace_state(OWNER, record.project_id), history, projects


def run_form(env, record):
    page = env.client.get('/v2/workbook', params={'project': record.project_code})
    form = BeautifulSoup(page.text, 'html.parser').select_one('#v2-canonical-run-form')
    assert form is not None
    fields = {i['name']: i.get('value', '') for i in form.select('input[name]')}
    fields['csrf_token'] = fields.pop('run_csrf_token')
    return fields


def token(client, project='', purpose='library-clone-v1'):
    return issue_token(SimpleNamespace(cookies=dict(client.cookies), state=SimpleNamespace()),
                       project, purpose=purpose)


@pytest.mark.parametrize('operation', ['run', 'clone'])
@pytest.mark.parametrize('bad', ['missing', 'invalid', 'other_session', 'other_project', 'other_operation', 'unbound', 'expired'])
def test_csrf_rejections_do_not_change_history_project_or_workspace(env, monkeypatch, operation, bad):
    from app.library.router import router as library_router
    env.client.app.include_router(library_router)
    record = env.create()
    data = run_form(env, record) if operation == 'run' else {'csrf_token': token(env.client)}
    if bad == 'missing':
        data.pop('csrf_token')
    elif bad == 'invalid':
        data['csrf_token'] = 'invalid'
    elif bad == 'other_session':
        env.client.cookies.set(auth.COOKIE_NAME, auth.create_session_token(user_id=OWNER, username='different-session'))
    elif bad == 'other_project':
        # Resource binding applies to Run; a Clone token is deliberately scoped
        # to the library operation, not to an inaccessible reference identity.
        data['csrf_token'] = token(env.client, 'other', purpose=('workbook-run-v1' if operation == 'run' else 'library-clone-v1'))
    elif bad == 'other_operation':
        data['csrf_token'] = token(env.client, record.project_code, purpose='capital-stack-save-v1')
    elif bad == 'unbound':
        data['csrf_token'] = auth.generate_csrf_token()
    else:
        import itsdangerous.timed
        with monkeypatch.context() as old_clock:
            old_clock.setattr(itsdangerous.timed.TimestampSigner, 'get_timestamp', lambda self: 1)
            data['csrf_token'] = token(env.client, record.project_code if operation == 'run' else '',
                                       purpose='workbook-run-v1' if operation == 'run' else 'library-clone-v1')
    before = state(record)
    monkeypatch.setattr('app.api.project_runner.run_project', lambda *a, **k: pytest.fail('rejected token executed engine'))
    monkeypatch.setattr('app.services.reference_seed_service.create_seeded_working_copy', lambda **k: pytest.fail('rejected token cloned'))
    url = '/v2/workbook/run' if operation == 'run' else '/library/clone/unknown'
    response = env.client.post(url, data=data, follow_redirects=False)
    assert response.status_code == 403
    assert state(record) == before


@pytest.mark.parametrize('transport', ['react', 'legacy'])
def test_actual_react_run_contract_and_legacy_form_tokens_run_and_stale_hash_preserves_history(env, monkeypatch, transport):
    flag_on(monkeypatch)
    record = env.create()
    data = run_form(env, record)
    contract = env.client.get('/v2/model-react/runs', params={'project': record.project_code}).json()['run_contract']
    assert data['csrf_token'] and contract['csrf_token']
    if transport == 'react':
        data['csrf_token'] = contract['csrf_token']
    else:
        data['run_csrf_token'] = data.pop('csrf_token')
    response = env.client.post(contract['url'], data=data, follow_redirects=False)
    assert response.status_code == 303 and 'v2_err' not in response.headers['location']
    before = state(record)
    assert len(before[1]) == 1
    monkeypatch.setattr('app.api.project_runner.run_project', lambda *a, **k: pytest.fail('stale hash executed engine'))
    monkeypatch.setattr('app.persistence.workspace_repository.v2_atomic_run_commit', lambda *a, **k: pytest.fail('stale hash committed'))
    data['content_hash'] = 'stale-hash'
    response = env.client.post(contract['url'], data=data, follow_redirects=False)
    assert response.status_code == 303 and 'v2_err' in response.headers['location']
    assert state(record) == before
    # HTMX replacement must preserve valid CSRF and fresh identity.
    response = env.client.post(contract['url'], data=data, headers={'HX-Request': 'true'})
    form = BeautifulSoup(response.text, 'html.parser').select_one('#v2-canonical-run-form')
    assert form and form.select_one('[name="run_csrf_token"]')['value']
    assert state(record) == before


def test_valid_clone_real_library_contract_and_legacy_form(env, monkeypatch):
    from app.library.router import router as library_router
    from app.persistence.projects_repository import get_reference_by_template_source
    env.client.app.include_router(library_router)
    flag_on(monkeypatch)
    record = env.create()
    # Fixture seeding creates canonical reference metadata on demand.
    reference = get_reference_by_template_source('generic_solar_reference')
    if reference is None:
        # Use existing seeded public reference creation authority.
        from app.services.project_library_service import ensure_reference_models
        ensure_reference_models()
        reference = get_reference_by_template_source('generic_solar_reference')
    assert reference is not None
    payload = env.client.get('/v2/model-react/library').json()
    before = state(record)
    response = env.client.post('/library/clone/' + reference.project_id,
                               data={'csrf_token': payload['csrf_token']}, follow_redirects=False)
    assert response.status_code == 303 and '/v2/workbook' in response.headers['location']
    assert len(state(record)[2]) == len(before[2]) + 1
    html = env.client.get('/library').text
    form = BeautifulSoup(html, 'html.parser').select_one('form[action^="/library/clone/"]')
    assert form and form.select_one('[name="csrf_token"]')['value']


def test_foreign_run_project_is_404_and_never_changes_history(env, monkeypatch):
    flag_on(monkeypatch)
    record = env.create()
    data = run_form(env, record)
    before = state(record)
    response = env.stranger.post('/v2/workbook/run', data=data, follow_redirects=False)
    assert response.status_code == 404
    assert state(record) == before


def test_valid_clone_token_does_not_grant_access_to_private_or_unknown_project(env):
    from app.library.router import router as library_router
    env.client.app.include_router(library_router)
    record = env.create()
    before = state(record)
    data = {"csrf_token": token(env.stranger)}
    responses = [env.stranger.post("/library/clone/" + source, data=data)
                 for source in (record.project_id, "unknown")]
    assert all(r.status_code == 404 for r in responses)
    assert responses[0].json() == responses[1].json()
    assert state(record) == before


def test_positive_caller_helper_uses_actual_explicit_cookie_instead_of_jar(env, monkeypatch):
    from tests.run_clone_csrf import post_valid_csrf
    from app.auth import COOKIE_NAME, create_session_token
    record = env.create()
    data = run_form(env, record)
    before = state(record)
    # Header session has the same owner but differs from the jar session.
    # A jar-bound token would fail 403 before reaching the stale-hash guard.
    cookie = create_session_token(user_id=OWNER, username="header-session")
    data["content_hash"] = "stale"
    response = post_valid_csrf(env.client, "/v2/workbook/run", data=data,
                               headers={"Cookie": COOKIE_NAME + "=" + cookie}, follow_redirects=False)
    assert response.status_code == 303 and "v2_err" in response.headers["location"]
    assert state(record) == before


@pytest.mark.parametrize("case", ["missing", "invalid", "conflicting"])
def test_legacy_run_token_alias_fails_closed_without_mutation(env, monkeypatch, case):
    record = env.create()
    data = run_form(env, record)
    good = data.pop("csrf_token")
    if case == "invalid":
        data["run_csrf_token"] = "invalid"
    elif case == "conflicting":
        data.update(run_csrf_token=good, csrf_token="different")
    before = state(record)
    monkeypatch.setattr('app.api.project_runner.run_project', lambda *a, **k: pytest.fail('invalid legacy token executed engine'))
    response = env.client.post('/v2/workbook/run', data=data)
    assert response.status_code == 403
    assert state(record) == before
