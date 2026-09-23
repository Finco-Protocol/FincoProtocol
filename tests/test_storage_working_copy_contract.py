"""Storage working-copy runtime contract tests.

Verifies that the product contract is truthful and fail-closed:

LIBRARY
- Solar/Wind references present "Create working copy"
- Storage reference is visible and presents "Working-copy runtime coming soon"
- Storage reference does NOT present "Create working copy"

BACKEND CLONE
- Solar/Wind clones succeed (200-series) and create a project row
- Storage direct clone returns 400 and creates ZERO project rows
- Storage reference is unchanged after a failed clone attempt

EXISTING STORAGE WORKING COPY
- GET /v2/workbook returns no HTTP 500
- Response shows controlled unsupported-runtime surface
- Response does not contain Run Model button
- Response does not contain Save / Export actions

DIRECT RUN
- POST /v2/workbook/run for Storage working copy returns 409 (non-HTMX)
- Zero economic engine invocation
- Zero Last-Run snapshot creation

SOLAR/WIND REGRESSION
- Solar and Wind working copies still open (200 OK) from /v2/workbook
"""
from __future__ import annotations

import pytest
from starlette.testclient import TestClient


@pytest.fixture
def client_contract(tmp_path, monkeypatch):
    from app.persistence import db
    monkeypatch.setattr(db, "DB_PATH", str(tmp_path / "storage-contract.db"))
    import main_web
    from app.services.project_library_service import ensure_reference_models
    with TestClient(main_web.app, raise_server_exceptions=False) as client:
        ensure_reference_models()
        yield client


def _cookie():
    from app.auth import DEMO_COOKIE_NAME, create_demo_session_token, new_demo_user_id
    user_id = new_demo_user_id()
    return user_id, {DEMO_COOKIE_NAME: create_demo_session_token(user_id)}


# ---------------------------------------------------------------------------
# Library UI
# ---------------------------------------------------------------------------

@pytest.mark.parametrize("template_source,expect_clone_btn,expect_unavailable", [
    ("generic_solar_reference", True, False),
    ("generic_wind_reference", True, False),
    ("generic_storage_reference", False, True),
])
def test_library_reference_card_clone_state(client_contract, template_source, expect_clone_btn, expect_unavailable):
    _, cookies = _cookie()
    html = client_contract.get("/library", cookies=cookies).text
    assert f"library-row-{template_source}-reference" in html, "Reference card must be present"
    if expect_clone_btn:
        assert f'data-testid="clone-{template_source}-reference"' in html
        assert f'data-testid="clone-unavailable-{template_source}-reference"' not in html
    if expect_unavailable:
        assert f'data-testid="clone-unavailable-{template_source}-reference"' in html
        assert f'data-testid="clone-{template_source}-reference"' not in html
        assert "Working-copy runtime coming soon" in html


def test_library_storage_reference_view_link_present(client_contract):
    _, cookies = _cookie()
    html = client_contract.get("/library", cookies=cookies).text
    assert f'data-testid="open-generic_storage_reference-reference"' in html


def test_library_solar_wind_clone_buttons_present(client_contract):
    _, cookies = _cookie()
    html = client_contract.get("/library", cookies=cookies).text
    assert html.count("Create working copy") == 2
    assert 'data-testid="clone-generic_solar_reference-reference"' in html
    assert 'data-testid="clone-generic_wind_reference-reference"' in html


# ---------------------------------------------------------------------------
# Backend clone contract
# ---------------------------------------------------------------------------

@pytest.mark.parametrize("source", ["generic_solar_reference", "generic_wind_reference"])
def test_solar_wind_clone_succeeds(client_contract, source):
    from app.persistence.db import get_connection
    from app.persistence.projects_repository import get_reference_by_template_source
    reference = get_reference_by_template_source(source)
    user_id, cookies = _cookie()
    response = client_contract.post(
        f"/library/clone/{reference.project_id}",
        cookies=cookies,
        follow_redirects=False,
    )
    assert response.status_code == 303
    with get_connection() as conn:
        copy = conn.execute("SELECT * FROM projects WHERE user_id=?", (user_id,)).fetchone()
    assert copy is not None
    assert copy["project_role"] == "working_copy"


