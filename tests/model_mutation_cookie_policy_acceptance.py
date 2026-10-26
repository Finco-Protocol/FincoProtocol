"""Real Chromium, explicit local HTTPS cookie policy; no production proxy assumptions.

Executed explicitly during correction review. The certificate is ephemeral local
TLS test transport only; FINCO certificate payload/signing authority is not used.
"""
import json
import os
from pathlib import Path
import shutil
import socket
import subprocess
import threading
import time

import pytest
from fastapi import FastAPI, Request
from fastapi.responses import HTMLResponse, JSONResponse
from playwright.sync_api import sync_playwright

from tests.test_model_mutation_request_security_v1 import snapshot


@pytest.fixture
def mutation_browser_servers(tmp_path,monkeypatch):
    from app import auth
    from app.persistence import db
    from app.services.project_library_service import ensure_reference_models,create_working_copy
    from app.persistence.projects_repository import get_reference_by_template_source
    from app.v2.router import router
    from app.v2.react_workspace_router import router as workspace_router
    from app.v2.capex_router import capex_router
    from app.v2.opex_router import opex_router
    from fastapi.staticfiles import StaticFiles
    import uvicorn
    monkeypatch.setenv('FINCO_WORKBOOK_V2','1');monkeypatch.setenv('FINCO_MODEL_REACT_V1','1')
    monkeypatch.setenv('FINCO_COOKIE_SECURE','true');monkeypatch.setenv('FINCO_COOKIE_SAMESITE','lax')
    monkeypatch.setattr(db,'DB_PATH',str(tmp_path/'browser-private.db'));db.init_db()
    def no_engine(*a,**kw):pytest.fail('mutation cookie acceptance invoked finance')
    monkeypatch.setattr('app.api.project_runner.run_project',no_engine)
    monkeypatch.setattr('app.services.production_financial_authority.run_clean_production',no_engine)
    ensure_reference_models()
    ref=get_reference_by_template_source('generic_solar_reference')
    own=create_working_copy('browser-mutation-owner',ref.project_id,requested_name='Browser mutation')
    cookie=auth.create_session_token(user_id=own.user_id,username='isolated-browser')
    app=FastAPI();app.include_router(router,prefix='/v2');app.include_router(workspace_router,prefix='/v2')
    app.include_router(capex_router,prefix='/v2/capex');app.include_router(opex_router,prefix='/v2/opex')
    app.mount('/static',StaticFiles(directory=str(Path(__file__).resolve().parents[1]/'static')),name='static')
    observations=[]
    @app.middleware('http')
    async def observe(request:Request,call_next):
        if request.method=='POST':observations.append({'origin':request.headers.get('origin'),'fetch_site':request.headers.get('sec-fetch-site'),'cookie_present':auth.COOKIE_NAME in request.cookies})
        return await call_next(request)
    @app.get('/_security_test_login')
    def login():
        response=JSONResponse({'isolated_fixture':True})
        response.set_cookie(**auth.make_session_cookie(cookie))
        return response
    # No submitted script or endpoint can run arbitrary code: a fixed local test form.
    @app.get('/_security_test_form')
    def form():
        return HTMLResponse('<form id="attack" method="post"><input name="project"><input name="scenario_name"><input name="csrf_token"><button>Submit</button></form>')
    openssl=shutil.which('openssl')
    if not openssl and Path('C:/Program Files/Git/usr/bin/openssl.exe').exists():openssl='C:/Program Files/Git/usr/bin/openssl.exe'
    assert openssl,'Local HTTPS test requires openssl; no browser test is silently skipped'
    key=tmp_path/'local-tls-key.pem';cert=tmp_path/'local-tls-cert.pem'
    subprocess.run([openssl,'req','-x509','-newkey','rsa:2048','-nodes','-keyout',str(key),'-out',str(cert),'-days','1','-subj','/CN=localhost','-addext','subjectAltName=DNS:localhost,IP:127.0.0.1'],check=True,capture_output=True)
    servers=[]
    for _ in range(2):
        with socket.socket() as s:s.bind(('127.0.0.1',0));port=s.getsockname()[1]
        server=uvicorn.Server(uvicorn.Config(app,host='127.0.0.1',port=port,ssl_keyfile=str(key),ssl_certfile=str(cert),log_level='error'))
        thread=threading.Thread(target=server.run,daemon=True);thread.start();servers.append((server,thread,port))
    try:
        deadline=time.monotonic()+20
        while not all(s.started for s,t,p in servers):
            assert time.monotonic()<deadline,'Local HTTPS fixture failed to start'
            time.sleep(.02)
        yield own,f'https://127.0.0.1:{servers[0][2]}',servers[1][2],observations
    finally:
        for s,t,p in servers:s.should_exit=True
        for s,t,p in servers:t.join(10)


