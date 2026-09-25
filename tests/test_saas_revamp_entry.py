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
    "generic_solar_reference", "generic_wind_reference",
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


@pytest.mark.parametrize("htmx", [False, True])
def test_storage_reference_clone_returns_400_and_creates_no_project(client_with_references, htmx):
    from app.persistence.db import get_connection
    from app.persistence.projects_repository import get_reference_by_template_source
    reference = get_reference_by_template_source("generic_storage_reference")
    assert reference and reference.project_role == "reference" and reference.is_protected
    user_id, cookies = _cookie()
    response = client_with_references.post(
        f"/library/clone/{reference.project_id}",
        cookies=cookies,
        headers={"HX-Request": "true"} if htmx else {},
        follow_redirects=False,
    )
    assert response.status_code == 400
    assert "Storage" in response.text
    assert "coming soon" in response.text.lower() or "not yet" in response.text.lower()
    with get_connection() as conn:
        rows = conn.execute("SELECT * FROM projects WHERE user_id=?", (user_id,)).fetchall()
        original = conn.execute("SELECT * FROM projects WHERE project_id=?", (reference.project_id,)).fetchone()
    assert len(rows) == 0, "Storage clone must create ZERO project rows"
    assert original["user_id"] == "__reference__" and original["is_protected"], "Reference must be unchanged"


def test_library_has_no_project_commands_or_global_kpis(client_with_references):
    _, cookies = _cookie()
    response = client_with_references.get("/library", cookies=cookies)
    assert response.status_code == 200
    html = response.text
    assert "Model Workspace" in html and "Reference Templates" in html
<<<<<<< HEAD
=======
    # Solar + Wind + EV Charging are cloneable (Storage is not yet).
>>>>>>> a1613ed (EV Charging V1 (4/5): canonical reference registry integration)
    assert html.count("Create working copy") == 3
    assert "Working-copy runtime coming soon" in html
    assert 'id="fo-kpi-strip"' not in html
    assert 'id="fo-btn-run"' not in html
    assert 'id="project-sidebar"' not in html
    assert 'class="app-layout app-layout--no-project"' in html


@pytest.mark.parametrize("count", [0, 1, 25, 50])
def test_reference_templates_are_independent_of_working_project_pages(client_with_references, count):
    from app.persistence.projects_repository import save_project
    user_id, cookies = _cookie()
    for i in range(count):
        save_project(
            user_id=user_id, project_code=f"project-{i:02d}",
            project_name=f"Working {i:02d}", source_project_template="generic_solar_reference",
            project_type="Solar", project_origin="user_created", project_role="working_copy",
            baseline_snapshot={},
        )
    for url in ("/library", "/library/list?page=2") if count > 20 else ("/library",):
        response = client_with_references.get(url, cookies=cookies)
        assert response.status_code == 200
        html = response.text
        assert html.count('class="fo-library-reference-card"') == 4
<<<<<<< HEAD
        for template in ("generic_solar_reference", "generic_wind_reference", "generic_storage_reference", "generic_data_center_reference"):
=======
        for template in ("generic_solar_reference", "generic_wind_reference", "generic_storage_reference"):
>>>>>>> a1613ed (EV Charging V1 (4/5): canonical reference registry integration)
            assert f'library-row-{template}-reference' in html
        assert html.count('class="fo-library-open"') == min(count - (20 if "page=2" in url else 0), 20)
    search = client_with_references.get("/library/list?search=Solar", cookies=cookies).text
    assert 'library-row-generic_solar_reference-reference' in search
    assert 'library-row-generic_wind_reference-reference' not in search
    working_only = client_with_references.get("/library/list?role=working_copy", cookies=cookies).text
    assert 'class="fo-library-reference-card"' not in working_only


def test_clone_unexpected_error_htmx_returns_500_with_safe_body(client_with_references, monkeypatch, caplog):
    from app.persistence.projects_repository import get_reference_by_template_source
    from app.services import project_library_service
    reference = get_reference_by_template_source("generic_solar_reference")
    _, cookies = _cookie()

    def failed_clone(**kwargs):
        raise RuntimeError("private-payload-marker")

    monkeypatch.setattr(project_library_service, "create_working_copy", failed_clone)
    response = client_with_references.post(
        f"/library/clone/{reference.project_id}", cookies=cookies,
        headers={"HX-Request": "true"},
    )
    assert response.status_code == 500
    assert "Could not create a working copy" in response.text
    assert "private-payload-marker" not in response.text
    assert "private-payload-marker" not in caplog.text
    assert "route=project_library_clone" in caplog.text
    assert f"source_project_id={reference.project_id}" in caplog.text
    assert "exception_type=RuntimeError" in caplog.text
    assert "module=" in caplog.text
    assert "function=failed_clone" in caplog.text
    assert "lineno=" in caplog.text


def test_clone_unexpected_error_non_htmx_returns_500_with_safe_body(client_with_references, monkeypatch, caplog):
    from app.persistence.projects_repository import get_reference_by_template_source
    from app.services import project_library_service
    reference = get_reference_by_template_source("generic_solar_reference")
    _, cookies = _cookie()

    def failed_clone(**kwargs):
        raise RuntimeError("private-payload-marker")

    monkeypatch.setattr(project_library_service, "create_working_copy", failed_clone)
    response = client_with_references.post(
        f"/library/clone/{reference.project_id}", cookies=cookies,
    )
    assert response.status_code == 500
    assert "Could not create a working copy" in response.text
    assert "private-payload-marker" not in response.text
    assert "private-payload-marker" not in caplog.text
    assert "route=project_library_clone" in caplog.text
    assert f"source_project_id={reference.project_id}" in caplog.text
    assert "exception_type=RuntimeError" in caplog.text
    assert "module=" in caplog.text
    assert "function=failed_clone" in caplog.text
    assert "lineno=" in caplog.text
