"""Q4 authenticated desktop/mobile end-to-end acceptance on a real uvicorn server.

Real Q1/Q3 evidence, real Chromium, real canonical engine runs and durable SQLite;
no mocked finance output, artificial comparison or external customer files.
"""
from __future__ import annotations

import re
import socket
import threading
import time
from pathlib import Path

import pytest

pytest.importorskip("playwright")
pytest.importorskip("uvicorn")

from playwright.sync_api import sync_playwright

OWNER = "q4-browser-synthetic-owner"


def _port():
    with socket.socket() as sock:
        sock.bind(("127.0.0.1", 0))
        return sock.getsockname()[1]


@pytest.fixture(scope="module")
def app_server(tmp_path_factory):
    from app.persistence import db
    from app.persistence.db import init_db

    db.DB_PATH = str(tmp_path_factory.mktemp("q4-browser") / "q4-browser.db")
    init_db()
    import main_web
    import uvicorn

    port = _port()
    server = uvicorn.Server(uvicorn.Config(
        main_web.app, host="127.0.0.1", port=port,
        log_level="error", lifespan="off",
    ))
    thread = threading.Thread(target=server.run, daemon=True)
    thread.start()
    deadline = time.monotonic() + 30
    while not server.started and time.monotonic() < deadline:
        time.sleep(0.05)
    assert server.started
    try:
        yield f"http://127.0.0.1:{port}"
    finally:
        server.should_exit = True
        thread.join(timeout=10)


@pytest.fixture(scope="module")
def browser():
    with sync_playwright() as pw:
        b = pw.chromium.launch(args=["--no-sandbox"])
        yield b
        b.close()


def _page(browser, width=1440):
    from app.auth import COOKIE_NAME, create_session_token
    ctx = browser.new_context(viewport={"width": width, "height": 900})
    ctx.add_cookies([{
        "name": COOKIE_NAME,
        "value": create_session_token(user_id=OWNER, username=OWNER),
        "domain": "127.0.0.1", "path": "/",
    }])
    page = ctx.new_page()
    page.browser_errors = []
    page.on("pageerror", lambda e: page.browser_errors.append(str(e)))
    return ctx, page


def _run(ctx, page, root, code):
    response = page.goto(f"{root}/v2/workbook?project={code}")
    assert response and response.status == 200
    h = page.locator('input[name="content_hash"]').first.input_value()
    v = page.locator('input[name="workbook_version"]').first.input_value()
    run = ctx.request.post(
        f"{root}/v2/workbook/run",
        headers={"HX-Request": "true"},
        form={"project": code, "content_hash": h, "workbook_version": v},
    )
    assert run.status == 200
    from app.persistence.workspace_repository import get_workspace_state
    ws = get_workspace_state(OWNER, _run.project_id)
    assert ws is not None and ws.last_runtime_summary and not ws.dirty, run.text()[:900]
    return ws


