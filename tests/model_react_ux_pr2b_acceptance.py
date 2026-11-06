"""Shared inline profile draft acceptance, real Chromium and synthetic isolated projects only."""
import json
import os
import re
from pathlib import Path
from urllib.parse import urlencode
import pytest
from tests.model_react_mvp_acceptance import session
from tests.model_react_ux_pr2a_acceptance import _profiles, _save_profile


def _open(browser, base, name, kind='wind'):
    context, page, record, errors = session(browser, base, 'pr2b-' + name + '-' + kind, kind)
    code = record.project_code
    page.goto(f'{base}/v2/model-react/{code}#inputs/capex')
    page.wait_for_selector('[data-cost-grid="capex"] [data-saved-total]')
    return context, page, code, errors


def _edit(context, page, base, code):
    prof = _profiles(context, base, code)
    lines = context.request.get(f'{base}/v2/model-react/costlines?project={code}&sheet=capex').json()
    mapping = {l['finco_display_code']: l['sub_line_id'] for l in lines.get('projection', {}).get('lines', [])}
    eligible = [i['item_key'] for i in prof['items'] if i['item_key'] in mapping and not re.fullmatch(r'C\.\d{2}\.U\d{3}', i['item_key'])]
    assert eligible, (prof['project'], list(mapping), prof['items'])
    page.locator('[data-pr2b-toggle="desktop"]').click()
    key = eligible[0]
    page.wait_for_selector(f'[data-pr2b-shape="{key}"]')
    return prof, key, mapping[key]


def _shot(page, name):
    if os.environ.get('UX_PR2B_EVIDENCE_DIR'):
        p = Path(os.environ['UX_PR2B_EVIDENCE_DIR']); p.mkdir(parents=True, exist_ok=True)
        page.screenshot(path=str(p / (name + '.png')))


