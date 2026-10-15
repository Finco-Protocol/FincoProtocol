"""RC-UX Phase 2 (Workstream B): guided "Add a PPA" in real Chromium under the real CSP.

An ordinary PPA is added without typing a contract ID; the contract reference is still required (never invented); the existing
Save path persists the typed stream; Run stays a separate, explicit action.
"""
from __future__ import annotations

import json
import os
import socket
import threading
import time

import pytest

pytest.importorskip("playwright", reason="playwright not installed in this workflow")
from playwright.sync_api import sync_playwright  # noqa: E402

PORT = 8801


@pytest.fixture(scope="module")
def live_server(tmp_path_factory):
    import uvicorn
    from app.persistence import db

    mp = pytest.MonkeyPatch()
    mp.setattr(db, "DB_PATH", str(tmp_path_factory.mktemp("rcux2-ppa") / "g.db"))
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


class Session:
    def __init__(self, live_server, browser, uid, viewport=None, scheme="light"):
        from app.auth import COOKIE_NAME, create_session_token
        from app.services.reference_seed_service import create_reference_seeded_project

        self.uid = uid
        self.rec = create_reference_seeded_project(user_id=uid, template_source="generic_solar_reference", requested_name="PPA", capacity_mw=40.0)
        self.ctx = browser.new_context(viewport=viewport or {"width": 1440, "height": 900}, color_scheme=scheme)   # real CSP: no bypass
        self.ctx.add_cookies([{"name": COOKIE_NAME, "value": create_session_token(user_id=uid, username="admin"), "url": live_server}])
        self.page = self.ctx.new_page()
        self.errors = []
        self.page.on("pageerror", lambda e: self.errors.append(str(e)))
        self.page.on("console", lambda m: self.errors.append(m.text) if m.type == "error"
                     and not str((m.location or {}).get("url", "")).endswith("/favicon.ico") else None)
        self.page.goto(f"{live_server}/v2/workbook?project={self.rec.project_code}&sheet=revenue")
        self.page.wait_for_selector("[data-testid=ppa-quick-add]", state="attached")

    def quick(self, name):
        return self.page.locator(f'[data-testid=ppa-quick-add] [data-quick="{name}"]')

    def fill(self, **values):
        for key, value in values.items():
            el = self.quick(key)
            if key == "kind":
                el.select_option(value)
            else:
                el.fill(value)

    def add(self):
        self.page.locator("[data-quick-add]").click()

    def saved_book(self):
        from app.persistence.workspace_repository import get_workspace_state
        from app.workbook.revenue_multistream import FIELD_ID
        from app.workbook.input_set import ProjectInputSet
        ws = get_workspace_state(self.uid, self.rec.project_id)
        raw = ProjectInputSet.from_snapshot(ws.draft_snapshot).get(FIELD_ID) or ""
        return json.loads(raw) if raw else None

    def close(self):
        self.ctx.close()


def _open_editor(s):
    s.page.evaluate("document.getElementById('tab-revenue').click()")
    s.page.locator("[data-testid=ppa-quick-add]").scroll_into_view_if_needed()


def test_a_fixed_ppa_is_added_with_a_generated_id_saved_and_not_run(live_server, browser):
    s = Session(live_server, browser, "rcux2-ppa-1")
    _open_editor(s)
    assert s.quick("start").input_value() and s.quick("end").input_value()          # derived from the project's own operating periods
    s.fill(price="62.5", share="80", ref="PPA-2031-A")
    s.add()
    assert s.page.locator("[data-quick-error]").is_hidden()
    s.page.locator("[data-revenue-save]").click()
    s.page.locator("[data-revenue-feedback]").filter(has_text="Saved").wait_for()
    book = s.saved_book()
    stream = book["streams"][0]
    assert stream["id"] == "ppa-1" and stream["type"] == "ppa" and stream["price_eur_mwh"] == 62.5
    assert stream["volume_share"] == 0.8 and stream["source_ref"] == "PPA-2031-A" and stream["indexation_rate"] == 0
    assert s.errors == [], s.errors
    s.close()


def test_two_ppas_get_distinct_generated_ids_and_an_indexed_one_keeps_its_indexation(live_server, browser):
    s = Session(live_server, browser, "rcux2-ppa-2")
    _open_editor(s)
    s.fill(price="60", share="50", ref="REF-A"); s.add()
    s.fill(kind="indexed_ppa", price="70", share="30", index="2.5", ref="REF-B"); s.add()
    s.page.locator("[data-revenue-save]").click()
    s.page.locator("[data-revenue-feedback]").filter(has_text="Saved").wait_for()
    streams = s.saved_book()["streams"]
    assert [r["id"] for r in streams] == ["ppa-1", "ppa-2"]
    assert streams[1]["indexation_rate"] == 0.025 and streams[1]["volume_share"] == 0.3
    assert s.errors == [], s.errors
    s.close()


@pytest.mark.parametrize("values,message", [
    ({"price": "62,5", "share": "80", "ref": "R"}, "starting price"),
    ({"price": "62.5", "share": "0", "ref": "R"}, "above 0%"),
    ({"price": "62.5", "share": "101", "ref": "R"}, "at most 100%"),
    ({"price": "62.5", "share": "80", "ref": ""}, "contract reference"),
    ({"price": "62.5", "share": "80", "ref": "R", "end": "2000-01-01"}, "later end date"),
])
def test_invalid_input_is_refused_with_an_actionable_message_and_nothing_is_added(live_server, browser, values, message):
    s = Session(live_server, browser, "rcux2-ppa-3")
    _open_editor(s)
    s.fill(**values)
    s.add()
    assert message in s.page.inner_text("[data-quick-error]")
    assert s.page.locator("[data-revenue-rows] tr").count() == 0
    assert s.saved_book() is None
    s.close()


def test_the_quick_add_form_fits_a_phone_without_document_overflow_in_dark_mode(live_server, browser):
    s = Session(live_server, browser, "rcux2-ppa-4", viewport={"width": 390, "height": 800}, scheme="dark")
    _open_editor(s)
    assert s.page.evaluate("document.documentElement.scrollWidth <= window.innerWidth + 1")
    s.close()
