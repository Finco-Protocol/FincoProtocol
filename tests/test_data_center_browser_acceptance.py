"""True-browser acceptance for the Generic Data Center Reference V1.

Flow (spec S.14):
  Home → Model Library → Generic Data Center Reference → Create Working Copy
  → Data Center Workbook

Confirms Data Center labels, absence of renewable-only primary controls
(PPA / P50 / merchant), CAPEX/OPEX/Revenue visibility, a working Run with
visible returns, and no horizontal overflow at 1280 px and 390 px.

Section 8 markers:
  DC_SECOND_EDIT_AFTER_HTMX_SWAP        Second revenue field edit succeeds after HTMX DOM swap.
  DC_DRIVER_EDIT_PERSISTS_AFTER_RELOAD   service_price edit persists across full page reload.
  DC_DRIVER_EDIT_CHANGES_RUNTIME         Higher service_price raises KPIs on next engine run.
  DC_LAST_RUN_WORKING_COPY_SEPARATION    Revenue outputs preserved (stale) when inputs edited.

Section 9 markers:
  DC_BROWSER_VERTICAL_INTEGRITY_1280     At 1280px: DC sensitivity drivers, no renewable
                                         leakage in scenarios tab, actual gearing tiles
                                         visible after run, no overflow.
  DC_BROWSER_VERTICAL_INTEGRITY_390      At 390px: IT Capacity label, DC drivers accessible.
  DC_MOBILE_390_NO_OVERFLOW              No horizontal overflow at 390px viewport.
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


# ─────────────────────────────────────────────────────────────────────────────
# Shared helper: create a DC working copy from the library
# ─────────────────────────────────────────────────────────────────────────────

def _create_dc_working_copy(page, dc_app, name: str, capacity_mw: str = "20") -> str:
    """Navigate library → new project → DC working copy; return workbook URL."""
    page.goto(dc_app["url"] + "/")
    page.get_by_role("link", name="Model", exact=True).click()
    page.wait_for_url("**/library")
    page.locator("a.fo-library-cta-new").click()
    page.wait_for_url("**/projects/new")
    page.locator('input[name="template_source"][value="generic_data_center_reference"]').check()
    page.locator("#npm-project_name").fill(name)
    page.locator("#npm-capacity_mw").fill(capacity_mw)
    page.get_by_role("button", name="Create project").click()
    page.wait_for_url("**/v2/workbook?project=**")
    return page.url


# ─────────────────────────────────────────────────────────────────────────────
# DC_BROWSER_VERTICAL_INTEGRITY_1280  (Section 9)
# ─────────────────────────────────────────────────────────────────────────────

def test_DC_BROWSER_VERTICAL_INTEGRITY_1280(dc_app, browser):
    """DC_BROWSER_VERTICAL_INTEGRITY_1280 -- at 1280px:
    - Sensitivity tab shows DC-native drivers; renewable drivers absent.
    - Scenario tab renders no PPA/merchant input fields.
    - After Run, debt tab shows actual-senior and actual-gearing KPI tiles.
    - Max. gearing cap label (renamed from Gearing) present on debt tab.
    - No horizontal overflow.
    """
    page = _page(browser, dc_app, user_id="dc-vi1280-" + uuid.uuid4().hex[:8])
    try:
        _create_dc_working_copy(page, dc_app, "DC VI 1280")

        # Run the engine (needed so debt derivation evidence is available)
        page.locator("#tab-overview").click()
        page.locator("#panel-overview").wait_for(state="visible")
        page.locator('[data-testid="v2-run-btn"]').click()
        page.locator('[data-testid="overview-status-current"]').wait_for(
            state="attached", timeout=180_000
        )

        # Sensitivity tab: DC drivers present, renewable drivers absent
        page.locator("#tab-sensitivity").click()
        sensitivity_panel = page.locator("#panel-sensitivity")
        sensitivity_panel.wait_for(state="visible")
        assert sensitivity_panel.locator('option[value="service_price"]').count() >= 1, (
            "DC sensitivity must expose 'service_price' driver option"
        )
        assert sensitivity_panel.locator('option[value="dc_occupancy"]').count() >= 1, (
            "DC sensitivity must expose 'dc_occupancy' driver option"
        )
        assert sensitivity_panel.locator('option[value="tariff"]').count() == 0, (
            "Renewable tariff option must not appear on DC sensitivity tab"
        )
        assert sensitivity_panel.locator('option[value="p50_hours"]').count() == 0, (
            "P50 hours option must not appear on DC sensitivity tab"
        )

        # Scenario tab: no PPA/merchant fields
        page.locator("#tab-scenarios").click()
        scenario_panel = page.locator("#panel-scenarios")
        scenario_panel.wait_for(state="visible")
        assert scenario_panel.locator(
            '[data-field-id="revenue.ppa.base_tariff"]'
        ).count() == 0, "PPA tariff field must not render in DC scenario tab"

        # Debt tab: actual gearing + actual senior tiles after run
        page.locator("#tab-debt").click()
        debt_panel = page.locator("#panel-debt")
        debt_panel.wait_for(state="visible")
        actual_senior = debt_panel.locator('[data-testid="debt-kpi-actual-senior"]')
        actual_senior.wait_for(state="attached", timeout=15_000)
        assert actual_senior.is_visible(), "Actual Senior Debt tile must be visible after run"
        actual_gearing = debt_panel.locator('[data-testid="debt-kpi-actual-gearing"]')
        actual_gearing.wait_for(state="attached", timeout=15_000)
        assert actual_gearing.is_visible(), "Actual Gearing tile must be visible after run"
        debt_text = debt_panel.inner_text()
        assert "Max. gearing cap" in debt_text, (
            "Debt tab must show 'Max. gearing cap' label (input cap, not realized gearing)"
        )

        # No horizontal overflow at 1280px
        _assert_no_horizontal_overflow(page)

    finally:
        page.close()


# ─────────────────────────────────────────────────────────────────────────────
# DC_BROWSER_VERTICAL_INTEGRITY_390 / DC_MOBILE_390_NO_OVERFLOW  (Section 9)
# ─────────────────────────────────────────────────────────────────────────────

def test_DC_MOBILE_390_NO_OVERFLOW(dc_app, browser):
    """DC_BROWSER_VERTICAL_INTEGRITY_390 / DC_MOBILE_390_NO_OVERFLOW -- at 390px:
    IT Capacity / MW IT label visible, service_price field accessible, run
    button reachable, no horizontal overflow.
    """
    page = _page(browser, dc_app, user_id="dc-vi390-" + uuid.uuid4().hex[:8])
    page.set_viewport_size({"width": 390, "height": 844})
    try:
        _create_dc_working_copy(page, dc_app, "DC VI 390")

        # Inputs: IT Capacity label present at 390px
        page.locator("#tab-inputs").click()
        page.locator("#panel-inputs").wait_for(state="visible")
        inputs_text = page.locator("#panel-inputs").inner_text()
        assert "IT Capacity" in inputs_text or "MW IT" in inputs_text, (
            "IT Capacity / MW IT label must be visible on inputs tab at 390px"
        )
        _assert_no_horizontal_overflow(page)

        # Revenue: service_price field accessible at 390px
        page.locator("#tab-revenue").click()
        revenue_panel = page.locator("#panel-revenue")
        revenue_panel.locator(
            '[data-field-id="revenue.data_center.service_price"]'
        ).wait_for(state="attached", timeout=30_000)
        _assert_no_horizontal_overflow(page)

        # Overview: run button accessible at 390px
        page.locator("#tab-overview").click()
        page.locator("#panel-overview").wait_for(state="visible")
        assert page.locator('[data-testid="v2-run-btn"]').count() >= 1, (
            "Run button must be accessible at 390px"
        )
        _assert_no_horizontal_overflow(page)

    finally:
        page.close()


# ─────────────────────────────────────────────────────────────────────────────
# Section 8 -- Working Copy / HTMX / Reload markers
# ─────────────────────────────────────────────────────────────────────────────

def test_DC_HTMX_WORKING_COPY_WORKFLOW(dc_app, browser):
    """Section 8 -- HTMX working copy workflow.

    DC_SECOND_EDIT_AFTER_HTMX_SWAP:
        Edit service_price; after HTMX swap replaces revenue sheet, edit it
        again without stale-element error.

    DC_DRIVER_EDIT_PERSISTS_AFTER_RELOAD:
        service_price edited to a known value and saved; full page reload shows
        the same value.

    DC_DRIVER_EDIT_CHANGES_RUNTIME:
        Engine run at service_price=175 (default); edit to 195; second run
        changes the KPIs shown on the overview panel.

    DC_LAST_RUN_WORKING_COPY_SEPARATION:
        After a run (revenue-state-clean), edit service_price without running.
        Revenue sheet re-renders with revenue-state-stale -- last-run outputs
        preserved but flagged stale.
    """
    page = _page(browser, dc_app, user_id="dc-htmx-" + uuid.uuid4().hex[:8])
    try:
        _create_dc_working_copy(page, dc_app, "DC HTMX Workflow")

        # Initial run at default service_price=175 EUR/kW/month
        page.locator("#tab-overview").click()
        page.locator("#panel-overview").wait_for(state="visible")
        page.locator('[data-testid="v2-run-btn"]').click()
        page.locator('[data-testid="overview-status-current"]').wait_for(
            state="attached", timeout=180_000
        )
        kpi_irr_before = page.locator('[data-testid="kpi-project-irr"]').inner_text()

        # Navigate to revenue tab
        page.locator("#tab-revenue").click()
        revenue_panel = page.locator("#panel-revenue")
        revenue_panel.locator(
            '[data-field-id="revenue.data_center.service_price"]'
        ).wait_for(state="visible", timeout=30_000)

        # Revenue should be clean after the run
        assert revenue_panel.locator(
            '[data-testid="revenue-state-clean"]'
        ).count() >= 1, "Revenue state must be 'clean' immediately after a run"

        # DC_SECOND_EDIT_AFTER_HTMX_SWAP
        # First edit: 175 -> 180
        sp_input = page.locator(
            '[data-field-id="revenue.data_center.service_price"] input.v2-field-input'
        )
        sp_input.fill("180")
        with page.expect_response(
            lambda r: "/v2/workbook/update" in r.url and r.status == 200
        ):
            sp_input.dispatch_event("blur")

        # HTMX replaced the revenue sheet -- re-find the field in the new DOM
        sp_input2 = page.locator(
            '[data-field-id="revenue.data_center.service_price"] input.v2-field-input'
        )
        sp_input2.wait_for(state="attached", timeout=10_000)
        # Second edit: 180 -> 185 (must succeed without stale-element error)
        sp_input2.fill("185")
        with page.expect_response(
            lambda r: "/v2/workbook/update" in r.url and r.status == 200
        ):
            sp_input2.dispatch_event("blur")
        # DC_SECOND_EDIT_AFTER_HTMX_SWAP: reached without error

        # DC_DRIVER_EDIT_PERSISTS_AFTER_RELOAD
        sp_input3 = page.locator(
            '[data-field-id="revenue.data_center.service_price"] input.v2-field-input'
        )
        sp_input3.wait_for(state="attached", timeout=10_000)
        sp_input3.fill("195")
        with page.expect_response(
            lambda r: "/v2/workbook/update" in r.url and r.status == 200
        ):
            sp_input3.dispatch_event("blur")

        current_url = page.url
        page.reload()
        page.wait_for_url(current_url)
        page.locator("#tab-revenue").click()
        sp_after_reload = page.locator(
            '[data-field-id="revenue.data_center.service_price"] input.v2-field-input'
        )
        sp_after_reload.wait_for(state="attached", timeout=30_000)
        value_after_reload = sp_after_reload.input_value()
        assert abs(float(value_after_reload) - 195.0) < 0.5, (
            f"service_price must persist as 195 after reload, got {value_after_reload!r}"
        )
        # DC_DRIVER_EDIT_PERSISTS_AFTER_RELOAD: value survived reload

        # DC_LAST_RUN_WORKING_COPY_SEPARATION
        # After editing post-run, revenue shows stale warning (last-run data preserved)
        revenue_panel2 = page.locator("#panel-revenue")
        stale_indicator = revenue_panel2.locator('[data-testid="revenue-state-stale"]')
        stale_indicator.wait_for(state="attached", timeout=10_000)
        assert stale_indicator.is_visible(), (
            "revenue-state-stale must be visible after editing service_price post-run"
        )
        stale_notice = revenue_panel2.locator('[data-testid="revenue-stale-notice"]')
        assert stale_notice.count() >= 1 and "stale" in stale_notice.inner_text().lower(), (
            "Revenue stale notice must warn that inputs changed"
        )
        # DC_LAST_RUN_WORKING_COPY_SEPARATION: last-run data preserved but stale

        # DC_DRIVER_EDIT_CHANGES_RUNTIME
        # Run again with service_price=195 (vs base 175) -- KPIs must differ
        page.locator("#tab-overview").click()
        page.locator("#panel-overview").wait_for(state="visible")
        page.locator('[data-testid="v2-run-btn"]').click()
        page.locator('[data-testid="overview-status-current"]').wait_for(
            state="attached", timeout=180_000
        )
        kpi_irr_after = page.locator('[data-testid="kpi-project-irr"]').inner_text()
        assert kpi_irr_before != kpi_irr_after, (
            f"Project IRR must change when service_price changes from 175 to 195.\n"
            f"  Before (175): {kpi_irr_before!r}\n  After (195):  {kpi_irr_after!r}"
        )
        # DC_DRIVER_EDIT_CHANGES_RUNTIME: different KPIs confirmed

        _assert_no_horizontal_overflow(page)

    finally:
        page.close()