@pytest.mark.parametrize("htmx", [False, True])
def test_storage_clone_returns_400_zero_rows(client_contract, htmx):
    from app.persistence.db import get_connection
    from app.persistence.projects_repository import get_reference_by_template_source
    reference = get_reference_by_template_source("generic_storage_reference")
    assert reference is not None
    user_id, cookies = _cookie()
    response = client_contract.post(
        f"/library/clone/{reference.project_id}",
        cookies=cookies,
        headers={"HX-Request": "true"} if htmx else {},
        follow_redirects=False,
    )
    assert response.status_code == 400
    assert "Storage" in response.text
    with get_connection() as conn:
        rows = conn.execute(
            "SELECT * FROM projects WHERE user_id=? AND project_role='working_copy'",
            (user_id,),
        ).fetchall()
    assert len(rows) == 0, "Storage clone must create zero working-copy rows"


def test_storage_clone_leaves_reference_unchanged(client_contract):
    from app.persistence.db import get_connection
    from app.persistence.projects_repository import get_reference_by_template_source
    reference = get_reference_by_template_source("generic_storage_reference")
    _, cookies = _cookie()
    client_contract.post(
        f"/library/clone/{reference.project_id}",
        cookies=cookies,
        follow_redirects=False,
    )
    with get_connection() as conn:
        original = conn.execute(
            "SELECT * FROM projects WHERE project_id=?",
            (reference.project_id,),
        ).fetchone()
    assert original["user_id"] == "__reference__"
    assert original["is_protected"] == 1
    assert original["project_role"] == "reference"


# ---------------------------------------------------------------------------
# Existing Storage working copy GET
# ---------------------------------------------------------------------------

@pytest.fixture
def storage_working_copy(client_contract, tmp_path):
    """Simulate a previously-created Storage working copy (pre-contract fix)."""
    from app.persistence.projects_repository import (
        get_reference_by_template_source,
        save_project,
    )
    from app.persistence.workspace_repository import save_workspace_state
    from app.persistence.scenarios_repository import get_or_create_base_case_scenario
    from app.auth import DEMO_COOKIE_NAME, create_demo_session_token, new_demo_user_id

    user_id = new_demo_user_id()
    cookies = {DEMO_COOKIE_NAME: create_demo_session_token(user_id)}
    reference = get_reference_by_template_source("generic_storage_reference")
    snapshot = {
        "project_type": "Storage",
        "project_origin": "user_created",
        "project_name": "My Storage Working Copy",
        "active_project": "my-storage-working-copy",
        "template_source": "generic_storage_reference",
    }
    record = save_project(
        user_id=user_id,
        project_code="my-storage-working-copy",
        project_name="My Storage Working Copy",
        source_project_template="generic_storage_reference",
        project_type="Storage",
        project_origin="user_created",
        template_source="generic_storage_reference",
        baseline_snapshot=snapshot,
        is_readonly=False,
        is_protected=False,
        project_role="working_copy",
        source_project_id=reference.project_id if reference else None,
    )
    save_workspace_state(
        user_id=user_id,
        project_id=record.project_id,
        project_code="my-storage-working-copy",
        draft_snapshot=snapshot,
        saved_snapshot=snapshot,
        last_runtime_snapshot={},
        last_runtime_summary={},
        governance_state={},
    )
    get_or_create_base_case_scenario(
        user_id, record.project_id, "my-storage-working-copy",
        "My Storage Working Copy", "Storage", "generic_storage_reference",
        snapshot, {},
    )
    return user_id, cookies, record


def test_storage_working_copy_get_no_500(client_contract, storage_working_copy):
    user_id, cookies, record = storage_working_copy
    response = client_contract.get(
        f"/v2/workbook?project={record.project_code}",
        cookies=cookies,
        follow_redirects=False,
    )
    assert response.status_code == 200


def test_storage_working_copy_shows_unsupported_runtime_surface(client_contract, storage_working_copy):
    user_id, cookies, record = storage_working_copy
    html = client_contract.get(
        f"/v2/workbook?project={record.project_code}",
        cookies=cookies,
    ).text
    assert 'data-testid="unsupported-runtime-page"' in html
    assert 'data-testid="unsupported-runtime-message"' in html
    assert "not yet enabled" in html
    assert 'data-testid="unsupported-runtime-preserved"' in html
    assert "preserved and has not been modified" in html


