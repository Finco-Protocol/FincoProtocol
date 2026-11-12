"""F04 local browser proof using a temporary build; never replaces served assets."""
from pathlib import Path
import os
import subprocess
import pytest
from tests.test_workflow_c_browser_v1 import live_server, browser
from tests.model_react_rcm_support import rcm_react_flag
from tests.model_react_rcm_financing_acceptance import fin_session, no_page_overflow
from tests.model_react_wf1_browser_acceptance import run_canonical

@pytest.fixture(scope='module')
def f04_build(tmp_path_factory):
    root = Path(__file__).resolve().parents[1]
    build = tmp_path_factory.mktemp('f04-browser-build')
    subprocess.run(['npm','run','build','--','--outDir',str(build)], cwd=root/'frontend', check=True, capture_output=True)
    return build

def assets(context, build):
    for ext, mime in [('js','application/javascript'),('css','text/css')]:
        context.route(f'**/static/react/finco-react.{ext}*', lambda route, request, ext=ext, mime=mime:
            route.fulfill(path=str(build/f'finco-react.{ext}'), content_type=mime))

def screenshot(page, name):
    if folder := os.environ.get('F04_SCREENSHOT_DIR'):
        Path(folder).mkdir(parents=True,exist_ok=True)
        page.screenshot(path=str(Path(folder)/f'{name}.png'),full_page=True)

@pytest.mark.parametrize('width',[1440,1024,390])
def test_f04_no_run_and_supported_method_boundary(live_server,fin_session,f04_build,width):
    context,page,record,errors=fin_session(f'f04-width-{width}',width=width)
    assets(context,f04_build)
    writes=[]
    page.on('request',lambda r:writes.append(r.url) if r.method not in ('GET','HEAD') else None)
    base=f'{live_server}/v2/model-react/{record.project_code}'
    page.goto(base+'#financing')

    try:
        page.wait_for_selector('[data-run-state="NOT_RUN"]',timeout=15000)
    except Exception:
        screenshot(page,f'failure-{width}')
        raise AssertionError({'errors':errors,'body':page.locator('body').inner_text()[:8000]})
    panel=page.locator('[data-f04-debt-provenance]')
    assert 'MONTHLY_SCHEDULE_NOT_AVAILABLE' in panel.inner_text()
    assert panel.locator('tbody tr').count()==5
    assert panel.locator('tbody td').filter(has_text='UNAVAILABLE').count()>=5
    no_page_overflow(page);screenshot(page,f'no-run-{width}')
    page.locator('[data-financing-tab-button="bankability"]').click()
    selector=page.locator('[data-bank="sizing_mode"]')
    selector.wait_for()
    assert selector.locator('option:not([disabled])').evaluate_all('(options)=>options.map(o=>o.value)')==['','flat_dscr_sculpted','gearing_cap']
    selector.select_option('gearing_cap')
    assert selector.input_value()=='gearing_cap'
    assert selector.locator('option[value="minimum_dscr_sculpted"]').evaluate('(option)=>option.disabled')
    assert selector.locator('option[value="frozen_excel_schedule"]').evaluate('(option)=>option.disabled')
    no_page_overflow(page);screenshot(page,f'methods-{width}')
    assert not writes
    assert not errors

@pytest.mark.parametrize('kind',['solar','wind'])
def test_f04_current_native_periods_and_provenance(live_server,fin_session,f04_build,kind):
    context,page,record,errors=fin_session(f'f04-run-{kind}',kind=kind)
    assets(context,f04_build)
    run_canonical(context,live_server,record.project_code)
    credit=context.request.get(live_server+'/v2/model-react/analysis/credit-decision',params={'project':record.project_code}).json()
    run=credit['data']['runs'][0]
    page.goto(f'{live_server}/v2/model-react/{record.project_code}#financing')
    page.wait_for_selector('[data-run-state="CURRENT"]',timeout=60000)
    panel=page.locator('[data-f04-debt-provenance]')
    assert run['identity']['history_id'] in panel.inner_text()
    assert run['identity']['composite_hash'] in panel.inner_text()
    assert 'MONTHLY_SCHEDULE_NOT_AVAILABLE' in panel.inner_text()
    table=page.locator('[aria-label="Native debt period schedule"]')
    assert table.locator('tbody tr').count()==len(run['debt_metrics']['periods'])
    assert 'Aggregate Senior' in panel.inner_text()
    no_page_overflow(page);screenshot(page,f'current-{kind}-1440')
    assert not errors

@pytest.mark.parametrize('case', ['atomic', 'cas', 'unknown', 'bankability'])
def test_f04_existing_save_contract_regression(live_server,fin_session,f04_build,case):
    from tests import model_react_pr3b2_acceptance as existing
    def session(*args,**kwargs):
        result=fin_session(*args,**kwargs)
        assets(result[0],f04_build)
        return result
    if case=='atomic':
        existing.test_pr3b2_atomic_block_and_unchanged_run(live_server,session,1440)
    else:
        check={'cas':existing.test_pr3b2_stale_csrf_and_retry_keep_draft,
               'unknown':existing.test_pr3b2_unknown_outcome_replays_identical_request,
               'bankability':existing.test_pr3b2_bankability_draft_and_original_paths}[case]
        check(live_server,session)
