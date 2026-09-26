"""P3 Run Certificate V1 — Playwright browser acceptance tests.

Acceptance markers:
  RUN_CERTIFICATE_BROWSER_1280            — certificate page at 1280px viewport
  RUN_CERTIFICATE_BROWSER_390             — certificate page at 390px viewport (mobile)
  RUN_CERTIFICATE_BROWSER_CONTEXTUAL_JOURNEY — contextual "View Run Certificate" link journey
"""
from __future__ import annotations

import threading
import time

import pytest

pytest.importorskip("playwright", reason="playwright not installed in this workflow")
from playwright.sync_api import sync_playwright, Page


# ---------------------------------------------------------------------------
# App server fixture
# ---------------------------------------------------------------------------

@pytest.fixture(scope="module")
def app_server():
    """Start a live FINCO app server and yield its base URL."""
    import uvicorn
    import sys
    import os
    sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
    from main_web import app as web_app

    config = uvicorn.Config(web_app, host="127.0.0.1", port=19750, log_level="error")
    server = uvicorn.Server(config)
    thread = threading.Thread(target=server.run, daemon=True)
    thread.start()

    import socket
    deadline = time.time() + 30
    while time.time() < deadline:
        try:
            with socket.create_connection(("127.0.0.1", 19750), timeout=1):
                break
        except OSError:
            time.sleep(0.2)
    else:
        raise RuntimeError("App server did not start within 30 seconds")

    yield "http://127.0.0.1:19750"

    server.should_exit = True
    thread.join(timeout=5)


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _demo_cookie_name() -> str:
    from app.auth import DEMO_COOKIE_NAME
    return DEMO_COOKIE_NAME


def _make_demo_token() -> str:
    from app.auth import create_demo_session_token, new_demo_user_id
    return create_demo_session_token(new_demo_user_id())


def _solar_project_code() -> str:
    from app.persistence.projects_repository import get_reference_by_template_source
    rec = get_reference_by_template_source("generic_solar_reference")
    assert rec is not None, "Solar reference must be seeded at startup"
    return rec.project_code


def _set_auth_cookie(context, base_url: str) -> None:
    """Set a demo session cookie on the browser context."""
    from urllib.parse import urlparse
    parsed = urlparse(base_url)
    context.add_cookies([{
        "name": _demo_cookie_name(),
        "value": _make_demo_token(),
        "domain": parsed.hostname,
        "path": "/",
    }])


def _navigate_to_certificate(page: Page, base_url: str, project_code: str) -> None:
    page.goto(f"{base_url}/verify/run/{project_code}", wait_until="domcontentloaded")


# ---------------------------------------------------------------------------
# Desktop — 1280px
# RUN_CERTIFICATE_BROWSER_1280
# ---------------------------------------------------------------------------

def test_run_certificate_browser_1280(app_server):
    """RUN_CERTIFICATE_BROWSER_1280: certificate page renders fully at 1280px viewport."""
    project_code = _solar_project_code()

    with sync_playwright() as pw:
        browser = pw.chromium.launch(executable_path="/opt/pw-browsers/chromium")
        context = browser.new_context(viewport={"width": 1280, "height": 900})
        _set_auth_cookie(context, app_server)
        page = context.new_page()
        try:
            _navigate_to_certificate(page, app_server, project_code)

            # Certificate route loads (not error page)
            assert page.title() != "", "Page title must not be empty"

            # Use text_content() to get raw DOM text unaffected by CSS text-transform.
            body_text = page.locator("body").text_content()

            # Status badge
            assert "INTEGRITY BOUND" in body_text, "INTEGRITY BOUND badge must be visible"

            # Run Identity section
            assert "Run Identity" in body_text, "Run Identity section must be visible"
            assert "Engine version" in body_text, "Engine version must be visible"

            # Integrity section
            assert "Composite identity" in body_text or "Integrity" in body_text, (
                "Integrity section must be visible"
            )
            assert "Assumption digest" in body_text, "Assumption digest must be visible"
            assert "Output digest" in body_text, "Output digest must be visible"
            assert "Certificate digest" in body_text, "Certificate digest must be visible"

            # Headline outputs
            assert "Project IRR" in body_text, "Project IRR headline output must be visible"

            # Disclaimer
            assert "Disclaimer" in body_text, "Disclaimer must be visible"
            assert "not an audit opinion" in body_text, "Disclaimer text must be visible"

        finally:
            browser.close()


