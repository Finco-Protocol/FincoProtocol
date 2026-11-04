"""O1 — the contracts document is protected by its own persisted-document token (Owner decision OD-B1 PROPOSED; strict mode is an activation switch).

Synthetic disposable data only. A fresh composite hash proves nothing about the stored PPA document: Writer A can refresh the workbook identity and still hold
the contracts document it loaded earlier. The token is derived from the PERSISTED bytes in the writer's own exclusive transaction.
"""
import json
import re
import uuid

import pytest

from tests.test_save_all_atomic_v1 import world, _project, _body, _state, _identity, URL  # noqa: F401  (disposable DB, clients, helpers)
from app.workbook import revenue_contracts_service as RC


def _read(world, rec):
    import os
    os.environ["FINCO_MODEL_REACT_V1"] = "1"
    return world.owner.get("/v2/model-react/revenue", params={"project": rec.project_code}).json()


def _doc(world, rec, price, indexation):
    c = _read(world, rec)["contracts"]
    w = c["operating_window"]
    return json.dumps({"version": 2, "technology": c.get("technology") or "solar", "indexation_basis": "OPERATING_YEAR",
                       "streams": [{"id": "ppa", "type": "ppa", "start_date": w["start"], "end_date": w["end"], "volume_share": 1,
                                    "price_eur_mwh": price, "indexation_rate": indexation, "source_ref": "Entered in FINCO workspace",
                                    "settlement": "SAME_PERIOD"}]})


def _stored(world, rec):
    return json.loads(_read(world, rec)["contracts"]["raw"])["streams"][0]


def _save(world, rec, doc, token=None, **over):
    body = _body(rec, world.owner, cells=[], cost_lines=[], contracts_json=doc)
    body.update(over)
    if token is not None:
        body["contracts_base_token"] = token
    return world.owner.post(URL, json=body)


def _token(world, rec):
    return _read(world, rec)["contracts"]["base_token"]


def test_the_read_echo_carries_a_stable_token_that_changes_with_the_persisted_document(world):
    rec = _project()
    t0 = _token(world, rec)
    assert re.fullmatch(r"[0-9a-f]{64}", t0) and _token(world, rec) == t0                       # deterministic, derived from the stored bytes
    assert _save(world, rec, _doc(world, rec, 55, 0.02)).status_code == 200                      # lenient mode: an absent token is accepted
    t1 = _token(world, rec)
    assert t1 != t0
    assert _save(world, rec, _doc(world, rec, 55, 0.02), token=t1, request_id="req-same-bytes-1").status_code == 200
    assert _token(world, rec) == t1                                                               # identical bytes -> identical token (not a counter)


def test_two_writers_a_stale_document_is_refused_with_a_fresh_composite_hash_and_nothing_else_is_written(world):
    rec = _project()
    assert _save(world, rec, _doc(world, rec, 55, 0.02)).status_code == 200
    t_h1 = _token(world, rec)                                                                       # Writer A loads H1
    assert _save(world, rec, _doc(world, rec, 55, 0.03), token=t_h1).status_code == 200            # Writer B saves H2 (indexation 3 %)
    before = _state(rec)
    # A refreshed the WORKBOOK identity (fresh composite hash, built inside _body) but still holds H1's document and token
    cells = [{"field_id": "project_setup.technical.p50_hours", "value": "1611"}]
    r = _save(world, rec, _doc(world, rec, 60, 0.02), token=t_h1, cells=cells)
    assert r.status_code == 409 and r.json()["code"] == "CONTRACTS_BASE_TOKEN_STALE" and r.json()["reload"] is True, r.text
    assert "streams" not in r.text and "0.03" not in r.text                                          # no other writer's document in the answer
    after = _state(rec)
    assert after["draft"] == before["draft"] and after["hash"] == before["hash"] and after["ledger"] == before["ledger"]    # cells too: nothing
    assert after["history"] == before["history"] and _stored(world, rec)["indexation_rate"] == 0.03


def test_strict_mode_missing_blank_and_counterfeit_tokens_fail_closed_and_the_right_token_saves(world, monkeypatch):
    rec = _project()
    assert _save(world, rec, _doc(world, rec, 55, 0.02)).status_code == 200
    monkeypatch.setenv("FINCO_CONTRACTS_BASE_TOKEN_REQUIRED", "1")
    assert RC.token_required()
    before = _state(rec)
    for label, token in (("missing", None), ("blank", ""), ("counterfeit", "0" * 64), ("wrong-length", "abc")):
        r = _save(world, rec, _doc(world, rec, 70, 0.02), token=token)
        code = "CONTRACTS_BASE_TOKEN_REQUIRED" if label in ("missing", "blank") else "CONTRACTS_BASE_TOKEN_STALE"
        assert r.status_code == 409 and r.json()["code"] == code and r.json()["reload"] is True, (label, r.text)
    assert _state(rec) == before
    ok = _save(world, rec, _doc(world, rec, 70, 0.02), token=_token(world, rec))
    assert ok.status_code == 200 and _stored(world, rec)["price_eur_mwh"] == 70


