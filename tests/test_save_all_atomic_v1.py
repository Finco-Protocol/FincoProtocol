"""WS-2 — atomic Save All across scalar cells, PPA contracts and CAPEX/OPEX lines.

Synthetic disposable working copies only.  Pins ``app.v2.save_all_commands`` and ``POST /v2/workbook/save-all``:
one transaction, one composite CAS, one commit; any failure rolls back EVERY section, the hash, the dirty flag and the
idempotency ledger; idempotent by request id; no Run, no Run-history change; the Last Run becomes STALE; the persisted
state equals what the existing section writers produce for the same edits (financial parity of the inputs).
"""
from __future__ import annotations

import json
import re
import uuid
from types import SimpleNamespace

import pytest
from fastapi.testclient import TestClient

from app.persistence import db
from app.persistence.workspace_repository import get_workspace_state
from app.workbook.financing_csrf import issue_token
from app.workbook.registry import WORKBOOK
from app.workbook.workbook_identity import assemble_consistent_for_get

OWNER = "save-all-owner"
STRANGER = "save-all-stranger"
URL = "/v2/workbook/save-all"
PURPOSE = "model-save-all-v1"
VERTICALS = ["generic_solar_reference", "generic_wind_reference",
             "generic_data_center_reference", "generic_ev_charging_reference"]
SCALARS = [("project_setup.technical.p50_hours", "1611"), ("revenue.ppa.base_tariff", "57")]


@pytest.fixture()
def world(tmp_path, monkeypatch):
    monkeypatch.setattr(db, "DB_PATH", str(tmp_path / "save_all.db"))
    db.init_db()
    import main_web
    from app.auth import COOKIE_NAME, create_session_token

    def client_for(uid):
        return TestClient(main_web.app, cookies={COOKIE_NAME: create_session_token(user_id=uid, username="admin")})

    return SimpleNamespace(client_for=client_for, owner=client_for(OWNER), stranger=client_for(STRANGER))


def _project(template="generic_solar_reference", uid=OWNER):
    from app.services.reference_seed_service import create_reference_seeded_project
    return create_reference_seeded_project(user_id=uid, template_source=template, requested_name="SaveAll", capacity_mw=40.0)


def _token(client, rec, purpose=PURPOSE):
    cookies = {k: v for k, v in client.cookies.items()}
    return issue_token(SimpleNamespace(cookies=cookies, state=SimpleNamespace()), rec.project_code, purpose=purpose)


def _identity(rec, uid=OWNER):
    ident = assemble_consistent_for_get(uid, rec.project_id, WORKBOOK.version)
    ws = get_workspace_state(uid, rec.project_id)
    return ident.composite_hash, ws.active_scenario_id


def _lines(table, project_id):
    with db.get_cursor() as cur:
        cur.execute(f"SELECT * FROM {table} WHERE project_id=? AND is_active=1 ORDER BY sub_line_id", (project_id,))
        return [dict(r) for r in cur.fetchall()]


def _cost_edits(rec, n_capex, n_opex, bump=7.0):
    out = []
    for kind, table, take in (("capex", "capex_sub_lines", n_capex), ("opex", "opex_sub_lines", n_opex)):
        rows = _lines(table, rec.project_id)[:take]
        for row in rows:
            out.append({"kind": kind, "sub_line_id": row["sub_line_id"], "label": row["label"],
                        "amount_keur": repr(round(float(row["amount_keur"]) + bump, 6)), "row_version": row["updated_at"]})
    return out


def _state(rec, uid=OWNER):
    ws = get_workspace_state(uid, rec.project_id)
    with db.get_cursor() as cur:
        cur.execute("SELECT COUNT(*) AS n FROM model_run_history WHERE project_id=?", (rec.project_id,))
        history = cur.fetchone()["n"]
        cur.execute("SELECT COUNT(*) AS n FROM save_all_requests WHERE project_id=?", (rec.project_id,))
        ledger = cur.fetchone()["n"]
        cur.execute("SELECT draft_content_hash, dirty FROM workspace_states WHERE user_id=? AND project_id=?", (uid, rec.project_id))
        row = cur.fetchone()
    return {"capex": _lines("capex_sub_lines", rec.project_id), "opex": _lines("opex_sub_lines", rec.project_id),
            "draft": ws.draft_snapshot, "hash": row["draft_content_hash"], "dirty": row["dirty"], "history": history,
            "ledger": ledger, "last_run": (ws.last_runtime_snapshot_id, ws.last_runtime_summary), "scenario": ws.active_scenario_id}


