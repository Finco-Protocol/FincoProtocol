"""B1 signed local HTTP regressions; real materialisation and real engine outputs."""
import csv
import io
import json
import sqlite3
from types import SimpleNamespace

import openpyxl
import pytest
from bs4 import BeautifulSoup
from tests.test_finv2_d01_routes_and_matrix import legacy  # existing signed synthetic-owner fixture
from app.services import sensitivity_service as S

OWNER = 'legacy-d01'
USER = SimpleNamespace(user_id=OWNER)
PAGE = '/scenarios/sensitivity'
EXPORT = PAGE + '/export'


def dump(env):
    with sqlite3.connect(env.db_path) as con:
        return '\n'.join(con.iterdump())


def save(record, field, value):
    from app.workbook.registry import WORKBOOK
    from app.workbook.workbook_identity import assemble_consistent_for_get
    from app.v2.save_all_commands import save_all, SaveAllInput
    identity = assemble_consistent_for_get(OWNER, record.project_id, WORKBOOK.version)
    from app.persistence.workspace_repository import get_workspace_state
    scenario_id = get_workspace_state(OWNER, record.project_id).active_scenario_id
    return save_all(project_record=record, user_id=OWNER, data=SaveAllInput(
        request_id='b1-'+__import__('uuid').uuid4().hex, workbook_version=WORKBOOK.version,
        content_hash=identity.composite_hash, scenario_id=scenario_id, cells=((field, value),)))


@pytest.mark.parametrize('kind', ['solar', 'wind'])
def test_saved_draft_html_csv_xlsx_same_real_inputs_outputs_units_and_no_writes(legacy, monkeypatch, kind):
    import main_web
    record = legacy.create(kind)
    save(record, 'revenue.ppa.base_tariff', '71.25')
    from app.services.production_waterfall_seam import execute_production_waterfall
    actual_executions = []
    def observe(inputs):
        execution = execute_production_waterfall(inputs)
        actual_executions.append((inputs, execution))
        return execution
    monkeypatch.setattr('app.services.production_waterfall_seam.execute_production_waterfall', observe)
    original = S.run_sensitivity
    grids = []
    def observed_grid(*args, **kwargs):
        grid = original(*args, **kwargs)
        grids.append(grid)
        return grid
    monkeypatch.setattr(S, 'run_sensitivity', observed_grid)
    def forbidden(*args, **kwargs):
        raise AssertionError('read-only sensitivity must never provision/backfill')
    monkeypatch.setattr(main_web, '_resolve_project_record', forbidden)
    monkeypatch.setattr(main_web, '_current_project_workspace', forbidden)
    params = dict(project=record.project_code, shocks='interest_rate,capex')
    if kind == 'wind': params.update(shocks='interest_rate', levels='-100,100')  # explicit numeric levels retain each driver's unit
    before = dump(legacy)
    page = legacy.client.get(PAGE, params=params)
    csv_response = legacy.client.get(EXPORT, params={**params, 'fmt':'csv'})
    xlsx_response = legacy.client.get(EXPORT, params={**params, 'fmt':'xlsx'})
    assert [r.status_code for r in (page,csv_response,xlsx_response)] == [200,200,200]
    assert dump(legacy) == before
    assert len(grids) == 3 and grids[0] == grids[1] == grids[2]
    assert all(r.headers['x-finco-sensitivity-basis']=='WORKING_COPY_DRAFT' for r in (page,csv_response,xlsx_response))
    assert len({r.headers['x-finco-sensitivity-input-hash'] for r in (page,csv_response,xlsx_response)}) == 1
    assert 'not a committed Run' in page.text
    base = S.resolve_sensitivity_source(USER, record.project_code)
    assert base.vertical == kind and base.inputs.technical.capacity_mw == 16
    assert base.inputs.revenue.ppa_base_tariff == 71.25
    assert actual_executions and all(p.technical.capacity_mw==16 for p,e in actual_executions)
    first = actual_executions[0][0]
    levels = [-200,-100,-50,50,100,200] if kind=='solar' else [-100,100]
    for row in grids[0]['rows']:
        point = actual_executions[1+grids[0]['rows'].index(row)][0]
        if row['shock_type']=='interest_rate':
            assert all(abs(b-a-row['level_pct']/10000)<1e-12 for a,b in zip(
                first.financing.senior_debt_interest_config.rate_schedule.explicit_all_in_rates,
                point.financing.senior_debt_interest_config.rate_schedule.explicit_all_in_rates))
        elif row['shock_type']=='capex':
            assert point.capex.total_capex == pytest.approx(first.capex.total_capex*(1+row['level_pct']/100))
    assert [r['level_pct'] for r in grids[0]['rows'] if r['shock_type']=='interest_rate'] == levels
    assert all(r['error'] is None for r in grids[0]['rows'])
    c = list(csv.DictReader(io.StringIO(csv_response.text)))
    wb = openpyxl.load_workbook(io.BytesIO(xlsx_response.content), data_only=True)
    xr = list(wb['Sensitivity'].values)
    assert list(xr[0][:4]) == ['Shock Type','Level','Unit','Error']
    for index, row in enumerate(grids[0]['rows'],1):
        assert c[index]['Unit'] == ('bps' if row['shock_type']=='interest_rate' else '%')
        assert xr[index+1][2] == c[index]['Unit']
        for k,label,fmt in grids[0]['kpi_defs']:
            value = row['kpis'][k]
            if value is not None:
                assert float(c[index][label]) == pytest.approx(value,abs=1e-6)
                col = list(xr[0]).index(label)
                assert xr[index+1][col] == pytest.approx(value,abs=1e-6)
                assert main_web._jinja_fmt_kpi(value,fmt) in page.text
    assert dict(wb['Source'].values)['basis']=='WORKING_COPY_DRAFT'