def test_verified_secure_lax_policy_same_origin_same_site_and_cross_site(mutation_browser_servers,tmp_path):
    own,target,other_port,observations=mutation_browser_servers
    results=[]
    with sync_playwright() as pw:
        browser=pw.chromium.launch(executable_path=os.environ.get('FINCO_TEST_CHROMIUM_PATH') or None,args=['--no-sandbox'])
        try:
            for name,origin,valid,expected,cookie_expected in [
                ('same-origin-missing',target,False,403,True),
                ('same-site-cross-origin',f'https://127.0.0.1:{other_port}',False,403,True),
                ('cross-site',f'https://localhost:{other_port}',False,401,False),
                ('same-origin-valid',target,True,303,True)]:
                context=browser.new_context(ignore_https_errors=True)
                page=context.new_page();page.goto(target+'/_security_test_login')
                policy=next(c for c in context.cookies() if c['name'].startswith('finco') or c['name'])
                assert policy['secure'] is True and policy['httpOnly'] is True and policy['sameSite']=='Lax'
                payload=page.evaluate('p => fetch("/v2/model-react/scenarios?project="+encodeURIComponent(p)).then(r=>r.json())',own.project_code)
                assert payload['ok']
                token=payload['mutations']['create']['csrf_token'] if valid else ''
                page.goto(origin+'/_security_test_form')
                before=snapshot();n=len(observations)
                with page.expect_response(lambda r:r.request.method=='POST' and '/workbook/scenarios/create' in r.url) as pending:
                    page.evaluate('''x => { const f=document.getElementById('attack'); f.action=x.target+'/v2/workbook/scenarios/create'; f.elements.project.value=x.project; f.elements.scenario_name.value=x.name; f.elements.csrf_token.value=x.token; f.submit(); }''',{'target':target,'project':own.project_code,'name':name,'token':token})
                response=pending.value
                assert response.status==expected,(name,response.status)
                assert len(observations)==n+1 and observations[-1]['cookie_present']==cookie_expected
                changed=snapshot()!=before
                assert changed==valid
                results.append({'case':name,'http':response.status,'database_changed':changed,**observations[-1],'cookie_policy':{'secure':policy['secure'],'httpOnly':policy['httpOnly'],'sameSite':policy['sameSite']}})
                context.close()
        finally:browser.close()
    evidence=Path(os.environ.get('FINCO_MUTATION_BROWSER_EVIDENCE',str(tmp_path/'browser-security.json')))
    evidence.parent.mkdir(parents=True,exist_ok=True)
    evidence.write_text(json.dumps({'scope':'Explicit isolated HTTPS configuration; production proxy, hosts and deployment cookies were not inspected','results':results},indent=2),encoding='utf-8')


