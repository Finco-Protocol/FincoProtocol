"""Production routing and adversarial coverage checks; service fixtures are SYNTHETIC."""
from copy import deepcopy
import json,os,shutil,subprocess
from pathlib import Path
import pytest,yaml
from tools import ci_v3_production as prod
from tools.ci_v3_calibrate import STEADY_STATE_CONTRACT
from tools.ci_v3_schema import ContractError,read_json,write_json
from tools.ci_v3_pytest_config import semantic_plugin_profile
ROOT=Path(__file__).resolve().parents[1]

def flow():return yaml.load((ROOT/'.github/workflows/ci_v3_required_job.yml').read_text(),Loader=yaml.BaseLoader)

def _route_script():return flow()['jobs']['route']['steps'][-1]['run']

@pytest.fixture(scope='module')
def route_trees(tmp_path_factory):
 """Real Git source differences are inputs, never restored to a historic application tree."""
 head=subprocess.check_output(['git','rev-parse','HEAD'],cwd=ROOT,text=True).strip()
 env={**os.environ,'GIT_AUTHOR_NAME':'SYNTHETIC','GIT_AUTHOR_EMAIL':'noreply@users.noreply.github.com','GIT_COMMITTER_NAME':'SYNTHETIC','GIT_COMMITTER_EMAIL':'noreply@users.noreply.github.com'}
 trees={}
 for kind in ('compatible','incompatible'):
  d=tmp_path_factory.mktemp('SYNTHETIC-route-'+kind)/'repo'
  subprocess.run(['git','clone','-q','--shared',str(ROOT),str(d)],check=True)
  if kind=='incompatible':
   f=d/'app/__init__.py';f.write_text(f.read_text()+'\n# SYNTHETIC application-source change\n')
   subprocess.run(['git','-C',str(d),'add','app/__init__.py'],check=True)
   subprocess.run(['git','-C',str(d),'commit','-q','-m','SYNTHETIC source-changing route'],env=env,check=True)
   assert subprocess.check_output(['git','-C',str(d),'diff','--name-only',head,'HEAD'],text=True).strip()=='app/__init__.py'
  trees[kind]=d
 return trees

def _route(cwd,tmp_path,rollback,event,repo):
 # Exercise the exact production routing predicate after independently verified
 # source/runtime admission; source differences never form a second hidden gate.
 config=prod.routing()
 mode=prod.route_mode(config,event!='pull_request' or repo==prod.REPO,rollback,True,True)
 assert 'git' not in _route_script() and 'tools.ci_v3_production route' in _route_script()
 return 'execution_mode='+mode+'\n'

@pytest.mark.parametrize('rollback,event,repo,mode',[('', 'push','Finco-Protocol/FincoProtocol','parallel'),('true','push','Finco-Protocol/FincoProtocol','sequential'),('','pull_request','elsewhere/fork','sequential'),('','pull_request','Finco-Protocol/FincoProtocol','parallel'),('', 'push','Finco-Protocol/FincoProtocol','admitted'),('','pull_request','Finco-Protocol/FincoProtocol','admitted')])
def test_real_route_and_immediate_rollback(tmp_path,route_trees,rollback,event,repo,mode):
 # Retain Epic's original [admitted] parameter identities alongside main's
 # [parallel] identities; both use the same authenticated source-aware route.
 expected='parallel' if mode=='admitted' else mode
 assert _route(route_trees['compatible'],tmp_path,rollback,event,repo)=='execution_mode='+expected+'\n'

@pytest.mark.parametrize('rollback,event,repo',[('', 'push','Finco-Protocol/FincoProtocol'),('true','push','Finco-Protocol/FincoProtocol'),('','pull_request','elsewhere/fork'),('','pull_request','Finco-Protocol/FincoProtocol')])
def test_incompatible_source_is_always_routed_sequentially(tmp_path,route_trees,rollback,event,repo):
 # Preserve original node identities while correcting the obsolete expectation:
 # an app/ difference is compatible once the source-aware proof is available.
 expected='sequential' if rollback=='true' or repo!=prod.REPO else 'parallel'
 assert _route(route_trees['incompatible'],tmp_path,rollback,event,repo)=='execution_mode='+expected+'\n'

def test_active_profile_retains_all_bounds_and_no_credential_or_failure_bypass():
 f=flow();jobs=f['jobs'];assert set(jobs)=={'route','sequential','plan','worker','aggregate','tests'}
 assert sum(int(j['timeout-minutes']) for n,j in jobs.items() if n!='sequential')==310
 assert jobs['sequential']['uses']=='./.github/workflows/ci_public_job.yml'
 assert jobs['worker']['needs']==['route','plan']
 assert jobs['worker']['strategy']['fail-fast']=='false'
 assert jobs['worker']['strategy']['matrix']=='${{ fromJSON(needs.plan.outputs.worker_matrix) }}'
 assert jobs['aggregate']['needs']==['route','plan','worker']
 assert jobs['tests']['if']=='${{ always() }}' and jobs['tests']['name']=='tests'
 assert 'continue-on-error' not in (ROOT/'.github/workflows/ci_v3_required_job.yml').read_text()
 for n,j in jobs.items():
  for s in j.get('steps',[]):
   assert not {'secrets','packages'}.intersection(s.get('env',{}))
  assert not j.get('permissions',{}).get('packages')
 script=jobs['tests']['steps'][0]['run']
 for result in ['failure','cancelled','skipped']:
  p=subprocess.run(['bash','-e','-c',script],env={**os.environ,'ROUTE_RESULT':'success','MODE':'parallel','PARALLEL_RESULT':result,'SEQUENTIAL_RESULT':'success'})
  assert p.returncode!=0

@pytest.fixture(scope='module')
def real_tiny(tmp_path_factory):
 from tests.ci_v3_pair_fixtures import pair_bundle
 directory=tmp_path_factory.mktemp('SYNTHETIC-production-real-phases')
 data=pair_bundle(directory);data['directory']=directory
 return data

