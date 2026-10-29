"""Real HTTPS Chromium WF03 checks, called by the mandatory Consolidation role.

No source bypass, synthetic token, product-DB action or skipped Chromium check.
Fixture provisioning is isolated; all lifecycle actions use visible real controls.
"""
from __future__ import annotations

import hashlib
import json
import os
from pathlib import Path
import shutil
import socket
import subprocess
import threading
import time
import uuid

import pytest


@pytest.fixture(scope='module')
def wf03_servers(tmp_path_factory):
    import uvicorn
    from app.persistence import db
    directory=tmp_path_factory.mktemp('wf03-https')
    mp=pytest.MonkeyPatch()
    mp.setattr(db,'DB_PATH',str(directory/'wf03.sqlite'))
    mp.setenv('FINCO_MODEL_REACT_V1','1')
    mp.setenv('FINCO_MODEL_EXECUTION_MODE','thread')
    db.init_db()
    import main_web
    openssl=shutil.which('openssl')
    if not openssl and Path('C:/Program Files/Git/usr/bin/openssl.exe').is_file():
        openssl='C:/Program Files/Git/usr/bin/openssl.exe'
    assert openssl, 'HTTPS acceptance requires openssl'
    key,cert=directory/'key.pem',directory/'cert.pem'
    subprocess.run([openssl,'req','-x509','-newkey','rsa:2048','-nodes','-keyout',str(key),'-out',str(cert),
                    '-days','1','-subj','/CN=localhost','-addext','subjectAltName=DNS:localhost,IP:127.0.0.1'],
                   check=True,capture_output=True)
    listener=socket.socket()
    listener.bind(('127.0.0.1',0))
    port=listener.getsockname()[1]
    server=uvicorn.Server(uvicorn.Config(main_web.app,host='127.0.0.1',port=port,
        ssl_keyfile=str(key),ssl_certfile=str(cert),log_level='error',lifespan='off',timeout_graceful_shutdown=5))
    thread=threading.Thread(target=lambda:server.run(sockets=[listener]),daemon=True)
    thread.start()
    deadline=time.monotonic()+30
    while not server.started:
        assert thread.is_alive() and time.monotonic()<deadline,'WF03 HTTPS server did not start'
        time.sleep(.02)
    evidence=Path(os.environ.get('FINCO_WF03_EVIDENCE_DIR',directory/'captures'))
    evidence.mkdir(parents=True,exist_ok=True)
    try:
        yield f'https://127.0.0.1:{port}',evidence
    finally:
        server.should_exit=True
        thread.join(timeout=15)
        listener.close()
        mp.undo()
        assert not thread.is_alive(),'WF03 HTTPS fixture leaked a server thread'


@pytest.fixture
def wf03_browser():
    # Close our sync Playwright loop before the unchanged secure-cookie and
    # Consolidation fixtures create theirs later in this same role/module.
    from playwright.sync_api import sync_playwright
    with sync_playwright() as pw:
        options={'args':['--no-sandbox']}
        if os.environ.get('FINCO_TEST_CHROMIUM_PATH'):
            options['executable_path']=os.environ['FINCO_TEST_CHROMIUM_PATH']
        instance=pw.chromium.launch(**options)  # Missing runtime fails, never skips.
        try: yield instance
        finally: instance.close()


def _context(browser,origin,owner,width=1440,theme=None,*,accept_dialogs=True):
    from app.auth import COOKIE_NAME, create_session_token, make_session_cookie
    context=browser.new_context(ignore_https_errors=True,viewport={'width':width,'height':1000})
    cookie=make_session_cookie(create_session_token(user_id=owner,username='admin'))
    context.add_cookies([{'name':COOKIE_NAME,'value':cookie['value'],'url':origin,
                         'httpOnly':cookie['httponly'],'secure':cookie['secure'],'sameSite':cookie['samesite'].capitalize()}])
    if theme:
        context.add_init_script('localStorage.setItem("fincoReactTheme",'+json.dumps(theme)+');')
    page=context.new_page()
    errors=[]
    page.on('pageerror',lambda error:errors.append(str(error)))
    if accept_dialogs:
        page.on('dialog',lambda dialog:dialog.accept())
    return context,page,errors


def _financial(record):
    from app.persistence.db import get_cursor
    with get_cursor() as cur:
        state={table:[dict(r) for r in cur.execute(f'SELECT * FROM {table} WHERE project_id=? ORDER BY rowid',(record.project_id,))]
               for table in ('workspace_states','scenarios','capex_sub_lines','opex_sub_lines','model_run_history')}
    raw=json.dumps(state,sort_keys=True,separators=(',',':'),default=str).encode()
    return hashlib.sha256(raw).hexdigest()


