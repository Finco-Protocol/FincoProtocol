"""FINCO48 Slice C — Physical Model HTMX decommission and unconditional React cutover contract."""
from __future__ import annotations

from pathlib import Path
from types import SimpleNamespace

import pytest
from fastapi.testclient import TestClient

from app.auth import COOKIE_NAME, create_session_token
from app.persistence import db
from app.runtime.model_execution import reset_model_executor_for_tests
from app.services.project_library_service import ensure_reference_models
from app.services.reference_seed_service import create_reference_seeded_project

REPO = Path(__file__).resolve().parents[1]


@pytest.fixture
def client_and_project(tmp_path, monkeypatch):
    import main_web

    monkeypatch.setattr(db, "DB_PATH", str(tmp_path / "finco48_decomm.db"))
    db.init_db()
    ensure_reference_models()
    uid = "finco48-decomm-owner"
    record = create_reference_seeded_project(
        user_id=uid,
        template_source="generic_solar_reference",
        requested_name="FINCO48 Decomm Contract",
        capacity_mw=16,
    )
    with TestClient(main_web.app, raise_server_exceptions=True) as client:
        client.cookies.set(COOKIE_NAME, create_session_token(user_id=uid, username="owner"))
        yield client, record
    reset_model_executor_for_tests()


def test_unconditional_react_even_with_flag_zero(client_and_project, monkeypatch):
    client, record = client_and_project
    monkeypatch.setenv("FINCO_MODEL_REACT_V1", "0")

    from app.v2.react_poc_router import react_poc_enabled
    import main_web

    assert react_poc_enabled() is True
    assert main_web._finco_model_react_flag(SimpleNamespace()) == {"finco_model_react": True}

    redirect_expectations = [
        ("/library", "/v2/model-react/"),
        ("/v2/workbook", "/v2/model-react/"),
        (f"/v2/workbook?project={record.project_code}", f"/v2/model-react/{record.project_code}"),
        ("/projects/new", "/v2/model-react/#new-project"),
        ("/projects/new/minimal", "/v2/model-react/#new-project"),
        ("/projects", "/v2/model-react/"),
        ("/projects/browse", "/v2/model-react/"),
        ("/pilot-guide", "/v2/model-react/#guide"),
        ("/help", "/v2/model-react/#guide"),
        ("/scenarios", "/v2/model-react/"),
        ("/home", "/v2/model-react/"),
    ]
    for path, expected_prefix in redirect_expectations:
        resp = client.get(path, follow_redirects=False)
        assert resp.status_code == 302, (path, resp.status_code, resp.text[:200])
        assert expected_prefix in resp.headers.get("location", ""), (path, resp.headers.get("location"))

    for shell_path in ("/v2/model-react", f"/v2/model-react/{record.project_code}"):
        shell = client.get(shell_path, follow_redirects=False)
        assert shell.status_code == 200, (shell_path, shell.status_code)
        assert "finco-react.js" in shell.text
        assert "React preview unavailable" not in shell.text

    slash_shell = client.get("/v2/model-react/", follow_redirects=True)
    assert slash_shell.status_code == 200 and "finco-react.js" in slash_shell.text

    boot = client.get("/v2/model-react/bootstrap", params={"project": record.project_code})
    assert boot.status_code == 200 and boot.json().get("ok") is True
    assert boot.json().get("code") != "REACT_POC_DISABLED"


def test_forged_htmx_get_on_model_presentation_routes_returns_410(client_and_project):
    client, record = client_and_project
    code = record.project_code
    htmx_routes = [
        "/library",
        "/library/list",
        f"/v2/workbook?project={code}",
        f"/v2/workbook/outputs?project={code}",
        f"/v2/workbook/diagnostics?project={code}",
        f"/v2/workbook/grid/sheet?project={code}&sheet=inputs",
        f"/v2/workbook/grid/panel?project={code}",
        f"/v2/workbook/trust/certificate?project={code}",
        f"/v2/workbook/trust/validation?project={code}",
        f"/v2/workbook/run-history?project={code}",
        f"/v2/workbook/run-compare?project={code}",
        f"/v2/workbook/scenarios/compare?project={code}",
        f"/v2/workbook/financing/integrity?project={code}",
        f"/v2/workbook/financing/investor?project={code}",
    ]
    for url in htmx_routes:
        resp = client.get(url, headers={"HX-Request": "true"}, follow_redirects=False)
        assert resp.status_code == 410, (url, resp.status_code, resp.text[:200])
        assert resp.json().get("code") == "HTMX_DECOMMISSIONED", (url, resp.text[:200])


def test_dead_legacy_model_templates_and_assets_removed_from_disk():
    removed_paths = [
        "app/templates/v2/workbook.html",
        "app/templates/v2/react_poc_fallback.html",
        "app/templates/v2/unsupported_workbook.html",
        "app/templates/v2/workbook_recovery.html",
        "app/templates/library/project_library.html",
        "app/templates/library/project_library_list.html",
        "static/js/workbook_v2.js",
        "static/js/inputs_grid_v1.js",
        "static/js/cost_staging.js",
        "static/css/workbook_v2.css",
    ]
    still_present = [rel for rel in removed_paths if (REPO / rel).exists()]
    assert not still_present, f"Legacy Model files still on disk: {still_present}"


def test_radar_and_public_surfaces_remain_healthy(client_and_project):
    client, _record = client_and_project
    for path in ("/", "/docs", "/api", "/radar/stocks", "/radar/r-live"):
        resp = client.get(path, follow_redirects=False)
        assert resp.status_code == 200, (path, resp.status_code)

    radar_htmx = client.get("/radar/stocks", headers={"HX-Request": "true"}, follow_redirects=False)
    assert radar_htmx.status_code == 200