@pytest.mark.parametrize('url', [PAGE, EXPORT])
@pytest.mark.parametrize('bad', ['unknown','foreign','archived','protected','scenario','other-project-scenario'])
def test_scope_refusals_no_factory_no_engine_no_leaks_or_writes(legacy,monkeypatch,url,bad):
    from app.persistence.db import get_cursor
    from app.services.reference_seed_service import create_reference_seeded_project
    from app.persistence.scenarios_repository import get_or_create_base_case_scenario
    record=legacy.create('solar')
    params=dict(project=record.project_code,shocks='interest_rate',levels='100')
    if bad=='unknown':params['project']='missing-opaque-code'
    elif bad=='foreign':
        foreign=create_reference_seeded_project(user_id='other-owner',requested_name='Private unrelated',template_source='generic_solar_reference',capacity_mw=22)
        params['project']=foreign.project_code
    elif bad in ('archived','protected'):
        # Dedicated fixture forgery only, not a writer accepted by the product.
        from tests.wf03_fixture_seams import archive_through_lifecycle
        if bad=='archived': archive_through_lifecycle(OWNER,record.project_code)
        else:
            with get_cursor() as cur:
                cur.execute("UPDATE projects SET project_role='reference', is_protected=1 WHERE project_id=?",(record.project_id,))
    elif bad=='scenario':params['scenario_id']='forged-scenario'
    else:
        other=legacy.create('wind')
        from app.persistence.workspace_repository import get_workspace_state
        ws=get_workspace_state(OWNER,other.project_id)
        sc=get_or_create_base_case_scenario(user_id=OWNER,project_id=other.project_id,project_code=other.project_code,source_project_template=other.template_source,project_name=other.project_name,project_type=other.project_type,governance_state={},base_input_set=dict(ws.draft_snapshot))
        params['scenario_id']=sc.scenario_id
    def forbidden(*args,**kwargs):raise AssertionError('scope refusal must precede the engine')
    monkeypatch.setattr(S,'run_sensitivity',forbidden)
    before=dump(legacy)
    response=legacy.client.get(url,params=params)
    assert response.status_code==404 and 'Private unrelated' not in response.text
    assert dump(legacy)==before


