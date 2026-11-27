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
    sync_playwright = pytest.importorskip("playwright.sync_api", reason="playwright not installed in this workflow").sync_playwright
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
