"""Independent mutation authority: real private reference fixtures and complete logical DB snapshots."""
import hashlib
import json
from types import SimpleNamespace

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from app import auth
from app.persistence import db
from app.workbook.mutation_csrf import mutation_token, validate_mutation_token, OPERATIONS
from tests.test_model_react_ux040506_v1 import env as run_env


def snapshot():
    """All tables, all columns, schema and row counts; no timestamps are ignored."""
    with db.get_connection() as connection:
        schema=[tuple(r) for r in connection.execute("SELECT type,name,tbl_name,sql FROM sqlite_master ORDER BY type,name")]
        tables={}
        for row in connection.execute("SELECT name FROM sqlite_master WHERE type='table' ORDER BY name"):
            name=row[0]
            values=[tuple(r) for r in connection.execute('SELECT * FROM "'+name.replace('"','""')+'"')]
            tables[name]=sorted(values,key=lambda r:json.dumps(r,default=str))
    return hashlib.sha256(json.dumps([schema,tables],sort_keys=True,default=str).encode()).hexdigest()


@pytest.fixture
def secured(tmp_path,monkeypatch):
    monkeypatch.setenv('FINCO_WORKBOOK_V2','1')
    monkeypatch.setenv('FINCO_MODEL_REACT_V1','1')
    monkeypatch.setattr(db,'DB_PATH',str(tmp_path/'mutation.db'));db.init_db()
    from app.services.project_library_service import ensure_reference_models,create_working_copy
    from app.persistence.projects_repository import get_reference_by_template_source
    from app.v2.router import router
    from app.v2.capex_router import capex_router
    from app.v2.opex_router import opex_router
    from app.v2.grid_router import router as grid_router
    from app.v2.react_workspace_router import router as workspace_router
    from app.library.router import router as library_router
    def no_engine(*a,**kw):pytest.fail('scenario/request-security path executed the financial engine')
    monkeypatch.setattr('app.api.project_runner.run_project',no_engine)
    monkeypatch.setattr('app.services.production_financial_authority.run_clean_production',no_engine)
    ensure_reference_models()
    app=FastAPI();app.include_router(router,prefix='/v2');app.include_router(capex_router,prefix='/v2/capex');app.include_router(opex_router,prefix='/v2/opex')
    app.include_router(grid_router,prefix='/v2');app.include_router(workspace_router,prefix='/v2');app.include_router(library_router)
    owner='mutation-security-owner';cookie=auth.create_session_token(user_id=owner,username='ordinary-local-fixture')
    with TestClient(app) as client:
        client.cookies.set(auth.COOKIE_NAME,cookie)
        def token(project,operation,*,session=None):
            return mutation_token(SimpleNamespace(cookies={auth.COOKIE_NAME:session or cookie},state=SimpleNamespace()),project,operation)
        def create(kind='solar',actor=owner):
            ref=get_reference_by_template_source('generic_'+kind+'_reference')
            return create_working_copy(actor,ref.project_id,requested_name='Mutation '+kind)
        yield SimpleNamespace(client=client,owner=owner,cookie=cookie,token=token,create=create,ref=get_reference_by_template_source)


def identity(record,owner):
    from app.workbook.registry import WORKBOOK
    from app.workbook.workbook_identity import assemble_consistent_for_get
    return {'project':record.project_code,'content_hash':assemble_consistent_for_get(owner,record.project_id,WORKBOOK.version).composite_hash,'workbook_version':WORKBOOK.version}


def child(record,owner):
    from app.persistence.scenarios_repository import get_base_case_scenario,add_scenario
    base=get_base_case_scenario(owner,record.project_id)
    return add_scenario(user_id=owner,project_id=record.project_id,project_code=record.project_code,scenario_name='Owned child',parent_scenario_id=base.scenario_id,base_input_set=base.base_input_set,overrides={})


