"""Synthetic real-browser block Save acceptance; canonical writers and real persistence."""
import copy
import json
import os
from pathlib import Path
import pytest
from tests.model_react_rcm_financing_acceptance import fin_session, no_page_overflow

__all__=('fin_session','test_pr3b2_atomic_block_and_unchanged_run','test_pr3b2_stale_csrf_and_retry_keep_draft','test_pr3b2_unknown_outcome_replays_identical_request','test_pr3b2_bankability_draft_and_original_paths','test_pr3b2_scenario_guard_keeps_then_discards_only_on_confirmation','test_pr3b2_changed_bankability_keeps_local_draft_until_review')

def fields(context,base,code):
    return context.request.get(base+'/v2/model-react/fields/debt',params={'project':code}).json()

def open_inputs(page,base,code):
    page.goto(f'{base}/v2/model-react/{code}#financing')
    page.wait_for_selector('[data-financing-editing="true"]',timeout=60000)
    page.wait_for_function("() => document.querySelector('[data-financing-editing]').getAttribute('aria-busy') === 'false'")
    return page.locator('[data-financing-editing]')

def draft(rec):
    from app.persistence.workspace_repository import get_workspace_state
    w=get_workspace_state(rec.user_id,rec.project_id)
    return copy.deepcopy(w.draft_snapshot),w.last_runtime_snapshot_id,copy.deepcopy(w.last_runtime_summary)

@pytest.mark.parametrize('width',[1440,390,320])
def test_pr3b2_atomic_block_and_unchanged_run(live_server,fin_session,width):
    from tests.model_react_wf1_browser_acceptance import run_canonical
    context,page,rec,errors=fin_session('pr3b2-save-'+str(width),width=width)
    if width==1440:run_canonical(context,live_server,rec.project_code)
    before=draft(rec);writes=[]
    from app.services.reference_seed_service import create_reference_seeded_project
    other=create_reference_seeded_project(user_id=rec.user_id,template_source='generic_solar_reference',requested_name='PR3b2 isolated other project',capacity_mw=20.)
    other_before=draft(other)
    page.on('request',lambda r:writes.append(json.loads(r.post_data)) if r.method=='POST' and '/workbook/save-all' in r.url else None)
    root=open_inputs(page,live_server,rec.project_code)
    assert draft(rec)==before
    data=fields(context,live_server,rec.project_code)
    for fid,value in [('debt.senior.gearing_pct','77'),('debt.senior.interest_rate_pct','4.21')]:
        f=next(f for f in data['fields'] if f['field_id']==fid)
        assert f['binding_label']=='bound'
        root.get_by_label(f['label'],exact=True).fill(value)
    root.get_by_role('button',name='Save Structure & Terms',exact=True).click()
    root.get_by_text('Saved and read back:',exact=False).wait_for(timeout=60000)
    assert len(writes)==1 and len(writes[0]['cells'])==2
    assert {c['field_id'] for c in writes[0]['cells']}=={'debt.senior.gearing_pct','debt.senior.interest_rate_pct'}
    assert writes[0]['contracts_json'] is None and writes[0]['cost_lines']==[] and 'profile_json' not in writes[0]
    after=draft(rec);assert after[1:]==before[1:]
    fresh=fields(context,live_server,rec.project_code)
    intended={'debt.senior.gearing_pct','debt.senior.interest_rate_pct'}
    assert {f['field_id']:f['value'] for f in fresh['fields'] if f['binding_label']=='bound' and f['field_id'] not in intended}=={f['field_id']:f['value'] for f in data['fields'] if f['binding_label']=='bound' and f['field_id'] not in intended}
    assert draft(other)==other_before
    assert float(next(f['value'] for f in fresh['fields'] if f['field_id']=='debt.senior.interest_rate_pct'))==4.21
    assert float(next(f['value'] for f in fresh['fields'] if f['field_id']=='debt.senior.gearing_pct'))==77
    page.reload();root=page.locator('[data-financing-editing]');root.get_by_label('All-in Interest Rate',exact=True).wait_for(timeout=60000)
    assert float(root.get_by_label('All-in Interest Rate',exact=True).input_value())==4.21
    no_page_overflow(page)
    shots=os.environ.get('PR3B2_SCREENSHOT_DIR')
    if shots:Path(shots).mkdir(parents=True,exist_ok=True);page.screenshot(path=str(Path(shots)/f'financing-{width}.png'),full_page=True)
    assert not [e for e in errors if 'Failed to load resource' not in e]

