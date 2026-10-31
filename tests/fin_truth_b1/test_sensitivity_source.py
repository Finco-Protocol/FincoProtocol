"""B1 signed local HTTP regressions; real materialisation and real engine outputs."""
import csv
import io
import json
import sqlite3
from dataclasses import replace
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
    return save_all(project_record=record, user_id=OWNER, data=SaveAllInput(
        request_id='b1-'+__import__('uuid').uuid4().hex, workbook_version=WORKBOOK.version,
        content_hash=identity.composite_hash, scenario_id=None, cells=((field, value),)))


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