@pytest.mark.parametrize('kind',['solar','wind'])
@pytest.mark.parametrize('op',['create','select','rename','archive','update-overrides','remove-override'])
def test_real_reference_mutations_refused_with_complete_snapshot(secured,kind,op):
    from app.persistence.scenarios_repository import get_base_case_scenario
    from app.services.project_library_service import is_protected_reference
    ref=secured.ref('generic_'+kind+'_reference');base=get_base_case_scenario(ref.user_id,ref.project_id)
    assert ref.user_id=='__reference__' and is_protected_reference(ref) and base.is_base_case
    projection=secured.client.get('/v2/model-react/scenarios',params={'project':ref.project_code}).json()
    assert any(s['scenario_id']==base.scenario_id for s in projection['scenarios'])
    data={'project':ref.project_code,'scenario_id':base.scenario_id,'scenario_name':'Denied','new_name':'Denied','tariff_eur_mwh':'95','field':'tariff_eur_mwh','csrf_token':secured.token(ref.project_code,'scenario-'+op)}
    before=snapshot();response=secured.client.post('/v2/workbook/scenarios/'+op,data=data,follow_redirects=False)
    assert response.status_code==409 and snapshot()==before


@pytest.mark.parametrize('kind',['solar','wind'])
def test_owned_workflow_and_foreign_archive_base_denials(secured,kind):
    from app.persistence.scenarios_repository import list_scenarios,get_base_case_scenario,get_scenario
    record=secured.create(kind);p=record.project_code
    def post(op,**values):return secured.client.post('/v2/workbook/scenarios/'+op,data={'project':p,'csrf_token':secured.token(p,'scenario-'+op),**values},follow_redirects=False)
    assert post('create',scenario_name='Child').status_code==303
    sc=next(s for s in list_scenarios(secured.owner,record.project_id) if s.scenario_name=='Child')
    assert post('rename',scenario_id=sc.scenario_id,new_name='Renamed').status_code==303
    assert get_scenario(sc.scenario_id,secured.owner).scenario_name=='Renamed'
    assert post('select',scenario_id=sc.scenario_id).status_code==303
    assert post('update-overrides',scenario_id=sc.scenario_id,tariff_eur_mwh='95').status_code==303
    assert get_scenario(sc.scenario_id,secured.owner).overrides['tariff_eur_mwh']==95
    assert post('remove-override',scenario_id=sc.scenario_id,field='tariff_eur_mwh').status_code==303
    assert 'tariff_eur_mwh' not in get_scenario(sc.scenario_id,secured.owner).overrides
    base=get_base_case_scenario(secured.owner,record.project_id)
    for op in ['rename','archive']:
        before=snapshot();assert post(op,scenario_id=base.scenario_id,new_name='No').status_code==409;assert snapshot()==before
    assert post('archive',scenario_id=sc.scenario_id).status_code==303
    before=snapshot();assert post('select',scenario_id=sc.scenario_id).status_code==404;assert snapshot()==before
    secured.client.cookies.set(auth.COOKIE_NAME,auth.create_session_token(user_id='foreign-private-owner',username='foreign'))
    for op in ['select','rename','archive']:
        before=snapshot();assert post(op,scenario_id=base.scenario_id,new_name='No').status_code==404;assert snapshot()==before


def request_spec(env,record,operation):
    p=record.project_code;data=identity(record,env.owner)
    if operation.startswith('scenario-'):
        sc=child(record,env.owner)
        data.update(scenario_id=sc.scenario_id,scenario_name='Attempt',new_name='Attempt',tariff_eur_mwh='95',field='tariff_eur_mwh')
        return '/v2/workbook/scenarios/'+operation.removeprefix('scenario-'),data,False
    if operation.startswith(('capex-','opex-')):
        kind,op=operation.split('-',1)
        data.update(label='Attempt',amount_keur='1',sub_line_id='unknown-row',row_version='unknown-version',parent_category_code='C.01',parent_group_code='B.09',kind='capex',contingency_pct='5')
        return '/v2/'+kind+('/contingency' if op=='contingency' else '/line/'+op),data,False
    if operation=='workbook-update':
        data.update(field_id='debt.senior.gearing_pct',value='65',sheet_id='debt')
        return '/v2/workbook/update',data,False
    if operation=='grid-save':
        data.update(cells=[{'field_id':'debt.senior.gearing_pct','value':'65'}])
        return '/v2/workbook/grid/save',data,True
    if operation=='grid-cost-lines-save':
        data.update(sheet='capex',payload='[]')
        return '/v2/workbook/grid/cost-lines/save',data,False
    return ('/v2/reference-seed/reset' if operation=='reference-seed-reset' else '/v2/workbook/export'),data,False


