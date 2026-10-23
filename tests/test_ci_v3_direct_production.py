"""Direct admission attacks; real tiny local phases, SYNTHETIC service/owners only."""
from copy import deepcopy
from pathlib import Path
import json
import subprocess

import pytest

from tests.ci_v3_pair_fixtures import pair_bundle
from tests.ci_v3_hosted_fixtures import archive
from tools.ci_v3_activation import select_mode
from tools.ci_v3_direct import PROFILE,authenticate_control,check_environment,validate_profile
from tools.ci_v3_phase_compare import control_report
from tools.ci_v3_pytest_config import semantic_plugin_profile
from tools.ci_v3_schema import ContractError,canonical_bytes,digest,read_json,seal,write_json
from tools.ci_v3_hosted_transport import sha


@pytest.fixture(scope='module')
def original(tmp_path_factory):
    directory=tmp_path_factory.mktemp('SYNTHETIC-direct-production-only')
    data=pair_bundle(directory)
    folder=directory/'baseline/public-verification-results'
    proc=read_json(folder/'process.json')
    # Synthetic service metadata ONLY. Real supervisor cleanup is independently
    # exercised with actual orphan/setsid subprocesses in the cleanup module.
    proc.update(cleanup_verified=True)
    proc['process_markers']['cleanup']={'mechanism':'linux-subreaper-proc-waitpid-v1',
        'cleanup_verified':True,'survivors_observed':[],'survivors_remaining':[]}
    write_json(folder/'process.json',proc)
    payload=archive(folder);data['api'].payloads[31]=payload
    prefix='/repos/'+data['root']['repository']
    artifact=next(a for a in data['api'].data[prefix+'/actions/runs/121/artifacts']['artifacts'] if a['id']==31)
    artifact['digest']='sha256:'+sha(payload)
    data['auth']['mandatory_sequential_baseline']['anchors']['public-verification-results']['artifact_digest']=sha(payload)
    data['directory']=directory
    return data


@pytest.fixture
def data(original):
    d=dict(original);d['api']=deepcopy(original['api']);d['root']=deepcopy(original['root']);d['bundle']=deepcopy(original['bundle'])
    d['api'].authenticated_service=True  # mock service boundary only, never hosted evidence
    source=d['root']['source'];control=control_report(read_json(d['directory']/'baseline/public-verification-results/inventory.json'))
    env={'Security_reference':'SYNTHETIC ONLY','CI_reference':'SYNTHETIC ONLY',
         'control_environment_sha256':digest(control['environment']),
         'control_plugins_sha256':digest(semantic_plugin_profile(control['plugin_registrations'])),
         'worker_environment_sha256':digest(d['bundle']['environment']),
         'worker_plugins_sha256':digest(semantic_plugin_profile(control['plugin_registrations'])),
         'worker_host_contract':{'machine':'x86_64','minimum_cpus':2,'memory_limit_bytes':6*1024**3,'kernel_prefixes':['6.11.','7.0.']}}
    profile={'schema':1,'kind':'ci-v3-direct-production-admission','source':source,
      'source_equivalence_review_reference':'SYNTHETIC explicit identical-tree review',
      'control':{'source':source,'binding':deepcopy(original['auth']['mandatory_sequential_baseline']),
                 'proof_sha256':digest(read_json(d['directory']/'baseline/public-shadow-proof/public-single-proof.json'))},
      'browser':{'source':source,'binding':deepcopy(original['auth']['browser_run']),
                 'proof_sha256':digest(read_json(d['directory']/'browser/browser-proof.json'))},
      'environment_decision':env,'accepted_decisions':{
        'nonpass':{'sha256':digest(d['bundle']['policy'])},'isolation':{'sha256':digest(d['bundle']['isolation'])},
        'environment':{'sha256':digest(env)},'daemon_lifecycle':{'reference':'SYNTHETIC lifecycle only'}}}
    activation={'schema':1,'kind':'ci-v3-mandatory-activation','enabled':True,'rollback':False,
      'admission_mode':PROFILE,'source':source,'controller':{'head':'a'*40,'tree':'b'*40},
      'mandatory_workflow_sha256':'e'*64,'deployment_review_reference':'SYNTHETIC ONLY',
      'owner_references':{r:'SYNTHETIC ONLY' for r in ['Financial','Security','CI']},
      'pilot_waiver':{'Financial_reference':'SYNTHETIC ONLY','separate_pilot_required':False,'pre_activation_two_x_required':False},
      'workflow_governance_approved':True,'required_contexts_preserved':True,'browser_acceptance_preserved':True,
      'nonpass_policy_sha256':digest(d['bundle']['policy']),'isolation_policy_sha256':digest(d['bundle']['isolation']),
      'environment_decision_sha256':digest(env),'daemon_lifecycle_review_reference':'SYNTHETIC lifecycle only'}
    d['root'].update(activation=activation,shadow_plugin_profile_sha256=env['worker_plugins_sha256'])
    d['profile']=profile;refresh(d)
    return d


