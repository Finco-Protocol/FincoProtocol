"""O1 on the native BESS document (same writer, same token primitive): a stale whole-document save is refused in the writer's transaction.

Synthetic disposable data only. The BESS route is release-closed outside tests; this proves the token contract for when it is opened.
"""
import json

from bs4 import BeautifulSoup

from tests.test_model_decision_workspace_v2 import env, tokens  # noqa: F401
from tests.test_m7_bess_workflow import storage, form, save  # noqa: F401


def _token_field(env, record):
    html = env.client.get('/v2/workbook/bess/inputs', params={'project': record.project_code}).text
    return BeautifulSoup(html, 'html.parser').select_one('input[name="contracts_base_token"]')['value']


def _stored(record):
    from app.persistence.workspace_repository import get_workspace_state
    from app.workbook import bess_config
    return (get_workspace_state('decision-user', record.project_id).draft_snapshot or {}).get(bess_config.SNAPSHOT_KEY)


def test_bess_two_writers_stale_document_is_refused_and_the_current_bytes_survive(env, storage, monkeypatch):
    monkeypatch.setenv('FINCO_CONTRACTS_BASE_TOKEN_REQUIRED', '1')
    a = dict(form(env, storage), contracts_base_token=_token_field(env, storage))         # Writer A loads H1 (+ its token)
    assert save(env, storage, a).status_code == 303                                          # strict mode: the right token saves
    after_b = _stored(storage)                                                               # the persisted bytes now stand for "H2"
    refreshed = form(env, storage)                                                           # A refreshes the composite hash only ...
    stale = dict(a, content_hash=refreshed['content_hash'], csrf_token=refreshed['csrf_token'])   # ... but keeps the H1 document token
    cfg = json.loads(stale['configuration'])
    cfg['variable_om_eur_per_dc_mwh'] = 1
    stale['configuration'] = json.dumps(cfg)
    r = save(env, storage, stale)
    assert r.status_code == 409 and 'changed after this page loaded' in r.json()['error']
    assert _stored(storage) == after_b                                                       # H2 bytes unchanged


def test_bess_strict_mode_refuses_missing_blank_and_counterfeit_tokens(env, storage, monkeypatch):
    monkeypatch.setenv('FINCO_CONTRACTS_BASE_TOKEN_REQUIRED', '1')
    before = _stored(storage)
    base = form(env, storage)
    for extra in ({}, {'contracts_base_token': ''}, {'contracts_base_token': 'f' * 64}, {'contracts_base_token': 'x'}):
        r = save(env, storage, dict(base, **extra))
        assert r.status_code == 409, (extra, r.status_code, r.text)
    assert _stored(storage) == before


def test_bess_form_schema_stays_closed_to_unknown_keys(env, storage):
    r = save(env, storage, dict(form(env, storage), extra='1'))
    assert r.status_code == 409 and 'BESS_FORM_SCHEMA' in r.text
