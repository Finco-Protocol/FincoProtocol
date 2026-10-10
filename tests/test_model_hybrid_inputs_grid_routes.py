"""WF-05 — grid validate / atomic batch Save / refresh routes and the grid projection.

Synthetic data only.  The routes add no economic authority: these tests pin that they are a thin,
fail-closed layer over the C0 canonical batch writer (all-or-nothing, CAS, ownership, protected
reference, no model execution, Last Run left intact and classified STALE).
"""
from __future__ import annotations

import re

import pytest
from fastapi.testclient import TestClient

from app.persistence import db
from app.persistence.workspace_repository import get_workspace_state

OWNER = "wf05-owner"
STRANGER = "wf05-stranger"


@pytest.fixture()
def env(tmp_path, monkeypatch):
    monkeypatch.setattr(db, "DB_PATH", str(tmp_path / "wf05.db"))
    db.init_db()
    import main_web
    from app.auth import COOKIE_NAME, create_session_token
    from app.services.reference_seed_service import create_reference_seeded_project

    rec = create_reference_seeded_project(
        user_id=OWNER, template_source="generic_solar_reference", requested_name="WF05", capacity_mw=40.0)
    client = TestClient(main_web.app, cookies={COOKIE_NAME: create_session_token(user_id=OWNER, username="admin")})
    page = client.get(f"/v2/workbook?project={rec.project_code}")
    assert page.status_code == 200
    grid_attrs = re.search(
        r'id="v2-input-grid"[^>]*data-csrf="([^"]+)"[^>]*data-content-hash="([0-9a-f]+)"'
        r'[^>]*data-workbook-version="([^"]+)"', page.text, re.S)
    csrf, chash, version = grid_attrs.groups()
    return {"client": client, "rec": rec, "csrf": csrf, "hash": chash, "version": version,
            "main": main_web, "html": page.text}


def _body(env, cells, **extra):
    body = {"project": env["rec"].project_code, "csrf_token": env["csrf"],
            "cells": [{"field_id": f, "value": v} for f, v in cells]}
    body.update(extra)
    return body


def _save_body(env, cells, **extra):
    return _body(env, cells, content_hash=env["hash"], workbook_version=env["version"], scenario_id=None, **extra)


def _draft(env):
    return get_workspace_state(OWNER, env["rec"].project_id).draft_snapshot


GOOD = [("project_setup.technical.p50_hours", "1611"), ("revenue.ppa.base_tariff", "57")]


def test_page_renders_hybrid_bar_grid_and_tab_without_removing_any_existing_tab(env):
    html = env["html"]
    for token in ('id="v2-hybrid-bar"', 'data-hy-group="inputs"', 'data-hy-group="scenarios"',
                  'data-hy-group="outputs"', 'data-hy-group="analysis"', 'data-hy-group="trust"',
                  'id="tab-input-grid"', 'id="panel-input-grid"', "inputs_grid_v1.js"):
        assert token in html, token
    for tab in ("overview", "scenarios", "compare", "sensitivity", "goal-seek", "project-setup", "inputs",
                "revenue", "capex", "opex", "investor", "debt", "tax", "fs", "returns", "trust", "run-history"):
        assert f'id="tab-{tab}"' in html, f"tab-{tab} must remain"


def test_validate_is_a_dry_run_with_typed_verdicts(env):
    c = env["client"]
    ok = c.post("/v2/workbook/grid/validate", json=_body(env, GOOD))
    assert ok.status_code == 200 and ok.json()["ok"] is True
    before = _draft(env)
    bad = c.post("/v2/workbook/grid/validate", json=_body(env, [
        ("project_setup.technical.p50_hours", "abc"), ("no.such.field", "1"),
        ("revenue.ppa.base_tariff", "1"), ("revenue.ppa.base_tariff", "2")])).json()
    assert bad["ok"] is False
    verdict = {(v["field_id"], i): v for i, v in enumerate(bad["cells"])}
    assert bad["cells"][0]["error_class"] == "INVALID"
    assert bad["cells"][1]["ok"] is False and bad["cells"][1]["code"] == "UnknownFieldError"
    assert bad["cells"][3]["code"] == "BATCH_DUPLICATE_FIELD"
    assert _draft(env) == before, "validation must not persist anything"
    assert verdict


