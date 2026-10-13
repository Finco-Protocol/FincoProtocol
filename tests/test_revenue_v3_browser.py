"""Real Chromium acceptance of the release-closed candidate in isolated storage."""
import json
from pathlib import Path
import uuid

import pytest

pytest.importorskip("playwright", reason="playwright not installed in this workflow")

from tests.test_model_golden_flows_browser import golden_app, browser, _page
from tests.test_wf07_revenue_browser import _click_tab, _populate_structured_editor
from tests.test_revenue_v3_products import candidate
from tests.revenue_v3_cases import book


@pytest.mark.parametrize("kind", ["solar", "wind"])
def test_real_product_editor_save_reload_scenario_run(candidate, golden_app, browser, kind):
    from app.services.reference_seed_service import create_reference_seeded_project
    from app.persistence.workspace_repository import get_workspace_state
    from app.workbook.service import WorkbookService
    owner = "products-browser-" + uuid.uuid4().hex[:8]
    record = create_reference_seeded_project(user_id=owner, requested_name="Contracted products " + kind,
        template_source="generic_" + kind + "_reference", capacity_mw=16)
    ws = get_workspace_state(owner, record.project_id)
    raw, _ = book(WorkbookService.build_draft_input_set_from_workspace(ws).to_projectinputs(), kind)
    page = _page(browser, golden_app, user_id=owner)
    errors = []
    page.on("pageerror", lambda error: errors.append(str(error)))
    url = golden_app["url"] + "/v2/workbook?project=" + record.project_code
    try:
        page.goto(url)
        _click_tab(page, "tab-revenue", "panel-revenue")
        _populate_structured_editor(page, raw)
        form = page.locator('[data-testid="revenue-contracts-form"]')
        for product in raw["products"]:
            form.locator('[data-product-type]').select_option(product["type"])
            form.locator('[data-product-add]').click()
            row = form.locator('[data-product-row]').last
            for key, value in product.items():
                field = row.locator('[data-product-field="' + key + '"]')
                if not field.count():
                    continue
                if field.evaluate("el => el.tagName") == "SELECT":
                    field.select_option(value)
                else:
                    if key.endswith('_factor') or key == 'indexation_rate':
                        value *= 100
                    field.fill(str(value))
            row.get_by_role("button", name="Use canonical periods", exact=True).click()
            if product["type"] == "rec":
                row.locator('[data-product-periods]').evaluate('el => el.open = true')
                points = row.locator('[data-product-field="certified_mwh"]')
                assert points.count() == len(product["periods"])
                for i, point in enumerate(product["periods"]):
                    points.nth(i).fill(str(point["certified_mwh"]))
        rights = form.locator('[data-product-rights]')
        rights.locator('..').evaluate("el => el.open = true")
        for right in raw["environmental_rights"]:
            rights.get_by_role("button", name="+ Attribute right", exact=True).click()
            grid = rights.locator('.rc-product-fields').last
            grid.locator('[data-product-field="energy_stream_id"]').fill(right["energy_stream_id"])
            grid.locator('[data-product-field="status"]').select_option(right["status"])
            grid.locator('[data-product-field="source_ref"]').fill(right["source_ref"])
        calls_before = len(golden_app["calls"])
        form.get_by_role("button", name="Save contracts", exact=True).click()
        page.wait_for_function("() => JSON.parse(document.getElementById('revenue-contracts-json')?.value || '{}').version === 3")
        assert json.loads(page.locator('#revenue-contracts-json').input_value()) == raw
        assert len(golden_app["calls"]) == calls_before
        page.reload()
        _click_tab(page, "tab-revenue", "panel-revenue")
        assert page.locator('[data-product-row]').count() == 3
        assert json.loads(page.locator('#revenue-contracts-json').input_value()) == raw
        page.locator('[data-testid="v2-run-btn"]').click()
        page.locator('[data-testid="overview-status-current"]').wait_for(state="attached", timeout=180_000)
        assert len(golden_app["calls"]) == calls_before + 1
        _click_tab(page, "tab-revenue", "panel-revenue")
        assert page.locator('[data-testid="revenue-products-audit"]').count() == 1
        _click_tab(page, "tab-scenarios", "panel-scenarios")
        page.locator('.v2-scenario-create-form input[name="scenario_name"]').fill("Availability alternative")
        page.locator('.v2-scenario-create-form button[type="submit"]').click()
        page.get_by_text("Availability alternative", exact=True).first.wait_for()
        _click_tab(page, "tab-revenue", "panel-revenue")
        page.locator('[data-product-row]').first.locator('[data-product-field="price_eur"]').fill('25')
        page.get_by_role("button", name="Save contracts", exact=True).click()
        page.get_by_role("button", name="Restore Base contracts", exact=True).wait_for()
        page.locator('[data-testid="v2-run-btn"]').click()
        page.locator('[data-testid="overview-status-current"]').wait_for(state="attached", timeout=180_000)
        assert len(golden_app["calls"]) == calls_before + 2
        page.wait_for_function("() => !document.querySelector('[data-testid=\"v2-run-btn\"]')?.disabled")
        _click_tab(page, "tab-revenue", "panel-revenue")
        evidence = Path(__file__).resolve().parents[2] / "m2_revenue_v3_evidence"
        evidence.mkdir(exist_ok=True)
        page.locator('[data-product-row]').first.locator('summary').first.scroll_into_view_if_needed()
        page.screenshot(path=str(evidence / (kind + '-desktop.png')))
        page.set_viewport_size({"width":390, "height":844})
        page.locator('[data-product-row]').first.locator('summary').first.scroll_into_view_if_needed()
        page.screenshot(path=str(evidence / (kind + '-narrow.png')))
        assert page.locator('.rc-products').evaluate('el => el.getBoundingClientRect().right <= innerWidth')
        assert not errors, errors
    finally:
        page.close()
