"""Product entry checks on an isolated database; no model run is performed."""
from __future__ import annotations

from tests.run_clone_csrf import post_valid_csrf

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


def _assert_no_project_for(user_id):
    from app.persistence.db import get_connection
    with get_connection() as conn:
        assert conn.execute("SELECT COUNT(*) FROM projects WHERE user_id=?", (user_id,)).fetchone()[0] == 0


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
    response = post_valid_csrf(client_with_references,
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
    response = post_valid_csrf(client_with_references,
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
    response = client_with_references.get("/v2/model-react/library", cookies=cookies)
    assert response.status_code == 200
    payload = response.json()
    assert payload["ok"] is True
    assert payload["projects"] == []
    # Solar + Wind + Data Center + EV Charging are cloneable (Storage is RELEASE_CLOSED).
    cloneable = [r for r in payload["references"] if r["vertical"]["pilot_tier"] != "RELEASE_CLOSED"]
    closed = [r for r in payload["references"] if r["vertical"]["pilot_tier"] == "RELEASE_CLOSED"]
    assert len(cloneable) == 4 and len(closed) == 1
    assert "kpis" not in payload


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
    for url in ("/v2/model-react/library", "/v2/model-react/library?page=2") if count > 20 else ("/v2/model-react/library",):
        response = client_with_references.get(url, cookies=cookies)
        assert response.status_code == 200
        payload = response.json()
        ref_templates = {r["template_source"] for r in payload["references"]}
        assert ref_templates == {
            "generic_solar_reference", "generic_wind_reference", "generic_storage_reference",
            "generic_data_center_reference", "generic_ev_charging_reference",
        }
        assert len(payload["projects"]) == min(count - (20 if "page=2" in url else 0), 20)
    search = client_with_references.get("/v2/model-react/library?search=Solar", cookies=cookies).json()
    assert any(r["template_source"] == "generic_solar_reference" for r in search["references"])
    assert not any(r["template_source"] == "generic_wind_reference" for r in search["references"])
    working_only = client_with_references.get("/v2/model-react/library?role=working_copy", cookies=cookies).json()
    assert working_only["projects"] is not None


def test_clone_unexpected_error_htmx_returns_500_with_safe_body(client_with_references, monkeypatch, caplog):
    from app.persistence.projects_repository import get_reference_by_template_source
    from app.services import project_library_service
    reference = get_reference_by_template_source("generic_solar_reference")
    user_id, cookies = _cookie()

    def failed_clone(*args, **kwargs):
        raise RuntimeError("private-payload-marker")

    # #419 Correction K: since R18 the canonical unkeyed clone runs through the atomic ``_create_working_copy`` lifecycle (the public
    # ``create_working_copy`` wraps that same function), so the fault is injected on the ACTIVE clone path. Same 500 / safe-body contract.
    monkeypatch.setattr(project_library_service, "create_working_copy", failed_clone)
    monkeypatch.setattr(project_library_service, "_create_working_copy", failed_clone)
    response = post_valid_csrf(client_with_references,
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
    assert "HX-Redirect" not in response.headers and "location" not in response.headers      # never a false success
    _assert_no_project_for(user_id)


def test_clone_unexpected_error_non_htmx_returns_500_with_safe_body(client_with_references, monkeypatch, caplog):
    from app.persistence.projects_repository import get_reference_by_template_source
    from app.services import project_library_service
    reference = get_reference_by_template_source("generic_solar_reference")
    user_id, cookies = _cookie()

    def failed_clone(*args, **kwargs):
        raise RuntimeError("private-payload-marker")

    # #419 Correction K: since R18 the canonical unkeyed clone runs through the atomic ``_create_working_copy`` lifecycle (the public
    # ``create_working_copy`` wraps that same function), so the fault is injected on the ACTIVE clone path. Same 500 / safe-body contract.
    monkeypatch.setattr(project_library_service, "create_working_copy", failed_clone)
    monkeypatch.setattr(project_library_service, "_create_working_copy", failed_clone)
    response = post_valid_csrf(client_with_references,
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
    assert "HX-Redirect" not in response.headers and "location" not in response.headers      # never a false success
    _assert_no_project_for(user_id)
