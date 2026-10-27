"""F01 transitive legacy/atomic/source-proof acceptance; synthetic isolated data."""
import copy,json,sqlite3
from dataclasses import replace
from unittest.mock import patch
import pytest
from app.input_adapter import RATE_UNIT,RATE_UNIT_KEY,RateUnitProvenanceError,senior_rate_authority
from app.workbook.input_set import ProjectInputSet
from tests.test_finval_rate_contract import env,USER,KINDS,RATE_FIELD,_prime,_ws,_snapshot,_save

@pytest.mark.parametrize('kind,project_type',zip(KINDS,['Solar','Wind','Data Center','EV Charging']))
def test_legacy_producer_and_explicit_form_collection_keep_percent_contract(kind,project_type):
    from main_web import _project_baseline_snapshot,_collect_form_snapshot
    from app import project_factories as pf
    snap=_project_baseline_snapshot(project_type,'generic_'+kind+'_reference')
    pi=getattr(pf,'create_generic_'+kind+'_reference')()
    assert float(snap['interest_rate_pct'])==senior_rate_authority(pi)[1]*100
    assert snap[RATE_UNIT_KEY]==RATE_UNIT
    for human in [.056,.56,5.6,9.]:
        posted=_collect_form_snapshot({**snap,'interest_rate_pct':str(human)})
        assert posted[RATE_UNIT_KEY]==RATE_UNIT and float(posted['interest_rate_pct'])==human
        assert senior_rate_authority(ProjectInputSet.from_snapshot(posted).to_projectinputs())[1]==pytest.approx(human/100,abs=1e-17)


def test_legacy_collection_never_labels_missing_or_forged_provenance():
    from main_web import _collect_form_snapshot
    assert RATE_UNIT_KEY not in _collect_form_snapshot({'interest_rate_pct':'.056'})
    with pytest.raises(RateUnitProvenanceError):_collect_form_snapshot({'interest_rate_pct':'.056',RATE_UNIT_KEY:'ratio'})

@pytest.mark.parametrize('mode',['single','batch'])
def test_interrupted_write_rolls_back_value_provenance_and_hash(env,monkeypatch,mode):
    import app.persistence.workspace_repository as repo
    from app.workbook.update_service import WorkbookUpdateService
    record=env.create();_prime(env,record);ws=_ws(record)
    token=env.client.get('/v2/model-react/fields/debt',params={'project':record.project_code}).json()['save']
    def row():
        with sqlite3.connect(env.db_path) as conn:return conn.execute('SELECT * FROM workspace_states WHERE project_id=?',(record.project_id,)).fetchone()
    before=row()
    def interrupted(*a,**kw):raise RuntimeError('F01 injected interruption after UPDATE before COMMIT')
    monkeypatch.setattr(repo,'mirror_project_name_cursor',interrupted)
    with pytest.raises(RuntimeError,match='F01 injected'):
        if mode=='single':
            WorkbookUpdateService.apply_draft_update(ws=ws,field_id=RATE_FIELD,raw_value='9',content_hash=token['content_hash'],workbook_version=token['workbook_version'],project_record=record)
        else:_save(env,record,9.,'batch')
    assert row()==before


def test_clone_refuses_unproven_source_without_any_financial_write(env,monkeypatch):
    from app.services import project_library_service as library
    from app.persistence.projects_repository import get_reference_by_template_source
    env.create();source=get_reference_by_template_source('generic_solar_reference')
    fake=replace(source,baseline_snapshot={**source.baseline_snapshot,'interest_rate_pct':'.056'},replay_metadata={})
    # Present the copied workspace as unversioned through a read-only fake;
    # no actual protected source record is changed by this negative test.
    actual=library.get_workspace_state(source.user_id,source.project_id)
    old=replace(actual,draft_snapshot={**actual.draft_snapshot,RATE_UNIT_KEY:'ratio'},saved_snapshot={**actual.saved_snapshot,RATE_UNIT_KEY:'ratio'})
    monkeypatch.setattr(library,'get_project_by_id',lambda _:fake)
    original=library.get_workspace_state
    monkeypatch.setattr(library,'get_workspace_state',lambda owner,pid:old if pid==source.project_id else original(owner,pid))
    with sqlite3.connect(env.db_path) as c:before=c.execute('SELECT COUNT(*) FROM projects').fetchone()[0]
    with pytest.raises(RateUnitProvenanceError):library.create_working_copy(USER,source.project_id,'Refused copy')
    with sqlite3.connect(env.db_path) as c:assert c.execute('SELECT COUNT(*) FROM projects').fetchone()[0]==before


