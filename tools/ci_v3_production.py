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
from tools.ci_v3_calibrate import STEADY_STATE_CONTRACT,evaluate

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


def validate_accepted_reference_successor(reference, historical, historical_native):
 # Preserve validate_reference_policy unchanged. Only its single, already
 # owner-authorized D-029 historic skip-to-pass may be admitted separately.
 # The caller must have independently authenticated BOTH source runs/JUnit.
 try:
  validate_reference_policy(reference,historical)
  return 'historical-phase-exact'
 except ContractError:
  original=phase_map(historical);accepted=phase_map(reference['report'])
  require(set(original)<=set(accepted),'accepted reference lost historical coverage')
  changed=sorted(n for n in original if original[n]!=accepted[n])
  require(changed==[D029_NODE],
          'accepted reference historical phase mismatches are not the single approved D-029 node: '+repr(changed[:30]))
  unexpected=sorted(n for n in accepted if n not in original and outcome(accepted[n])['status']!='passed')
  require(not unexpected,'accepted reference has nonhistorical nonpass: '+repr(unexpected[:30]))
  require(set(historical_native)==set(original) and set(reference['native'])==set(accepted),
          'D-029 successor missing authenticated original/native evidence')
  try:
   facts=d029_source_facts()
  except (OSError,ValueError,subprocess.CalledProcessError,ContractError) as exc:
   raise ContractError('D-029 successor exact current-source authentication failed: '+type(exc).__name__) from exc
  problems=d029_transition_problems(D029_NODE,original[D029_NODE],historical_native[D029_NODE],
      accepted[D029_NODE],reference['native'][D029_NODE],facts,accepted,reference['native'])
  require(not problems,'D-029 accepted-source successor proof rejected: '+repr(problems))
  return 'exact-D029-authorized-reference-successor'

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
   historic_native=native_cases((out/'historical/public-verification-results/results.xml').read_bytes(),historical)
   admission=validate_accepted_reference_successor(reference,historical,historic_native)
   write_json(out/'source-reference.json',reference);ready=True;reason='accepted-source reference authenticated; '+admission
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
 require_reference_runtime(reference)
 baseline_native=native_cases((out/'baseline/public-verification-results/results.xml').read_bytes(),baseline)
 validate_accepted_reference_successor(reference,baseline,baseline_native)
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
 # The accepted-base report is independently authenticated and contains actual
 # per-phase timing from its native execution. It supersedes older baseline
 # durations for modules present in that exact accepted tree. PR-only modules
 # remain conservative explicit node-count estimates, never fabricated times.
 current_ms=Counter();current_measured=set()
 for ph in reference['report']['phases']:
  ms=ph.get('duration_ms')
  if type(ms) is int and ms>=0:
   module=ph['nodeid'].split('::')[0]
   current_ms[module]+=ms
   current_measured.add(module)
 sources={m:('authenticated accepted-source phase milliseconds'
             if m in current_measured and current_ms[m]>0 else
             'authenticated historical native JUnit milliseconds'
             if times.get(m,0)>0 else 'unmeasured current module: node_count * 1000ms proxy') for m in inv['modules']}
 weights=seal({'schema':1,'kind':'ci-v3-weights','source':ctx['source'],
   'inventory_digest':inv['digest'],
   'modules_ms':{m:max(1,current_ms[m] if m in current_measured and current_ms[m]>0 else times.get(m,counts[m]*1000)) for m in inv['modules']},
   'measurement':'authenticated accepted-source phase durations when available; historical native JUnit fallback; explicit unmeasured module proxy'})
 write_json(out/'weights.json',weights)
 write_json(out/'timing-provenance.json',{'accepted_reference_run_id':reference['run_id'],
   'accepted_reference_digest':reference['digest'],'historical_run_id':BASE_RUN,
   'module_weight_sources':sources,'worker_count':routing()['worker_count']})
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
 request={'mode':'worker','worker':f'worker-{index}','context':context(),'inventory':plan['inventory'],'owned_modules':[m for m,w in plan['plan']['module_workers'].items() if w==f'worker-{index}'],'target_calibration':dict(STEADY_STATE_CONTRACT)}
 child,proc=observe_container(request,out/'execution',project,plan['image'],5400,built_image=True)
 write_json(out/'process.json',proc);write_json(out/'binding.json',{'context':context(),'worker':index,'plan_sha256':sha(planfolder/'plan.json'),'image':plan['image']})
 import shutil
 for name in ['source','bootstrap']:shutil.rmtree(out/'execution'/name)
 # Transient databases/build trees are not evidence. Keep all native XML,
 # lossless reports, process/cleanup/calibration receipts and original logs.
 shutil.rmtree(out/'execution/child/tmp')
 require(proc['normal_successful_exit'],'worker failure or cleanup failure')