def test_no_session_precedes_source_lookup_and_invalid_levels_refuse(legacy,monkeypatch):
    from fastapi.testclient import TestClient
    import main_web
    # Full Legacy middleware intentionally provisions a demo identity on a
    # first visit. Test the unchanged handlers with the real session resolver
    # and no provisioning middleware to exercise genuinely absent/forged auth.
    from fastapi import FastAPI
    app=FastAPI()
    app.add_api_route(PAGE,main_web.scenario_sensitivity_endpoint)
    app.add_api_route(EXPORT,main_web.scenario_sensitivity_export_endpoint)
    anonymous=TestClient(app)
    for url in (PAGE,EXPORT):
        r=anonymous.get(url,params={'project':'secret-unknown'},follow_redirects=False)
        assert r.status_code==302 and r.headers['location']=='/login'
    record=legacy.create('solar')
    before=dump(legacy)
    for level in ('nan','inf','bad','50,'):
        for url in (PAGE,EXPORT):
            r=legacy.client.get(url,params=dict(project=record.project_code,shocks='interest_rate',levels=level))
            assert r.status_code==422 and r.json()['state']=='SENSITIVITY_LEVEL_INVALID'
    assert dump(legacy)==before


def test_source_changes_during_execution_are_refused(legacy,monkeypatch):
    record=legacy.create('solar')
    original=S.run_sensitivity
    def concurrent_save(*args,**kwargs):
        result=original(*args,**kwargs)
        save(record,'revenue.ppa.base_tariff','72')
        return result
    monkeypatch.setattr(S,'run_sensitivity',concurrent_save)
    response=legacy.client.get(EXPORT,params=dict(project=record.project_code,shocks='capex',levels='0'))
    assert response.status_code==409 and response.json()['state']=='SENSITIVITY_SOURCE_CHANGED'


@pytest.mark.parametrize('alias,kind',[('generic_solar_reference','solar'),('generic_wind_reference','wind'),('generic_data_center_reference','data_center')])
def test_finite_factory_alias_and_unknown_refusal(legacy,alias,kind):
    before=dump(legacy)
    source=S.resolve_sensitivity_source(USER,alias)
    assert source.vertical==kind and source.provenance['basis']=='EXPLICIT_FACTORY_ALIAS'
    assert dump(legacy)==before
    with pytest.raises(S.SensitivitySourceError): S._resolve_sensitivity_project(USER,'an-arbitrary-project-code')


def test_active_saved_scenario_tariff_and_cost_lines_are_consumed_without_writes(legacy):
    from app.persistence.scenarios_repository import get_or_create_base_case_scenario, add_scenario, select_scenario
    from app.persistence.workspace_repository import get_workspace_state
    record=legacy.create('solar')
    ws=get_workspace_state(OWNER,record.project_id)
    snap=dict(ws.draft_snapshot)
    base=get_or_create_base_case_scenario(user_id=OWNER,project_id=record.project_id,
        project_code=record.project_code,project_name=record.project_name,project_type=record.project_type,
        source_project_template=record.template_source,base_input_set=snap,governance_state={})
    scenario=add_scenario(OWNER,record.project_id,record.project_code,'Selected tariff',base.scenario_id,
                          snap,overrides={'tariff_eur_mwh':79.5})
    assert select_scenario(OWNER,record.project_id,scenario.scenario_id)
    source=S.resolve_sensitivity_source(USER,record.project_code,scenario.scenario_id)
    assert source.inputs.revenue.ppa_base_tariff==79.5
    assert source.provenance['scenario_id']==scenario.scenario_id
    from app.persistence.capex_sub_lines import get_active_sub_lines_for_project
    expected=sum(r.amount_keur for r in get_active_sub_lines_for_project(record.project_id))
    assert source.inputs.capex.total_capex==pytest.approx(expected,abs=1e-6)
    before=dump(legacy)
    response=legacy.client.get(EXPORT,params=dict(project=record.project_code,
        scenario_id=scenario.scenario_id,shocks='capex',levels='0'))
    assert response.status_code==200 and dump(legacy)==before
    rows=list(csv.DictReader(io.StringIO(response.text)))
    assert rows[0]['scenario_id']==scenario.scenario_id and rows[0]['label'].startswith('Working Copy draft')
    assert select_scenario(OWNER,record.project_id,base.scenario_id)
    stale=legacy.client.get(EXPORT,params=dict(project=record.project_code,
        scenario_id=scenario.scenario_id,shocks='capex',levels='0'))
    assert stale.status_code==404