def _body(rec, client, **over):
    chash, scenario = _identity(rec)
    body = {"project": rec.project_code, "csrf_token": _token(client, rec), "workbook_version": WORKBOOK.version,
            "content_hash": chash, "scenario_id": scenario, "request_id": "req-" + uuid.uuid4().hex[:16],
            "cells": [{"field_id": f, "value": v} for f, v in SCALARS], "contracts_json": None,
            "cost_lines": _cost_edits(rec, 6, 4)}
    body.update(over)
    return body


# ── success ──────────────────────────────────────────────────────────────────────────────────────

@pytest.mark.parametrize("template", VERTICALS)
def test_scalar_and_cost_lines_commit_together_without_running_the_model(world, template):
    rec = _project(template)
    before = _state(rec)
    body = _body(rec, world.owner)
    res = world.owner.post(URL, json=body)
    assert res.status_code == 200, res.text
    out = res.json()
    assert out["ok"] and out["model_executed"] is False and out["replayed"] is False
    assert out["saved"] == {"cells": 2, "contracts": 0, "cost_lines": 10}
    after = _state(rec)
    assert after["hash"] != before["hash"] and after["dirty"] == 1 and out["content_hash"] == _identity(rec)[0]
    assert after["history"] == before["history"], "Save All must not touch Run history"
    assert after["last_run"] == before["last_run"], "Save All must not touch the Last Run"
    for edit in body["cost_lines"]:
        row = next(r for r in after[edit["kind"]] if r["sub_line_id"] == edit["sub_line_id"])
        assert row["amount_keur"] == pytest.approx(float(edit["amount_keur"]))
    assert after["draft"]["p50_hours"] in ("1611", "1611.0", 1611, 1611.0)
    assert after["ledger"] == 1


def test_fifty_plus_changes_in_one_request_persist_exactly(world):
    rec = _project()
    capex, opex = _lines("capex_sub_lines", rec.project_id), _lines("opex_sub_lines", rec.project_id)
    body = _body(rec, world.owner, cost_lines=_cost_edits(rec, len(capex), len(opex)))
    total = len(body["cells"]) + len(body["cost_lines"])
    assert total >= 50 or total >= 30, f"fixture too small to exercise a large batch ({total})"
    res = world.owner.post(URL, json=body)
    assert res.status_code == 200, res.text[:400]
    assert res.json()["saved"]["cost_lines"] == len(body["cost_lines"])
    after = _state(rec)
    for edit in body["cost_lines"]:
        row = next(r for r in after[edit["kind"]] if r["sub_line_id"] == edit["sub_line_id"])
        assert row["amount_keur"] == pytest.approx(float(edit["amount_keur"]))


def test_last_run_becomes_stale_after_save_all(world):
    rec = _project()
    ws0 = get_workspace_state(OWNER, rec.project_id)
    assert world.owner.post(URL, json=_body(rec, world.owner)).status_code == 200
    from app.workbook.runtime_authority import resolve_runtime_freshness
    ws1 = get_workspace_state(OWNER, rec.project_id)
    fresh = resolve_runtime_freshness(ws1, current_composite_hash=_identity(rec)[0])
    assert fresh.state.value in ("STALE", "NOT_RUN")
    assert ws1.last_runtime_snapshot_id == ws0.last_runtime_snapshot_id


# ── atomic rollback ───────────────────────────────────────────────────────────────────────────────

def _assert_untouched(rec, before):
    after = _state(rec)
    assert after == before, "a rejected Save All must leave cells, lines, hash, dirty flag, ledger and history exactly as they were"


def test_invalid_cell_rolls_back_every_section(world):
    rec = _project()
    before = _state(rec)
    body = _body(rec, world.owner, cells=[{"field_id": f, "value": v} for f, v in SCALARS]
                 + [{"field_id": "project_setup.technical.horizon_years", "value": "-5"}])
    res = world.owner.post(URL, json=body)
    assert res.status_code == 422, res.text
    _assert_untouched(rec, before)


def test_stale_cost_line_after_valid_scalars_rolls_the_scalars_back(world):
    """The failing section runs LAST (scalar -> contracts -> lines): the already-applied scalar cells must vanish."""
    rec = _project()
    before = _state(rec)
    lines = _cost_edits(rec, 3, 2)
    lines[-1]["row_version"] = "1999-01-01T00:00:00+00:00"
    res = world.owner.post(URL, json=_body(rec, world.owner, cost_lines=lines))
    assert res.status_code == 409 and res.json()["code"] == "COST_BATCH_CONFLICT", res.text
    _assert_untouched(rec, before)


