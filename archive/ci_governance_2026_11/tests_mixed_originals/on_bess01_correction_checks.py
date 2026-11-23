"""Opt-in negative controls for the reviewed Correction A handoff."""
import ast
import json
import os
import subprocess
from contextlib import contextmanager

import pytest

from tests import on_bess01_scope as B
from tests.on_bess01_router_review import violations
from tests.on_bess01_contract_checks import client, payload


def sources():
    router = (B.ROOT / 'app/v2/bess_setup_router.py').read_text()
    parent = (B.ROOT / 'app/v2/react_poc_router.py').read_text()
    old = subprocess.check_output(['git', 'show', B.BASE + ':app/v2/react_poc_router.py'], cwd=B.ROOT).decode()
    return router, parent, old


@pytest.mark.parametrize('old,new', [
    ('not react_poc_enabled()', 'False'),
    ('resolve_request_session(request) is None', 'False'),
    ('origin and origin.rstrip', 'False and origin.rstrip'),
    ('== "cross-site"', '== "same-site"'),
    ('!= "application/json"', '== "application/json"'),
    ('len(data) > MAX_BYTES', 'False'),
    ('MAX_BYTES = 2_100_000', 'MAX_BYTES = 9_999_999'),
    ('extra="forbid"', 'extra="allow"'),
    ('strict=True', 'strict=False'),
    ('not validate_csrf_token(', 'validate_csrf_token('),
    ('extract_bound_token(request, body.request_id, body.csrf_token, purpose=PURPOSE)', 'body.csrf_token'),
    ('PURPOSE = "on-bess-01-preview"', 'PURPOSE = "new-project-create"'),
    ('if not cap["preview_supported"]:', 'if False:'),
    ('"persisted": False', '"persisted": True'),
    ('"financial_calculation_count": 0', '"financial_calculation_count": 1'),
    ('"message": message', '"message": str(exc)'),
    ('"preview": result', '"preview": body.native_json'),
    ('    cap = capability()', '    save_project(body)\n    cap = capability()'),
    ('@router.post(', '@router.put('),
])
def test_structural_rejections_are_independent_of_git_pin(old, new):
    router, parent, baseline = sources()
    changed = router.replace(old, new)
    assert changed != router
    assert violations(changed, parent, baseline)
    assert not violations(router + '\n# formatting only\n', parent, baseline)


@pytest.mark.parametrize('addition', [
    '\nrouter.include_router(other_router)\n',
    '\nrouter.add_api_route("/extra", bess_preview, methods=["POST"])\n',
    '\nasync def extra(t):\n    return validate_csrf_token(t)\n',
    '\nfrom app.persistence.db import get_cursor\n',
    '\nrouter = APIRouter()\n',
])
def test_extra_registration_call_or_import_is_refused(addition):
    router, parent, baseline = sources()
    assert violations(router + addition, parent, baseline)
    assert violations(router, parent + addition, baseline)


@pytest.mark.parametrize('path', [
    'app/v2/react_opex_lines.py',
    'financial_engine/cfads.py',
    'tax_reference_registry/records.py',
    'tests/test_trust_readiness_controls.py',
    'app/workbook/bess_config.py',
])
def test_foreign_app_engine_tax_and_original_assertions_fail_closed(path):
    p = B.ROOT / path
    raw = p.read_bytes()
    try:
        p.write_bytes(raw + b'\n')
        assert not B.exact_blobs_ok()
        from tests import fin_v2_cohorts as C
        assert not C.valid()
    finally:
        p.write_bytes(raw)
    assert B.exact_blobs_ok()


def test_repinning_an_unsafe_router_does_not_repair_structure():
    p = B.ROOT / 'app/v2/bess_setup_router.py'
    m = B.ROOT / B.MANIFEST
    raw, seal = p.read_bytes(), m.read_bytes()
    try:
        p.write_bytes(raw.replace(b'not validate_csrf_token(', b'validate_csrf_token('))
        d = json.loads(seal)
        d['source_blobs'][str(p.relative_to(B.ROOT))] = B._blob(p.read_bytes())
        m.write_text(json.dumps(d))
        assert not B.signature_ok()
        assert not B.exact_blobs_ok()
    finally:
        p.write_bytes(raw)
        m.write_bytes(seal)


