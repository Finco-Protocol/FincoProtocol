"""Actual Chromium agreement Save/Run/history with disposable canonical projects."""
import os
from pathlib import Path

import pytest

pytest.importorskip('playwright', reason='playwright not installed in this workflow')

from playwright.sync_api import expect
from tests.test_financing_f37_browser_v1 import live_server, browser, _project, USER  # noqa: F401
from tests.model_workspace_navigation import activate_destination
from tests.test_investor_f4_workspace import funded_agreement


@pytest.mark.parametrize('kind', ['solar', 'wind'])
def test_actual_editor_save_reload_run_history_and_responsive_layout(live_server, browser, kind):
    from app.auth import COOKIE_NAME, create_session_token
    from app.persistence.workspace_repository import get_workspace_state
    record = _project('generic_' + kind + '_reference', two_senior=False)
    doc = funded_agreement(get_workspace_state(USER, record.project_id))
    ctx = browser.new_context(viewport={'width': 1440, 'height': 1000}, accept_downloads=True)
    ctx.add_cookies([{'name': COOKIE_NAME, 'value': create_session_token(user_id=USER, username='admin'), 'url': live_server}])
    page = ctx.new_page()
    errors = []
    page.on('pageerror', lambda e: errors.append(str(e)))
    page.goto(f'{live_server}/v2/workbook?project={record.project_code}')
    with page.expect_response(lambda r: '/v2/workbook/financing/investor?' in r.url) as refreshed:
        activate_destination(page, 'tab-investor')
    refreshed.value.finished()
    page.locator('[data-testid=f4-agreement-panel] summary').click()
    root = page.locator('#f4-investor-workspace')
    expect(root.locator('.f4-agreement-form')).to_be_visible()
    page.wait_for_function('() => window.fincoF4EditorRegistered === true')
    root.locator('[name=agreement_id]').fill(doc['agreement_id'])
    for investor in doc['investors']:
        root.locator('[data-f4-add=investor]').click()
        row = root.locator('tr[data-f4-investor]').last
        for field in ('investor_id', 'ownership_fraction', 'commitment_keur'):
            value = investor[field] * 100 if field == 'ownership_fraction' else investor[field]
            row.locator(f'[data-f4-field={field}]').fill(str(value))
    for contribution in doc['contributions']:
        root.locator('[data-f4-add=contribution]').click()
        row = root.locator('tr[data-f4-contribution]').last
        for field, value in contribution.items():
            row.locator(f'[data-f4-field={field}]').fill(str(value))
    expect(root.locator('[data-f4-draft]')).to_have_attribute('data-draft', 'dirty')       # S7-07: unsaved edits are visible
    root.locator('button[value=save]').click()
    expect(root).to_have_attribute('data-state', 'STALE')
    expect(root.locator('[data-testid=f4-workflow-state]')).to_have_attribute('data-workflow', 'SAVED_NOT_RUN')   # saved, not yet in any Run
    expect(root.locator('[data-f4-draft]')).to_have_attribute('data-draft', 'clean')
    root.get_by_role('button', name='Reload agreement').click()
    expect(root.locator('tr[data-f4-investor]')).to_have_count(2)
    expect(root).to_have_attribute('data-state', 'STALE')
    with page.expect_response(lambda r: '/v2/workbook/run' in r.url and r.request.method == 'POST', timeout=60000) as response:
        page.locator('[data-testid=header-run-btn]').click()
    assert response.value.status == 200
    response.value.finished()
    assert 'No Run was committed' not in response.value.text(), response.value.text()
    from app.model_v2.investor_f4 import EVIDENCE_KEY
    assert EVIDENCE_KEY in get_workspace_state(USER, record.project_id).last_runtime_summary, response.value.text()
    expect(page.locator('[data-testid=f4-agreement-panel]')).to_have_attribute('open', '')
    root.get_by_role('button', name='Reload agreement').click()
    expect(root).to_have_attribute('data-state', 'CURRENT', timeout=30000)
    expect(root.locator('[data-testid=f4-workflow-state]')).to_have_attribute('data-workflow', 'INCORPORATED')   # recorded by the canonical Run
    expect(root.locator('[data-testid=f4-capital-accounts] tbody tr')).to_have_count(2)
    expect(root.locator('[data-testid=f4-run-binding]')).to_contain_text(doc['agreement_id'])
    with page.expect_download() as download:
        root.get_by_role('link', name='Export Run-bound investor workbook').click()
    assert download.value.suggested_filename == 'investor-waterfall.xlsx'
    for scheme, width in [('light', 1440), ('dark', 390)]:
        page.emulate_media(color_scheme=scheme)
        page.set_viewport_size({'width': width, 'height': 1000})
        assert page.evaluate('document.documentElement.scrollWidth - document.documentElement.clientWidth') <= 1
        directory = os.environ.get('F4_SCREENSHOT_DIR')
        if directory:
            Path(directory).mkdir(parents=True, exist_ok=True)
            page.screenshot(path=str(Path(directory) / f'{kind}-{scheme}-{width}.png'), full_page=True)
    page.set_viewport_size({'width': 1440, 'height': 1000})
    held = []

    def delay_old_read(route):
        response = route.fetch()
        held.append((route, response))

    page.route('**/v2/workbook/investor/agreement?*', delay_old_read, times=1)
    root.get_by_role('button', name='Reload agreement').click()
    for _ in range(100):
        if held:
            break
        page.wait_for_timeout(100)
    assert held, 'The old CURRENT response must be captured before the edit'
    root.locator('tr[data-f4-investor]').first.locator('[data-f4-field=ownership_fraction]').fill('80')
    root.locator('tr[data-f4-investor]').last.locator('[data-f4-field=ownership_fraction]').fill('20')
    root.locator('button[value=save]').click()
    expect(root).to_have_attribute('data-state', 'STALE')
    held[0][0].fulfill(response=held[0][1])
    expect(root).to_have_attribute('data-state', 'STALE')
    expect(root.locator('tr[data-f4-investor]').first.locator('[data-f4-field=ownership_fraction]')).to_have_value('80.0')
    history = root.locator('details').filter(has=page.locator('summary', has_text='Immutable investor Run History'))
    history.locator('summary').click()
    history.locator('a[hx-get*=history_id]').first.click()
    expect(root).to_have_attribute('data-state', 'HISTORICAL')
    expect(root.locator('.f4-agreement-form')).to_have_count(0)
    expect(root.locator('[data-testid=f4-capital-accounts] tbody tr')).to_have_count(2)
    assert not errors
    ctx.close()


def test_protected_investor_workspace_has_no_agreement_editor(live_server, browser):
    from app.auth import COOKIE_NAME, create_session_token
    from app.persistence.db import get_connection
    record = _project('generic_solar_reference', two_senior=False)
    conn = get_connection()
    conn.execute('UPDATE projects SET is_protected=1 WHERE project_id=?', (record.project_id,))
    conn.commit()
    conn.close()
    ctx = browser.new_context()
    ctx.add_cookies([{'name': COOKIE_NAME, 'value': create_session_token(user_id=USER, username='admin'), 'url': live_server}])
    page = ctx.new_page()
    page.goto(f'{live_server}/v2/workbook?project={record.project_code}')
    with page.expect_response(lambda r: '/v2/workbook/financing/investor?' in r.url) as response:
        activate_destination(page, 'tab-investor')
    response.value.finished()
    page.locator('[data-testid=f4-agreement-panel] summary').click()
    root = page.locator('#f4-investor-workspace')
    expect(root).to_contain_text('Read-only protected reference')
    expect(root.locator('.f4-agreement-form')).to_have_count(0)
    ctx.close()
