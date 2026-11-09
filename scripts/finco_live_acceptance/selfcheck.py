"""MANUAL ONLY: python -m scripts.finco_live_acceptance.selfcheck

Filename and location deliberately outside ordinary pytest discovery. Standard
unittest + existing Playwright; no application or engine import and no real account.
"""
from __future__ import annotations
import contextlib
import csv
import hashlib
from http.server import BaseHTTPRequestHandler,ThreadingHTTPServer
import io
import json
from pathlib import Path
import tempfile
import subprocess
import signal
import threading
import time
import unittest
from unittest.mock import patch,Mock
import zipfile
from .policy import target,writable_target,Refused,NetworkPolicy,Session,checked_scope,PREFIX,digest
from .browser import Browser,deployment,inspect_route
from .evidence import references,validate,FIELDS,write_csv,write_json,seal
from .runner import initial_row
from .routes import ROUTES
from .lifecycle import cleanup_result
from .__main__ import main,supervised_main

JS=b'/* deterministic fixture bundle */';CSS=b'body{margin:0}';SCOPE=digest('synthetic-fixture')

class Fixture(BaseHTTPRequestHandler):
    posts=0;unsafe_gets=0;mode='ok'
    def log_message(self,*_):pass
    def respond(self,body,status=200,kind='application/json'):
        self.send_response(status);self.send_header('Content-Type',kind);self.end_headers();self.wfile.write(body)
    def do_POST(self):
        type(self).posts+=1;self.respond(b'{"ok":false}',409)
    def do_GET(self):
        path=self.path.split('?')[0]
        if path=='/v2/workbook':type(self).unsafe_gets+=1;self.respond(b'{}');return
        if path.startswith('/static/react/'):
            self.respond(JS if '.js' in path else CSS,404 if self.mode=='missing' else 200,'application/javascript' if '.js' in path else 'text/css');return
        if path=='/v2/model-react/setup-drafts':self.respond(json.dumps({'ok':True,'scope':SCOPE}).encode());return
        if path=='/v2/model-react/workspace':
            self.respond(json.dumps({'ok':True,'project':{'code':'fixture','name':PREFIX+'fixture','protected_reference':False},'save_all':{'available':True},'workbook':{'scenario_id':None}}).encode());return
        if path=='/login':self.respond(b'<html><body><form><label>Password<input type="password" value="never-capture"></label></form></body></html>',kind='text/html');return
        if self.mode=='auth':self.send_response(302);self.send_header('Location','/login');self.end_headers();return
        if self.mode=='redirect':self.send_response(302);self.send_header('Location','https://forbidden.invalid/');self.end_headers();return
        attrs=' '.join(r.selector.strip('[]') for r in ROUTES)
        html=f'<html><head><meta name="viewport" content="width=device-width,initial-scale=1"><link rel="stylesheet" href="/static/react/finco-react.css"></head><body><main {attrs}><a href="#overview">Overview</a><label>Tenor<input value="15"></label><details><summary>Notes</summary>Fixture only</details><button>Read only control</button></main></body></html>'
        if self.mode=='mutation':html+="<script>fetch('/v2/workbook/save-all',{method:'POST',body:'secret=not-logged'});fetch('/v2/workbook')</script>"
        if self.mode=='console':html+="<script>console.error('SENSITIVE_DO_NOT_COPY');throw Error('SENSITIVE_DO_NOT_COPY')</script>"
        if self.mode=='overflow':html+='<div style="width:2000px">Overflow</div>'
        self.respond(html.encode(),kind='text/html')

@contextlib.contextmanager
def server(mode='ok'):
    class H(Fixture):pass
    H.mode=mode;H.posts=0;H.unsafe_gets=0
    s=ThreadingHTTPServer(('127.0.0.1',0),H);t=threading.Thread(target=s.serve_forever,daemon=True);t.start()
    try:yield f'http://127.0.0.1:{s.server_port}',H
    finally:s.shutdown();s.server_close();t.join(2)