@pytest.fixture
def evidence(real_tiny,tmp_path,monkeypatch):
 monkeypatch.setattr(prod,'routing',lambda:{'worker_count':3})
 d=real_tiny;plan=tmp_path/'public-ci-v3-plan';plan.mkdir()
 shutil.copytree(d['directory']/'baseline/public-verification-results',plan/'baseline/public-verification-results')
 first=read_json(d['paths']['worker-0']/'child/adapter.json');ctx=first['context'];monkeypatch.setattr(prod,'context',lambda:ctx)
 from tools.ci_v3_isolation import constrained_plan
 allocation=constrained_plan(d['project'],d['bundle']['inventory'],d['bundle']['policy'],d['bundle']['weights'],d['bundle']['isolation'])
 image='sha256:'+'a'*64
 from tools import ci_v3_source_reference as ref
 from tools.ci_v3_phase_compare import control_report,native_cases
 from tools.ci_v3_schema import seal
 baseline=control_report(read_json(plan/'baseline/public-verification-results/inventory.json'))
 snapshot=seal({'schema':1,'kind':'ci-v3-source-reference','base':ctx['source'],'source':ctx['source'],'run_id':122,'attempt':1,'artifacts':[],'report':baseline,'native':{n:list(v) for n,v in native_cases((plan/'baseline/public-verification-results/results.xml').read_bytes(),baseline).items()}})
 monkeypatch.setattr(prod,'source_base',lambda:ctx['source'])
 monkeypatch.setattr(ref,'git',lambda *args:subprocess.check_output(['git','-C',str(d['project']),*args],text=True).strip())
 monkeypatch.setattr(prod,'runtime_packages',lambda environment:None)
 monkeypatch.setenv('FINCO_PRODUCTION_MERGE_SHA','')
 # Synthetic source heads are not Git commits: serve the authenticated runtime
 # inputs for exactly that synthetic head only; any other revision still fails closed.
 runtime_path='docs/ci_v3/phase4/runtime/inputs.json'
 def synthetic_runtime_blob(head,path):
  if head==ctx['source']['head'] and path==runtime_path:return (ROOT/runtime_path).read_bytes()
  raise subprocess.CalledProcessError(128,['git','show',head+':'+path])
 monkeypatch.setattr(prod,'reference_runtime_blob',synthetic_runtime_blob)
 write_json(plan/'plan.json',{'context':ctx,'inventory':d['bundle']['inventory'],'plan':allocation,'image':image,'collection_environment':first['environment'],'collection_plugins':semantic_plugin_profile(first['plugin_registrations']),'source_reference':snapshot,'inventory_reconciliation':ref.reconciliation(snapshot,d['bundle']['inventory']),'merge_guard':{'head':ctx['source']['head'],'tree':ctx['source']['tree'],'merge_sha':None,'merge_tree':None,'mode':'main-head','equivalent':True},'runtime_inputs':read_json(ROOT/'docs/ci_v3/phase4/runtime/inputs.json')})
 workers=[]
 for i in range(3):
  folder=tmp_path/f'worker-{i}';folder.mkdir();shutil.copytree(d['paths'][f'worker-{i}']/'child',folder/'execution/child')
  write_json(folder/'binding.json',{'context':ctx,'worker':i,'plan_sha256':prod.sha(plan/'plan.json'),'image':image})
  # Synthetic process receipt ONLY; actual subreaper/container tests are separate.
  write_json(folder/'process.json',{'normal_successful_exit':True,'container_removed':True,'source_bytes_unchanged':True,'descendant_cleanup':{'cleanup_verified':True,'survivors_observed':[],'survivors_remaining':[]}})
  write_json(folder/'execution/child/calibration.json',{'context':ctx,'contract':dict(STEADY_STATE_CONTRACT),'meets_test_assumption':True,'samples_s':[.1,.2,.3]})
  workers.append(folder)
 return plan,workers

def test_cache_cold_first_sample_with_healthy_steady_state_is_accepted(evidence):
 plan,workers=evidence
 for folder,samples in zip(workers,([.610031006,.217968788,.222495816],[.801908379,.255256116,.251828227],[.704152905,.243172698,.242377088])):
  q=read_json(folder/'execution/child/calibration.json');q['samples_s']=samples;write_json(folder/'execution/child/calibration.json',q)
 assert prod.verify_data(plan,workers)['workers']==3


def test_complete_real_original_nodes_phases_native_outcomes(evidence):
 result=prod.verify_data(*evidence)
 assert result['original_nodes']==6 and result['workers']==3 and result['cleanup_verified']
 assert result['baseline_is_current_source'] is False

@pytest.mark.parametrize('attack',['missing-phase','phase-reason','native-byte','source','environment','ownership','cleanup','calibration','calibration-cold-gross','calibration-contract-swapped','calibration-verdict-forged','calibration-missing-contract','plan-pin'])
def test_partial_or_changed_execution_never_turns_green(evidence,attack):
 plan,workers=evidence;folder=workers[0];p=folder/'execution/child/adapter.json';r=read_json(p)
 if attack=='missing-phase':r['phases'].pop()
 elif attack=='phase-reason':r['phases'][0]['reason']='changed'
 elif attack=='native-byte':(folder/'execution/child/native.xml').write_text('<invalid/>')
 elif attack=='source':r['context']={**r['context'],'source':{'head':'f'*40,'tree':'e'*40}}
 elif attack=='environment':r['environment']={}
 elif attack=='ownership':r['selected']=[]
 elif attack=='cleanup':
  q=read_json(folder/'process.json');q['descendant_cleanup']['survivors_observed']=[{'pid':9}];write_json(folder/'process.json',q)
 elif attack=='calibration':
  q=read_json(folder/'execution/child/calibration.json');q['samples_s']=[.1,.2,.7];write_json(folder/'execution/child/calibration.json',q)
 elif attack=='calibration-cold-gross':        # a first start beyond the explicit cold-start ceiling is still refused
  q=read_json(folder/'execution/child/calibration.json');q['samples_s']=[1.9,.2,.2];write_json(folder/'execution/child/calibration.json',q)
 elif attack=='calibration-contract-swapped':  # a receipt produced under a looser, unapproved contract is refused
  q=read_json(folder/'execution/child/calibration.json');q['contract']={**STEADY_STATE_CONTRACT,'ceiling_s':.9};q['samples_s']=[.1,.8,.8];write_json(folder/'execution/child/calibration.json',q)
 elif attack=='calibration-verdict-forged':    # the recorded verdict is never trusted over the raw samples
  q=read_json(folder/'execution/child/calibration.json');q['samples_s']=[.2,.9,.9];q['meets_test_assumption']=True;write_json(folder/'execution/child/calibration.json',q)
 elif attack=='calibration-missing-contract':
  q=read_json(folder/'execution/child/calibration.json');q.pop('contract');write_json(folder/'execution/child/calibration.json',q)
 else:
  q=read_json(folder/'binding.json');q['plan_sha256']='f'*64;write_json(folder/'binding.json',q)
 write_json(p,r)
 with pytest.raises((ContractError,ValueError)):
  prod.verify_data(plan,workers)


