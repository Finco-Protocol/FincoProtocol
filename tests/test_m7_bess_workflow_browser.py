"""Actual integrated Model Save/Run in Chromium, not the operating preview."""
import os
from pathlib import Path
import pytest

pytest.importorskip('playwright', reason='playwright not installed in this workflow')
from playwright.sync_api import sync_playwright, expect
from tests.test_m7_bess_workflow import env, storage  # noqa: F401
from tests.test_m7_bess_candidate_browser import live, enabled  # noqa: F401
from tests.model_workspace_navigation import activate_destination


@pytest.mark.parametrize('theme,width', [('light', 1440), ('dark', 390)])
def test_integrated_save_run_and_stale_reopen(env, storage, live, theme, width):
    from app.auth import COOKIE_NAME, create_session_token
    from app.persistence.workspace_repository import get_workspace_state
    with sync_playwright() as pw:
        browser = pw.chromium.launch()
        ctx = browser.new_context(viewport={'width': width, 'height': 1000}, color_scheme=theme)
        ctx.add_cookies([{'name': COOKIE_NAME, 'value': create_session_token(user_id='decision-user', username='admin'), 'url': live}])
        page = ctx.new_page()
        errors = []
        page.on('pageerror', lambda e: errors.append(str(e)))
        page.goto(live + '/v2/workbook?project=' + storage.project_code)
        activate_destination(page, 'tab-project-setup')
        form = page.locator('[data-m7-financial-form]')
        expect(form).to_be_visible()
        expect(form.locator('[data-m7-save]')).to_be_enabled()
        form.locator('[data-m7-variable-om]').fill('1')
        form.locator('[data-m7-save]').click()
        page.wait_for_load_state('networkidle')
        page.locator('[data-testid="v2-run-btn"]').click()
        expect(page.locator('[data-testid=toolbar-runtime-state]')).to_have_text('Current', timeout=45000)
        ws = get_workspace_state('decision-user', storage.project_id)
        assert ws.last_runtime_summary.get('bess_operating_audit') and not ws.dirty
        activate_destination(page, 'tab-project-setup')
        expect(page.locator('[data-testid="bess-run-evidence"]')).to_be_visible()
        page.locator('[data-m7-point="20"] [data-m7-point-field="sell_price_eur_mwh"]').fill('120')
        page.locator('[data-m7-save]').click()
        page.wait_for_load_state('networkidle')
        page.reload()
        assert get_workspace_state('decision-user', storage.project_id).dirty
        activate_destination(page, 'tab-project-setup')
        expect(page.locator('[data-m7-point="20"] [data-m7-point-field="sell_price_eur_mwh"]')).to_have_value('120')
        assert page.evaluate('document.documentElement.scrollWidth - document.documentElement.clientWidth') <= 1
        output = os.environ.get('M7_SCREENSHOT_DIR')
        if output:
            Path(output).mkdir(parents=True, exist_ok=True)
            page.screenshot(path=str(Path(output) / f'bess-integrated-{theme}-{width}.png'), full_page=True)
        assert not errors
        ctx.close(); browser.close()