@pytest.mark.parametrize('kind', ['solar', 'wind'])
def test_pr2b_shared_draft_saved_timeline_and_mobile(live_server, browser, rcm_react_flag, kind):
    context, page, code, errors = _open(browser, live_server, 'shared', kind)
    try:
        p = _profiles(context, live_server, code)
        key = next(i['item_key'] for i in p['items'] if not re.fullmatch(r'C\.\d{2}\.U\d{3}', i['item_key']))
        _save_profile(context, live_server, code, [(key, 'MILESTONE', '', '1')])
        page.reload(); page.wait_for_selector('[data-saved-total]')
        prof, key, sub = _edit(context, page, live_server, code)
        n = prof['months']; assert n >= 2
        page.locator('[data-cost-timeline-toggle="capex"]').click(); page.wait_for_selector('[data-timeline-note="ready"]')
        before = [page.locator(f'[data-timeline-cell="{sub}:M{m}"]').text_content() for m in range(1, n+1)]
        saved_spec = json.dumps([[key, 'MILESTONE', '', '1']])
        canonical = context.request.get(f'{live_server}/v2/model-react/capex/preview?project={code}&'+urlencode({'spec':saved_spec}), headers={'X-Finco-React-Request':'1'}).json()
        assert before == [m['items'][key] for m in canonical['plan']['months']]
        page.locator(f'[data-pr2b-shape="{key}"]').select_option('EXPLICIT')
        page.locator(f'[data-pr2b-open="{sub}"]').click()
        cells = page.locator(f'[data-pr2b-editor="{key}"] [data-capex-month-input]')
        assert cells.count() == n and all(v == '' for v in cells.evaluate_all('els=>els.map(e=>e.value)'))
        # Missing / extra / negative / non100 / ambiguous are retained and block Save.
        ta = page.locator(f'[data-capex-explicit="{key}"]')
        for text in ['100\t'+'\t'.join(['0']*(n-2)), '\t'.join(['100']+['0']*n), '\t'.join(['-1','101']+['0']*(n-2)), '\t'.join(['99']+['0']*(n-1)), '12,5']:
            ta.fill(text); assert page.locator('[data-capex-save]').is_disabled()
            assert ta.input_value() == text
        page.wait_for_selector('[data-pr2b-ambiguous]')
        values = ['12.50000000'] + ['0']*(n-2) + ['87.50000000']
        ta.fill('\t'.join(values)); assert page.locator('[data-capex-save]').is_enabled()
        cells.first.focus(); page.keyboard.press('ArrowRight')
        # Move only at the text boundary.
        cells.first.evaluate('el=>el.setSelectionRange(el.value.length,el.value.length)'); cells.first.focus(); page.keyboard.press('ArrowRight')
        assert cells.nth(1).evaluate('el=>el===document.activeElement')
        assert before == [page.locator(f'[data-timeline-cell="{sub}:M{m}"]').text_content() for m in range(1,n+1)]
        page.locator('[data-cost-view-link="monthly"]').click()
        page.wait_for_selector('[data-capex-studio="ready"]')
        assert page.locator(f'[data-capex-shape="{key}"]').input_value() == 'EXPLICIT'
        assert '12.50000000' in page.locator(f'[data-capex-explicit="{key}"]').input_value()
        assert page.locator('[data-wf-dialog="true"]').count() == 0
        page.locator(f'[data-capex-explicit="{key}"]').fill('\n'.join(values))
        page.locator('[data-cost-view-link="lines"]').click(); page.wait_for_selector('[data-saved-total]')
        # Presentation toggle may reset on remount; the ONE draft does not.
        page.locator('[data-pr2b-toggle="desktop"]').click(); page.wait_for_selector(f'[data-pr2b-shape="{key}"]')
        assert page.locator(f'[data-pr2b-shape="{key}"]').input_value() == 'EXPLICIT'
        page.locator(f'[data-pr2b-open="{sub}"]').click()
        for width in (1440, 1024):
            page.set_viewport_size({'width':width,'height':900}); page.wait_for_timeout(100)
            assert page.evaluate('document.documentElement.scrollWidth-innerWidth') <= 1
            _shot(page, f'{kind}-inline-{width}')
        # Profile Save does not commit a staged line amount.
        amount = page.locator(f'tr[data-line="{sub}"] input[data-c="1"]')
        old = amount.input_value(); amount.fill('1234.56789')
        posts = []; page.on('request', lambda r: posts.append(r.url) if r.method == 'POST' else None)
        page.locator('[data-capex-save]').click(); page.wait_for_selector('[data-capex-status="ok"]')
        assert _profiles(context, live_server, code)['saved']['rows'][key] == {'shape':'EXPLICIT','explicit':','.join(values),'milestone':''}
        assert amount.input_value() == '1234.56789'
        fresh_lines = context.request.get(f'{live_server}/v2/model-react/costlines?project={code}&sheet=capex').json()
        assert str(next(l for l in fresh_lines['lines'] if l['sub_line_id']==sub)['amount_keur']) != '1234.56789'
        assert len(posts) == 1 and '/spending-profiles/save' in posts[0]
        amount.fill(old)
        # Mobile uses the native top-layer inspector with full editing and no page overflow.
        for width in (390,320):
            page.set_viewport_size({'width':width,'height':844}); page.wait_for_timeout(100)
            # Toggle editing off then on to open inspector on its active row.
            mobile = page.locator('[data-pr2b-toggle="mobile"]')
            if mobile.get_attribute('aria-pressed') == 'true': mobile.click()
            mobile.click(); page.wait_for_selector('.ux-line-inspector[open]')
            dialog = page.locator('.ux-line-inspector[open]')
            dialog.locator('[aria-label="Choose line profile"]').select_option(sub)
            assert dialog.locator(f'[data-capex-month-input="{key}:1"]').is_enabled()
            assert page.evaluate('document.documentElement.scrollWidth-innerWidth') <= 1
            _shot(page,f'{kind}-inspector-{width}')
            dialog.locator('[aria-label="Close line details"]').click()
        page.reload(); page.wait_for_selector('[data-saved-total]')
        assert _profiles(context, live_server, code)['saved']['rows'][key]['explicit'] == ','.join(values)
        assert not errors, errors
    finally: context.close()