def test_spawn_infrastructure_is_joined_before_independent_orphan_check(tmp_path):
 script=tmp_path/'spawn_check.py'
 script.write_text('''import multiprocessing,time,json
from tools.ci_v3_built_image_child import finalize_multiprocessing
if __name__=='__main__':
 p=multiprocessing.get_context('spawn').Process(target=time.sleep,args=(.01,))
 p.start();p.join(5)
 assert p.exitcode==0
 result=finalize_multiprocessing()
 assert result['tracker_pid_before'] is not None
 assert result['verified'] and result['tracker_pid_after'] is None
 print(json.dumps(result))
''')
 subprocess.run([__import__('sys').executable,str(script)],check=True,env={**os.environ,'PYTHONPATH':str(ROOT)},capture_output=True,text=True,timeout=20)


def test_browser_exception_after_passes_cannot_produce_success(tmp_path):
 import sys
 script='''from pathlib import Path
from tests.model_statements_tree_acceptance import browser_failure_guard,write_browser_summary
import sys
out=Path(sys.argv[1]);results=[{'check':'earlier check','status':'PASS'}]
try:
 with browser_failure_guard(out,results,{'name':'keyboard OPEX'},[]):
  raise TimeoutError('synthetic navigation timeout')
finally:
 write_browser_summary(out,results,{})
'''
 run=subprocess.run([sys.executable,'-c',script,str(tmp_path)],cwd=ROOT,capture_output=True,text=True)
 assert run.returncode!=0 and 'TimeoutError' in run.stderr
 summary=read_json(tmp_path/'browser-results.json')
 assert summary['all_pass'] is False and summary['passed']==1 and summary['total']==2
 fail=summary['checks'][-1]
 assert fail['status']=='FAIL' and fail['exception_type']=='TimeoutError' and fail['step']=='keyboard OPEX'


def test_browser_diagnostic_failure_preserves_original_exception(tmp_path):
 from tests.model_statements_tree_acceptance import browser_failure_guard
 class ClosedDuringFailure:
  def is_closed(self):return False
  def evaluate(self,*args):raise RuntimeError('page lost')
  def screenshot(self,**kwargs):raise RuntimeError('screenshot lost')
 results=[]
 with pytest.raises(AssertionError,match='wrong keyboard focus'):
  with browser_failure_guard(tmp_path,results,{'name':'Tab'},[ClosedDuringFailure()]):
   raise AssertionError('wrong keyboard focus')
 assert results[-1]['status']=='FAIL' and results[-1]['exception_type']=='AssertionError'
 assert results[-1]['diagnostic_error']=='page lost' and results[-1]['screenshot_error']=='screenshot lost'


def test_owned_descriptor_sharer_is_joined_without_name_permission(tmp_path):
 import sys
 script=tmp_path/'descriptor_sharer.py'
 script.write_text('''from multiprocessing.reduction import DupFd
from tools.ci_v3_built_image_child import finalize_multiprocessing
import os,json
r,w=os.pipe()
x=DupFd(r);fd=x.detach()
for f in [r,w,fd]:os.close(f)
result=finalize_multiprocessing()
assert result['resource_sharer_owned_thread_before'] is True
assert result['resource_sharer_owned_thread_after'] is False and result['verified']
print(json.dumps(result))
''')
 subprocess.run([sys.executable,str(script)],check=True,env={**os.environ,'PYTHONPATH':str(ROOT)},capture_output=True,text=True,timeout=20)


def test_unowned_serve_named_thread_still_blocks_cleanup():
 import threading
 from tools.ci_v3_built_image_child import finalize_multiprocessing
 release=threading.Event()
 thread=threading.Thread(target=release.wait,name='Thread-1 (_serve)',daemon=True)
 thread.start()
 try:
  result=finalize_multiprocessing()
  assert result['verified'] is False and result['reason']=='application work remains'
  assert thread.name in result['threads']
 finally:
  release.set();thread.join(2)


def test_fixture_owned_acquisition_pool_is_closed_and_joined():
 from app.radar_runtime.service import AcquisitionService
 from app.radar_runtime.snapshot_store import SnapshotStore
 from tests.conftest import _close_owned_acquisition_services
 service=AcquisitionService(SnapshotStore(':memory:'))
 pool=service._provider_pool
 assert pool.submit(lambda: 1).result(timeout=2)==1
 _close_owned_acquisition_services([(service,pool)])
 assert service._closed and not any(t.is_alive() for t in pool._threads)


def scale_plan(tmp_path,monkeypatch,count):
 from tools.ci_v3_schema import seal
 from tools.ci_v3_partition_plan import plan_partitions
 # Synthetic collection, not FINCO runtime or owner evidence.
 nodes=[f'tests/test_scale_{i:02}.py::test_original' for i in range(24)]
 ctx={'source':{'head':'a'*40,'tree':'b'*40},'repository':prod.REPO,'run_id':'123','attempt':1}
 inv=prod.inventory({'collection':{'source':ctx['source'],'nodes':nodes,'skips':[]}})
 policy=seal({'schema':1,'kind':'ci-v3-policy','authority':'offline-prototype','inventory_digest':inv['digest'],'new_nodes':'fail-closed','selective_execution':False,'module_overlaps':{},'allowed_nonpass':{}})
 weights=seal({'schema':1,'kind':'ci-v3-weights','source':ctx['source'],'inventory_digest':inv['digest'],'modules_ms':{m:1000+i for i,m in enumerate(inv['modules'])}})
 group=list(inv['modules'])[:2]
 allocation=plan_partitions(inv,policy,weights,count,groups={'shared':group})
 assert allocation==plan_partitions(inv,policy,weights,count,groups={'shared':group})
 assert allocation['module_workers'][group[0]]==allocation['module_workers'][group[1]]
 write_json(tmp_path/'plan.json',{'context':ctx,'inventory':inv,'plan':allocation,'source_reference':{}})
 monkeypatch.setattr(prod,'context',lambda:ctx)
 monkeypatch.setattr(prod,'routing',lambda:{'worker_count':count})
 return ctx


@pytest.mark.parametrize('count', range(2,13))
def test_configurable_matrix_preserves_grouped_whole_module_ownership(tmp_path,monkeypatch,count):
 scale_plan(tmp_path,monkeypatch,count)
 matrix=prod.worker_matrix(tmp_path)['include']
 assert [v['index'] for v in matrix]==list(range(count))
 assert sum(v['nodes'] for v in matrix)==24 and all(v['nodes']>0 for v in matrix)
 # A source/config mismatch must reject instead of resizing the plan.
 monkeypatch.setattr(prod,'routing',lambda:{'worker_count':2 if count!=2 else 3})
 with pytest.raises(ContractError,match='worker count drift'):prod.worker_matrix(tmp_path)