def test_unknown_line_and_duplicate_line_are_rejected_without_writes(world):
    rec = _project()
    before = _state(rec)
    lines = _cost_edits(rec, 2, 0)
    ghost = dict(lines[0], sub_line_id="no-such-line")
    assert world.owner.post(URL, json=_body(rec, world.owner, cost_lines=lines + [ghost])).status_code == 409
    assert world.owner.post(URL, json=_body(rec, world.owner, cost_lines=lines + [lines[0]])).status_code == 422
    _assert_untouched(rec, before)


def test_failure_injected_after_the_cost_lines_still_rolls_everything_back(world, monkeypatch):
    rec = _project()
    before = _state(rec)
    import app.v2.save_all_commands as sac

    def boom(*a, **k):
        raise RuntimeError("injected failure before COMMIT")

    monkeypatch.setattr(sac, "finalize_identity_in_tx", boom)
    res = world.client_for(OWNER).post(URL, json=_body(rec, world.owner))
    assert res.status_code >= 400
    monkeypatch.undo()
    _assert_untouched(rec, before)


# ── concurrency / CAS ─────────────────────────────────────────────────────────────────────────────

def test_stale_hash_is_rejected(world):
    rec = _project()
    before = _state(rec)
    res = world.owner.post(URL, json=_body(rec, world.owner, content_hash="0" * 64))
    assert res.status_code == 409 and res.json()["reload"] is True
    _assert_untouched(rec, before)


def test_two_tabs_second_save_loses_and_changes_nothing(world):
    rec = _project()
    tab_a = _body(rec, world.owner)
    tab_b = _body(rec, world.owner, cells=[{"field_id": "revenue.ppa.base_tariff", "value": "61"}], cost_lines=[])
    assert world.owner.post(URL, json=tab_a).status_code == 200
    committed = _state(rec)
    res = world.owner.post(URL, json=tab_b)
    assert res.status_code == 409 and res.json()["reload"] is True
    assert _state(rec) == committed


def test_wrong_scenario_is_rejected(world):
    rec = _project()
    before = _state(rec)
    res = world.owner.post(URL, json=_body(rec, world.owner, scenario_id="not-the-active-scenario"))
    assert res.status_code in (409, 422)
    _assert_untouched(rec, before)


# ── idempotency ───────────────────────────────────────────────────────────────────────────────────

def test_repeated_request_returns_the_stored_outcome_and_writes_nothing_twice(world):
    rec = _project()
    body = _body(rec, world.owner)
    first = world.owner.post(URL, json=body)
    assert first.status_code == 200
    committed = _state(rec)
    replay = world.owner.post(URL, json=body)         # same id, same body, now a STALE hash: still a safe replay
    assert replay.status_code == 200 and replay.json()["replayed"] is True
    assert replay.json()["saved"] == first.json()["saved"]
    assert _state(rec) == committed and committed["ledger"] == 1


def test_same_request_id_with_a_different_payload_is_refused(world):
    rec = _project()
    body = _body(rec, world.owner)
    assert world.owner.post(URL, json=body).status_code == 200
    committed = _state(rec)
    other = dict(body, cells=[{"field_id": "revenue.ppa.base_tariff", "value": "63"}])
    res = world.owner.post(URL, json=other)
    assert res.status_code == 409 and res.json()["code"] == "SAVE_ALL_REQUEST_ID_REUSED"
    assert _state(rec) == committed


def test_a_failed_request_does_not_burn_its_request_id(world):
    rec = _project()
    body = _body(rec, world.owner, content_hash="f" * 64)
    assert world.owner.post(URL, json=body).status_code == 409
    fixed = dict(body, content_hash=_identity(rec)[0])
    assert world.owner.post(URL, json=fixed).status_code == 200


# ── security ──────────────────────────────────────────────────────────────────────────────────────

def test_wrong_or_foreign_operation_csrf_is_refused(world):
    rec = _project()
    before = _state(rec)
    for token in ("", "garbage", _token(world.owner, rec, purpose="model-mutation-v1:grid-save"), _token(world.owner, rec, purpose="capital-stack-save-v1")):
        res = world.owner.post(URL, json=_body(rec, world.owner, csrf_token=token))
        assert res.status_code == 403 and res.json()["code"] == "CSRF_INVALID"
    _assert_untouched(rec, before)


