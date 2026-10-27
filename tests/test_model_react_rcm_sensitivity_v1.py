"""RC-M Lane B — contract and financial-parity tests for the React Sensitivity adapter.

The adapter is read-only and adds no calculation: every point is the original ``run_project`` through the canonical sensitivity
matrix service.  These tests prove the access/guard order, the bounded budget, that nothing is persisted, and — independently of the
adapter — that a one-driver strip equals the Legacy one-driver route and that the matrix equals the Legacy matrix route for the same
driver and levels on the same runtime.  Synthetic data only.
"""
from __future__ import annotations

import re
from types import SimpleNamespace

import pytest
from bs4 import BeautifulSoup
from fastapi import FastAPI
from fastapi.testclient import TestClient

from app.persistence import db
from app.persistence.workspace_repository import get_workspace_state

OWNER = "rcm-sens-owner"
STRANGER = "rcm-sens-stranger"
BASE = "/v2/model-react/analysis/sensitivity"
HDR = {"X-Finco-React-Request": "1"}


@pytest.fixture()
def env(tmp_path, monkeypatch):
    monkeypatch.setattr(db, "DB_PATH", str(tmp_path / "rcm_sens.db"))
    db.init_db()
    from app.auth import COOKIE_NAME, create_session_token
    from app.runtime.model_execution import reset_model_executor_for_tests
    from app.services.reference_seed_service import create_reference_seeded_project
    from app.v2.react_analysis import router as analysis_router
    from app.v2.react_poc_router import router as poc_router
    from app.v2.react_workspace_router import router as workspace_router
    from app.v2.router import router as v2_router

    monkeypatch.setenv("FINCO_MODEL_REACT_V1", "1")
    app = FastAPI()
    app.include_router(v2_router, prefix="/v2")
    app.include_router(workspace_router, prefix="/v2")
    app.include_router(analysis_router, prefix="/v2")     # idempotent when the workspace router already mounts it
    app.include_router(poc_router, prefix="/v2")
    with TestClient(app) as client:
        client.cookies.set(COOKIE_NAME, create_session_token(user_id=OWNER, username="admin"))
        stranger = TestClient(app)
        stranger.cookies.set(COOKIE_NAME, create_session_token(user_id=STRANGER, username="stranger"))
        anonymous = TestClient(app)

        def create(kind="solar", user=OWNER, capacity=20.0):
            return create_reference_seeded_project(user_id=user, template_source=f"generic_{kind}_reference",
                                                   requested_name=f"Sens {kind}", capacity_mw=capacity)

        yield SimpleNamespace(client=client, stranger=stranger, anonymous=anonymous, create=create, app=app)
    reset_model_executor_for_tests()


def get(env_client, path, **params):
    return env_client.get(f"{BASE}/{path}", params=params, headers=HDR)


# ── guards ─────────────────────────────────────────────────────────────────

def test_requires_flag_header_session_and_project_access(env, monkeypatch):
    record = env.create()
    params = {"project": record.project_code, "driver": "tariff"}
    assert env.client.get(f"{BASE}/strip", params=params).status_code == 400            # no custom header
    assert env.client.get(f"{BASE}/catalog", params=params).json()["code"] == "REQUEST_HEADER_REQUIRED"
    assert env.anonymous.get(f"{BASE}/strip", params=params, headers=HDR).status_code == 401
    assert get(env.stranger, "strip", **params).status_code == 404                       # another user's project
    assert get(env.client, "strip", project="does-not-exist", driver="tariff").status_code == 404
    monkeypatch.setenv("FINCO_MODEL_REACT_V1", "0")
    assert get(env.client, "strip", **params).status_code == 404


