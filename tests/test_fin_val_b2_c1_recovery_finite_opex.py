"""FIN-VAL B2/C1 — Working Copy recovery (SC-3), finite capacity rescale (R-1), placeholder CAPEX
identifiers, and OPEX financial-authority presentation/validation.

Disposable databases and the real canonical routes only.  Legacy stored data is simulated by writing the
snapshot straight into the disposable DB (what a pre-SC-2 Save left behind); no test uses a production
bypass.  Nothing here edits a financial formula, golden value or tolerance.
"""
from __future__ import annotations

import json
import math
import re
import sqlite3
from types import SimpleNamespace

import pytest

from app.workbook.registry import WORKBOOK

USER = "fin-val-b2-user"
TECHS = ("solar", "wind", "data_center", "ev_charging")


# ── fixtures / helpers ──────────────────────────────────────────────────────────────────────────────
@pytest.fixture
def env(tmp_path, monkeypatch):
    from fastapi import FastAPI
    from fastapi.testclient import TestClient
    from app.auth import COOKIE_NAME, create_session_token
    from app.persistence import db
    from app.runtime.model_execution import reset_model_executor_for_tests
    from app.services.reference_seed_service import create_reference_seeded_project
    from app.v2.grid_router import router as grid_router
    from app.v2.react_workspace_router import router as react_router
    from app.v2.router import router

    monkeypatch.setattr(db, "DB_PATH", str(tmp_path / "b2.db"))
    monkeypatch.setenv("FINCO_MODEL_REACT_V1", "1")
    db.init_db()
    app = FastAPI()
    app.include_router(router, prefix="/v2")
    app.include_router(grid_router, prefix="/v2")
    app.include_router(react_router, prefix="/v2")
    with TestClient(app, raise_server_exceptions=False) as client:
        client.cookies.set(COOKIE_NAME, create_session_token(user_id=USER, username="admin"))

        def create(kind="solar", capacity=16, name=None):
            return create_reference_seeded_project(
                user_id=USER, requested_name=name or "B2 " + kind,
                template_source="generic_" + kind + "_reference", capacity_mw=capacity)

        def as_user(user_id):
            other = TestClient(app, raise_server_exceptions=False)
            other.cookies.set(COOKIE_NAME, create_session_token(user_id=user_id, username="x"))
            return other

        yield SimpleNamespace(client=client, create=create, as_user=as_user, db_path=str(tmp_path / "b2.db"), app=app)
    reset_model_executor_for_tests()


def _ws(record):
    from app.persistence.workspace_repository import get_workspace_state
    return get_workspace_state(USER, record.project_id)


def _snapshot(record):
    return dict(_ws(record).draft_snapshot)


def _poison(env, record, key, value):
    """Store a value the SC-2 bound would now refuse - i.e. data an older Save left behind."""
    with sqlite3.connect(env.db_path) as conn:
        raw = conn.execute("SELECT draft_snapshot_json FROM workspace_states WHERE project_id=?", (record.project_id,)).fetchone()[0]
        snap = json.loads(raw)
        snap[key] = value
        conn.execute("UPDATE workspace_states SET draft_snapshot_json=? WHERE project_id=?", (json.dumps(snap), record.project_id))


def _prime(env, record, client=None):
    """First render of a new Working Copy persists a revenue backfill (changes the CAS hash): render once."""
    (client or env.client).get("/v2/workbook", params={"project": record.project_code})


def _page_tokens(env, record, client=None):
    c = client or env.client
    _prime(env, record, c)
    page = c.get("/v2/workbook", params={"project": record.project_code})
    assert page.status_code == 200 and 'id="v2-input-grid"' in page.text
    out = {k: re.search(f'name="{k}" value="([^"]*)"', page.text).group(1) for k in ("content_hash", "workbook_version")}
    grid = re.search(r'id="v2-input-grid"[^>]*', page.text).group(0)
    out["grid_csrf"] = re.search(r'data-csrf="([^"]*)"', grid).group(1)
    out["grid_hash"] = re.search(r'data-content-hash="([^"]*)"', grid).group(1)
    m = re.search(r'hx-post="/v2/workbook/update"[^>]*>\s*<input type="hidden" name="csrf_token" value="([^"]*)"', page.text)
    out["update_csrf"] = m.group(1) if m else ""
    m = re.search(r'name="run_csrf_token" value="([^"]*)"', page.text)
    out["run_csrf"] = m.group(1) if m else ""
    out["html"] = page.text
    return out