def test_pr3b2_stale_csrf_and_retry_keep_draft(live_server,fin_session):
    context,page,rec,errors=fin_session('pr3b2-refusal')
    root=open_inputs(page,live_server,rec.project_code);field=root.get_by_label('All-in Interest Rate',exact=True)
    field.fill('4.32');before=draft(rec)
    def reject(route):
        body=json.loads(route.request.post_data);body['csrf_token']='forged';route.continue_(post_data=json.dumps(body))
    page.route('**/v2/workbook/save-all',reject)
    root.get_by_role('button',name='Save Structure & Terms',exact=True).click()
    root.locator('[role="alert"]').first.wait_for(timeout=60000)
    assert field.input_value()=='4.32' and draft(rec)==before
    page.unroute('**/v2/workbook/save-all',reject)
    # A real competing canonical Save after the preflight read forces server CAS refusal.
    def race(route):
        body=json.loads(route.request.post_data)
        w=context.request.get(live_server+'/v2/model-react/workspace',params={'project':rec.project_code}).json()
        competing={**body,'request_id':'pr3b2-competitor','content_hash':w['workbook']['composite_hash'],'csrf_token':w['save_all']['csrf_token'],
                   'cells':[{'field_id':'debt.senior.gearing_pct','value':'73'}]}
        assert context.request.post(live_server+'/v2/workbook/save-all',data=competing).status==200
        route.continue_()
    page.route('**/v2/workbook/save-all',race)
    with page.expect_response(lambda r:'/workbook/save-all' in r.url and r.status==409):root.get_by_role('button',name='Save Structure & Terms',exact=True).click()
    assert field.input_value()=='4.32'
    page.unroute('**/v2/workbook/save-all',race)
    root.get_by_role('button',name='Reload saved values',exact=True).click()
    page.wait_for_function("() => document.querySelector('[data-financing-editing]').getAttribute('aria-busy') === 'false'")
    root.get_by_role('button',name='Save Structure & Terms',exact=True).click()
    root.get_by_text('Saved and read back:',exact=False).wait_for(timeout=60000)
    assert float(next(f['value'] for f in fields(context,live_server,rec.project_code)['fields'] if f['field_id']=='debt.senior.gearing_pct'))==73

def test_pr3b2_unknown_outcome_replays_identical_request(live_server,fin_session):
    context,page,rec,errors=fin_session('pr3b2-unknown')
    root=open_inputs(page,live_server,rec.project_code);root.get_by_label('All-in Interest Rate',exact=True).fill('4.43');bodies=[]
    def lose(route):
        bodies.append(route.request.post_data);response=route.fetch();assert response.status==200;route.abort()
    page.route('**/v2/workbook/save-all',lose)
    root.get_by_role('button',name='Save Structure & Terms',exact=True).click()
    root.get_by_role('button',name='Check and retry identical Save').wait_for(timeout=60000)
    page.unroute('**/v2/workbook/save-all',lose)
    page.on('request',lambda r:bodies.append(r.post_data) if r.method=='POST' and '/workbook/save-all' in r.url else None)
    root.get_by_role('button',name='Check and retry identical Save').click()
    root.get_by_text('Saved and read back:',exact=False).wait_for(timeout=60000)
    assert len(bodies)==2 and bodies[0]==bodies[1]

def test_pr3b2_bankability_draft_and_original_paths(live_server,fin_session):
    context,page,rec,errors=fin_session('pr3b2-bank')
    root=open_inputs(page,live_server,rec.project_code)
    root.get_by_text('Advanced · Bankability, repayment profile, fees & reserves',exact=True).click()
    bank=root.locator('[data-bankability-editor]');bank.locator('[data-bank="sizing_mode"]').select_option('gearing_cap')
    page.locator('[data-financing-read-link][data-financing-tab-button="terms"]').click()
    page.get_by_role('button',name='Stay and keep editing').click()
    assert bank.locator('[data-bank="sizing_mode"]').input_value()=='gearing_cap'
    bank.get_by_role('button',name='Save bankability',exact=True).click()
    bank.get_by_text('saved and read back',exact=False).wait_for(timeout=60000)
    for view,marker in [('terms','[data-sheet-editor="debt"]'),('overview','[data-financing-overview]'),('debt-metrics','[data-debt-metrics],[data-dm-empty]'),('bankability','[data-bankability-editor]'),('facilities','[data-capital-stack]'),('sources-uses','[data-sources-uses]'),('investors','[data-investors-panel]')]:
        page.goto(f'{live_server}/v2/model-react/{rec.project_code}?financing={view}#financing');page.wait_for_selector(marker,timeout=60000)

