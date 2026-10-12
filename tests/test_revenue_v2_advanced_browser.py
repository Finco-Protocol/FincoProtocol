"""Real-browser V2 scheduled contract Save/reload and read-only preview UI."""
import json
from pathlib import Path
import uuid

import pytest

from tests.test_model_golden_flows_browser import golden_app, browser, _page, _click_tab


@pytest.mark.parametrize("kind", ["solar", "wind"])
def test_price_curve_editor_real_save_reload_and_mobile(golden_app, browser, kind):
    from app.services.reference_seed_service import create_reference_seeded_project
    from app.persistence.workspace_repository import get_workspace_state
    from app.workbook.service import WorkbookService
    from financial_engine.adapters.project_inputs import from_project_inputs
    from financial_engine.orchestrator import _build_period_engine

    owner = "advanced-curve-browser-" + uuid.uuid4().hex[:8]
    record = create_reference_seeded_project(
        user_id=owner, requested_name="Synthetic Price Curves " + kind,
        template_source="generic_" + kind + "_reference", capacity_mw=16)
    ws = get_workspace_state(owner, record.project_id)
    pi = WorkbookService.build_draft_input_set_from_workspace(ws).to_projectinputs()
    op = [p for p in _build_period_engine(from_project_inputs(pi)).periods() if p.is_operation]
    assert len(op) >= 3
    points = "\n".join(p.start_date.isoformat() + "\t" + ("55" if i < 2 else "47")
                       for i,p in enumerate(op))
    page = _page(browser, golden_app, user_id=owner)
    errors = []
    page.on("pageerror", lambda error: errors.append(str(error)))
    page.goto(golden_app["url"] + "/v2/workbook?project=" + record.project_code)
    _click_tab(page, "tab-revenue", "panel-revenue")
    form = page.locator('[data-testid="revenue-contracts-form"]')
    form.locator('[data-revenue-add-type]').select_option("scheduled_ppa")
    form.locator('[data-revenue-add]').click()
    ppa = form.locator('[data-revenue-row]').first
    ppa.locator('[data-field="id"]').fill("price-curve-ppa")
    ppa.locator('[data-field="start_date"]').fill(op[0].start_date.isoformat())
    ppa.locator('[data-field="end_date"]').fill(op[-1].end_date.isoformat())
    ppa.locator('[data-field="volume_share"]').fill("60")
    ppa.locator('[data-field="source_ref"]').fill("synthetic-signed-schedule")
    ppa.locator("button[aria-label^='Edit price points']").click()
    panel = form.locator(".rc-curve-editor")
    assert panel.is_visible()
    panel.locator("textarea").fill(points)
    panel.get_by_role("button", name="Replace curve with pasted points").click()
    # The editor rerenders only this row; one canonical Save author remains.
    form.locator('[data-revenue-add-type]').select_option("residual_merchant")
    form.locator('[data-revenue-add]').click()
    merchant = form.locator('[data-revenue-row]').last
    merchant.locator('[data-field="id"]').fill("residual-market")
    merchant.locator('[data-field="start_date"]').fill(op[0].start_date.isoformat())
    merchant.locator('[data-field="end_date"]').fill(op[-1].end_date.isoformat())
    merchant.locator('[data-field="price_eur_mwh"]').fill("75")
    merchant.locator('[data-field="source_ref"]').fill("synthetic-reference-market")
    form.get_by_role("button", name="Save contracts").click()
    form = page.locator('[data-testid="revenue-contracts-form"]')
    form.locator('[data-revenue-source]').wait_for(timeout=30000)
    saved = json.loads(form.locator('[data-revenue-source]').input_value())
    assert saved["version"] == 2
    assert saved["streams"][0]["id"] == "price-curve-ppa"
    assert len(saved["streams"][0]["price_curve"]) == len(op)
    assert saved["streams"][0]["price_curve"][2]["price_eur_mwh"] == 47
    assert form.locator('[data-revenue-save]').is_disabled()
    page.reload()
    _click_tab(page, "tab-revenue", "panel-revenue")
    form = page.locator('[data-testid="revenue-contracts-form"]')
    assert json.loads(form.locator('[data-revenue-source]').input_value()) == saved
    evidence = Path(__file__).resolve().parents[1] / "reports" / "revenue_v2_advanced"
    evidence.mkdir(parents=True, exist_ok=True)
    page.screenshot(path=str(evidence / (kind + "-curve-desktop.png")), full_page=True)
    page.set_viewport_size({"width": 390, "height": 844})
    page.screenshot(path=str(evidence / (kind + "-curve-mobile.png")), full_page=True)
    assert page.locator(".rc-scroll").first.evaluate(
        "el => el.getBoundingClientRect().right <= innerWidth")
    assert not errors, errors
    page.close()
