"""CAPEX/OPEX Productivity V1.1 — atomic multi-row Save of EXISTING cost line items.

Synthetic disposable working copies only.  Pins the contract of ``app.v2.cost_batch_commands`` and the
``POST /v2/workbook/grid/cost-lines/save`` route:

* all lines persist in ONE transaction or none (any invalid / stale / unknown / foreign line, a stale
  composite hash, or a failure in the middle of the writes rolls back EVERY row, the hash and the
  dirty flag);
* ownership / reference protection, CSRF, no silent retry;
* Save never runs the engine, never touches the Last Run, Run History or export evidence, and the
  workspace becomes STALE; identical inputs give identical Run results afterwards (no double counting);
* exact numeric preservation and the existing single-row editing contract stay intact.
"""
from __future__ import annotations

import json
import re

import pytest
from fastapi.testclient import TestClient

from app.persistence import db
from app.persistence.workspace_repository import get_workspace_state

OWNER = "cost-batch-owner"
STRANGER = "cost-batch-stranger"
VERTICALS = ["generic_solar_reference", "generic_wind_reference",
             "generic_data_center_reference", "generic_ev_charging_reference"]
URL = "/v2/workbook/grid/cost-lines/save"


@pytest.fixture()
def world(tmp_path, monkeypatch):
    monkeypatch.setattr(db, "DB_PATH", str(tmp_path / "cost_batch.db"))
    db.init_db()
    import main_web
    from app.auth import COOKIE_NAME, create_session_token

    def client_for(uid):
        return TestClient(main_web.app, cookies={COOKIE_NAME: create_session_token(user_id=uid, username="admin")})

    return {"main": main_web, "client_for": client_for, "owner": client_for(OWNER)}


def _project(template="generic_solar_reference", uid=OWNER):
    from app.services.reference_seed_service import create_reference_seeded_project
    return create_reference_seeded_project(user_id=uid, template_source=template, requested_name="Batch", capacity_mw=40.0)


def _tokens(client, rec):
    page = client.get(f"/v2/workbook?project={rec.project_code}")
    assert page.status_code == 200
    m = re.search(r'id="v2-input-grid"[^>]*data-csrf="([^"]+)"[^>]*data-content-hash="([0-9a-f]+)"'
                  r'[^>]*data-workbook-version="([^"]+)"', page.text, re.S)
    csrf, chash, version = m.groups()
    return {"csrf": csrf, "hash": chash, "version": version}


def _rows(table, project_id):
    with db.get_cursor() as cur:
        cur.execute(f"SELECT * FROM {table} WHERE project_id=? AND is_active=1 ORDER BY sub_line_id", (project_id,))
        return [dict(r) for r in cur.fetchall()]


def _snapshot(rec, uid=OWNER):
    ws = get_workspace_state(uid, rec.project_id)
    with db.get_cursor() as cur:
        cur.execute("SELECT COUNT(*) AS n FROM model_run_history WHERE project_id=?", (rec.project_id,))
        history = cur.fetchone()["n"]
        cur.execute("SELECT draft_content_hash, dirty FROM workspace_states WHERE user_id=? AND project_id=?",
                    (uid, rec.project_id))
        row = cur.fetchone()
    return {"capex": _rows("capex_sub_lines", rec.project_id), "opex": _rows("opex_sub_lines", rec.project_id),
            "draft": ws.draft_snapshot, "hash": row["draft_content_hash"], "dirty": row["dirty"],
            "last_run": (ws.last_runtime_snapshot_id, ws.last_runtime_summary), "history": history}


def _edits(rec, count_capex=6, count_opex=4, bump=7.0):
    """Edits for existing lines: (payload dicts, expected new amount per (kind, id))."""
    out, expect = [], {}
    for kind, table, take in (("capex", "capex_sub_lines", count_capex), ("opex", "opex_sub_lines", count_opex)):
        rows = _rows(table, rec.project_id)
        assert len(rows) >= take, f"{rec.template_source} has only {len(rows)} active {kind} lines"
        for row in rows[:take]:
            new_amount = repr(round(float(row["amount_keur"]) + bump, 6))
            item = {"kind": kind, "sub_line_id": row["sub_line_id"], "label": row["label"],
                    "amount_keur": new_amount, "row_version": row["updated_at"]}
            out.append(item)
            expect[(kind, row["sub_line_id"])] = float(new_amount)
    return out, expect


