"""Owner-directed production on private run-built images; no synthetic admission.

The original authenticated sequential baseline remains historical. Current-source
collection and every executed phase are verified independently in this run.
"""
from __future__ import annotations
import argparse
from collections import Counter
import hashlib,json,os,subprocess,sys
from pathlib import Path
from tools.ci_v3_schema import read_json,write_json,require,seal,skip_counter,validate_inventory,check_seal,worker_count,ContractError
from tools.ci_v3_container import observe_container
from tools.ci_v3_partition_plan import plan_partitions
from tools.ci_v3_phase_compare import control_report,phase_map,native_cases
from tools.ci_v3_pytest_config import semantic_plugin_profile
from tools.ci_v3_real_contract import outcome
from tools.ci_v3_hosted_transport import GitHub,extract_archive

REPO='Finco-Protocol/FincoProtocol'
BASE_HEAD='e96561a220fc6adeb85587eb01d61745a922ab41'
BASE_RUN=39971606511
BASE_ARCHIVES={'public-verification-results': (12516255156, '6a00783ef7639f4a3cd60e89118265eb0870ffe6a0d0df753afa84bc8aba5faf'), 'public-shadow-proof': (12515687491, 'af888a778831b20bd4330ef0b74632b34dbba20af0ad245be22513deea591583'), 'public-source-safety': (12509561813, '2e08315411661bebc18c3efd4e89de54c214c03a1252b7427715050810a4f7af')}

from tools.ci_v3_source_reference import source_base, authenticate_reference, validate_reference, reconciliation, runtime_inputs_match, runtime_packages

ROUTING=Path(__file__).resolve().parents[1]/'docs/ci_v3/phase4/production-routing.json'

def routing():
 value=read_json(ROUTING);worker_count(value.get('worker_count'))
 require(type(value.get('enabled')) is bool and type(value.get('rollback')) is bool,'invalid routing switches')
 return value

def route_mode(config,trusted,rollback,runtime_compatible,reference_ready):
 return 'parallel' if config['enabled'] and not config['rollback'] and rollback!='true' and trusted and runtime_compatible and reference_ready else 'sequential'

def validate_reference_policy(reference, historical):
 # A successful legacy control is evidence, not a Financial/CI nonpass approval.
 original=phase_map(historical);accepted=phase_map(reference['report'])
 require(set(original)<=set(accepted),'accepted reference lost historical coverage')
 for node,values in accepted.items():
  if node in original:require(values==original[node],'accepted reference changed historical outcomes')
  else:require(outcome(values)['status']=='passed','accepted reference has nonhistorical nonpass; sequential bootstrap required: '+node)

def require_reference_runtime(reference):
 # A different software contract needs a fresh sequential control, before workers.
 path='docs/ci_v3/phase4/runtime/inputs.json'
 previous=subprocess.check_output(['git','show',reference['source']['head']+':'+path])
 require(json.loads(previous)==read_json(path),'accepted-source runtime inputs changed; sequential bootstrap required')

def route_preflight(out):
 config=routing();ctx=context()
 trusted=os.environ['GITHUB_EVENT_NAME'] in ('push','pull_request') and (os.environ['GITHUB_EVENT_NAME']!='pull_request' or os.environ.get('SOURCE_REPO')==REPO)
 compatible=runtime_inputs_match();ready=False;reason='disabled, rollback, untrusted source or incompatible runtime'
 if route_mode(config,trusted,os.environ.get('ROLLBACK',''),compatible,True)=='parallel':
  try:
   api=GitHub();reference=authenticate_reference(api,source_base(),out/'reference')
   require_reference_runtime(reference)
   historical=authenticate_baseline(api,out/'historical')
   validate_reference_policy(reference,historical)
   write_json(out/'source-reference.json',reference);ready=True;reason='accepted-source reference authenticated'
  except (ValueError,OSError,subprocess.CalledProcessError) as error:
   reason='accepted-source evidence unavailable: '+str(error)
 mode=route_mode(config,trusted,os.environ.get('ROLLBACK',''),compatible,ready)
 with open(os.environ['GITHUB_OUTPUT'],'a') as stream:print('execution_mode='+mode,file=stream)
 print('CI_V3_ROUTE='+mode+'; '+reason)

def validate_merge_guard(guard):
 src=context()['source'];expected=os.environ.get('FINCO_PRODUCTION_MERGE_SHA','')
 require(guard.get('head')==src['head'] and guard.get('tree')==src['tree'] and guard.get('equivalent') is True,'merge-tree source binding')
 if expected:
  require(guard.get('mode')=='identical-tree' and guard.get('merge_sha')==expected and guard.get('merge_tree')==src['tree'],'synthetic merge-tree binding')
 else:
  require(guard.get('mode')=='main-head' and guard.get('merge_sha') is None and guard.get('merge_tree') is None,'main source merge-tree binding')

