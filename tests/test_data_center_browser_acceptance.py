"""True-browser acceptance for the Generic Data Center Reference V1.

Flow (spec S.14):
  Home → Model Library → Generic Data Center Reference → Create Working Copy
  → Data Center Workbook

Confirms Data Center labels, absence of renewable-only primary controls
(PPA / P50 / merchant), CAPEX/OPEX/Revenue visibility, a working Run with
visible returns, and no horizontal overflow at 1280 px and 390 px.
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
def dc_app(tmp_path_factory):
    """Live application with isolated persistence."""
    from app.persistence import db

    db.DB_PATH = str(tmp_path_factory.mktemp("dc-browser") / "finco.db")

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
    assert server.started, "Data Center browser fixture server did not start"
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


def _page(browser, dc_app, *, user_id: str):
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


def test_data_center_reference_browser_acceptance(dc_app, browser):
    page = _page(browser, dc_app, user_id="dc-browser-" + uuid.uuid4().hex[:8])
    try:
        # ── Home → Model Library ────────────────────────────────────────
        page.goto(dc_app["url"] + "/")
        page.get_by_role("link", name="Model", exact=True).click()
        page.wait_for_url("**/library")
        assert page.get_by_text("Generic Data Center Reference").count() >= 1

        # ── Create Working Copy from the Data Center reference ─────────
        page.locator("a.fo-library-cta-new").click()
        page.wait_for_url("**/projects/new")
        import os as _os
        if _os.environ.get("DC_BROWSER_DEBUG_DUMP"):
            with open(_os.environ["DC_BROWSER_DEBUG_DUMP"], "w", encoding="utf-8") as fh:
                fh.write(page.url + "\n" + page.content())
        page.locator('input[name="template_source"][value="generic_data_center_reference"]').check()
        page.locator("#npm-project_name").fill("DC Browser Acceptance")
        page.locator("#npm-capacity_mw").fill("25")
        page.get_by_role("button", name="Create project").click()
        page.wait_for_url("**/v2/workbook?project=**")

        # ── Data Center terminology ─────────────────────────────────────
        assert page.locator(".v2-toolbar-wc-badge").inner_text().lower() == "working copy"

        # Renewable-only controls must not appear as primary inputs, and the
        # capacity control carries the Data Center IT-load label.
        page.locator("#tab-inputs").click()
        page.locator("#panel-inputs").wait_for(state="visible")
        inputs_panel = page.locator("#panel-inputs")
        assert inputs_panel.locator(
            '[data-field-id="project_setup.technical.p50_hours"]'
        ).count() == 0
        capacity_row = inputs_panel.locator(
            '[data-field-id="project_setup.technical.capacity_mw"]'
        )
        assert capacity_row.count() == 1
        assert "IT Capacity" in capacity_row.inner_text()

        # ── Revenue sheet: DC drivers visible, PPA/merchant hidden ─────
        page.locator("#tab-revenue").click()
        revenue_panel = page.locator("#panel-revenue")
        revenue_panel.locator('[data-field-id="revenue.data_center.service_price"]').wait_for(
            state="visible", timeout=30_000
        )
        assert revenue_panel.locator('[data-field-id="revenue.data_center.pue"]').count() == 1
        assert revenue_panel.locator('[data-field-id="revenue.data_center.occupancy_y1"]').count() == 1
        assert revenue_panel.locator('[data-field-id="revenue.ppa.base_tariff"]').count() == 0
        assert revenue_panel.locator('[data-field-id="revenue.merchant.price_curve_json"]').count() == 0
        revenue_panel.locator('[data-testid="dc-revenue-reconciliation"]').wait_for(
            state="visible", timeout=30_000
        )

        # ── CAPEX / OPEX sheets visible with editable working-copy rows ─
        page.locator("#tab-capex").click()
        page.locator("#panel-capex").wait_for(state="visible")
        page.locator('#panel-capex [data-testid="capex-summary"], #panel-capex').first.wait_for(
            state="attached", timeout=30_000
        )
        capex_panel = page.locator("#panel-capex")
        assert "Total CAPEX" in capex_panel.inner_text()
        # Data Center detail taxonomy is present in the DOM (UPS child).
        assert capex_panel.locator("text=UPS and Electrical Distribution").count() >= 1

        page.locator("#tab-opex").click()
        page.locator("#panel-opex").wait_for(state="visible")
        opex_panel = page.locator("#panel-opex")
        opex_panel.locator('text=Power Expenses').first.wait_for(
            state="attached", timeout=30_000
        )
        opex_text = opex_panel.inner_text()
        assert "Power Expenses" in opex_text
        # B.08 is derived for Data Center: the scalar override form is gone.
        assert opex_panel.locator(
            'form input[name="field_id"][value="opex.power_expenses"]'
        ).count() == 0

        # ── Run works and returns are visible ───────────────────────────
        page.locator("#tab-overview").click()
        page.locator("#panel-overview").wait_for(state="visible")
        page.locator('[data-testid="v2-run-btn"]').click()
        page.locator('[data-testid="overview-status-current"]').wait_for(
            state="attached", timeout=180_000
        )
        page.locator("#tab-returns").click()
        page.locator("#panel-returns").wait_for(state="visible")
        assert page.locator("#panel-returns").inner_text() != ""

        # ── No horizontal overflow at 1280 px ───────────────────────────
        _assert_no_horizontal_overflow(page)

        # ── No horizontal overflow at 390 px ────────────────────────────
        page.set_viewport_size({"width": 390, "height": 844})
        page.locator("#tab-overview").click()
        page.locator("#panel-overview").wait_for(state="visible")
        _assert_no_horizontal_overflow(page)
    finally:
        page.close()
