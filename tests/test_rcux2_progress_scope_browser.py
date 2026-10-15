"""UX-012: a command only reads "Running… / Solving…" while ITS OWN request is active (real Chromium, real CSP)."""
from __future__ import annotations

import time

import pytest

pytest.importorskip("playwright", reason="playwright not installed in this workflow")

from tests.test_rcux2_construction_timing_browser import Timing  # noqa: E402
from tests.test_rcux2_ppa_quick_add_browser import browser, live_server  # noqa: F401,E402


def _display(page, selector):
    return page.locator(selector).first.evaluate("e => getComputedStyle(e).display")


def test_an_unrelated_lazy_fetch_does_not_make_other_commands_show_progress_text(live_server, browser):
    t = Timing(live_server, browser, "rcux2-ps-1")
    held = {}
    t.page.route("**/decision/goal-seek*", lambda route: held.setdefault("route", route))          # keep the panel's own lazy GET in flight
    t.page.evaluate("document.getElementById('tab-goal-seek').click()")
    for _ in range(50):
        if "route" in held:
            break
        time.sleep(0.1)
    assert "route" in held
    t.page.wait_for_selector("#v2-sheet-goal-seek.htmx-request", state="attached")                  # the ancestor panel is busy loading
    assert _display(t.page, "#v2-sheet-goal-seek .v2-run-loading") == "none"                        # Goal Seek's own button does not claim to be solving
    assert _display(t.page, "#v2-canonical-run-form .v2-run-loading") == "none"                     # and the model Run button does not claim to be running
    assert _display(t.page, "#v2-canonical-run-form .v2-run-label") != "none"
    held["route"].continue_()
    t.close()


def test_the_run_button_shows_progress_only_while_the_run_request_is_active(live_server, browser):
    t = Timing(live_server, browser, "rcux2-ps-2")
    seen = {}

    def hold(route):
        seen["route"] = route
    t.page.route("**/v2/workbook/run", hold)
    t.page.evaluate("document.getElementById('tab-overview').click()")
    t.page.locator('[data-testid="header-run-btn"]').click()
    for _ in range(50):
        if "route" in seen:
            break
        time.sleep(0.1)
    assert "route" in seen
    assert _display(t.page, "#v2-canonical-run-form .v2-run-loading") == "inline"                  # its own request is active
    assert _display(t.page, "#v2-canonical-run-form .v2-run-label") == "none"
    seen["route"].abort()
    t.close()
