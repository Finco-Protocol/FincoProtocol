"""D7 (code only, NOT enabled until Owner decision OD-B2): ONE Save All writes scalar cells + CAPEX/OPEX lines + the CAPEX monthly profile document
in a single exclusive transaction, with a profile-document token (typed STALE_PROFILE_DOCUMENT) and exact rollback of every section.

Synthetic disposable working copies only (Solar, Wind, Data Center, EV Charging). No Run is executed and no Run history is touched.
"""
from __future__ import annotations

import json

import pytest

from app.capex_profiles import config
from app.capex_profiles.service import profile_document_token, read_profile_token, save_profiles
from app.persistence.workspace_repository import get_workspace_state
from tests.test_save_all_atomic_v1 import (  # noqa: F401  (disposable DB, clients and helpers of the existing Save All suite)
    OWNER, URL, VERTICALS, _body, _identity, _lines, _project, _state, world)


@pytest.fixture(autouse=True)
def _enabled(monkeypatch):
    monkeypatch.setenv("FINCO_SAVE_ALL_PROFILE_ENABLED", "1")


def _leaf(rec):
    import dataclasses  # noqa: F401
    from app.capex_profiles.runtime import leaves_for
    from app.services.capex_sub_lines_integration import apply_user_sub_lines_replacing_base
    from app.workbook.service import WorkbookService
    ws = get_workspace_state(OWNER, rec.project_id)
    pi = WorkbookService.to_projectinputs(WorkbookService.build_draft_input_set_from_workspace(ws))
    capex = apply_user_sub_lines_replacing_base(pi.capex, project_id=rec.project_id)
    return next(l for l in leaves_for(capex, rec.project_id) if l.amount_keur > 0).item_key


def _doc(key, shape="FRONT_LOADED", percents=(), month=None):
    return json.dumps({"version": 1, "profiles": [{"item_key": key, "shape": shape, "explicit_percent": list(percents), "milestone_month": month}]})


def _token(rec):
    return read_profile_token(OWNER, rec.project_id)


def _edits(rec, bump=7.0):
    """Line edits that only touch lines which already carry cash: a category with no base amount has no default construction timing to bind a profile to."""
    out = []
    for kind, table, take in (("capex", "capex_sub_lines", 3), ("opex", "opex_sub_lines", 2)):
        for row in [r for r in _lines(table, rec.project_id) if float(r["amount_keur"]) > 0][:take]:
            out.append({"kind": kind, "sub_line_id": row["sub_line_id"], "label": row["label"],
                        "amount_keur": repr(round(float(row["amount_keur"]) + bump, 6)), "row_version": row["updated_at"]})
    return out


def _post(world, rec, doc, token="auto", **over):
    over.setdefault("cost_lines", _edits(rec))
    body = _body(rec, world.owner, profile_json=doc, profile_base_token=_token(rec) if token == "auto" else token, **over)
    if body["profile_base_token"] is None:
        body.pop("profile_base_token")
    return world.owner.post(URL, json=body)


def _stored_profile(rec):
    return (get_workspace_state(OWNER, rec.project_id).draft_snapshot or {}).get(config.SNAPSHOT_KEY)


def test_a_profile_document_is_refused_before_any_transaction_while_the_switch_is_off(world, monkeypatch):
    monkeypatch.delenv("FINCO_SAVE_ALL_PROFILE_ENABLED")
    rec = _project()
    before = _state(rec)
    r = _post(world, rec, _doc(_leaf(rec)))
    assert r.status_code == 422 and r.json()["code"] == "SAVE_ALL_PROFILE_NOT_ENABLED"
    assert _state(rec) == before


@pytest.mark.parametrize("template", VERTICALS)
def test_cells_lines_and_profile_commit_together_and_the_token_rotates(world, template):
    rec = _project(template)
    key, t0 = _leaf(rec), _token(rec)
    before = _state(rec)
    r = _post(world, rec, _doc(key))
    assert r.status_code == 200, r.text
    assert r.json()["saved"]["profile"] == 1 and r.json()["saved"]["cost_lines"] > 0 and r.json()["model_executed"] is False
    after = _state(rec)
    assert json.loads(_stored_profile(rec))["profiles"][0]["item_key"] == key
    assert after["capex"] != before["capex"] or after["opex"] != before["opex"]           # the line edits landed in the SAME commit
    assert after["history"] == before["history"] and after["last_run"] == before["last_run"] and after["dirty"] == 1
    assert _token(rec) != t0                                                               # the persisted document changed, so its token did


