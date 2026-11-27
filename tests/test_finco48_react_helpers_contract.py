"""Regression witness for canonical React test helper tokens, cookie forwarding, and fail-closed isolation."""
from __future__ import annotations

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from app.auth import COOKIE_NAME, create_session_token
from tests.model_react_test_helpers import (
    react_fields_save_contract,
    react_grid_and_update_tokens,
    react_inputs_save_contract,
    react_run_contract,
    react_workbook_tokens,
)


@pytest.fixture
def helper_env(tmp_path, monkeypatch):
    from app.persistence import db
    from app.services.project_library_service import ensure_reference_models
    from app.services.reference_seed_service import create_reference_seeded_project
    from app.v2.react_workspace_router import router as react_ws_router
    from app.v2.router import router as v2_router

    monkeypatch.setattr(db, "DB_PATH", str(tmp_path / "helpers-contract.db"))
    db.init_db()
    ensure_reference_models()

    app = FastAPI()
    app.include_router(v2_router, prefix="/v2")
    app.include_router(react_ws_router, prefix="/v2")

    rec_a = create_reference_seeded_project(
        user_id="helper-owner-a",
        template_source="generic_solar_reference",
        requested_name="Helper Owner A",
        capacity_mw=20.0,
    )
    rec_b = create_reference_seeded_project(
        user_id="helper-owner-b",
        template_source="generic_wind_reference",
        requested_name="Helper Owner B",
        capacity_mw=30.0,
    )
    cookies_a = {COOKIE_NAME: create_session_token(user_id="helper-owner-a", username="owner_a")}
    cookies_b = {COOKIE_NAME: create_session_token(user_id="helper-owner-b", username="owner_b")}
    with TestClient(app) as client:
        yield client, rec_a, rec_b, cookies_a, cookies_b


def test_default_react_client_gets_real_operation_bound_tokens_and_distinct_identities(helper_env):
    from types import SimpleNamespace
    from app.workbook.mutation_csrf import validate_mutation_token

    client, rec_a, rec_b, cookies_a, cookies_b = helper_env

    toks_a = react_grid_and_update_tokens(client, rec_a.project_code, cookies=cookies_a)
    toks_b = react_grid_and_update_tokens(client, rec_b.project_code, cookies=cookies_b)

    assert toks_a["content_hash"] != toks_b["content_hash"]
    for key in ("content_hash", "workbook_version", "grid_csrf", "grid_hash", "update_csrf", "run_csrf"):
        assert toks_a[key]
        assert toks_b[key]
    assert toks_a["grid_csrf"] != toks_a["update_csrf"] != toks_a["run_csrf"]
    assert toks_a["run_csrf"] != toks_b["run_csrf"]

    req_a = SimpleNamespace(cookies=cookies_a, state=SimpleNamespace())
    req_b = SimpleNamespace(cookies=cookies_b, state=SimpleNamespace())
    assert validate_mutation_token(req_a, rec_a.project_code, toks_a["grid_csrf"], "grid-save")
    assert not validate_mutation_token(req_b, rec_a.project_code, toks_a["grid_csrf"], "grid-save")

    wb_a = react_workbook_tokens(client, rec_a.project_code, cookies=cookies_a)
    assert wb_a == {"content_hash": toks_a["content_hash"], "workbook_version": toks_a["workbook_version"]}
    grid_tok = react_inputs_save_contract(client, rec_a.project_code, cookies=cookies_a)["csrf_token"]
    assert validate_mutation_token(req_a, rec_a.project_code, grid_tok, "grid-save")
    debt_tok = react_fields_save_contract(client, rec_a.project_code, "debt", cookies=cookies_a)["csrf_token"]
    assert validate_mutation_token(req_a, rec_a.project_code, debt_tok, "workbook-update")
    run_tok = react_run_contract(client, rec_a.project_code, cookies=cookies_a)["csrf_token"]
    assert run_tok


def test_unauthenticated_and_foreign_reads_fail_closed_through_helpers(helper_env):
    client, rec_a, rec_b, cookies_a, cookies_b = helper_env

    with pytest.raises(AssertionError, match="HTTP 401"):
        react_workbook_tokens(client, rec_a.project_code)
    with pytest.raises(AssertionError, match="HTTP 404"):
        react_workbook_tokens(client, rec_a.project_code, cookies=cookies_b)
    with pytest.raises(AssertionError, match="HTTP 404"):
        react_grid_and_update_tokens(client, rec_b.project_code, cookies=cookies_a)