@pytest.mark.parametrize('value',[None,True,False,1,13,2.0,'5'])
def test_invalid_production_worker_configuration_rejected(tmp_path,monkeypatch,value):
 p=tmp_path/'routing.json';write_json(p,{'worker_count':value})
 monkeypatch.setattr(prod,'ROUTING',p)
 with pytest.raises(ContractError,match='worker count'):prod.routing()


@pytest.mark.parametrize('attack',['missing','extra','duplicate','out-of-order','count','foreign-owner'])
def test_dynamic_aggregate_rejects_worker_identity_and_count_attacks(evidence,attack):
 from tools.ci_v3_schema import seal
 plan,workers=evidence
 if attack=='missing':workers=workers[:-1]
 elif attack=='extra':workers=workers+[workers[0]]
 elif attack=='duplicate':workers=[workers[0],workers[0],workers[2]]
 elif attack=='out-of-order':workers=list(reversed(workers))
 else:
  data=read_json(plan/'plan.json');allocation={k:v for k,v in data['plan'].items() if k!='digest'}
  if attack=='count':allocation['worker_count']=5
  else:allocation['module_workers'][next(iter(allocation['module_workers']))]='worker-11'
  data['plan']=seal(allocation);write_json(plan/'plan.json',data)
 with pytest.raises(ContractError):prod.verify_data(plan,workers)


def test_matrix_failure_does_not_trigger_sequential_retry():
 jobs=flow()['jobs']
 assert jobs['worker']['strategy']['fail-fast']=='false'
 script=jobs['aggregate']['steps'][0]['run']
 for state in ['failure','cancelled','skipped']:
  run=subprocess.run(['bash','-e','-c',script],env={**os.environ,'PLAN':'success','WORKERS':state})
  assert run.returncode!=0
 assert jobs['sequential']['if']=="${{ needs.route.outputs.execution_mode == 'sequential' }}"
 assert sum('docker build' in step.get('run','') for job in jobs.values() for step in job.get('steps',[]))==1


@pytest.mark.parametrize('count',[5,8,12])
@pytest.mark.parametrize('attack',[None,'missing','extra','duplicate','failed-producer','archive-bytes'])
def test_independent_service_authentication_requires_exact_dynamic_workers(tmp_path,monkeypatch,count,attack):
 # Same identities and attacks as before; the service names are now the current attempt's (PR #400 incident).
 download=tmp_path/'download';ctx,run=attempt_service(tmp_path,monkeypatch,count)
 names=run.current_names
 if attack=='missing':run.artifacts.pop()
 elif attack=='extra':run.artifacts.append({**run.artifacts[-1],'name':prod.attempt_name(f'public-ci-v3-worker-{count}',ctx['attempt'])})
 elif attack=='duplicate':run.artifacts.append(dict(run.artifacts[-1]))
 elif attack=='failed-producer':run.jobs[-1]['conclusion']='failure'
 elif attack=='archive-bytes':run.archives[run.artifacts[-1]['id']]=b'corrupted'
 if attack:
  with pytest.raises(ContractError):prod.authenticate_current(run,download,tmp_path/'authenticated')
 else:
  result=prod.authenticate_current(run,download,tmp_path/'authenticated')
  assert {p.name for p in result.iterdir()}=={'public-ci-v3-plan',*[f'public-ci-v3-worker-{i}' for i in range(count)],'current-attempt-artifacts.json'}
  assert len(names)==count+2


# ── Run-attempt artifact identity: replay of PR #400 run 41099667692 (SYNTHETIC service, real ZIP round trips) ───────
RUNTIME_BYTES=b'SYNTHETIC runtime-image.tar.gz bytes'

def _zip(folder):
 import io,zipfile
 buffer=io.BytesIO()
 with zipfile.ZipFile(buffer,'w') as archive:
  for file in sorted(folder.rglob('*')):
   if file.is_file():archive.writestr(str(file.relative_to(folder)),file.read_bytes())
 return buffer.getvalue()

def sealed(plan,runtime_bytes=RUNTIME_BYTES,image='sha256:'+'a'*64):
 """Complete the plan exactly as the plan job does: record the runtime archive, then seal it to this attempt."""
 import hashlib
 data=read_json(plan/'plan.json');data.setdefault('image',image);data['image_archive_sha256']=hashlib.sha256(runtime_bytes).hexdigest()
 write_json(plan/'plan.json',data);runtime=plan.parent/(plan.name+'.runtime-image.tar.gz');runtime.write_bytes(runtime_bytes)
 return prod.seal_attempt(plan,runtime),runtime

class AttemptRun:
 """SYNTHETIC GitHub run: artifact listing spans every attempt (as the service does); jobs are per attempt."""
 def __init__(self,ctx):self.ctx=ctx;self.artifacts=[];self.jobs=[];self.archives={};self.current_names=[];self.next_id=5000
 def add(self,name,data,attempt,head=None,ident=None):
  import hashlib
  ident=ident or self.next_id;self.next_id+=1
  self.artifacts.append({'id':ident,'name':name,'expired':False,'digest':'sha256:'+hashlib.sha256(data).hexdigest(),
   'workflow_run':{'id':int(self.ctx['run_id']),'head_sha':head or self.ctx['source']['head']},'attempt(not-in-api)':attempt})
  self.archives[ident]=data;return ident
 def get(self,path):return {'head_sha':self.ctx['source']['head'],'run_attempt':self.ctx['attempt'],'path':'.github/workflows/public_safety_and_smoke.yml','head_repository':{'full_name':prod.REPO}}
 def listing(self,path,key):
  if key=='artifacts':return [{k:v for k,v in a.items() if k!='attempt(not-in-api)'} for a in self.artifacts]
  assert path.endswith(f'/attempts/{self.ctx["attempt"]}/jobs');return self.jobs
 def raw(self,path,archive):return self.archives[int(path.split('/')[-2])]