def check_legacy_cost_buttons_use_their_own_operation_tokens(mutation_browser_servers):
    """Visible Legacy controls, real issued tokens and completed HTMX swaps."""
    own,target,_port,_observations=mutation_browser_servers
    from app.persistence import db
    from tests.model_workspace_navigation import activate_destination

    def database_state():
        with db.get_connection() as connection:
            schema=[tuple(r) for r in connection.execute("SELECT type,name,tbl_name,sql FROM sqlite_master ORDER BY type,name")]
            tables={}
            for row in connection.execute("SELECT name FROM sqlite_master WHERE type='table' ORDER BY name"):
                name=row[0]
                rows=[dict(r) for r in connection.execute('SELECT * FROM "'+name.replace('"','""')+'"')]
                tables[name]=sorted(rows,key=lambda r:json.dumps(r,sort_keys=True,default=str))
        return schema,tables

    def assert_only_cost_command_changed(before,after):
        assert before[0]==after[0] and set(before[1])==set(after[1])
        for table,rows in before[1].items():
            if table=='capex_sub_lines':
                foreign=lambda data:[r for r in data if r['project_id']!=own.project_id]
                assert foreign(rows)==foreign(after[1][table])
            elif table=='workspace_states':
                def unchanged(data):
                    return [{k:v for k,v in r.items() if not (
                        r['project_id']==own.project_id and r['user_id']==own.user_id
                        and k in {'dirty','draft_content_hash','updated_at'})} for r in data]
                assert unchanged(rows)==unchanged(after[1][table])
            elif table=='sqlite_sequence':
                previous={r['name']:r['seq'] for r in rows}
                current={r['name']:r['seq'] for r in after[1][table]}
                assert {k:v for k,v in previous.items() if k!='capex_sub_lines'}=={k:v for k,v in current.items() if k!='capex_sub_lines'}
                inserted=len(after[1]['capex_sub_lines'])-len(before[1]['capex_sub_lines'])
                assert current.get('capex_sub_lines',0)-previous.get('capex_sub_lines',0)==inserted
            else:
                assert rows==after[1][table],table  # includes every Run/history/project/scenario/financial table

    def lines(state):
        return {r['sub_line_id']:r for r in state[1]['capex_sub_lines'] if r['project_id']==own.project_id}

    events=[];errors=[]
    evidence=Path(os.environ.get('FINCO_MUTATION_COST_UI_EVIDENCE','artifacts/workspace-consolidation/mutation-cost-ui.json'))
    with sync_playwright() as pw:
        browser=pw.chromium.launch(executable_path=os.environ.get('FINCO_TEST_CHROMIUM_PATH') or None,args=['--no-sandbox'])
        context=browser.new_context(ignore_https_errors=True,viewport={'width':1440,'height':1000})
        page=context.new_page()
        page.on('request',lambda r:events.append({'event':'request','method':r.method,'path':r.url.split('?')[0].removeprefix(target)}) if r.method=='POST' else None)
        page.on('response',lambda r:events.append({'event':'response','method':r.request.method,'path':r.url.split('?')[0].removeprefix(target),'status':r.status}) if r.request.method=='POST' else None)
        page.on('requestfailed',lambda r:errors.append({'event':'requestfailed','path':r.url.split('?')[0].removeprefix(target),'failure':r.failure}))
        page.on('pageerror',lambda e:errors.append({'event':'pageerror','error':str(e)}))
        page.add_init_script("""window.__capexSettled=0;window.__capexEvents=[];
            for(const type of ['htmx:beforeRequest','htmx:afterSwap','htmx:afterSettle','htmx:validation:halted'])
                document.addEventListener(type,e=>{if(e.target.id==='v2-sheet-capex'){
                    if(type==='htmx:afterSettle')window.__capexSettled++;
                    window.__capexEvents.push({type,target:e.target.id});}},false);""")
        try:
            page.goto(target+'/_security_test_login')
            page.goto(target+'/v2/workbook?project='+own.project_code+'&sheet=capex')
            page.wait_for_function('window.htmx && document.readyState === "complete"')
            activate_destination(page,'tab-capex')
            page.wait_for_function('document.getElementById("tab-capex").getAttribute("aria-selected")==="true"')
            sheet=page.locator('#v2-sheet-capex');sheet.wait_for(state='visible')
            add_form=sheet.locator('form[hx-post="/v2/capex/line/add"]').first
            group=add_form.locator('xpath=ancestor::details[contains(@class,"v2-capex-group")]')
            if group.get_attribute('open') is None:
                group.locator(':scope > summary').click()
            disclosure=add_form.locator('xpath=ancestor::details[contains(@class,"v2-add-row-disclosure")]')
            if disclosure.get_attribute('open') is None:
                disclosure.locator(':scope > summary').click()
            add_form.wait_for(state='visible')
            assert add_form.locator('[name="project"]').input_value()==own.project_code
            assert add_form.locator('input[type="hidden"][name="csrf_token"]').input_value()
            add_form.locator('[name="label"]').fill('Browser secure line')
            add_form.locator('[name="amount_keur"]').fill('12')
            assert add_form.evaluate('f => f.checkValidity()')
            baseline=database_state()

            def click_and_settle(control,path):
                assert control.is_visible() and control.is_enabled()
                settled=page.evaluate('window.__capexSettled')
                with page.expect_response(lambda r:r.request.method=='POST' and r.url==target+path) as pending:
                    control.click()
                assert pending.value.status==200
                page.wait_for_function('(n)=>window.__capexSettled>n',arg=settled)
                assert page.locator('#tab-capex').get_attribute('aria-selected')=='true'
                assert sheet.is_visible()

            click_and_settle(add_form.locator('button[type="submit"]'),'/v2/capex/line/add')
            added=database_state();assert_only_cost_command_changed(baseline,added)
            original=lines(baseline);first=lines(added)
            assert len(first)==len(original)+1
            new_ids=set(first)-set(original);assert len(new_ids)==1
            source_id=new_ids.pop();assert first[source_id]['label']=='Browser secure line' and first[source_id]['amount_keur']==12
            assert all(first[k]==v for k,v in original.items())
            source=sheet.locator('form[data-sub-line-id="'+source_id+'"]')
            duplicate=source.locator('button[hx-post="/v2/capex/line/add"]')
            add_token=json.loads(duplicate.get_attribute('hx-vals'))['csrf_token']
            assert add_token and add_token!=source.locator('[name="csrf_token"]').input_value()
            click_and_settle(duplicate,'/v2/capex/line/add')
            duplicated=database_state();assert_only_cost_command_changed(added,duplicated)
            second=lines(duplicated);assert len(second)==len(first)+1
            copy_ids=set(second)-set(first);assert len(copy_ids)==1
            copy_id=copy_ids.pop();assert second[copy_id]['label']=='Browser secure line (copy)' and second[copy_id]['amount_keur']==12
            assert all(second[k]==v for k,v in first.items())
            copy=sheet.locator('form[data-sub-line-id="'+copy_id+'"]')
            assert copy.locator('[name="row_version"]').input_value()==second[copy_id]['updated_at']
            assert copy.locator('[name="content_hash"]').input_value()==next(r['draft_content_hash'] for r in duplicated[1]['workspace_states'] if r['project_id']==own.project_id and r['user_id']==own.user_id)
            deactivate=copy.locator('button[hx-post="/v2/capex/line/deactivate"]')
            deactivate_token=json.loads(deactivate.get_attribute('hx-vals'))['csrf_token']
            assert deactivate_token and deactivate_token!=add_token and deactivate_token!=copy.locator('[name="csrf_token"]').input_value()
            click_and_settle(deactivate,'/v2/capex/line/deactivate')
            final=database_state();assert_only_cost_command_changed(duplicated,final)
            last=lines(final)
            assert len(last)==len(second) and sum(r['is_active'] for r in last.values())==sum(r['is_active'] for r in second.values())-1
            assert last[copy_id]['is_active']==0
            assert {k:v for k,v in last[copy_id].items() if k not in {'is_active','updated_at'}}=={k:v for k,v in second[copy_id].items() if k not in {'is_active','updated_at'}}
            assert all(last[k]==v for k,v in second.items() if k!=copy_id)
            assert [e['path'] for e in events if e['event']=='request']==['/v2/capex/line/add','/v2/capex/line/add','/v2/capex/line/deactivate']
            assert not errors,errors
            evidence.parent.mkdir(parents=True,exist_ok=True)
            page.screenshot(path=str(evidence.with_suffix('.png')),full_page=False)
        finally:
            evidence.parent.mkdir(parents=True,exist_ok=True)
            evidence.write_text(json.dumps({'scope':'Actual visible Legacy CAPEX controls under isolated HTTPS; no production deployment claim','requests_and_responses':events,'errors':errors,'htmx_events':page.evaluate('window.__capexEvents || []') if not page.is_closed() else [],'capex_selected':page.locator('#tab-capex').get_attribute('aria-selected')=='true' if not page.is_closed() else False},indent=2),encoding='utf-8')
            context.close();browser.close()
