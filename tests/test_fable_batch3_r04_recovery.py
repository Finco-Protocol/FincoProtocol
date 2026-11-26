"""FINCO 36 Correction G — safe recovery of a persisted invalid R04 contract book (real HTTP, forged storage fixture only).

The stored over-cap book is injected BELOW the validators (fixture only).  Viewing never mutates; no financial output is exposed; every
failed/unauthorized/stale repair leaves the whole state unchanged; the repair goes through the ONE canonical book writer (CAS, CSRF,
owner, scenario, whole proposed-state validation); the prior sealed Run is untouched and a new validated Run succeeds afterwards.
"""
from __future__ import annotations

import json
import re

import pytest

from app.auth import generate_csrf_token
from app.persistence import db
from app.persistence.run_history_repository import get_run_history
from app.persistence.workspace_repository import get_workspace_state
from tests.test_fable_batch3_r04_review_route import MERCHANT, _ppa, book
from tests.test_model_react_wf2_projections_v1 import OWNER, STRANGER, env  # noqa: F401

KEY = "rev_multistream_config_json"


def _post_book(client, record, raw, *, csrf=None, content_hash=None):
    save = client.get("/v2/model-react/revenue", params={"project": record.project_code}).json()["save"] if False else None
    return None


def _contracts_post(env, record, raw, *, client=None, csrf=None, content_hash=None, use_recovery_tokens=True):
    c = client or env.client
    if use_recovery_tokens:
        payload = env.client.get("/v2/model-react/inputs", params={"project": record.project_code}).json()
        tokens = payload["contracts_save"]
    else:
        tokens = env.client.get("/v2/model-react/revenue", params={"project": record.project_code}).json()["save"]
    return c.post("/v2/workbook/revenue/contracts", data={
        "project": record.project_code, "csrf_token": csrf if csrf is not None else tokens["csrf_token"],
        "content_hash": content_hash if content_hash is not None else tokens["content_hash"], "contracts": raw, "action": "save"},
        follow_redirects=False)


def _state(record):
    ws = get_workspace_state(OWNER, record.project_id)
    return dict(ws.draft_snapshot), ws.dirty, len(get_run_history(OWNER, record.project_id))


def _run(env, record):
    contract = env.client.get("/v2/model-react/runs", params={"project": record.project_code}).json()["run_contract"]
    ws = env.client.get("/v2/model-react/workspace", params={"project": record.project_code}).json()
    return env.client.post(contract["url"], data={
        "project": record.project_code, "content_hash": ws["workbook"]["composite_hash"],
        "workbook_version": ws["workbook"]["version"], "csrf_token": contract["csrf_token"]}, follow_redirects=False)


