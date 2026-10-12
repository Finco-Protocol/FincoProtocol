"""F3.8 authenticated Chromium, real committed Runs and existing workbook panels."""
import os
from pathlib import Path

import pytest

from tests.test_financing_f37_browser_v1 import live_server, browser, _project, USER  # noqa: F401
from playwright.sync_api import expect  # noqa: E402
from tests.model_workspace_navigation import activate_destination


@pytest.mark.parametrize('kind', ['solar', 'wind'])
def test_trace_opens_in_existing_output_tax_returns_and_mobile(live_server, browser, kind):
    from app.auth import COOKIE_NAME, create_session_token
    record = _project('generic_' + kind + '_reference', two_senior=True)
    for scheme, width in [('light', 1440), ('dark', 390)]:
        ctx = browser.new_context(viewport={'width': width, 'height': 1000}, color_scheme=scheme)
        ctx.add_cookies([{'name': COOKIE_NAME, 'value': create_session_token(user_id=USER, username='admin'), 'url': live_server}])
        page = ctx.new_page()
        errors = []
        page.on('pageerror', lambda e: errors.append(str(e)))
        page.goto(f'{live_server}/v2/workbook?project={record.project_code}')
        activate_destination(page, 'tab-outputs')
        page.locator('#v2-sheet-outputs [data-testid=financing-trace-loader] summary').click()
        trace = page.locator('#v2-sheet-outputs [data-testid=financing-trace]')
        expect(trace).to_have_attribute('data-state', 'CURRENT')
        expect(trace.locator('[data-testid=f38-facility]')).to_have_count(2)
        expect(trace.locator('[data-testid=f38-status]')).to_have_attribute('data-status', 'RECONCILED')
        trace.locator('[data-testid=f38-facility]').first.locator('summary').click()
        expect(trace.locator('[data-testid=f38-facility-periods]').first).to_be_visible()
        assert trace.locator('table').count() == trace.locator('caption').count()
        assert page.evaluate('document.documentElement.scrollWidth - document.documentElement.clientWidth') <= 1
        directory = os.environ.get('F38_SCREENSHOT_DIR')
        if directory:
            Path(directory).mkdir(parents=True, exist_ok=True)
            page.screenshot(path=str(Path(directory) / f'{kind}-{scheme}-{width}.png'), full_page=True)
        for sheet in ('tax', 'returns'):
            activate_destination(page, 'tab-' + sheet)
            loader = page.locator(f'#v2-sheet-{sheet} [data-testid=financing-trace-loader]')
            loader.locator('summary').click()
            expect(loader.locator('[data-testid=financing-trace]')).to_have_attribute('data-state', 'CURRENT')
            detail = loader.locator('details').filter(has=page.locator('summary', has_text=(
                'Tax evidence and attribution limits' if sheet == 'tax' else 'Cash flow and sponsor evidence')))
            detail.locator('summary').click()
            expect(detail.locator('[data-testid=f38-tax]' if sheet == 'tax' else '[data-testid=f38-sponsor]')).to_be_visible()
        assert not errors
        ctx.close()


def test_changed_snapshot_is_visible_unavailable_not_stuck_loading(live_server, browser, monkeypatch):
    from app.auth import COOKIE_NAME, create_session_token
    from app.v2.post_run_context import PostRunRequestContext, PostRunContextChanged
    record = _project('generic_solar_reference', two_senior=False)
    ctx = browser.new_context()
    ctx.add_cookies([{'name': COOKIE_NAME, 'value': create_session_token(user_id=USER, username='admin'), 'url': live_server}])
    page = ctx.new_page()
    page.goto(f'{live_server}/v2/workbook?project={record.project_code}')
    activate_destination(page, 'tab-tax')
    monkeypatch.setattr(PostRunRequestContext, 'validate_current', lambda *a: (_ for _ in ()).throw(PostRunContextChanged('changed')))
    loader = page.locator('#v2-sheet-tax [data-testid=financing-trace-loader]')
    loader.locator('summary').click()
    expect(loader.locator('[data-testid=financing-trace-unavailable]')).to_contain_text('UNAVAILABLE')
    assert loader.locator('[data-raw]').count() == 0
    ctx.close()