# ── D-029 (PR #384): the ONE Financial-Owner-authorized historical outcome reconciliation ─────────────────────────────
# Policy, not suppression. The original test `test_scope_guard_...` is SKIPPED in the authenticated baseline and the
# accepted-source reference only because the Trust pack was not part of those diffs. D-029 legitimately changes the Trust
# registry (one reviewed data-store entry), so the original test now genuinely EXECUTES and PASSES through its reviewed
# exact-content successor. Every other historical node keeps hard phase/native equality. The exception holds only while
# ALL of these are proven from actual evidence and Git content, never from a branch name, PR number or environment value:
# exact node; baseline = setup passed / call skipped with the original reason / teardown passed; current = three passed
# phases and native JUnit passed; the current Trust files are the exact reviewed blobs derived from the pinned main; the
# Trust-scope diff against that main is exactly the reviewed set; the D-029 successor tests (positive and negative) passed
# in this same run; and the reconciliation record in the repository equals the constants below.
D029_NODE='tests/test_trust_readiness_registry.py::test_scope_guard_this_work_touches_no_engine_input_writer_or_radar_code'
D029_SKIP_REASON='trust pack not part of this diff'
D029_MAIN='36edeeb5d9a14749fdfafcd3b60a0d384cac73ba'
D029_MAIN_BLOBS={'app/trust_readiness/registry.py':'32a6bcb86516ff4d1ee8b1dc90191fdb57c5dc2d'}
D029_BLOBS={'app/trust_readiness/registry.py':'99ff83825e6bef013be9411235d2d77345f78b02',
 'docs/readiness/02_data_handling.md':'330db9c4ae6cd6c8349aad4a1d0c632010e6c1e4',
 'docs/readiness/06_retention_and_deletion.md':'a155b44b47ce3cbe22239e6a65635d666e0f3dac'}
D029_TRUST_PATHS=('app/trust_readiness','docs/readiness','tests/test_trust_readiness_*.py','tools/render_readiness_docs.py','app/templates/trust','static/trust_readiness.css')
D029_TRUST_CHANGED=frozenset({'app/trust_readiness/registry.py','docs/readiness/02_data_handling.md','docs/readiness/06_retention_and_deletion.md','tests/test_trust_readiness_registry.py',
 'tests/test_trust_readiness_controls.py'})
# RC-M (PR #388, Financial Owner's standing authorization, Correction B): the Trust-scope CSRF-inventory test gained ONE additive line that admits the two
# React adapters' CSRF-bound POST modules while their exact reviewed content holds (tests/rcm_adapter_csrf_successor.py).  The file is therefore part of
# the reviewed Trust-scope set, but only as this EXACT blob: any other edit of it still fails this gate until it is re-reviewed.
D029_TRUST_CHANGED_BLOBS={'tests/test_trust_readiness_controls.py':'cd5b3114d9a11ca4507667a099bb853573d056d3'}
_D='tests/test_trust_readiness_registry.py::'
D029_EVIDENCE_NODES=tuple(_D+n for n in (
 'test_generated_documents_are_up_to_date','test_csrf_registry_correction_is_only_the_two_approved_sentences',
 'test_demo_retention_exception_accepts_only_exact_approved_content','test_f4_csrf_correction_preserves_historical_content_and_authorities',
 'test_d029_trust_successor_exact_baseline_and_exact_new_content','test_d029_trust_entry_makes_only_accurate_retention_claims',
 'test_d029_trust_successor_does_not_weaken_historical_layers','test_d029_successor_refuses_a_second_application_or_a_missing_anchor',
 *('test_d029_trust_successor_rejects_arbitrary_registry_drift[%s-<lambda>]'%case for case in (
  'unrelated edit','historical entry removed','misleading retention claim','altered security statement','entry duplicated','entry moved','entry softened'))))