def production_plan(folder):
 data=read_json(folder/'plan.json');plan=data['plan']
 check_seal(plan,'ci-v3-plan');validate_inventory(data['inventory'])
 count=worker_count(plan.get('worker_count'))
 require(count==routing()['worker_count'],'configured/plan worker count drift')
 names={f'worker-{i}' for i in range(count)}
 owners=plan['module_workers']
 require(set(owners)==set(data['inventory']['modules']) and set(owners.values())==names,'incomplete/foreign/empty worker assignment')
 require(plan['source']==data['inventory']['source']==context()['source'] and plan['inventory_digest']==data['inventory']['digest'],'plan inventory/source drift')
 require(data['context']==context(),'plan source/run/attempt drift')
 return data

def worker_matrix(folder):
 data=production_plan(folder);owners=data['plan']['module_workers']
 return {'include':[{'index':i,'nodes':sum(owners[n['module']]==f'worker-{i}' for n in data['inventory']['nodes'])} for i in range(data['plan']['worker_count'])]}

def git(*a):return subprocess.check_output(['git',*a],text=True).strip()
def context():
 source={'head':git('rev-parse','HEAD'),'tree':git('rev-parse','HEAD^{tree}')}
 require(source['head']==os.environ['FINCO_PRODUCTION_HEAD'],'source drift')
 require(os.environ['GITHUB_REPOSITORY']==REPO,'foreign repository')
 return {'source':source,'repository':REPO,'run_id':os.environ['GITHUB_RUN_ID'],'attempt':int(os.environ['GITHUB_RUN_ATTEMPT'])}
def sha(path):return hashlib.sha256(Path(path).read_bytes()).hexdigest()
def files(folder):return {str(f.relative_to(folder)):sha(f) for f in sorted(Path(folder).rglob('*')) if f.is_file()}

def authenticate_baseline(api,out):
 run=api.get(f'/repos/{REPO}/actions/runs/{BASE_RUN}')
 require(run['head_sha']==BASE_HEAD and run['run_attempt']==1 and run['conclusion']=='success'
         and run['path']=='.github/workflows/public_safety_and_smoke.yml','baseline service identity')
 listing=api.listing(f'/repos/{REPO}/actions/runs/{BASE_RUN}/artifacts','artifacts')
 for name,(ident,pin) in BASE_ARCHIVES.items():
  matches=[a for a in listing if a['id']==ident and a['name']==name and a['digest']=='sha256:'+pin and not a['expired']]
  require(len(matches)==1,'baseline archive service pin')
  data=api.raw(f'/repos/{REPO}/actions/artifacts/{ident}/zip',archive=True)
  require(hashlib.sha256(data).hexdigest()==pin,'baseline archive bytes')
  extract_archive(data,out/name)
 raw=read_json(out/'public-verification-results/inventory.json');report=control_report(raw)
 require(report['source']['head']==BASE_HEAD and report['pytest_exitstatus']==0 and not report['deselected'],'baseline full execution')
 proc=read_json(out/'public-verification-results/process.json');cleanup=proc.get('process_markers',{}).get('cleanup',{})
 require(proc.get('cleanup_verified') is True and cleanup.get('mechanism')=='linux-subreaper-proc-waitpid-v1'
         and cleanup.get('cleanup_verified') is True and cleanup.get('survivors_observed')==cleanup.get('survivors_remaining')==[], 'baseline descendant cleanup')
 phase_map(report);native_cases((out/'public-verification-results/results.xml').read_bytes(),report)
 require(git('merge-base','--is-ancestor',BASE_HEAD,'HEAD')=='','baseline ancestry')
 # Authenticate this historical source in its original checkout. Current-source
 # expectations come from the separately authenticated accepted-source reference.
 guard=read_json(out/'public-verification-results/merge-tree.json')
 clone=out/'original-checkout'
 subprocess.run(['git','clone','--quiet','--shared','--no-checkout','.',str(clone)],check=True)
 subprocess.run(['git','-C',str(clone),'checkout','--quiet','--detach',BASE_HEAD],check=True)
 code='from pathlib import Path;from tools.ci_single_gate import verify_control;import json,sys;v=verify_control(Path(sys.argv[1]),sys.argv[2],"success","success",sys.argv[3]);assert v==json.loads((Path(sys.argv[1])/"public-shadow-proof/public-single-proof.json").read_text())'
 subprocess.run([sys.executable,'-c',code,str(out.resolve()),BASE_HEAD,guard['merge_sha']],cwd=clone,check=True)
 import shutil
 shutil.rmtree(clone)
 return report

