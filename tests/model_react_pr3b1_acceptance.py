"""PR3b-1 mounted Financing acceptance. Synthetic projects only; no read-layer writes."""
import pytest
from tests.model_react_rcm_financing_acceptance import fin_session, no_page_overflow

__all__ = ('test_pr3b1_mounted_workspace_links_and_responsive','test_pr3b1_read_layer_get_failures_and_race','test_pr3b1_actual_solar_wind_last_run','test_pr3b1_identity_mismatch_and_abort','test_pr3b1_late_aborted_read_cannot_replace_remounted_scope','test_pr3b1_protected_reference_keeps_existing_read_only_views','fin_session')

@pytest.mark.parametrize('width',[1440,1024,390,320])
def test_pr3b1_mounted_workspace_links_and_responsive(live_server,fin_session,width):
    context,page,record,errors=fin_session('pr3b1-width-'+str(width),width=width)
    writes=[];page.on('request',lambda r:writes.append(r.url) if r.method not in ('GET','HEAD') else None)
    base=f'{live_server}/v2/model-react/{record.project_code}'
    page.goto(base+'#financing')
    page.wait_for_selector('[data-run-state="NOT_RUN"]',timeout=60000)
    assert page.locator('[role="tablist"][aria-label="Financing sections"]').count()==0
    assert page.locator('[aria-label="Financing workspace sections"]').count()==1
    no_page_overflow(page)
    import os
    from pathlib import Path
    shots=os.environ.get('PR3B1_SCREENSHOT_DIR')
    if shots:
        Path(shots).mkdir(parents=True,exist_ok=True)
        page.screenshot(path=str(Path(shots)/f'financing-mounted-{width}.png'),full_page=True)
    page.evaluate("window.__pr3b1_document = true")
    page.locator('[data-financing-tab-button="terms"]').click()
    page.wait_for_selector('[data-sheet-editor="debt"]')
    assert 'financing=terms' in page.url
    assert page.evaluate('window.__pr3b1_document === true')
    page.reload();page.wait_for_selector('[data-sheet-editor="debt"]')
    for view,marker in [('bankability','[data-bankability-editor]'),('facilities','[data-capital-stack]'),('investors','[data-investors-panel]'),('sources-uses','[data-sources-uses]'),('debt-metrics','[data-debt-metrics], [data-dm-empty]'),('overview','[data-financing-overview]')]:
        page.locator('[data-financing-tab-button="'+view+'"]').click();page.wait_for_selector(marker,timeout=60000)
        no_page_overflow(page)
    page.get_by_role('button',name='Back to Financing workspace').click()
    page.wait_for_selector('[data-run-state="NOT_RUN"]')
    page.locator('[href="#results"]').filter(has_text='Returns and valuation').click()
    page.wait_for_function("() => location.hash === '#results'")
    assert not writes
    assert not [e for e in errors if 'Failed to load resource' not in e]

@pytest.mark.parametrize('status',[403,404,409])
def test_pr3b1_read_layer_get_failures_and_race(live_server,fin_session,status):
    context,page,record,errors=fin_session('pr3b1-status-'+str(status))
    page.route('**/v2/model-react/financing/studio?*',lambda route:route.fulfill(status=status,content_type='application/json',body='{"ok":false,"code":"SYNTHETIC_REFUSAL"}'))
    page.goto(f'{live_server}/v2/model-react/{record.project_code}#financing')
    page.get_by_role('alert').filter(has_text=str(status)).wait_for(timeout=60000)
    assert page.locator('[data-run-zones="visible"]').count()==0
    assert page.get_by_role('button',name='Reload evidence').count()==1


