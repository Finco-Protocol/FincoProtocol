"""Authenticated accepted-source regression reference, separate from historical control.

Only successful ordinary mandatory evidence on the event-pinned accepted base (or
an ancestor with the identical Git tree) can supply expectations. No new policy
approval is inferred. Unsupported deletions/outcome changes remain fail closed.
"""
from __future__ import annotations
import hashlib
import json
import os
from pathlib import Path
import re
import shutil
import subprocess
import sys
from tools.ci_v3_schema import require, read_json, write_json, seal, check_seal, skip_counter, worker_count, unique_strings
from tools.ci_v3_hosted_transport import extract_archive
from tools.ci_v3_phase_compare import phase_map, native_cases
from tools.ci_v3_real_contract import outcome

REPO='Finco-Protocol/FincoProtocol'

def git(*args):
    return subprocess.check_output(['git',*args],text=True).strip()

def source_base():
    head=os.environ.get('FINCO_PRODUCTION_BASE','')
    require(re.fullmatch('[0-9a-f]{40}',head) is not None and head!='0'*40,'missing/invalid accepted source base')
    event_path=os.environ.get('GITHUB_EVENT_PATH')
    if event_path:
        event=read_json(event_path)
        expected=event['pull_request']['base']['sha'] if 'pull_request' in event else event.get('before')
        require(head==expected,'accepted source base differs from authenticated event')
    require(git('merge-base','--is-ancestor',head,'HEAD')=='','accepted base is not an ancestor')
    return {'head':head,'tree':git('rev-parse',head+'^{tree}')}

def runtime_inputs_match(root=Path('.')):
    """Changed dependency inputs need a reviewed matching runtime contract."""
    try:
        contract=read_json(root/'docs/ci_v3/phase4/runtime/inputs.json')
        required={'requirements.txt','requirements-ci-tests.txt','constraints.txt',
                  'docs/ci_v3/phase4/runtime/Dockerfile','docs/ci_v3/phase4/runtime/python.lock'}
        require(set(contract)==required,'runtime input contract shape')
        return all(hashlib.sha256((root/name).read_bytes()).hexdigest()==pin for name,pin in contract.items())
    except (OSError,ValueError):
        return False

def runtime_packages(environment):
    expected={}
    for line in Path('docs/ci_v3/phase4/runtime/python.lock').read_text().splitlines():
        if not line.strip() or line.startswith('#'):continue
        name,version=line.split('==');expected[name.lower().replace('_','-')]=version
    actual=dict(environment['packages'])
    require({k:v for k,v in actual.items() if k not in {'pip','setuptools','wheel'}}==expected,'resolved runtime differs from complete Python lock')

def validate_reference(snapshot,base):
    check_seal(snapshot,'ci-v3-source-reference')
    require(snapshot['base']==base,'accepted source reference base mismatch')
    src=snapshot['source']
    require(src['tree']==base['tree'] and git('rev-parse',src['head']+'^{tree}')==base['tree']
            and git('merge-base','--is-ancestor',src['head'],base['head'])=='','false accepted-source tree alias')
    report=snapshot['report']
    require(report['collection']['source']==src and report['pytest_exitstatus']==0 and not report['deselected'], 'reference source/execution mismatch')
    require(report['collection']['complete'] is True and report['collection']['errors']==[],'reference collection incomplete')
    unique_strings(report['collection']['nodes'],'reference collection nodes')
    phases=phase_map(report)
    require(set(report['collection']['nodes'])==set(phases),'reference incomplete original nodes')
    require(set(snapshot['native'])==set(phases),'reference native original nodes missing')
    for n,values in phases.items():
        status=outcome(values)['status'];case=snapshot['native'][n]
        require(status in ('passed','skipped','xfail') and isinstance(case,list) and len(case)==2 and case[0]==status,'reference phase/native outcome mismatch')
    return phases,snapshot['native']