def test_forged_over_cap_book_recovery_view_failed_repairs_unchanged_valid_repair_restores_workspace(env, monkeypatch):
    record = env.create("solar")
    good = book([_ppa("a", "2031-03-01", "2032-03-01", 1000), MERCHANT])
    assert _contracts_post(env, record, good, use_recovery_tokens=False).status_code in (200, 303)
    first = _run(env, record)
    assert first.status_code == 303 and "v2_err" not in first.headers["location"], first.headers["location"]
    sealed = get_run_history(OWNER, record.project_id)
    assert len(sealed) == 1
    # fixture only: forge the stored book below the validators
    snap, dirty, _ = _state(record)
    forged = dict(snap)
    forged[KEY] = book([_ppa("a", "2031-03-01", "2032-03-01", 10 ** 9), MERCHANT])
    with db.get_cursor() as cur:
        cur.execute("UPDATE workspace_states SET draft_snapshot_json=? WHERE project_id=?", (json.dumps(forged), record.project_id))
    before = _state(record)
    # 1. viewing: typed recovery with the exact violation, NO financial outputs, NO mutation
    view = env.client.get("/v2/model-react/inputs", params={"project": record.project_code})
    body = view.json()
    assert view.status_code == 409 and body["code"] == "WORKING_COPY_RECOVERY_REQUIRED"
    issue = body["recovery"]["issues"][0]
    assert issue["field_id"] == "revenue.multistream.contracts" and issue["repairable"] is True
    assert "R04_GLOBAL_P50_CAP_EXCEEDED" in issue["reason"] and "committed" in issue["reason"]
    assert "results" not in body and "grid" not in body and body["contracts_save"]["url"] == "/v2/workbook/revenue/contracts"
    assert _state(record) == before
    monkeypatch.setenv("FINCO_MODEL_REACT_V1", "0")
    page = env.client.get("/v2/workbook", params={"project": record.project_code})
    monkeypatch.setenv("FINCO_MODEL_REACT_V1", "1")
    assert 'data-testid="workbook-recovery-book-form"' in page.text and "R04_GLOBAL_P50_CAP_EXCEEDED" in page.text
    assert _state(record) == before
    # 2. refused repairs: the whole state is unchanged each time
    still_over = book([_ppa("a", "2031-03-01", "2032-03-01", 10 ** 8), MERCHANT])
    attempts = [
        ("still over the cap", _contracts_post(env, record, still_over), 422),
        ("malformed book", _contracts_post(env, record, "{not json"), 422),
        ("bad csrf", _contracts_post(env, record, good, csrf="forged"), 403),
        ("stale hash", _contracts_post(env, record, good, content_hash="0" * 64), 409),
        ("other tenant", _contracts_post(env, record, good, client=env.stranger), 404),
    ]
    for label, resp, status in attempts:
        assert resp.status_code == status, (label, resp.status_code, resp.text[:200])
        assert _state(record) == before, label
    # 3. a valid complete replacement through the canonical writer
    repaired = _contracts_post(env, record, good)
    assert repaired.status_code == 303 and "v2_err" not in repaired.headers.get("location", "")
    snap2, dirty2, hist2 = _state(record)
    assert json.loads(snap2[KEY])["streams"][0]["annual_quantity"]["amount"] == "1000" and hist2 == 1
    assert [e.history_id for e in get_run_history(OWNER, record.project_id)] == [e.history_id for e in sealed]   # earlier sealed Run untouched
    healthy = env.client.get("/v2/model-react/inputs", params={"project": record.project_code})
    assert healthy.status_code == 200 and healthy.json()["ok"] is True
    # 4. freshness is truthful (the saved book is newer than the sealed Run) and a validated NEW Run now succeeds
    assert dirty2 in (1, True)
    second = _run(env, record)
    assert second.status_code == 303 and "v2_err" not in second.headers["location"], second.headers["location"]
    assert len(get_run_history(OWNER, record.project_id)) == 2


def test_run_with_valid_tokens_is_refused_while_the_stored_book_is_invalid(env):
    record = env.create("solar")
    env.client.get("/v2/workbook", params={"project": record.project_code})
    contract = env.client.get("/v2/model-react/runs", params={"project": record.project_code}).json()["run_contract"]
    ws = env.client.get("/v2/model-react/workspace", params={"project": record.project_code}).json()
    data = {"project": record.project_code, "content_hash": ws["workbook"]["composite_hash"],
            "workbook_version": ws["workbook"]["version"], "csrf_token": contract["csrf_token"]}
    snap, _, _ = _state(record)
    forged = dict(snap)
    forged[KEY] = book([_ppa("a", "2031-03-01", "2032-03-01", 10 ** 9), MERCHANT])
    with db.get_cursor() as cur:
        cur.execute("UPDATE workspace_states SET draft_snapshot_json=? WHERE project_id=?", (json.dumps(forged), record.project_id))
    before = _state(record)
    resp = env.client.post(contract["url"], data=data, follow_redirects=False)
    assert resp.status_code != 200 or "COMMITTED" not in resp.text
    if resp.status_code == 303:
        assert "v2_err" in resp.headers["location"] or "recovery" in resp.headers["location"].lower() or "workbook" in resp.headers["location"]
    assert _state(record) == before                                                     # no Run, no History row, no mutation
