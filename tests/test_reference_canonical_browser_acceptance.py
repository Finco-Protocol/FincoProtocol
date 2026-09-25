"""Browser acceptance for canonical reference last-run (pre-seeded KPIs).

Verifies that Solar, Wind, and Data Center reference workbooks open showing
CURRENT status and populated KPIs — not "NOT RUN" — because the startup
canonical last-run seeding has already run.  Also verifies that a working
copy created from a reference starts with an empty last-run state (NOT RUN),
and that no horizontal overflow occurs at 390 px.

Acceptance markers (all must PASS):
  SOLAR_REFERENCE_PRERUN_BROWSER
  WIND_REFERENCE_PRERUN_BROWSER
  DATA_CENTER_REFERENCE_PRERUN_BROWSER
  REFERENCE_WORKING_COPY_BROWSER_SEPARATION
  REFERENCE_MOBILE_390_NO_OVERFLOW
"""
from __future__ import annotations

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
def ref_app(tmp_path_factory):
    """Live application with isolated DB, references seeded at startup."""
    from app.persistence import db

    db.DB_PATH = str(tmp_path_factory.mktemp("ref-browser") / "finco.db")

    import main_web
    import uvicorn

    port = _free_port()
    server = uvicorn.Server(
        uvicorn.Config(main_web.app, host="127.0.0.1", port=port, log_level="error")
    )
    thread = threading.Thread(target=server.run, daemon=True)
    thread.start()
    deadline = time.time() + 30
    while not server.started and time.time() < deadline:
        time.sleep(0.05)
    assert server.started, "Reference browser fixture server did not start"
    try:
        yield {"url": f"http://127.0.0.1:{port}"}
    finally:
        server.should_exit = True
        thread.join(10)


_CHROMIUM_EXEC = "/opt/pw-browsers/chromium"


@pytest.fixture(scope="module")
def browser():
    launch_kwargs: dict = {"args": ["--no-sandbox", "--disable-setuid-sandbox"]}
    import os
    if os.path.exists(_CHROMIUM_EXEC):
        launch_kwargs["executable_path"] = _CHROMIUM_EXEC
    with sync_playwright() as pw:
        instance = pw.chromium.launch(**launch_kwargs)
        yield instance
        instance.close()


def _page(browser, ref_app, *, user_id: str, width: int = 1280):
    from app.auth import COOKIE_NAME, create_session_token

    page = browser.new_page(viewport={"width": width, "height": 900})
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


def _open_reference_workbook(page, ref_app, project_code_fragment: str) -> None:
    """Navigate from the library to a reference workbook."""
    page.goto(ref_app["url"] + "/library")
    page.wait_for_url("**/library")
    # Find the reference row / card and click View Reference
    page.locator(f'[data-testid*="open-"][data-testid*="{project_code_fragment}"]').first.click()
    page.wait_for_url("**/v2/workbook?project=**")
    page.locator("#panel-overview, #tab-overview").first.wait_for(state="attached", timeout=20_000)


def _find_reference_project_code(ref_app, template_source: str) -> str:
    """Return the project_code for a given template_source by querying the DB."""
    from app.persistence.projects_repository import get_reference_by_template_source
    rec = get_reference_by_template_source(template_source)
    assert rec is not None, f"Reference for {template_source} not found"
    return rec.project_code


# ---------------------------------------------------------------------------
# SOLAR_REFERENCE_PRERUN_BROWSER
# ---------------------------------------------------------------------------

def test_solar_reference_prerun_browser(ref_app, browser):
    """SOLAR_REFERENCE_PRERUN_BROWSER = PASS

    The Solar reference workbook must open showing CURRENT status (not NOT RUN)
    and populated KPIs at 1280px.
    """
    page = _page(browser, ref_app, user_id="solar-ref-browser-" + uuid.uuid4().hex[:6])
    try:
        pc = _find_reference_project_code(ref_app, "generic_solar_reference")
        page.goto(ref_app["url"] + f"/v2/workbook?project={pc}")
        page.locator("#tab-overview").click()
        page.locator("#panel-overview").wait_for(state="visible", timeout=20_000)

        # Must show CURRENT, not NOT RUN
        assert page.locator('[data-testid="overview-status-current"]').count() >= 1, \
            "Solar reference must show CURRENT status after canonical seeding"
        assert page.locator('[data-testid="overview-status-notrun"]').count() == 0, \
            "Solar reference must NOT show NOT RUN after canonical seeding"

        # KPI tiles must be populated
        irr_tile = page.locator('[data-testid="kpi-project-irr"]')
        assert irr_tile.count() >= 1
        irr_text = irr_tile.inner_text()
        assert irr_text.strip() not in ("—", "", "N/A"), \
            f"Solar reference project_irr tile must show a value; got: {irr_text!r}"

        _assert_no_horizontal_overflow(page)
    finally:
        page.close()


# ---------------------------------------------------------------------------
# WIND_REFERENCE_PRERUN_BROWSER
# ---------------------------------------------------------------------------