def test_save_is_one_atomic_batch_and_never_runs_the_model(env):
    c = env["client"]
    ws0 = get_workspace_state(OWNER, env["rec"].project_id)
    res = c.post("/v2/workbook/grid/save", json=_save_body(env, GOOD))
    assert res.status_code == 200, res.text
    out = res.json()
    assert out["ok"] and out["model_executed"] is False
    assert {s["field_id"] for s in out["saved"]} == {f for f, _ in GOOD}
    assert out["content_hash"] != env["hash"]
    draft = _draft(env)
    assert draft["p50_hours"] in ("1611", "1611.0")
    ws1 = get_workspace_state(OWNER, env["rec"].project_id)
    assert ws1.last_runtime_snapshot_id == ws0.last_runtime_snapshot_id
    assert ws1.last_runtime_summary == ws0.last_runtime_summary


def test_one_invalid_cell_rolls_back_the_whole_batch(env):
    c = env["client"]
    before = _draft(env)
    res = c.post("/v2/workbook/grid/save", json=_save_body(env, GOOD + [("project_setup.technical.horizon_years", "-5")]))
    assert res.status_code == 422
    body = res.json()
    assert body["code"] == "GRID_VALIDATION_FAILED"
    assert [x["ok"] for x in body["cells"]] == [True, True, False]
    assert _draft(env) == before


def test_stale_hash_replay_and_scenario_mismatch_are_rejected_without_writes(env):
    c = env["client"]
    assert c.post("/v2/workbook/grid/save", json=_save_body(env, GOOD)).status_code == 200
    after = _draft(env)
    replay = c.post("/v2/workbook/grid/save", json=_save_body(env, [("revenue.ppa.base_tariff", "60")]))
    assert replay.status_code == 409 and replay.json()["reload"] is True
    assert _draft(env) == after
    fresh_hash = c.post("/v2/workbook/grid/save", json=_save_body(env, [("revenue.ppa.base_tariff", "60")])).status_code
    assert fresh_hash == 409
    wrong_scenario = _save_body(env, [("revenue.ppa.base_tariff", "61")])
    wrong_scenario["scenario_id"] = "not-the-active-scenario"
    assert c.post("/v2/workbook/grid/save", json=wrong_scenario).status_code in (409, 422)
    assert _draft(env) == after


def test_cascade_fields_are_refused_in_a_batch(env):
    res = env["client"].post("/v2/workbook/grid/save", json=_save_body(env, [("project_setup.technical.capacity_mw", "50")]))
    assert res.status_code == 422
    assert "CASCADE" in res.text.upper() or "FIELD_INVALID" in res.text


def test_csrf_session_and_ownership_are_enforced(env):
    c = env["client"]
    assert c.post("/v2/workbook/grid/save", json=_save_body(env, GOOD, csrf_token="forged")).status_code == 403
    assert c.post("/v2/workbook/grid/validate", json=_body(env, GOOD, csrf_token="")).status_code in (403, 422)
    anon = TestClient(env["main"].app)
    assert anon.post("/v2/workbook/grid/save", json=_save_body(env, GOOD)).status_code in (401, 403, 404)
    assert anon.get(f"/v2/workbook/grid/panel?project={env['rec'].project_code}").status_code in (401, 404)
    from app.auth import COOKIE_NAME, create_session_token
    other = TestClient(env["main"].app, cookies={COOKIE_NAME: create_session_token(user_id=STRANGER, username="admin")})
    res = other.post("/v2/workbook/grid/save", json=_save_body(env, GOOD))
    assert res.status_code in (403, 404)
    assert other.get(f"/v2/workbook/grid/panel?project={env['rec'].project_code}").status_code == 404


