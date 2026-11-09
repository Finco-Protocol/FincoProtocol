"""Explicit operator execution. Importing this module never starts a browser or request."""
from __future__ import annotations
from collections import Counter
from datetime import datetime,timezone
import hashlib
from pathlib import Path
import signal
import subprocess
import time
from urllib.parse import quote
import uuid
from .browser import Browser,deployment,inspect_route
from .evidence import FIELDS,write_json,write_csv,references,validate,seal
from .lifecycle import blocked_rows,run_project
from .policy import NetworkPolicy,Refused,Session,target,writable_target,PREFIX,digest,checked_scope
from .routes import ROUTES,url_for


def expected_artifacts(args):
    if bool(args.expected_js_sha256)!=bool(args.expected_css_sha256):raise Refused('BOTH_EXPECTED_DIGESTS_REQUIRED')
    if args.expected_js_sha256:return {'js':args.expected_js_sha256,'css':args.expected_css_sha256}
    root=Path(__file__).resolve().parents[2]
    return {ext:hashlib.sha256(p.read_bytes()).hexdigest() if (p:=root/'static/react'/('finco-react.'+ext)).is_file() else None for ext in ('js','css')}


def initial_row(tech,width,route):
    return dict(zip(FIELDS,(''+route.key+'-'+tech+'-'+str(width),tech,width,route.key,route.source,
        route.path+('' if route.global_route else '{synthetic-project}')+('?' + route.query if route.query else '')+route.fragment,
        'NOT_TESTED','NOT_VISITED','','','NOT_CAPTURED','','','','',False,False,0,0,0,0)))


def recheck(rows,refs,production):
    """No numerical, save or wizard-chain PASS from a rendered route."""
    relevant={'L01':{'covenant','debt-metrics'},'L02':{'wizard'},'L03':{'debt-metrics'},'L04':{'financing'},'L05':{'financing'},'L06':{'capex-lines','opex-lines'},'L08':{r.key for r in ROUTES}}
    result=[]
    for i in range(1,11):
        key=f'L{i:02}';selected=[r for r in rows if r['route'] in relevant.get(key,set())]
        passed=[r for r in selected if r['status']=='PASS']
        evidence=';'.join(r['id'] for r in passed)
        state='PARTIAL' if passed else 'NOT_TESTED';verification='LAYOUT_ONLY; no numeric or functional claim'
        constraint='BLOCKED_UNSAFE_TARGET' if production and key in ('L01','L02','L04') else 'FUNCTIONAL_CONTRACT_NOT_EXERCISED'
        if key=='L07':state='NOT_IMPLEMENTED';verification='NOT_IMPLEMENTED_BY_DECISION';constraint='R01-A independent semantics/oracle required'
        if key=='L09':state='NOT_IMPLEMENTED';verification='EXPECTED_UNSUPPORTED';constraint='No new repayment/hedge semantics inferred'
        if key=='L10':state='PARTIAL';verification='See RELEASE_PROVENANCE.json';evidence='RELEASE_PROVENANCE.json';constraint='Frontend byte proof is not backend HTTP proof'
        old=refs.get(key,[])
        result.append({'id':key,'old_evidence_reference':';'.join(x['reference'] for x in old) or 'INPUT_NOT_AVAILABLE',
          'old_status':';'.join(x['status'] for x in old) or 'UNKNOWN','current_verification':verification,'status':state,
          'evidence_id':evidence,'severity':'P1' if key in ('L01','L02') else 'P2','test_identity':'onaccept01-'+key,
          'known_constraint':constraint,'unknown_constraint':'Original claim coverage unresolved' if not old else ''})
    return result


