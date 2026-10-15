"""RC-UX Phase 2 / Addendum D (Flowbite): real Chromium under the real CSP.

Proves the self-hosted Flowbite layer is actually applied (computed styles, not class names), initialises once and survives HTMX swaps, works
in light and dark mode and on a phone, loads nothing from outside the origin and raises no CSP / console / page errors.
"""
from __future__ import annotations

import re
from urllib.parse import urlparse

import pytest

pytest.importorskip("playwright", reason="playwright not installed in this workflow")

from tests.test_rcux2_construction_timing_browser import Timing  # noqa: E402
from tests.test_rcux2_ppa_quick_add_browser import browser, live_server  # noqa: F401,E402


class Page(Timing):
    """A session that also records every request URL."""

    def __init__(self, live_server, browser, uid, viewport=None, scheme="light", sheet="overview"):
        self.sheet = sheet
        self.urls = []
        from app.auth import COOKIE_NAME, create_session_token
        from app.services.reference_seed_service import create_reference_seeded_project
        self.uid = uid
        self.rec = create_reference_seeded_project(user_id=uid, template_source="generic_solar_reference", requested_name="FB", capacity_mw=40.0)
        self.ctx = browser.new_context(viewport=viewport or {"width": 1440, "height": 900}, color_scheme=scheme)
        self.ctx.add_cookies([{"name": COOKIE_NAME, "value": create_session_token(user_id=uid, username="admin"), "url": live_server}])
        self.page = self.ctx.new_page()
        self.errors, self.posts = [], []
        self.page.on("pageerror", lambda e: self.errors.append(str(e)))
        self.page.on("console", lambda m: self.errors.append(m.text) if m.type == "error"
                     and not str((m.location or {}).get("url", "")).endswith("/favicon.ico") else None)
        self.page.on("request", lambda r: self.urls.append(r.url))
        self.base = live_server
        self.page.goto(f"{live_server}/v2/workbook?project={self.rec.project_code}&sheet={sheet}")
        self.page.wait_for_selector("#v2-workbook-shell", state="attached")


def test_flowbite_assets_are_self_hosted_and_raise_no_csp_or_console_error(live_server, browser):
    p = Page(live_server, browser, "rcux2-fb-1")
    p.page.wait_for_load_state("networkidle")
    origin = urlparse(live_server).netloc
    assert {urlparse(u).netloc for u in p.urls if u.startswith("http")} == {origin}              # nothing from a CDN or any other host
    assert any(u.endswith("/static/vendor/flowbite.min.js") for u in p.urls) and any(u.endswith("/static/css/flowbite_finco.min.css") for u in p.urls)
    assert p.page.evaluate("typeof window.initFlowbite === 'function' && typeof window.Accordion === 'function'")
    assert p.errors == [], p.errors
    p.close()


def test_revenue_form_controls_use_the_flowbite_styles_and_the_advanced_accordion_toggles(live_server, browser):
    p = Page(live_server, browser, "rcux2-fb-2", sheet="revenue")
    p.page.evaluate("document.getElementById('tab-revenue').click()")
    field = p.page.locator('[data-testid=ppa-quick-add] [data-quick="price"]')
    field.scroll_into_view_if_needed()
    style = field.evaluate("e => { const c = getComputedStyle(e); return {r: c.borderTopLeftRadius, b: c.borderTopWidth, bg: c.backgroundColor}; }")
    assert style["r"] == "8px" and style["b"] == "1px" and style["bg"] == "rgb(249, 250, 251)"        # Flowbite input: rounded-lg, 1px border, bg-gray-50
    button = p.page.locator("[data-accordion-target='#rc-adv-body']")
    body = p.page.locator("#rc-adv-body")
    assert button.get_attribute("aria-expanded") == "true" and body.is_visible()                       # open by default: existing flows keep working
    button.click()
    assert body.is_hidden() and button.get_attribute("aria-expanded") == "false"
    button.click()
    assert body.is_visible()
    assert p.errors == [], p.errors
    p.close()


