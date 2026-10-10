"""Authenticated real-browser contract Save / scenario Save / canonical Run."""
import json
from pathlib import Path
import uuid

import pytest

from tests.test_model_golden_flows_browser import golden_app, browser, _page, _click_tab
from tests.test_wf07_revenue_multistream import contracts


@pytest.mark.parametrize("kind", ["solar", "wind"])
def test_authenticated_contract_save_scenario_run_and_narrow_render(golden_app, browser, kind):
    from app.services.reference_seed_service import create_reference_seeded_project
    from app.persistence.workspace_repository import get_workspace_state
    from app.workbook.service import WorkbookService
    from app.persistence.scenarios_repository import list_scenarios
    owner = "wf07-browser-" + uuid.uuid4().hex[:8]
    record = create_reference_seeded_project(user_id=owner, requested_name="Revenue contracts " + kind,
        template_source="generic_" + kind + "_reference", capacity_mw=16)
    pi = WorkbookService.build_draft_input_set_from_workspace(get_workspace_state(owner, record.project_id)).to_projectinputs()
    payload = contracts(pi, kind, price=95, merchant_price=90, strike=100)
    page = _page(browser, golden_app, user_id=owner)
    errors = []
    page.on("pageerror", lambda error: errors.append(str(error)))
    page.goto(golden_app["url"] + "/v2/workbook?project=" + record.project_code)
    _click_tab(page, "tab-revenue", "panel-revenue")
    page.locator("#revenue-contracts-json").fill(json.dumps(payload, indent=2))
    page.get_by_role("button", name="Save contracts", exact=True).click()
    page.locator("table[aria-label='Saved revenue contracts']").wait_for(timeout=30_000)
    assert json.loads(page.locator("#revenue-contracts-json").input_value()) == payload
    page.locator('[data-testid="v2-run-btn"]').click()
    page.locator('[data-testid="overview-status-current"]').wait_for(state="attached", timeout=180_000)
    before = get_workspace_state(owner, record.project_id).last_runtime_summary["total_revenue_keur"]
    _click_tab(page, "tab-scenarios", "panel-scenarios")
    page.locator('.v2-scenario-create-form input[name="scenario_name"]').fill("Contract alternative")
    page.locator(".v2-scenario-create-form").get_by_role("button", name="Create").click()
    page.get_by_text("Contract alternative", exact=True).first.wait_for(timeout=30_000)
    scenario = next(s for s in list_scenarios(owner, record.project_id) if not s.is_base_case)
    assert get_workspace_state(owner, record.project_id).active_scenario_id == scenario.scenario_id
    _click_tab(page, "tab-revenue", "panel-revenue")
    assert "Contract alternative" in page.locator('[data-testid="revenue-contracts"]').inner_text()
    payload["streams"][0]["price_eur_mwh"] = 105
    page.locator("#revenue-contracts-json").fill(json.dumps(payload, indent=2))
    page.get_by_role("button", name="Save contracts", exact=True).click()
    page.get_by_role("button", name="Restore Base contracts", exact=True).wait_for(timeout=30_000)
    page.locator('[data-testid="v2-run-btn"]').click()
    page.locator('[data-testid="overview-status-current"]').wait_for(state="attached", timeout=180_000)
    _click_tab(page, "tab-revenue", "panel-revenue")
    assert get_workspace_state(owner, record.project_id).last_runtime_summary["total_revenue_keur"] > before
    assert page.locator('[data-testid="revenue-contracts-audit"]').count() == 1
    evidence = Path(__file__).resolve().parents[1] / "reports" / "wf07_validation"
    evidence.mkdir(parents=True, exist_ok=True)
    page.screenshot(path=str(evidence / (kind + "-contracts-desktop.png")), full_page=True)
    page.set_viewport_size({"width": 390, "height": 844})
    page.screenshot(path=str(evidence / (kind + "-contracts-narrow.png")), full_page=True)
    assert page.locator("#revenue-contracts-json").evaluate("el => el.getBoundingClientRect().right <= innerWidth")
    assert not errors, errors
    page.close()