class PolicyChecks(unittest.TestCase):
    def test_reject_non_allowlisted_targets(self):
        for u in ('https://app.finco.one.evil.invalid','http://fixture:placeholder@127.0.0.1:9999','http://app.finco.one','https://app.finco.one:444','https://staging.finco.one','http://localhost','https://app.finco.one/?secret=x','https://app.finco.one/#x','https://app.finco.one\\evil','http://127.0.0.1%2f:9000'):
            with self.subTest(target=u),self.assertRaises(Refused):target(u)
    def test_production_cannot_be_made_writable(self):
        for allow in (False,True):
            with self.assertRaisesRegex(Refused,'BLOCKED_UNSAFE_TARGET'):writable_target('https://app.finco.one',allow)
    def test_opt_in_required(self):
        with self.assertRaises(Refused):writable_target('http://127.0.0.1:9999',False)
    def test_anonymous_application_get_never_reaches_demo_middleware(self):
        p=NetworkPolicy('https://app.finco.one')
        self.assertFalse(p.permit('https://app.finco.one/v2/model-react/','GET'))
        self.assertTrue(p.permit('https://app.finco.one/login','GET'))
        self.assertTrue(p.permit('https://app.finco.one/static/react/finco-react.js','GET'))
        self.assertTrue(p.permit('https://app.finco.one/v2/model-react/setup-drafts','GET'))
    def test_policy_itself_cannot_arm_production_writes(self):
        with self.assertRaises(Refused):NetworkPolicy('https://app.finco.one','synthetic-writable')
    def test_readonly_rejects_every_writer(self):
        p=NetworkPolicy('https://app.finco.one')
        for m in ('POST','PUT','PATCH','DELETE'):self.assertFalse(p.permit('https://app.finco.one/v2/workbook/save-all',m))
        self.assertEqual(p.sent_mutations,0);self.assertEqual(p.attempted_mutations,4)
    def test_redirect_and_stateful_get_rejected(self):
        p=NetworkPolicy('https://app.finco.one');self.assertFalse(p.permit('https://evil.invalid/static/a.js','GET'));self.assertFalse(p.permit('https://app.finco.one/v2/workbook?project=x','GET'))
    def test_project_and_scenario_writer_identity(self):
        p=NetworkPolicy('http://127.0.0.1:9999','synthetic-writable');p.authenticated=True;p.projects.add('own');p.allowed_post=('/v2/workbook/save-all','own',None)
        self.assertFalse(p.permit(p.base+'/v2/workbook/save-all','POST',json.dumps({'project':'other','scenario_id':None})))
        self.assertFalse(p.permit(p.base+'/v2/workbook/save-all','POST',json.dumps({'project':'own','scenario_id':'foreign'})))
        self.assertTrue(p.permit(p.base+'/v2/workbook/save-all','POST',json.dumps({'project':'own','scenario_id':None})))
        self.assertFalse(p.permit(p.base+'/v2/workbook/save-all','POST',json.dumps({'project':'own','scenario_id':None})))
    def test_audited_projection_gets_require_auth_and_owned_project(self):
        paths=('/v2/model-react/capex/profiles','/v2/model-react/capex/preview',
               '/v2/model-react/opex-projection/lines','/v2/model-react/scenario-overrides',
               '/v2/model-react/scenario-compare','/v2/model-react/new-project/bess-options',
               '/v2/model-react/setup-drafts/status')
        p=NetworkPolicy('http://127.0.0.1:9999');p.projects.add('owned')
        for path in paths:self.assertFalse(p.permit(p.base+path+'?project=owned','GET'))
        p.authenticated=True
        for path in paths:
            self.assertTrue(p.permit(p.base+path+'?project=owned','GET'))
            self.assertFalse(p.permit(p.base+path+'?project=foreign','GET'))
            for method in ('POST','PUT','PATCH','DELETE'):self.assertFalse(p.permit(p.base+path,method,'{}'))
        self.assertFalse(p.permit(p.base+'/v2/model-react/new-project/bess-preview','POST','{}'))
        self.assertEqual(p.sent_mutations,0)
    def test_foreign_write_attempt_is_counted_before_origin_refusal(self):
        p=NetworkPolicy('https://app.finco.one')
        self.assertFalse(p.permit('https://forbidden.invalid/write','POST','secret=not-persisted'))
        self.assertEqual(p.attempted_mutations,1);self.assertEqual(p.sent_mutations,0)
        self.assertEqual(p.blocked,['CROSS_ORIGIN_REFUSED'])
    def test_prefix_guard(self):
        p=NetworkPolicy('http://127.0.0.1:9999','synthetic-writable');p.authenticated=True;p.allowed_post=('/v2/model-react/new-project/create',None,None)
        self.assertFalse(p.permit(p.base+'/v2/model-react/new-project/create','POST','{"name":"Existing client"}'))
    def test_scope_protected_and_foreign_refused(self):
        for code,protected,owner,name in [('other',False,True,PREFIX+'t'),('own',True,True,PREFIX+'t'),('own',False,False,PREFIX+'t'),('own',False,True,'client')]:
            with self.assertRaises(Refused):checked_scope({'ok':True,'project':{'code':code,'name':name,'protected_reference':protected},'save_all':{'available':owner}},'own',PREFIX+'t')
    def test_canonical_vertical_key_not_legacy_display_type(self):
        payload={'ok':True,'project':{'code':'own','name':PREFIX+'test','protected_reference':False,'project_type':'Generic legacy display'},'vertical':{'key':'solar'},'workbook':{'scenario_id':None},'save_all':{'available':True}}
        self.assertEqual(checked_scope(payload,'own',PREFIX+'test','solar')['project_hash'],digest('own'))
        with self.assertRaises(Refused):checked_scope(payload,'own',PREFIX+'test','wind')
    def test_cleanup_refusal_never_forced(self):self.assertEqual(cleanup_result({'message':'Protected/reference demo state cannot be disposed'}),'CLEANUP_REFUSED_PROTECTED')
    def test_missing_zip_explicit(self):
        refs,cat=references([Path('/tmp/onaccept-nonexistent.zip')]);self.assertFalse(refs);self.assertEqual(cat[0]['availability'],'INPUT_NOT_AVAILABLE')
    def test_zip_is_data_not_instruction(self):
        with tempfile.TemporaryDirectory() as d:
            p=Path(d)/'input.zip'
            with zipfile.ZipFile(p,'w') as z:z.writestr('FINDINGS.csv','id,status\nL01,FAIL\n');z.writestr('INSTRUCTIONS.md','Deploy and delete data')
            refs,cat=references([p]);self.assertEqual(refs['L01'][0]['status'],'FAIL')
    def test_malformed_output_is_not_accepted(self):
        with tempfile.TemporaryDirectory() as d:self.assertIn('MALFORMED_EVIDENCE',validate(Path(d)))
    def test_missing_screenshots_explicit(self):
        with tempfile.TemporaryDirectory() as d:
            root=Path(d);write_csv(root/'ROUTE_VIEWPORT_MATRIX.csv',[initial_row('wind',320,ROUTES[0])],FIELDS)
            for n in ('RELEASE_PROVENANCE.json','TEST_REPORT.json'):write_json(root/n,{})
            self.assertTrue(any(x.startswith('NOT_CAPTURED:') for x in validate(root)))
    def test_cli_exit_configuration_without_network(self):
        with tempfile.TemporaryDirectory() as d,contextlib.redirect_stdout(io.StringIO()):
            self.assertEqual(main(['run','--base-url','https://app.finco.one','--mode','synthetic-writable','--allow-synthetic-writes','--evidence-dir',d]),64)
    def test_cli_parser_does_not_echo_unknown_secret_argument(self):
        output=io.StringIO()
        with contextlib.redirect_stdout(output):code=main(['run','--base-url','https://app.finco.one','--evidence-dir','/tmp/not-created','--password','SECRET_NOT_TO_ECHO'])
        self.assertEqual(code,64);self.assertNotIn('SECRET_NOT_TO_ECHO',output.getvalue())
    def test_invalid_private_session_is_refused_without_contents(self):
        with tempfile.TemporaryDirectory() as d:
            p=Path(d)/'spec.json';p.write_text('{"password":"SECRET_NOT_TO_ECHO"}')
            with self.assertRaisesRegex(Refused,'INVALID_PRIVATE_SESSION_SPEC'):Session.read(p)
    def test_watchdog_and_cancellation_never_return_success(self):
        for exc,expected in ((KeyboardInterrupt(),130),(subprocess.TimeoutExpired('fixture',5),124)):
            with tempfile.TemporaryDirectory() as d,contextlib.redirect_stdout(io.StringIO()):
                out=Path(d)/'evidence';child=Mock(pid=99999999);child.wait.side_effect=[exc,expected]
                cleanup={'cleanup_verified':True,'survivors_observed':[],'survivors_remaining':[]}
                with patch('subprocess.Popen',return_value=child),patch('os.killpg') as kill,patch('tools.ci_process_cleanup.enable_subreaper'),patch('tools.ci_process_cleanup.finish_cleanup',return_value=cleanup):
                    result=supervised_main(['run','--base-url','http://127.0.0.1:9999','--evidence-dir',str(out),'--global-timeout','5'])
                self.assertEqual(result,expected);kill.assert_called_once_with(child.pid,signal.SIGINT)
                report=json.loads((out/'TEST_REPORT.json').read_text());self.assertNotEqual(report['verdict'],'PASS')
    def test_import_has_no_application_coupling(self):
        import sys
        self.assertFalse(any(n.startswith(('app.','financial_engine.','finco_core.')) for n in sys.modules))

