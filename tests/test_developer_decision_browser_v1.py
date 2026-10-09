"""Workflow E — real-Chromium acceptance for the Developer & Decision workspace and Compare additions."""
from __future__ import annotations

import os
import socket
import threading
import time

import pytest

pytest.importorskip("playwright", reason="playwright not installed in this workflow")
from playwright.sync_api import sync_playwright  # noqa: E402

PORT = 8797


@pytest.fixture(scope="module")
def live_server(tmp_path_factory):
    import uvicorn
    from app.persistence import db

    mp = pytest.MonkeyPatch()
    mp.setattr(db, "DB_PATH", str(tmp_path_factory.mktemp("wde-browser") / "c.db"))
    db.init_db()
    import main_web

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
        exe = os.environ.get("FINCO_TEST_CHROMIUM_PATH")
        if exe:
            options["executable_path"] = exe
        try:
            instance = pw.chromium.launch(**options)
        except Exception as exc:
            pytest.skip(f"chromium unavailable: {exc}")
        yield instance
        instance.close()



def _ctx(live_server, browser, uid, name, viewport=None, scheme="light"):
    from app.auth import COOKIE_NAME, create_session_token
    from app.services.reference_seed_service import create_reference_seeded_project

    rec = create_reference_seeded_project(user_id=uid, template_source="generic_solar_reference",
                                          requested_name=name, capacity_mw=40.0)
    ctx = browser.new_context(viewport=viewport or {"width": 1440, "height": 1000},
                              color_scheme=scheme, bypass_csp=True)
    ctx.add_cookies([{"name": COOKIE_NAME, "value": create_session_token(user_id=uid, username="admin"),
                      "url": live_server}])
    return rec, ctx


def test_developer_workspace_and_compare_acceptance(live_server, browser):
    rec, ctx = _ctx(live_server, browser, "wde-u1", "WDE Solar")
    page = ctx.new_page()
    errors = []
    page.on("pageerror", lambda e: errors.append(str(e)))
    page.goto(f"{live_server}/v2/developer-decision?project={rec.project_code}")
    page.wait_for_selector('[data-testid="dd-page"]')
    assert page.locator('[data-testid="dd-dev-state"]').inner_text().endswith("DISABLED")
    assert page.locator('[data-testid="dd-bridge-gap"]').is_visible()
    assert page.locator('[data-testid="dd-expected_npv"]').get_attribute("data-available") == "false"
    assert page.locator('[data-testid="dd-stage"]').inner_text() == "Stage: Not set"
    page.locator('[data-testid="dd-expected-npv-conditions"] summary').click()
    assert page.locator('[data-testid="dd-expected-npv-conditions"] tr').count() == 8
    page.goto(f"{live_server}/v2/compare-projects?projects={rec.project_code}")
    assert page.locator(f'[data-testid="ds-freshness-{rec.project_code}"]').inner_text().strip() == "NOT RUN"
    # narrow viewport: no horizontal page scroll
    page.set_viewport_size({"width": 390, "height": 800})
    page.goto(f"{live_server}/v2/developer-decision?project={rec.project_code}")
    page.wait_for_selector('[data-testid="dd-page"]')
    assert page.evaluate("document.documentElement.scrollWidth <= window.innerWidth + 1")
    assert not errors
    ctx.close()
