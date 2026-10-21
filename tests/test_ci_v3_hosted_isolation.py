"""Exact-blob conservative partition constraints and credential-free container invocation."""
from pathlib import Path
import sys

import pytest
import yaml

from tests.ci_v3_synthetic_evidence import bundle, reseal
from tools.ci_v3_container import docker_command, image_ref, observe_container
from tools.ci_v3_isolation import assess, constrained_plan, verify_colocation
from tools.ci_v3_real_contract import file_sha
from tools.ci_v3_schema import ContractError, seal


@pytest.fixture
def reviewed(tmp_path):
    data=bundle();inventory=data['inventory'];root=tmp_path/'project'
    for module in inventory['modules']:
        p=root/module;p.parent.mkdir(parents=True,exist_ok=True);p.write_text('def test_example(): pass\n')
    isolation=seal({'schema':3,'kind':'ci-v3-isolation-policy','source':inventory['source'],
        'profile':'docker-no-network-private-workspace-v1','fixture_tree_reviewed':True,'review_reference':'unit fixture only',
        'modules':{m:{'sha256':file_sha(root/m),'reviewed':True,'rationale':'unit fixture','mode':'runner-private'} for m in inventory['modules']}})
    weights=seal({'schema':1,'kind':'ci-v3-weights','source':inventory['source'],'inventory_digest':inventory['digest'],
        'modules_ms':dict(zip(sorted(inventory['modules']),[4000,3000,1000,2000]))})
    return root,inventory,data['policy'],weights,isolation


def test_whole_module_deterministic_ownership_and_no_omission(reviewed):
    root,inventory,policy,weights,isolation=reviewed
    a=constrained_plan(*reviewed);b=constrained_plan(*reviewed)
    assert a==b and a['worker_count']==3
    assert set(a['module_workers'])==set(inventory['modules'])
    assert sum(sum(n['module']==m for n in inventory['nodes']) for m in a['module_workers'])==len(inventory['nodes'])


@pytest.mark.parametrize('attack',['unreviewed','stale-source','stale-blob','missing','external-network','host-resource','blocked','profile','fixtures','overlap'])
def test_unsupported_isolation_fails_closed(reviewed,attack):
    root,inventory,policy,weights,isolation=reviewed
    module=sorted(inventory['modules'])[0];decision=isolation['modules'][module]
    if attack=='unreviewed':decision['reviewed']=False
    elif attack=='stale-source':isolation['source']={'head':'f'*40,'tree':'e'*40}
    elif attack=='stale-blob':decision['sha256']='f'*64
    elif attack=='missing':isolation['modules'].pop(module)
    elif attack=='external-network':decision['requires_external_network']=True
    elif attack=='host-resource':decision['requires_host_resource']=True
    elif attack=='blocked':decision['mode']='blocked'
    elif attack=='profile':isolation['profile']='shared-host'
    elif attack=='fixtures':isolation['fixture_tree_reviewed']=False
    else:policy['module_overlaps']={module:['worker-2']};policy=reseal(policy)
    with pytest.raises(ContractError):constrained_plan(root,inventory,policy,weights,isolation)


def test_colocation_is_enforced_or_reports_sequential_bottleneck(reviewed):
    root,inventory,policy,weights,isolation=reviewed
    for m in isolation['modules'].values():m.update(mode='co-locate',group='all-session-state')
    with pytest.raises(ContractError,match='empty worker'):constrained_plan(*reviewed)
    plan={'module_workers':{'a':'worker-0','b':'worker-1'}}
    with pytest.raises(ContractError,match='split isolation'):verify_colocation(plan,{'session':['a','b']})


def test_static_findings_never_self_approve(tmp_path):
    path=tmp_path/'tests/test_risk.py';path.parent.mkdir()
    path.write_text('''import pytest
import sqlite3
STATE=[]
@pytest.fixture(scope="session")
def db():
 return sqlite3.connect("shared.db")
''')
    result=assess(tmp_path)['modules']['tests/test_risk.py']
    assert result['reviewed'] is False and result['mode']=='blocked'
    assert {'session-fixture','database','module-global-state'} <= {f['risk'] for f in result['findings']}


def test_container_never_inherits_actions_credentials(tmp_path,monkeypatch):
    monkeypatch.setenv('GH_TOKEN','do-not-forward-fixture')
    args=docker_command('example.invalid/image@sha256:'+'a'*64,'ci-v3-'+'b'*32,tmp_path/'project',tmp_path/'bootstrap',tmp_path/'evidence','worker-0')
    assert '--network=none' in args and '--read-only' in args and '--cap-drop=ALL' in args
    assert '--security-opt=no-new-privileges' in args
    assert all('GH_TOKEN' not in a and 'GITHUB_TOKEN' not in a and 'do-not-forward-fixture' not in a for a in args)
    assert not any('docker.sock' in a or '/home/runner' in a for a in args)
    assert any('target=/bootstrap,readonly' in a for a in args)


@pytest.mark.parametrize('image',['ubuntu:latest','image','x@sha256:short','x; echo bad'])
def test_mutable_or_malformed_images_rejected(image):
    with pytest.raises(ContractError):image_ref(image)


@pytest.mark.skipif(sys.platform=='linux',reason='This negative verifies the non-Linux refusal')
def test_no_windows_fallback_for_hosted_execution(tmp_path):
    with pytest.raises(ContractError,match='requires Linux'):observe_container({},tmp_path/'out',tmp_path,'example.invalid/image@sha256:'+'a'*64,10)
    assert not (tmp_path/'out').exists()


def test_candidate_has_real_stages_but_no_active_registration():
    root=Path(__file__).resolve().parents[1]
    path=root/'docs/ci_v3/phase2/shadow-workflow.candidate.yml'
    text=path.read_text(encoding='utf-8');flow=yaml.load(text,Loader=yaml.BaseLoader)
    assert not (root/'.github/workflows/ci_v3_shadow.yml').exists()
    assert set(flow['jobs'])=={'admission','plan','worker-0','worker-1','worker-2','aggregate'}
    assert 'exit 78' not in text and 'ci_v3_hosted_controller worker' in text
    assert flow['jobs']['aggregate']['if']=='always()'
    assert all(j['permissions']=={'contents':'read','actions':'read'} for j in flow['jobs'].values())
    assert flow['jobs']['admission']['environment']=='ci-v3-shadow-admission'
