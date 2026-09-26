"""P1 Institutional Trust Pack — browser acceptance tests.

Verifies that the /model/methodology page renders correctly at desktop (1280px)
and mobile (390px) widths and contains all required methodology markers.
"""
from __future__ import annotations

import threading
import time
import pytest

pytest.importorskip("playwright", reason="playwright not installed in this workflow")
from playwright.sync_api import sync_playwright, Page


# ── App server fixture ────────────────────────────────────────────────────────

@pytest.fixture(scope="module")
def app_server():
    """Start a live FINCO app server and yield its base URL."""
    import uvicorn
    import sys, os
    sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
    from main_web import app as web_app

    config = uvicorn.Config(web_app, host="127.0.0.1", port=19723, log_level="error")
    server = uvicorn.Server(config)
    thread = threading.Thread(target=server.run, daemon=True)
    thread.start()

    # Wait until server accepts connections
    import socket
    deadline = time.time() + 30
    while time.time() < deadline:
        try:
            with socket.create_connection(("127.0.0.1", 19723), timeout=1):
                break
        except OSError:
            time.sleep(0.2)
    else:
        raise RuntimeError("App server did not start within 30 seconds")

    yield "http://127.0.0.1:19723"

    server.should_exit = True
    thread.join(timeout=5)


# ── Required content markers on the methodology page ─────────────────────────

_REQUIRED_MARKERS = [
    # Formula authorities
    "cfads_keur",
    "ebitda_keur",
    "financial_engine/cfads.py",
    "finco_core/ebitda.py",
    "365",  # XIRR 365-day convention
    # Reference model parameters
    "33,000",       # total CAPEX kEUR
    "380",          # Y1 OPEX kEUR
    "64 MW",        # capacity
    "25%",          # tax rate (rendered in table)
    "1.20",         # target DSCR
    "75.0%",        # gearing
    "50",           # operating periods
    # Engine-reconciled canonical reference values (not "live engine numbers")
    "11.56%",       # Project IRR
    "50.47%",       # Equity IRR (EQUITY_ONLY)
    "17.90%",       # Total Sponsor XIRR
    "24,750",       # senior debt kEUR
    "147,815",      # total EBITDA kEUR
    "123,129",      # total CFADS kEUR
    # Sources & Uses reconciliation
    "500",          # share capital kEUR
    "7,750",        # SHL kEUR
    # DSRA actual state
    "NONE",         # dsra_support_mode = NONE
]


def _check_methodology_page(page: Page, base_url: str, width: int):
    page.set_viewport_size({"width": width, "height": 900})
    page.goto(f"{base_url}/model/methodology", wait_until="domcontentloaded")

    # Page must load (not 404 / 500)
    assert page.title() != "", "Page title is empty — likely a render error"
    assert "methodology" in page.title().lower() or "FINCO" in page.title(), (
        f"Unexpected page title: {page.title()!r}"
    )

    body_text = page.locator("body").inner_text()

    for marker in _REQUIRED_MARKERS:
        assert marker in body_text, (
            f"Required methodology marker {marker!r} not found on page "
            f"(viewport={width}px)"
        )


# ── Tests ─────────────────────────────────────────────────────────────────────

def test_methodology_page_desktop_1280(app_server):
    """TRUST_PACK_BROWSER_METHODOLOGY_1280 — methodology page renders at 1280px."""
    with sync_playwright() as pw:
        browser = pw.chromium.launch(executable_path="/opt/pw-browsers/chromium")
        page = browser.new_page()
        try:
            _check_methodology_page(page, app_server, 1280)
        finally:
            browser.close()


def test_methodology_page_mobile_390(app_server):
    """TRUST_PACK_BROWSER_METHODOLOGY_390 — methodology page renders at 390px."""
    with sync_playwright() as pw:
        browser = pw.chromium.launch(executable_path="/opt/pw-browsers/chromium")
        page = browser.new_page()
        try:
            _check_methodology_page(page, app_server, 390)
        finally:
            browser.close()


def test_methodology_page_has_nav_links(app_server):
    """TRUST_PACK_BROWSER_NAV_LINKS — methodology page must have internal anchor links."""
    with sync_playwright() as pw:
        browser = pw.chromium.launch(executable_path="/opt/pw-browsers/chromium")
        page = browser.new_page()
        page.set_viewport_size({"width": 1280, "height": 900})
        try:
            page.goto(f"{app_server}/model/methodology", wait_until="domcontentloaded")
            # Check that section anchors exist
            for anchor_id in ["cfads", "ebitda", "debt", "project-irr", "reference"]:
                count = page.locator(f"#{anchor_id}").count()
                assert count >= 1, f"Expected section anchor #{anchor_id} not found"
        finally:
            browser.close()


def test_methodology_page_no_500_error(app_server):
    """TRUST_PACK_BROWSER_NO_500 — /model/methodology must not return a 500 error."""
    with sync_playwright() as pw:
        browser = pw.chromium.launch(executable_path="/opt/pw-browsers/chromium")
        page = browser.new_page()
        try:
            response = page.goto(
                f"{app_server}/model/methodology", wait_until="domcontentloaded"
            )
            assert response is not None, "No response received"
            assert response.status == 200, (
                f"Expected HTTP 200, got {response.status}"
            )
        finally:
            browser.close()


def test_methodology_page_no_horizontal_overflow_390(app_server):
    """TRUST_PACK_BROWSER_390 — no horizontal scroll at 390px mobile width."""
    with sync_playwright() as pw:
        browser = pw.chromium.launch(executable_path="/opt/pw-browsers/chromium")
        page = browser.new_page()
        page.set_viewport_size({"width": 390, "height": 900})
        try:
            page.goto(f"{app_server}/model/methodology", wait_until="domcontentloaded")
            scroll_width = page.evaluate("document.documentElement.scrollWidth")
            client_width = page.evaluate("document.documentElement.clientWidth")
            assert scroll_width <= client_width + 5, (
                f"Horizontal overflow at 390px: scrollWidth={scroll_width} > clientWidth={client_width}"
            )
        finally:
            browser.close()


def test_docs_links_to_methodology(app_server):
    """TRUST_PACK_DOCS_DISCOVERABILITY — /docs page must link to /model/methodology."""
    with sync_playwright() as pw:
        browser = pw.chromium.launch(executable_path="/opt/pw-browsers/chromium")
        page = browser.new_page()
        page.set_viewport_size({"width": 1280, "height": 900})
        try:
            response = page.goto(f"{app_server}/docs", wait_until="domcontentloaded")
            assert response is not None and response.status == 200
            links = page.locator("a[href='/model/methodology']")
            assert links.count() >= 1, (
                "/docs page must contain at least one link to /model/methodology"
            )
        finally:
            browser.close()