def refresh(d):
    profile={k:v for k,v in d['profile'].items() if k!='digest'};d['profile']=seal(profile)
    d['root']['direct_admission']=d['profile'];d['root']['activation']['direct_admission_digest']=d['profile']['digest']


def select(d):
    a=d['root']['activation']
    return select_mode(a,d['profile'],source=d['root']['source'],workflow_sha256=a['mandatory_workflow_sha256'],
                       controller=a['controller'],root_sha256='1'*64,expected_root_sha256='1'*64)


def test_direct_mode_has_explicit_waiver_and_never_fabricates_pair_or_speedup(data):
    assert select(data)['mode']=='parallel'
    assert 'performance' not in data['profile'] and 'accepted_pair_digest' not in data['root']['activation']
    assert not select(data)['retry_on_parallel_failure']


@pytest.mark.parametrize('attack',['Financial','Security','CI','waiver','two-x','pilot','tree','equivalence','proof-pin',
                                   'policy','environment','host','browser-attempt','workflow'])
def test_protected_direct_inputs_fail_closed(data,attack):
    a=data['root']['activation'];p=data['profile']
    if attack in ('Financial','Security','CI'):del a['owner_references'][attack]
    elif attack=='waiver':a['pilot_waiver']['Financial_reference']=''
    elif attack=='two-x':a['pilot_waiver']['pre_activation_two_x_required']=True
    elif attack=='pilot':a['accepted_pair_digest']='f'*64
    elif attack=='tree':p['control']['source']={**p['control']['source'],'tree':'f'*40}
    elif attack=='equivalence':p['source_equivalence_review_reference']=''
    elif attack=='proof-pin':p['control']['proof_sha256']=''
    elif attack=='policy':a['nonpass_policy_sha256']='f'*64
    elif attack=='environment':p['environment_decision']['Security_reference']=''
    elif attack=='host':p['environment_decision']['worker_host_contract']['memory_limit_bytes']=0
    elif attack=='browser-attempt':p['browser']['binding']['attempt']=2
    else:a['workflow_governance_approved']=False
    refresh(data)
    with pytest.raises(ContractError):select(data)


def test_rollback_returns_sequential_before_any_service_or_execution(data):
    data['root']['activation']['rollback']=True
    assert select(data)['mode']=='sequential'


def test_original_control_and_browser_are_actually_downloaded_and_reverified(data,tmp_path):
    report,native,proc=authenticate_control(data['root'],data['bundle'],data['project'],tmp_path/'verified',data['api'])
    assert len(report['selected'])==6 and native and proc['cleanup_verified']
    assert report['original_source']==data['root']['source']


@pytest.mark.parametrize('attack',['unauthenticated','control-head','native-byte','proof-hash','no-cleanup','live-descendant',
                                   'runtime','policy','browser-missing'])
def test_real_original_service_native_cleanup_and_policy_attacks(data,tmp_path,attack):
    root=data['root'];p=data['profile'];api=data['api'];prefix='/repos/'+root['repository']
    if attack=='unauthenticated':api.authenticated_service=False
    elif attack=='control-head':api.data[prefix+'/actions/runs/121']['head_sha']='f'*40
    elif attack=='native-byte':api.payloads[31]+=b'tampered'
    elif attack=='proof-hash':p['control']['proof_sha256']='f'*64
    elif attack in ('no-cleanup','live-descendant'):
        folder=tmp_path/'changed';folder.mkdir()
        import zipfile,io
        with zipfile.ZipFile(io.BytesIO(api.payloads[31])) as z:z.extractall(folder)
        proc=read_json(folder/'process.json')
        if attack=='no-cleanup':proc.pop('cleanup_verified')
        else:proc['process_markers']['cleanup']['survivors_observed']=[{'pid':999}]
        write_json(folder/'process.json',proc);payload=archive(folder);api.payloads[31]=payload
        a=next(a for a in api.data[prefix+'/actions/runs/121/artifacts']['artifacts'] if a['id']==31)
        a['digest']='sha256:'+sha(payload);p['control']['binding']['anchors']['public-verification-results']['artifact_digest']=sha(payload)
    elif attack=='runtime':p['environment_decision']['control_environment_sha256']='f'*64
    elif attack=='policy':data['bundle']['policy']['allowed_nonpass']={'unexecuted':{'status':'skipped','reason':'invented'}}
    else:api.data[prefix+'/actions/runs/120/artifacts']['artifacts']=[]
    refresh(data)
    with pytest.raises((ContractError,AssertionError)):
        authenticate_control(root,data['bundle'],data['project'],tmp_path/'rejected',api)


