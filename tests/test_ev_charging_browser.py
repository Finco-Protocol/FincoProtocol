"""EV Charging Correction B — real browser acceptance (spec §14).

Drives the actual UI journey: Home → Model Library → Generic EV Charging Hub
Reference → Create Working Copy → EV working-copy workbook.  Then verifies EV
driver fields, edits a driver through the real form (save → reload → persist),
runs the model, checks Returns, and asserts no horizontal overflow at 1280 px
and 390 px.  Skipped automatically where Playwright/Chromium is unavailable
(the Linux CI browser ring provides execution).
"""

from __future__ import annotations

import os
import socket
import threading
import time
import uuid

import pytest

pytest.importorskip("playwright")
pytest.importorskip("uvicorn")

from playwright.sync_api import sync_playwright


def _free_port() -> int:
    with socket.socket() as sock:
        sock.bind(("127.0.0.1", 0))
        return sock.getsockname()[1]


@pytest.fixture(scope="module")
def ev_app(tmp_path_factory):
    """Live application with isolated persistence."""
    from app.persistence import db

    db.DB_PATH = str(tmp_path_factory.mktemp("ev-browser") / "finco.db")

    import main_web
    import uvicorn

    port = _free_port()
    server = uvicorn.Server(
        uvicorn.Config(main_web.app, host="127.0.0.1", port=port, log_level="error")
    )
    thread = threading.Thread(target=server.run, daemon=True)
    thread.start()
    deadline = time.time() + 15
    while not server.started and time.time() < deadline:
        time.sleep(0.05)
    assert server.started, "EV browser fixture server did not start"
    try:
        yield {"url": f"http://127.0.0.1:{port}"}
    finally:
        server.should_exit = True
        thread.join(10)


_CHROMIUM_EXEC = "/opt/pw-browsers/chromium"


@pytest.fixture(scope="module")
def browser():
    launch_kwargs: dict = {"args": ["--no-sandbox", "--disable-setuid-sandbox"]}
    if os.path.exists(_CHROMIUM_EXEC):
        launch_kwargs["executable_path"] = _CHROMIUM_EXEC
    with sync_playwright() as pw:
        instance = pw.chromium.launch(**launch_kwargs)
        yield instance
        instance.close()


def _page(browser, ev_app, *, user_id: str):
    from app.auth import COOKIE_NAME, create_session_token

    page = browser.new_page(viewport={"width": 1280, "height": 1000})
    page.context.add_cookies(
        [{
            "name": COOKIE_NAME,
            "value": create_session_token(user_id=user_id, username=user_id),
            "domain": "127.0.0.1",
            "path": "/",
        }]
    )
    return page


def _assert_no_horizontal_overflow(page) -> None:
    overflow = page.evaluate(
        "document.documentElement.scrollWidth - document.documentElement.clientWidth"
    )
    assert overflow <= 1, f"horizontal overflow of {overflow}px"


def _create_ev_working_copy(page, ev_app) -> str:
    """Home → Model Library → EV reference → Create Working Copy → workbook.

    Returns the working-copy project code fragment from the final URL.
    """
    page.goto(ev_app["url"] + "/")
    page.get_by_role("link", name="Model", exact=True).click()
    page.wait_for_url("**/library")
    assert page.get_by_text("Generic EV Charging Hub Reference").count() >= 1

    page.locator("a.fo-library-cta-new").click()
    page.wait_for_url("**/projects/new")
    page.locator('input[name="template_source"][value="generic_ev_charging_reference"]').check()
    page.locator("#npm-project_name").fill("EV Browser Acceptance")
    page.locator("#npm-capacity_mw").fill("5")
    page.get_by_role("button", name="Create project").click()
    page.wait_for_url("**/v2/workbook?project=**")
    return page.url


