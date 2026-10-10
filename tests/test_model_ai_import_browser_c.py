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
            "domain": "127.0.0.1",
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
        assert page.get_by_text("2 fields changed", exact=False).count() == 1
        saved = get_workspace_state(OWNER, p.project_id)
        assert saved.draft_snapshot["rev_ppa_index"] == "2.0"
        assert saved.draft_snapshot["horizon_years"] == "28"
        assert saved.saved_snapshot == original.saved_snapshot
        assert not saved.last_runtime_snapshot_id
        assert page.get_by_text("This is not a successful financial model run.").count() == 1
        assert not page.browser_errors
        Path("artifacts/model-ai-import").mkdir(parents=True, exist_ok=True)
        page.screenshot(path="artifacts/model-ai-import/import-c-solar-applied.png", full_page=True)
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
        assert page.evaluate(
            "() => document.querySelector('#upload').getBoundingClientRect().right <= innerWidth + 1"
        ), "390px Import file picker must not overflow viewport"
        page.locator("#upload").set_input_files(str(file_path))
        page.get_by_role("button", name="Extract and review").click()
        assert page.get_by_text("Review detected assumptions").count() == 1
        assert page.locator("tr.review-row").count() == 2
        page.get_by_role("button", name="Needs review").click()
        page.get_by_role("button", name="All", exact=True).click()
        page.goto(app_server["url"] + "/v2/workbook/import?project=" + CODE)
        assert page.locator("#upload").count() == 1
        assert get_workspace_state(OWNER, app_server["project"].project_id).draft_snapshot == original.draft_snapshot
        assert not page.browser_errors
        Path("artifacts/model-ai-import").mkdir(parents=True, exist_ok=True)
        page.screenshot(path="artifacts/model-ai-import/import-c-mobile.png", full_page=True)
    finally:
        ctx.close()


def _owner_financial_evidence(project_id: str):
    """Persisted owner-only financial and historical state, before/after denial."""
    from app.persistence.workspace_repository import get_workspace_state
    from app.persistence.run_history_repository import get_run_history
    from app.persistence.db import get_connection

    ws = get_workspace_state(OWNER, project_id)
    assert ws is not None
    conn = get_connection()
    try:
        run_count = conn.execute(
            "SELECT COUNT(*) FROM runs WHERE user_id=?", (OWNER,)
        ).fetchone()[0]
    finally:
        conn.close()
    return {
        "draft": ws.draft_snapshot,
        "saved": ws.saved_snapshot,
        "dirty": ws.dirty,
        "runtime_id": ws.last_runtime_snapshot_id,
        "runtime_snapshot": ws.last_runtime_snapshot,
        "runtime_summary": ws.last_runtime_summary,
        "runtime_identity": ws.last_runtime_identity,
        "run_committed": ws.any_run_committed,
        "runs": run_count,
        "history": tuple(e.history_id for e in get_run_history(OWNER, project_id)),
    }


def _foreign_apply_ticket(project_id: str):
    """Real signed owner-bound ticket, never exposed to the foreign browser."""
    from app.model_import.review import seal_approved
    from app.workbook.workbook_identity import assemble_consistent_for_get
    from app.workbook.registry import WORKBOOK
    from app.persistence.workspace_repository import get_workspace_state

    ws = get_workspace_state(OWNER, project_id)
    identity = assemble_consistent_for_get(OWNER, project_id, WORKBOOK.version)
    approved = [{
        "source_id": 0, "sheet": "CSV", "cell": "B2",
        "label": "PPA Index", "field_id": "revenue.ppa.index",
        "value": "2", "unit": "%", "original_value": "2", "method": "exact_field_id",
    }]
    return seal_approved(
        {
            "owner": OWNER, "project_id": project_id,
            "scenario_id": ws.active_scenario_id,
            "content_hash": identity.composite_hash,
            "workbook_version": WORKBOOK.version,
            "digest": "f" * 64, "rows": [approved[0]],
        }, approved,
    )