def test_corrupt_snapshot_and_bankability_rate_owner_refuse_before_engine(legacy,monkeypatch):
    from app.persistence.db import get_cursor
    record=legacy.create('solar')
    save(record,'debt.bankability.configuration',json.dumps({'version':1,'rates_pct':[5.5]*30}))
    def forbidden(*args,**kwargs):raise AssertionError('refusal precedes execution')
    monkeypatch.setattr(S,'run_sensitivity',forbidden)
    before=dump(legacy)
    r=legacy.client.get(EXPORT,params=dict(project=record.project_code,shocks='interest_rate',levels='100'))
    assert r.status_code==422 and r.json()['state']=='RATE_SHOCK_BANKABILITY_OWNED'
    assert dump(legacy)==before
    with get_cursor() as cur:
        row=cur.execute('SELECT draft_snapshot_json FROM workspace_states WHERE project_id=?',(record.project_id,)).fetchone()
        snapshot=json.loads(row[0]);snapshot['interest_rate_pct']='not-a-rate'
        cur.execute('UPDATE workspace_states SET draft_snapshot_json=? WHERE project_id=?',(json.dumps(snapshot),record.project_id))
    before=dump(legacy)
    r=legacy.client.get(EXPORT,params=dict(project=record.project_code,shocks='capex',levels='0'))
    assert r.status_code==409 and r.json()['state']=='SENSITIVITY_INPUT_UNAVAILABLE'
    assert dump(legacy)==before


def test_legacy_ev_source_repair_preserves_unadmitted_surface_refusal(legacy,monkeypatch):
    record=legacy.create('ev_charging')
    def forbidden(*args,**kwargs):raise AssertionError('Legacy EV sensitivity is not admitted')
    monkeypatch.setattr(S,'run_sensitivity',forbidden)
    before=dump(legacy)
    page=legacy.client.get(PAGE,params=dict(project=record.project_code,shocks='interest_rate',levels='100'))
    export=legacy.client.get(EXPORT,params=dict(project=record.project_code,shocks='interest_rate',levels='100'))
    assert page.status_code==200 and not BeautifulSoup(page.text,'html.parser').select('tr.sens-row')
    assert 'An error occurred' in page.text
    assert export.status_code==422 and export.json()['state']=='SENSITIVITY_VERTICAL_UNAVAILABLE'
    assert dump(legacy)==before


def test_explicit_factory_alias_html_and_export_are_read_only(legacy):
    before=dump(legacy)
    for path in (PAGE,EXPORT):
        response=legacy.client.get(path,params=dict(project='generic_solar_reference',shocks='interest_rate',levels='0'))
        assert response.status_code==200
        assert response.headers['x-finco-sensitivity-basis']=='EXPLICIT_FACTORY_ALIAS'
    assert dump(legacy)==before