@pytest.mark.parametrize('kind',['solar','wind'])
def test_pr3b1_actual_solar_wind_last_run(live_server,fin_session,kind):
    from tests.model_react_wf1_browser_acceptance import run_canonical
    context,page,record,errors=fin_session('pr3b1-actual-'+kind,kind=kind)
    run_canonical(context,live_server,record.project_code)
    expected=context.request.get(live_server+'/v2/model-react/analysis/credit-decision',params={'project':record.project_code}).json()
    run=expected['data']['runs'][0]
    writes=[];page.on('request',lambda r:writes.append(r.url) if r.method not in ('GET','HEAD') else None)
    page.goto(f'{live_server}/v2/model-react/{record.project_code}#financing')
    try:
        page.wait_for_selector('[data-run-state]',timeout=15000)
    except Exception:
        raise AssertionError({'browser_errors':errors,'visible_page':page.locator('body').inner_text()[:6000]})
    assert page.locator('[data-run-state]').get_attribute('data-run-state')=='CURRENT', page.locator('.pr3b1').inner_text()
    assert page.locator('[data-run-zones="visible"]').count()==1
    assert run['identity']['snapshot_id'] in page.locator('.pr3b1 [role="status"]').inner_text()
    assert run['capacity']['final_commitment']['d'] in page.locator('.pr3b1').inner_text()
    no_page_overflow(page)
    page.get_by_role('combobox',name='Run history',exact=True).select_option(run['identity']['history_id'])
    assert 'dm_run=' in page.url
    page.reload();page.wait_for_selector('[data-run-state="CURRENT"]',timeout=60000)
    assert page.get_by_role('combobox',name='Run history',exact=True).input_value()==run['identity']['history_id']
    assert not writes
    assert not [e for e in errors if 'Failed to load resource' not in e]


@pytest.mark.parametrize('mode',['identity','abort'])
def test_pr3b1_identity_mismatch_and_abort(live_server,fin_session,mode):
    context,page,record,errors=fin_session('pr3b1-negative-'+mode)
    def reply(route):
        if mode=='abort': route.abort();return
        response=route.fetch();body=response.json();body['identity']['content_hash']='synthetic-mixed-identity'
        route.fulfill(response=response,json=body)
    page.route('**/v2/model-react/financing/studio?*',reply)
    page.goto(f'{live_server}/v2/model-react/{record.project_code}#financing')
    if mode=='identity':
        page.wait_for_selector('[data-run-state="UNAVAILABLE"]',timeout=60000)
        assert page.locator('[data-run-zones="hidden"]').count()==1
        assert 'Last Run changed' in page.locator('.pr3b1').inner_text()
    else:
        page.locator('[data-financing-studio] [role="alert"]').wait_for(timeout=60000)
    assert page.locator('[data-run-zones="visible"]').count()==0


def test_pr3b1_late_aborted_read_cannot_replace_remounted_scope(live_server,fin_session):
    from playwright.sync_api import Error
    context,page,record,errors=fin_session('pr3b1-reordered')
    waiting=[]
    def hold_first(route):
        if not waiting: waiting.append(route)
        else: route.continue_()
    page.route('**/v2/model-react/financing/studio?*',hold_first)
    page.goto(f'{live_server}/v2/model-react/{record.project_code}#financing')
    page.wait_for_selector('[data-financing-studio]')
    for _ in range(100):
        if waiting: break
        page.wait_for_timeout(50)
    assert len(waiting)==1
    page.evaluate("location.hash='#overview'")
    page.wait_for_selector('[data-financing-studio]',state='detached')
    page.evaluate("location.hash='#financing'")
    page.wait_for_selector('[data-run-state="NOT_RUN"]',timeout=60000)
    try: waiting[0].fulfill(status=200,content_type='application/json',body='{"ok":false,"code":"LATE_OLD_READ"}')
    except Error: pass  # the previous reader's AbortController already cancelled the route
    assert page.locator('[data-run-state="NOT_RUN"]').count()==1
    assert page.locator('[data-financing-studio] [role="alert"]').count()==0


def test_pr3b1_protected_reference_keeps_existing_read_only_views(live_server,fin_session):
    from app.persistence.projects_repository import get_reference_by_template_source
    from app.services.project_library_service import ensure_reference_models
    context,page,record,errors=fin_session('pr3b1-reference')
    ensure_reference_models();reference=get_reference_by_template_source('generic_solar_reference')
    page.goto(f'{live_server}/v2/model-react/{reference.project_code}#financing')
    page.locator('[data-financing-studio] [role="alert"]').filter(has_text='409').wait_for(timeout=60000)
    page.get_by_text('Existing Financing views',exact=True).click()
    page.get_by_role('navigation',name='Available existing Financing views').get_by_role('button',name='Debt terms',exact=True).click()
    page.wait_for_selector('[data-sheet-editor="debt"]')
    assert page.locator('[data-sheet-editor="debt"] input.fm-input').count()==0
    page.locator('[data-financing-tab-button="bankability"]').click()
    page.wait_for_selector('[data-bank-readonly="true"]')
    assert page.locator('[data-bank-save]').is_disabled()