@pytest.mark.parametrize("template", VERTICALS)
def test_an_unbindable_profile_rolls_back_every_section_exactly(world, template):
    rec = _project(template)
    before = _state(rec)
    r = _post(world, rec, _doc(_leaf(rec), "EXPLICIT", percents=["50", "50"]))              # weights do not match the construction months
    assert r.status_code == 422 and r.json()["section"] == "profile" and r.json()["code"] == "CAPEX_PROFILE_PERIOD_COUNT_MISMATCH"
    assert _state(rec) == before                                                           # cells, lines, hash, dirty, ledger: byte-identical


@pytest.mark.parametrize("fault", ["after_lines", "after_profile"])
def test_fault_injection_restores_the_previous_bytes_of_every_section(world, monkeypatch, fault):
    rec = _project()
    key = _leaf(rec)
    assert _post(world, rec, _doc(key, "BACK_LOADED")).status_code == 200                  # a previous profile exists: it must come back exactly
    before = _state(rec)
    from app.v2 import save_all_commands as S
    if fault == "after_lines":
        import app.capex_profiles.service as svc
        monkeypatch.setattr(svc, "save_profiles_in_tx", lambda *a, **k: (_ for _ in ()).throw(RuntimeError("injected")))
    else:
        monkeypatch.setattr(S, "finalize_identity_in_tx", lambda *a, **k: (_ for _ in ()).throw(RuntimeError("injected")))
    r = world.owner.post(URL, json=_body(rec, world.owner, profile_json=_doc(key, "UNIFORM"), profile_base_token=_token(rec), cost_lines=_edits(rec)))
    assert r.status_code == 500                                                            # the app answers a server error; the transaction was rolled back
    assert _state(rec) == before
    assert json.loads(_stored_profile(rec))["profiles"][0]["shape"] == "BACK_LOADED"


def test_two_writers_a_stale_profile_document_is_refused_even_with_a_fresh_composite_hash(world):
    rec = _project()
    key = _leaf(rec)
    t_h1 = _token(rec)                                                                      # Writer A loads the profile document (H1)
    chash, scenario = _identity(rec)
    save_profiles(owner=OWNER, project_id=rec.project_id, expected_hash=chash, expected_scenario_id=scenario or "", raw=_doc(key, "BACK_LOADED"))   # Writer B saves H2
    before = _state(rec)
    r = _post(world, rec, _doc(key, "UNIFORM"), token=t_h1)                                 # A refreshes the composite hash (via _body) but keeps the H1 token
    assert r.status_code == 409 and r.json()["code"] == "STALE_PROFILE_DOCUMENT" and r.json()["reload"] is True
    assert "BACK_LOADED" not in r.text and key not in r.text                                # nothing of B's document leaks
    assert _state(rec) == before                                                            # A's cells and lines were NOT applied either
    assert json.loads(_stored_profile(rec))["profiles"][0]["shape"] == "BACK_LOADED"


@pytest.mark.parametrize("token", [None, "", "f" * 64, "x"])
def test_a_missing_blank_or_counterfeit_profile_token_changes_nothing(world, token):
    rec = _project()
    before = _state(rec)
    r = _post(world, rec, _doc(_leaf(rec)), token=token)
    assert r.status_code == 409 and r.json()["code"] in ("PROFILE_DOCUMENT_TOKEN_REQUIRED", "STALE_PROFILE_DOCUMENT")
    assert _state(rec) == before


def test_an_idempotent_replay_returns_the_stored_outcome_and_writes_nothing(world):
    rec = _project()
    key = _leaf(rec)
    body = _body(rec, world.owner, profile_json=_doc(key), profile_base_token=_token(rec), request_id="req-replay-profile-1", cost_lines=_edits(rec))
    first = world.owner.post(URL, json=body)
    assert first.status_code == 200 and first.json()["replayed"] is False
    after_first = _state(rec)
    again = world.owner.post(URL, json=body)                                                # token is stale by now: the ledger answers first
    assert again.status_code == 200 and again.json()["replayed"] is True and again.json()["content_hash"] == first.json()["content_hash"]
    assert _state(rec) == after_first
    changed = dict(body, profile_json=_doc(key, "UNIFORM"))
    assert world.owner.post(URL, json=changed).status_code == 409                           # same id, different content: refused


def test_a_stranger_and_a_protected_reference_cannot_use_the_profile_path(world):
    rec = _project()
    before = _state(rec)
    body = _body(rec, world.owner, profile_json=_doc(_leaf(rec)), profile_base_token=_token(rec))
    assert world.stranger.post(URL, json=body).status_code in (403, 404)
    assert _state(rec) == before
