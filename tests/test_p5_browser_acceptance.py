"""P5 FINCO Verified Assets V1 — browser acceptance tests.

Tests both 1280px (desktop) and 390px (mobile phone) viewports.
Covers:
  - /verified collection page
  - /verified/{asset_id} individual asset page
  - /verified/{asset_id}.json machine-readable endpoint
  - Navigation: Verified link present in proto-nav

All tests use the demo/test user session fixture established by the
existing browser acceptance test patterns in this codebase.

Markers:
  FINCO_P5_BROWSER_ACCEPTANCE_1280PX
  FINCO_P5_BROWSER_ACCEPTANCE_390PX
"""
from __future__ import annotations

import pytest

# Browser acceptance tests require the Playwright-capable test infrastructure.
# These tests are skipped in environments where the web process is not available.
pytest_plugins = []

try:
    from playwright.sync_api import sync_playwright
    _PLAYWRIGHT_AVAILABLE = True
except ImportError:
    _PLAYWRIGHT_AVAILABLE = False

pytestmark = pytest.mark.skipif(
    not _PLAYWRIGHT_AVAILABLE,
    reason="playwright not installed — browser acceptance tests skipped",
)


VIEWPORTS = {
    "desktop": {"width": 1280, "height": 800},
    "mobile": {"width": 390, "height": 844},
}

BASE_URL = "http://localhost:8000"


def _authenticated_page(playwright, viewport_key: str):
    """Return a Playwright page pre-authenticated via demo session cookie."""
    vp = VIEWPORTS[viewport_key]
    browser = playwright.chromium.launch(
        headless=True,
        executable_path="/opt/pw-browsers/chromium",
    )
    context = browser.new_context(viewport=vp)
    page = context.new_page()

    # Establish demo session by hitting the demo login route.
    page.goto(f"{BASE_URL}/demo-login", wait_until="networkidle")

    return page, browser


# ── Collection page ────────────────────────────────────────────────────────────

@pytest.mark.parametrize("viewport_key", ["desktop", "mobile"])
def test_verified_index_loads(viewport_key):
    """GET /verified returns 200 and shows the page heading.

    FINCO_P5_BROWSER_ACCEPTANCE_1280PX
    FINCO_P5_BROWSER_ACCEPTANCE_390PX
    """
    with sync_playwright() as p:
        page, browser = _authenticated_page(p, viewport_key)
        try:
            response = page.goto(f"{BASE_URL}/verified", wait_until="networkidle")
            assert response.status == 200, f"Expected 200, got {response.status}"

            # Heading visible
            h1 = page.locator("h1").first
            assert h1.is_visible()
            assert "Verified" in h1.inner_text()

            # No horizontal scroll
            scroll_width = page.evaluate("document.documentElement.scrollWidth")
            client_width = page.evaluate("document.documentElement.clientWidth")
            assert scroll_width <= client_width + 2, (
                f"Horizontal scroll at {viewport_key}: scrollWidth={scroll_width} > clientWidth={client_width}"
            )
        finally:
            browser.close()


@pytest.mark.parametrize("viewport_key", ["desktop", "mobile"])
def test_verified_index_shows_pipeline_banner(viewport_key):
    """Pipeline banner (NUMBER → LINEAGE → EVIDENCE → MARKET OBSERVATION) is visible."""
    with sync_playwright() as p:
        page, browser = _authenticated_page(p, viewport_key)
        try:
            page.goto(f"{BASE_URL}/verified", wait_until="networkidle")
            pipeline = page.locator(".va-pipeline")
            assert pipeline.count() > 0
            assert pipeline.first.is_visible()
        finally:
            browser.close()


@pytest.mark.parametrize("viewport_key", ["desktop", "mobile"])
def test_verified_index_nav_link_active(viewport_key):
    """'Verified' nav link is marked active on the collection page."""
    with sync_playwright() as p:
        page, browser = _authenticated_page(p, viewport_key)
        try:
            page.goto(f"{BASE_URL}/verified", wait_until="networkidle")
            active_links = page.locator(".proto-nav__link--active")
            assert active_links.count() > 0
            active_text = active_links.first.inner_text().strip()
            assert "Verified" in active_text
        finally:
            browser.close()


