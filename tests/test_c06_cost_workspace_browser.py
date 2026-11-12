"""C06 added-line profile acceptance: real Chromium, canonical Save/Run and synthetic local data."""
import os
from pathlib import Path
import pytest
from tests.test_workflow_c_browser_v1 import live_server, browser
from tests.model_react_rcm_support import rcm_react_flag
from tests.model_react_mvp_acceptance import session
from tests.model_react_ux_pr2a_acceptance import _profiles
from tests.model_react_wf06b_acceptance import _open_add, _costlines
from tests.model_react_wf1_browser_acceptance import run_canonical

@pytest.mark.parametrize('width', [1440, 390])
def test_added_active_line_profile_save_reload_run(live_server, browser, rcm_react_flag, width):
    context, page, record, errors = session(browser, live_server, f'c06-browser-{width}', 'solar')
    code = record.project_code
    def history():
        return context.request.get(f'{live_server}/v2/model-react/runs?project={code}').json()['runs']
    try:
        page.goto(f'{live_server}/v2/model-react/{code}#inputs/capex')
        page.wait_for_selector('[data-cost-grid="capex"] [data-saved-total]')
        manager = _open_add(page, 'capex', 'C.02')
        manager.get_by_label('Line label').fill('C06 added profile line')
        manager.get_by_label('Amount').fill('120')
        manager.locator('[data-cost-add="capex"]').click()
        page.wait_for_selector('[data-cost-line-commands="capex"] [role="status"]:has-text("verified in the fresh projection")', timeout=30000)
        payload = _costlines(context, live_server, code, 'capex')
        line = next(l for l in payload['lines'] if l['label'] == 'C06 added profile line')
        sub = line['sub_line_id']
        key = next(l['finco_display_code'] for l in payload['projection']['lines'] if l['sub_line_id'] == sub)
        prof = _profiles(context, live_server, code); months = prof['months']
        assert line['active'] and '.U' in key and key in {i['item_key'] for i in prof['items']}
        assert not {i['item_key'] for i in prof.get('excluded', [])} & {i['item_key'] for i in prof['items']}
        page.locator('[data-pr2b-toggle="desktop"]').click()
        page.locator(f'[data-pr2b-shape="{key}"]').select_option('EXPLICIT')
        page.locator(f'[data-pr2b-open="{sub}"]').click()
        ta = page.locator(f'[data-capex-explicit="{key}"]')
        for values in (['100']+['0']*(months-2), ['99']+['0']*(months-1)):
            ta.fill('\t'.join(values)); assert page.locator('[data-capex-save]').is_disabled()
        values = ['37.5']+['0']*(months-2)+['62.5']
        ta.fill('\t'.join(values)); assert page.locator('[data-capex-save]').is_enabled()
        assert page.locator(f'[data-pr2b-editor="{key}"] [data-capex-month-input]').count() == months
        # Saving the profile must leave this separately staged amount unpersisted.
        amount = page.locator(f'tr[data-line="{sub}"] input[data-c="1"]')
        amount.fill('121')
        prior_history = history(); posts=[]
        page.on('request', lambda r: posts.append(r.url) if r.method == 'POST' else None)
        page.locator('[data-capex-save]').click(); page.wait_for_selector('[data-capex-status="ok"]')
        expected = {'shape':'EXPLICIT','explicit':','.join(values),'milestone':''}
        assert _profiles(context, live_server, code)['saved']['rows'][key] == expected
        assert history() == prior_history
        assert len(posts) == 1 and '/spending-profiles/save' in posts[0]
        fresh = next(l for l in _costlines(context, live_server, code, 'capex')['lines'] if l['sub_line_id'] == sub)
        assert float(fresh['amount_keur']) == 120 and amount.input_value() == '121'
        amount.fill('120')
        page.reload(); page.wait_for_selector('[data-cost-grid="capex"] [data-saved-total]')
        assert _profiles(context, live_server, code)['saved']['rows'][key] == expected
        page.set_viewport_size({'width':width,'height':900})
        if width == 390:
            page.locator('[data-pr2b-toggle="mobile"]').click()
            dialog = page.locator('.ux-line-inspector[open]'); dialog.wait_for()
            dialog.locator('[aria-label="Choose line profile"]').select_option(sub)
            assert dialog.locator(f'[data-capex-month-input="{key}:1"]').is_enabled()
        else:
            page.locator('[data-pr2b-toggle="desktop"]').click()
            assert page.locator(f'[data-pr2b-shape="{key}"]').input_value() == 'EXPLICIT'
            page.locator(f'[data-pr2b-open="{sub}"]').click()
        assert page.evaluate('document.documentElement.scrollWidth-innerWidth') <= 1
        if folder := os.environ.get('C06_SCREENSHOT_DIR'):
            Path(folder).mkdir(parents=True, exist_ok=True)
            page.screenshot(path=str(Path(folder)/f'c06-profile-{width}.png'),full_page=True)
        run_canonical(context, live_server, code)
        assert len(history()) == len(prior_history)+1
        assert _profiles(context, live_server, code)['saved']['rows'][key] == expected
        # A retired profiled row must lose editing eligibility, keeping its saved profile intact.
        page.goto(f'{live_server}/v2/model-react/{code}#inputs/capex')
        page.set_viewport_size({'width':1440,'height':900})
        page.wait_for_selector('[data-cost-grid="capex"] [data-saved-total]')
        row = page.locator(f'tr[data-line="{sub}"]')
        row.locator('[data-row-menu]').click()
        row.locator('[role="menuitem"]').first.click()
        page.get_by_role('button', name='Deactivate line').last.click()
        page.wait_for_selector('[data-cost-line-commands="capex"] [role="status"]:has-text("deactivated and verified")', timeout=30000)
        after_retire = _profiles(context, live_server, code)
        assert key not in {i['item_key'] for i in after_retire['items']}
        assert after_retire['saved']['rows'][key] == expected
        page.reload(); page.wait_for_selector('[data-cost-grid="capex"] [data-saved-total]')
        page.locator('[data-pr2b-toggle="desktop"]').click()
        assert page.locator(f'[data-pr2b-shape="{key}"]:enabled').count() == 0
        assert not errors, errors
    finally:
        context.close()
