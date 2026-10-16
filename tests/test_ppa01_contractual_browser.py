"""Real Chromium acceptance of dated PPA edits; no browser pricing engine."""
import json
import os
import re

import pytest

pytest.importorskip('playwright', reason='playwright not installed in this workflow')

from tests.test_rcux2_ppa_quick_add_browser import Session, browser, live_server  # noqa: E402,F401
from tests.model_workspace_navigation import activate_destination  # noqa: E402


def open_calendar(s):
    s.page.on('dialog',lambda d:d.accept())
    activate_destination(s.page,'tab-revenue')
    s.fill(kind='indexed_ppa',price='60',share='60',index='2',ref='synthetic-calendar-contract')
    s.use_full_window(); s.add()
    s.page.locator('.rc-index-editor summary').click()
    s.page.locator('[data-index-mode=calendar]').check()


def save(s):
    with s.page.expect_response(lambda r:r.request.method=='POST' and r.url.endswith('/v2/workbook/revenue/contracts')) as response:
        s.page.locator('[data-revenue-save]').click()
    assert response.value.status==200, response.value.text()[:400]
    s.page.locator('[data-revenue-feedback]').filter(has_text=re.compile('^Saved Working Copy')).wait_for()


def shot(s,name):
    path=os.environ.get('PPA01_CALENDAR_SCREENSHOTS')
    if path:
        os.makedirs(path,exist_ok=True)
        s.page.screenshot(path=os.path.join(path,name+'.png'),full_page=True)


@pytest.mark.parametrize('template',['generic_solar_reference','generic_wind_reference'])
@pytest.mark.parametrize('mobile',[False,True])
def test_four_anchor_controls_save_reload_and_refusal_keep_draft(live_server,browser,template,mobile):
    s=Session(live_server,browser,'ppa-date-'+template[8:12]+str(mobile),template=template,
              viewport={'width':390,'height':844} if mobile else None,scheme='dark' if mobile else 'light')
    open_calendar(s)
    field=lambda key:s.page.locator('[data-calendar-field='+key+']')
    field('price_base_date').fill('2028-07-01')
    field('first_review_date').fill('2029-12-31')
    rule=field('start_rule')
    assert set(rule.locator('option').evaluate_all('els=>els.map(e=>e.value)'))=={'SIGNATURE','COD','PPA_START','CUSTOM'}
    rule.select_option('SIGNATURE'); field('signing_date').fill('2028-12-31')
    assert s.page.locator('[data-calendar-resolved]').inner_text()=='2028-12-31'
    save(s)
    expected=s.saved_book()
    assert expected['streams'][0]['indexation_timing']['signing_date']=='2028-12-31'
    s.page.reload(); s.page.wait_for_selector('[data-testid=ppa-quick-add]',state='attached')
    activate_destination(s.page,'tab-revenue')
    assert field('price_base_date').input_value()=='2028-07-01'
    assert field('signing_date').input_value()=='2028-12-31'
    preview=s.page.locator('[data-calendar-prices]')
    assert preview.locator('tbody tr').count()>20
    s.page.get_by_text('Period prices (saved contracts)',exact=True).click()
    first=preview.locator('tbody tr').first
    # Both reference CODs follow two explicit Dec-31 reviews since signature.
    assert first.locator('td').last.inner_text()=='62.4240'
    assert s.errors==[],s.errors
    shot(s,'calendar-'+template[8:12]+('-mobile' if mobile else '-desktop'))
    rule.select_option('CUSTOM'); field('custom_start_date').fill('2029-04-15')
    field('first_review_date').fill('2030-04-15')
    assert s.page.locator('[data-calendar-prices]').is_hidden()
    with s.page.expect_response(lambda r:r.request.method=='POST' and r.url.endswith('/v2/workbook/revenue/contracts')) as response:
        s.page.locator('[data-revenue-save]').click()
    assert response.value.status==422
    s.page.locator('[data-revenue-error]').filter(has_text='REVIEW_PERIOD_ALIGNMENT').wait_for()
    assert field('custom_start_date').input_value()=='2029-04-15'
    assert s.saved_book()==expected
    assert 'unsaved' in s.page.locator('[data-revenue-feedback]').inner_text().lower() or 'not saved' in s.page.locator('[data-revenue-feedback]').inner_text().lower()
    s.close()


@pytest.mark.parametrize('template',['generic_solar_reference','generic_wind_reference'])
def test_dated_level_tables_paste_and_reload(live_server,browser,template):
    s=Session(live_server,browser,'ppa-date-level-'+template[8:12],template=template)
    open_calendar(s)
    field=lambda key:s.page.locator('[data-calendar-field='+key+']')
    field('method').select_option('DATED_INDEX_LEVELS')
    field('start_rule').select_option('SIGNATURE')
    field('price_base_date').fill('2028-07-01'); field('signing_date').fill('2028-12-31')
    field('first_review_date').fill('2029-12-31'); field('index_base_date').fill('2028-12-01')
    end=s.window_end()
    obs=['2028-12-01\t100\tOBSERVED\t2028-12-20\tsynthetic-base']
    reviews=[]
    for year in range(2029,int(end[:4])+1):
        if f'{year}-12-31'>=end: break
        obs.append(f'{year}-12-01\t{100+(year-2028)*3}\tFORECAST\t\tsynthetic-assumption')
        reviews.append(f'{year}-12-31\t{year}-12-01')
    for title,lines in [('Index observations',obs),('Price reviews',reviews)]:
        paste=s.page.get_by_role('textbox',name='Paste '+title,exact=True)
        paste.fill('\n'.join(lines))
        paste.locator('..').get_by_role('button',name='Replace with pasted rows').click()
    save(s)
    actual=s.saved_book()['streams'][0]
    assert actual['indexation_rate']==0
    assert actual['indexation_timing']['observations'][0]['basis']=='OBSERVED'
    assert actual['indexation_timing']['observations'][1]['publication_date'] is None
    s.page.get_by_text('Period prices (saved contracts)',exact=True).click()
    assert s.page.locator('[data-calendar-prices] tbody tr').first.locator('td').last.inner_text()=='63.6000'
    assert s.errors==[],s.errors
    shot(s,'dated-levels-'+template[8:12])
    s.close()
