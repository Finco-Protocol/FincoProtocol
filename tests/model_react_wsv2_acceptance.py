"""Explicit local Chromium WS1 acceptance, pending governed mandatory-role registration."""
import json
import os
import time
from pathlib import Path
import pytest
from tests.test_workflow_c_browser_v1 import live_server, browser  # noqa: F401
from tests.model_react_rcm_support import rcm_react_flag  # noqa: F401
OUT = Path(os.environ.get('WSV2_SCREENSHOT_DIR', 'artifacts/wsv2-core'))


def shot(page, name):
    OUT.mkdir(parents=True, exist_ok=True)
    page.evaluate("window.scrollTo(0, 0)")
    page.screenshot(path=str(OUT / (name + '.png')), full_page=True)


def session(browser, base, uid, kind='solar'):
    from app.auth import COOKIE_NAME, create_session_token
    from app.services.reference_seed_service import create_reference_seeded_project
    record = create_reference_seeded_project(user_id=uid, requested_name='Workspace review ' + kind,
        template_source='generic_' + kind + '_reference', capacity_mw=16)
    context = browser.new_context(viewport={'width':1440, 'height':1000})
    context.add_cookies([{'name':COOKIE_NAME,'value':create_session_token(user_id=uid,username='admin'),'url':base}])
    return context, context.new_page(), record


def destination(page, name):
    menu = page.locator('.wsv2-menu')
    if menu.is_visible() and menu.get_attribute('aria-expanded') != 'true': menu.click()
    page.locator(f'[data-workspace-destination="{name}"]').click()


@pytest.mark.parametrize('kind', ['solar','wind','data_center','ev_charging'])
def test_wsv2_real_run_reads_exact_snapshot_without_document_reload(live_server,browser,rcm_react_flag,kind):
    context,page,record = session(browser,live_server,'ws1-browser-'+kind,kind)
    errors, runs = [], []
    page.on('pageerror', lambda error: errors.append(str(error)))
    page.on('request', lambda request: runs.append(request.post_data) if request.method=='POST' and '/v2/workbook/run' in request.url else None)
    try:
        page.goto(f'{live_server}/v2/model-react/{record.project_code}#inputs/project')
        page.wait_for_selector('[data-sheet-editor="project_setup"]')
        skip = page.get_by_role('link', name='Skip to main content')
        skip.focus(); skip.press('Enter')
        page.wait_for_function("() => document.activeElement?.id === 'rx-main-content'")
        assert page.locator('[data-sheet-editor="project_setup"]').is_visible(), 'skip link must not change sections'
        origin = page.evaluate('performance.timeOrigin')
        page.wait_for_function("() => Boolean(document.querySelector('[data-wf-run]')) && !document.querySelector('[data-wf-run]').disabled")
        started = time.monotonic()
        page.locator('[data-wf-run]').click()
        page.wait_for_selector('[data-financial-page="results"][data-financial-state="CURRENT"]',timeout=120000)
        elapsed=time.monotonic()-started
        assert page.evaluate('performance.timeOrigin')==origin and len(runs)==1
        from app.persistence.workspace_repository import get_workspace_state
        from app.persistence.run_history_repository import get_run_history
        state=get_workspace_state(record.user_id,record.project_id)
        history=get_run_history(record.user_id,record.project_id)
        assert len(history)==1 and history[0].runtime_snapshot_id==state.last_runtime_snapshot_id
        assert page.locator('[data-results-view] [data-run-identity]').first.get_attribute('data-run-identity')==state.last_runtime_snapshot_id
        # The shared display control changes rendering only: no Save, Run, dirty state or canonical identity changes.
        from decimal import Decimal, ROUND_HALF_UP
        before_hash = state.last_runtime_composite_hash
        cell = page.locator('[data-period-table="operating-performance"] td[data-v]:not([data-v="0"])').first
        raw = cell.get_attribute('data-v')
        canonical = cell.get_attribute('data-canonical')
        for digits in (0, 2, 3, 0):
            page.get_by_label('Report precision', exact=True).select_option(str(digits))
            expected = Decimal(raw).quantize(Decimal(1).scaleb(-digits), rounding=ROUND_HALF_UP)
            text = format(abs(expected), f',.{digits}f')
            if expected < 0: text = '(' + text + ')'
            assert cell.inner_text() == text
            assert cell.get_attribute('data-canonical') == canonical
            assert page.locator('[data-workflow-bar]').get_attribute('data-unsaved') == '0'
            assert get_workspace_state(record.user_id, record.project_id).last_runtime_composite_hash == before_hash
            assert len(get_run_history(record.user_id,record.project_id)) == 1 and len(runs) == 1
            if digits in (2,3): shot(page, f'{kind}-precision-{digits}')
        shot(page,kind+'-results')
        destination(page,'overview')
        page.wait_for_selector(f'[data-financial-overview][data-overview-snapshot="{state.last_runtime_snapshot_id}"]')
        page.wait_for_selector('[data-overview-sources-uses] table')
        for width in (1440,1366,768,390):
            page.set_viewport_size({'width':width,'height':1000})
            assert page.evaluate('document.documentElement.scrollWidth <= innerWidth + 1')
            shot(page,f'{kind}-overview-{width}')
        destination(page,'inputs/opex')
        page.wait_for_selector('#wf-inputs-costs')
        assert page.locator('[data-workspace-destination="inputs/opex"]').get_attribute('aria-current')=='page'
        assert page.evaluate('document.activeElement?.getClientRects().length > 0')
        page.go_back(); page.wait_for_selector('[data-financial-overview]')
        page.go_forward(); page.wait_for_selector('#wf-inputs-costs')
        page.reload(); page.wait_for_selector('#wf-inputs-costs')
        assert len(runs)==1 and not errors, errors
        (OUT/(kind+'-timing.json')).write_text(json.dumps({'mode':os.environ.get('FINCO_MODEL_EXECUTION_MODE'),'environment':'local replica','samples':1,'click_to_visible_seconds':elapsed,'snapshot_id':state.last_runtime_snapshot_id},indent=2))
    finally: context.close()