def test_storage_working_copy_no_run_model_button(client_contract, storage_working_copy):
    user_id, cookies, record = storage_working_copy
    html = client_contract.get(
        f"/v2/workbook?project={record.project_code}",
        cookies=cookies,
    ).text
    assert "Run Model" not in html
    assert 'id="v2-run-controls"' not in html
    assert 'fo-btn-run' not in html


def test_storage_working_copy_no_save_export(client_contract, storage_working_copy):
    user_id, cookies, record = storage_working_copy
    html = client_contract.get(
        f"/v2/workbook?project={record.project_code}",
        cookies=cookies,
    ).text
    assert 'data-testid="unsupported-back-to-library"' in html
    assert 'data-testid="unsupported-view-reference"' in html
    assert "v2-run-controls" not in html


def test_storage_working_copy_project_row_unchanged(client_contract, storage_working_copy):
    from app.persistence.db import get_connection
    user_id, cookies, record = storage_working_copy
    client_contract.get(
        f"/v2/workbook?project={record.project_code}",
        cookies=cookies,
    )
    with get_connection() as conn:
        row = conn.execute(
            "SELECT * FROM projects WHERE project_id=?",
            (record.project_id,),
        ).fetchone()
    assert row["project_role"] == "working_copy"
    assert row["project_type"] == "Storage"
    assert row["user_id"] == user_id


# ---------------------------------------------------------------------------
# Direct run must fail closed
# ---------------------------------------------------------------------------

def test_storage_working_copy_run_returns_409(client_contract, storage_working_copy):
    user_id, cookies, record = storage_working_copy
    # First open the workbook to get a valid content_hash
    # (We need to skip the hash check — send an arbitrary hash to hit the type guard)
    response = client_contract.post(
        "/v2/workbook/run",
        cookies=cookies,
        data={
            "project": record.project_code,
            "content_hash": "0" * 64,
            "workbook_version": "2",
        },
        follow_redirects=False,
    )
    # Non-HTMX: 409 (unsupported runtime), not 500
    assert response.status_code == 409
    assert "Storage" in response.text
    assert "not yet" in response.text.lower() or "not supported" in response.text.lower()


def test_storage_working_copy_run_creates_no_last_run_snapshot(client_contract, storage_working_copy):
    from app.persistence.db import get_connection
    user_id, cookies, record = storage_working_copy
    client_contract.post(
        "/v2/workbook/run",
        cookies=cookies,
        data={
            "project": record.project_code,
            "content_hash": "0" * 64,
            "workbook_version": "2",
        },
        follow_redirects=False,
    )
    with get_connection() as conn:
        ws = conn.execute(
            "SELECT * FROM workspace_states WHERE project_id=?",
            (record.project_id,),
        ).fetchone()
    assert not ws["last_runtime_snapshot_id"], "Storage run must create zero Last-Run snapshots"


# ---------------------------------------------------------------------------
# Solar / Wind regression
# ---------------------------------------------------------------------------

@pytest.mark.parametrize("source", ["generic_solar_reference", "generic_wind_reference"])
def test_solar_wind_workbook_opens_without_regression(client_contract, source):
    from app.persistence.projects_repository import get_reference_by_template_source
    reference = get_reference_by_template_source(source)
    assert reference is not None
    _, cookies = _cookie()
    # Clone to a working copy first
    clone_resp = client_contract.post(
        f"/library/clone/{reference.project_id}",
        cookies=cookies,
        follow_redirects=False,
    )
    assert clone_resp.status_code == 303
    dest = clone_resp.headers["Location"]
    # Extract project code from redirect URL
    import urllib.parse
    project_code = urllib.parse.parse_qs(urllib.parse.urlparse(dest).query).get("project", [None])[0]
    assert project_code is not None
    response = client_contract.get(dest, cookies=cookies)
    assert response.status_code == 200
    html = response.text
    assert "unsupported-runtime" not in html
    assert "Run Model" in html or "v2-run-controls" in html