D029_RECORD='docs/model_v2/d029/evidence/D029_CI_V3_OUTCOME_RECONCILIATION.json'

# ── WS-2 Gate C (PR #397, Financial Owner Option 1): the SEPARATE, closed successor of the current Trust-source state ──────────
# D-029 above is the immutable historical reconciliation.  WS-2 adds ONE data store (`save_all_requests`) to the Trust inventory, so
# at HEAD the three Trust sources are one coherent, independently reviewed LATER state.  The transition is recognised against exactly
# one of two atomic states - never a per-file mix: STATE A = the original D-029 tuple, STATE B = the WS-2 tuple below together with the
# exact reviewed Trust test blobs, the exact receipt, the unchanged D-029 record, the WS-2 manifest pins and the extra same-run
# evidence nodes.  It is not a second outcome reconciliation: the only reconciled node and transition stay the D-029 ones.
WS2_RECEIPT='docs/react_migration/wsv2_editing/WS2_CI_V3_TRUST_SUCCESSOR.json'
WS2_MANIFEST='docs/react_migration/wsv2_editing/SOURCE_SUCCESSOR.json'
WS2_TRUST_BLOBS={'app/trust_readiness/registry.py':'c616833bdce263b60b4bccec217cad1fb4e8d7d8',
 'docs/readiness/02_data_handling.md':'7b8a8ca074757aee5f098c2e3299153b8f0e960b',
 'docs/readiness/06_retention_and_deletion.md':'4e46c27f1e74095554608bb084182af8960b14ee'}
WS2_TRUST_EXTRA_BLOBS={'tests/test_trust_readiness_registry.py':'69e0b15e0c4cfd36102d1442e577f7cc6d9b6516'}
WS2_RECORD_BLOB='3de6bae74c873570f20037912dcb32f74f19e41d'
# State B needs exactly the same 15 same-run D-029 evidence nodes as state A: they execute the registry chain against the WS-2 text. (The
# table-classification test also runs in CI but is not part of the aggregate's original-node evidence set, so it cannot be required here.)
WS2_EXTRA_NODES=()

def d029_expected_record():
 return {'authorization':'Financial Owner, PR #384 Correction C (relayed in the PR thread)','node':D029_NODE,
  'transition':{'from':'SKIPPED','reason':D029_SKIP_REASON,'to':'PASSED'},'scope':'single node; no other historical outcome may change',
  'main':D029_MAIN,'main_blobs':D029_MAIN_BLOBS,'current_blobs':{**D029_BLOBS,**D029_TRUST_CHANGED_BLOBS},
  'trust_scope_changed_paths':sorted(D029_TRUST_CHANGED),'required_passing_nodes':list(D029_EVIDENCE_NODES)}

def ws2_expected_receipt():
 return {'schema':'WS2_CI_V3_TRUST_SUCCESSOR_V1','authorization':'Financial Owner, PR #397 Correction M (WS-2 Gate C Option 1; relayed in the PR thread)',
  'scope':'current Trust-source state after the WS-2 save_all_requests classification; not a second historical outcome reconciliation',
  'predecessor_record':D029_RECORD,'predecessor_record_blob':WS2_RECORD_BLOB,'d029_main':D029_MAIN,
  'current_blobs':{**WS2_TRUST_BLOBS,**WS2_TRUST_EXTRA_BLOBS,**D029_TRUST_CHANGED_BLOBS},
  'trust_scope_changed_paths':sorted(D029_TRUST_CHANGED),'required_passing_nodes':list(D029_EVIDENCE_NODES+WS2_EXTRA_NODES)}