def inventory(report):
 return seal({'schema':1,'kind':'ci-v3-inventory','authority':'offline-prototype','source':report['collection']['source'],'repository':REPO,
  'nodes':[{'nodeid':n,'module':n.split('::')[0],'fixture_unit':n.split('::')[0],'execution_owner':'plan.module_workers','optional_overlap_ownership':'policy.module_overlaps','domain':'F','confidence':'unresolved','mandatory':True,'obligations':['full-regression'],'dependency_evidence':'actual complete run collection'} for n in report['collection']['nodes']],
  'modules':{n.split('::')[0]:{'isolation_review':'unproven','dependency_evidence':{}} for n in report['collection']['nodes']},'collection_skips':report['collection']['skips']})

def make_plan(project,out,image):
 ctx=context();api=GitHub();baseline=authenticate_baseline(api,out/'baseline')
 reference=authenticate_reference(api,source_base(),out/'reference')
 historical=set(baseline['selected']);require(historical<=set(reference['report']['selected']),'accepted reference lost historical coverage')
 guard=read_json('merge-tree.json');validate_merge_guard(guard)
 require(runtime_inputs_match(),'runtime source inputs changed without a reviewed contract')
 child,proc=observe_container({'mode':'discover','worker':None,'context':ctx},out/'collection',project,image,900,built_image=True)
 require(proc['normal_successful_exit'],'collection/cleanup failed')
 report=read_json(child/'adapter.json');require(not report['phases'] and not report['unauthorized_deselection'],'collection executed/deselected')
 inv=inventory(report);old=set(baseline['selected']);require(old<=set(report['collection']['nodes']),'original nodes lost')
 changes=reconciliation(reference,inv)
 runtime_packages(report['environment'])
 policy=seal({'schema':1,'kind':'ci-v3-policy','authority':'offline-prototype','inventory_digest':inv['digest'],'new_nodes':'fail-closed','selective_execution':False,'module_overlaps':{},'allowed_nonpass':{}})
 times=Counter()
 for ph in baseline['phases']:times[ph['nodeid'].split('::')[0]]+=round(ph.get('duration_s',ph.get('duration',0))*1000)
 # JUnit native duration is measured baseline input, never current-source timing.
 import xml.etree.ElementTree as ET
 from tools.ci_v3_nonpass import node_id
 for c in ET.parse(out/'baseline/public-verification-results/results.xml').iter('testcase'):
  if c.get('classname'):times[node_id(c.get('classname'),c.get('name'),set(inv['modules'])).split('::')[0]]+=round(float(c.get('time','0'))*1000)
 counts=Counter(n['module'] for n in inv['nodes'])
 weights=seal({'schema':1,'kind':'ci-v3-weights','source':ctx['source'],'inventory_digest':inv['digest'],'modules_ms':{m:max(1,times.get(m,counts[m]*1000)) for m in inv['modules']},'measurement':'historical authenticated native JUnit durations; new modules node-count proxy'})
 config=routing();groups=config['groups']
 plan=plan_partitions(inv,policy,weights,workers=config['worker_count'],groups=groups)
 require(set(plan['module_workers'].values())=={f'worker-{i}' for i in range(config['worker_count'])},'empty production worker')
 write_json(out/'plan.json',{'context':ctx,'inventory':inv,'plan':plan,'image':image,'image_archive_sha256':sha('runtime-image.tar.gz'),'collection_environment':report['environment'],'collection_plugins':semantic_plugin_profile(report['plugin_registrations']),'baseline_original_source':baseline['source'],'baseline_is_current_source':False,'groups':groups,'source_reference':reference,'inventory_reconciliation':changes,'merge_guard':guard,'runtime_inputs':read_json('docs/ci_v3/phase4/runtime/inputs.json')})
 write_json(out/'collection-process.json',proc)
 # Keep only actual evidence, never Git clones/bootstrap copies/databases.
 import shutil
 for name in ['source','bootstrap']:shutil.rmtree(out/'collection'/name)