@pytest.mark.parametrize('operation',sorted(OPERATIONS))
def test_each_operation_rejects_missing_invalid_cross_scope_tokens_without_writes(secured,operation,monkeypatch):
    record=secured.create();url,data,is_json=request_spec(secured,record,operation)
    for bad in ['missing','invalid','generic','wrong_session','wrong_project','wrong_operation','expired']:
        values=dict(data)
        if bad=='missing':values['csrf_token']='' # JSON field remains structurally valid to exercise its refusal gate.
        elif bad=='invalid':values['csrf_token']='invalid'
        elif bad=='generic':values['csrf_token']=auth.generate_csrf_token()
        elif bad=='wrong_session':values['csrf_token']=secured.token(record.project_code,operation,session=auth.create_session_token(user_id=secured.owner,username='another-session'))
        elif bad=='wrong_project':values['csrf_token']=secured.token('other-project',operation)
        elif bad=='wrong_operation':values['csrf_token']=secured.token(record.project_code,'workbook-export' if operation!='workbook-export' else 'grid-save')
        else:
            import itsdangerous.timed
            with monkeypatch.context() as clock:
                clock.setattr(itsdangerous.timed.TimestampSigner,'get_timestamp',lambda self:1)
                values['csrf_token']=secured.token(record.project_code,operation)
        before=snapshot();response=secured.client.post(url,**({'json':values} if is_json else {'data':values}),follow_redirects=False)
        assert response.status_code==403,(operation,bad,response.status_code,response.text[:200])
        assert snapshot()==before,(operation,bad)


@pytest.mark.parametrize('kind',['capex','opex'])
def test_valid_cost_operation_retains_cas_and_row_version_checks(secured,kind):
    record=secured.create();p=record.project_code
    parent={'parent_category_code':'C.01'} if kind=='capex' else {'parent_group_code':'B.09'}
    old=identity(record,secured.owner)
    response=secured.client.post('/v2/'+kind+'/line/add',data={**old,**parent,'label':'Secure row','amount_keur':'1.25','csrf_token':secured.token(p,kind+'-add')},follow_redirects=False)
    assert response.status_code==303
    before=snapshot()
    response=secured.client.post('/v2/'+kind+'/line/add',data={**old,**parent,'label':'Stale row','amount_keur':'1.25','csrf_token':secured.token(p,kind+'-add')},follow_redirects=False)
    assert response.status_code==409 and snapshot()==before
    module=__import__('app.persistence.'+kind+'_sub_lines',fromlist=['list_sub_lines_for_project'])
    with db.get_cursor() as cursor:row=next(r for r in module.list_sub_lines_for_project(cursor,record.project_id,include_inactive=True) if r.label=='Secure row')
    for version,expected in [('not-current',409),(row.updated_at,303)]:
        before=snapshot()
        response=secured.client.post('/v2/'+kind+'/line/deactivate',data={**identity(record,secured.owner),'sub_line_id':row.sub_line_id,'row_version':version,'csrf_token':secured.token(p,kind+'-deactivate')},follow_redirects=False)
        assert response.status_code==expected
        if expected==409:assert snapshot()==before


def test_react_and_legacy_issue_usable_separate_tokens(secured):
    from bs4 import BeautifulSoup
    record=secured.create();p=record.project_code
    page=secured.client.get('/v2/workbook',params={'project':p})
    assert page.status_code==200
    soup=BeautifulSoup(page.text,'html.parser')
    form=soup.select_one('form[hx-post="/v2/workbook/scenarios/create"]')
    assert form and form.select_one('input[name="csrf_token"]')['value']
    scenarios=secured.client.get('/v2/model-react/scenarios',params={'project':p}).json()
    token=scenarios['mutations']['create']['csrf_token']
    req=SimpleNamespace(cookies={auth.COOKIE_NAME:secured.cookie},state=SimpleNamespace())
    assert validate_mutation_token(req,p,token,'scenario-create')
    assert not validate_mutation_token(req,p,token,'scenario-select')
    for endpoint,operation in [('inputs','grid-save'),('fields/debt','workbook-update'),('costlines','grid-cost-lines-save')]:
        payload=secured.client.get('/v2/model-react/'+endpoint,params={'project':p}).json()
        assert payload['ok'] and validate_mutation_token(req,p,payload['save']['csrf_token'],operation)