def _assert_foreign_import_denied(*, ctx, page, app_server, expected_destination: str):
    """GET and all three POST boundaries reject a non-owner before ticket issuance."""
    from app.auth import generate_csrf_token
    from app.model_import.review import seal_preview
    from app.workbook.registry import WORKBOOK
    from app.workbook.workbook_identity import assemble_consistent_for_get

    url = app_server["url"]
    project = app_server["project"]
    evidence_before = _owner_financial_evidence(project.project_id)

    # Browser follows the 302: the user sees only their own Library/login.
    page.goto(url + "/v2/workbook/import?project=" + CODE)
    assert page.url == url + expected_destination
    assert CODE not in page.locator("body").inner_text()
    assert page.locator("#upload").count() == 0
    assert page.locator("input[name='preview_ticket']").count() == 0
    assert page.locator("input[name='approved_ticket']").count() == 0

    csrf = generate_csrf_token()
    signed_preview = seal_preview(
        owner=OWNER, project_id=project.project_id,
        scenario_id=None,
        content_hash=assemble_consistent_for_get(
            OWNER, project.project_id, WORKBOOK.version
        ).composite_hash,
        workbook_version=WORKBOOK.version, digest="c" * 64,
        proposals=[{
            "id": 0, "source_cell": "B2", "sheet": "CSV",
            "original_value": "2", "label": "revenue.ppa.index",
            "source_unit": "%", "field_id": "revenue.ppa.index",
            "status": "ready", "reason": None,
            "mapping_method": "exact_field_id",
        }],
    )

    # Don't rely on missing CSRF to prove isolation: each request supplies
    # a VALID CSRF, and the signed review/apply tickets are genuine.
    attempts = [
        ("preview", {
            "multipart": {
                "project": CODE,
                "csrf_token": csrf,
                "encoding": "utf-8",
                "upload": {
                    "name": "synthetic.csv",
                    "mimeType": "text/csv",
                    "buffer": b"Assumption,Value,Unit\nrevenue.ppa.index,2,%\n",
                },
            },
        }),
        ("confirm", {
            "form": {
                "project": CODE, "csrf_token": csrf,
                "preview_ticket": signed_preview,
                "keep_0": "on", "field_0": "revenue.ppa.index",
                "unit_0": "%",
            },
        }),
        ("apply", {
            "form": {
                "project": CODE, "csrf_token": csrf,
                "approved_ticket": _foreign_apply_ticket(project.project_id),
            },
        }),
    ]
    for route, payload in attempts:
        response = ctx.request.post(
            url + "/v2/workbook/import/" + route,
            max_redirects=0, **payload,
        )
        assert response.status == 302, (route, response.status, response.text()[:200])
        assert response.headers.get("location") == expected_destination, route
        assert "preview_ticket" not in response.text(), route
        assert "approved_ticket" not in response.text(), route
        assert _owner_financial_evidence(project.project_id) == evidence_before, route

    assert not page.browser_errors
    assert _owner_financial_evidence(project.project_id) == evidence_before


def test_invalid_session_redirects_and_no_writes(browser, app_server):
    """No-cookie visitor is a new anonymous DEMO, not necessarily /login."""
    from app.auth import DEMO_COOKIE_NAME, decode_demo_session_token

    ctx, page = _page(browser, app_server["url"], authenticated=False)
    try:
        _assert_foreign_import_denied(
            ctx=ctx, page=page, app_server=app_server,
            expected_destination="/library",
        )
        demo_cookie = next(
            (c for c in ctx.cookies() if c["name"] == DEMO_COOKIE_NAME), None
        )
        assert demo_cookie is not None, "Missing canonical demo-session provisioning"
        session = decode_demo_session_token(demo_cookie["value"])
        assert session is not None and session.is_demo
        assert session.user_id != OWNER
        Path("artifacts/model-ai-import").mkdir(parents=True, exist_ok=True)
        page.screenshot(
            path="artifacts/model-ai-import/import-c-nonowner-denied.png",
            full_page=True,
        )
    finally:
        ctx.close()


def test_authenticated_nonowner_cannot_preview_confirm_or_apply(browser, app_server):
    """Valid signed account token is not sufficient for access to another owner."""
    from app.auth import COOKIE_NAME, create_session_token

    ctx, page = _page(browser, app_server["url"], authenticated=False)
    ctx.add_cookies([{
        "name": COOKIE_NAME,
        "value": create_session_token(
            user_id="synthetic-import-foreign-account",
            username="synthetic-import-foreign-account",
        ),
        "domain": "127.0.0.1", "path": "/",
    }])
    try:
        _assert_foreign_import_denied(
            ctx=ctx, page=page, app_server=app_server,
            expected_destination="/library",
        )
    finally:
        ctx.close()