def test_worker_runtime_profiles_are_explicitly_reviewed_instead_of_rewritten_equal(data):
    control=control_report(read_json(data['directory']/'baseline/public-verification-results/inventory.json'))
    worker={'environment':deepcopy(data['bundle']['environment']),
            'plugin_registrations':control['plugin_registrations'],
            'runtime_host':{'machine':'x86_64','cpu_count':2,'kernel':'6.11.0-ci',
                            'cgroup_limits':{'memory.max':str(6*1024**3)}}}
    assert check_environment(data['root'],data['bundle'],control,[worker])
    worker['runtime_host']['cgroup_limits']['memory.max']='max'
    with pytest.raises((ContractError,ValueError)):check_environment(data['root'],data['bundle'],control,[worker])


def complete_root(d):
    """Full production root and service boundary, all marked SYNTHETIC ONLY."""
    root=d['root'];api=d['api'];repo=root['repository'];prefix='/repos/'+repo
    root.update(execution_authority='mandatory',experiment_pairs=0,run_attempt=1,
                workflow_path='.github/workflows/public_safety_and_smoke.yml')
    files={p:sha(('SYNTHETIC '+p).encode()) for p in ['.github/workflows/public_safety_and_smoke.yml',
        '.github/workflows/ci_v3_required_job.yml','.github/workflows/ci_public_job.yml']}
    root['workflow_files_sha256']=files;root['workflow_sha256']=files[root['workflow_path']]
    a=root['activation'];a.update(mandatory_workflow_sha256=root['workflow_sha256'],workflow_files_sha256=files)
    root['activation_sha256']=sha(canonical_bytes(a))
    root['production_budget_authorization']={'approved':True,'review_reference':'SYNTHETIC ONLY',
        'source':root['source'],'run_id':root['run_id'],'attempt':1,'maximum_minutes':375,
        'ancillary_accounting':'separately-authorized','ancillary_max_minutes':75,'ancillary_review_reference':'SYNTHETIC ONLY'}
    run=deepcopy(api.data[prefix+'/actions/runs/123']);run.update(run_attempt=1,event='push',status='in_progress',conclusion=None)
    api.data[prefix+'/actions/runs/123']=run;api.data[prefix+'/actions/runs/123/attempts/1']=run
    api.data[prefix+'/actions/workflows/77']['path']=root['workflow_path']
    for path in files:api.contents[(repo,root['workflow_head'],path)]=('SYNTHETIC '+path).encode()
    return root


@pytest.mark.parametrize('missing', [None,'root-pin','budget','isolation','unreviewed-isolation','owner'])
def test_full_router_selects_parallel_only_with_complete_admission(data,tmp_path,monkeypatch,missing):
    import tools.ci_v3_hosted_controller as host
    import tools.ci_v3_mandatory as mandatory
    import tools.ci_v3_hosted_transport as service
    root=complete_root(data)
    if missing=='budget':root['production_budget_authorization']['approved']=False
    if missing=='owner':del root['activation']['owner_references']['Security'];root['activation_sha256']=sha(canonical_bytes(root['activation']))
    if missing=='isolation':
        item=root['bundle']['files']['isolation']
        data['api'].contents[(root['bundle']['repository'],root['bundle']['revision'],item['path'])]=b'tampered'
    if missing=='unreviewed-isolation':
        isolation={k:v for k,v in data['bundle']['isolation'].items() if k!='digest'}
        isolation['fixture_tree_reviewed']=False;isolation=seal(isolation)
        item=root['bundle']['files']['isolation'];payload=canonical_bytes(isolation)
        data['api'].contents[(root['bundle']['repository'],root['bundle']['revision'],item['path'])]=payload
        item['sha256']=sha(payload);root['direct_admission']['accepted_decisions']['isolation']['sha256']=digest(isolation)
        root['activation']['isolation_policy_sha256']=digest(isolation);refresh(data)
        root['activation_sha256']=sha(canonical_bytes(root['activation']))
    path=tmp_path/'root.json';path.write_bytes(canonical_bytes(root));pin=sha(path.read_bytes())
    if missing=='root-pin':pin='0'*64
    # Controller checkout validation is independently adversarially exercised by
    # the hosted protocol suite; the synthetic tiny project is not this repo.
    monkeypatch.setattr(host,'validate_controller',lambda r:None)
    monkeypatch.setattr(mandatory,'GitHub',lambda:data['api'])
    monkeypatch.setenv('GITHUB_RUN_ID','123');monkeypatch.setenv('GITHUB_RUN_ATTEMPT','1')
    monkeypatch.setenv('CI_V3_REQUESTED_HEAD',root['source']['head']);monkeypatch.setenv('GITHUB_OUTPUT',str(tmp_path/'outputs'))
    output=tmp_path/'route.json'
    assert mandatory.main(['route','--root',str(path),'--root-sha256',pin,'--project',str(data['project']),'--output',str(output)])==0
    assert read_json(output)['execution_mode']==('parallel' if missing is None else 'sequential')
    if missing is None:
        assert (tmp_path/'direct-admission-evidence/authenticated-original.json').is_file()