def test_current_map_cannot_forge_a_foreign_pin_even_when_repinned():
    p = B.ROOT / 'docs/ci_v4/SOURCE_SUCCESSOR.json'
    m = B.ROOT / B.MANIFEST
    raw, seal = p.read_bytes(), m.read_bytes()
    try:
        d = json.loads(raw)
        d['source_blobs']['tools/ci_v4_select.py'] = '0' * 40
        p.write_text(json.dumps(d))
        s = json.loads(seal)
        s['source_blobs'][str(p.relative_to(B.ROOT))] = B._blob(p.read_bytes())
        m.write_text(json.dumps(s))
        assert not B.exact_blobs_ok()
    finally:
        p.write_bytes(raw)
        m.write_bytes(seal)


def test_unregistered_csrf_caller_and_symlink_are_refused():
    p = B.ROOT / 'app/v2/bess_unregistered.py'
    try:
        p.write_text('from app.auth import validate_csrf_token\nx = validate_csrf_token(None)\n')
        assert not B.exact_blobs_ok()
    finally:
        p.unlink()
    p = B.ROOT / 'app/v2/bess_setup_router.py'
    raw = p.read_bytes()
    try:
        p.unlink()
        p.symlink_to(B.ROOT / 'tests/on_bess01_router_review.py')
        assert not B.exact_blobs_ok()
    finally:
        p.unlink()
        p.write_bytes(raw)


def test_orphan_commit_has_no_parent_authority():
    tree = subprocess.check_output(['git', 'write-tree'], cwd=B.ROOT).decode().strip()
    identity = dict(os.environ, GIT_AUTHOR_NAME='FINCO synthetic control', GIT_AUTHOR_EMAIL='synthetic.invalid',
                    GIT_COMMITTER_NAME='FINCO synthetic control', GIT_COMMITTER_EMAIL='synthetic.invalid')
    orphan = subprocess.check_output(['git', 'commit-tree', tree], input=b'Synthetic orphan control\n', cwd=B.ROOT, env=identity).decode().strip()
    assert not B.exact_blobs_ok(ref=orphan)


def test_all_original_assertions_remain_identical_to_accepted_main():
    for path in B.FROZEN | {'tests/test_ux_pr3b2_scope.py'}:
        if not path.startswith('tests/'):
            continue
        before = subprocess.check_output(['git', 'show', B.BASE + ':' + path], cwd=B.ROOT)
        current = (B.ROOT / path).read_bytes()
        assertions = lambda raw: [ast.dump(n) for n in ast.walk(ast.parse(raw)) if isinstance(n, ast.Assert)]
        assert assertions(before) == assertions(current), path


def test_dropped_registration_never_self_authorizes(monkeypatch):
    from tests import fin_v2_cohorts as C
    monkeypatch.setattr(C, 'COHORT_MODULES', tuple(n for n in C.COHORT_MODULES if n != B.__name__))
    assert not B.exact_blobs_ok()
    assert not C.valid()


def test_direct_router_import_has_no_partial_initialization():
    completed = subprocess.run([os.sys.executable, '-c',
        'from app.v2.bess_setup_router import router; assert len(router.routes) == 2'],
        cwd=B.ROOT, capture_output=True, text=True)
    assert completed.returncode == 0, completed.stderr


@pytest.mark.parametrize('fault', ['expired', 'purpose', 'session'])
def test_signed_tokens_refuse_expiry_wrong_purpose_and_same_actor_new_session(client, fault):
    import time
    from itsdangerous import URLSafeTimedSerializer, TimestampSigner
    from starlette.requests import Request
    from app import auth
    from app.workbook import financing_csrf as F
    from app.v2.bess_setup_router import PURPOSE
    body = payload(client)
    cookie = client.cookies.get(auth.COOKIE_NAME)
    request = Request({'type': 'http', 'headers': [(b'cookie', (auth.COOKIE_NAME + '=' + cookie).encode())]})
    if fault == 'purpose':
        body['csrf_token'] = F.issue_token(request, body['request_id'], purpose='new-project-create')
    elif fault == 'expired':
        class ExpiredSigner(TimestampSigner):
            def get_timestamp(self):
                return int(time.time()) - 90_000
        old = URLSafeTimedSerializer(auth.CSRF_SECRET, signer=ExpiredSigner).dumps('a' * 48)
        binding = F._session_binding(request, body['request_id'])
        body['csrf_token'] = old + '.' + F._digest(binding, old, PURPOSE)
    else:
        client.cookies.set(auth.COOKIE_NAME, auth.create_session_token(user_id='synthetic-bess-owner', username='renewed-session'))
    assert client.post('/v2/model-react/new-project/bess-preview', json=body).status_code == 403