def _single_save(env, record, field_id, value, tokens):
    data = {"project": record.project_code, "field_id": field_id, "value": value,
            "content_hash": tokens["content_hash"], "workbook_version": tokens["workbook_version"]}
    if tokens.get("update_csrf"):
        data["csrf_token"] = tokens["update_csrf"]
    return env.client.post("/v2/workbook/update", headers={"HX-Request": "true"}, data=data)


def _grid_save(env, record, cells, tokens, **over):
    body = {"project": record.project_code, "csrf_token": tokens["grid_csrf"], "content_hash": tokens["grid_hash"],
            "workbook_version": tokens["workbook_version"], "scenario_id": None, "cells": cells}
    body.update(over)
    return env.client.post("/v2/workbook/grid/save", json=body)


def _recovery_form(html):
    """Hidden inputs of the first recovery form, exactly as the server rendered them."""
    form = re.search(r'<form method="post" action="/v2/workbook/update".*?</form>', html, re.S)
    assert form is not None, "recovery form not rendered"
    fields = dict(re.findall(r'<input type="hidden" name="([a-z_]+)" value="([^"]*)"', form.group(0)))
    return fields


def _history_count(env, record):
    with sqlite3.connect(env.db_path) as conn:
        return conn.execute("SELECT COUNT(*) FROM model_run_history WHERE project_id=?", (record.project_id,)).fetchone()[0]


def _semantic(snapshot, ignore=()):
    out = {}
    for key, value in snapshot.items():
        if key in ignore:
            continue
        if isinstance(value, str) and value[:1] in "{[":
            try:
                value = json.loads(value)
            except ValueError:
                pass
        if isinstance(value, (int, float)) and not isinstance(value, bool):
            value = float(value)
        elif isinstance(value, str):
            try:
                value = float(value)
            except ValueError:
                pass
        if value == "":
            value = None  # the first Save normalises an unset value to ""; same meaning
        out[key] = value
    return out


def _db_fingerprint(env, record):
    with sqlite3.connect(env.db_path) as conn:
        conn.row_factory = sqlite3.Row
        tables = {}
        for table in ("capex_sub_lines", "opex_sub_lines"):
            tables[table] = [tuple(r) for r in conn.execute(f"SELECT * FROM {table} WHERE project_id=? ORDER BY sub_line_id", (record.project_id,))]
        tables["workspace_states"] = tuple(conn.execute("SELECT * FROM workspace_states WHERE project_id=?", (record.project_id,)).fetchone())
        tables["projects"] = tuple(conn.execute("SELECT * FROM projects WHERE project_id=?", (record.project_id,)).fetchone())
        tables["history"] = conn.execute("SELECT COUNT(*) FROM model_run_history").fetchone()[0]
        return tables