def test_preexisting_legacy_factory_selector_row_keeps_disclosed_alias_contract(legacy):
    import main_web
    factory_row=main_web._resolve_project_record(USER,'generic_solar_reference')
    assert factory_row.project_origin=='factory_template'
    source=S.resolve_sensitivity_source(USER,'generic_solar_reference')
    assert source.provenance['basis']=='EXPLICIT_FACTORY_ALIAS' and source.context is None
    assert source.vertical=='solar' and source.inputs.technical.capacity_mw==64
    before=dump(legacy)
    for path in (PAGE,EXPORT):
        response=legacy.client.get(path,params=dict(project='generic_solar_reference',shocks='interest_rate',levels='0'))
        assert response.status_code==200
        assert response.headers['x-finco-sensitivity-basis']=='EXPLICIT_FACTORY_ALIAS'
    assert dump(legacy)==before


def test_archiving_the_active_scenario_during_calculation_discards_export(legacy,monkeypatch):
    from app.persistence.workspace_repository import get_workspace_state
    from app.persistence.scenarios_repository import get_or_create_base_case_scenario, select_scenario, archive_scenario
    record=legacy.create('solar')
    ws=get_workspace_state(OWNER,record.project_id)
    base=get_or_create_base_case_scenario(user_id=OWNER,project_id=record.project_id,
        project_code=record.project_code,project_name=record.project_name,project_type=record.project_type,
        source_project_template=record.template_source,base_input_set=dict(ws.draft_snapshot),governance_state={})
    assert select_scenario(OWNER,record.project_id,base.scenario_id)
    original=S.run_sensitivity
    def concurrent_archive(*args,**kwargs):
        result=original(*args,**kwargs)
        assert archive_scenario(OWNER,base.scenario_id)
        return result
    monkeypatch.setattr(S,'run_sensitivity',concurrent_archive)
    response=legacy.client.get(EXPORT,params=dict(project=record.project_code,
        scenario_id=base.scenario_id,shocks='capex',levels='0'))
    assert response.status_code==409 and response.json()['state']=='SENSITIVITY_SOURCE_CHANGED'


# Correction B: real persisted monthly profiles, not marker/label-only proof.
def _profile_identity(record):
    from app.workbook.registry import WORKBOOK
    from app.workbook.workbook_identity import assemble_consistent_for_get
    return assemble_consistent_for_get(record.user_id, record.project_id, WORKBOOK.version).composite_hash


def _profile_document(record, shape):
    from app.capex_profiles.runtime import leaves_for
    actor=SimpleNamespace(user_id=record.user_id)
    pi=S.resolve_sensitivity_source(actor,record.project_code).inputs
    return {'version':1,'profiles':[{'item_key':l.item_key,'shape':shape,
            'explicit_percent':[],'milestone_month':None}
            for l in leaves_for(pi.capex,record.project_id) if l.amount_keur>0]}


def _store_profile(record,document):
    from app.capex_profiles.service import save_profiles
    from app.persistence.workspace_repository import get_workspace_state
    ws=get_workspace_state(record.user_id,record.project_id)
    save_profiles(owner=record.user_id,project_id=record.project_id,
        expected_hash=_profile_identity(record),expected_scenario_id=ws.active_scenario_id or '',raw=json.dumps(document))


def _profile_scenarios(record):
    from app.persistence.scenarios_repository import get_or_create_base_case_scenario,add_scenario
    from app.persistence.workspace_repository import get_workspace_state
    from app.persistence.capex_sub_lines import get_active_sub_lines_for_project
    ws=get_workspace_state(OWNER,record.project_id);snapshot=dict(ws.draft_snapshot)
    base=get_or_create_base_case_scenario(user_id=OWNER,project_id=record.project_id,
        project_code=record.project_code,project_name=record.project_name,project_type=record.project_type,
        source_project_template=record.template_source,base_input_set=snapshot,governance_state={})
    line=next(x for x in get_active_sub_lines_for_project(record.project_id) if x.amount_keur>0)
    case=add_scenario(OWNER,record.project_id,record.project_code,'Profile case',base.scenario_id,snapshot,
        overrides={'tariff_eur_mwh':79.5,'_capex_sub_line_overrides':{line.sub_line_id:line.amount_keur*1.1}})
    return base,case


