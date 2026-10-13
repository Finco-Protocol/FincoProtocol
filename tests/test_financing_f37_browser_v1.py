"""F3.7 Sources & Uses by instrument in a REAL Chromium (live server, synthetic projects)."""
from __future__ import annotations

import os
import socket
import threading
import time

import pytest

pytest.importorskip("playwright", reason="playwright not installed in this workflow")
from playwright.sync_api import expect, sync_playwright  # noqa: E402

PORT = 8798
USER = "decision-user"          # the shared F2/F3 save/run helpers are bound to this synthetic user
VERTICALS = ["generic_solar_reference", "generic_wind_reference",
             "generic_data_center_reference", "generic_ev_charging_reference"]
SHOTS = os.environ.get("F37_SCREENSHOT_DIR")


@pytest.fixture(scope="module")
def live_server(tmp_path_factory):
    import uvicorn
    from app.persistence import db

    mp = pytest.MonkeyPatch()
    mp.setattr(db, "DB_PATH", str(tmp_path_factory.mktemp("f37") / "f37.db"))
    db.init_db()
    import main_web
    from app.v2.financing_sources_uses_router import router
    if not any(getattr(r, "path", "") == "/v2/financing/sources-uses" for r in main_web.app.routes):
        main_web.app.include_router(router, prefix="/v2")
    server = uvicorn.Server(uvicorn.Config(main_web.app, host="127.0.0.1", port=PORT, log_level="warning"))
    thread = threading.Thread(target=server.run, daemon=True)
    thread.start()
    for _ in range(180):
        try:
            socket.create_connection(("127.0.0.1", PORT), timeout=1).close()
            break
        except OSError:
            time.sleep(1)
    yield f"http://127.0.0.1:{PORT}"
    server.should_exit = True
    thread.join(timeout=10)
    from app.runtime import model_execution as me
    me.reset_model_executor_for_tests(None)
    mp.undo()


@pytest.fixture(scope="module")
def browser():
    with sync_playwright() as pw:
        options = {"args": ["--no-sandbox"]}
        if os.environ.get("FINCO_TEST_CHROMIUM_PATH"):
            options["executable_path"] = os.environ["FINCO_TEST_CHROMIUM_PATH"]
        try:
            instance = pw.chromium.launch(**options)
        except Exception as exc:
            pytest.skip(f"chromium unavailable: {exc}")
        yield instance
        instance.close()


def _project(template, *, two_senior):
    """Create a synthetic project, optionally commit a real two-Senior Run through the real HTTP path."""
    from types import SimpleNamespace
    from fastapi.testclient import TestClient
    from app.auth import COOKIE_NAME, create_session_token
    from app.persistence.workspace_repository import get_workspace_state
    from app.services.reference_seed_service import create_reference_seeded_project
    from app.workbook import multisenior_config as config
    from app.workbook.input_set import ProjectInputSet
    from main_web import app
    from tests.test_model_financing_f2 import run, save
    from tests.test_model_financing_f3_workspace import collection_for_inputs, state

    record = create_reference_seeded_project(user_id=USER, template_source=template, requested_name="F37", capacity_mw=16)
    with TestClient(app) as client:
        client.cookies.set(COOKIE_NAME, create_session_token(user_id=USER, username="admin"))
        env = SimpleNamespace(client=client)
        client.get("/v2/workbook", params={"project": record.project_code})
        mp = pytest.MonkeyPatch()
        try:
            if two_senior:
                mp.setattr(config, "ACTIVATION_ENABLED", True)
                ws = get_workspace_state(USER, record.project_id)
                pi = ProjectInputSet.from_snapshot(ws.draft_snapshot).to_projectinputs()
                assert "field-error-banner" not in save(env, record, state(active=True, collection=collection_for_inputs(pi)),
                                                        field=config.FIELD_ID).text
            run(env, record)
        finally:
            mp.undo()
    return record


def _open(live_server, browser, record, viewport, scheme="light"):
    from app.auth import COOKIE_NAME, create_session_token
    ctx = browser.new_context(viewport=viewport, color_scheme=scheme)
    ctx.add_cookies([{"name": COOKIE_NAME, "value": create_session_token(user_id=USER, username="admin"), "url": live_server}])
    page = ctx.new_page()
    errors = []
    page.on("pageerror", lambda e: errors.append(str(e)))
    page.goto(f"{live_server}/v2/financing/sources-uses?project={record.project_code}")
    page.wait_for_selector("[data-testid=su-instruments]")
    return ctx, page, errors


def _shot(page, name):
    if SHOTS:
        os.makedirs(SHOTS, exist_ok=True)
        page.screenshot(path=os.path.join(SHOTS, name), full_page=True)


@pytest.mark.parametrize("template", VERTICALS[:2])
def test_two_senior_instrument_table_expand_link_and_layouts(live_server, browser, template):
    record = _project(template, two_senior=True)
    ctx, page, errors = _open(live_server, browser, record, {"width": 1440, "height": 1000})
    expect(page.locator("[data-testid=su-instrument-row]")).to_have_count(2)
    expect(page.locator("[data-testid=su-instrument-status]")).to_contain_text("RECONCILED")
    assert all(s == "RECONCILED" for s in page.locator("[data-testid=su-recon-table] tbody tr").evaluate_all(
        "rows => rows.map(r => r.dataset.status)"))
    detail = page.locator("[data-testid=su-instrument-row] details").first
    assert not detail.evaluate("d => d.open")
    detail.locator("summary").click()
    assert detail.evaluate("d => d.open") and detail.locator("tbody tr").count() >= 1
    link = page.locator("[data-testid=su-capital-stack-link]")
    assert "sheet=debt" in link.get_attribute("href")
    _shot(page, f"{template}-01-desktop.png")
    ctx.close()
    for scheme, width in (("dark", 1440), ("light", 390), ("dark", 390)):
        ctx, page, errors = _open(live_server, browser, record, {"width": width, "height": 900}, scheme)
        assert page.evaluate("document.documentElement.scrollWidth - document.documentElement.clientWidth") <= 1
        _shot(page, f"{template}-02-{scheme}-{width}.png")
        assert not errors
        ctx.close()


@pytest.mark.parametrize("template", VERTICALS)
def test_single_senior_run_shows_unavailable_instrument_split(live_server, browser, template):
    record = _project(template, two_senior=False)
    ctx, page, errors = _open(live_server, browser, record, {"width": 1440, "height": 900})
    expect(page.locator("[data-testid=su-instruments-unavailable]")).to_contain_text("not proof of funding drawn")
    assert page.locator("[data-testid=su-instrument-row]").count() == 0
    _shot(page, f"{template}-03-aggregate-only.png")
    assert not errors
    ctx.close()