# ═══ SC-3: Working Copy recovery ═══════════════════════════════════════════════════════════════════
class TestLegacyRecovery:
    def test_unreadable_working_copy_returns_controlled_recovery_page_without_mutation(self, env):
        record = env.create()
        _prime(env, record)
        _poison(env, record, "capex_epc_contract_keur", "-20000.0")
        before = _db_fingerprint(env, record)
        page = env.client.get("/v2/workbook", params={"project": record.project_code})
        assert page.status_code == 200
        assert 'data-testid="workbook-recovery-page"' in page.text
        assert "capex.C.epc_contract" in page.text and "-20000.0" in page.text
        assert "must be zero or greater" in page.text
        assert _db_fingerprint(env, record) == before              # read-only: stored value, history, metadata untouched
        assert _snapshot(record)["capex_epc_contract_keur"] == "-20000.0"

    def test_authorized_owner_repairs_through_the_existing_save_and_the_copy_becomes_readable(self, env):
        record = env.create()
        _prime(env, record)
        _poison(env, record, "capex_epc_contract_keur", "-20000.0")
        before = _snapshot(record)
        page = env.client.get("/v2/workbook", params={"project": record.project_code})
        form = _recovery_form(page.text)
        assert form["field_id"] == "capex.C.epc_contract" and form["csrf_token"]
        resp = env.client.post("/v2/workbook/update", data={**form, "value": "20000"}, follow_redirects=False)
        assert resp.status_code == 303 and "v2_err" not in resp.headers["location"]
        after = _snapshot(record)
        assert float(after["capex_epc_contract_keur"]) == 20000.0
        # no unrelated draft field was modified (semantic comparison: the first write normalises types only)
        assert _semantic(after, ignore=("capex_epc_contract_keur",)) == _semantic(before, ignore=("capex_epc_contract_keur",))
        healthy = env.client.get("/v2/workbook", params={"project": record.project_code})
        assert healthy.status_code == 200 and 'id="v2-input-grid"' in healthy.text
        assert _history_count(env, record) == 0                    # recovery never runs the model

    def test_two_invalid_values_are_listed_and_repaired_one_at_a_time(self, env):
        record = env.create()
        _prime(env, record)
        _poison(env, record, "capex_epc_contract_keur", "-1")
        _poison(env, record, "capex_insurances_keur", "-2")
        page = env.client.get("/v2/workbook", params={"project": record.project_code})
        assert page.text.count('data-testid="workbook-recovery-issue"') == 2
        form = _recovery_form(page.text)
        env.client.post("/v2/workbook/update", data={**form, "value": "10"}, follow_redirects=False)
        again = env.client.get("/v2/workbook", params={"project": record.project_code})
        assert again.status_code == 200 and again.text.count('data-testid="workbook-recovery-issue"') == 1
        assert _history_count(env, record) == 0

    def test_invalid_replacement_is_refused_and_nothing_is_rewritten(self, env):
        record = env.create()
        _prime(env, record)
        _poison(env, record, "capex_epc_contract_keur", "-20000.0")
        form = _recovery_form(env.client.get("/v2/workbook", params={"project": record.project_code}).text)
        before = _snapshot(record)
        for bad in ("-5", "abc", "nan", "inf"):
            resp = env.client.post("/v2/workbook/update", data={**form, "value": bad}, follow_redirects=False)
            assert resp.status_code in (303, 422)
            assert _semantic(_snapshot(record)) == _semantic(before)
        shown = env.client.get("/v2/workbook", params={"project": record.project_code})
        assert 'data-testid="workbook-recovery-page"' in shown.text

    def test_stale_cas_forged_missing_and_cross_session_tokens_are_refused(self, env):
        record = env.create()
        _prime(env, record)
        _poison(env, record, "capex_epc_contract_keur", "-20000.0")
        form = _recovery_form(env.client.get("/v2/workbook", params={"project": record.project_code}).text)
        before = _snapshot(record)
        stale = env.client.post("/v2/workbook/update", data={**form, "content_hash": "0" * 64, "value": "20000"}, follow_redirects=False)
        assert stale.status_code == 303 and "v2_err" in stale.headers["location"]
        forged = env.client.post("/v2/workbook/update", data={**form, "csrf_token": "bad", "value": "20000"})
        missing = env.client.post("/v2/workbook/update", data={k: v for k, v in form.items() if k != "csrf_token"} | {"value": "20000"})
        assert forged.status_code == 403 and missing.status_code == 403
        other = env.as_user("someone-else")
        cross = other.post("/v2/workbook/update", data={**form, "value": "20000"})
        assert cross.status_code in (403, 404)
        assert _snapshot(record) == before

    def test_other_users_and_anonymous_get_no_recovery_detail(self, env):
        from fastapi.testclient import TestClient
        record = env.create()
        _prime(env, record)
        _poison(env, record, "capex_epc_contract_keur", "-20000.0")
        other = env.as_user("someone-else").get("/v2/workbook", params={"project": record.project_code}, follow_redirects=False)
        assert other.status_code == 302 and "recovery" not in other.text.lower() and "-20000" not in other.text
        anon = TestClient(env.app, raise_server_exceptions=False).get("/v2/workbook", params={"project": record.project_code}, follow_redirects=False)
        assert anon.status_code in (302, 401, 403) and "-20000" not in anon.text

    def test_protected_reference_is_never_repairable(self, env):
        from app.persistence.projects_repository import get_reference_by_template_source
        from app.services.project_library_service import ensure_reference_models
        ensure_reference_models()
        ref = get_reference_by_template_source("generic_solar_reference")
        assert ref is not None
        # poison the shared reference draft directly (disposable DB), as legacy data would
        with sqlite3.connect(env.db_path) as conn:
            rows = conn.execute("SELECT user_id, project_id, draft_snapshot_json FROM workspace_states WHERE project_id=?", (ref.project_id,)).fetchall()
            assert rows
            owner_id, _pid, raw = rows[0]
            snap = json.loads(raw)
            snap["capex_epc_contract_keur"] = "-5"
            conn.execute("UPDATE workspace_states SET draft_snapshot_json=? WHERE project_id=?", (json.dumps(snap), ref.project_id))
        client = env.client
        page = client.get("/v2/workbook", params={"project": ref.project_code})
        if 'data-testid="workbook-recovery-page"' in page.text:
            assert 'data-testid="workbook-recovery-form"' not in page.text      # no editor for a protected reference
            assert "protected reference" in page.text
        resp = client.post("/v2/workbook/update", data={
            "project": ref.project_code, "field_id": "capex.C.epc_contract", "value": "1",
            "content_hash": "0" * 64, "workbook_version": WORKBOOK.version, "csrf_token": "x"})
        assert resp.status_code in (403, 404)

    def test_unreadable_non_registry_value_is_reported_but_not_offered_for_repair(self, env):
        record = env.create()
        _prime(env, record)
        _poison(env, record, "project_type", "Not A Technology")
        page = env.client.get("/v2/workbook", params={"project": record.project_code})
        assert page.status_code == 200 and 'data-testid="workbook-recovery-page"' in page.text
        assert 'data-testid="workbook-recovery-form"' not in page.text
        assert "cannot be repaired from this view" in page.text