def attempt_service(tmp_path,monkeypatch,count,attempt=1,plan_source=None,workers=None):
 """Current attempt's plan/runtime/worker artifacts, downloaded exactly as the consumers download them."""
 download=tmp_path/'download';download.mkdir(exist_ok=True)
 if plan_source is None:
  plan_source=tmp_path/'plan-source';plan_source.mkdir();ctx=scale_plan(plan_source,monkeypatch,count)
  ctx['attempt']=attempt;data=read_json(plan_source/'plan.json');data['context']=ctx;write_json(plan_source/'plan.json',data)
  monkeypatch.setattr(prod,'source_base',lambda:ctx['source'])
  monkeypatch.setattr(prod,'authenticate_reference',lambda *args,**kwargs:{})
 ctx=prod.context();sealed(plan_source)
 run=AttemptRun(ctx)
 plan_name=prod.attempt_name(prod.PLAN,ctx['attempt']);shutil.copytree(plan_source,download/plan_name)
 run.add(plan_name,_zip(plan_source),ctx['attempt']);run.add(prod.attempt_name(prod.RUNTIME,ctx['attempt']),b'SYNTHETIC zip of runtime',ctx['attempt'])
 run.jobs.append({'id':1,'name':'safety-and-smoke / plan','status':'completed','conclusion':'success'})
 for i in range(count):
  name=prod.attempt_name(f'public-ci-v3-worker-{i}',ctx['attempt']);folder=download/name
  if workers:shutil.copytree(workers[i],folder)
  else:folder.mkdir();(folder/'receipt.txt').write_text(name)
  run.add(name,_zip(folder),ctx['attempt'])
  run.jobs.append({'id':10+i,'name':f'safety-and-smoke / worker-{i}','status':'completed','conclusion':'success'})
 run.current_names=[plan_name,prod.attempt_name(prod.RUNTIME,ctx['attempt']),*[prod.attempt_name(f'public-ci-v3-worker-{i}',ctx['attempt']) for i in range(count)]]
 return ctx,run

def toolkit_by_name(listing,name):
 # actions/download-artifact (pinned d3f86a10 / @actions/artifact getArtifact): newest = highest numeric ID for that name.
 return max((a for a in listing if a['name']==name),key=lambda a:a['id'])

def stale_attempt_1_baseline_only(tmp_path):
 folder=tmp_path/'attempt-1-plan';(folder/'baseline/public-verification-results').mkdir(parents=True)
 (folder/'baseline/public-verification-results/inventory.json').write_text('{}')
 return folder

def no_docker(monkeypatch):
 def refused(*args,**kwargs):raise AssertionError('Docker/pytest reached before the attempt binding was proven: '+repr(args))
 monkeypatch.setattr(prod.subprocess,'run',refused);monkeypatch.setattr(prod.subprocess,'check_output',refused)
 monkeypatch.setattr(prod,'observe_container',refused)

def test_case_a_incident_replay_stale_attempt_1_plan_never_wins(tmp_path,monkeypatch):
 """Run 41099667692: attempt 1's baseline-only plan got the HIGHER ID (12999360429 > 12998263477) under the same name."""
 ctx,run=attempt_service(tmp_path,monkeypatch,8,attempt=2)
 stale=stale_attempt_1_baseline_only(tmp_path)
 # Attempt 1 artifacts, with higher numeric IDs exactly as observed; both the legacy and an attempt-1 scoped name.
 for name in ['public-ci-v3-plan',prod.attempt_name(prod.PLAN,1)]:run.add(name,_zip(stale),1,ident=12999360429 if name=='public-ci-v3-plan' else 12999360430)
 run.add(prod.attempt_name(prod.RUNTIME,1),b'SYNTHETIC attempt-1 runtime',1,ident=13000105279)
 listing=run.listing('',"artifacts")
 # The old design's by-name resolution is exactly the incident: the stale baseline-only artifact wins.
 run.add('public-ci-v3-plan',_zip(tmp_path/'download'/prod.attempt_name(prod.PLAN,2)),2,ident=12998263477)
 assert toolkit_by_name(run.listing('','artifacts'),'public-ci-v3-plan')['id']==12999360429
 # The attempt-scoped name is unique, so the same toolkit rule can only resolve the complete attempt-2 plan.
 current=toolkit_by_name(run.listing('','artifacts'),prod.attempt_name(prod.PLAN,2))
 assert current['id']==run.artifacts[0]['id'] and 'plan.json' in __import__('zipfile').ZipFile(__import__('io').BytesIO(run.archives[current['id']])).namelist()
 result=prod.authenticate_current(run,tmp_path/'download',tmp_path/'authenticated')
 receipts=read_json(result/'current-attempt-artifacts.json')
 assert receipts['attempt']==2 and {r['name'] for r in receipts['artifacts']}==set(run.current_names)
 assert not {12999360429,12999360430,13000105279,12998263477}&{r['id'] for r in receipts['artifacts']}
 # And the stale attempt-1 plan, had it been handed to a worker, is refused before Docker/pytest.
 no_docker(monkeypatch)
 with pytest.raises(ContractError,match='missing plan.json'):prod.worker(tmp_path,tmp_path/'w',stale,0,tmp_path/'download'/'x')
 assert listing  # attempt-1 artifacts were present the whole time

@pytest.mark.parametrize('order',['valid-first','malformed-first'])
def test_case_b_ambiguous_current_attempt_plan_is_rejected_whatever_the_order(tmp_path,monkeypatch,order):
 ctx,run=attempt_service(tmp_path,monkeypatch,5,attempt=2)
 malformed=_zip(stale_attempt_1_baseline_only(tmp_path))
 duplicate={**run.artifacts[0],'id':99,'digest':'sha256:'+__import__('hashlib').sha256(malformed).hexdigest()};run.archives[99]=malformed
 run.artifacts.insert(0 if order=='malformed-first' else 1,duplicate)
 with pytest.raises(ContractError,match='missing/duplicate service artifact'):prod.authenticate_current(run,tmp_path/'download',tmp_path/'authenticated')

def test_case_c_baseline_only_plan_starts_no_expensive_work(tmp_path,monkeypatch):
 (tmp_path/'current').mkdir();scale_plan(tmp_path/'current',monkeypatch,8)
 stale=stale_attempt_1_baseline_only(tmp_path);runtime=tmp_path/'runtime-image.tar.gz';runtime.write_bytes(RUNTIME_BYTES)
 no_docker(monkeypatch)
 for index in range(8):
  with pytest.raises(ContractError,match='incomplete plan artifact: missing plan.json'):prod.worker(tmp_path,tmp_path/f'w{index}',stale,index,runtime)
 # A complete plan.json without the attempt seal (i.e. never passed the plan job's seal step) is equally refused.
 write_json(stale/'plan.json',{'context':prod.context()})
 with pytest.raises(ContractError,match='missing attempt-seal.json'):prod.preflight(stale,runtime)

@pytest.mark.parametrize('mix',['runtime-from-other-attempt','plan-from-other-attempt','runtime-missing'])
def test_case_d_plan_and_runtime_from_different_attempts_rejected_before_docker(tmp_path,monkeypatch,mix):
 plan=tmp_path/'plan';plan.mkdir();ctx=scale_plan(plan,monkeypatch,8);ctx['attempt']=2
 data=read_json(plan/'plan.json');data['context']=ctx;write_json(plan/'plan.json',data)
 seal,runtime=sealed(plan)
 assert prod.preflight(plan,runtime)['context']['attempt']==2
 if mix=='runtime-from-other-attempt':runtime.write_bytes(b'SYNTHETIC attempt-1 rebuilt runtime, same HEAD')
 elif mix=='runtime-missing':runtime.unlink()
 else:monkeypatch.setattr(prod,'context',lambda:{**ctx,'attempt':3})
 no_docker(monkeypatch)
 with pytest.raises(ContractError,match='runtime|another run/attempt'):prod.worker(tmp_path,tmp_path/'w',plan,0,runtime)

