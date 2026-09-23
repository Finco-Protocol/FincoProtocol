"""Product entry checks on an isolated database; no model run is performed."""
from __future__ import annotations

import pytest
from starlette.testclient import TestClient


@pytest.fixture
def client_with_references(tmp_path, monkeypatch):
    from app.persistence import db
    monkeypatch.setattr(db, "DB_PATH", str(tmp_path / "product-entry.db"))
    import main_web
    from app.services.project_library_service import ensure_reference_models
    with TestClient(main_web.app, raise_server_exceptions=False) as client:
        ensure_reference_models()
        yield client


def _cookie():
    from app.auth import DEMO_COOKIE_NAME, create_demo_session_token, new_demo_user_id
    user_id = new_demo_user_id()
    return user_id, {DEMO_COOKIE_NAME: create_demo_session_token(user_id)}


@pytest.mark.parametrize("source", [
    "generic_solar_reference", "generic_wind_reference", "generic_storage_reference",
])
@pytest.mark.parametrize("htmx", [False, True])
def test_reference_clone_opens_independent_working_project(client_with_references, source, htmx):
    from app.persistence.db import get_connection
    from app.persistence.projects_repository import get_reference_by_template_source
    reference = get_reference_by_template_source(source)
    assert reference and reference.project_role == "reference" and reference.is_protected
    user_id, cookies = _cookie()
    response = client_with_references.post(
        f"/library/clone/{reference.project_id}",
        cookies=cookies,
        headers={"HX-Request": "true"} if htmx else {},
        follow_redirects=False,
    )
    assert response.status_code == (204 if htmx else 303)
    destination = response.headers["HX-Redirect" if htmx else "Location"]
    with get_connection() as conn:
        copy = conn.execute("SELECT * FROM projects WHERE user_id=?", (user_id,)).fetchone()
        original = conn.execute("SELECT * FROM projects WHERE project_id=?", (reference.project_id,)).fetchone()
        workspace = conn.execute("SELECT * FROM workspace_states WHERE project_id=?", (copy["project_id"],)).fetchone()
        base = conn.execute("SELECT * FROM scenarios WHERE project_id=? AND is_base_case=1", (copy["project_id"],)).fetchone()
    assert copy["project_role"] == "working_copy" and not copy["is_protected"] and not copy["is_readonly"]
    assert copy["source_project_id"] == reference.project_id
    assert original["user_id"] == "__reference__" and original["is_protected"]
    assert workspace is not None and base is not None
    assert copy["project_code"] in destination and destination.startswith("/v2/workbook?")


def test_library_has_no_project_commands_or_global_kpis(client_with_references):
    _, cookies = _cookie()
    response = client_with_references.get("/library", cookies=cookies)
    assert response.status_code == 200
    html = response.text
    assert "Model Workspace" in html and "Reference Templates" in html
    assert html.count("Create working copy") == 3
    assert 'id="fo-kpi-strip"' not in html
    assert 'id="fo-btn-run"' not in html
    assert 'id="project-sidebar"' not in html
    assert 'class="app-layout app-layout--no-project"' in html