def test_ev_browser_full_journey(ev_app, browser):
    user_id = "ev-browser-" + uuid.uuid4().hex[:8]
    page = _page(browser, ev_app, user_id=user_id)
    try:
        _create_ev_working_copy(page, ev_app)

        # ── EV driver section visible on the Revenue sheet ──────────────
        page.locator("#tab-revenue").click()
        revenue_panel = page.locator("#panel-revenue")
        revenue_panel.locator(
            '[data-field-id="revenue.ev_charging.charging_price"]'
        ).wait_for(state="visible", timeout=30_000)
        for fid in (
            "revenue.ev_charging.hours_y1",
            "revenue.ev_charging.hours_y2",
            "revenue.ev_charging.hours_stabilized",
            "revenue.ev_charging.charging_price_escalation",
            "revenue.ev_charging.charging_efficiency",
            "revenue.ev_charging.electricity_price",
            "revenue.ev_charging.electricity_price_escalation",
        ):
            assert revenue_panel.locator(f'[data-field-id="{fid}"]').count() == 1, fid
        # availability is informational (display-only, never a BOUND control)
        avail = revenue_panel.locator(
            '[data-field-id="revenue.ev_charging.availability_info"]'
        )
        assert avail.count() == 1
        assert avail.locator("input:not([type=hidden])").count() == 0
        # "net of availability" policy lives in the field description (title/help)
        title = avail.get_attribute("title") or ""
        help_attr = avail.locator("[title]").first.get_attribute("title") or "" if avail.locator("[title]").count() else ""
        assert "net of availability" in (title + " " + help_attr) or "Availability" in avail.inner_text()
        # no renewable/PPA primary controls for EV
        assert revenue_panel.locator('[data-field-id="revenue.ppa.base_tariff"]').count() == 0
        assert revenue_panel.locator('[data-field-id="revenue.merchant.price_curve_json"]').count() == 0

        # ── Edit a real EV driver through the actual form: 0.40 → 0.45 ──
        price_input = revenue_panel.locator(
            '[data-field-id="revenue.ev_charging.charging_price"] input[name="value"]'
        )
        price_input.fill("0.45")
        revenue_panel.locator(
            '[data-field-id="revenue.ev_charging.charging_price"] form button[type="submit"], '
            '[data-field-id="revenue.ev_charging.charging_price"] button'
        ).first.click()
        page.wait_for_timeout(800)  # HTMX swap

        # ── Reload: the persisted driver value survives ─────────────────
        page.reload()
        page.locator("#tab-revenue").click()
        revenue_panel = page.locator("#panel-revenue")
        price_input = revenue_panel.locator(
            '[data-field-id="revenue.ev_charging.charging_price"] input[name="value"]'
        )
        price_input.wait_for(state="visible", timeout=30_000)
        assert price_input.input_value() == "0.45", "driver edit must persist"

        # ── CAPEX and OPEX sheets open; B.08 shown as derived ───────────
        page.locator("#tab-capex").click()
        page.locator("#panel-capex").wait_for(state="visible")
        assert "Total CAPEX" in page.locator("#panel-capex").inner_text()
        assert page.locator("#panel-capex").locator("text=DC Fast Chargers").count() >= 1

        page.locator("#tab-opex").click()
        opex_panel = page.locator("#panel-opex")
        opex_panel.locator('text=Power Expenses').first.wait_for(state="attached", timeout=30_000)
        opex_text = opex_panel.inner_text()
        assert "Power Expenses" in opex_text
        assert "Electricity Procurement" in opex_text

        # ── Run + Returns ───────────────────────────────────────────────
        page.locator("#tab-overview").click()
        page.locator("#panel-overview").wait_for(state="visible")
        page.locator('[data-testid="v2-run-btn"]').click()
        page.locator('[data-testid="overview-status-current"]').wait_for(
            state="attached", timeout=180_000
        )
        page.locator("#tab-returns").click()
        page.locator("#panel-returns").wait_for(state="visible")
        returns_text = page.locator("#panel-returns").inner_text()
        assert returns_text.strip() != ""

        # ── No horizontal overflow at 1280 px ───────────────────────────
        _assert_no_horizontal_overflow(page)
    finally:
        page.close()


def test_ev_browser_mobile_390(ev_app, browser):
    user_id = "ev-mobile-" + uuid.uuid4().hex[:8]
    page = _page(browser, ev_app, user_id=user_id)
    try:
        page.set_viewport_size({"width": 390, "height": 844})
        _create_ev_working_copy(page, ev_app)

        page.locator("#tab-revenue").click()
        revenue_panel = page.locator("#panel-revenue")
        revenue_panel.locator(
            '[data-field-id="revenue.ev_charging.charging_price"]'
        ).wait_for(state="visible", timeout=30_000)
        # EV driver fields are reachable at 390 px
        assert revenue_panel.locator(
            '[data-field-id="revenue.ev_charging.hours_stabilized"]'
        ).count() == 1

        _assert_no_horizontal_overflow(page)
    finally:
        page.close()