def _profile_http_run(legacy,record):
    from tests.run_clone_csrf import post_valid_csrf
    from app.workbook.registry import WORKBOOK
    from app.persistence.run_history_repository import get_run_history
    before=len(get_run_history(OWNER,record.project_id))
    response=post_valid_csrf(legacy.client,'/v2/workbook/run',headers={'HX-Request':'true'},
        data={'project':record.project_code,'content_hash':_profile_identity(record),'workbook_version':WORKBOOK.version})
    assert response.status_code==200,response.text[:500]
    rows=get_run_history(OWNER,record.project_id)
    assert len(rows)==before+1,response.text[:500]
    return rows[0]


@pytest.mark.parametrize('kind',['solar','wind'])
def test_profiled_real_http_formats_match_canonical_run_and_change_cash_timing(legacy,monkeypatch,kind):
    import dataclasses
    import hashlib
    import os
    from pathlib import Path
    import main_web
    from app.services import production_waterfall_seam as seam
    from app.services.production_financial_authority import run_clean_production
    from app.run_integrity.evidence import build_run_integrity_evidence
    from app.persistence.scenarios_repository import select_scenario
    from app.persistence.capex_sub_lines import get_active_sub_lines_for_project
    monkeypatch.setenv('FINCO_MODEL_EXECUTION_MODE','thread')
    record=legacy.create(kind)
    # Prime existing canonical workbook backfills before measuring GET purity.
    assert legacy.client.get('/v2/workbook',params={'project':record.project_code}).status_code==200
    base,case=_profile_scenarios(record)
    captures=[];grids=[];rows=[]
    def observe(*args,**kwargs):
        clean=run_clean_production(*args,**kwargs)
        ev=build_run_integrity_evidence(clean)
        captures.append({'inputs':dataclasses.asdict(clean.project_inputs),
            'funding':ev['sources_uses']['construction_periods'],'uses':ev['sources_uses']['summary']})
        return clean
    # Both paths delegate to the REAL production authority. No output is replaced.
    monkeypatch.setattr(seam,'run_clean_production',observe)
    monkeypatch.setattr('app.services.production_financial_authority.run_clean_production',observe)
    original=S.run_sensitivity
    def observe_grid(*args,**kwargs):
        result=original(*args,**kwargs);grids.append(result);return result
    monkeypatch.setattr(S,'run_sensitivity',observe_grid)
    for shape in ('FRONT_LOADED','BACK_LOADED'):
        assert select_scenario(OWNER,record.project_id,base.scenario_id)
        save(record,'debt.senior.interest_rate_pct','5.5')
        _store_profile(record,_profile_document(record,shape))
        assert select_scenario(OWNER,record.project_id,case.scenario_id)
        source=S.resolve_sensitivity_source(USER,record.project_code,case.scenario_id)
        assert source.profile_basis is not None
        assert source.inputs.revenue.ppa_base_tariff==79.5
        lines=get_active_sub_lines_for_project(record.project_id)
        effective=sum(case.overrides['_capex_sub_line_overrides'].get(x.sub_line_id,x.amount_keur) for x in lines)
        assert source.inputs.capex.total_capex==pytest.approx(effective,abs=1e-6)
        start=len(captures);grid_start=len(grids);before=dump(legacy)
        params=dict(project=record.project_code,scenario_id=case.scenario_id,shocks='interest_rate',levels='100')
        page=legacy.client.get(PAGE,params=params)
        csv_response=legacy.client.get(EXPORT,params={**params,'fmt':'csv'})
        xlsx_response=legacy.client.get(EXPORT,params={**params,'fmt':'xlsx'})
        assert [r.status_code for r in (page,csv_response,xlsx_response)]==[200,200,200]
        assert dump(legacy)==before  # includes all immutable prior Runs from the previous profile
        assert grids[grid_start]==grids[grid_start+1]==grids[grid_start+2]
        assert len(captures)==start+6
        for i in (start+2,start+4):
            assert captures[start]==captures[i] and captures[start+1]==captures[i+1]
        a,b=captures[start:start+2]
        assert len(a['funding'])==source.inputs.info.construction_months
        assert len(b['funding'])==source.inputs.info.construction_months
        assert a['inputs']['financing']['construction_financing']['senior_pricing']['flat_all_in_rate']==pytest.approx(.055)
        assert b['inputs']['financing']['construction_financing']['senior_pricing']['flat_all_in_rate']==pytest.approx(.065)
        assert all(x==pytest.approx(.065) for x in b['inputs']['financing']['senior_debt_interest_config']['rate_schedule']['explicit_all_in_rates'])
        assert abs(a['uses']['capitalized_idc_keur']-b['uses']['capitalized_idc_keur'])>1e-3
        assert len({r.headers['x-finco-sensitivity-input-hash'] for r in (page,csv_response,xlsx_response)})==1
        exported=list(csv.DictReader(io.StringIO(csv_response.text)))
        wb=openpyxl.load_workbook(io.BytesIO(xlsx_response.content),data_only=True)
        values=list(wb['Sensitivity'].values)
        grid=grids[grid_start]
        for index,kpis in enumerate((grid['base_kpis'],grid['rows'][0]['kpis'])):
            for key,label,fmt in grid['kpi_defs']:
                if kpis[key] is None:continue
                assert float(exported[index][label])==pytest.approx(kpis[key],abs=1e-6)
                assert values[index+1][list(values[0]).index(label)]==pytest.approx(kpis[key],abs=1e-6)
                assert main_web._jinja_fmt_kpi(kpis[key],fmt) in page.text
        assert exported[0]['project_id']==record.project_id and exported[0]['scenario_id']==case.scenario_id
        first=_profile_http_run(legacy,record)
        assert captures[-1]==a  # complete canonical consumed inputs AND full-precision funding/uses
        assert first.integrity_evidence['sources_uses']['construction_periods']==a['funding']
        save(record,'debt.senior.interest_rate_pct','6.5')
        second=_profile_http_run(legacy,record)
        assert captures[-1]==b  # +100 bps equals a genuine HTTP Run at 6.5%, including construction
        assert second.integrity_evidence['sources_uses']['construction_periods']==b['funding']
        rows.append({'technology':kind,'profile':shape,'project_id':record.project_id,'scenario_id':case.scenario_id,
            'source_hash':exported[0]['input_hash'],'no_write_dump_sha256':hashlib.sha256(before.encode()).hexdigest(),
            'base':a,'plus_100_bps':b,'history_ids':[first.history_id,second.history_id]})
    assert rows[0]['base']['funding']!=rows[1]['base']['funding']
    assert rows[0]['base']['uses']['base_project_capex_keur']==pytest.approx(rows[1]['base']['uses']['base_project_capex_keur'],abs=1e-6)
    assert abs(rows[0]['base']['uses']['capitalized_idc_keur']-rows[1]['base']['uses']['capitalized_idc_keur'])>1e-3
    out=os.environ.get('FIN_TRUTH_B1_PROFILE_EVIDENCE_DIR')
    if out:
        Path(out).mkdir(parents=True,exist_ok=True)
        (Path(out)/(kind+'-profile-real-http.json')).write_text(json.dumps(rows,indent=2,default=str)+'\n')