def test_case_e_two_attempt_end_to_end_contract_authenticates_and_verifies_current_attempt(evidence,tmp_path,monkeypatch):
 """Attempt 1 left a baseline-only plan; attempt 2 completed. Seal -> upload -> download -> preflight -> independent verify."""
 plan,workers=evidence;ctx=read_json(plan/'plan.json')['context']
 monkeypatch.setattr(prod,'context',lambda:{**ctx,'attempt':2});data=read_json(plan/'plan.json');data['context']=prod.context();write_json(plan/'plan.json',data)
 sealed(plan)   # the plan job's seal step precedes every worker, so bindings name the final plan bytes
 for folder in workers:
  for name in ('binding.json','execution/child/adapter.json','execution/child/calibration.json'):
   d=read_json(folder/name);d['context']=prod.context();write_json(folder/name,d)
  d=read_json(folder/'binding.json');d['plan_sha256']=prod.sha(plan/'plan.json');write_json(folder/'binding.json',d)
 monkeypatch.setattr(prod,'authenticate_reference',lambda api,base,out,anchor=None:anchor)
 attempt=tmp_path/'service';attempt.mkdir()
 cur,run=attempt_service(attempt,monkeypatch,3,plan_source=plan,workers=workers)
 stale=_zip(stale_attempt_1_baseline_only(tmp_path/'attempt-1'))
 for k,name in enumerate(['public-ci-v3-plan',prod.attempt_name(prod.PLAN,1)]):run.add(name,stale,1,ident=12999360429+k)
 # Worker preflight on the downloaded handoff, then the expensive phase is never reached in this unit test.
 handoff=attempt/'download'/prod.attempt_name(prod.PLAN,2);runtime=plan.parent/(plan.name+'.runtime-image.tar.gz')
 assert prod.preflight(handoff,runtime)['plan']['worker_count']==3
 result=prod.authenticate_current(run,attempt/'download',attempt/'authenticated')
 proof=prod.verify_data(result/'public-ci-v3-plan',[result/f'public-ci-v3-worker-{i}' for i in range(3)])
 assert proof['attempt']==2 and proof['workers']==3 and proof['original_nodes']==6 and proof['cleanup_verified']

@pytest.mark.parametrize('attack',['rerun-failed-reused-attempt-1-plan','cancelled-plan','duplicated-worker','missing-worker','wrong-head',
 'forged-archive','mutated-payload-after-seal','wrong-tree','wrong-run','wrong-image','stale-worker-only','runtime-missing'])
def test_case_f_replays_reruns_and_forgeries_stay_fail_closed(tmp_path,monkeypatch,attack):
 ctx,run=attempt_service(tmp_path,monkeypatch,8,attempt=2);download=tmp_path/'download';plan=download/prod.attempt_name(prod.PLAN,2)
 if attack=='rerun-failed-reused-attempt-1-plan':
  # Re-run failed jobs: plan reused from attempt 1, so this attempt has no plan job and no attempt-2 artifacts.
  for a in run.artifacts:a['name']=a['name'].replace('-attempt-2','-attempt-1')
  run.jobs=[j for j in run.jobs if not j['name'].endswith('/ plan')]
 elif attack=='cancelled-plan':run.jobs[0]['conclusion']='cancelled'
 elif attack=='duplicated-worker':run.artifacts.append({**run.artifacts[3],'id':77});run.archives[77]=run.archives[run.artifacts[3]['id']]
 elif attack=='missing-worker':run.artifacts=[a for a in run.artifacts if a['name']!=prod.attempt_name('public-ci-v3-worker-4',2)]
 elif attack=='wrong-head':run.artifacts[2]['workflow_run']={**run.artifacts[2]['workflow_run'],'head_sha':'f'*40}
 elif attack=='wrong-run':run.artifacts[0]['workflow_run']={**run.artifacts[0]['workflow_run'],'id':1}
 elif attack=='forged-archive':run.archives[run.artifacts[0]['id']]=_zip(stale_attempt_1_baseline_only(tmp_path))
 elif attack=='mutated-payload-after-seal':
  # Service bytes and download agree, but the payload is not the one the plan job sealed.
  (plan/'baseline').mkdir();(plan/'baseline/injected.json').write_text('{}')
  import hashlib;data=_zip(plan);run.archives[run.artifacts[0]['id']]=data;run.artifacts[0]['digest']='sha256:'+hashlib.sha256(data).hexdigest()
 elif attack=='wrong-tree':monkeypatch.setattr(prod,'context',lambda:{**ctx,'source':{**ctx['source'],'tree':'e'*40}})
 elif attack=='wrong-image':
  import hashlib;s=read_json(plan/'attempt-seal.json');s['image']='sha256:'+'c'*64;write_json(plan/'attempt-seal.json',s)
  data=_zip(plan);run.archives[run.artifacts[0]['id']]=data;run.artifacts[0]['digest']='sha256:'+hashlib.sha256(data).hexdigest()
 elif attack=='stale-worker-only':
  w=next(a for a in run.artifacts if a['name']==prod.attempt_name('public-ci-v3-worker-7',2));w['name']=prod.attempt_name('public-ci-v3-worker-7',1)
 elif attack=='runtime-missing':run.artifacts=[a for a in run.artifacts if not a['name'].startswith('ci-v3-runtime')]
 with pytest.raises(ContractError):prod.authenticate_current(run,download,tmp_path/'authenticated')

def _plain(step_run):return step_run if isinstance(step_run,str) else ''