def test_react_trust_scopes_integrity_to_active_scenario_and_fails_closed_cross_owner(helper_env):
    from app.persistence.scenarios_repository import list_scenarios
    from tests.model_mutation_csrf import post_valid_mutation

    client, rec_a, rec_b, cookies_a, cookies_b = helper_env

    # 1. NOT_RUN -> no integrity claim; foreign user -> 404 (no cross-owner leakage)
    r0 = client.get("/v2/model-react/trust", params={"project": rec_a.project_code}, cookies=cookies_a)
    assert r0.status_code == 200
    assert r0.json()["run_state"] == "NOT_RUN" and r0.json()["integrity"] is None
    assert client.get("/v2/model-react/trust", params={"project": rec_a.project_code}, cookies=cookies_b).status_code == 404

    # 2. Committed Base Run -> CURRENT + PASS integrity
    wb0 = react_workbook_tokens(client, rec_a.project_code, cookies=cookies_a)
    run_tok = react_run_contract(client, rec_a.project_code, cookies=cookies_a)["csrf_token"]
    ran = client.post(
        "/v2/workbook/run",
        cookies=cookies_a,
        headers={"HX-Request": "true"},
        data={"project": rec_a.project_code, "csrf_token": run_tok, **wb0},
    )
    assert ran.status_code == 200, ran.text[:300]
    r_cur = client.get("/v2/model-react/trust", params={"project": rec_a.project_code}, cookies=cookies_a).json()
    assert r_cur["run_state"] == "CURRENT" and r_cur["integrity"]["overall"] == "PASS"

    # 3. Edit Base -> STALE on the SAME active scenario retains its committed Run integrity
    wb1 = react_workbook_tokens(client, rec_a.project_code, cookies=cookies_a)
    upd = post_valid_mutation(
        client,
        "/v2/workbook/update",
        cookies=cookies_a,
        headers={"HX-Request": "true"},
        data={"project": rec_a.project_code, "field_id": "debt.senior.gearing_pct", "value": "68", **wb1},
    )
    assert upd.status_code == 200, upd.text[:300]
    r_stale = client.get("/v2/model-react/trust", params={"project": rec_a.project_code}, cookies=cookies_a).json()
    assert r_stale["run_state"] == "STALE" and r_stale["integrity"]["overall"] == "PASS"

    # 4. Switch to a brand-new un-run child scenario -> NOT_RUN and integrity withheld (None)
    cr = post_valid_mutation(
        client,
        "/v2/workbook/scenarios/create",
        cookies=cookies_a,
        headers={"HX-Request": "true"},
        data={"project": rec_a.project_code, "scenario_name": "Upside"},
    )
    assert cr.status_code == 200, cr.text[:300]
    child = next(s for s in list_scenarios("helper-owner-a", rec_a.project_id) if not s.is_base_case)
    sel = post_valid_mutation(
        client,
        "/v2/workbook/scenarios/select",
        cookies=cookies_a,
        headers={"HX-Request": "true"},
        data={"project": rec_a.project_code, "scenario_id": child.scenario_id},
    )
    assert sel.status_code == 200, sel.text[:300]
    r_child = client.get("/v2/model-react/trust", params={"project": rec_a.project_code}, cookies=cookies_a).json()
    assert r_child["run_state"] == "NOT_RUN" and r_child["integrity"] is None

    # 5. Restoring Base keeps its committed Run integrity
    base = next(s for s in list_scenarios("helper-owner-a", rec_a.project_id) if s.is_base_case)
    sel_base = post_valid_mutation(
        client,
        "/v2/workbook/scenarios/select",
        cookies=cookies_a,
        headers={"HX-Request": "true"},
        data={"project": rec_a.project_code, "scenario_id": base.scenario_id},
    )
    assert sel_base.status_code == 200
    r_back = client.get("/v2/model-react/trust", params={"project": rec_a.project_code}, cookies=cookies_a).json()
    assert r_back["integrity"]["overall"] == "PASS"


def test_statements_drilldown_registered_detects_mounted_and_absent_routes(monkeypatch):
    from fastapi import APIRouter
    from app.v2 import router as v2_router_mod

    assert v2_router_mod._statements_drilldown_registered() is True

    empty_sub = APIRouter()
    monkeypatch.setattr(v2_router_mod.router, "routes", list(empty_sub.routes))
    assert v2_router_mod._statements_drilldown_registered() is False