def test_ambiguous_projection_is_safe_read_and_save_is_typed_failure(env):
    from tests.test_fin_val_b2_c1_recovery_finite_opex import _poison
    rec=env.create();_prime(env,rec);_poison(env,rec,RATE_UNIT_KEY,'ratio')
    response=env.client.get('/v2/model-react/fields/debt',params={'project':rec.project_code})
    assert response.status_code==200
    data=response.json();field=next(f for f in data['fields'] if f['field_id']==RATE_FIELD)
    assert field['binding_label']=='partial' and field['rate_contract']['code']=='RATE_UNIT_PROVENANCE_AMBIGUOUS'
    before=copy.deepcopy(_snapshot(rec));save=data['save']
    result=env.client.post('/v2/workbook/update',headers={'HX-Request':'true'},data={'project':rec.project_code,'field_id':RATE_FIELD,'value':'.056','csrf_token':save['csrf_token'],'content_hash':save['content_hash'],'workbook_version':save['workbook_version']})
    assert result.headers['X-Finco-Error-Code']=='RATE_UNIT_PROVENANCE_AMBIGUOUS'
    assert _snapshot(rec)==before
    page=env.client.get('/v2/workbook',params={'project':rec.project_code})
    assert page.status_code==200 and 'workbook-recovery-page' in page.text
    assert 'owner-reviewed provenance repair' in page.text
    history=env.client.get('/v2/workbook/run-history',params={'project':rec.project_code})
    assert history.status_code==200
    assert _snapshot(rec)==before


def test_form_cannot_upgrade_or_replace_persisted_provenance():
    from app.input_adapter import preserve_rate_provenance
    canonical={'interest_rate_pct':'.056',RATE_UNIT_KEY:RATE_UNIT,'_finval_interest_rate_origin':{'source':'verified'}}
    assert preserve_rate_provenance(canonical,{'interest_rate_pct':'5.6'})=={**canonical,'interest_rate_pct':'5.6'}
    for incoming in ({'interest_rate_pct':'.056',RATE_UNIT_KEY:'ratio'},
                     {**canonical,'_finval_interest_rate_origin':{'source':'forged'}}):
        with pytest.raises(RateUnitProvenanceError):preserve_rate_provenance(canonical,incoming)
    with pytest.raises(RateUnitProvenanceError):
        preserve_rate_provenance({'interest_rate_pct':'.056'},canonical)
    old={'interest_rate_pct':'.056'}
    assert preserve_rate_provenance(old,old)==old


def test_legacy_full_snapshot_write_preserves_contract_and_refuses_client_relabel(env):
    from app.persistence.workspace_repository import save_workspace_state
    from tests.test_fin_val_b2_c1_recovery_finite_opex import _poison
    rec=env.create();_prime(env,rec);ws=_ws(rec)
    draft=dict(ws.draft_snapshot);saved=dict(ws.saved_snapshot)
    draft.pop(RATE_UNIT_KEY);draft.pop('_finval_interest_rate_origin',None)
    saved.pop(RATE_UNIT_KEY);saved.pop('_finval_interest_rate_origin',None)
    def persist(draft,saved):
        return save_workspace_state(user_id=USER,project_id=rec.project_id,project_code=rec.project_code,draft_snapshot=draft,saved_snapshot=saved)
    persist(draft,saved)
    restored=_ws(rec)
    assert restored.draft_snapshot[RATE_UNIT_KEY]==RATE_UNIT
    assert restored.saved_snapshot[RATE_UNIT_KEY]==RATE_UNIT
    assert restored.draft_snapshot['_finval_interest_rate_origin']==ws.draft_snapshot['_finval_interest_rate_origin']
    _poison(env,rec,RATE_UNIT_KEY,'ratio')
    def row():
        with sqlite3.connect(env.db_path) as c:return c.execute('SELECT * FROM workspace_states WHERE project_id=?',(rec.project_id,)).fetchone()
    before=row()
    with pytest.raises(RateUnitProvenanceError):persist(ws.draft_snapshot,ws.saved_snapshot)
    assert row()==before


def test_direct_snapshot_converter_cannot_bypass_saved_unit_authority():
    from app.persistence.projects_repository import _compute_baseline_snapshot
    from app.input_adapter import _snapshot_to_dict
    snap=_compute_baseline_snapshot('Solar','generic_solar_reference')
    snap.pop(RATE_UNIT_KEY)
    before=copy.deepcopy(snap)
    with pytest.raises(RateUnitProvenanceError):_snapshot_to_dict(snap)
    assert snap==before
