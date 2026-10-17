"""Scoped template+real Chromium smoke with synthetic OPEX lines only (not authenticated app)."""
from pathlib import Path
import shutil
from types import SimpleNamespace as N
from jinja2 import Environment, FileSystemLoader, select_autoescape
import pytest

ROOT = Path(__file__).resolve().parents[1]
TEMPLATES = ROOT / 'app/templates/v2/partials'
JS = ROOT / 'static/js/model_opex_profiles_v1.js'


def render():
    env=Environment(loader=FileSystemLoader(str(TEMPLATES)),autoescape=select_autoescape(('html',)))
    def line(code,name,y1,read_only=False,derived=False):
        return N(code=code,name=name,is_active=True,is_derived=derived,is_contingency=derived,
                 is_read_only=read_only,inflation_pct=2.0,year_values=(y1,y1*1.02,y1*1.0404),source='WORKING_COPY')
    vm=N(display_years=3,groups=[N(lines=[line('B.03.01','Maintenance',100),
                                                  line('B.05.01','Security',30),
                                                  line('B.13.01','Contingency',3,read_only=True,derived=True)])])
    return env.get_template('_opex_profile_candidate.html').render(opex_vm=vm,ws_dirty=True).replace('<script src="/static/js/model_opex_profiles_v1.js" defer></script>','')


def test_wf11_candidate_template_protects_derived_rows_and_explains_authority():
    html=render()
    assert 'No Save or Run integration' in html
    assert 'changed inputs — Run required' in html
    assert 'B.13.01 · Contingency' in html
    assert 'value="B.13.01"' not in html
    assert 'data-wf11-candidate' in html


@pytest.mark.parametrize("width", [390, 1440])
def test_wf11_candidate_browser_real_chromium(width):
    playwright=pytest.importorskip('playwright.sync_api')
    with playwright.sync_playwright() as p:
        browser=p.chromium.launch(headless=True,args=['--no-sandbox'], **({'executable_path': shutil.which('chromium')} if shutil.which('chromium') else {}))
        page=browser.new_page(viewport={'width':width,'height':844})
        page.set_content(render())
        page.add_script_tag(path=str(JS))
        page.get_by_test_id('opex-profile-workspace').locator('summary').first.click()
        form=page.locator('[data-wf11-maintenance]')
        form.locator('[name=owner_line]').select_option('B.03.01')
        form.locator('[name=year]').fill('2')
        form.locator('[name=amount]').fill('250')
        form.locator('button[type=submit]').click()
        assert 'financial classification' in page.locator('[data-wf11-status]').inner_text()
        assert page.locator('[data-wf11-event-rows] tr').count()==1
        assert '2' in page.locator('[data-wf11-event-rows]').inner_text()
        form.locator('button[type=submit]').click()
        assert 'DUPLICATE_EVENT_ID' in page.locator('[data-wf11-status]').inner_text()
        seasonal=page.locator('[data-wf11-seasonal]')
        seasonal.locator('[name=seasonal_line]').select_option('B.03.01')
        seasonal.locator('[name=seasonal_year]').fill('2')
        seasonal.locator('[name=h1]').fill('40')
        seasonal.locator('[name=h2]').fill('60')
        seasonal.locator('button[type=submit]').click()
        cells=page.locator('[data-wf11-seasonal-output] td').all_inner_texts()
        assert cells==['40.8000','61.2000','102.0000']
        assert 'NOT VERIFIED' in page.locator('[data-wf11-seasonal-status]').inner_text()
        seasonal.locator('[name=h2]').fill('70')
        seasonal.locator('button[type=submit]').click()
        assert 'WEIGHTS_MUST_TOTAL_100' in page.locator('[data-wf11-seasonal-status]').inner_text()
        assert page.locator('body').evaluate('(e) => e.scrollWidth <= window.innerWidth + 1')
        browser.close()
