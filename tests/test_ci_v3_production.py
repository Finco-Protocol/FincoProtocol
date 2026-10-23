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
 f=flow();jobs=f['jobs'];assert set(jobs)=={'route','sequential','plan','worker-0','worker-1','worker-2','aggregate','tests'}
 assert sum(int(j['timeout-minutes']) for n,j in jobs.items() if n!='sequential')==355
 assert jobs['sequential']['uses']=='./.github/workflows/ci_public_job.yml'
 for i in range(3):assert jobs[f'worker-{i}']['needs']==['route','plan']
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
