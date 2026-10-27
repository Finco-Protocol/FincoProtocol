"""FIN-VAL rate-unit regression: no engine/golden/tolerance changes."""
from dataclasses import replace
import pytest
from app.input_adapter import _resolve_user_inputs, senior_rate_authority
from app.persistence.projects_repository import _compute_baseline_snapshot
from app.workbook.input_set import ProjectInputSet
from app.v2.router import _build_sheet_fields
from app import project_factories as factories

KINDS=('solar','wind','data_center','ev_charging')
TYPES=('Solar','Wind','Data Center','EV Charging')

@pytest.mark.parametrize('kind,project_type',zip(KINDS,TYPES))
def test_new_baseline_rate_is_human_percent(kind,project_type):
    pi=getattr(factories,'create_generic_'+kind+'_reference')()
    snap=_compute_baseline_snapshot(project_type,'generic_'+kind+'_reference')
    assert float(snap['interest_rate_pct']) == senior_rate_authority(pi)[1]*100

@pytest.mark.parametrize('human,ratio',[(.055,.00055),(.056,.00056),(.56,.0056),(5.6,.056),(9.,.09)])
def test_explicit_human_percent_is_converted_once_even_if_equal_to_factory_ratio(human,ratio):
    pi=factories.create_generic_solar_reference()
    result=_resolve_user_inputs(project_type='Solar',base_inputs=pi,interest_rate_pct=human)
    assert senior_rate_authority(result)[1] == pytest.approx(ratio,abs=1e-17)

@pytest.mark.parametrize('human',[.056,.56,5.6,9.])
def test_rate_display_has_no_magnitude_inference(human):
    snap=_compute_baseline_snapshot('Solar','generic_solar_reference');snap['interest_rate_pct']=str(human)
    row=next(r for r in _build_sheet_fields('debt',ProjectInputSet.from_snapshot(snap)) if r['field_id']=='debt.senior.interest_rate_pct')
    assert row['value']==human
    # User percentages, including sub-one percentages, are never multiplied by 100 for display.
    assert row['display_value']==f'{human:.3f}'.rstrip('0').rstrip('.')+'%'

from tests.test_fin_val_b2_c1_recovery_finite_opex import (
    env, USER, _prime, _ws, _snapshot,
)
from app.input_adapter import RATE_UNIT, RATE_UNIT_KEY, build_projectinputs_from_snapshot
from app.workbook.update_service import WorkbookUpdateService, FieldValidationError
from app.workbook.service import WorkbookService
from app.workbook.registry import WORKBOOK
import copy, hashlib, json, os, uuid
from pathlib import Path

RATE_FIELD='debt.senior.interest_rate_pct'

def _save(env,record,human,mode='single',hash_override=None):
    ws=_ws(record);pis=ProjectInputSet.from_snapshot(ws.draft_snapshot)
    projection=env.client.get('/v2/model-react/fields/debt',params={'project':record.project_code}).json()
    if mode=='batch':
        return WorkbookUpdateService.apply_batch_draft_update(ws=ws,
            updates=[(RATE_FIELD,str(human))], content_hash=hash_override or projection['save']['content_hash'],
            workbook_version=WORKBOOK.version,expected_scenario_id=ws.active_scenario_id,
            project_record=record,actor_user_id=USER)
    projection=env.client.get('/v2/model-react/fields/debt',params={'project':record.project_code}).json()
    response=env.client.post('/v2/workbook/update',headers={'HX-Request':'true'},data={
        'project':record.project_code,'field_id':RATE_FIELD,'value':str(human),
        'content_hash':hash_override or projection['save']['content_hash'],
        'workbook_version':projection['save']['workbook_version'],
        'csrf_token':projection['save']['csrf_token']})
    assert response.status_code==200,response.text[:300]
    return response

def _emit(name,obj):
    folder=os.getenv('FINVAL_EVIDENCE_DIR')
    if folder:
        Path(folder).mkdir(parents=True,exist_ok=True)
        (Path(folder)/(name+'.json')).write_text(json.dumps(obj,indent=2,default=str))

@pytest.mark.parametrize('kind',KINDS)
@pytest.mark.parametrize('mode',['single','batch'])
def test_clone_display_save_reload_typed_four_rates(env,kind,mode):
    record=env.create(kind,capacity=20);_prime(env,record)
    assert _snapshot(record)[RATE_UNIT_KEY]==RATE_UNIT
    for human in [.056,.56,5.6,9.]:
        _save(env,record,human,mode)
        snap=_snapshot(record);assert float(snap['interest_rate_pct'])==human
        assert snap[RATE_UNIT_KEY]==RATE_UNIT
        typed=ProjectInputSet.from_snapshot(snap).to_projectinputs()
        assert senior_rate_authority(typed)[1]==pytest.approx(human/100,abs=1e-17)
        row=next(r for r in env.client.get('/v2/model-react/fields/debt',params={'project':record.project_code}).json()['fields'] if r['field_id']==RATE_FIELD)
        assert row['value']==human
        assert row['display_value']==f'{human:.12g}%'