def _post(client, rec, tok, lines, **over):
    data = {"project": rec.project_code, "csrf_token": tok["csrf"], "workbook_version": tok["version"],
            "content_hash": tok["hash"], "sheet": "capex", "payload": json.dumps(lines)}
    data.update(over)
    return client.post(URL, data=data, headers={"HX-Request": "true"})


# ── success ───────────────────────────────────────────────────────────────────────────────────────

@pytest.mark.parametrize("template", VERTICALS)
def test_ten_edits_across_capex_and_opex_persist_atomically_and_exactly(world, template):
    rec = _project(template)
    tok = _tokens(world["owner"], rec)
    before = _snapshot(rec)
    lines, expect = _edits(rec, 6, 4)
    assert len(lines) == 10
    res = _post(world["owner"], rec, tok, lines)
    assert res.status_code == 200, res.text[:400]
    assert res.headers["x-cost-batch-saved"] == "10"
    after = _snapshot(rec)
    for kind in ("capex", "opex"):
        by_id = {r["sub_line_id"]: r for r in after[kind]}
        for r in before[kind]:
            new = by_id[r["sub_line_id"]]
            key = (kind, r["sub_line_id"])
            if key in expect:
                assert new["amount_keur"] == expect[key]                       # exact stored value
                assert new["updated_at"] != r["updated_at"]                    # new row version
            else:
                assert new == r                                                  # untouched rows are byte-identical
    assert after["dirty"] == 1 and after["hash"] != before["hash"]
    assert after["draft"] == before["draft"], "line items must not touch the scalar draft"
    assert after["last_run"] == before["last_run"] and after["history"] == before["history"]
    # the response carries the NEW CAS token for the next command
    new_hash = re.search(r'id="v2-cost-authority-capex"[^>]*data-content-hash="([0-9a-f]+)"', res.text).group(1)
    assert new_hash == after["hash"] != tok["hash"]
    assert 'data-testid="toolbar-runtime-state"' in res.text, "post-Save STALE refresh must ride on the response"


def test_unedited_cells_keep_their_exact_stored_value(world):
    rec = _project()
    tok = _tokens(world["owner"], rec)
    row = _rows("capex_sub_lines", rec.project_id)[0]
    exact = "123.456789012"                                                       # more precision than any display
    assert _post(world["owner"], rec, tok, [{
        "kind": "capex", "sub_line_id": row["sub_line_id"], "label": row["label"],
        "amount_keur": exact, "row_version": row["updated_at"]}]).status_code == 200
    assert _rows("capex_sub_lines", rec.project_id)[0]["amount_keur"] == float(exact)


def test_opex_escalation_and_notes_default_to_the_stored_values(world):
    rec = _project()
    tok = _tokens(world["owner"], rec)
    row = _rows("opex_sub_lines", rec.project_id)[0]
    assert _post(world["owner"], rec, tok, [{
        "kind": "opex", "sub_line_id": row["sub_line_id"], "label": row["label"],
        "amount_keur": "11", "row_version": row["updated_at"]}], sheet="opex").status_code == 200
    new = _rows("opex_sub_lines", rec.project_id)[0]
    assert new["amount_keur"] == 11.0 and new["inflation_pct"] == row["inflation_pct"] and new["comments"] == row["comments"]


# ── all-or-nothing ────────────────────────────────────────────────────────────────────────────────

def _assert_nothing_changed(rec, before):
    assert _snapshot(rec) == before


@pytest.mark.parametrize("breaker,status,code", [
    ("non_finite", 422, "COST_BATCH_INVALID"),
    ("empty_label", 422, "COST_BATCH_INVALID"),
    ("duplicate", 422, "COST_BATCH_INVALID"),
    ("stale_row", 409, "COST_BATCH_CONFLICT"),
    ("unknown_row", 409, "COST_BATCH_CONFLICT"),
])
def test_one_bad_line_rolls_back_every_other_line(world, breaker, status, code):
    rec = _project()
    tok = _tokens(world["owner"], rec)
    before = _snapshot(rec)
    lines, _ = _edits(rec, 4, 3)
    bad = dict(lines[2])
    if breaker == "non_finite":
        lines[2] = {**bad, "amount_keur": "nan"}
    elif breaker == "empty_label":
        lines[2] = {**bad, "label": "   "}
    elif breaker == "duplicate":
        lines.append(dict(lines[0]))
    elif breaker == "stale_row":
        lines[2] = {**bad, "row_version": "1999-01-01T00:00:00+00:00"}
    else:
        lines[2] = {**bad, "sub_line_id": "does-not-exist"}
    res = _post(world["owner"], rec, tok, lines)
    assert res.status_code == status, res.text[:300]
    body = res.json()
    assert body["ok"] is False and body["code"] == code
    assert any(not v["ok"] for v in body["lines"]), "the failing line must be attributed"
    _assert_nothing_changed(rec, before)
    assert (res.headers.get("hx-retarget") is None), "no swap instruction on failure: typed values stay on screen"