def test_flag_disables_both_routes(client, monkeypatch):
    body = payload(client)
    monkeypatch.setenv('FINCO_MODEL_REACT_V1', '0')
    assert client.get('/v2/model-react/new-project/bess-options').status_code == 404
    assert client.post('/v2/model-react/new-project/bess-preview', json=body).status_code == 404


def test_options_requires_an_authenticated_session(client):
    client.cookies.clear()
    assert client.get('/v2/model-react/new-project/bess-options').status_code == 401


def test_availability_is_rechecked_after_native_parsing(client, monkeypatch):
    from app.v2 import bess_setup_router as R
    from app.services.bess_setup_preview import capability
    body = payload(client)
    answers = iter([capability(), {**capability(), 'preview_supported': False}])
    monkeypatch.setattr(R, 'capability', lambda: next(answers))
    response = client.post('/v2/model-react/new-project/bess-preview', json=body)
    assert response.status_code == 409
    assert response.json()['persisted'] is False


def test_hidden_foreign_drift_cannot_use_git_index_flags():
    path = 'app/v2/react_opex_lines.py'
    p = B.ROOT / path
    raw = p.read_bytes()
    subprocess.run(['git', 'update-index', '--assume-unchanged', path], cwd=B.ROOT, check=True)
    try:
        p.write_bytes(raw + b'\n')
        assert not B.exact_blobs_ok()
    finally:
        p.write_bytes(raw)
        subprocess.run(['git', 'update-index', '--no-assume-unchanged', path], cwd=B.ROOT, check=True)
    assert B.exact_blobs_ok()


@contextmanager
def evidence_file(path, raw):
    p = B.ROOT / path
    old = p.read_bytes() if p.exists() else None
    mode = p.stat().st_mode if p.exists() else 0o644
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_bytes(raw)
    try:
        yield p
    finally:
        if p.is_symlink():
            p.unlink()
        if old is None:
            p.unlink(missing_ok=True)
        else:
            p.write_bytes(old)
            p.chmod(mode)
        for parent in p.parents:
            if parent == B.ROOT or B.ROOT not in parent.parents:
                break
            try:
                parent.rmdir()
            except OSError:
                break


def real_attestation():
    from tools.ci_acceptance import attest
    head = subprocess.check_output(['git', 'rev-parse', 'HEAD'], cwd=B.ROOT).decode().strip()
    return attest(head)


def test_existing_workflow_attestation_is_data_and_never_source_ownership():
    from tests import fin_v2_cohorts as C
    from tests.test_trust_readiness_controls import test_known_gap_state_changing_posts_have_no_csrf_token
    path = 'evidence/source.json'
    with evidence_file(path, json.dumps(real_attestation()).encode()):
        assert path not in B.OWNED_PATHS | B.SUPERSEDED
        assert B.allowed_path(path) and B.exact_blobs_ok() and C.valid()
        test_known_gap_state_changing_posts_have_no_csrf_token()
    assert B.exact_blobs_ok()


@pytest.mark.parametrize('fault', ['head', 'tree', 'extra-key', 'mode', 'symlink'])
def test_workflow_attestation_never_admits_forgery_or_foreign_modes(fault):
    d = real_attestation()
    if fault in ('head', 'tree'):
        d[fault] = '0' * 40
    elif fault == 'extra-key':
        d['source_override'] = 'app/unreviewed.py'
    with evidence_file('evidence/source.json', json.dumps(d).encode()) as p:
        if fault == 'mode':
            p.chmod(0o755)
        elif fault == 'symlink':
            p.unlink()
            p.symlink_to(B.ROOT / 'docs/bess_setup/SOURCE_SUCCESSOR.json')
        assert not B.exact_blobs_ok()
    assert B.exact_blobs_ok()


@pytest.mark.parametrize('path,raw', [
    ('evidence/unreviewed.json', b'{}'),
    ('evidence/source.py', b'unsigned = True\n'),
    ('evidence/browser/solar-0.056.png', b'not a PNG'),
    ('evidence/financial/solar-rate-0.056.json', b'not JSON'),
    ('evidence/native.xml', b'<!DOCTYPE x><testsuite/>'),
])
def test_data_exception_has_no_prefix_glob_or_executable_escape(path, raw):
    with evidence_file(path, raw):
        assert not B.exact_blobs_ok()
    assert B.exact_blobs_ok()