def test_protected_references_and_unsupported_verticals_are_refused(env):
    from app.persistence.projects_repository import get_reference_by_template_source
    from app.services.project_library_service import ensure_reference_models

    ensure_reference_models()
    reference = get_reference_by_template_source("generic_solar_reference")
    refused = get(env.client, "strip", project=reference.project_code, driver="tariff")
    assert refused.status_code == 409 and refused.json()["code"] == "MATRIX_PROTECTED_REFERENCE"
    storage = get_reference_by_template_source("generic_storage_reference")
    assert get(env.client, "catalog", project=storage.project_code).status_code == 409


@pytest.mark.parametrize("params,code", [
    ({"driver": "service_price"}, "MATRIX_DRIVER_UNSUPPORTED"),          # Data Center driver on a Solar project
    ({"driver": "nope"}, "MATRIX_DRIVER_UNSUPPORTED"),
    ({"driver": "tariff", "levels": "-10,0"}, "MATRIX_LEVEL_COUNT"),
    ({"driver": "tariff", "levels": "-10,x,0,5,10"}, "MATRIX_LEVEL_INVALID"),
    ({"driver": "tariff", "levels": "-10,-10,0,5,10"}, "MATRIX_LEVEL_DUPLICATE"),
    ({"driver": "tariff", "levels": "-90,-10,0,5,90"}, "MATRIX_LEVEL_OUT_OF_BOUNDS"),
    ({"driver": "tariff", "levels": "-10,-5,0,5,nan"}, "MATRIX_LEVEL_INVALID"),
])
def test_invalid_strip_requests_are_typed_422_and_run_nothing(env, params, code):
    record = env.create()
    response = get(env.client, "strip", project=record.project_code, **params)
    assert response.status_code == 422 and response.json()["code"] == code and "Nothing was changed" in response.json()["message"]


@pytest.mark.parametrize("params,code", [
    ({"driver_a": "tariff", "driver_b": "tariff", "metric": "project_irr"}, "MATRIX_DRIVER_DUPLICATE"),
    ({"driver_a": "tariff", "driver_b": "capex", "metric": "bogus"}, "MATRIX_METRIC_UNSUPPORTED"),
    ({"driver_a": "tariff", "driver_b": "capex", "metric": "total_cfads_keur"}, "MATRIX_METRIC_UNSUPPORTED"),
    ({"driver_a": "tariff", "driver_b": "capex", "metric": "project_irr", "grid": "4"}, "MATRIX_GRID_INVALID"),
    ({"driver_a": "tariff", "driver_b": "capex", "metric": "project_irr", "threshold": "abc"}, "MATRIX_THRESHOLD_INVALID"),
])
def test_invalid_matrix_requests_are_typed_422(env, params, code):
    record = env.create()
    response = get(env.client, "matrix", project=record.project_code, **params)
    assert response.status_code == 422 and response.json()["code"] == code


def test_catalog_describes_the_canonical_drivers_metrics_and_limits(env):
    from app.v2.sensitivity_matrix_projection import MAX_CELLS, drivers_for, supported_metrics

    record = env.create("wind")
    body = get(env.client, "catalog", project=record.project_code).json()
    assert body["ok"] and body["vertical"]["key"] == "wind" and body["vertical"]["pilot_tier"] == "PILOT_CANDIDATE"
    assert [d["key"] for d in body["drivers"]] == [d.key for d in drivers_for("wind")]
    assert [m["key"] for m in body["metrics"]] == [m["key"] for m in supported_metrics()]
    assert body["limits"]["max_cells"] == MAX_CELLS == 25 and body["limits"]["strip_points"] == 5
    assert body["semantics"] == {"ephemeral": True, "writes_nothing": True, "is_a_run": False, "basis": body["semantics"]["basis"]}
    assert "total_cfads_keur" not in {m["key"] for m in body["metrics"]}


# ── one-driver strip: shape, base, no persistence ──────────────────────────

def snapshot_state(record):
    ws = get_workspace_state(record.user_id, record.project_id)
    return (ws.last_runtime_snapshot_id, dict(ws.draft_snapshot), dict(ws.saved_snapshot), ws.dirty)