class TestReactRecovery:
    def test_inputs_returns_typed_recovery_state_with_the_operation_bound_save_contract(self, env):
        record = env.create()
        _prime(env, record)
        _poison(env, record, "capex_epc_contract_keur", "-20000.0")
        before = _db_fingerprint(env, record)
        resp = env.client.get("/v2/model-react/inputs", params={"project": record.project_code})
        assert resp.status_code == 409
        body = resp.json()
        assert body["ok"] is False and body["code"] == "WORKING_COPY_RECOVERY_REQUIRED"
        issue = body["recovery"]["issues"][0]
        assert issue["field_id"] == "capex.C.epc_contract" and issue["stored_value"] == "-20000.0" and issue["repairable"] is True
        assert body["save"]["url"] == "/v2/workbook/grid/save" and body["save"]["csrf_token"] and len(body["save"]["content_hash"]) == 64
        assert _db_fingerprint(env, record) == before

    def test_react_owner_repairs_with_the_returned_token_and_cas_then_inputs_are_healthy(self, env):
        record = env.create()
        _prime(env, record)
        _poison(env, record, "capex_epc_contract_keur", "-20000.0")
        save = env.client.get("/v2/model-react/inputs", params={"project": record.project_code}).json()["save"]
        body = {"project": record.project_code, "csrf_token": save["csrf_token"], "content_hash": save["content_hash"],
                "workbook_version": save["workbook_version"], "scenario_id": save["scenario_id"],
                "cells": [{"field_id": "capex.C.epc_contract", "value": "20000"}]}
        resp = env.client.post(save["url"], json=body)
        assert resp.status_code == 200 and resp.json()["ok"] is True and resp.json()["model_executed"] is False
        healthy = env.client.get("/v2/model-react/inputs", params={"project": record.project_code})
        assert healthy.status_code == 200 and healthy.json()["ok"] is True
        assert _history_count(env, record) == 0

    def test_react_repair_refuses_invalid_stale_forged_and_cross_session_requests(self, env):
        record = env.create()
        _prime(env, record)
        _poison(env, record, "capex_epc_contract_keur", "-20000.0")
        save = env.client.get("/v2/model-react/inputs", params={"project": record.project_code}).json()["save"]
        base = {"project": record.project_code, "csrf_token": save["csrf_token"], "content_hash": save["content_hash"],
                "workbook_version": save["workbook_version"], "scenario_id": save["scenario_id"],
                "cells": [{"field_id": "capex.C.epc_contract", "value": "20000"}]}
        before = _snapshot(record)
        assert env.client.post(save["url"], json={**base, "cells": [{"field_id": "capex.C.epc_contract", "value": "-1"}]}).status_code == 422
        assert env.client.post(save["url"], json={**base, "content_hash": "0" * 64}).status_code == 409
        assert env.client.post(save["url"], json={**base, "csrf_token": "bad"}).status_code == 403
        other = env.as_user("someone-else")
        assert other.post(save["url"], json=base).status_code in (403, 404)
        assert _snapshot(record) == before

    def test_other_user_gets_non_disclosing_not_found(self, env):
        record = env.create()
        _prime(env, record)
        _poison(env, record, "capex_epc_contract_keur", "-20000.0")
        resp = env.as_user("someone-else").get("/v2/model-react/inputs", params={"project": record.project_code})
        assert resp.status_code == 404 and "-20000" not in resp.text and "recovery" not in resp.text.lower()

    def test_healthy_inputs_contract_is_unchanged(self, env):
        record = env.create()
        _prime(env, record)
        body = env.client.get("/v2/model-react/inputs", params={"project": record.project_code}).json()
        assert body["ok"] is True and set(("grid", "save", "project", "cost_line_boundary")) <= set(body)
        assert "recovery" not in body