def check_visible_https_archive_restore_matrix(servers,browser,template,width,theme):
    from app.services.reference_seed_service import create_reference_seeded_project
    origin,evidence=servers
    owner='wf03-browser-'+uuid.uuid4().hex
    record=create_reference_seeded_project(user_id=owner,template_source=template,requested_name='WF03 browser',capacity_mw=40)
    before=_financial(record)
    context,page,errors=_context(browser,origin,owner,width,theme)
    mutations=[]
    page.on('request',lambda req:mutations.append((req.method,req.url)) if req.method=='POST' else None)
    identity=f'{template}-{width}-{theme or "default"}'
    stage='navigate_library'
    responses=[]
    page.on('response',lambda r:responses.append({
        'method':r.request.method,'status':r.status,
        'path':r.url.split('?',1)[0].split(origin,1)[-1]
    }) if ('/library/projects/' in r.url or '/model-react/' in r.url) else None)
    try:
        page.goto(origin+'/v2/model-react/')
        stage='initial_archive_button'
        page.get_by_role('button',name='Archive project',exact=True).wait_for()
        assert page.evaluate('document.documentElement.scrollWidth<=innerWidth+1')
        assert page.locator('#finco-react-root').get_attribute('data-fm-theme')==theme
        page.screenshot(path=str(evidence/(identity+'-active.png')),full_page=True)
        stage='archive_post'
        with page.expect_response(lambda r:r.request.method=='POST' and r.url.endswith('/archive')) as sent:
            page.get_by_role('button',name='Archive project',exact=True).click()
        assert sent.value.status==200 and sent.value.json()['ok']
        stage='archive_library_refresh'
        page.get_by_role('button',name='Archive project',exact=True).wait_for(state='detached')
        stage='show_archived_projects'
        page.get_by_role('button',name='Show archived projects',exact=True).click()
        stage='archived_library_restore_visible'
        page.get_by_role('button',name='Restore project',exact=True).wait_for()
        assert page.evaluate('document.documentElement.scrollWidth<=innerWidth+1')
        page.screenshot(path=str(evidence/(identity+'-archived.png')),full_page=True)
        stage='archived_project_open'
        page.locator('[data-open-project='+json.dumps(record.project_code)+']').click()
        stage='archived_workspace_interstitial'
        page.locator('[data-workspace-state="PROJECT_ARCHIVED"]').wait_for()
        assert page.get_by_role('button',name='Run model',exact=True).count()==0
        page.screenshot(path=str(evidence/(identity+'-interstitial.png')),full_page=True)
        stage='restore_post'
        with page.expect_response(lambda r:r.request.method=='POST' and r.url.endswith('/unarchive')) as restored:
            page.get_by_role('button',name='Restore project',exact=True).click()
        assert restored.value.status==200 and restored.value.json()['current']['lifecycle_version']==2
        stage='restored_workspace_ready'
        page.locator('[data-workspace-state="PROJECT_ARCHIVED"]').wait_for(state='detached')
        # Assert real application readiness instead of unrelated browser-wide
        # network idleness (optional projections can continue loading).
        page.locator('[data-workspace-status="true"]').wait_for(timeout=30000)
        stage='financial_neutrality_and_no_implicit_run'
        assert _financial(record)==before,'Lifecycle or its visible read flow changed financial state/history'
        assert not any(url.split('?')[0].endswith(('/run','/save-run')) for method,url in mutations)
        assert not errors,errors
        (evidence/(identity+'.json')).write_text(json.dumps({'template':template,'width':width,'theme':theme,
            'https':True,'before_financial_sha256':before,'after_financial_sha256':_financial(record),
            'mutations':mutations,'page_errors':errors,'model_executed':False},indent=2),encoding='utf-8')
    except Exception as exc:
        # Persist the first failing phase independently of pytest's final
        # traceback: the CI supervisor may terminate the full suite early.
        failure_dir=Path('artifacts')/'wf03-archive-failures'
        failure_dir.mkdir(parents=True,exist_ok=True)
        (failure_dir/(identity+'.json')).write_text(json.dumps({
            'case':identity,'stage':stage,'error_type':type(exc).__name__,
            'error':str(exc)[:4000],'http':responses[-40:],
            'page_errors':errors,'mutations':mutations,
        },indent=2),encoding='utf-8')
        try: page.screenshot(path=str(failure_dir/(identity+'.png')),full_page=True,timeout=5000)
        except Exception: pass
        raise
    finally: context.close()