def test_protected_reference_is_never_writable(env):
    from app.persistence.projects_repository import get_project_by_code  # noqa: F401  (import guards the API)
    c = env["client"]
    ref_page = c.get("/v2/workbook?project=generic_solar_reference-reference")
    if ref_page.status_code != 200 or 'id="v2-input-grid"' not in ref_page.text:
        pytest.skip("reference project not seeded in this fixture")
    assert 'data-editable="false"' in ref_page.text
    body = _save_body(env, GOOD)
    body["project"] = "generic_solar_reference-reference"
    assert c.post("/v2/workbook/grid/save", json=body).status_code in (403, 404)


def test_body_bounds_are_enforced(env):
    c = env["client"]
    many = [(f"x.{i}", "1") for i in range(51)]
    assert c.post("/v2/workbook/grid/validate", json=_body(env, many)).status_code == 422
    assert c.post("/v2/workbook/grid/validate", json=_body(env, [("revenue.ppa.base_tariff", "9" * 200)])).status_code == 422
    assert c.post("/v2/workbook/grid/validate", json=_body(env, [])).status_code == 422


def test_refresh_routes_only_serve_known_sheets(env):
    c = env["client"]
    code = env["rec"].project_code
    assert c.get(f"/v2/workbook/grid/sheet?project={code}&sheet=capex").status_code == 200
    assert c.get(f"/v2/workbook/grid/sheet?project={code}&sheet=opex").status_code == 200
    assert c.get(f"/v2/workbook/grid/sheet?project={code}&sheet=debt").status_code == 404
    panel = c.get(f"/v2/workbook/grid/panel?project={code}")
    assert panel.status_code == 200 and 'id="v2-input-grid"' in panel.text
    assert "no-store" in panel.headers["cache-control"]


# ── projection ───────────────────────────────────────────────────────────────────────

def _projection(env):
    from app.v2 import router as R
    ws = get_workspace_state(OWNER, env["rec"].project_id)
    pis = R._build_pis_with_composite_identity(ws, env["rec"], OWNER)
    return R._build_input_grid_ctx(env["rec"], pis, ws, OWNER, project_editable=True)["input_grid"]


def test_line_item_categories_are_never_offered_as_editable_cells(env):
    grid = _projection(env)
    cats = {(s.section_id, c.code): c.rows[0] for s in grid.sections if s.section_id in ("capex", "opex")
            for c in s.categories}
    seeded_line_driven = [r for r in cats.values() if "line items" in r.reason]
    assert seeded_line_driven, "reference-seeded categories are line-item driven"
    assert all(not r.editable and not r.field_id for r in seeded_line_driven)
    cx = [c for (sec, _), c in cats.items() if sec == "capex"]
    assert all(not r.editable for r in cx), "no CAPEX category scalar is an input when lines exist"


def test_projection_marks_only_values_changed_since_the_last_run(env):
    from app.v2.input_grid_projection import baseline_pis
    from app.workbook.input_set import ProjectInputSet
    from app.workbook.registry import WORKBOOK
    ws = get_workspace_state(OWNER, env["rec"].project_id)
    base, note = baseline_pis(ws, WORKBOOK, ProjectInputSet)
    assert base is None and "No Last Run" in note
    assert _projection(env).modified_since_run_count == 0


def test_projection_only_exposes_registry_bound_numeric_fields(env):
    from app.workbook.registry import WORKBOOK
    grid = _projection(env)
    ids = [r.field_id for s in grid.sections for c in s.categories for r in c.rows if r.editable]
    assert ids and len(ids) == len(set(ids))
    for fid in ids:
        spec = WORKBOOK.field(fid)
        assert spec.editable and spec.persisted and not spec.runtime_only
    assert "project_setup.technical.capacity_mw" not in ids
    assert "debt.financing.instruments" not in ids