def test_wind_reference_prerun_browser(ref_app, browser):
    """WIND_REFERENCE_PRERUN_BROWSER = PASS

    The Wind reference workbook must open showing CURRENT status and populated
    KPIs at 1280px.
    """
    page = _page(browser, ref_app, user_id="wind-ref-browser-" + uuid.uuid4().hex[:6])
    try:
        pc = _find_reference_project_code(ref_app, "generic_wind_reference")
        page.goto(ref_app["url"] + f"/v2/workbook?project={pc}")
        page.locator("#tab-overview").click()
        page.locator("#panel-overview").wait_for(state="visible", timeout=20_000)

        assert page.locator('[data-testid="overview-status-current"]').count() >= 1, \
            "Wind reference must show CURRENT status after canonical seeding"
        assert page.locator('[data-testid="overview-status-notrun"]').count() == 0, \
            "Wind reference must NOT show NOT RUN after canonical seeding"

        irr_tile = page.locator('[data-testid="kpi-project-irr"]')
        assert irr_tile.count() >= 1
        irr_text = irr_tile.inner_text()
        assert irr_text.strip() not in ("—", "", "N/A"), \
            f"Wind reference project_irr tile must show a value; got: {irr_text!r}"

        _assert_no_horizontal_overflow(page)
    finally:
        page.close()


# ---------------------------------------------------------------------------
# DATA_CENTER_REFERENCE_PRERUN_BROWSER
# ---------------------------------------------------------------------------

def test_data_center_reference_prerun_browser(ref_app, browser):
    """DATA_CENTER_REFERENCE_PRERUN_BROWSER = PASS

    The Data Center reference workbook must open showing CURRENT status and
    populated KPIs at 1280px.
    """
    page = _page(browser, ref_app, user_id="dc-ref-browser-" + uuid.uuid4().hex[:6])
    try:
        pc = _find_reference_project_code(ref_app, "generic_data_center_reference")
        page.goto(ref_app["url"] + f"/v2/workbook?project={pc}")
        page.locator("#tab-overview").click()
        page.locator("#panel-overview").wait_for(state="visible", timeout=20_000)

        assert page.locator('[data-testid="overview-status-current"]').count() >= 1, \
            "DC reference must show CURRENT status after canonical seeding"
        assert page.locator('[data-testid="overview-status-notrun"]').count() == 0, \
            "DC reference must NOT show NOT RUN after canonical seeding"

        irr_tile = page.locator('[data-testid="kpi-project-irr"]')
        assert irr_tile.count() >= 1
        irr_text = irr_tile.inner_text()
        assert irr_text.strip() not in ("—", "", "N/A"), \
            f"DC reference project_irr tile must show a value; got: {irr_text!r}"

        _assert_no_horizontal_overflow(page)
    finally:
        page.close()


# ---------------------------------------------------------------------------
# REFERENCE_WORKING_COPY_BROWSER_SEPARATION
# ---------------------------------------------------------------------------

def test_reference_working_copy_browser_separation(ref_app, browser):
    """REFERENCE_WORKING_COPY_BROWSER_SEPARATION = PASS

    A working copy created from the Solar reference must open with NOT RUN
    status — it must NOT inherit the reference's canonical last-run.
    """
    page = _page(browser, ref_app, user_id="wc-sep-browser-" + uuid.uuid4().hex[:6])
    try:
        # Navigate to library → new project form → create Solar working copy
        page.goto(ref_app["url"] + "/library")
        page.wait_for_url("**/library")
        page.locator("a.fo-library-cta-new").click()
        page.wait_for_url("**/projects/new")
        page.locator('input[name="template_source"][value="generic_solar_reference"]').check()
        page.locator("#npm-project_name").fill("Solar WC Separation Test")
        page.locator("#npm-capacity_mw").fill("64")
        page.get_by_role("button", name="Create project").click()
        page.wait_for_url("**/v2/workbook?project=**", timeout=30_000)

        page.locator("#tab-overview").click()
        page.locator("#panel-overview").wait_for(state="visible", timeout=20_000)

        # Working copy must show the "no run" empty state — it must not
        # inherit the reference's canonical last-run.
        assert page.locator('[data-testid="overview-no-run-state"]').count() >= 1, \
            "Working copy must show overview-no-run-state (must not inherit reference last-run)"
        assert page.locator('[data-testid="overview-status-current"]').count() == 0, \
            "Working copy must NOT show CURRENT before user runs the engine"
    finally:
        page.close()


# ---------------------------------------------------------------------------
# REFERENCE_MOBILE_390_NO_OVERFLOW
# ---------------------------------------------------------------------------

def test_reference_mobile_390_no_overflow(ref_app, browser):
    """REFERENCE_MOBILE_390_NO_OVERFLOW = PASS

    At 390px viewport, the Solar reference workbook overview (with canonical
    last-run showing CURRENT) must have no horizontal overflow.
    """
    # Open at 1280px, wait for CURRENT, then resize to 390px and re-check.
    page = _page(browser, ref_app, user_id="mobile-390-" + uuid.uuid4().hex[:6], width=1280)
    try:
        pc = _find_reference_project_code(ref_app, "generic_solar_reference")
        page.goto(ref_app["url"] + f"/v2/workbook?project={pc}")
        page.locator("#tab-overview").click()
        page.locator("#panel-overview").wait_for(state="visible", timeout=20_000)
        # Confirm CURRENT before resizing
        page.locator('[data-testid="overview-status-current"]').wait_for(
            state="attached", timeout=10_000
        )
        # Resize to 390px and check no overflow
        page.set_viewport_size({"width": 390, "height": 844})
        page.locator("#tab-overview").click()
        page.locator("#panel-overview").wait_for(state="visible", timeout=10_000)
        _assert_no_horizontal_overflow(page)
    finally:
        page.close()