def worker(project,out,planfolder,index):
 plan=production_plan(planfolder)
 require(type(index) is int and 0 <= index < plan['plan']['worker_count'],'worker index outside plan')
 require(sha('runtime-image.tar.gz')==plan['image_archive_sha256'],'runtime transfer bytes')
 subprocess.run(['docker','load','--input','runtime-image.tar.gz'],check=True)
 request={'mode':'worker','worker':f'worker-{index}','context':context(),'inventory':plan['inventory'],'owned_modules':[m for m,w in plan['plan']['module_workers'].items() if w==f'worker-{index}'],'target_calibration':{'ceiling_s':.6,'statistic':'maximum','samples':3}}
 child,proc=observe_container(request,out/'execution',project,plan['image'],5400,built_image=True)
 write_json(out/'process.json',proc);write_json(out/'binding.json',{'context':context(),'worker':index,'plan_sha256':sha(planfolder/'plan.json'),'image':plan['image']})
 import shutil
 for name in ['source','bootstrap']:shutil.rmtree(out/'execution'/name)
 # Transient databases/build trees are not evidence. Keep all native XML,
 # lossless reports, process/cleanup/calibration receipts and original logs.
 shutil.rmtree(out/'execution/child/tmp')
 require(proc['normal_successful_exit'],'worker failure or cleanup failure')

def verify_data(planfolder,workers):
 data=production_plan(planfolder)
 require(len(workers)==data['plan']['worker_count'],'missing/extra worker artifacts')
 validate_inventory(data['inventory']);check_seal(data['plan'],'ci-v3-plan')
 require(data['inventory']['source']==data['plan']['source']==context()['source'] and data['plan']['inventory_digest']==data['inventory']['digest'], 'plan inventory/source drift')
 baseline=control_report(read_json(planfolder/'baseline/public-verification-results/inventory.json'));bp=phase_map(baseline);bn=native_cases((planfolder/'baseline/public-verification-results/results.xml').read_bytes(),baseline)
 reference=data['source_reference'];rp,rn=validate_reference(reference,source_base())
 require(set(bp)<=set(rp),'accepted reference lost historical coverage')
 changes=reconciliation(reference,data['inventory']);require(changes==data['inventory_reconciliation'],'inventory reconciliation mismatch')
 validate_merge_guard(data['merge_guard'])
 require(runtime_inputs_match() and data['runtime_inputs']==read_json('docs/ci_v3/phase4/runtime/inputs.json'),'runtime source contract drift')
 runtime_packages(data['collection_environment'])
 seen={};skips=skip_counter(data['inventory']['collection_skips']);expected={n['nodeid'] for n in data['inventory']['nodes']}
 for index,folder in enumerate(workers):
  binding=read_json(folder/'binding.json');require(binding=={'context':context(),'worker':index,'plan_sha256':sha(planfolder/'plan.json'),'image':data['image']},'worker binding')
  proc=read_json(folder/'process.json');cleanup=proc.get('descendant_cleanup') or {}
  require(proc['normal_successful_exit'] and proc['container_removed'] and proc['source_bytes_unchanged'] and cleanup.get('cleanup_verified') is True and cleanup.get('survivors_observed')==cleanup.get('survivors_remaining')==[], 'worker process/cleanup')
  r=read_json(folder/'execution/child/adapter.json');require(r['context']==context() and r['worker']==f'worker-{index}' and r['pytest_exitstatus']==0 and not r['unauthorized_deselection'],'worker source/exit')
  require(r['collection']['complete'] and not r['collection']['errors'] and set(r['collection']['nodes'])==expected and skip_counter(r['collection']['skips'])==skips,'worker collection mismatch')
  owned={n for n in expected if data['plan']['module_workers'][n.split('::')[0]]==f'worker-{index}'}
  require(set(r['selected'])==owned and len(r['selected'])==len(owned) and Counter(r['deselected'])==Counter(expected-owned),'ownership loss/duplicate')
  require(r['environment']==data['collection_environment'] and semantic_plugin_profile(r['plugin_registrations'])==data['collection_plugins'],'worker environment/plugins drift')
  calibration=read_json(folder/'execution/child/calibration.json');require(calibration['context']==context() and calibration['meets_test_assumption'] and len(calibration['samples_s'])>=3 and max(calibration['samples_s'])<=.6,'target calibration failed')
  phases=phase_map(r);native=native_cases((folder/'execution/child/native.xml').read_bytes(),r)
  require(not set(seen)&set(phases),'duplicate execution')
  for n,v in phases.items():
   require(outcome(v)['status'] in ('passed','skipped','xfail'),'failure/unexpected xpass')
   if n in bp:require(v==bp[n] and native[n]==bn[n],'original phase/native outcome regression: '+n)
   else:require(outcome(v)['status']=='passed','nonhistorical nonpass requires explicit reviewed authority: '+n)
   if n in rp:require(v==rp[n] and list(native[n])==rn[n],'accepted-source phase/native outcome regression: '+n)
   else:require(outcome(v)['status']=='passed','new nonpass needs explicit treatment: '+n)
  seen.update(phases)
 require(set(seen)==expected,'incomplete full coverage')
 return {'source':data['context']['source'],'run_id':data['context']['run_id'],'attempt':data['context']['attempt'],'execution_mode':'parallel','workers':data['plan']['worker_count'],'original_nodes':len(seen),'baseline_original_nodes':len(bp),'new_nodes':len(expected-set(bp)),'collection_skips':sum(skips.values()),'all_phases_verified':True,'native_junit_verified':True,'cleanup_verified':True,'original_common_outcomes_equal':True,'baseline_source':baseline['source'],'baseline_is_current_source':False,'environment_equal_to_sequential_baseline':data['collection_environment']==baseline['environment'],'accepted_reference_source':reference['source'],'accepted_reference_base':reference['base'],'accepted_reference_run_id':reference['run_id'],'accepted_reference_attempt':reference['attempt'],'accepted_reference_digest':reference['digest'],'inventory_reconciliation':changes,'current_source_execution_verified':True,'same_source_sequential_control_claimed':False}