def test_stale_composite_hash_is_rejected_without_any_write_and_not_retried(world):
    rec = _project()
    tok = _tokens(world["owner"], rec)
    before = _snapshot(rec)
    lines, _ = _edits(rec, 3, 2)
    res = _post(world["owner"], rec, tok, lines, content_hash="0" * 64)
    assert res.status_code == 409 and res.json()["code"] == "STALE_CONTENT" and res.json()["reload"] is True
    _assert_nothing_changed(rec, before)
    assert _post(world["owner"], rec, tok, lines, workbook_version="stale-version").status_code == 409
    _assert_nothing_changed(rec, before)


def test_concurrent_row_edit_after_page_load_is_a_genuine_409_with_no_partial_write(world):
    rec = _project()
    tok = _tokens(world["owner"], rec)
    lines, _ = _edits(rec, 3, 2)
    # another writer changes ONE staged row through the existing single-row command (rotates hash + version)
    other = lines[1]
    res = world["owner"].post("/v2/capex/line/update", data={
        "project": rec.project_code, "sub_line_id": other["sub_line_id"], "label": other["label"],
        "amount_keur": "999", "row_version": other["row_version"], "workbook_version": tok["version"],
        "content_hash": tok["hash"]}, headers={"HX-Request": "true"})
    assert res.status_code == 200
    mid = _snapshot(rec)
    res = _post(world["owner"], rec, tok, lines)
    assert res.status_code == 409
    _assert_nothing_changed(rec, mid)


def test_failure_in_the_middle_of_the_writes_rolls_back_rows_hash_and_dirty_flag(world, monkeypatch):
    from app.v2 import cost_batch_commands as cb
    rec = _project()
    tok = _tokens(world["owner"], rec)
    before = _snapshot(rec)
    lines, _ = _edits(rec, 3, 3)
    calls = {"n": 0}
    real = cb._update_opex

    def boom(*a, **k):
        calls["n"] += 1
        if calls["n"] == 2:                          # CAPEX rows and one OPEX row are already written
            raise RuntimeError("synthetic failure after partial writes")
        return real(*a, **k)

    monkeypatch.setattr(cb, "_update_opex", boom)
    with pytest.raises(RuntimeError):
        cb.update_cost_lines_batch(
            project_record=rec, user_id=OWNER,
            edits=[cb.CostLineEdit(l["kind"], l["sub_line_id"], l["label"], l["amount_keur"], l["row_version"]) for l in lines],
            workbook_version=tok["version"], expected_content_hash=tok["hash"])
    assert calls["n"] == 2
    _assert_nothing_changed(rec, before)


def test_batch_bound_is_enforced(world):
    rec = _project()
    tok = _tokens(world["owner"], rec)
    row = _rows("capex_sub_lines", rec.project_id)[0]
    one = {"kind": "capex", "sub_line_id": row["sub_line_id"], "label": "x", "amount_keur": "1", "row_version": row["updated_at"]}
    assert _post(world["owner"], rec, tok, []).status_code == 422
    assert _post(world["owner"], rec, tok, [dict(one, sub_line_id=f"{i}") for i in range(51)]).status_code == 422
    assert _post(world["owner"], rec, tok, "not-json").status_code == 422


# ── authority: CSRF, ownership, references, foreign lines ────────────────────────────────────────

def test_csrf_session_ownership_and_unknown_sheet_are_enforced(world):
    rec = _project()
    tok = _tokens(world["owner"], rec)
    before = _snapshot(rec)
    lines, _ = _edits(rec, 2, 1)
    assert _post(world["owner"], rec, tok, lines, csrf_token="forged").status_code == 403
    assert _post(world["owner"], rec, tok, lines, csrf_token="").status_code == 403
    assert _post(world["owner"], rec, tok, lines, sheet="revenue").status_code == 404
    anon = TestClient(world["main"].app)
    assert _post(anon, rec, tok, lines).status_code in (401, 403, 404)
    assert _post(world["client_for"](STRANGER), rec, tok, lines).status_code in (403, 404)
    _assert_nothing_changed(rec, before)