def d029_source_facts():
 facts={'record':read_json(D029_RECORD),'blobs':{p:git('rev-parse','HEAD:'+p) for p in {**D029_BLOBS,**D029_TRUST_CHANGED_BLOBS}}}
 facts['main_blobs']={p:git('rev-parse',D029_MAIN+':'+p) for p in D029_MAIN_BLOBS}
 # WS-2 successor facts, read from Git/HEAD exactly like the D-029 ones; an unreadable receipt is `None` and can never match.
 facts['ws2_extra_blobs']={p:git('rev-parse','HEAD:'+p) for p in WS2_TRUST_EXTRA_BLOBS}
 facts['record_blob']=git('rev-parse','HEAD:'+D029_RECORD)
 try:facts['ws2_receipt']=read_json(WS2_RECEIPT)
 except (OSError,ValueError,ContractError):facts['ws2_receipt']=None
 try:
  pins=read_json(WS2_MANIFEST)['source_blobs'];facts['ws2_manifest_pins']={p:pins.get(p) for p in {**WS2_TRUST_BLOBS,**WS2_TRUST_EXTRA_BLOBS}}
 except (OSError,ValueError,KeyError,TypeError,ContractError):facts['ws2_manifest_pins']=None
 git('merge-base','--is-ancestor',D029_MAIN,'HEAD')
 facts['changed']=frozenset(git('diff','--name-only',D029_MAIN,'HEAD','--',*D029_TRUST_PATHS).splitlines())
 return facts

def d029_transition_problems(node,old_phases,old_native,new_phases,new_native,facts,run_phases,run_native):
 """[] means the single authorized SKIPPED -> PASSED transition holds. Pure; fails closed on anything else."""
 if node!=D029_NODE:return ['not the authorized node']
 problems=[];shape=lambda ph:[(p['when'],p['outcome'],p['wasxfail']) for p in ph]
 try:
  if shape(old_phases)!=[('setup','passed',None),('call','skipped',None),('teardown','passed',None)] or D029_SKIP_REASON not in old_phases[1]['reason']:problems.append('baseline is not the original skip')
  if old_phases[0]!=new_phases[0] or old_phases[2]!=new_phases[2]:problems.append('setup/teardown phase changed')
  if tuple(old_native)[0]!='skipped' or D029_SKIP_REASON not in str(tuple(old_native)[1]):problems.append('baseline native JUnit is not the original skip')
  if shape(new_phases)!=[('setup','passed',None),('call','passed',None),('teardown','passed',None)] or outcome(new_phases)['status']!='passed':problems.append('current execution is not three passed phases')
  if tuple(new_native)[0]!='passed':problems.append('current native JUnit does not confirm PASSED')
  if facts['record']!=d029_expected_record():problems.append('reconciliation record differs from the reviewed constants')
  # ONE coherent state: STATE A (original D-029 tuple) or STATE B (the WS-2 tuple with its receipt, manifest pins and extra evidence).  Never a mix.
  state_a=facts['blobs']=={**D029_BLOBS,**D029_TRUST_CHANGED_BLOBS}
  state_b=(not state_a and facts['blobs']=={**WS2_TRUST_BLOBS,**D029_TRUST_CHANGED_BLOBS}
           and facts.get('ws2_extra_blobs')==WS2_TRUST_EXTRA_BLOBS and facts.get('record_blob')==WS2_RECORD_BLOB
           and facts.get('ws2_receipt')==ws2_expected_receipt() and facts.get('ws2_manifest_pins')=={**WS2_TRUST_BLOBS,**WS2_TRUST_EXTRA_BLOBS})
  if not (state_a or state_b):problems.append('Trust sources are not the exact reviewed blobs')
  if facts['main_blobs']!=D029_MAIN_BLOBS:problems.append('Trust baseline is not the pinned main')
  if facts['changed']!=D029_TRUST_CHANGED:problems.append('Trust-scope diff differs from the reviewed set')
  for ev in D029_EVIDENCE_NODES+(WS2_EXTRA_NODES if state_b else ()):
   if ev not in run_phases or outcome(run_phases[ev])['status']!='passed' or tuple(run_native.get(ev,('missing',)))[0]!='passed':problems.append('required successor test did not pass: '+ev)
 except (KeyError,IndexError,TypeError,ValueError,ContractError) as e:problems.append('malformed evidence: '+type(e).__name__)
 return problems

