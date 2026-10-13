"""Real Chromium checks the existing release-closed Junior proposal workflow."""
import json
import os
from pathlib import Path

import pytest

pytest.importorskip("playwright", reason="playwright not installed in this workflow")
from playwright.sync_api import expect  # noqa: E402
from tests.test_capital_stack_workspace_browser_v1 import live_server, browser, _session, _ws  # noqa: E402,F401
from tests.test_financing_f3_junior_workspace import working_case, state  # noqa: E402


@pytest.mark.parametrize("kind", ["solar", "wind"])
def test_candidate_readonly_policy_disabled_activation_and_real_senior_proposal_save(live_server, browser, kind):
    from app.workbook import multisenior_config as config, junior_debt_config
    from app.workbook.registry import WORKBOOK
    from app.workbook.update_service import WorkbookUpdateService
    uid = "f35b-browser-" + kind
    record, context, page, errors = _session(live_server, browser, uid, "generic_" + kind + "_reference")
    try:
        candidate = working_case(_ws(uid, record))
        proposal = json.loads(state(candidate))
        proposal["scopes"]["base"]["activation"] = None
        WorkbookUpdateService.apply_draft_update(ws=_ws(uid, record), project_record=record,
            field_id=config.FIELD_ID, raw_value=json.dumps(proposal), workbook_version=WORKBOOK.version,
            content_hash=page.locator("[name=content_hash]").first.input_value())
        page.reload()
        expect(page.locator("[data-f3-activate]")).to_be_disabled()
        assert not page.locator("[data-f3-activate]").is_checked()
        expected_junior = candidate.financing_collection.instruments[1].commitment_keur
        expect(page.locator('[data-testid="cs-working-junior"]')).to_contain_text(f"{expected_junior:,.2f} kEUR")
        expect(page.locator('[data-testid="cs-junior-policy"]')).to_contain_text("production activation closed")
        readonly = page.locator("[data-cs-readonly-instrument]")
        assert readonly.count() == 1 and readonly.locator("input, select, textarea").count() == 0
        readonly.locator("[data-cs-expand]").click()
        expect(readonly.locator("[data-cs-detail]")).to_be_visible()
        expect(readonly).to_contain_text("Senior first")
        original_junior = json.loads(_ws(uid, record).draft_snapshot[config.SNAPSHOT_KEY])["scopes"]["base"]["proposal"]["instruments"][1]
        rate = page.locator('[data-f3="rate_pct"]').first
        rate.fill("4.25")
        page.locator("[data-f3-save]").click()
        expect(page.locator('[data-f3="rate_pct"]').first).to_have_value("4.25")
        expect(page.locator('[data-testid="cs-stack-status"]')).to_have_text("SAVED PROPOSAL")
        after = _ws(uid, record)
        saved = json.loads(after.draft_snapshot[config.SNAPSHOT_KEY])["scopes"]["base"]
        assert saved["activation"] is None and saved["proposal"]["instruments"][1] == original_junior
        assert after.dirty and not after.last_runtime_summary
        for width, scheme in ((1440, "light"), (390, "dark")):
            page.set_viewport_size({"width": width, "height": 950})
            page.emulate_media(color_scheme=scheme)
            assert page.evaluate("document.documentElement.scrollWidth <= innerWidth")
            output = os.environ.get("F35B_SCREENSHOT_DIR")
            if output:
                folder = Path(output)
                folder.mkdir(parents=True, exist_ok=True)
                page.screenshot(path=str(folder / f"{kind}-{scheme}-{width}.png"))
        assert junior_debt_config.ACTIVATION_ENABLED is False
        assert not errors
    finally:
        context.close()