def authenticate_current(api,downloaded,out):
 ctx=context();run=api.get(f'/repos/{REPO}/actions/runs/{ctx["run_id"]}')
 require(run['head_sha']==ctx['source']['head'] and run['run_attempt']==ctx['attempt'] and run.get('path')=='.github/workflows/public_safety_and_smoke.yml' and run.get('head_repository',{}).get('full_name')==REPO,'service current repository/workflow/source/attempt')
 listing=api.listing(f'/repos/{REPO}/actions/runs/{ctx["run_id"]}/artifacts','artifacts')
 jobs=api.listing(f'/repos/{REPO}/actions/runs/{ctx["run_id"]}/attempts/{ctx["attempt"]}/jobs','jobs')
 count=production_plan(downloaded/'public-ci-v3-plan')['plan']['worker_count']
 expected={f'public-ci-v3-worker-{i}' for i in range(count)}
 require({a['name'] for a in listing if a['name'].startswith('public-ci-v3-worker-')}==expected,'unexpected/missing worker artifact identity')
 for name in ['public-ci-v3-plan',*sorted(expected)]:
  matches=[a for a in listing if a['name']==name and not a['expired']];require(len(matches)==1,'missing/duplicate service artifact')
  suffix='plan' if name=='public-ci-v3-plan' else name.removeprefix('public-ci-v3-')
  producers=[j for j in jobs if j['name'].endswith('/ '+suffix) or j['name']==suffix]
  require(len(producers)==1 and producers[0]['status']=='completed' and producers[0]['conclusion']=='success', 'artifact producer not successful')
  a=matches[0];payload=api.raw(f'/repos/{REPO}/actions/artifacts/{a["id"]}/zip',archive=True)
  require('sha256:'+hashlib.sha256(payload).hexdigest()==a['digest'],'service archive digest')
  extract_archive(payload,out/name);require(files(out/name)==files(downloaded/name),'downloaded evidence differs from independent service archive')
 data=production_plan(out/'public-ci-v3-plan')
 independently_verified=authenticate_reference(api,source_base(),out/'reference-authentication',anchor=data['source_reference'])
 require(independently_verified==data['source_reference'],'accepted-source reference differs from independent authentication')
 return out

def main():
 p=argparse.ArgumentParser();p.add_argument('stage',choices=['route','plan','worker','verify']);p.add_argument('--output',required=True);p.add_argument('--plan',default='evidence/public-ci-v3-plan');p.add_argument('--evidence',default='evidence');p.add_argument('--worker',type=int,choices=range(12));p.add_argument('--image');p.add_argument('--independent',action='store_true');a=p.parse_args();out=Path(a.output).resolve();out.mkdir(parents=True,exist_ok=False)
 if a.stage=='route':route_preflight(out)
 elif a.stage=='plan':make_plan(Path.cwd(),out,a.image)
 elif a.stage=='worker':worker(Path.cwd(),out,Path(a.plan).resolve(),a.worker)
 else:
  folder=Path(a.evidence).resolve()
  if a.independent:folder=authenticate_current(GitHub(),folder,out/'authenticated')
  result=verify_data(folder/'public-ci-v3-plan',[folder/f'public-ci-v3-worker-{i}' for i in range(production_plan(folder/'public-ci-v3-plan')['plan']['worker_count'])])
  write_json(out/'production-proof.json',result)
if __name__=='__main__':main()