# ═══ R-1: finite derived amounts, atomic capacity rescale ═══════════════════════════════════════════
class TestCapacityRescaleFiniteness:
    @pytest.mark.parametrize("kind", TECHS)
    @pytest.mark.parametrize("capacity", ["1e306", "5e307", "1e308"])
    def test_non_finite_derived_amounts_are_refused_before_anything_is_written(self, env, kind, capacity):
        record = env.create(kind)
        tokens = _page_tokens(env, record)
        before = _db_fingerprint(env, record)
        resp = _single_save(env, record, "project_setup.technical.capacity_mw", capacity, tokens)
        assert resp.status_code == 200 and "representable numeric range" in resp.text and "Nothing was changed" in resp.text
        assert _db_fingerprint(env, record) == before              # sub-lines, draft, metadata, history: byte-identical
        snap = _snapshot(record)
        assert snap["capacity_mw"] == "16"
        assert all(str(v).lower() not in ("inf", "-inf", "nan", "infinity") for v in snap.values() if isinstance(v, (str, float)))
        assert env.client.get("/v2/workbook", params={"project": record.project_code}).status_code == 200

    @pytest.mark.parametrize("kind", ("solar", "wind"))
    def test_large_finite_capacity_is_applied_with_all_derived_amounts_finite(self, env, kind):
        record = env.create(kind)
        tokens = _page_tokens(env, record)
        resp = _single_save(env, record, "project_setup.technical.capacity_mw", "1e305", tokens)
        assert "representable" not in resp.text
        snap = _snapshot(record)
        assert float(snap["capacity_mw"]) == 1e305 and math.isfinite(float(snap["total_capex_keur"])) and math.isfinite(float(snap["opex_y1_keur"]))
        with sqlite3.connect(env.db_path) as conn:
            amounts = [r[0] for t in ("capex_sub_lines", "opex_sub_lines") for r in conn.execute(f"SELECT amount_keur FROM {t} WHERE project_id=?", (record.project_id,))]
        assert amounts and all(math.isfinite(a) for a in amounts)
        assert env.client.get("/v2/workbook", params={"project": record.project_code}).status_code == 200

    @pytest.mark.parametrize("kind", TECHS)
    @pytest.mark.parametrize("capacity", ["8", "24.5", "100", "1234.5"])
    def test_normal_capacity_rescale_is_bit_identical_to_the_previous_algorithm(self, env, kind, capacity):
        from app.services.reference_seed_service import rescale_reference_seeded_project
        new_rec = env.create(kind, name="new " + kind)
        old_rec = env.create(kind, name="old " + kind)
        assert float(capacity) != 16
        rescale_reference_seeded_project(user_id=USER, project_code=new_rec.project_code, capacity_mw=float(capacity))
        _legacy_rescale(USER, old_rec.project_code, float(capacity))

        def view(rec):
            with sqlite3.connect(env.db_path) as conn:
                lines = {t: sorted((r[0], r[1]) for r in conn.execute(
                    f"SELECT {'business_code' if t == 'opex_sub_lines' else 'parent_category_code'}, amount_keur FROM {t} WHERE project_id=? AND is_active=1", (rec.project_id,)))
                    for t in ("capex_sub_lines", "opex_sub_lines")}
            snap = _snapshot(rec)
            keys = ("capacity_mw", "total_capex_keur", "opex_y1_keur", "opex_power_expenses_y1_keur")
            return lines, {k: snap.get(k) for k in keys}, _semantic(json.loads(json.dumps(snap.get("_reference_seed_profile") or {}, default=str)) if not isinstance(snap.get("_reference_seed_profile"), str) else json.loads(snap["_reference_seed_profile"]))

        assert view(new_rec) == view(old_rec)

    def test_preflight_never_writes_even_when_it_succeeds(self, env):
        from app.services.reference_seed_service import preflight_capacity_rescale
        record = env.create()
        before = _db_fingerprint(env, record)
        preflight_capacity_rescale(user_id=USER, project_code=record.project_code, capacity_mw=48.0)
        assert _db_fingerprint(env, record) == before

    def test_capacity_edit_with_stale_cas_still_changes_nothing(self, env):
        record = env.create()
        tokens = _page_tokens(env, record)
        before = _db_fingerprint(env, record)
        resp = _single_save(env, record, "project_setup.technical.capacity_mw", "48", {**tokens, "content_hash": "0" * 64})
        assert "Draft changed" in resp.text or "changed since" in resp.text.lower()
        assert _db_fingerprint(env, record) == before