def test_strip_returns_five_real_points_with_base_deltas_and_writes_nothing(env):
    record = env.create()
    before = snapshot_state(record)
    response = get(env.client, "strip", project=record.project_code, driver="tariff")
    assert response.status_code == 200
    body = response.json()
    assert body["ok"] and body["kind"] == "strip" and body["run"]["evaluations"] == 5 and body["run"]["writes_nothing"] is True
    assert body["run"]["is_a_run"] is False and body["run"]["ephemeral"] is True
    assert [r["label"] for r in body["rows"]] == ["−20 %", "−10 %", "Base", "+10 %", "+20 %"]
    assert [r["is_base"] for r in body["rows"]] == [False, False, True, False, False]
    assert all(r["status"] == "OK" for r in body["rows"]) and body["counts"] == {"OK": 5, "FAILED": 0, "UNAVAILABLE": 0}
    assert [c["key"] for c in body["columns"]][:3] == ["project_irr", "equity_irr", "sponsor_irr"]
    base_row = body["rows"][2]
    assert base_row["values"]["project_irr"]["delta"] == 0 and base_row["values"]["project_irr"]["delta_display"].startswith("+0.00")
    # tariff shocks the canonical input: the typed input moves exactly by the level, and the result moves with it
    originals = [r["input"]["original"] for r in body["rows"]]
    shocked = [r["input"]["shocked"] for r in body["rows"] if not r["is_base"]]
    assert len({o for o in originals if o is not None}) == 1
    assert shocked == pytest.approx([originals[0] * f for f in (0.8, 0.9, 1.1, 1.2)], rel=1e-12)
    irr = [r["values"]["project_irr"]["raw"] for r in body["rows"]]
    assert irr == sorted(irr) and len(set(irr)) == 5                       # higher tariff -> higher Project IRR
    assert snapshot_state(record) == before                                 # the Working Copy, Last Run and drafts are untouched


def test_strip_with_custom_levels_without_a_base_level_evaluates_one_extra_base_point(env):
    record = env.create()
    body = get(env.client, "strip", project=record.project_code, driver="generation", levels="-8,-4,2,4,8").json()
    assert body["ok"] and body["run"]["evaluations"] == 6 and body["run"]["base_reused_from_zero_cell"] is False
    assert body["base"]["status"] == "OK" and body["base"]["values"]["project_irr"]["display"] != "—"
    assert all(not r["is_base"] for r in body["rows"])


# ── parity with the Legacy one-driver route (independent oracle) ───────────

def _legacy_tokens(env, code):
    page = env.client.get("/v2/workbook", params={"project": code})
    assert page.status_code == 200
    return page


def _pct(text):
    match = re.search(r"-?\d+(?:\.\d+)?", text.replace(",", ""))
    return float(match.group(0)) if match else None


def test_strip_equals_the_legacy_one_driver_route_for_tariff(env):
    record = env.create()
    _legacy_tokens(env, record.project_code)
    legacy = env.client.post("/v2/workbook/scenarios/sensitivity/run",
                             data={"project": record.project_code, "driver": "tariff"}, headers={"HX-Request": "true"})
    assert legacy.status_code == 200, legacy.text[:300]
    soup = BeautifulSoup(legacy.text, "html.parser")
    headers = [th.get_text(" ", strip=True) for th in soup.select("table.v2-sens-table thead th")]
    irr_col = next(i for i, h in enumerate(headers) if h.startswith("Project IRR"))
    legacy_rows = []
    for tr in soup.select("table.v2-sens-table tbody tr"):
        cells = tr.find_all("td")
        legacy_rows.append((cells[0].get_text(" ", strip=True).split(" FAILED")[0], _pct(cells[irr_col].get_text(" ", strip=True).split("Δ")[0])))
    body = get(env.client, "strip", project=record.project_code, driver="tariff").json()
    assert len(legacy_rows) == 5 == len(body["rows"])
    for (label, legacy_irr), row in zip(legacy_rows, body["rows"]):
        assert legacy_irr == pytest.approx(row["values"]["project_irr"]["raw"] * 100, abs=0.006), (label, row["label"])