def test_workflow_publishes_only_complete_current_attempt_artifacts_and_consumes_by_attempt():
 jobs=flow()['jobs'];text=(ROOT/'.github/workflows/ci_v3_required_job.yml').read_text()
 uploads=[(n,s) for n,j in jobs.items() for s in j.get('steps',[]) if s.get('uses','').startswith('actions/upload-artifact@')]
 for job,step in uploads:
  name=step['with']['name']
  assert name.endswith('-attempt-${{ github.run_attempt }}'),name
  if name.startswith(('public-','ci-v3-runtime')):assert step['if']=='${{ success() }}' and step['with']['if-no-files-found']=='error',name
  else:assert name.startswith('ci-v3-diagnostic-') and step['if']=='${{ failure() || cancelled() }}',name
 assert 'always()' not in ''.join(str(s.get('if','')) for _,s in uploads)
 plan=jobs['plan']['steps'];ids=[s.get('id') for s in plan]
 assert ids.index('distribution')<ids.index('seal')<ids.index('plan_upload')<ids.index('runtime_upload')
 assert 'tools.ci_v3_production seal' in plan[ids.index('seal')]['run']
 worker=jobs['worker'];assert worker['if'].startswith("${{ success() && needs.plan.result == 'success'")
 downloads=[s for s in worker['steps'] if s.get('uses','').startswith('actions/download-artifact@')]
 assert [s['with']['artifact-ids'] for s in downloads]==['${{ needs.plan.outputs.plan_artifact_id }}','${{ needs.plan.outputs.runtime_artifact_id }}']
 assert all('name' not in s['with'] and 'pattern' not in s['with'] for s in downloads)
 assert worker['steps'][0]['name'].startswith('Refuse a plan produced by another run attempt')
 assert [s['with']['pattern'] for s in jobs['aggregate']['steps'] if s.get('uses','').startswith('actions/download-artifact@')]==['public-ci-v3-*-attempt-${{ github.run_attempt }}']
 assert 'name: public-ci-v3-plan\n' not in text and 'name: ci-v3-runtime\n' not in text

@pytest.mark.parametrize('plan_attempt,run_attempt,plan_id,ok',[('2','2','12998263477',True),('1','2','12999360429',False),('','2','',False),('2','2','',False)])
def test_worker_attempt_guard_runs_before_any_download(plan_attempt,run_attempt,plan_id,ok):
 step=flow()['jobs']['worker']['steps'][0]
 env={**os.environ,'PLAN_ATTEMPT':plan_attempt,'RUN_ATTEMPT':run_attempt,'PLAN_ID':plan_id,'RUNTIME_ID':plan_id and '13000105279'}
 assert (subprocess.run(['bash','-e','-c',step['run']],env=env,capture_output=True).returncode==0)==ok

@pytest.mark.parametrize('plan_attempt,ok',[('2',True),('1',False),('',False)])
def test_aggregate_requires_the_plan_of_this_attempt(plan_attempt,ok):
 script=flow()['jobs']['aggregate']['steps'][0]['run']
 env={**os.environ,'PLAN':'success','WORKERS':'success','PLAN_ATTEMPT':plan_attempt,'RUN_ATTEMPT':'2'}
 assert (subprocess.run(['bash','-e','-c',script],env=env).returncode==0)==ok

@pytest.mark.parametrize('shape',['scoped-attempt-2','legacy','scoped-missing-worker'])
def test_accepted_reference_selects_only_its_final_attempt(tmp_path,monkeypatch,shape):
 from tools import ci_v3_source_reference as ref
 head=subprocess.check_output(['git','rev-parse','HEAD'],cwd=ROOT,text=True).strip()
 base={'head':head,'tree':subprocess.check_output(['git','rev-parse','HEAD^{tree}'],cwd=ROOT,text=True).strip()}
 count=prod.routing()['worker_count']
 run={'id':41,'head_sha':head,'run_attempt':2,'conclusion':'success','path':'.github/workflows/public_safety_and_smoke.yml','head_repository':{'full_name':prod.REPO}}
 logical=['public-ci-v3-plan','public-ci-v3-aggregate',*[f'public-ci-v3-worker-{i}' for i in range(count)]]
 if shape=='legacy':names=logical
 else:names=[n+'-attempt-2' for n in logical]+[n+'-attempt-1' for n in logical]   # attempt 1 left complete-looking duplicates
 if shape=='scoped-missing-worker':names.remove('public-ci-v3-worker-0-attempt-2')
 listing=[{'id':i,'name':n,'expired':False,'digest':'sha256:0','workflow_run':{'head_sha':head}} for i,n in enumerate(['public-source-safety','public-shadow-proof',*names])]
 jobs=[{'name':n,'status':'completed','conclusion':'success'} for n in ['source-safety','safety-and-smoke / tests','mandatory-evidence',*[f'safety-and-smoke / worker-{i}' for i in range(count)]]]
 class Service:
  def get(self,path):return run
  def listing(self,path,key):return [run] if key=='workflow_runs' else listing if key=='artifacts' else jobs
 seen={}
 class Stop(Exception):pass
 def capture(api,r,lst,requested,out,folders=None):seen.update(names=requested,folders=folders or {});raise Stop
 monkeypatch.setattr(ref,'_download',capture)
 if shape=='scoped-missing-worker':
  with pytest.raises(ContractError,match='accepted reference worker set'):ref.authenticate_reference(Service(),base,tmp_path)
  return
 with pytest.raises(Stop):ref.authenticate_reference(Service(),base,tmp_path)
 expected=[n+('-attempt-2' if shape!='legacy' else '') for n in logical]
 assert sorted(seen['names'])==sorted(['public-source-safety','public-shadow-proof',*expected])
 assert {seen['folders'].get(n,n) for n in expected}==set(logical)


@pytest.mark.parametrize('mode,ready,runtime',[('parallel',True,True),('sequential',False,True),('sequential',True,False)])
def test_source_aware_admission_selects_parallel_only_with_authenticated_reference(mode,ready,runtime):
 assert prod.route_mode(prod.routing(),True,'',runtime,ready)==mode

@pytest.mark.parametrize('field,value',[('enabled',False),('rollback',True)])
def test_disabled_or_configured_rollback_is_sequential(field,value):
 config={**prod.routing(),field:value}
 assert prod.route_mode(config,True,'',True,True)=='sequential'

@pytest.mark.parametrize('field,value',[('enabled','true'),('rollback',0)])
def test_invalid_routing_switch_type_is_rejected(tmp_path,monkeypatch,field,value):
 p=tmp_path/'config.json';write_json(p,{**prod.routing(),field:value})
 monkeypatch.setattr(prod,'ROUTING',p)
 with pytest.raises(ContractError):prod.routing()