# ---------------------------------------------------------------------------
# Mobile — 390px
# RUN_CERTIFICATE_BROWSER_390
# ---------------------------------------------------------------------------

def test_run_certificate_browser_390(app_server):
    """RUN_CERTIFICATE_BROWSER_390: certificate page renders correctly at 390px (no horizontal overflow)."""
    project_code = _solar_project_code()

    with sync_playwright() as pw:
        browser = pw.chromium.launch(executable_path="/opt/pw-browsers/chromium")
        context = browser.new_context(viewport={"width": 390, "height": 844})
        _set_auth_cookie(context, app_server)
        page = context.new_page()
        try:
            _navigate_to_certificate(page, app_server, project_code)

            # Use text_content() to get raw DOM text unaffected by CSS text-transform.
            body_text = page.locator("body").text_content()

            # Certificate still loads
            assert "INTEGRITY BOUND" in body_text, "INTEGRITY BOUND must be visible at 390px"
            assert "Disclaimer" in body_text, "Disclaimer must be visible at 390px"
            assert "Project IRR" in body_text, "Headline outputs must be visible at 390px"

            # Zero horizontal overflow — document width must not exceed viewport width
            scroll_width = page.evaluate("document.documentElement.scrollWidth")
            viewport_width = 390
            assert scroll_width <= viewport_width + 2, (
                f"Horizontal overflow at 390px: scrollWidth={scroll_width} > {viewport_width}. "
                "SHA-256 values or other content causing overflow."
            )

            # SHA-256 values are present (readable/wrapped, not clipped)
            # The composite hash row must be in the DOM
            cert_hash_elements = page.locator("[class*='mono']").count()
            assert cert_hash_elements > 0, "Monospace hash values must be present (not clipped)"

            # Headline output grid must be present
            output_cells = page.locator("[class*='output-cell']").count()
            assert output_cells > 0, "Headline output cells must be present at 390px"

        finally:
            browser.close()


# ---------------------------------------------------------------------------
# Contextual journey — RUN_CERTIFICATE_BROWSER_CONTEXTUAL_JOURNEY
# ---------------------------------------------------------------------------

def test_run_certificate_browser_contextual_journey(app_server):
    """RUN_CERTIFICATE_BROWSER_CONTEXTUAL_JOURNEY: 'View Run Certificate' link appears on
    model surface for a project with a committed last run, and navigates to certificate page."""
    project_code = _solar_project_code()

    with sync_playwright() as pw:
        browser = pw.chromium.launch(executable_path="/opt/pw-browsers/chromium")
        context = browser.new_context(viewport={"width": 1280, "height": 900})
        _set_auth_cookie(context, app_server)
        page = context.new_page()
        try:
            # Navigate to the model index page for the reference project
            page.goto(
                f"{app_server}/?project={project_code}",
                wait_until="domcontentloaded",
            )

            # "View Run Certificate" link must appear in the last-run indicator
            cert_link = page.locator("a[href*='/verify/run/']")
            assert cert_link.count() > 0, (
                "A 'View Run Certificate' link must appear on the model surface for a project "
                "with a committed last run. Check _last_run_indicator.html."
            )

            # The link must point to this project's certificate
            href = cert_link.first.get_attribute("href")
            assert project_code in href, (
                f"Certificate link {href!r} must reference project_code={project_code!r}"
            )

            # Follow the link
            with page.expect_navigation(wait_until="domcontentloaded"):
                cert_link.first.click()

            # Certificate page must load
            body_text = page.locator("body").inner_text()
            assert "INTEGRITY BOUND" in body_text, (
                "Navigating the contextual 'View Run Certificate' link must reach the "
                "certificate page showing INTEGRITY BOUND."
            )

        finally:
            browser.close()