def execute(args):
    started=time.monotonic();base=target(args.base_url);out=Path(args.evidence_dir).resolve()
    if out.exists() and any(out.iterdir()):raise Refused('EVIDENCE_DIRECTORY_MUST_BE_NEW; retained ledger prevents blind duplicate creation')
    # Evidence is private and never goes under application code, source-control metadata or the runner itself.
    checkout=Path(__file__).resolve().parents[2]
    if checkout==out or checkout in out.parents:raise Refused('EVIDENCE_MUST_BE_OUTSIDE_CHECKOUT')
    out.mkdir(parents=True,exist_ok=True);out.chmod(0o700);(out/'screenshots').mkdir()
    session=Session.read(Path(args.session_spec)) if args.session_spec else None
    if args.mode=='synthetic-writable':writable_target(base,args.allow_synthetic_writes)
    elif args.allow_synthetic_writes:raise Refused('WRITE_OPT_IN_IN_READ_ONLY_MODE_REFUSED')
    policy=NetworkPolicy(base,args.mode);production='app.finco.one' in base
    refs,catalog=references([Path(p) for p in args.reference_zip])
    rows=[initial_row(t,w,r) for t in args.technology for w in args.viewports for r in ROUTES]
    functional=blocked_rows(args.technology,'BLOCKED_UNSAFE_TARGET' if production else 'BLOCKED_ENV')
    provenance={'base_url':base,'timestamp_utc':datetime.now(timezone.utc).isoformat(),'frontend':'FRONTEND_NOT_PROVABLE','backend':'BACKEND_NOT_HTTP_VERIFIABLE','artifacts':{}}
    ledger={};run_id=uuid.uuid4().hex[:16];code=2;stop=''
    source={}
    for key,cmd in (('head',['rev-parse','HEAD']),('tree',['rev-parse','HEAD^{tree}']),('branch',['branch','--show-current'])):
        try:source[key]=subprocess.check_output(['git',*cmd],cwd=checkout,text=True,stderr=subprocess.DEVNULL,timeout=2).strip()
        except (OSError,subprocess.SubprocessError):source[key]='SOURCE_NOT_AVAILABLE'
    write_json(out/'PRECHECK.json',{'source':source,'base_url':base,'mode':args.mode,'synthetic_account_configured':bool(session),
      'account_scope_sha256':session.account_scope if session else None,'project_hashes':{t:digest(p['code']) for t,p in session.projects.items()} if session else {},'inputs':catalog,'registry_count':len(ROUTES),
      'technology':args.technology,'viewports':args.viewports,'run_id':run_id,'legacy_get_policy':'BLOCKED_STATEFUL_GET',
      'source_boundary':'No app/engine/writer/wizard/covenant or automatic CI integration'})
    def save_ledger():write_json(out/'PROJECT_LEDGER.private.json',ledger)
    def alarm(*_):raise Refused('GLOBAL_TIMEOUT')
    previous=signal.signal(signal.SIGALRM,alarm);signal.setitimer(signal.ITIMER_REAL,args.global_timeout)
    try:
        with Browser(base,policy,args.route_timeout,started+args.global_timeout,session.storage_state if session else None) as browser:
            provenance.update(deployment(browser,expected_artifacts(args)))
            owned={};auth_verified=False
            if session:
                try:
                    identity=browser.json_get('/v2/model-react/setup-drafts?technology=solar')
                    if identity.get('scope')!=session.account_scope:raise Refused('SYNTHETIC_ACCOUNT_MISMATCH')
                    policy.authenticated=True
                    library=browser.json_get('/v2/model-react/library?page=1')
                    pages=library.get('total_pages')
                    if not isinstance(pages,int) or not 1<=pages<=5:raise Refused('SYNTHETIC_ACCOUNT_INVENTORY_UNPROVEN')
                    for number in range(1,pages+1):
                        inventory=library if number==1 else browser.json_get('/v2/model-react/library?page='+str(number))
                        projects=inventory.get('projects')
                        if not isinstance(projects,list) or any(not str(x.get('name','')).startswith(PREFIX) or x.get('protected_reference') is not False for x in projects):raise Refused('ACCOUNT_CONTAINS_NON_TOOL_PROJECTS')
                    for tech,p in session.projects.items():
                        policy.projects.add(p['code'])
                        payload=browser.json_get('/v2/model-react/workspace?project='+quote(p['code']))
                        checked_scope(payload,p['code'],p['name'],tech)
                        owned[tech]=p['code']
                    auth_verified=True
                except Refused as e:
                    stop=str(e);policy.authenticated=False;owned={}
            if args.mode=='synthetic-writable':
                if not auth_verified:
                    functional=blocked_rows(args.technology,stop or 'BLOCKED_ENV_NO_VERIFIED_SYNTHETIC_SESSION')
                elif provenance['frontend']!='FRONTEND_EXACT_MATCH':
                    functional=blocked_rows(args.technology,'BLOCKED_FRONTEND_PROVENANCE')
                else:
                    functional=[]
                    for tech in args.technology:
                        functional.extend(run_project(browser,tech,PREFIX+run_id+'-'+tech,ledger,save_ledger))
            for row in rows:
                route=next(r for r in ROUTES if r.key==row['route']);project=owned.get(row['technology'])
                if auth_verified and route.key=='login':
                    row.update(status='NOT_SUPPORTED',reason='AUTHENTICATED_LOGIN_NAVIGATION_NOT_REPEATED');continue
                if route.unsafe_get:
                    row.update(status='NOT_SUPPORTED',reason='STATEFUL_LEGACY_GET_NOT_VISITED');continue
                if not auth_verified and route.key!='login':
                    row.update(status='BLOCKED_AUTH',reason=stop or 'ANONYMOUS_DEMO_PROVISIONING_GET_REFUSED');continue
                url=url_for(base,route,project)
                if url is None:
                    row.update(status='BLOCKED_NO_SYNTHETIC_PROJECT',reason='NO_VERIFIED_PREEXISTING_SYNTHETIC_PROJECT');continue
                # Never screenshot a library containing arbitrary projects. Authenticated scope is verified above;
                # operator attests an isolated synthetic-only account in the private session specification.
                row.update(inspect_route(browser,url,route.selector,int(row['viewport']),out,row['id']))
    except KeyboardInterrupt:stop='CANCELLED';code=130
    except Exception as e:stop=str(e) if isinstance(e,Refused) else 'BROWSER_OR_NETWORK_UNAVAILABLE'
    finally:
        signal.setitimer(signal.ITIMER_REAL,0);signal.signal(signal.SIGALRM,previous)
        write_csv(out/'ROUTE_VIEWPORT_MATRIX.csv',rows,FIELDS)
        write_csv(out/'L01_L10_RECHECK.csv',recheck(rows,refs,production))
        write_csv(out/'SYNTHETIC_FUNCTIONAL_MATRIX.csv',functional)
        provenance['request_evidence']={'attempted_mutations':policy.attempted_mutations,'sent_mutations':policy.sent_mutations,
          'blocked_reason_counts':dict(Counter(policy.blocked)),'post_route_and_body_digests_only':policy.posts}
        provenance['observed_backend_headers_sha_only']=sorted(browser.observed_build_headers) if 'browser' in locals() else []
        provenance['backend_header_constraint']='Observed headers alone are not independently verified backend identity.'
        write_json(out/'RELEASE_PROVENANCE.json',provenance)
        write_json(out/'TEST_REPORT.json',{'schema':'ON_ACCEPT01_V1','state':'FINALIZING'})
        failures=validate(out)
        counts=dict(Counter(r['status'] for r in rows))
        if code!=130:
            code=1 if counts.get('FAIL') or provenance['frontend']=='FRONTEND_MISMATCH' or (args.mode=='read-only' and policy.attempted_mutations) else 2 if stop or failures or any(r['status']!='PASS' for r in rows) or any(r['status']!='PASS' for r in functional) else 0
        write_json(out/'TEST_REPORT.json',{'schema':'ON_ACCEPT01_V1','exit_code':code,'verdict':'PASS' if code==0 else 'FAIL' if code==1 else 'BLOCKED',
          'route_counts':counts,'coverage_rows':len(rows),'elapsed_seconds':round(time.monotonic()-started,3),
          'stop_reason':stop,'evidence_failures':failures,'mutations_sent':policy.sent_mutations,
          'claims':'Route PASS means layout/accessibility/network smoke, never Save/Run or L01/L02 semantic acceptance.'})
        (out/'KNOWN_GAPS_AND_NEXT_STEPS.md').write_text('# Explicit limitations\n\nLive L01 boundary and L02 wizard-to-persisted-unit comparisons are not inferred from rendering. Production writes are not implemented. Legacy workbook GET is not read-only and is not visited.\n\n'+(stop or 'See matrices for every unverified operation.')+'\n\nNo per-project disposal API was found; retain private ledger for operator reconciliation. Never reset shared protected/reference demo sessions.\n')
        seal(out)
    return code