@pytest.mark.parametrize("session_kind", ["invalid", "expired"])
def test_invalid_or_expired_cookie_denies_import(browser, app_server, session_kind):
    """Invalid/expired admin cookies cannot bypass the canonical resolver."""
    from datetime import datetime, timedelta, timezone
    from app.auth import (
        COOKIE_NAME, SESSION_MAX_AGE_HOURS, SessionData, _get_serializer,
    )

    if session_kind == "invalid":
        token = "not-a-valid-signed-admin-session"
    else:
        expired = SessionData(
            user_id=OWNER, username=OWNER,
            login_at=datetime.now(timezone.utc) - timedelta(
                hours=SESSION_MAX_AGE_HOURS + 2
            ),
            session_type="admin",
        )
        token = _get_serializer().dumps(expired.to_dict())

    ctx, page = _page(browser, app_server["url"], authenticated=False)
    ctx.add_cookies([{
        "name": COOKIE_NAME, "value": token,
        "domain": "127.0.0.1", "path": "/",
    }])
    try:
        _assert_foreign_import_denied(
            ctx=ctx, page=page, app_server=app_server,
            expected_destination="/login",
        )
    finally:
        ctx.close()


def _new_seeded_browser_project(kind: str, *, f3_active: bool):
    """Actual canonical Working Copy and (optionally) activated F3 authority."""
    from app.services.reference_seed_service import create_reference_seeded_project
    from app.persistence.workspace_repository import get_workspace_state
    from app.workbook.workbook_identity import assemble_consistent_for_get
    from app.workbook.input_set import ProjectInputSet
    from app.workbook.registry import WORKBOOK
    from app.workbook.update_service import WorkbookUpdateService
    from tests.test_model_financing_f3_workspace import state, collection_for_inputs
    from app.workbook.multisenior_config import FIELD_ID

    project = create_reference_seeded_project(
        user_id=OWNER, requested_name="Synthetic Browser " + kind,
        template_source="generic_" + kind + "_reference", capacity_mw=16,
    )
    if f3_active:
        ws = get_workspace_state(OWNER, project.project_id)
        pi = ProjectInputSet.from_snapshot(ws.draft_snapshot).to_projectinputs()
        raw = state(active=True, collection=collection_for_inputs(pi))
        WorkbookUpdateService.apply_draft_update(
            ws=ws, field_id=FIELD_ID, raw_value=raw,
            content_hash=assemble_consistent_for_get(
                OWNER, project.project_id, WORKBOOK.version
            ).composite_hash,
            workbook_version=WORKBOOK.version, project_record=project,
        )
    return project


def _run_in_real_browser_context(ctx, page, root: str, project):
    """Normal authorized HTTP Run, through Chromium's authenticated context."""
    from app.persistence.workspace_repository import get_workspace_state

    response = page.goto(root + "/v2/workbook?project=" + project.project_code)
    assert response and response.status == 200
    hash_token = page.locator('input[name="content_hash"]').first.input_value()
    version = page.locator('input[name="workbook_version"]').first.input_value()
    run_response = ctx.request.post(
        root + "/v2/workbook/run",
        headers={"HX-Request": "true"},
        form={
            "project": project.project_code,
            "content_hash": hash_token,
            "workbook_version": version,
        },
    )
    assert run_response.status == 200, run_response.text()[:1000]
    ws = get_workspace_state(OWNER, project.project_id)
    assert ws and ws.last_runtime_summary and not ws.dirty, run_response.text()[:1200]
    return ws