def test_real_htmx_scenario_create_and_select_render_usable_forms(secured):
    from bs4 import BeautifulSoup
    from app.persistence.scenarios_repository import list_scenarios
    record=secured.create();p=record.project_code
    response=secured.client.post('/v2/workbook/scenarios/create',data={'project':p,'scenario_name':'HTMX scenario','csrf_token':secured.token(p,'scenario-create')},headers={'HX-Request':'true'},follow_redirects=False)
    assert response.status_code==200,response.text[:300]
    soup=BeautifulSoup(response.text,'html.parser')
    form=soup.select_one('form[hx-post="/v2/workbook/scenarios/create"]')
    assert form and form.select_one('input[name="csrf_token"]')['value']
    sc=next(s for s in list_scenarios(secured.owner,record.project_id) if s.scenario_name=='HTMX scenario')
    response=secured.client.post('/v2/workbook/scenarios/select',data={'project':p,'scenario_id':sc.scenario_id,'csrf_token':secured.token(p,'scenario-select')},headers={'HX-Request':'true'},follow_redirects=False)
    assert response.status_code==200


def test_grid_bound_token_validation_save_and_stale_cas(secured):
    record=secured.create();p=record.project_code
    payload=secured.client.get('/v2/model-react/inputs',params={'project':p}).json()
    data={'project':p,'csrf_token':payload['save']['csrf_token'],'cells':[{'field_id':'debt.senior.gearing_pct','value':'66'}]}
    assert secured.client.post('/v2/workbook/grid/validate',json=data).status_code==200
    values={**data,'content_hash':payload['save']['content_hash'],'workbook_version':payload['save']['workbook_version'],'scenario_id':payload['save']['scenario_id']}
    assert secured.client.post('/v2/workbook/grid/save',json=values).status_code==200
    before=snapshot();assert secured.client.post('/v2/workbook/grid/save',json=values).status_code==409;assert snapshot()==before


def test_real_htmx_run_returns_bound_export_token_after_atomic_commit(run_env, monkeypatch):
    from bs4 import BeautifulSoup
    from tests.run_clone_csrf import post_valid_csrf
    from app.persistence.workspace_repository import get_workspace_state
    monkeypatch.setenv('FINCO_WORKBOOK_V2','1')
    record=run_env.create()
    data=identity(record,record.user_id)
    response=post_valid_csrf(run_env.client,'/v2/workbook/run',data=data,headers={'HX-Request':'true'},follow_redirects=False)
    assert response.status_code==200
    ws=get_workspace_state(record.user_id,record.project_id)
    assert ws.last_runtime_snapshot_id
    with db.get_connection() as connection:
        assert connection.execute('SELECT COUNT(*) FROM model_run_history WHERE project_id=?',(record.project_id,)).fetchone()[0]==1
    soup=BeautifulSoup(response.text,'html.parser')
    forms=soup.select('form[action="/v2/workbook/export"]')
    assert forms and all(f.select_one('input[name="csrf_token"]')['value'] for f in forms)
    request=SimpleNamespace(cookies=dict(run_env.client.cookies),state=SimpleNamespace())
    assert all(validate_mutation_token(request,record.project_code,f.select_one('input[name="csrf_token"]')['value'],'workbook-export') for f in forms)
    def no_engine(*a,**kw):pytest.fail('committed evidence export executed finance')
    monkeypatch.setattr('app.api.project_runner.run_project',no_engine)
    before=snapshot()
    rejected=run_env.client.post('/v2/workbook/export',data={'project':record.project_code,'csrf_token':'invalid'},follow_redirects=False)
    assert rejected.status_code==403 and snapshot()==before
    with db.get_connection() as connection:
        exports_before=connection.execute('SELECT COUNT(*) FROM scenario_exports').fetchone()[0]
    exported=run_env.client.post('/v2/workbook/export',data={'project':record.project_code,'csrf_token':forms[0].select_one('input[name="csrf_token"]')['value']},follow_redirects=False)
    assert exported.status_code==200 and exported.content.startswith(b'PK')
    with db.get_connection() as connection:
        assert connection.execute('SELECT COUNT(*) FROM scenario_exports').fetchone()[0]==exports_before+1
        assert connection.execute('SELECT COUNT(*) FROM model_run_history WHERE project_id=?',(record.project_id,)).fetchone()[0]==1