def _legacy_rescale(user_id, project_code, capacity_mw):
    """Verbatim pre-change algorithm (autocommit statements, sums after the updates) used as the bit-identity oracle."""
    from app.persistence.db import get_cursor
    from app.persistence.projects_repository import get_project_by_code
    from app.persistence.workspace_repository import get_workspace_state, save_workspace_state
    from app.services import reference_seed_service as svc

    record = get_project_by_code(user_id, project_code)
    ws = get_workspace_state(user_id, record.project_id)
    profile = svc._resolve_seed_profile(ws.draft_snapshot)
    opex_items = profile.get("opex_items", {})
    with get_cursor() as cur:
        cur.execute("SELECT sub_line_id, replay_metadata_json FROM capex_sub_lines WHERE project_id=? AND is_active=1 AND source='reference_seed'", (record.project_id,))
        for row in cur.fetchall():
            metadata = json.loads(row["replay_metadata_json"] or "{}")
            rate = metadata.get("unit_rate_keur_per_mw")
            if rate is not None and metadata.get("scaling_mode") == svc.ScalingMode.PER_MW.value:
                cur.execute("UPDATE capex_sub_lines SET amount_keur=?, updated_at=datetime('now') WHERE project_id=? AND sub_line_id=?",
                            (float(rate) * capacity_mw, record.project_id, row["sub_line_id"]))
        cur.execute("SELECT sub_line_id, replay_metadata_json FROM opex_sub_lines WHERE project_id=? AND is_active=1 AND source='reference_seed'", (record.project_id,))
        for row in cur.fetchall():
            metadata = json.loads(row["replay_metadata_json"] or "{}")
            seed = opex_items.get(metadata.get("canonical_key"), {})
            rate = metadata.get("unit_rate_keur_per_mw", seed.get("unit_rate_keur_per_mw"))
            if rate is not None and metadata.get("scaling_mode") == svc.ScalingMode.PER_MW.value:
                cur.execute("UPDATE opex_sub_lines SET amount_keur=?, updated_at=datetime('now') WHERE project_id=? AND sub_line_id=?",
                            (float(rate) * capacity_mw, record.project_id, row["sub_line_id"]))
        cur.execute("SELECT COALESCE(SUM(amount_keur), 0) AS total FROM capex_sub_lines WHERE project_id=? AND is_active=1", (record.project_id,))
        capex_total = float(cur.fetchone()["total"])
        cur.execute("SELECT COALESCE(SUM(amount_keur), 0) AS total FROM opex_sub_lines WHERE project_id=? AND is_active=1", (record.project_id,))
        opex_total = float(cur.fetchone()["total"])
        if record.template_source == "generic_ev_charging_reference":
            opex_total += svc._ev_b08_from_snapshot(dict(ws.draft_snapshot), float(capacity_mw))
    snapshot = dict(ws.draft_snapshot)
    snapshot["capacity_mw"] = f"{capacity_mw:.12g}"
    snapshot["total_capex_keur"] = f"{capex_total:.12g}"
    if record.template_source == "generic_data_center_reference":
        from app.data_center_authority import drivers_from_snapshot
        drivers = drivers_from_snapshot(dict(ws.draft_snapshot))
        power_y1 = svc.annual_power_cost_keur(capacity_mw=capacity_mw, occupancy=drivers.occupancy_y1, pue=drivers.pue,
                                              electricity_price_eur_mwh=drivers.electricity_price_eur_mwh)
        snapshot["opex_power_expenses_y1_keur"] = f"{power_y1:.12g}"
        snapshot["opex_y1_keur"] = f"{opex_total + power_y1:.12g}"
    else:
        snapshot["opex_y1_keur"] = f"{opex_total:.12g}"
    profile = dict(profile)
    profile["seed_capacity_mw"] = capacity_mw
    if profile.get("data_center") is not None:
        profile["data_center"] = dict(profile["data_center"])
        profile["data_center"]["seed_capacity_mw"] = capacity_mw
    snapshot["_reference_seed_profile"] = profile
    save_workspace_state(user_id=user_id, project_id=record.project_id, project_code=record.project_code, draft_snapshot=snapshot,
                         saved_snapshot=ws.saved_snapshot, dirty=True, governance_state=ws.governance_state, replay_metadata=ws.replay_metadata)


# ═══ Placeholder CAPEX identifiers (BookDepreciableAssetBasis duplicate 'Unused') ══════════════════
CAPEX_FIELDS = sorted(f.field_id for f in WORKBOOK.all_fields()
                      if f.field_id.startswith("capex.") and f.editable and f.binding_status.name == "BOUND")


