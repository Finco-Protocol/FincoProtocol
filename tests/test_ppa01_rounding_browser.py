"""Real Chromium rounding controls and server-derived saved price stages."""
import json
import os

import pytest

pytest.importorskip('playwright', reason='playwright not installed in this workflow')

from tests.test_rcux2_ppa_quick_add_browser import Session, browser, live_server  # noqa: E402,F401
from tests.test_ppa01_contractual_browser import save  # noqa: E402
from tests.model_workspace_navigation import activate_destination  # noqa: E402


@pytest.mark.parametrize('template', ['generic_solar_reference', 'generic_wind_reference'])
@pytest.mark.parametrize('mobile', [False, True])
def test_rounding_controls_default_off_save_reload_and_server_preview(live_server, browser, template, mobile):
    s = Session(live_server, browser, 'rounding-' + template[8:12] + str(mobile), template=template,
                viewport={'width': 390, 'height': 844} if mobile else None, scheme='dark' if mobile else 'light')
    activate_destination(s.page, 'tab-revenue')
    s.fill(kind='indexed_ppa', price='62.345', share='100', index='2', ref='synthetic-rounding-contract')
    s.use_full_window(); s.add()
    editor = s.page.locator('.rc-index-editor')
    editor.locator(':scope > summary').click()
    rounding = s.page.locator('.rc-rounding-editor')
    rounding.locator(':scope > summary').click()
    toggle = rounding.get_by_role('checkbox', name='Apply contractual price rounding')
    assert not toggle.is_checked()
    toggle.focus(); s.page.keyboard.press('Space')
    assert toggle.is_checked()
    assert rounding.get_by_label('Decimal places', exact=True).input_value() == '2'
    assert rounding.get_by_label('Rounding method', exact=True).input_value() == 'HALF_UP'
    assert rounding.get_by_text('This setting changes calculated PPA revenue.', exact=True).is_visible()
    save(s)
    expected = s.saved_book()
    assert expected['streams'][0]['price_rounding'] == dict(enabled=True, decimal_places=2, method='HALF_UP')
    s.page.reload(); s.page.wait_for_selector('[data-testid=ppa-quick-add]', state='attached')
    activate_destination(s.page, 'tab-revenue')
    editor = s.page.locator('.rc-index-editor'); editor.locator(':scope > summary').click()
    rounding = s.page.locator('.rc-rounding-editor'); rounding.locator(':scope > summary').click()
    assert rounding.get_by_role('checkbox').is_checked()
    rounding.locator('[data-rounding-prices] > summary').click()
    stages = json.loads(s.page.locator('[data-rounding-preview]').input_value())
    prices = next(iter(stages.values()))
    rows = rounding.locator('[data-rounding-prices] tbody tr')
    assert rows.count() == len(prices) and len(prices) > 20
    for index in (0, 1, 2, len(prices)-1):
        assert rows.nth(index).locator('td').last.inner_text() == str(prices[index]['effective_price'])
    assert prices[0]['effective_price'] == 62.345 and not prices[0]['rounding_applied']
    assert any(p['rounding_applied'] for p in prices)
    rounding.get_by_label('Decimal places', exact=True).select_option('6')
    rounding.get_by_label('Rounding method', exact=True).select_option('HALF_EVEN')
    assert rounding.locator('[data-rounding-prices]').is_hidden()
    assert s.saved_book() == expected
    save(s)
    assert s.saved_book()['streams'][0]['price_rounding'] == dict(enabled=True, decimal_places=6, method='HALF_EVEN')
    assert s.errors == [], s.errors
    path = os.environ.get('PPA01_ROUNDING_SCREENSHOTS')
    if path:
        os.makedirs(path, exist_ok=True)
        s.page.locator('.rc-index-editor > summary').click()
        s.page.locator('.rc-rounding-editor > summary').click()
        s.page.screenshot(path=os.path.join(path, template + ('-mobile' if mobile else '-desktop') + '.png'), full_page=True)
    s.close()