@pytest.mark.parametrize('unit',[None,'ratio','ratio_v0','human_percent_v2',True])
def test_ambiguous_or_forged_snapshot_unit_is_not_reinterpreted(unit):
    snap=_compute_baseline_snapshot('Solar','generic_solar_reference')
    if unit is None:snap.pop(RATE_UNIT_KEY)
    else:snap[RATE_UNIT_KEY]=unit
    original=copy.deepcopy(snap)
    with pytest.raises(ValueError,match='INTEREST_RATE_UNIT_UNVERIFIED'):
        build_projectinputs_from_snapshot(snap)
    assert snap==original

@pytest.mark.parametrize('value',[float('nan'),float('inf'),-1,21,True])
def test_invalid_rate_fail_closed(value):
    from app.input_adapter import _set_financing_interest_rate
    with pytest.raises(ValueError):_set_financing_interest_rate(factories.create_generic_solar_reference(),value)

def test_calibrated_typed_schedule_is_preserved():
    from app.input_adapter import _set_financing_interest_rate
    pi=factories.create_generic_solar_reference();cfg=pi.financing.senior_debt_interest_config
    rs=replace(cfg.rate_schedule,explicit_all_in_rates=(.05,.06)*15)
    pi=replace(pi,financing=replace(pi.financing,senior_debt_interest_config=replace(cfg,rate_schedule=rs)))
    assert _set_financing_interest_rate(pi,9.) is pi

@pytest.mark.parametrize('kind',KINDS)
def test_resaving_same_economic_rate_keeps_typed_authority_bit_identical(kind):
    pi=getattr(factories,'create_generic_'+kind+'_reference')()
    value=senior_rate_authority(pi)[1]*100
    assert _resolve_user_inputs(project_type='Solar',base_inputs=pi,interest_rate_pct=value)==pi

def test_bankability_schedule_owns_rate_and_scalar_edit_is_refused():
    from app.input_adapter import assert_debt_scalar_edit_allowed
    snap=_compute_baseline_snapshot('Solar','generic_solar_reference')
    snap['bankability_config_json']=json.dumps({'version':1,'rates_pct':[6.0]*30})
    pis=ProjectInputSet.from_snapshot(snap)
    assert senior_rate_authority(pis.to_projectinputs())[1]==.06
    with pytest.raises(ValueError,match='configuration owns'):
        assert_debt_scalar_edit_allowed(pis,RATE_FIELD)

@pytest.mark.parametrize('mode',['single','batch'])
def test_stale_rate_save_keeps_value_and_unit_together(env,mode):
    from app.workbook.update_service import StaleContentError
    record=env.create();_prime(env,record)
    old=env.client.get('/v2/model-react/fields/debt',params={'project':record.project_code}).json()['save']['content_hash']
    _save(env,record,5.6,mode)
    before=_snapshot(record)
    if mode=='batch':
        with pytest.raises((ValueError,StaleContentError)):_save(env,record,9.,mode,old)
    else:
        projection=env.client.get('/v2/model-react/fields/debt',params={'project':record.project_code}).json()
        r=env.client.post('/v2/workbook/update',headers={'HX-Request':'true'},data={
            'project':record.project_code,'field_id':RATE_FIELD,'value':'9',
            'content_hash':old,'workbook_version':WORKBOOK.version,'csrf_token':projection['save']['csrf_token']})
        assert r.status_code==200  # Existing HTMX error-envelope contract.
        event=json.loads(r.headers['HX-Trigger'])['workbook-field-error']
        assert event['conflict'] is True and 'not saved' in event['message']
    assert _snapshot(record)==before


def test_clone_never_changes_source_reference(env):
    from app.persistence.projects_repository import get_reference_by_template_source
    from app.persistence.workspace_repository import get_workspace_state
    env.create()
    source=get_reference_by_template_source('generic_solar_reference')
    before=copy.deepcopy((source.baseline_snapshot,get_workspace_state(source.user_id,source.project_id)))
    env.create(name='Second isolated copy')
    source2=get_reference_by_template_source('generic_solar_reference')
    assert (source2.baseline_snapshot,get_workspace_state(source2.user_id,source2.project_id))==before