@pytest.mark.parametrize("viewport_key", ["desktop", "mobile"])
def test_verified_index_asset_cards_present(viewport_key):
    """Asset cards or empty notice are rendered — no blank page."""
    with sync_playwright() as p:
        page, browser = _authenticated_page(p, viewport_key)
        try:
            page.goto(f"{BASE_URL}/verified", wait_until="networkidle")
            cards = page.locator(".va-card")
            empty = page.locator(".va-empty")
            assert cards.count() > 0 or empty.count() > 0, (
                "Neither asset cards nor empty notice rendered"
            )
        finally:
            browser.close()


# ── Individual asset page ──────────────────────────────────────────────────────

@pytest.mark.parametrize("viewport_key", ["desktop", "mobile"])
@pytest.mark.parametrize("asset_id", ["generic_solar_reference", "generic_wind_reference"])
def test_verified_asset_detail_loads(asset_id, viewport_key):
    """GET /verified/{asset_id} returns 200 and shows asset name.

    FINCO_P5_BROWSER_ACCEPTANCE_1280PX
    FINCO_P5_BROWSER_ACCEPTANCE_390PX
    """
    with sync_playwright() as p:
        page, browser = _authenticated_page(p, viewport_key)
        try:
            response = page.goto(
                f"{BASE_URL}/verified/{asset_id}", wait_until="networkidle"
            )
            assert response.status == 200

            h1 = page.locator("h1").first
            assert h1.is_visible()

            # No horizontal scroll
            scroll_width = page.evaluate("document.documentElement.scrollWidth")
            client_width = page.evaluate("document.documentElement.clientWidth")
            assert scroll_width <= client_width + 2
        finally:
            browser.close()


@pytest.mark.parametrize("viewport_key", ["desktop", "mobile"])
def test_verified_asset_back_link(viewport_key):
    """Detail page includes a back link to /verified."""
    with sync_playwright() as p:
        page, browser = _authenticated_page(p, viewport_key)
        try:
            page.goto(
                f"{BASE_URL}/verified/generic_solar_reference", wait_until="networkidle"
            )
            back_link = page.locator(".va-detail-header__back")
            assert back_link.count() > 0
            assert back_link.first.is_visible()
            href = back_link.first.get_attribute("href")
            assert href == "/verified"
        finally:
            browser.close()


def test_verified_asset_not_found_returns_404():
    """GET /verified/nonexistent_asset returns 404 status."""
    with sync_playwright() as p:
        page, browser = _authenticated_page(p, "desktop")
        try:
            response = page.goto(
                f"{BASE_URL}/verified/nonexistent_asset_xyz_p5",
                wait_until="networkidle",
            )
            assert response.status == 404
        finally:
            browser.close()


# ── JSON endpoint ──────────────────────────────────────────────────────────────

def test_verified_asset_json_endpoint():
    """GET /verified/{asset_id}.json returns JSON with schema field."""
    import json as _json

    with sync_playwright() as p:
        page, browser = _authenticated_page(p, "desktop")
        try:
            response = page.goto(
                f"{BASE_URL}/verified/generic_solar_reference.json",
                wait_until="networkidle",
            )
            assert response.status == 200
            content_type = response.headers.get("content-type", "")
            assert "json" in content_type

            body = _json.loads(page.content() or response.body())
            assert body.get("schema") == "FINCO_VERIFIED_ASSET_V1"
            assert "status" in body
            assert "asset_id" in body
        finally:
            browser.close()


def test_verified_asset_json_unauthenticated_returns_401():
    """GET /verified/{asset_id}.json without auth returns 401."""
    with sync_playwright() as p:
        browser = p.chromium.launch(
            headless=True,
            executable_path="/opt/pw-browsers/chromium",
        )
        context = browser.new_context(viewport=VIEWPORTS["desktop"])
        page = context.new_page()
        try:
            response = page.goto(
                f"{BASE_URL}/verified/generic_solar_reference.json",
                wait_until="networkidle",
            )
            assert response.status == 401
        finally:
            browser.close()