@pytest.mark.parametrize('surface',['html','csv','xlsx'])
@pytest.mark.parametrize('fault',['malformed','falsey-zero','unsupported-shape','missing-leaf','stale-leaf',
    'unbindable-weights','milestone-outside-grid','missing-workspace','foreign','archived','protected','deleted-scenario','stale-scenario'])
def test_profile_source_refusals_never_run_defaults_or_write(legacy,monkeypatch,surface,fault):
    from app.persistence.db import get_cursor
    from app.capex_profiles.config import SNAPSHOT_KEY
    from app.persistence.scenarios_repository import select_scenario
    from app.persistence.capex_sub_lines import get_active_sub_lines_for_project
    record=legacy.create('solar')
    document=_profile_document(record,'FRONT_LOADED');_store_profile(record,document)
    params=dict(project=record.project_code,shocks='interest_rate',levels='100')
    if fault=='foreign':
        from app.services.reference_seed_service import create_reference_seeded_project
        other=create_reference_seeded_project(user_id='other-owner',requested_name='Unrelated profiled source',
            template_source='generic_solar_reference',capacity_mw=16)
        _store_profile(other,_profile_document(other,'FRONT_LOADED'));params['project']=other.project_code
    elif fault=='archived':
        from tests.wf03_fixture_seams import archive_through_lifecycle
        archive_through_lifecycle(OWNER,record.project_code)
    elif fault=='protected':
        with get_cursor() as cur:cur.execute("UPDATE projects SET project_role='reference',is_protected=1 WHERE project_id=?",(record.project_id,))
    elif fault in ('deleted-scenario','stale-scenario'):
        base,case=_profile_scenarios(record);params['scenario_id']=case.scenario_id
        assert select_scenario(OWNER,record.project_id,case.scenario_id if fault=='deleted-scenario' else base.scenario_id)
        if fault=='deleted-scenario':
            with get_cursor() as cur:cur.execute('DELETE FROM scenarios WHERE scenario_id=? AND user_id=?',(case.scenario_id,OWNER))
    elif fault=='stale-leaf':
        from app.v2 import capex_commands
        from app.workbook.registry import WORKBOOK
        line=next(x for x in get_active_sub_lines_for_project(record.project_id) if x.business_code==document['profiles'][0]['item_key'])
        capex_commands.deactivate_capex_line(project_record=record,user_id=OWNER,sub_line_id=line.sub_line_id,
            row_version=line.updated_at,workbook_version=WORKBOOK.version,expected_content_hash=_profile_identity(record))
    else:
        # Historical/corrupt fixtures: canonical Save rejects these, so place
        # them only in this disposable DB to exercise the read-side refusal.
        with get_cursor() as cur:
            if fault=='missing-workspace':
                cur.execute('DELETE FROM workspace_states WHERE project_id=? AND user_id=?',(record.project_id,OWNER))
            else:
                row=cur.execute('SELECT draft_snapshot_json FROM workspace_states WHERE project_id=?',(record.project_id,)).fetchone()
                snapshot=json.loads(row[0])
                if fault=='malformed':snapshot[SNAPSHOT_KEY]='{broken'
                elif fault=='falsey-zero':snapshot[SNAPSHOT_KEY]=0
                elif fault=='unsupported-shape':
                    document['profiles'][0]['shape']='GAUSSIAN';snapshot[SNAPSHOT_KEY]=json.dumps(document)
                elif fault=='missing-leaf':
                    document['profiles'][0]['item_key']='base:no_such_leaf';snapshot[SNAPSHOT_KEY]=json.dumps(document)
                elif fault=='unbindable-weights':
                    document['profiles'][0].update(shape='EXPLICIT',explicit_percent=['50','50']);snapshot[SNAPSHOT_KEY]=json.dumps(document)
                elif fault=='milestone-outside-grid':
                    document['profiles'][0].update(shape='MILESTONE',milestone_month=99);snapshot[SNAPSHOT_KEY]=json.dumps(document)
                cur.execute('UPDATE workspace_states SET draft_snapshot_json=? WHERE project_id=?',(json.dumps(snapshot),record.project_id))
    def forbidden(*args,**kwargs):raise AssertionError('invalid profile source must refuse BEFORE any engine point')
    monkeypatch.setattr(S,'run_sensitivity',forbidden)
    before=dump(legacy)
    path=PAGE if surface=='html' else EXPORT
    if surface!='html':params['fmt']=surface
    response=legacy.client.get(path,params=params)
    assert response.status_code in (404,409,422),response.text[:300]
    assert 'rows' not in response.json() and 'base_kpis' not in response.json()
    assert dump(legacy)==before