def test_concurrent_rate_save_has_one_cas_winner_and_preserves_unit(env):
    from concurrent.futures import ThreadPoolExecutor
    from threading import Barrier
    from app.workbook.update_service import StaleContentError
    record=env.create();_prime(env,record);ws=_ws(record)
    token=env.client.get('/v2/model-react/fields/debt',params={'project':record.project_code}).json()['save']
    barrier=Barrier(2)
    def attempt(value):
        barrier.wait()
        try:
            WorkbookUpdateService.apply_draft_update(ws=ws,field_id=RATE_FIELD,raw_value=value,
                content_hash=token['content_hash'],workbook_version=token['workbook_version'],project_record=record)
            return 'saved'
        except StaleContentError:return 'stale'
    with ThreadPoolExecutor(max_workers=2) as pool:out=list(pool.map(attempt,['5.6','9.0']))
    assert sorted(out)==['saved','stale']
    snap=_snapshot(record);assert snap[RATE_UNIT_KEY]==RATE_UNIT
    assert float(snap['interest_rate_pct']) in (5.6,9.)

def test_repeated_save_and_materialization_never_converts_percent_twice(env):
    record=env.create();_prime(env,record)
    for mode in ['single','batch','single']:
        _save(env,record,.056,mode)
        snap=_snapshot(record);assert float(snap['interest_rate_pct'])==.056
        pis=ProjectInputSet.from_snapshot(snap)
        for _ in range(3):
            assert senior_rate_authority(pis.to_projectinputs())[1]==pytest.approx(.00056,abs=1e-17)
            assert float(pis.to_snapshot()['interest_rate_pct'])==.056


def test_unit_marker_cannot_be_mutated_as_a_registry_field(env):
    record=env.create();_prime(env,record);before=_snapshot(record)
    save=env.client.get('/v2/model-react/fields/debt',params={'project':record.project_code}).json()['save']
    response=env.client.post('/v2/workbook/update',data={
        'project':record.project_code,'field_id':RATE_UNIT_KEY,'value':'ratio',
        'content_hash':save['content_hash'],'workbook_version':save['workbook_version'],'csrf_token':save['csrf_token']},follow_redirects=False)
    assert response.status_code==422 and _snapshot(record)==before


def test_foreign_actor_cannot_change_rate_or_unit(env):
    record=env.create();_prime(env,record);before=_snapshot(record)
    save=env.client.get('/v2/model-react/fields/debt',params={'project':record.project_code}).json()['save']
    with env.as_user('foreign-rate-actor') as client:
        response=client.post('/v2/workbook/update',data={
            'project':record.project_code,'field_id':RATE_FIELD,'value':'9',
            'content_hash':save['content_hash'],'workbook_version':save['workbook_version'],'csrf_token':save['csrf_token']},follow_redirects=False)
        assert response.status_code in (403,404)
    assert _snapshot(record)==before

def test_old_reference_bootstrap_never_migrates_pricing_but_new_copy_is_canonical(env,monkeypatch):
    from app.persistence import projects_repository as projects
    from app.services import project_library_service as library
    from app.persistence.db import get_connection
    original=projects._compute_baseline_snapshot
    def historical_seed(project_type,template_source):
        snap=original(project_type,template_source)
        if RATE_UNIT_KEY in snap:
            snap['interest_rate_pct']=str(float(snap['interest_rate_pct'])/100)
            snap.pop(RATE_UNIT_KEY)
        return snap
    # Construct an old database using an explicit historical fixture producer;
    # no existing protected reference is modified by the fixture or correction.
    with monkeypatch.context() as mp:
        mp.setattr(projects,'_compute_baseline_snapshot',historical_seed)
        library.ensure_reference_models()
    def protected_rows():
        with get_connection() as conn:
            return {
                'projects':[tuple(r) for r in conn.execute("SELECT * FROM projects WHERE user_id='__reference__' ORDER BY project_id")],
                'workspaces':[tuple(r) for r in conn.execute("SELECT * FROM workspace_states WHERE user_id='__reference__' ORDER BY project_id")],
                'scenarios':[tuple(r) for r in conn.execute("SELECT * FROM scenarios WHERE user_id='__reference__' ORDER BY scenario_id")],
            }
    before=protected_rows()
    library.ensure_reference_models()
    assert protected_rows()==before
    for kind in KINDS:
        rec=env.create(kind)
        snap=_snapshot(rec)
        assert snap[RATE_UNIT_KEY]==RATE_UNIT
        pi=getattr(factories,'create_generic_'+kind+'_reference')()
        assert float(snap['interest_rate_pct'])==senior_rate_authority(pi)[1]*100
    assert protected_rows()==before