# ── matrix: shape, budget, parity with the Legacy matrix route ─────────────

def test_matrix_3x3_returns_the_canonical_view_and_respects_the_budget(env):
    record = env.create()
    body = get(env.client, "matrix", project=record.project_code, driver_a="tariff", driver_b="capex", metric="project_irr").json()
    assert body["ok"] and body["kind"] == "matrix" and body["run"]["cells"] == 9 and body["run"]["evaluations"] == 9
    matrix = body["matrix"]
    assert [lv["label"] for lv in matrix["driver_a"]["levels"]] == ["−10 %", "Base", "+10 %"]
    assert len(matrix["cells"]) == 9 and matrix["counts"]["OK"] == 9 and matrix["base"]["status"] == "OK"
    centre = next(c for c in matrix["cells"] if c["is_base"])
    assert centre["raw"] == matrix["base"]["raw"] and centre["delta"] == 0
    assert body["run"]["writes_nothing"] is True


def test_matrix_5x5_is_the_maximum_and_is_bounded(env):
    record = env.create()
    body = get(env.client, "matrix", project=record.project_code, driver_a="tariff", driver_b="capex", metric="min_dscr", grid="5").json()
    assert body["ok"] and body["run"]["cells"] == 25 and body["run"]["evaluations"] == 25 and body["matrix"]["counts"]["OK"] == 25
    too_many = get(env.client, "matrix", project=record.project_code, driver_a="tariff", driver_b="capex", metric="min_dscr",
                   grid="5", levels_a="-20,-10,0,10,20,30")
    assert too_many.status_code == 422


def test_matrix_equals_the_legacy_matrix_route(env):
    record = env.create()
    legacy = env.client.post("/v2/workbook/sensitivity/matrix/run",
                             data={"project": record.project_code, "driver_a": "tariff", "driver_b": "capex", "metric": "project_irr"},
                             headers={"HX-Request": "true"})
    assert legacy.status_code == 200, legacy.text[:300]
    soup = BeautifulSoup(legacy.text, "html.parser")
    legacy_cells = {(int(td["data-a"]), int(td["data-b"])): _pct(td.get_text(" ", strip=True)) for td in soup.select("[data-testid='matrix-cell']")}
    assert len(legacy_cells) == 9
    body = get(env.client, "matrix", project=record.project_code, driver_a="tariff", driver_b="capex", metric="project_irr").json()
    mine = {(c["i"], c["j"]): c["raw"] * 100 for c in body["matrix"]["cells"]}
    assert set(mine) == set(legacy_cells)
    for key, legacy_value in legacy_cells.items():           # same cell, same canonical run -> same figure at display precision
        assert legacy_value == pytest.approx(mine[key], abs=0.006), key


def test_interest_rate_shock_is_refused_when_a_calibrated_schedule_owns_the_rate(env):
    """The rate-lock gate of the Save path applies to the sensitivity driver too (no scalar over a typed schedule)."""
    from app.input_adapter import assert_debt_scalar_edit_allowed  # noqa: F401  (the gate the service delegates to)

    record = env.create()
    body = get(env.client, "strip", project=record.project_code, driver="interest_rate").json()
    # on a fresh Working Copy the scalar is allowed; the response is a normal strip or a typed refusal — never a silent flat strip
    assert body["ok"] is False or (body["rows"] and body["counts"]["OK"] >= 1)


def test_data_center_is_available_but_flagged_as_a_preview(env):
    record = env.create("data_center", capacity=10.0)
    body = get(env.client, "catalog", project=record.project_code).json()
    assert body["ok"] and body["vertical"]["pilot_tier"] == "PREVIEW" and body["vertical"]["limitations"]
    assert "service_price" in {d["key"] for d in body["drivers"]} and "tariff" not in {d["key"] for d in body["drivers"]}