@pytest.mark.parametrize('kind',['solar','wind'])
def test_canonical_reference_with_real_committed_run_remains_byte_identical(tmp_path,monkeypatch,kind):
    from app.services import project_library_service as library
    from app.persistence.projects_repository import get_reference_by_template_source
    from app.persistence.scenarios_repository import get_base_case_scenario
    from app.persistence.workspace_repository import get_workspace_state
    from app.v2.router import router
    monkeypatch.setenv('FINCO_WORKBOOK_V2','1')
    monkeypatch.setattr(db,'DB_PATH',str(tmp_path/'real-reference.db'));db.init_db()
    library.ensure_reference_models()
    ref=get_reference_by_template_source('generic_'+kind+'_reference')
    definition=next(x for x in library._REFERENCE_DEFINITIONS if x['template_source']==ref.template_source)
    library._seed_reference_last_run(ref,definition,current_composite_hash=library._reference_current_composite_hash(ref))
    ws=get_workspace_state(ref.user_id,ref.project_id);assert ws.last_runtime_snapshot_id
    base=get_base_case_scenario(ref.user_id,ref.project_id)
    with db.get_connection() as connection:
        assert connection.execute('SELECT COUNT(*) FROM model_run_history WHERE project_id=?',(ref.project_id,)).fetchone()[0]>0
    def no_engine(*a,**kw):pytest.fail('reference rejection executed finance')
    monkeypatch.setattr('app.api.project_runner.run_project',no_engine)
    monkeypatch.setattr('app.services.production_financial_authority.run_clean_production',no_engine)
    app=FastAPI();app.include_router(router,prefix='/v2')
    with TestClient(app) as client:
        client.cookies.set(auth.COOKIE_NAME,auth.create_session_token(user_id='ordinary-reference-reader',username='isolated'))
        request=SimpleNamespace(cookies=dict(client.cookies),state=SimpleNamespace())
        for op in ['create','select','rename','archive','update-overrides','remove-override']:
            values={'project':ref.project_code,'scenario_id':base.scenario_id,'scenario_name':'Denied','new_name':'Denied','tariff_eur_mwh':'95','field':'tariff_eur_mwh','csrf_token':mutation_token(request,ref.project_code,'scenario-'+op)}
            before=snapshot();response=client.post('/v2/workbook/scenarios/'+op,data=values,follow_redirects=False)
            assert response.status_code==409 and snapshot()==before


@pytest.mark.parametrize('kind',['solar','wind'])
@pytest.mark.parametrize('op',['select','rename','archive','update-overrides','remove-override'])
def test_reference_child_is_also_immutable_not_just_base_restrictions(secured,kind,op):
    # Defensive fixture: an existing child under a reference is seeded through
    # the repository, not claimed to exist in deployed canonical references.
    ref=secured.ref('generic_'+kind+'_reference');sc=child(ref,ref.user_id)
    data={'project':ref.project_code,'scenario_id':sc.scenario_id,'new_name':'Denied','tariff_eur_mwh':'95','field':'tariff_eur_mwh','csrf_token':secured.token(ref.project_code,'scenario-'+op)}
    before=snapshot();response=secured.client.post('/v2/workbook/scenarios/'+op,data=data,follow_redirects=False)
    assert response.status_code==409 and snapshot()==before


def test_positive_caller_helper_leaves_released_capital_stack_requests_untouched(monkeypatch):
    from tests import model_mutation_csrf as helper
    from unittest.mock import Mock
    client=Mock();data={'project':'private','field_id':'debt.financing.instruments','csrf_token':'deliberately-invalid'}
    monkeypatch.setattr(helper,'mutation_token',lambda *a,**kw:pytest.fail('Capital Stack token was replaced'))
    helper.post_valid_mutation(client,'/v2/workbook/update',data=data)
    client.post.assert_called_once_with('/v2/workbook/update',data=data)
    client.build_request.assert_not_called()