def reconciliation(snapshot,inventory):
    previous=set(snapshot['report']['selected']);current={n['nodeid'] for n in inventory['nodes']}
    removed=sorted(previous-current)
    require(not removed,'original nodes removed; reviewed reconciliation authority required: '+repr(removed[:10]))
    require(skip_counter(snapshot['report']['collection']['skips'])==skip_counter(inventory['collection_skips']),
            'collection skip change; reviewed reconciliation authority required')
    return {'reference_digest':snapshot['digest'],'previous_original_nodes':len(previous),
            'current_original_nodes':len(current),'added':sorted(current-previous),'removed':removed,
            'collection_skips_equal':True,'new_nonpass_policy':'reject','changed_outcomes_policy':'reject'}

def _download(api,run,listing,names,out):
    anchors=[]
    for name in names:
        found=[a for a in listing if a['name']==name and not a['expired']]
        require(len(found)==1,'accepted reference artifact missing/duplicate')
        a=found[0];require(a['workflow_run']['head_sha']==run['head_sha'],'accepted reference artifact source')
        raw=api.raw(f'/repos/{REPO}/actions/artifacts/{a["id"]}/zip',archive=True)
        require('sha256:'+hashlib.sha256(raw).hexdigest()==a['digest'],'accepted reference service archive digest')
        extract_archive(raw,out/name)
        anchors.append({k:a[k] for k in ['id','name','digest']})
    return anchors