@pytest.mark.parametrize('attack',['removed-node','reconciliation','reference-base','merge-tree','merge-sha','merge-result-tree','merge-mode','attempt','setup','call','teardown','skip','xfail','failure','reference-outcome'])
def test_current_source_regressions_cannot_claim_historical_equivalence(evidence,attack):
 from tools.ci_v3_schema import seal
 plan,workers=evidence;data=read_json(plan/'plan.json')
 if attack=='removed-node':
  inv={k:v for k,v in data['inventory'].items() if k!='digest'};inv['nodes']=inv['nodes'][1:];data['inventory']=seal(inv)
  allocation={k:v for k,v in data['plan'].items() if k!='digest'};allocation['inventory_digest']=data['inventory']['digest'];data['plan']=seal(allocation)
 elif attack=='reconciliation':data['inventory_reconciliation']['added']=['tests/test_unknown.py::test_missing']
 elif attack=='reference-base':
  ref={k:v for k,v in data['source_reference'].items() if k!='digest'};ref['base']={'head':'f'*40,'tree':'f'*40};data['source_reference']=seal(ref)
 elif attack=='merge-tree':data['merge_guard']['tree']='e'*40
 elif attack=='merge-sha':data['merge_guard']['merge_sha']='e'*40
 elif attack=='merge-result-tree':data['merge_guard']['merge_tree']='e'*40
 elif attack=='merge-mode':data['merge_guard']['mode']='unchecked'
 elif attack=='reference-outcome':
  ref={k:v for k,v in data['source_reference'].items() if k!='digest'};ref['report']['phases'][0]['reason']='changed expected outcome without authority';data['source_reference']=seal(ref)
 else:
  f=workers[0]/'execution/child/adapter.json';r=read_json(f)
  if attack=='attempt':r['context']={**r['context'],'attempt':r['context']['attempt']+1}
  elif attack in ('setup','call','teardown'):r['phases']=[ph for j,ph in enumerate(r['phases']) if j!=next(i for i,x in enumerate(r['phases']) if x['when']==attack)]
  else:
   ph=next(x for x in r['phases'] if x['when']=='call')
   ph['outcome']='failed' if attack=='failure' else 'skipped';ph['reason']='unapproved changed outcome'
   if attack=='xfail':ph['wasxfail']='unapproved policy'
  write_json(f,r)
 write_json(plan/'plan.json',data)
 # Rebind benign changed plan bytes so the specific downstream semantic checks,
 # not a stale checksum alone, must reject the mutation.
 for folder in workers:
  binding=read_json(folder/'binding.json');binding['plan_sha256']=prod.sha(plan/'plan.json');write_json(folder/'binding.json',binding)
 with pytest.raises((ContractError,ValueError)):prod.verify_data(plan,workers)

@pytest.mark.parametrize('check',['worker binding','worker process/cleanup'])
def test_negative_controls_kill_removal_of_critical_verifier_checks(evidence,check):
 import inspect
 plan,workers=evidence
 if check=='worker binding':
  f=workers[0]/'binding.json';d=read_json(f);d['plan_sha256']='f'*64;write_json(f,d)
 else:
  f=workers[0]/'process.json';d=read_json(f);d['descendant_cleanup']['survivors_observed']=[{'pid':123}];write_json(f,d)
 def rejection_contract(verifier):
  with pytest.raises(ContractError):verifier(plan,workers)
 rejection_contract(prod.verify_data)
 code=inspect.getsource(prod.verify_data);lines=code.splitlines();found=[i for i,l in enumerate(lines) if "'"+check+"'" in l]
 assert len(found)==1
 line=lines[found[0]]
 # The worker binding check shares a line with reading the binding.
 if check=='worker binding':lines[found[0]]=line.split(';require',1)[0]
 else:lines[found[0]]='  pass  # SYNTHETIC MUTANT: required cleanup check removed'
 scope=dict(prod.__dict__);exec('\n'.join(lines),scope)
 with pytest.raises(pytest.fail.Exception):rejection_contract(scope['verify_data'])


@pytest.mark.parametrize('field,value',[('merge_tree','f'*40),('mode','main-head'),('merge_sha','e'*40),('equivalent',False)])
def test_synthetic_merge_record_requires_all_exact_identity_fields(evidence,monkeypatch,field,value):
 plan,workers=evidence;data=read_json(plan/'plan.json');src=data['context']['source'];merge='d'*40
 monkeypatch.setenv('FINCO_PRODUCTION_MERGE_SHA',merge)
 guard={**src,'mode':'identical-tree','merge_sha':merge,'merge_tree':src['tree'],'equivalent':True}
 prod.validate_merge_guard(guard)
 guard[field]=value
 with pytest.raises(ContractError):prod.validate_merge_guard(guard)


def test_accepted_sequential_success_does_not_authorize_new_nonpass(evidence):
 """A reference may preserve expectations, never invent Financial/CI policy."""
 import xml.etree.ElementTree as ET
 from tools.ci_v3_phase_compare import phase_map
 from tools.ci_v3_real_contract import outcome
 from tools.ci_v3_nonpass import node_id
 plan,workers=evidence
 data=read_json(plan/'plan.json');reference=data['source_reference']
 # The current/reference synthetic campaign has a real skip/xfail. Simulate it
 # being newly introduced relative to the independently pinned historical policy.
 chosen=next(n for n,v in phase_map(reference['report']).items() if outcome(v)['status']!='passed')
 file=plan/'baseline/public-verification-results/inventory.json';old=read_json(file)
 modules={n.split('::')[0] for n in old['collected']}
 old['collected']=[n for n in old['collected'] if n!=chosen]
 old['selected']=[n for n in old['selected'] if n!=chosen]
 old['phases']=[ph for ph in old['phases'] if ph['nodeid']!=chosen]
 old['outcomes'].pop(chosen)
 write_json(file,old)
 file=plan/'baseline/public-verification-results/results.xml';tree=ET.parse(file)
 for suite in tree.iter('testsuite'):
  for case in list(suite.findall('testcase')):
   if case.get('classname') and node_id(case.get('classname'),case.get('name'),modules)==chosen:suite.remove(case)
  direct=list(suite.findall('testcase'))
  if direct:
   for key,count in [('tests',len(direct)),('failures',sum(c.find('failure') is not None for c in direct)),('errors',sum(c.find('error') is not None for c in direct)),('skipped',sum(c.find('skipped') is not None for c in direct))]:suite.set(key,str(count))
 tree.write(file,encoding='utf-8')
 # All current reference/native outcomes agree; absence of actual policy is
 # independently blocking even though the accepted-source run was successful.
 with pytest.raises(ContractError,match='nonhistorical nonpass requires explicit reviewed authority'):
  prod.verify_data(plan,workers)


def test_reference_runtime_check_fails_closed_for_unresolvable_or_changed_source(monkeypatch):
 ref={'source':{'head':'88baaef'+'0'*33}}
 with pytest.raises(subprocess.CalledProcessError):prod.require_reference_runtime(ref)
 changed=dict(read_json(ROOT/'docs/ci_v3/phase4/runtime/inputs.json'),tampered=True)
 monkeypatch.setattr(prod,'reference_runtime_blob',lambda h,p:json.dumps(changed).encode())
 with pytest.raises(ContractError):prod.require_reference_runtime(ref)
