"""Stream A (UX-004): a Goal Seek result must never be wiped by the lazy panel GET.

Real Chromium against a live uvicorn server. The lazy ``GET /decision/goal-seek`` is HELD by a route handler so the order of
responses is deterministic; the solve (POST) is fulfilled with a result fragment so no engine run is needed.
"""
from __future__ import annotations

import os
import socket
import threading
import time

import pytest

pytest.importorskip("playwright", reason="playwright not installed in this workflow")
from playwright.sync_api import sync_playwright  # noqa: E402

PORT = 8799
RESULT = '<div id="v2-goal-seek-result" data-testid="gs-result">Required tariff 61.20 EUR/MWh</div>'


@pytest.fixture(scope="module")
def live_server(tmp_path_factory):
    import uvicorn
    from app.persistence import db

    mp = pytest.MonkeyPatch()
    mp.setattr(db, "DB_PATH", str(tmp_path_factory.mktemp("uxa-gs") / "g.db"))
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


def _open(live_server, browser, uid):
    from app.auth import COOKIE_NAME, create_session_token
    from app.services.reference_seed_service import create_reference_seeded_project

    rec = create_reference_seeded_project(user_id=uid, template_source="generic_solar_reference", requested_name="GS", capacity_mw=40.0)
    ctx = browser.new_context(viewport={"width": 1440, "height": 900}, bypass_csp=True)
    ctx.add_cookies([{"name": COOKIE_NAME, "value": create_session_token(user_id=uid, username="admin"), "url": live_server}])
    page = ctx.new_page()
    page.goto(f"{live_server}/v2/workbook?project={rec.project_code}")
    page.wait_for_selector("#tab-goal-seek", state="attached")
    return ctx, page


def test_a_delayed_lazy_get_cannot_wipe_a_result_that_was_requested_after_it(live_server, browser):
    ctx, page = _open(live_server, browser, "uxa-gs-1")
    held = {}
    page.route("**/decision/goal-seek*", lambda route: held.setdefault("route", route))      # hold the lazy GET
    page.route("**/goal-seek/run", lambda route: route.fulfill(status=200, content_type="text/html", body=RESULT))
    page.evaluate("document.getElementById('tab-goal-seek').click()")
    for _ in range(50):
        if "route" in held:
            break
        time.sleep(0.1)
    assert "route" in held, "the lazy GET was not issued"
    page.fill("#gs-target-value", "9.5")
    page.click("[data-testid=gs-run-btn]")
    page.wait_for_selector("[data-testid=gs-result]", state="attached")
    held["route"].continue_()                                                                  # the late GET answers now (or was aborted)
    time.sleep(1.0)
    assert page.locator("[data-testid=gs-result]").count() == 1, "UX-004: the Goal Seek result disappeared"
    ctx.close()


def test_reopening_the_tab_keeps_an_existing_result(live_server, browser):
    ctx, page = _open(live_server, browser, "uxa-gs-2")
    page.route("**/goal-seek/run", lambda route: route.fulfill(status=200, content_type="text/html", body=RESULT))
    page.evaluate("document.getElementById('tab-goal-seek').click()")
    page.wait_for_selector("#gs-target-value", state="attached")
    time.sleep(0.5)
    page.fill("#gs-target-value", "9.5")
    page.click("[data-testid=gs-run-btn]")
    page.wait_for_selector("[data-testid=gs-result]", state="attached")
    page.evaluate("document.getElementById('tab-goal-seek').click()")
    time.sleep(1.0)
    assert page.locator("[data-testid=gs-result]").count() == 1
    ctx.close()