def test_protected_reference_is_never_writable(world):
    from app.persistence.projects_repository import resolve_accessible_project
    page = world["owner"].get("/v2/workbook?project=generic_solar_reference-reference")
    if page.status_code != 200:
        pytest.skip("reference project not seeded in this fixture")
    ref, _owner = resolve_accessible_project(OWNER, "generic_solar_reference-reference")
    assert ref is not None
    before = {"capex": _rows("capex_sub_lines", ref.project_id), "opex": _rows("opex_sub_lines", ref.project_id)}
    # references carry no persisted line items: the request must still be refused for the PROJECT
    rows = before["capex"] or before["opex"] or [{"sub_line_id": "ref-line", "label": "x", "updated_at": "2026-01-01"}]
    kind = "capex" if before["capex"] or not before["opex"] else "opex"
    own = _project()
    tok = _tokens(world["owner"], own)
    res = world["owner"].post(URL, data={
        "project": "generic_solar_reference-reference", "csrf_token": tok["csrf"], "workbook_version": tok["version"],
        "content_hash": tok["hash"], "sheet": "capex",
        "payload": json.dumps([{"kind": kind, "sub_line_id": rows[0]["sub_line_id"], "label": rows[0]["label"],
                                "amount_keur": "1", "row_version": rows[0]["updated_at"]}])})
    assert res.status_code in (403, 404)
    assert before == {"capex": _rows("capex_sub_lines", ref.project_id), "opex": _rows("opex_sub_lines", ref.project_id)}


def test_a_line_of_another_project_is_not_found_and_never_modified(world):
    mine, theirs = _project(), _project(uid=STRANGER)
    tok = _tokens(world["owner"], mine)
    their_before = _snapshot(theirs, STRANGER)
    my_before = _snapshot(mine)
    foreign = _rows("capex_sub_lines", theirs.project_id)[0]
    lines, _ = _edits(mine, 2, 1)
    lines.append({"kind": "capex", "sub_line_id": foreign["sub_line_id"], "label": foreign["label"],
                  "amount_keur": "1", "row_version": foreign["updated_at"]})
    res = _post(world["owner"], mine, tok, lines)
    assert res.status_code == 409
    assert [v["code"] for v in res.json()["lines"] if not v["ok"]] == ["ROW_NOT_FOUND"]
    assert _snapshot(theirs, STRANGER) == their_before
    _assert_nothing_changed(mine, my_before)


def test_a_deactivated_line_cannot_be_saved_through_the_batch(world):
    rec = _project()
    tok = _tokens(world["owner"], rec)
    row = _rows("capex_sub_lines", rec.project_id)[0]
    res = world["owner"].post("/v2/capex/line/deactivate", data={
        "project": rec.project_code, "sub_line_id": row["sub_line_id"], "row_version": row["updated_at"],
        "workbook_version": tok["version"], "content_hash": tok["hash"]}, headers={"HX-Request": "true"})
    assert res.status_code == 200
    tok2 = _tokens(world["owner"], rec)
    before = _snapshot(rec)
    out = _post(world["owner"], rec, tok2, [{"kind": "capex", "sub_line_id": row["sub_line_id"],
                                              "label": row["label"], "amount_keur": "5", "row_version": row["updated_at"]}])
    assert out.status_code == 409 and out.json()["lines"][0]["code"] in ("ROW_INACTIVE", "ROW_STALE")
    _assert_nothing_changed(rec, before)


# ── engine / Last Run / history / scenario ───────────────────────────────────────────────────────

_VOLATILE = {"snapshot_id", "run_id", "timestamp", "executed_at", "computed_at"}


def _economic(value):
    """Drop run identity/timestamps; every economic number must match exactly (no tolerance)."""
    if isinstance(value, dict):
        return {k: _economic(v) for k, v in value.items() if k not in _VOLATILE and not k.endswith("_at")}
    if isinstance(value, list):
        return [_economic(v) for v in value]
    return value


def _run(client, rec):
    tok = _tokens(client, rec)
    res = client.post("/v2/workbook/run", headers={"HX-Request": "true"}, data={
        "project": rec.project_code, "workbook_version": tok["version"], "content_hash": tok["hash"]})
    assert res.status_code == 200, res.text[:300]
    ws = get_workspace_state(OWNER, rec.project_id)
    return ws.last_runtime_snapshot_id, ws.last_runtime_summary