def authenticate_reference(api,base,out,anchor=None):
    """Authenticate service bytes, then use that reviewed source's original verifier.

    Reference packages retain a flat snapshot, never recursive archive chains.
    The independent current gate repeats this authentication and compares bytes.
    """
    candidates=[base['head']]
    candidates += [p for p in git('show','-s','--format=%P',base['head']).split()
                   if git('rev-parse',p+'^{tree}')==base['tree']]
    if anchor:
        require(anchor['base']==base and anchor['source']['head'] in candidates,'stale/foreign reference anchor')
        runs=[api.get(f'/repos/{REPO}/actions/runs/{anchor["run_id"]}')]
    else:
        runs=[]
        for head in candidates:
            runs += api.listing(f'/repos/{REPO}/actions/runs?head_sha={head}&status=completed','workflow_runs')
    eligible=[r for r in runs if r['head_sha'] in candidates and r['conclusion']=='success'
              and r['path']=='.github/workflows/public_safety_and_smoke.yml'
              and r.get('head_repository',{}).get('full_name')==REPO]
    require(bool(eligible),'no successful accepted-source mandatory reference; use sequential control')
    run=sorted(eligible,key=lambda r:r['id'],reverse=True)[0]
    if anchor:require(run['run_attempt']==anchor['attempt'],'accepted reference attempt changed')
    head=run['head_sha'];attempt=run['run_attempt'];rid=run['id']
    jobs=api.listing(f'/repos/{REPO}/actions/runs/{rid}/attempts/{attempt}/jobs','jobs')
    for name in ['source-safety','safety-and-smoke / tests','mandatory-evidence']:
        matches=[j for j in jobs if j['name']==name]
        require(len(matches)==1 and matches[0]['status']=='completed' and matches[0]['conclusion']=='success','accepted reference required check failed')
    listing=api.listing(f'/repos/{REPO}/actions/runs/{rid}/artifacts','artifacts')
    parallel=any(a['name']=='public-ci-v3-plan' for a in listing)
    names=['public-source-safety','public-shadow-proof']
    if parallel:
        config=json.loads(git('show',head+':docs/ci_v3/phase4/production-routing.json'))
        count=worker_count(config['worker_count'])
        expected={f'public-ci-v3-worker-{i}' for i in range(count)}
        require({a['name'] for a in listing if a['name'].startswith('public-ci-v3-worker-')}==expected,'accepted reference worker set')
        for i in range(count):
            matches=[j for j in jobs if j['name']=='safety-and-smoke / worker-'+str(i)]
            require(len(matches)==1 and matches[0]['conclusion']=='success','accepted reference worker producer failed')
        names += ['public-ci-v3-plan','public-ci-v3-aggregate',*sorted(expected)]
    else:
        names += ['public-verification-results']
    evidence=out/'evidence';anchors=_download(api,run,listing,names,evidence)
    if anchor:require(anchors==anchor['artifacts'],'accepted reference artifact pins changed')
    clone=out/'checkout'
    subprocess.run(['git','clone','--quiet','--shared','--no-checkout','.',str(clone)],check=True)
    subprocess.run(['git','-C',str(clone),'checkout','--quiet','--detach',head],check=True)
    # This is the authenticated accepted source, not arbitrary PR controller code.
    script='''import sys,json,os
from pathlib import Path
p=Path(sys.argv[1]);head=sys.argv[2];parallel=sys.argv[3]=='true'
if parallel:
 from tools.ci_v3_production import verify_data
 data=json.loads((p/'public-ci-v3-plan/plan.json').read_text())
 os.environ['FINCO_PRODUCTION_BASE']=data.get('source_reference',{}).get('base',{}).get('head','')
 os.environ['FINCO_PRODUCTION_MERGE_SHA']=data.get('merge_guard',{}).get('merge_sha') or ''
 count=data['plan']['worker_count']
 proof=verify_data(p/'public-ci-v3-plan',[p/f'public-ci-v3-worker-{i}' for i in range(count)])
 assert proof==json.loads((p/'public-ci-v3-aggregate/production-proof.json').read_text())==json.loads((p/'public-shadow-proof/parallel-required-proof/production-proof.json').read_text())
 from tools.ci_v3_phase_compare import native_cases
 reports=[json.loads((p/f'public-ci-v3-worker-{i}/execution/child/adapter.json').read_text()) for i in range(count)]
 natives={}
 for i,r in enumerate(reports):natives.update(native_cases((p/f'public-ci-v3-worker-{i}/execution/child/native.xml').read_bytes(),r))
 report={'source':data['context']['source'],'collection':reports[0]['collection'],'selected':sorted(n for r in reports for n in r['selected']),'deselected':[], 'phases':[ph for r in reports for ph in r['phases']],'pytest_exitstatus':0,'environment':reports[0]['environment']}
 # A combined summary is not an original adapter envelope; never reuse its digest.
else:
 from tools.ci_single_gate import verify_control
 from tools.ci_v3_phase_compare import control_report,native_cases
 guard=json.loads((p/'public-verification-results/merge-tree.json').read_text())
 proof=verify_control(p,head,'success','success',guard.get('merge_sha'))
 assert proof==json.loads((p/'public-shadow-proof/public-single-proof.json').read_text())
 report=control_report(json.loads((p/'public-verification-results/inventory.json').read_text()))
 natives=native_cases((p/'public-verification-results/results.xml').read_bytes(),report)
Path(sys.argv[4]).write_text(json.dumps({'report':report,'native':natives}))
'''
    src={'head':head,'tree':git('rev-parse',head+'^{tree}')}
    env={**os.environ,'FINCO_PRODUCTION_HEAD':head,'GITHUB_RUN_ID':str(rid),'GITHUB_RUN_ATTEMPT':str(attempt),'GITHUB_REPOSITORY':REPO,'GITHUB_EVENT_PATH':''}
    result=out/'result.json'
    subprocess.run([sys.executable,'-c',script,str(evidence.resolve()),head,str(parallel).lower(),str(result.resolve())],cwd=clone,env=env,check=True)
    raw=read_json(result);snapshot=seal({'schema':1,'kind':'ci-v3-source-reference','base':base,'source':src,
             'run_id':rid,'attempt':attempt,'artifacts':anchors,'report':raw['report'],'native':raw['native']})
    validate_reference(snapshot,base)
    shutil.rmtree(clone);shutil.rmtree(evidence);result.unlink()
    return snapshot