def check_blank_setup_is_durable_explicit_and_non_runnable(servers,browser):
    from app.persistence.db import get_cursor
    origin,evidence=servers
    owner='wf03-draft-browser-'+uuid.uuid4().hex
    context,page,errors=_context(browser,origin,owner,accept_dialogs=False)
    refused=[]
    def refuse_navigation(dialog):
        refused.append(dialog.type)
        dialog.dismiss()
    page.on('dialog',refuse_navigation)
    try:
        page.goto(origin+'/v2/model-react/#new-project')
        page.get_by_role('button',name='Blank setup draft',exact=True).click()
        page.get_by_label('Technology',exact=True).select_option('wind')
        page.get_by_role('button',name='Next',exact=True).click()
        page.get_by_label('Setup name',exact=True).fill('Explicit Wind setup')
        page.get_by_label('Country / market',exact=True).select_option('DE')
        page.locator('[id="setup-project_setup.technical.capacity_mw"]').fill('40')
        page.get_by_role('button',name='Next',exact=True).click()
        page.get_by_role('button',name='Save setup draft',exact=True).click()
        page.get_by_text('Setup draft saved. No runnable project was created and the model was not run.',exact=True).wait_for()
        assert page.get_by_role('button',name='Create runnable project — unavailable',exact=True).is_disabled()
        page.reload()
        page.get_by_text('Resume a saved setup draft',exact=True).click()
        page.get_by_role('button',name='Explicit Wind setup · wind',exact=True).click()
        assert page.get_by_label('Setup name',exact=True).input_value()=='Explicit Wind setup'
        assert page.locator('[id="setup-project_setup.technical.capacity_mw"]').input_value()=='40'
        page.locator('[id="setup-project_setup.technical.capacity_mw"]').fill('41')
        from playwright.sync_api import expect
        expect(page.locator('[data-setup-draft="true"]')).to_have_attribute('data-setup-dirty','true')
        with page.expect_event('dialog'):
            page.go_back()
        assert refused, 'Dirty browser Back must ask before discarding explicit edits'
        assert page.locator('[data-setup-draft="true"]').is_visible()
        assert page.locator('[id="setup-project_setup.technical.capacity_mw"]').input_value()=='41'
        with get_cursor() as cur:
            rows=cur.execute('SELECT * FROM setup_drafts WHERE user_id=?',(owner,)).fetchall()
            assert len(rows)==1 and rows[0]['state']=='SETUP_DRAFT'
            assert json.loads(rows[0]['fields_json'])=={'project_setup.technical.capacity_mw':'40'}
            for table in ('projects','workspace_states','scenarios','model_run_history','save_all_requests'):
                assert cur.execute(f'SELECT count(*) FROM {table} WHERE user_id=?',(owner,)).fetchone()[0]==0
        assert not errors,errors
        page.screenshot(path=str(evidence/'blank-setup-reloaded.png'),full_page=True)
    finally: context.close()


def check_lost_archive_response_then_restore_and_original_replay(servers,browser):
    from app.persistence.db import get_cursor
    from app.services.reference_seed_service import create_reference_seeded_project
    origin,evidence=servers
    owner='wf03-replay-browser-'+uuid.uuid4().hex
    record=create_reference_seeded_project(user_id=owner,template_source='generic_wind_reference',requested_name='Replay',capacity_mw=40)
    before=_financial(record)
    context,page,errors=_context(browser,origin,owner)
    second=context.new_page()
    try:
        page.goto(origin+'/v2/model-react/')
        page.get_by_role('button',name='Archive project',exact=True).wait_for()
        def lose_response(route):
            result=route.fetch()
            assert result.status==200
            route.abort('failed')  # real server commit, lost browser response
        page.route('**/library/projects/*/archive',lose_response)
        page.route('**/lifecycle/status?*',lambda route:route.abort('failed'))
        page.get_by_role('button',name='Archive project',exact=True).click()
        page.get_by_text('The result is unknown.',exact=False).wait_for()
        second.goto(origin+'/v2/model-react/?archived=1')
        second.get_by_role('button',name='Restore project',exact=True).click()
        second.get_by_role('button',name='Restore project',exact=True).wait_for(state='detached')
        page.unroute('**/library/projects/*/archive')
        page.unroute('**/lifecycle/status?*')
        with page.expect_response(lambda r:r.request.method=='POST' and r.url.endswith('/archive')) as replay:
            page.get_by_role('button',name='Archive project',exact=True).click()
        payload=replay.value.json()
        assert payload['replayed'] and payload['receipt']['to_version']==1
        assert payload['current']['archived'] is False and payload['current']['lifecycle_version']==2
        page.get_by_role('button',name='Archive project',exact=True).wait_for()
        assert _financial(record)==before
        with get_cursor() as cur:
            assert cur.execute('SELECT count(*) FROM project_lifecycle_events WHERE project_id=?',(record.project_id,)).fetchone()[0]==2
        assert not errors,errors
        page.screenshot(path=str(evidence/'lost-response-restore-original-replay.png'),full_page=True)
    finally: context.close()