class TestPlaceholderCapexIdentifiers:
    @pytest.mark.parametrize("kind", TECHS)
    def test_fourteen_sequential_positive_scalar_edits_keep_the_workbook_page_readable(self, env, kind):
        record = env.create(kind)
        for index, field_id in enumerate(CAPEX_FIELDS):
            tokens = _page_tokens(env, record)
            assert _single_save(env, record, field_id, str(1000 + 10 * index), tokens).status_code == 200
            assert env.client.get("/v2/workbook", params={"project": record.project_code}).status_code == 200, field_id

    @pytest.mark.parametrize("kind", ("solar", "wind"))
    def test_run_after_two_placeholder_edits_commits_and_equals_the_single_edit_result(self, env, kind):
        def run(fields):
            record = env.create(kind, name=f"{kind} {len(fields)}")
            for field_id, value in fields:
                assert _single_save(env, record, field_id, value, _page_tokens(env, record)).status_code == 200
            tokens = _page_tokens(env, record)
            resp = env.client.post("/v2/workbook/run", headers={"HX-Request": "true"}, data={
                "project": record.project_code, "csrf_token": tokens["run_csrf"],
                "content_hash": tokens["content_hash"], "workbook_version": tokens["workbook_version"]})
            assert resp.status_code == 200
            with sqlite3.connect(env.db_path) as conn:
                rows = conn.execute("SELECT runtime_summary_json FROM model_run_history WHERE project_id=?", (record.project_id,)).fetchall()
            assert len(rows) == 1                                  # committed, and the response page rendered (no 500)
            summary = json.loads(rows[0][0])
            return {k: summary[k] for k in ("total_capex_keur", "project_irr", "equity_irr", "min_dscr", "total_opex_keur", "senior_debt_keur")}

        one = run([("capex.C.ops_preparation", "800")])
        two = run([("capex.C.ops_preparation", "500"), ("capex.C.insurances", "300")])
        assert one == two

    def test_placeholder_gets_a_unique_deterministic_identifier_and_nothing_else_changes(self, env):
        from app.input_adapter import build_projectinputs_from_snapshot
        record = env.create()
        base = build_projectinputs_from_snapshot(_snapshot(record)).capex
        _prime(env, record)
        snap = _snapshot(record)
        snap.update({"capex_ops_prep_keur": "500", "capex_insurances_keur": "300", "capex_lease_tax_keur": "7"})
        capex = build_projectinputs_from_snapshot(snap).capex
        names = [getattr(capex, f).name for f in ("ops_prep", "insurances", "lease_tax")]
        assert names == ["Operations Preparation", "Insurances", "Lease & Tax"] and len(set(names)) == 3
        for field in ("ops_prep", "insurances", "lease_tax"):
            item, original = getattr(capex, field), getattr(base, field)
            assert item.asset_class == original.asset_class and item.spending_profile == original.spending_profile
            assert item.y0_share == original.y0_share and item.useful_life_override == original.useful_life_override
        # non-placeholder items keep their factory names
        assert capex.epc_contract.name == base.epc_contract.name and capex.audit_legal.name == base.audit_legal.name

    def test_scalar_edit_of_a_named_item_keeps_its_name(self, env):
        from app.input_adapter import build_projectinputs_from_snapshot
        record = env.create()
        _prime(env, record)
        snap = _snapshot(record)
        base_name = build_projectinputs_from_snapshot(snap).capex.epc_contract.name
        snap["capex_epc_contract_keur"] = "123"
        assert build_projectinputs_from_snapshot(snap).capex.epc_contract.name == base_name


# ═══ OPEX financial authority ═══════════════════════════════════════════════════════════════════════
OPEX_FIELDS = sorted(f.field_id for f in WORKBOOK.all_fields()
                     if f.field_id.startswith("opex.lines.") and f.editable and f.binding_status.name == "BOUND")


