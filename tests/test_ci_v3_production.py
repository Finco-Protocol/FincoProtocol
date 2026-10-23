"""Production routing and adversarial coverage checks; service fixtures are SYNTHETIC."""
from copy import deepcopy
import json,os,shutil,subprocess
from pathlib import Path
import pytest,yaml
from tools import ci_v3_production as prod
from tools.ci_v3_schema import ContractError,read_json,write_json
from tools.ci_v3_pytest_config import semantic_plugin_profile
ROOT=Path(__file__).resolve().parents[1]

def flow():return yaml.load((ROOT/'.github/workflows/ci_v3_required_job.yml').read_text(),Loader=yaml.BaseLoader)

@pytest.mark.parametrize('rollback,event,repo,mode',[('', 'push','Finco-Protocol/FincoProtocol','parallel'),('true','push','Finco-Protocol/FincoProtocol','sequential'),('','pull_request','elsewhere/fork','sequential'),('','pull_request','Finco-Protocol/FincoProtocol','parallel')])
def test_real_route_and_immediate_rollback(tmp_path,rollback,event,repo,mode):
 script=flow()['jobs']['route']['steps'][-1]['run'].replace('${{ github.event.pull_request.head.repo.full_name }}',repo)
 output=tmp_path/'output'
 subprocess.run(['bash','-e','-c',script],cwd=ROOT,check=True,env={**os.environ,'ROLLBACK':rollback,'GITHUB_EVENT_NAME':event,'GITHUB_REPOSITORY':'Finco-Protocol/FincoProtocol','GITHUB_OUTPUT':str(output)})
 assert output.read_text()=='execution_mode='+mode+'\n'

def test_active_profile_retains_all_bounds_and_no_credential_or_failure_bypass():
 f=flow();jobs=f['jobs'];assert set(jobs)=={'route','sequential','plan','worker','aggregate','tests'}
 assert sum(int(j['timeout-minutes']) for n,j in jobs.items() if n!='sequential')==155
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
 write_json(plan/'plan.json',{'context':ctx,'inventory':d['bundle']['inventory'],'plan':allocation,'image':image,'collection_environment':first['environment'],'collection_plugins':semantic_plugin_profile(first['plugin_registrations'])})
 workers=[]
 for i in range(3):
  folder=tmp_path/f'worker-{i}';folder.mkdir();shutil.copytree(d['paths'][f'worker-{i}']/'child',folder/'execution/child')
  write_json(folder/'binding.json',{'context':ctx,'worker':i,'plan_sha256':prod.sha(plan/'plan.json'),'image':image})
  # Synthetic process receipt ONLY; actual subreaper/container tests are separate.
  write_json(folder/'process.json',{'normal_successful_exit':True,'container_removed':True,'source_bytes_unchanged':True,'descendant_cleanup':{'cleanup_verified':True,'survivors_observed':[],'survivors_remaining':[]}})
  write_json(folder/'execution/child/calibration.json',{'context':ctx,'meets_test_assumption':True,'samples_s':[.1,.2,.3]})
  workers.append(folder)
 return plan,workers

def test_complete_real_original_nodes_phases_native_outcomes(evidence):
 result=prod.verify_data(*evidence)
 assert result['original_nodes']==6 and result['workers']==3 and result['cleanup_verified']
 assert result['baseline_is_current_source'] is False

@pytest.mark.parametrize('attack',['missing-phase','phase-reason','native-byte','source','environment','ownership','cleanup','calibration','plan-pin'])
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
 write_json(tmp_path/'plan.json',{'context':ctx,'inventory':inv,'plan':allocation})
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
 import hashlib,io,zipfile
 download=tmp_path/'download';plan=download/'public-ci-v3-plan';plan.mkdir(parents=True)
 ctx=scale_plan(plan,monkeypatch,count)
 artifacts=[];jobs=[];archives={}
 names=['public-ci-v3-plan',*[f'public-ci-v3-worker-{i}' for i in range(count)]]
 for ident,name in enumerate(names,1):
  folder=download/name
  if name!='public-ci-v3-plan':folder.mkdir();(folder/'receipt.txt').write_text(name)
  buffer=io.BytesIO()
  with zipfile.ZipFile(buffer,'w') as archive:
   for file in folder.rglob('*'):
    if file.is_file():archive.writestr(str(file.relative_to(folder)),file.read_bytes())
  data=buffer.getvalue();archives[ident]=data
  artifacts.append({'id':ident,'name':name,'expired':False,'digest':'sha256:'+hashlib.sha256(data).hexdigest()})
  suffix='plan' if name=='public-ci-v3-plan' else name.removeprefix('public-ci-v3-')
  jobs.append({'name':'safety-and-smoke / '+suffix,'status':'completed','conclusion':'success'})
 if attack=='missing':artifacts.pop()
 elif attack=='extra':artifacts.append({**artifacts[-1],'name':f'public-ci-v3-worker-{count}'})
 elif attack=='duplicate':artifacts.append(dict(artifacts[-1]))
 elif attack=='failed-producer':jobs[-1]['conclusion']='failure'
 elif attack=='archive-bytes':archives[len(names)]=b'corrupted'
 class Service:
  def get(self,path):return {'head_sha':ctx['source']['head'],'run_attempt':ctx['attempt']}
  def listing(self,path,key):return artifacts if key=='artifacts' else jobs
  def raw(self,path,archive):return archives[int(path.split('/')[-2])]
 if attack:
  with pytest.raises(ContractError):prod.authenticate_current(Service(),download,tmp_path/'authenticated')
 else:
  result=prod.authenticate_current(Service(),download,tmp_path/'authenticated')
  assert {p.name for p in result.iterdir()}==set(names)
