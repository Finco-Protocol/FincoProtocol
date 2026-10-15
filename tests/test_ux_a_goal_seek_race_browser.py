"""Stream A (UX-004): a Goal Seek result must never be wiped by the lazy panel GET.

Real Chromium against a live uvicorn server under the application's REAL Content-Security-Policy (no bypass). The lazy ``GET /decision/goal-seek`` is HELD by a route handler so the order of
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
RESULT2 = '<div id="v2-goal-seek-result" data-testid="gs-result">Required tariff 63.80 EUR/MWh</div>'
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


class _Page:
    """A page under the real CSP that records every page error and console error."""

    def __init__(self, live_server, browser, uid):
        from app.auth import COOKIE_NAME, create_session_token
        from app.services.reference_seed_service import create_reference_seeded_project

        self.uid = uid
        self.rec = create_reference_seeded_project(
            user_id=uid, template_source="generic_solar_reference", requested_name="GS", capacity_mw=40.0)
        self.ctx = browser.new_context(viewport={"width": 1440, "height": 900})          # NO bypass_csp: the real policy applies
        self.ctx.add_cookies([{"name": COOKIE_NAME, "value": create_session_token(user_id=uid, username="admin"), "url": live_server}])
        self.page = self.ctx.new_page()
        self.errors = []
        self.run_posts = 0
        self.page.on("pageerror", lambda e: self.errors.append(str(e)))
        # Chromium's implicit /favicon.ico probe is browser chrome, not an application request (same rule as the consolidation suite).
        self.page.on("console", lambda m: self.errors.append(m.text) if m.type == "error"
                     and not str((m.location or {}).get("url", "")).endswith("/favicon.ico") else None)
        self.page.on("request", self._count)
        self.page.goto(f"{live_server}/v2/workbook?project={self.rec.project_code}")
        self.page.wait_for_selector("#tab-goal-seek", state="attached")

    def _count(self, request):
        if request.method == "POST" and request.url.endswith("/goal-seek/run"):
            self.run_posts += 1

    def open_tab(self):
        self.page.evaluate("document.getElementById('tab-goal-seek').click()")

    def open_and_load(self):
        """Open the tab and wait for the lazy GET to be swapped in, so the form the test types into is the final one."""
        with self.page.expect_response(lambda r: "/decision/goal-seek" in r.url):
            self.open_tab()
        self.page.wait_for_selector(".htmx-request", state="detached")      # a locator wait: string predicates would need unsafe-eval

    def solve(self, target="9.5"):
        self.page.wait_for_selector("#gs-target-value", state="attached")
        self.page.fill("#gs-target-value", target)
        self.page.click("[data-testid=gs-run-btn]")

    def assert_clean(self):
        relevant = [e for e in self.errors if "EvalError" in e or "unsafe-eval" in e or "Content Security Policy" in e or "htmx" in e.lower()]
        assert relevant == [], relevant
        assert self.errors == [], self.errors

    def close(self):
        self.ctx.close()


def _fulfil(page, body, status=200, delay=0.0):
    def handler(route):
        if delay:
            time.sleep(delay)
        route.fulfill(status=status, content_type="text/html", body=body)
    page.route("**/goal-seek/run", handler)


def test_the_workbook_and_the_first_opening_of_goal_seek_raise_no_csp_or_htmx_error(live_server, browser):
    s = _Page(live_server, browser, "uxa-gs-0")
    s.page.wait_for_selector("#v2-workbook-shell", state="attached")
    s.open_tab()
    s.page.wait_for_selector("#gs-target-value", state="attached")
    s.assert_clean()
    s.close()


def test_a_delayed_lazy_get_cannot_wipe_a_result_that_was_requested_after_it(live_server, browser):
    s = _Page(live_server, browser, "uxa-gs-1")
    held = {}
    s.page.route("**/decision/goal-seek*", lambda route: held.setdefault("route", route))      # hold the lazy GET
    _fulfil(s.page, RESULT)
    s.open_tab()
    for _ in range(50):
        if "route" in held:
            break
        time.sleep(0.1)
    assert "route" in held, "the lazy GET was not issued"
    s.page.fill("#gs-target-value", "9.5")
    s.page.click("[data-testid=gs-run-btn]")
    s.page.wait_for_selector("[data-testid=gs-result]", state="attached")
    try:
        held["route"].continue_()                                                                  # the late GET answers now (or was aborted)
    except Exception:
        pass
    time.sleep(1.0)
    assert s.page.locator("[data-testid=gs-result]").count() == 1, "UX-004: the Goal Seek result disappeared"
    s.assert_clean()
    s.close()


def test_reopening_the_tab_keeps_an_existing_result_and_a_second_solve_replaces_it(live_server, browser):
    s = _Page(live_server, browser, "uxa-gs-2")
    _fulfil(s.page, RESULT)
    s.open_and_load()
    s.solve()
    s.page.wait_for_selector("[data-testid=gs-result]", state="attached")
    s.open_tab()
    time.sleep(1.0)
    assert s.page.locator("[data-testid=gs-result]").count() == 1 and "61.20" in s.page.inner_text("#v2-goal-seek-results")
    s.page.unroute("**/goal-seek/run")
    _fulfil(s.page, RESULT2)
    s.solve("10.5")
    s.page.locator("#v2-goal-seek-results").filter(has_text="63.80").wait_for()
    assert s.run_posts == 2
    s.assert_clean()
    s.close()


def test_repeated_clicks_do_not_run_the_solve_twice(live_server, browser):
    s = _Page(live_server, browser, "uxa-gs-3")
    _fulfil(s.page, RESULT, delay=0.8)
    s.open_and_load()
    s.page.wait_for_selector("#gs-target-value", state="attached")
    s.page.fill("#gs-target-value", "9.5")
    s.page.dblclick("[data-testid=gs-run-btn]")
    s.page.wait_for_selector("[data-testid=gs-result]", state="attached", timeout=15000)
    for _ in range(3):
        s.open_tab()
    time.sleep(1.0)
    assert s.run_posts == 1, s.run_posts
    s.assert_clean()
    s.close()


def test_a_failed_solve_is_visible(live_server, browser):
    s = _Page(live_server, browser, "uxa-gs-4")
    _fulfil(s.page, "<p>Workspace not found.</p>", status=500)
    s.open_and_load()
    s.solve()
    s.page.wait_for_selector("[data-testid=gs-error]", state="attached")
    assert "could not be completed" in s.page.inner_text("[data-testid=gs-error]")
    s.close()                                                              # the 500 itself is a logged network error by design


def test_a_scenario_change_clears_a_result_that_belonged_to_the_previous_scenario(live_server, browser):
    from app.persistence.scenarios_repository import add_scenario, get_or_create_base_case_scenario
    from app.persistence.workspace_repository import get_workspace_state
    from app.workbook.service import WorkbookService
    s = _Page(live_server, browser, "uxa-gs-5")
    ws = get_workspace_state(s.uid, s.rec.project_id)
    values = dict(WorkbookService.build_draft_input_set_from_workspace(ws).values)
    base = get_or_create_base_case_scenario(
        user_id=s.uid, project_id=s.rec.project_id, project_code=s.rec.project_code, project_name="GS", project_type="solar",
        source_project_template="", base_input_set=values, governance_state={})
    add_scenario(user_id=s.uid, project_id=s.rec.project_id, project_code=s.rec.project_code, scenario_name="Alt",
                 parent_scenario_id=base.scenario_id, base_input_set=values, overrides={})
    s.page.goto(f"{live_server}/v2/workbook?project={s.rec.project_code}")
    _fulfil(s.page, RESULT)
    s.open_and_load()
    s.solve()
    s.page.wait_for_selector("[data-testid=gs-result]", state="attached")
    s.page.evaluate("document.getElementById('tab-scenarios').click()")
    row = s.page.locator(".v2-scenario-row").filter(has_text="Alt")
    row.get_by_role("button", name="Select", exact=True).click()
    s.page.wait_for_selector("[data-testid=gs-context-changed]", state="attached")
    assert s.page.locator("[data-testid=gs-result]").count() == 0
    s.assert_clean()
    s.close()


def test_goal_seek_progress_reports_only_real_states(live_server, browser):
    """UX-015: request sent -> finished, or failed. No percentage, no invented stages; the solve itself is mocked here, so nothing is claimed about solver time."""
    s = _Page(live_server, browser, "uxa-gs-6")
    held = {}
    s.page.route("**/goal-seek/run", lambda route: held.setdefault("route", route))
    s.open_and_load()
    s.page.fill("#gs-target-value", "9.5")
    s.page.click("[data-testid=gs-run-btn]")
    for _ in range(50):
        if "route" in held:
            break
        time.sleep(0.1)
    assert "route" in held
    toast = s.page.locator("[data-testid=toast-info]")
    toast.wait_for()
    assert "request sent" in toast.inner_text() and "%" not in toast.inner_text()                 # a real state, never a simulated percentage
    held["route"].fulfill(status=200, content_type="text/html", body=RESULT)
    s.page.locator("[data-testid=toast-success]").filter(has_text="Goal Seek finished").wait_for()
    assert s.page.locator("[data-testid=toast-info]").count() == 0                                # the waiting toast is gone
    s.page.unroute("**/goal-seek/run")
    _fulfil(s.page, "<p>Workspace not found.</p>", status=500)
    s.page.click("[data-testid=gs-run-btn]")
    s.page.locator("[data-testid=toast-error]").filter(has_text="did not complete").wait_for()
    s.close()