def test_pr3b2_scenario_guard_keeps_then_discards_only_on_confirmation(live_server,fin_session):
    context,page,rec,errors=fin_session('pr3b2-scenario')
    root=open_inputs(page,live_server,rec.project_code);original=root.get_by_label('All-in Interest Rate',exact=True).input_value()
    financing_writes=[]
    page.on('request',lambda r:financing_writes.append(r.url) if r.method=='POST' and any(p in r.url for p in ('/workbook/save-all','/workbook/update','/workbook/investor/')) else None)
    before=draft(rec);root.get_by_label('All-in Interest Rate',exact=True).fill('4.54')
    page.evaluate("location.hash='#scenarios'")
    page.get_by_role('button',name='Stay and keep editing').click()
    assert root.get_by_label('All-in Interest Rate',exact=True).input_value()=='4.54'
    page.evaluate("location.hash='#scenarios'")
    page.get_by_role('button',name='Discard changes and continue').click()
    page.get_by_label('New scenario name').fill('PR3b2 isolated scenario')
    page.get_by_role('button',name='Create scenario',exact=True).click()
    page.wait_for_function("() => document.querySelector('[data-active-scenario-banner]').innerText.includes('PR3b2 isolated scenario')")
    page.evaluate("location.hash='#financing'")
    page.wait_for_selector('[data-financing-editing]',timeout=60000)
    assert root.get_by_label('All-in Interest Rate',exact=True).input_value()==original
    after=draft(rec)
    # The unchanged scenario redirect has separate Revenue normalization (baseline
    # replay retained privately). Pin every Financing input and every Run record.
    from app.workbook.registry import WORKBOOK
    keys={v for k,v in WORKBOOK.field_id_to_snapshot_key().items() if k.startswith('debt.')}
    assert {k:after[0].get(k) for k in keys}=={k:before[0].get(k) for k in keys}
    assert not financing_writes
    assert after[1:]==before[1:]

def test_pr3b2_changed_bankability_keeps_local_draft_until_review(live_server,fin_session):
    context,page,rec,errors=fin_session('pr3b2-bank-race')
    root=open_inputs(page,live_server,rec.project_code)
    root.get_by_text('Advanced · Bankability, repayment profile, fees & reserves',exact=True).click()
    bank=root.locator('[data-bankability-editor]');bank.locator('[data-bank="sizing_mode"]').select_option('gearing_cap')
    other=context.new_page();other.goto(f'{live_server}/v2/model-react/{rec.project_code}?financing=bankability#financing')
    other.locator('[data-bank="day_count"]').select_option('act_360')
    other.get_by_role('button',name='Save bankability',exact=True).click()
    other.get_by_text('saved and read back',exact=False).wait_for(timeout=60000)
    before=draft(rec)
    bank.get_by_role('button',name='Save bankability',exact=True).click()
    bank.get_by_text('changed after this view loaded',exact=False).wait_for(timeout=60000)
    assert bank.locator('[data-bank="sizing_mode"]').input_value()=='gearing_cap' and draft(rec)==before
    root.get_by_role('button',name='Reload saved values',exact=True).click()
    bank.get_by_role('button',name='Keep draft against refreshed configuration').wait_for(timeout=60000)
    assert bank.locator('[data-bank="sizing_mode"]').input_value()=='gearing_cap'
    assert bank.get_by_role('button',name='Save bankability',exact=True).is_disabled()
    bank.get_by_role('button',name='Discard changes',exact=True).click()
    assert bank.locator('[data-bank="day_count"]').input_value()=='act_360' and draft(rec)==before
    other.close()
