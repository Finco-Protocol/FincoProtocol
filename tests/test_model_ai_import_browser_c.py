"""True authenticated browser acceptance for Workflow C, using synthetic inputs.

Drives a real uvicorn app with actual signed session cookies, production
routing/templates and SQLite persistence. No financial engine on file upload
or approval, no customer spreadsheets and no external AI calls.
"""
from __future__ import annotations

import io
import socket
import threading
import time
from pathlib import Path

import pytest

pytest.importorskip("playwright")
pytest.importorskip("uvicorn")

from openpyxl import Workbook
from playwright.sync_api import sync_playwright

OWNER = "import-c-browser-owner"
CODE = "synthetic-import-solar"


def _port():
    with socket.socket() as sock:
        sock.bind(("127.0.0.1", 0))
        return sock.getsockname()[1]


@pytest.fixture(scope="module")
def app_server(tmp_path_factory):
    from app.persistence import db

    db.DB_PATH = str(tmp_path_factory.mktemp("synthetic-import-browser") / "import.db")
    from app.persistence.db import init_db
    init_db()
    from app.persistence.projects_repository import save_project
    from app.persistence.workspace_repository import save_workspace_state

    project = save_project(
        user_id=OWNER, project_code=CODE, project_name="Synthetic Import Solar",
        source_project_template="generic_solar_reference",
        template_source="generic_solar_reference",
        project_type="Solar", project_origin="working_copy",
        project_role="working_copy")
    snapshot = {
        "active_project": CODE, "template_source": "generic_solar_reference",
        "project_origin": "working_copy", "project_type": "solar_pv",
        "construction_months": "18", "horizon_years": "25",
        "p50_hours": "1700",
    }
    save_workspace_state(
        user_id=OWNER, project_id=project.project_id,
        project_code=CODE, draft_snapshot=snapshot, saved_snapshot=snapshot,
    )
    import main_web
    import uvicorn

    port = _port()
    # No reference-bootstrap financial runs and no model executor prewarm;
    # only explicit HTTP requests are exercised.
    server = uvicorn.Server(uvicorn.Config(
        main_web.app, host="127.0.0.1", port=port,
        log_level="error", lifespan="off"))
    thread = threading.Thread(target=server.run, daemon=True)
    thread.start()
    deadline = time.monotonic() + 30
    while not server.started and time.monotonic() < deadline:
        time.sleep(0.05)
    assert server.started, "Synthetic import test server did not start"
    try:
        yield {"url": f"http://127.0.0.1:{port}", "project": project,
               "snapshot": snapshot}
    finally:
        server.should_exit = True
        thread.join(timeout=10)


@pytest.fixture(scope="module")
def browser():
    with sync_playwright() as pw:
        instance = pw.chromium.launch(args=["--no-sandbox"])
        yield instance
        instance.close()


def _page(browser, url, *, authenticated=True, width=1440):
    from app.auth import COOKIE_NAME, create_session_token
    ctx = browser.new_context(viewport={"width": width, "height": 900})
    if authenticated:
        ctx.add_cookies([{
            "name": COOKIE_NAME,
            "value": create_session_token(user_id=OWNER, username=OWNER),
            "url": url,
            "path": "/",
        }])
    page = ctx.new_page()
    page.browser_errors = []
    page.on("pageerror", lambda error: page.browser_errors.append(str(error)))
    return ctx, page