def test_accordion_initialises_once_and_survives_repeated_htmx_settles(live_server, browser):
    p = Page(live_server, browser, "rcux2-fb-3", sheet="debt")
    p.page.evaluate("document.getElementById('tab-debt').click()")
    button = p.page.locator("[data-accordion-target='#cs-unsupported-body']")
    body = p.page.locator("#cs-unsupported-body")
    button.scroll_into_view_if_needed()
    assert body.is_hidden()
    for _ in range(3):                                                                                  # what every HTMX swap triggers
        p.page.evaluate("document.body.dispatchEvent(new CustomEvent('htmx:afterSettle', {bubbles: true}))")
    button.click()
    assert body.is_visible() and button.get_attribute("aria-expanded") == "true"                        # one click = one toggle (no duplicate listeners)
    button.click()
    assert body.is_hidden()
    assert p.errors == [], p.errors
    p.close()


def test_save_feedback_toast_is_accessible_dismissible_and_does_not_replace_the_saved_state(live_server, browser):
    p = Page(live_server, browser, "rcux2-fb-4", sheet="project_setup")
    p.page.evaluate("document.getElementById('tab-project-setup').click()")
    p.page.wait_for_function("() => document.querySelector('[data-testid=construction-timing] [data-dd=end]').value !== ''")
    p.dd("duration").fill("20")
    p.save()
    toast = p.page.locator("[data-testid=toast-success]").first
    toast.wait_for()
    assert toast.get_attribute("role") == "status" and "Construction timing saved" in toast.inner_text()
    assert p.page.locator("#fx-toast-region").get_attribute("aria-live") == "polite"
    toast.get_by_role("button", name="Close").click()
    assert p.page.locator("[data-testid=toast-success]").count() == 0
    assert p.saved()[1] == 20
    assert p.errors == [], p.errors
    p.close()


def test_run_shows_a_loading_toast_then_a_result_toast_and_overview_cards_are_flowbite_cards(live_server, browser):
    p = Page(live_server, browser, "rcux2-fb-5", sheet="overview")
    p.page.evaluate("document.getElementById('tab-overview').click()")
    with p.page.expect_response(lambda r: "/v2/workbook/run" in r.url and r.request.method == "POST", timeout=240000):
        p.page.locator('[data-testid="header-run-btn"]').click()
        p.page.locator("[data-testid=toast-info]").wait_for()                                            # loading state while the model runs
    p.page.locator("[data-testid=toast-success]").filter(has_text="Model run complete").wait_for(timeout=240000)
    card = p.page.locator(".v2-kpi-tile").first
    card.wait_for()
    style = card.evaluate("e => { const c = getComputedStyle(e); return {r: c.borderTopLeftRadius, b: c.borderTopWidth, s: c.boxShadow, bg: c.backgroundColor}; }")
    assert style["r"] == "8px" and style["b"] == "1px" and style["s"] != "none" and style["bg"] == "rgb(255, 255, 255)"
    assert p.page.locator("[data-testid=overview-state-strip]").evaluate("e => getComputedStyle(e).borderTopLeftRadius") == "8px"
    assert p.errors == [], p.errors
    p.close()


def test_dark_mode_uses_the_dark_flowbite_palette(live_server, browser):
    p = Page(live_server, browser, "rcux2-fb-6", scheme="dark", sheet="revenue")
    p.page.evaluate("document.getElementById('tab-revenue').click()")
    field = p.page.locator('[data-testid=ppa-quick-add] [data-quick="price"]')
    field.scroll_into_view_if_needed()
    assert field.evaluate("e => getComputedStyle(e).backgroundColor") == "rgb(55, 65, 81)"             # dark:bg-gray-700
    assert p.page.locator("[data-testid=ppa-quick-add]").evaluate("e => getComputedStyle(e).backgroundColor") == "rgb(31, 41, 55)"   # dark:bg-gray-800
    p.close()


@pytest.mark.parametrize("sheet", ["overview", "revenue", "debt", "investor", "run-history"])
def test_phone_layout_in_dark_mode_has_no_document_overflow(live_server, browser, sheet):
    p = Page(live_server, browser, "rcux2-fb-7", viewport={"width": 390, "height": 844}, scheme="dark", sheet=sheet)
    p.page.wait_for_timeout(800)
    assert p.page.evaluate("document.documentElement.scrollWidth <= window.innerWidth + 1"), sheet
    assert p.errors == [], p.errors
    p.close()