@pytest.mark.parametrize("template", ["generic_solar_reference", "generic_wind_reference"])
def test_save_is_stale_not_current_and_identical_inputs_reproduce_identical_results(world, template):
    rec = _project(template)
    run_id, summary = _run(world["owner"], rec)
    history = _snapshot(rec)["history"]
    originals = {("capex", r["sub_line_id"]): r for r in _rows("capex_sub_lines", rec.project_id)}
    originals.update({("opex", r["sub_line_id"]): r for r in _rows("opex_sub_lines", rec.project_id)})

    tok = _tokens(world["owner"], rec)
    lines, _ = _edits(rec, 3, 2, bump=125.0)
    assert _post(world["owner"], rec, tok, lines).status_code == 200
    ws = get_workspace_state(OWNER, rec.project_id)
    assert (ws.last_runtime_snapshot_id, ws.last_runtime_summary) == (run_id, summary), "Save never changes the Last Run"
    assert _snapshot(rec)["history"] == history, "Save never writes Run History"
    from app.workbook.runtime_authority import resolve_runtime_freshness
    from app.workbook.workbook_identity import assemble_consistent_for_get
    from app.workbook.registry import WORKBOOK
    state = resolve_runtime_freshness(ws, current_composite_hash=assemble_consistent_for_get(
        OWNER, rec.project_id, WORKBOOK.version).composite_hash).state.value
    assert state == "STALE"

    # restore the EXACT original values through the same batch → the canonical Run reproduces the first Run
    tok = _tokens(world["owner"], rec)
    restore = [{"kind": k, "sub_line_id": sid, "label": o["label"], "amount_keur": repr(o["amount_keur"]),
                "row_version": _current_version(k, sid, rec)}
               for (k, sid), o in originals.items() if any(l["sub_line_id"] == sid and l["kind"] == k for l in lines)]
    assert _post(world["owner"], rec, tok, restore).status_code == 200
    new_run_id, new_summary = _run(world["owner"], rec)
    assert new_run_id != run_id
    assert _economic(new_summary) == _economic(summary)


def _current_version(kind, sid, rec):
    table = "capex_sub_lines" if kind == "capex" else "opex_sub_lines"
    return next(r["updated_at"] for r in _rows(table, rec.project_id) if r["sub_line_id"] == sid)


def test_scenario_state_is_consistent_the_batch_uses_the_current_composite_token(world):
    rec = _project()
    tok = _tokens(world["owner"], rec)
    created = world["owner"].post("/v2/workbook/scenarios/create", data={
        "project": rec.project_code, "scenario_name": "Upside", "workbook_version": tok["version"],
        "content_hash": tok["hash"]}, headers={"HX-Request": "true"})
    if created.status_code != 200:
        pytest.skip(f"scenario create unavailable in this fixture: {created.status_code}")
    # The page token of the OLD scenario state is stale now: the batch must be refused, not silently retried.
    lines, _ = _edits(rec, 2, 1)
    before = _snapshot(rec)
    stale = _post(world["owner"], rec, tok, lines)
    assert stale.status_code == 409
    _assert_nothing_changed(rec, before)
    fresh = _tokens(world["owner"], rec)
    assert _post(world["owner"], rec, fresh, lines).status_code == 200


# ── existing single-row editing is preserved ─────────────────────────────────────────────────────

def test_single_row_command_still_works_after_a_batch_with_the_returned_token(world):
    rec = _project()
    tok = _tokens(world["owner"], rec)
    lines, _ = _edits(rec, 2, 1)
    res = _post(world["owner"], rec, tok, lines)
    assert res.status_code == 200
    new_hash = re.search(r'id="v2-cost-authority-capex"[^>]*data-content-hash="([0-9a-f]+)"', res.text).group(1)
    row = _rows("capex_sub_lines", rec.project_id)[0]
    single = world["owner"].post("/v2/capex/line/update", data={
        "project": rec.project_code, "sub_line_id": row["sub_line_id"], "label": row["label"], "amount_keur": "42",
        "row_version": row["updated_at"], "workbook_version": tok["version"], "content_hash": new_hash},
        headers={"HX-Request": "true"})
    assert single.status_code == 200 and "data-cost-error" not in single.text
    assert _rows("capex_sub_lines", rec.project_id)[0]["amount_keur"] == 42.0


def test_batch_module_adds_no_financial_authority():
    import ast
    import pathlib
    src = pathlib.Path("app/v2/cost_batch_commands.py").read_text(encoding="utf-8")
    imported = {n.module for n in ast.walk(ast.parse(src)) if isinstance(n, ast.ImportFrom) and n.module}
    assert not any(m.startswith(("financial_engine", "finco_core", "app.workbook.update_service",
                                 "app.workbook.input_set", "app.runtime")) for m in imported), imported
    assert "run_project" not in src and "execute" not in src.lower().replace("executes", "")