def test_wsv2_wizard_three_steps_library_and_safe_exception(live_server,browser,rcm_react_flag):
    context,page,record=session(browser,live_server,'ws1-wizard')
    try:
        page.goto(f'{live_server}/v2/model-react/')
        page.wait_for_selector('[data-library-view]'); shot(page,'library')
        page.locator('[data-new-project-cta]').click()
        page.wait_for_selector('[data-wizard-step="1"]')
        assert page.locator('.rcm-steps li').count()==3
        page.locator('[data-blank-project-constraint] summary').click()
        assert 'cannot currently be saved' in page.locator('[data-blank-project-constraint]').inner_text()
        shot(page,'wizard-start')
        page.locator('[data-path-card="new"]').click()
        page.locator('[data-tech-card="solar"]').click()
        page.locator('[data-wizard-next]').click()
        page.locator('#rcm-name').fill('New workspace review')
        page.locator('[data-wizard-next]').click()
        page.wait_for_selector('[data-wizard-step="3"]')
        assert page.locator('[data-wizard-panel="timeline"]').count()==0
        shot(page,'wizard-review')
        page.locator('[data-wizard-create]').click()
        page.wait_for_selector('[data-sheet-editor="project_setup"]',timeout=30000)
        assert page.url.endswith('#inputs'); shot(page,'inputs')
        destination(page,'financing')
        page.wait_for_selector('[data-financing-studio]'); shot(page,'financing')
        page.route('**/v2/workbook/run',lambda route: route.fulfill(status=409,content_type='application/json',body=json.dumps({
            'ok':False,'outcome':'FAILED','error_code':'SHL_MATURITY_RESIDUAL_FAILS_CLOSED',
            'message':'The shareholder loan still has an unpaid balance at maturity. No result was committed.'})))
        page.locator('[data-wf-run]').click(); page.wait_for_selector('[data-run-failure]')
        assert page.locator('[data-run-failure] a[href="#financing"]').count()==1
        shot(page,'exception-typed-fault-injection')
    finally: context.close()


def test_wsv2_refuses_same_run_with_split_freshness(live_server,browser,rcm_react_flag):
    context,page,record=session(browser,live_server,'ws1-split-freshness')
    runs=[]
    page.on('request',lambda request:runs.append(request.post_data) if request.method=='POST' and '/v2/workbook/run' in request.url else None)
    try:
        page.goto(f'{live_server}/v2/model-react/{record.project_code}#inputs')
        page.wait_for_function("() => Boolean(document.querySelector('[data-wf-run]')) && !document.querySelector('[data-wf-run]').disabled")
        def split(route):
            response=route.fetch(); body=response.json()
            if body.get('snapshot'):
                body['state']='STALE'; body['freshness']['state']='STALE'
            route.fulfill(response=response,json=body)
        page.route('**/v2/model-react/statements?*',split)
        page.locator('[data-wf-run]').click()
        page.wait_for_selector('[data-run-refresh="blocked"]',timeout=120000)
        assert page.locator('[data-wf-run]').is_disabled()
        assert page.locator('[data-results-view]').count()==0 and len(runs)==1
    finally:context.close()


def test_wsv2_before_visuals_use_exact_main_assets(live_server,browser,rcm_react_flag):
    import subprocess
    from tests.model_react_wf1_browser_acceptance import run_canonical
    context,page,record=session(browser,live_server,'ws1-before-assets')
    baseline='b1a58681e41af9f1b4d52b176f0001725720b15c'
    try:
        for extension,kind in [('js','application/javascript'),('css','text/css')]:
            asset=subprocess.check_output(['git','show',baseline+':static/react/finco-react.'+extension])
            page.route('**/static/react/finco-react.'+extension+'*',lambda route,_request,asset=asset,kind=kind:route.fulfill(status=200,content_type=kind,body=asset))
        page.goto(f'{live_server}/v2/model-react/')
        page.wait_for_selector('[data-library-view]');shot(page,'before-library')
        page.locator('[data-new-project-cta]').click();page.wait_for_selector('[data-wizard-step="1"]');shot(page,'before-wizard')
        page.goto(f'{live_server}/v2/model-react/{record.project_code}#inputs')
        page.wait_for_selector('[data-sheet-editor="project_setup"]');shot(page,'before-inputs')
        run_canonical(context,live_server,record.project_code)
        page.goto(f'{live_server}/v2/model-react/{record.project_code}#results')
        page.wait_for_selector('[data-results-view]');shot(page,'before-results')
        page.goto(f'{live_server}/v2/model-react/{record.project_code}#overview')
        page.wait_for_selector('[data-workspace-status]');shot(page,'before-overview')
        page.goto(f'{live_server}/v2/model-react/{record.project_code}#financing')
        page.wait_for_selector('[data-financing-studio]');shot(page,'before-financing')
        (OUT/'before-provenance.json').write_text(json.dumps({'asset_sha':baseline,'backend':'local candidate; added read-only Overview route unused by baseline bundle','not_live_production':True},indent=2))
    finally:context.close()