@pytest.mark.parametrize("kind,width", [("solar", 1440), ("wind", 390)])
def test_q4_finding_preview_confirm_select_run_compare(browser, app_server, kind, width):
    from app.services.reference_seed_service import create_reference_seeded_project
    from app.persistence.workspace_repository import get_workspace_state
    from app.persistence.scenarios_repository import list_scenarios, get_scenario
    from app.persistence.run_history_repository import get_run_history

    project = create_reference_seeded_project(
        user_id=OWNER,
        requested_name="Q4 Browser " + kind + " " + str(width),
        template_source="generic_" + kind + "_reference",
        capacity_mw=40,
    )
    _run.project_id = project.project_id
    ctx, page = _page(browser, width)
    root = app_server
    code = project.project_code
    artifact = Path("artifacts/model-q4-browser")
    artifact.mkdir(parents=True, exist_ok=True)

    try:
        # Wind template may not persist gearing. Set a source-proven value via
        # canonical Save, not by relying on an engine fallback/default.
        from app.persistence.workspace_repository import get_workspace_state
        if not get_workspace_state(OWNER, project.project_id).draft_snapshot.get("gearing_pct"):
            page.goto(f"{root}/v2/workbook?project={code}")
            h = page.locator('input[name="content_hash"]').first.input_value()
            v = page.locator('input[name="workbook_version"]').first.input_value()
            saved = ctx.request.post(f"{root}/v2/workbook/update",
                headers={"HX-Request": "true"},
                form={"project": code, "field_id": "debt.senior.gearing_pct",
                      "value": "65", "sheet_id": "debt",
                      "content_hash": h, "workbook_version": v})
            assert saved.status == 200
            assert float(get_workspace_state(OWNER, project.project_id).draft_snapshot["gearing_pct"]) == 65
        base_ws = _run(ctx, page, root, code)
        before_history = tuple(get_run_history(OWNER, project.project_id))
        assert before_history and base_ws.last_runtime_snapshot_id
        original = float(base_ws.draft_snapshot["gearing_pct"])
        # A materially different user-entered assumption: no solver prediction.
        proposed = 10 if original != 10 else 15

        page.goto(f"{root}/v2/workbook?project={code}")
        finding = page.locator('details[data-check-id="QM-SD-006"]')
        assert finding.count() == 1, "Q1/Q3 finding must be visible on real Workbook"
        finding.evaluate(
            "(el) => { for(let n=el;n;n=n.parentElement) if(n.tagName==='DETAILS') n.open=true; }"
        )
        form = finding.locator('[data-testid="q4-create-form"]')
        assert form.count() == 1, "Q4 eligible finding must expose actual editable form"
        form.locator('[name="scenario_name"]').fill("Q4 Browser " + kind)
        form.locator('[name="proposed_value"]').fill(str(proposed))
        form.get_by_role("button", name="Preview What-if").click()
        preview = page.locator('[data-testid="q4-preview"]')
        preview.wait_for(state="visible", timeout=20000)
        assert str(original) in preview.inner_text()
        assert str(float(proposed)) in preview.inner_text()
        assert "NOT A RUN" in preview.inner_text()
        assert len(get_run_history(OWNER, project.project_id)) == len(before_history)
        page.screenshot(path=str(artifact / f"q4-{kind}-review-{width}.png"), full_page=True)
        if width == 390:
            assert page.evaluate("document.documentElement.scrollWidth - innerWidth") <= 1

        preview.locator('input[name="confirmed"]').check()
        preview.get_by_role("button", name="Confirm and create What-if").click()
        result = page.locator('[data-testid="q4-created"]')
        result.wait_for(state="visible", timeout=20000)
        assert "NOT_RUN" in result.inner_text()
        page.screenshot(path=str(artifact / f"q4-{kind}-confirmed-{width}.png"), full_page=True)
        scenarios = list_scenarios(OWNER, project.project_id)
        child = next(x for x in scenarios if x.scenario_name == "Q4 Browser " + kind)
        base = next(x for x in scenarios if x.is_base_case)
        assert child.overrides == {"gearing_pct": proposed}
        assert len(get_run_history(OWNER, project.project_id)) == len(before_history)

        no_run = page.goto(
            f"{root}/v2/workbook/whatif/compare?project={code}&scenario_id={child.scenario_id}"
        )
        assert no_run.status == 200 and "NOT_RUN" in page.inner_text("body")

        selection = ctx.request.post(
            f"{root}/v2/workbook/scenarios/select",
            headers={"HX-Request": "true"},
            form={"project": code, "scenario_id": child.scenario_id},
        )
        assert selection.status == 200
        assert get_workspace_state(OWNER, project.project_id).active_scenario_id == child.scenario_id
        after = _run(ctx, page, root, code)
        assert after.last_runtime_snapshot_id != base_ws.last_runtime_snapshot_id
        assert len(get_run_history(OWNER, project.project_id)) == len(before_history) + 1

        compare = page.goto(
            f"{root}/v2/workbook/whatif/compare?project={code}&scenario_id={child.scenario_id}"
        )
        assert compare.status == 200
        assert page.locator('[data-testid="q4-committed-compare"]').count() == 1
        assert "Canonical Run Integrity" in page.inner_text("body")
        page.screenshot(path=str(artifact / f"q4-{kind}-compared-{width}.png"), full_page=True)
        assert not page.browser_errors

        return_base = ctx.request.post(
            f"{root}/v2/workbook/scenarios/select",
            headers={"HX-Request": "true"},
            form={"project": code, "scenario_id": base.scenario_id},
        )
        assert return_base.status == 200
        returned = get_workspace_state(OWNER, project.project_id)
        assert returned.active_scenario_id == base.scenario_id
        assert float(base.base_input_set["gearing_pct"]) == original
        assert before_history[0].history_id in {
            e.history_id for e in get_run_history(OWNER, project.project_id)
        }
        assert not page.browser_errors
    finally:
        ctx.close()