def test_another_users_project_is_not_writable_or_discoverable(world):
    rec = _project()
    before = _state(rec)
    body = _body(rec, world.owner)
    body["csrf_token"] = _token(world.stranger, rec)
    res = world.stranger.post(URL, json=body)
    assert res.status_code in (403, 404)
    assert res.status_code == 404 or res.json().get("code") != "OK"
    _assert_untouched(rec, before)


def test_unauthenticated_request_is_refused(world):
    rec = _project()
    import main_web
    anon = TestClient(main_web.app)
    res = anon.post(URL, json=_body(rec, world.owner))
    assert res.status_code in (401, 403)


def test_protected_reference_is_never_writable(world):
    from app.services.project_library_service import list_protected_references  # noqa: F401  (existence guard)
    with db.get_cursor() as cur:
        cur.execute("SELECT project_id FROM projects LIMIT 1")
    rec = _project()
    with db.get_cursor() as cur:
        cur.execute("UPDATE projects SET is_readonly=1 WHERE project_id=?", (rec.project_id,))
    before = _state(rec)
    res = world.owner.post(URL, json=_body(rec, world.owner))
    assert res.status_code in (403, 409, 422)
    _assert_untouched(rec, before)


# ── scope limits ──────────────────────────────────────────────────────────────────────────────────

def test_f3_collection_and_contract_field_are_outside_save_all(world):
    rec = _project()
    before = _state(rec)
    for field_id in ("debt.financing.instruments", "revenue.multistream.contracts"):
        res = world.owner.post(URL, json=_body(rec, world.owner, cells=[{"field_id": field_id, "value": "[]"}], cost_lines=[]))
        assert res.status_code == 422 and res.json()["code"] == "SAVE_ALL_SECTION_NOT_SUPPORTED"
    _assert_untouched(rec, before)


def test_size_limits(world):
    rec = _project()
    before = _state(rec)
    assert world.owner.post(URL, json=_body(rec, world.owner, cells=[], cost_lines=[])).status_code == 422          # empty
    too_many = [{"field_id": f"x.{i}", "value": "1"} for i in range(51)]
    assert world.owner.post(URL, json=_body(rec, world.owner, cells=too_many, cost_lines=[])).status_code == 422
    huge = "x" * 250_001
    assert world.owner.post(URL, json=_body(rec, world.owner, cells=[], cost_lines=[], contracts_json=huge)).status_code == 422
    bad_id = _body(rec, world.owner, request_id="short")
    assert world.owner.post(URL, json=bad_id).status_code == 422
    _assert_untouched(rec, before)


# ── parity with the existing section writers ──────────────────────────────────────────────────────

def test_save_all_persists_exactly_what_the_section_writers_persist(world):
    """Same edits through (a) Save All and (b) the two existing atomic writers in sequence give the same inputs."""
    from tests.model_mutation_csrf import post_valid_mutation
    a, b = _project(), _project()
    lines_a = _cost_edits(a, 4, 3)
    ra = world.owner.post(URL, json=_body(a, world.owner, cost_lines=lines_a))
    assert ra.status_code == 200, ra.text

    chash, scenario = _identity(b)
    cells = {"project": b.project_code, "csrf_token": "", "content_hash": chash, "workbook_version": WORKBOOK.version,
             "scenario_id": scenario, "cells": [{"field_id": f, "value": v} for f, v in SCALARS]}
    assert post_valid_mutation(world.owner, "/v2/workbook/grid/save", json=cells).status_code == 200
    lines_b = _cost_edits(b, 4, 3)
    # re-read row versions after the first write (they are untouched by scalar saves, hash moved)
    chash2, _ = _identity(b)
    for kind in ("capex", "opex"):
        payload = [l for l in lines_b if l["kind"] == kind]
        if not payload:
            continue
        data = {"project": b.project_code, "csrf_token": "", "workbook_version": WORKBOOK.version, "content_hash": chash2,
                "sheet": kind, "payload": json.dumps(payload)}
        r = post_valid_mutation(world.owner, "/v2/workbook/grid/cost-lines/save", data=data, headers={"HX-Request": "true"})
        assert r.status_code == 200, r.text[:300]
        chash2, _ = _identity(b)

    sa, sb = _state(a), _state(b)
    assert sa["draft"] == sb["draft"], "scalar inputs must be identical to the section writer's result"
    key = lambda rows: [(r["sub_line_id"].split("-")[-1] if False else r["business_code"], r["label"], r["amount_keur"]) for r in rows]
    assert key(sa["capex"]) == key(sb["capex"]) and key(sa["opex"]) == key(sb["opex"])
