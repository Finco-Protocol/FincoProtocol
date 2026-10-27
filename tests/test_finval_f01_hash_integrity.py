"""Correction A: provenance reconciliation must never store a stale supplied hash."""
import json,sqlite3
import pytest
from app.input_adapter import RATE_UNIT_KEY,RATE_UNIT
from app.workbook.input_set import ProjectInputSet
from tests.test_finval_rate_contract import env,USER,_prime,_ws


def row(env,rec):
    with sqlite3.connect(env.db_path) as c:
        return c.execute('SELECT * FROM workspace_states WHERE project_id=?',(rec.project_id,)).fetchone()


def stored_hash(env,rec):
    with sqlite3.connect(env.db_path) as c:
        return c.execute('SELECT draft_content_hash FROM workspace_states WHERE project_id=?',(rec.project_id,)).fetchone()[0]


def persist(rec,draft,saved,hint):
    from app.persistence.workspace_repository import save_workspace_state
    return save_workspace_state(user_id=USER,project_id=rec.project_id,project_code=rec.project_code,
        draft_snapshot=draft,saved_snapshot=saved,v2_draft_content_hash=hint)

@pytest.mark.parametrize('omitted',[(RATE_UNIT_KEY,),('_finval_interest_rate_origin',),(RATE_UNIT_KEY,'_finval_interest_rate_origin'),()])
def test_stale_supplied_hash_is_typed_refusal_and_rolls_back_every_column(env,omitted):
    rec=env.create();_prime(env,rec);ws=_ws(rec)
    draft={**ws.draft_snapshot,'interest_rate_pct':'.056'}
    for key in omitted:draft.pop(key,None)
    hint=ProjectInputSet.from_snapshot(draft).content_hash if omitted else '0'*64
    before=row(env,rec)
    with pytest.raises(ValueError,match='RATE_UNIT_CONTENT_HASH_MISMATCH') as error:
        persist(rec,draft,ws.saved_snapshot,hint)
    assert getattr(error.value,'code',None)=='RATE_UNIT_CONTENT_HASH_MISMATCH'
    assert row(env,rec)==before


def test_correct_final_snapshot_hash_is_kept_after_unit_and_origin_preservation(env):
    rec=env.create();_prime(env,rec);ws=_ws(rec)
    final={**ws.draft_snapshot,'interest_rate_pct':'.056'}
    hint=ProjectInputSet.from_snapshot(final).content_hash
    incoming={k:v for k,v in final.items() if k not in (RATE_UNIT_KEY,'_finval_interest_rate_origin')}
    persist(rec,incoming,ws.saved_snapshot,hint)
    after=_ws(rec)
    assert after.draft_snapshot==final
    assert after.draft_snapshot[RATE_UNIT_KEY]==RATE_UNIT
    assert stored_hash(env,rec)==ProjectInputSet.from_snapshot(after.draft_snapshot).content_hash==hint

@pytest.mark.parametrize('valid',[True,False])
def test_new_workspace_cannot_accept_a_false_rate_hash(env,valid):
    rec=env.create();_prime(env,rec);ws=_ws(rec)
    snapshot=ws.draft_snapshot;hint=ProjectInputSet.from_snapshot(snapshot).content_hash
    with sqlite3.connect(env.db_path) as c:c.execute('DELETE FROM workspace_states WHERE project_id=?',(rec.project_id,))
    assert row(env,rec) is None
    if valid:
        persist(rec,snapshot,snapshot,hint)
        assert stored_hash(env,rec)==hint
    else:
        with pytest.raises(ValueError,match='RATE_UNIT_CONTENT_HASH_MISMATCH'):
            persist(rec,snapshot,snapshot,'0'*64)
        assert row(env,rec) is None


def test_ambiguous_legacy_rate_cannot_be_changed_even_without_a_hash_hint(env):
    from tests.test_fin_val_b2_c1_recovery_finite_opex import _poison
    from app.input_adapter import RateUnitProvenanceError
    rec=env.create();_prime(env,rec);_poison(env,rec,RATE_UNIT_KEY,None)
    ws=_ws(rec);before=row(env,rec)
    with pytest.raises(RateUnitProvenanceError):
        persist(rec,{**ws.draft_snapshot,'interest_rate_pct':'.056'},ws.saved_snapshot,None)
    assert row(env,rec)==before
    # Unrelated safe persistence retains the exact ambiguous rate, never labels it.
    persist(rec,{**ws.draft_snapshot,'scenario':'Base'},ws.saved_snapshot,None)
    assert _ws(rec).draft_snapshot==ws.draft_snapshot


def test_concurrent_save_and_new_clones_keep_distinct_identity_and_source_provenance(env):
    from concurrent.futures import ThreadPoolExecutor
    from app.services.project_library_service import create_working_copy
    from app.persistence.projects_repository import get_reference_by_template_source
    from tests.test_finval_rate_contract import _save
    rec=env.create();_prime(env,rec)
    source=get_reference_by_template_source('generic_solar_reference')
    def protected_rows():
        with sqlite3.connect(env.db_path) as c:
            return (c.execute('SELECT * FROM projects WHERE project_id=?',(source.project_id,)).fetchone(),
                    c.execute('SELECT * FROM workspace_states WHERE project_id=?',(source.project_id,)).fetchone())
    before=protected_rows()
    with ThreadPoolExecutor(max_workers=3) as pool:
        saved=pool.submit(_save,env,rec,.056,'batch')
        a=pool.submit(create_working_copy,USER,source.project_id,'F01 concurrent clone A')
        b=pool.submit(create_working_copy,USER,source.project_id,'F01 concurrent clone B')
        saved.result();copies=[a.result(),b.result()]
    assert len({rec.project_id,*[c.project_id for c in copies]})==3
    assert _ws(rec).draft_snapshot[RATE_UNIT_KEY]==RATE_UNIT
    assert float(_ws(rec).draft_snapshot['interest_rate_pct'])==.056
    for clone in copies:
        ws=_ws(clone)
        assert ws.draft_snapshot[RATE_UNIT_KEY]==RATE_UNIT
        assert ws.draft_snapshot['_finval_interest_rate_origin']['source_project_id']==source.project_id
        assert ws.draft_snapshot['active_project']==clone.project_code
    assert protected_rows()==before


def test_current_unit_ambiguity_preserves_committed_history_and_safe_detail_reads(env):
    from tests.test_finval_rate_contract import _save
    from tests.test_finval_rate_run_acceptance import _run
    from tests.test_fin_val_b2_c1_recovery_finite_opex import _poison
    rec=env.create();_prime(env,rec);_save(env,rec,.56);_run(env,rec,True)
    def history():
        with sqlite3.connect(env.db_path) as c:
            return c.execute('SELECT * FROM model_run_history WHERE project_id=?',(rec.project_id,)).fetchall()
    before=history();assert len(before)==1
    _poison(env,rec,RATE_UNIT_KEY,None)
    listing=env.client.get('/v2/workbook/run-history',params={'project':rec.project_code})
    assert listing.status_code==200
    detail=env.client.get('/v2/workbook/run-history/detail',params={'project':rec.project_code,'history_id':before[0][0]})
    assert detail.status_code==200
    assert history()==before