@pytest.mark.parametrize("kind,field,value,unit,xlsx", [
    ("solar", "project_setup.technical.p50_hours", "1840", "h", False),
    ("wind", "project_setup.technical.p50_hours", "2800", "h", True),
    ("data_center", "revenue.data_center.occupancy_y1", "62", "%", False),
    ("ev_charging", "revenue.ev_charging.charging_price", "0.38", "EUR/kWh", True),
])
def test_authenticated_four_vertical_import_run_chromium(
        browser, app_server, tmp_path, kind, field, value, unit, xlsx):
    from app.persistence.workspace_repository import get_workspace_state
    from app.persistence.run_history_repository import get_run_history
    from app.workbook.multisenior_config import SNAPSHOT_KEY

    project = _new_seeded_browser_project(
        kind, f3_active=kind in ("solar", "wind")
    )
    ctx, page = _page(
        browser, app_server["url"], width=390 if kind == "ev_charging" else 1440
    )
    try:
        initial = _run_in_real_browser_context(
            ctx, page, app_server["url"], project
        )
        initial_history = tuple(get_run_history(OWNER, project.project_id))
        previous_snapshot_id = initial.last_runtime_snapshot_id
        previous_f3 = initial.draft_snapshot.get(SNAPSHOT_KEY)

        csv_path = tmp_path / ("synthetic-" + kind + (".xlsx" if xlsx else ".csv"))
        if xlsx:
            wb = Workbook()
            ws = wb.active
            ws.title = "Assumptions"
            ws.append(["Assumption", "Value", "Unit"])
            ws.append([field, float(value), unit])
            wb.save(str(csv_path))
        else:
            csv_path.write_text(
                f"Assumption,Value,Unit\n{field},{value},{unit}\n",
                encoding="utf-8",
            )
        page.goto(app_server["url"] + "/v2/workbook/import?project=" + project.project_code)
        page.locator("#upload").set_input_files(str(csv_path))
        page.get_by_role("button", name="Extract and review").click()
        assert page.get_by_text("Review detected assumptions").count() == 1
        page.locator('input[name="keep_0"]').check()
        Path("artifacts/model-ai-import").mkdir(parents=True, exist_ok=True)
        page.screenshot(
            path=f"artifacts/model-ai-import/f3-{kind}-review.png",
            full_page=True,
        )
        page.get_by_role("button", name="Review approved change set").click()
        assert page.get_by_text("Final confirmation", exact=False).count() == 1
        page.screenshot(
            path=f"artifacts/model-ai-import/f3-{kind}-confirmation.png",
            full_page=True,
        )
        page.get_by_role("button", name="Apply 1 approved fields atomically").click()
        assert page.get_by_text("Import Apply result").count() == 1
        assert page.get_by_text("1 field changed", exact=False).count() == 1
        page.screenshot(
            path=f"artifacts/model-ai-import/f3-{kind}-applied-stale.png",
            full_page=True,
        )
        stale = get_workspace_state(OWNER, project.project_id)
        assert stale.dirty
        assert stale.last_runtime_snapshot_id == previous_snapshot_id
        assert stale.draft_snapshot.get(SNAPSHOT_KEY) == previous_f3
        assert len(get_run_history(OWNER, project.project_id)) == len(initial_history)
        current = _run_in_real_browser_context(
            ctx, page, app_server["url"], project
        )
        assert current.last_runtime_snapshot_id != previous_snapshot_id
        assert current.draft_snapshot.get(SNAPSHOT_KEY) == previous_f3
        assert len(get_run_history(OWNER, project.project_id)) == len(initial_history) + 1
        page.goto(app_server["url"] + "/v2/workbook?project=" + project.project_code)
        page.screenshot(
            path=f"artifacts/model-ai-import/f3-{kind}-post-run-current.png",
            full_page=True,
        )
        assert not page.browser_errors
    finally:
        ctx.close()


def test_active_f3_forbidden_financing_import_browser_rolls_back(
        browser, app_server, tmp_path):
    from app.persistence.workspace_repository import get_workspace_state
    from app.persistence.run_history_repository import get_run_history
    from app.workbook.workbook_identity import assemble_consistent_for_get
    from app.workbook.registry import WORKBOOK

    project = _new_seeded_browser_project("solar", f3_active=True)
    ctx, page = _page(browser, app_server["url"])
    try:
        previous = _run_in_real_browser_context(
            ctx, page, app_server["url"], project
        )
        before_hash = assemble_consistent_for_get(
            OWNER, project.project_id, WORKBOOK.version
        ).composite_hash
        history_before = tuple(get_run_history(OWNER, project.project_id))
        csv_path = tmp_path / "synthetic-forbidden-f3.csv"
        csv_path.write_text(
            "Assumption,Value,Unit\n"
            "revenue.ppa.index,2,%\n"
            "debt.senior.interest_rate_pct,6,%\n",
            encoding="utf-8",
        )
        page.goto(app_server["url"] + "/v2/workbook/import?project=" + project.project_code)
        page.locator("#upload").set_input_files(str(csv_path))
        page.get_by_role("button", name="Extract and review").click()
        page.locator('input[name="keep_0"]').check()
        page.locator('input[name="keep_1"]').check()
        page.get_by_role("button", name="Review approved change set").click()
        assert page.get_by_text("Final confirmation", exact=False).count() == 1
        page.get_by_role("button", name="Apply 2 approved fields atomically").click()
        assert page.get_by_role("alert").get_by_text(
            "F3_COMPETING_FINANCING_EDITOR_REJECTED", exact=False
        ).count() == 1
        Path("artifacts/model-ai-import").mkdir(parents=True, exist_ok=True)
        page.screenshot(
            path="artifacts/model-ai-import/f3-rejected-financing-atomic.png",
            full_page=True,
        )
        assert get_workspace_state(OWNER, project.project_id) == previous
        assert assemble_consistent_for_get(
            OWNER, project.project_id, WORKBOOK.version
        ).composite_hash == before_hash
        assert tuple(get_run_history(OWNER, project.project_id)) == history_before
        assert not page.browser_errors
    finally:
        ctx.close()