class TestOpexAuthority:
    def test_eleven_opex_line_fields_carry_the_engine_non_negative_floor_and_nothing_else_changed(self):
        assert len(OPEX_FIELDS) == 11
        specs = [WORKBOOK.field(f) for f in OPEX_FIELDS]
        assert all(s.min_value == 0 and s.max_value is None for s in specs)
        for field_id in ("opex.lines.contingencies", "opex.summary.total_y1"):
            assert WORKBOOK.field(field_id).min_value is None

    @pytest.mark.parametrize("field_id", OPEX_FIELDS)
    def test_negative_opex_is_refused_zero_and_positive_are_accepted(self, env, field_id):
        record = env.create()
        tokens = _page_tokens(env, record)
        before = _snapshot(record)
        assert "must be" in _single_save(env, record, field_id, "-100", tokens).text
        assert _snapshot(record) == before
        grid = _grid_save(env, record, [{"field_id": field_id, "value": "-1"}], tokens)
        assert grid.status_code == 422 and grid.json()["cells"][0]["error_class"] == "OUT_OF_BOUNDS"
        assert _snapshot(record) == before
        tokens = _page_tokens(env, record)
        assert _single_save(env, record, field_id, "0", tokens).status_code == 200
        assert float(_snapshot(record)[WORKBOOK.field(field_id).snapshot_key]) == 0.0

    def test_grid_and_legacy_sheet_stop_offering_editors_that_cannot_change_the_run(self, env):
        expectations = {
            "solar": ("Maintenance", "opex.lines.site_maintenance"),
            "wind": ("Maintenance", "opex.lines.site_maintenance"),
            "ev_charging": (None, "opex.lines.power_expenses"),
        }
        for kind, (_name, shadowed) in expectations.items():
            record = env.create(kind, name="auth " + kind)
            tokens = _page_tokens(env, record)
            assert f'data-field-id="{shadowed}"' not in tokens["html"]            # legacy OPEX sheet: no editor
            grid = env.client.get("/v2/model-react/inputs", params={"project": record.project_code}).json()["grid"]
            editable_ids = {row["field_id"] for s in grid["sections"] for c in s["categories"] for row in c["rows"] if row["editable"]}
            assert shadowed not in editable_ids
        # editors whose edit DOES reach the Run remain
        record = env.create("solar", name="auth solar keep")
        tokens = _page_tokens(env, record)
        for kept in ("opex.lines.security", "opex.lines.cleaning_materials", "opex.lines.audit_accounting_legal"):
            assert f'data-field-id="{kept}"' in tokens["html"]

    def test_authority_notes_follow_the_proven_precedence(self, env):
        from app.v2.opex_authority import DERIVED_FROM_DRIVERS, REPLACED_BY_LINES, opex_group_authority_notes
        solar = env.create("solar", name="notes solar")
        notes = opex_group_authority_notes(solar.project_id, "generic_solar_reference")
        assert {"B.01", "B.03", "B.06", "B.07"} <= set(notes) and set(notes.values()) == {REPLACED_BY_LINES}
        assert "B.08" not in notes and "B.02" not in notes
        ev = env.create("ev_charging", name="notes ev")
        assert opex_group_authority_notes(ev.project_id, "generic_ev_charging_reference")["B.08"] == DERIVED_FROM_DRIVERS
        assert opex_group_authority_notes("no-such-project", "generic_solar_reference") == {}

    def test_run_precedence_replaced_group_is_ignored_and_active_group_reaches_the_run(self, env):
        """Evidence for the matrix: same Working Copy, same value; only the active group changes total OPEX."""
        def total_opex(field_id):
            record = env.create("solar", name="run " + str(field_id))
            if field_id:
                assert _single_save(env, record, field_id, "60", _page_tokens(env, record)).status_code == 200
            tokens = _page_tokens(env, record)
            env.client.post("/v2/workbook/run", headers={"HX-Request": "true"}, data={
                "project": record.project_code, "csrf_token": tokens["run_csrf"],
                "content_hash": tokens["content_hash"], "workbook_version": tokens["workbook_version"]})
            with sqlite3.connect(env.db_path) as conn:
                row = conn.execute("SELECT runtime_summary_json FROM model_run_history WHERE project_id=?", (record.project_id,)).fetchone()
            return json.loads(row[0])["total_opex_keur"]

        base = total_opex(None)
        assert total_opex("opex.lines.site_maintenance") == base          # replaced by the seeded line items
        assert total_opex("opex.lines.security") > base                   # appended item reaches the Run


class TestRecoveryGateDoesNotPreemptTypedScopeRefusals:
    """The recovery gate must not take over conditions the pages already handle in place (RC-7B 3/3 selection)."""

    def test_typed_quarterly_refusal_is_not_an_unreadable_draft(self, monkeypatch):
        from app import input_adapter
        from app.workbook.draft_recovery import diagnose_draft

        def refuse(snapshot):
            raise input_adapter.SnapshotInputError("QUARTERLY_FINANCING_STRUCTURE_MISMATCH: recorded structure not carried")
        monkeypatch.setattr(input_adapter, "build_projectinputs_from_snapshot", refuse)
        assert diagnose_draft({"capex_epc_contract_keur": "1"}) is None

    def test_an_unknown_non_quarterly_error_is_still_reported_and_not_repairable(self, monkeypatch):
        from app import input_adapter
        from app.workbook.draft_recovery import diagnose_draft

        def refuse(snapshot):
            raise input_adapter.SnapshotInputError("SOMETHING_ELSE: unreadable")
        monkeypatch.setattr(input_adapter, "build_projectinputs_from_snapshot", refuse)
        recovery = diagnose_draft({})
        assert recovery is not None and recovery.issues and not recovery.issues[0].repairable