def test_pr2b_storage_eligibility_is_server_evidence(live_server, browser, rcm_react_flag):
    from app.auth import COOKIE_NAME, create_session_token
    from app.services.project_library_service import ensure_reference_models, create_working_copy, UnsupportedProjectRuntimeError
    from app.persistence.projects_repository import get_reference_by_template_source
    from app.workbook.bess_config import ACTIVATION_ENABLED
    ensure_reference_models()
    reference = get_reference_by_template_source('generic_storage_reference')
    assert reference is not None
    # Do not activate a feature flag to manufacture technology parity.
    assert ACTIVATION_ENABLED is False
    with pytest.raises(UnsupportedProjectRuntimeError):
        create_working_copy('pr2b-bess-evidence', reference.project_id, 'Synthetic battery')
    context = browser.new_context(viewport={'width':1440,'height':900})
    context.add_cookies([{'name':COOKIE_NAME,'value':create_session_token(user_id='pr2b-bess-evidence',username='admin'),'url':live_server}])
    page = context.new_page()
    try:
        code = reference.project_code
        import httpx
        token = create_session_token(user_id='pr2b-bess-evidence',username='admin')
        responses = {}
        for endpoint in ('capex/profiles','costlines','workspace'):
            # stream=True records the real HTTP status even when the closed runtime aborts its error body.
            with httpx.stream('GET',f'{live_server}/v2/model-react/{endpoint}?project={code}&sheet=capex',
                              cookies={COOKIE_NAME:token},timeout=15,trust_env=False) as response:
                responses[endpoint]={'status':response.status_code}
        assert responses['capex/profiles']['status']==500
        responses['runtime']={'activation_enabled':False,'clone':'UnsupportedProjectRuntimeError',
                              'reason':'BESS_FINANCIAL_ACTIVATION_RELEASE_CLOSED; no editable profile surface can be verified'}
        if os.environ.get('UX_PR2B_EVIDENCE_DIR'):
            Path(os.environ['UX_PR2B_EVIDENCE_DIR'], 'bess-api-eligibility.json').write_text(json.dumps(responses,indent=2))
        page.goto(f'{live_server}/v2/model-react/{code}#inputs/capex/monthly')
        page.wait_for_timeout(200)
        assert page.locator('[data-capex-save]').count()==0
        _shot(page,'bess-closed-runtime')
    finally: context.close()


@pytest.mark.parametrize('failure', ['csrf', 'cas', 'unknown', 'explicit-readback', 'milestone-readback'])
def test_pr2b_save_failures_retain_full_draft(live_server, browser, rcm_react_flag, failure):
    context, page, code, errors = _open(browser, live_server, failure)
    try:
        prof, key, sub = _edit(context, page, live_server, code)
        shape = page.locator(f'[data-pr2b-shape="{key}"]')
        shape.select_option('MILESTONE' if failure=='milestone-readback' else 'EXPLICIT')
        page.locator(f'[data-pr2b-open="{sub}"]').click()
        if failure=='milestone-readback': page.locator(f'[data-capex-milestone="{key}"]').fill(str(prof['months']))
        else: page.locator(f'[data-capex-explicit="{key}"]').fill('\t'.join(['100']+['0']*(prof['months']-1)))
        url = '**/v2/capex/spending-profiles/save'
        calls=[]
        def intercept(route):
            calls.append(route.request.post_data)
            if failure=='csrf': route.fulfill(status=403,body='Refused')
            elif failure=='unknown':
                # The real server commits, only the browser response is lost.
                response = route.fetch(); assert response.ok; route.abort()
            else: route.continue_()
        page.route(url,intercept)
        if failure=='cas': _save_profile(context,live_server,code,[(key,'UNIFORM','','')])
        if failure.endswith('readback'):
            def wrong_readback(route):
                response=route.fetch(); body=response.json()
                if key in body['saved']['rows']:
                    if failure=='explicit-readback': body['saved']['rows'][key]['explicit']='0,'+','.join(['100']+['0']*(prof['months']-2))
                    else: body['saved']['rows'][key]['milestone']='1'
                route.fulfill(response=response,json=body)
            page.route('**/v2/model-react/capex/profiles?*',wrong_readback)
        page.locator('[data-capex-save]').click()
        page.wait_for_selector('[data-capex-status]')
        assert shape.input_value() == ('MILESTONE' if failure=='milestone-readback' else 'EXPLICIT')
        assert len(calls)==1
        if failure in ('csrf','cas'):
            assert page.locator('[data-capex-status]').get_attribute('data-capex-status')=='error'
            assert page.locator('[data-capex-save]').is_disabled()
        else:
            page.wait_for_selector('[data-pr2b-draft-state="unknown"]')
            assert shape.is_disabled() and page.locator('[data-capex-save]').is_disabled()
            page.unroute('**/v2/model-react/capex/profiles?*')
            page.locator('[data-pr2b-reconcile]').click()
            page.wait_for_selector('[data-capex-status="ok"]')
            assert len(calls)==1 and shape.is_enabled()
    finally: context.close()