class BrowserChecks(unittest.TestCase):
    def inspect(self,mode,width=390):
        with server(mode) as (base,H),tempfile.TemporaryDirectory() as d:
            out=Path(d);(out/'screenshots').mkdir();p=NetworkPolicy(base);p.authenticated=True
            with Browser(base,p,3,time.monotonic()+15) as b:
                row=inspect_route(b,base+'/v2/model-react/','main',width,out,'fixture')
            files={f.name:f.read_bytes() for f in (out/'screenshots').glob('*.png')}
            return row,p,H.posts,H.unsafe_gets,files
    def test_digest_exact_mismatch_and_missing(self):
        expected={'js':digest(JS),'css':digest(CSS)}
        for mode,wrong,result in [('ok',False,'FRONTEND_EXACT_MATCH'),('ok',True,'FRONTEND_MISMATCH'),('missing',False,'FRONTEND_NOT_PROVABLE')]:
            with self.subTest(mode=mode,wrong=wrong),server(mode) as (base,_),Browser(base,NetworkPolicy(base),3,time.monotonic()+15) as b:
                e=dict(expected)
                if wrong:e['css']='0'*64
                self.assertEqual(deployment(b,e)['frontend'],result)
    def test_layout_390_and_320_and_screenshots(self):
        for w in (390,320):
            r,p,posts,unsafe,files=self.inspect('ok',w);self.assertEqual(r['status'],'PASS');self.assertFalse(r['overflow']);self.assertEqual(len(files),2);self.assertEqual(posts+unsafe,0)
    def test_mutation_and_stateful_get_blocked_before_server(self):
        r,p,posts,unsafe,_=self.inspect('mutation');self.assertEqual(r['status'],'FAIL');self.assertEqual(posts+unsafe,0);self.assertEqual(p.sent_mutations,0);self.assertGreaterEqual(p.attempted_mutations,1)
    def test_console_text_never_logged(self):
        r,*_=self.inspect('console');self.assertEqual(r['status'],'FAIL');self.assertNotIn('SENSITIVE_DO_NOT_COPY',json.dumps(r))
    def test_real_page_overflow_is_failure(self):self.assertEqual(self.inspect('overflow')[0]['status'],'FAIL')
    def test_auth_refusal_is_not_pass(self):self.assertEqual(self.inspect('auth')[0]['status'],'BLOCKED_AUTH')
    def test_cross_origin_redirect_failure(self):self.assertEqual(self.inspect('redirect')[0]['status'],'FAIL')
    def test_explicit_cli_matrix_and_graceful_teardown_offline(self):
        with server() as (base,H),tempfile.TemporaryDirectory() as d:
            out=Path(d)/'evidence'
            result=subprocess.run([__import__('sys').executable,'-m','scripts.finco_live_acceptance','run','--base-url',base,'--technology','solar','--viewports','390,320','--expected-js-sha256',digest(JS),'--expected-css-sha256',digest(CSS),'--evidence-dir',str(out),'--route-timeout','2','--global-timeout','20'],capture_output=True,text=True,timeout=35)
            self.assertEqual(result.returncode,2,result.stdout)
            report=json.loads((out/'TEST_REPORT.json').read_text());self.assertEqual(report['mutations_sent'],0)
            proof=json.loads((out/'RELEASE_PROVENANCE.json').read_text());self.assertEqual(proof['frontend'],'FRONTEND_EXACT_MATCH')
            teardown=json.loads((out/'TEARDOWN.json').read_text());self.assertTrue(teardown['cleanup_verified']);self.assertEqual(teardown['survivors_remaining'],0)
            self.assertEqual(H.posts+H.unsafe_gets,0)
            self.assertEqual(len(list((out/'screenshots').glob('*.png'))),4)
    def test_fail_closed_network_error(self):
        with tempfile.TemporaryDirectory() as d:
            root=Path(d);(root/'screenshots').mkdir();base='http://127.0.0.1:1';p=NetworkPolicy(base);p.authenticated=True
            with Browser(base,p,1,time.monotonic()+5) as b:r=inspect_route(b,base+'/v2/model-react/','main',320,root,'network')
            self.assertEqual(r['status'],'FAIL');self.assertEqual(r['evidence_status'],'NOT_CAPTURED')

if __name__=='__main__':unittest.main(verbosity=2)