def test_a_cells_only_save_all_does_not_need_the_contracts_token_even_in_strict_mode(world, monkeypatch):
    rec = _project()
    monkeypatch.setenv("FINCO_CONTRACTS_BASE_TOKEN_REQUIRED", "1")
    body = _body(rec, world.owner, cost_lines=[], cells=[{"field_id": "project_setup.technical.p50_hours", "value": "1611"}])
    assert world.owner.post(URL, json=body).status_code == 200


def test_replay_of_a_committed_request_is_not_re_checked_against_the_new_document(world):
    rec = _project()
    assert _save(world, rec, _doc(world, rec, 55, 0.02)).status_code == 200
    t = _token(world, rec)
    first = _body(rec, world.owner, cells=[], cost_lines=[], contracts_json=_doc(world, rec, 56, 0.02), contracts_base_token=t, request_id="req-replay-0001")
    assert world.owner.post(URL, json=first).status_code == 200
    again = world.owner.post(URL, json=first)                                                       # token is stale NOW, but this is the same request
    assert again.status_code == 200 and again.json()["replayed"] is True
    changed = dict(first, contracts_json=_doc(world, rec, 57, 0.02))                               # same id, different body: refused, not a silent save
    assert world.owner.post(URL, json=changed).status_code == 409


def test_the_token_is_bound_to_project_field_and_scenario_scope():
    same = "x-document"
    base = RC.document_token("revenue.multistream.contracts", "p1", "base", same)
    assert base != RC.document_token("revenue.multistream.contracts", "p2", "base", same)          # another project
    assert base != RC.document_token("revenue.multistream.contracts", "p1", "scenario:s1", same)    # another scenario
    assert base != RC.document_token("project_setup.bess.configuration", "p1", "base", same)        # another field
    assert base != RC.document_token("revenue.multistream.contracts", "p1", "base", same + " ")     # one byte


def test_a_token_from_another_project_is_refused(world):
    a, b = _project(), _project()
    assert _save(world, a, _doc(world, a, 55, 0.02)).status_code == 200
    assert _save(world, b, _doc(world, b, 55, 0.02)).status_code == 200                              # identical text in both projects
    r = _save(world, a, _doc(world, a, 61, 0.02), token=_token(world, b))
    assert r.status_code == 409 and r.json()["code"] == "CONTRACTS_BASE_TOKEN_STALE"
    assert _stored(world, a)["price_eur_mwh"] == 55


def _form_tokens(world, rec):
    page = world.owner.get("/v2/workbook", params={"project": rec.project_code}).text
    got = {k: re.search(rf'name="{k}" value="([^"]*)"', page).group(1) for k in ("content_hash", "workbook_version", "contracts_base_token")}
    form = re.search(r'<form[^>]*revenue-contracts-form.*?</form>', page, re.S).group(0)
    got["csrf_token"] = re.search(r'name="csrf_token" value="([^"]*)"', form).group(1)
    return got


def test_the_legacy_standalone_route_sends_and_verifies_the_token(world):
    import os
    os.environ["FINCO_MODEL_REACT_V1"] = "1"
    rec = _project()
    assert _save(world, rec, _doc(world, rec, 55, 0.02)).status_code == 200
    tokens = _form_tokens(world, rec)                                                                # Writer A's legacy page: token echoed in the form
    assert re.fullmatch(r"[0-9a-f]{64}", tokens["contracts_base_token"])
    assert _save(world, rec, _doc(world, rec, 55, 0.03), token=tokens["contracts_base_token"]).status_code == 200      # Writer B moves to H2
    fresh = _form_tokens(world, rec)
    stale = dict(fresh, contracts_base_token=tokens["contracts_base_token"])                          # fresh composite hash, stale document token
    r = world.owner.post("/v2/workbook/revenue/contracts", data={"project": rec.project_code, **stale, "action": "save",
                                                                  "contracts": _doc(world, rec, 90, 0.02)})
    assert r.status_code == 409 and r.json()["code"] == "CONTRACTS_BASE_TOKEN_STALE" and r.json()["reload"] is True, r.text
    assert _stored(world, rec)["indexation_rate"] == 0.03
    ok = world.owner.post("/v2/workbook/revenue/contracts", data={"project": rec.project_code, **fresh, "action": "save",
                                                                   "contracts": _doc(world, rec, 90, 0.02)}, follow_redirects=False)
    assert ok.status_code in (200, 303) and _stored(world, rec)["price_eur_mwh"] == 90