def d029_authorized(node,old_phases,old_native,new_phases,new_native,run_phases,run_native,receipts):
 if node!=D029_NODE:return False
 try:facts=d029_source_facts()
 except (OSError,ValueError,subprocess.CalledProcessError,ContractError):return False
 if d029_transition_problems(node,old_phases,old_native,new_phases,new_native,facts,run_phases,run_native):return False
 receipts.append({'node':node,'from':'SKIPPED','to':'PASSED'});return True

def verify_data(planfolder,workers):
 data=production_plan(planfolder)
 require(len(workers)==data['plan']['worker_count'],'missing/extra worker artifacts')
 validate_inventory(data['inventory']);check_seal(data['plan'],'ci-v3-plan')
 require(data['inventory']['source']==data['plan']['source']==context()['source'] and data['plan']['inventory_digest']==data['inventory']['digest'], 'plan inventory/source drift')
 baseline=control_report(read_json(planfolder/'baseline/public-verification-results/inventory.json'));bp=phase_map(baseline);bn=native_cases((planfolder/'baseline/public-verification-results/results.xml').read_bytes(),baseline)
 reference=data['source_reference'];rp,rn=validate_reference(reference,source_base())
 require(set(bp)<=set(rp),'accepted reference lost historical coverage')
 require_reference_runtime(reference)
 validate_accepted_reference_successor(reference,baseline,bn)
 changes=reconciliation(reference,data['inventory']);require(changes==data['inventory_reconciliation'],'inventory reconciliation mismatch')
 validate_merge_guard(data['merge_guard'])
 require(runtime_inputs_match() and data['runtime_inputs']==read_json('docs/ci_v3/phase4/runtime/inputs.json'),'runtime source contract drift')
 runtime_packages(data['collection_environment'])
 reconciled=[]
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
  calibration=read_json(folder/'execution/child/calibration.json');require(calibration['context']==context() and calibration.get('contract')==STEADY_STATE_CONTRACT and calibration['meets_test_assumption'] is True and evaluate(calibration['samples_s'],STEADY_STATE_CONTRACT)['meets_test_assumption'] is True,'target calibration failed')
  phases=phase_map(r);native=native_cases((folder/'execution/child/native.xml').read_bytes(),r)
  require(not set(seen)&set(phases),'duplicate execution')
  for n,v in phases.items():
   require(outcome(v)['status'] in ('passed','skipped','xfail'),'failure/unexpected xpass')
   if n in bp:require((v==bp[n] and native[n]==bn[n]) or d029_authorized(n,bp[n],bn[n],v,native[n],phases,native,reconciled),'original phase/native outcome regression: '+n)
   else:require(outcome(v)['status']=='passed','nonhistorical nonpass requires explicit reviewed authority: '+n)
   if n in rp:require((v==rp[n] and list(native[n])==rn[n]) or d029_authorized(n,rp[n],rn[n],v,native[n],phases,native,reconciled),'accepted-source phase/native outcome regression: '+n)
   else:require(outcome(v)['status']=='passed','new nonpass needs explicit treatment: '+n)
  seen.update(phases)
 require(set(seen)==expected,'incomplete full coverage')
 return {'source':data['context']['source'],'run_id':data['context']['run_id'],'attempt':data['context']['attempt'],'execution_mode':'parallel','workers':data['plan']['worker_count'],'original_nodes':len(seen),'baseline_original_nodes':len(bp),'new_nodes':len(expected-set(bp)),'collection_skips':sum(skips.values()),'all_phases_verified':True,'native_junit_verified':True,'cleanup_verified':True,'original_common_outcomes_equal':not reconciled,'authorized_outcome_reconciliations':reconciled,'baseline_source':baseline['source'],'baseline_is_current_source':False,'environment_equal_to_sequential_baseline':data['collection_environment']==baseline['environment'],'accepted_reference_source':reference['source'],'accepted_reference_base':reference['base'],'accepted_reference_run_id':reference['run_id'],'accepted_reference_attempt':reference['attempt'],'accepted_reference_digest':reference['digest'],'inventory_reconciliation':changes,'current_source_execution_verified':True,'same_source_sequential_control_claimed':False}

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