@pytest.mark.parametrize('ancestor',[True,False])
def test_original_evidence_reuse_requires_identical_tree_and_real_ancestry(data,tmp_path,ancestor):
    project=tmp_path/'source'
    subprocess.run(['git','clone','--quiet','--local',str(data['project']),str(project)],check=True)
    tree=data['root']['source']['tree'];old=deepcopy(data['root']['source'])
    command=['git','-C',str(project),'-c','user.name=Synthetic','-c','user.email=synthetic@example.invalid','commit-tree',tree]
    if ancestor:command+=['-p',old['head']]
    head=subprocess.check_output(command,input='SYNTHETIC identical-tree source binding\n',text=True).strip()
    subprocess.run(['git','-C',str(project),'checkout','--quiet','--detach',head],check=True)
    data['root']['source']={'head':head,'tree':tree};data['profile']['source']=data['root']['source']
    data['root']['activation']['source']=data['root']['source'];refresh(data)
    assert select(data)['mode']=='parallel'
    if not ancestor:
        with pytest.raises(subprocess.CalledProcessError):
            authenticate_control(data['root'],data['bundle'],project,tmp_path/'verify',data['api'])
    else:
        view,_,process=authenticate_control(data['root'],data['bundle'],project,tmp_path/'verify',data['api'])
        assert view['source']==data['root']['source'] and view['original_source']==old
        raw=read_json(tmp_path/'verify/control/public-verification-results/inventory.json')
        assert raw['head']==old['head'] and process['cleanup_verified']


@pytest.mark.parametrize('attack',[None,'missing-worker','native-tamper','bad-cleanup'])
def test_direct_final_adapter_compares_all_three_real_tiny_workers(data,tmp_path,monkeypatch,attack):
    import shutil
    import tools.ci_v3_direct as direct
    import tools.ci_v3_hosted_controller as host
    from tools.ci_v3_mandatory import verify_current_phases
    received=tmp_path/'received';received.mkdir()
    for name,path in data['paths'].items():shutil.copytree(path,received/name)
    data['root']['_root_sha256']=data['root_sha']
    original_receipt=host.validate_receipt
    def synthetic_receipt(directory,stage,pin,ctx,root,execution_profile=None):
        value=original_receipt(directory,stage,pin,ctx,root,data['profile_name'])
        observed=value['observation']
        observed.setdefault('cleanup_verified',observed['descendant_cleanup_complete'] and not observed['surviving_descendants_at_parent_exit'])
        return value
    # Only the host-containment boundary is SYNTHETIC: these fixture receipts
    # explicitly declare their real local POSIX observer, never a Docker run.
    data['profile_name']=data['profile'] if isinstance(data['profile'],str) else 'posix-process-group'
    monkeypatch.setattr(host,'validate_receipt',synthetic_receipt)
    original_environment=direct.check_environment
    def local_environment(root,bundle,control,workers=()):
        for worker in workers:
            assert digest(worker['environment'])==root['direct_admission']['environment_decision']['worker_environment_sha256']
        return original_environment(root,bundle,control)  # Docker host contract separately tested above
    monkeypatch.setattr(direct,'check_environment',local_environment)
    if attack=='missing-worker':shutil.rmtree(received/'worker-2')
    elif attack=='native-tamper':(received/'worker-0/child/native.xml').write_text('changed')
    elif attack=='bad-cleanup':
        path=received/'worker-0/receipt.json';receipt=read_json(path)
        receipt['observation']['cleanup_verified']=False;write_json(path,receipt)
    def verify():
        return verify_current_phases(data['root'],data['bundle'],data['project'],received,tmp_path/'proof',data['api'])
    if attack:
        with pytest.raises((ContractError,OSError)):verify()
    else:
        result=verify()
        assert result['phase_equivalent'] and result['native_junit_valid'] and result['process_cleanup_valid']
        assert result['admission_mode']==PROFILE and 'performance' not in result
