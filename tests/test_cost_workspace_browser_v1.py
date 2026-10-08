"""Cost Workspace V1 — real-browser proof of the Deactivate / Reactivate HTMX forms.

Drives the actual rendered page (live server, real Chromium): click x, see the
line move to "Inactive lines", click Reactivate, see it return; persisted and
visible after a reload. Skipped when Playwright / Chromium are unavailable.
"""
from __future__ import annotations

import os
import re
import socket
import threading
import time

import pytest

pytest.importorskip("playwright", reason="playwright not installed in this workflow")
from playwright.sync_api import sync_playwright  # noqa: E402

PORT = 8793


@pytest.fixture(scope="module")
def live_server(tmp_path_factory):
    import uvicorn
    from app.persistence import db

    mp = pytest.MonkeyPatch()
    mp.setattr(db, "DB_PATH", str(tmp_path_factory.mktemp("cw-browser") / "b.db"))
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
        except Exception as exc:  # browser binary unavailable in this environment
            pytest.skip(f"chromium unavailable: {exc}")
        yield instance
        instance.close()


def _active(project_id, table, sub_line_id):
    from app.persistence.db import get_cursor

    with get_cursor() as cur:
        cur.execute(f"SELECT is_active FROM {table} WHERE sub_line_id=?", (sub_line_id,))
        return cur.fetchone()["is_active"]


@pytest.mark.parametrize("template", ["generic_solar_reference", "generic_data_center_reference"])
@pytest.mark.parametrize("kind,table,tab", [("capex", "capex_sub_lines", "capex"),
                                              ("opex", "opex_sub_lines", "opex")])
def test_deactivate_then_reactivate_in_a_real_browser(live_server, browser, template, kind, table, tab):
    from app.auth import COOKIE_NAME, create_session_token
    from app.services.reference_seed_service import create_reference_seeded_project

    uid = f"u-cwb-{kind}-{template[8:12]}"
    rec = create_reference_seeded_project(user_id=uid, template_source=template,
                                          requested_name="Browser CW", capacity_mw=40.0)
    ctx = browser.new_context(viewport={"width": 1440, "height": 900})
    ctx.add_cookies([{"name": COOKIE_NAME, "value": create_session_token(user_id=uid, username="admin"),
                      "url": live_server}])
    page = ctx.new_page()
    page.on("dialog", lambda d: d.accept())          # OPEX x asks for a native confirmation
    posts = []
    page.on("response", lambda r: posts.append((r.url.split(str(PORT))[-1], r.status))
            if r.request.method == "POST" and "/line/" in r.url else None)

    def open_sheet():
        page.goto(f"{live_server}/v2/workbook?project={rec.project_code}")
        page.wait_for_selector(f"#tab-{tab}")
        page.evaluate(f"document.getElementById('tab-{tab}').click()")
        page.wait_for_timeout(400)

    open_sheet()
    deact = page.locator(f'#panel-{tab} button[aria-label^="Deactivate"]').first
    sid = deact.evaluate("e => e.closest('[data-sub-line-id]')?.getAttribute('data-sub-line-id') || "
                         "e.closest('form').querySelector('[name=sub_line_id]').value")
    deact.evaluate("e=>{let d=e.closest('details'); while(d){d.open=true; d=d.parentElement.closest('details');}}")
    deact.click()
    page.wait_for_timeout(1200)
    assert posts[-1][0].endswith("/line/deactivate") and posts[-1][1] == 200
    assert _active(rec.project_id, table, sid) == 0

    # reload: the line is listed as inactive with a working Reactivate control
    open_sheet()
    btn = page.locator(f'[data-testid="{kind}-reactivate-{sid}"]')
    assert btn.count() == 1
    btn.evaluate("e=>{let d=e.closest('details'); while(d){d.open=true; d=d.parentElement.closest('details');}}")
    btn.click()
    page.wait_for_timeout(1200)
    assert posts[-1][0].endswith("/line/reactivate") and posts[-1][1] == 200
    assert _active(rec.project_id, table, sid) == 1

    open_sheet()                                     # persisted across reload
    assert page.locator(f'[data-testid="{kind}-reactivate-{sid}"]').count() == 0
    ctx.close()