def test_authenticated_csv_review_apply_without_automatic_run(browser, app_server, tmp_path):
    from app.persistence.workspace_repository import get_workspace_state
    from app.workbook.workbook_identity import assemble_consistent_for_get
    from app.workbook.registry import WORKBOOK

    p = app_server["project"]
    original = get_workspace_state(OWNER, p.project_id)
    initial_hash = assemble_consistent_for_get(
        OWNER, p.project_id, WORKBOOK.version).composite_hash

    ctx, page = _page(browser, app_server["url"])
    try:
        response = page.goto(app_server["url"] + "/v2/workbook/import?project=" + CODE)
        assert response and response.status == 200
        assert page.get_by_text("CSV/XLSX Input Import").count() == 1

        csv_path = tmp_path / "synthetic-input.csv"
        csv_path.write_text(
            "Assumption,Value,Unit\n"
            "revenue.ppa.index,0.02,fraction\n"
            "project_setup.technical.horizon_years,28,years\n",
            encoding="utf-8")
        page.locator("#upload").set_input_files(str(csv_path))
        page.get_by_role("button", name="Extract and review").click()
        assert page.get_by_text("Review detected assumptions").count() == 1
        # Upload/extract must never change the saved financial state or create runs.
        after_upload = get_workspace_state(OWNER, p.project_id)
        assert after_upload.draft_snapshot == original.draft_snapshot
        assert not after_upload.last_runtime_snapshot_id
        assert assemble_consistent_for_get(
            OWNER, p.project_id, WORKBOOK.version).composite_hash == initial_hash

        page.locator('input[name="keep_0"]').check()
        page.locator('input[name="keep_1"]').check()
        page.get_by_role("button", name="Review approved change set").click()
        assert page.get_by_text("Final confirmation", exact=False).count() == 1
        after_review = get_workspace_state(OWNER, p.project_id)
        assert after_review.draft_snapshot == original.draft_snapshot
        page.get_by_role("button", name="Apply 2 approved fields atomically").click()
        assert page.get_by_text("Import Apply result").count() == 1
        saved = get_workspace_state(OWNER, p.project_id)
        assert saved.draft_snapshot["rev_ppa_index"] == "2.0"
        assert saved.draft_snapshot["horizon_years"] == "28"
        assert saved.saved_snapshot == original.saved_snapshot
        assert not saved.last_runtime_snapshot_id
        assert page.get_by_text("This is not a successful financial model run.").count() >= 0
        assert not page.browser_errors
        page.screenshot(path=str(tmp_path / "import-c-solar-applied.png"), full_page=True)
    finally:
        ctx.close()


def test_wind_xlsx_readonly_multisheet_mobile(browser, app_server, tmp_path):
    from app.persistence.workspace_repository import get_workspace_state
    original = get_workspace_state(OWNER, app_server["project"].project_id)
    book = Workbook()
    a = book.active
    a.title = "Technical"
    a.append(["Assumption", "Value", "Unit"])
    a.append(["project_setup.technical.construction_months", 24, "months"])
    b = book.create_sheet("Revenue")
    b.append(["Assumption", "Value", "Unit"])
    b.append(["revenue.ppa.index", 3.5, "%"])
    stream = io.BytesIO()
    book.save(stream)
    file_path = tmp_path / "synthetic-wind.xlsx"
    file_path.write_bytes(stream.getvalue())

    ctx, page = _page(browser, app_server["url"], width=390)
    try:
        page.goto(app_server["url"] + "/v2/workbook/import?project=" + CODE)
        page.locator("#upload").set_input_files(str(file_path))
        page.get_by_role("button", name="Extract and review").click()
        assert page.get_by_text("Review detected assumptions").count() == 1
        assert page.locator("tr.review-row").count() == 2
        page.get_by_role("button", name="Needs review").click()
        page.get_by_role("button", name="All", exact=True).click()
        page.reload()
        assert page.locator("#upload").count() == 1
        assert get_workspace_state(OWNER, app_server["project"].project_id).draft_snapshot == original.draft_snapshot
        assert not page.browser_errors
        page.screenshot(path=str(tmp_path / "import-c-mobile.png"), full_page=True)
    finally:
        ctx.close()


def test_invalid_session_redirects_and_no_writes(browser, app_server):
    from app.persistence.workspace_repository import get_workspace_state
    before = get_workspace_state(OWNER, app_server["project"].project_id)
    ctx, page = _page(browser, app_server["url"], authenticated=False)
    try:
        page.goto(app_server["url"] + "/v2/workbook/import?project=" + CODE)
        assert "/login" in page.url
        assert get_workspace_state(OWNER, app_server["project"].project_id).draft_snapshot == before.draft_snapshot
    finally:
        ctx.close()
