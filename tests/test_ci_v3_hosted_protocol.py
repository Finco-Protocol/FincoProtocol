"""Service-shaped transport attacks and real-subprocess integration, never FINCO execution."""
from copy import deepcopy
import io
from pathlib import Path
import stat
import zipfile

import pytest

from tests.ci_v3_hosted_fixtures import real_bundle
from tools.ci_v3_hosted_controller import STAGES, aggregate, load_bundle, load_root, validate_controller
from tools.ci_v3_hosted_transport import extract_archive, receive, sha
from tools.ci_v3_schema import ContractError, canonical_bytes


@pytest.fixture(scope='module')
def actual_hosted_bundle(tmp_path_factory):
    return real_bundle(tmp_path_factory.mktemp('actual-subprocess-mocked-service'))


@pytest.fixture
def data(actual_hosted_bundle):
    d=dict(actual_hosted_bundle)
    for key in ['api','anchors','root']: d[key]=deepcopy(d[key])
    return d


def transfer(data,path):
    return receive(data['api'],data['root'],123,2,data['anchors'],path,STAGES)


def test_complete_real_execution_and_mock_service_chain(data,tmp_path):
    transport=transfer(data,tmp_path/'received')
    proof=aggregate(data['root'],data['root_sha'],data['bundle'],data['project'],tmp_path/'received',tmp_path/'verified',123,2,transport,data['profile'])
    assert proof['coverage_valid'] and not proof['authoritative_acceptance']
    assert proof['execution']['phase1_proof']['unique_nodes']==6
    assert proof['transport']['provenance_mode']=='mock-service'
    assert proof['transport']['provenance_authenticated'] is False
    assert proof['execution_profile']==data['profile']


@pytest.mark.parametrize('attack',['run','attempt','stale-attempt','job','job-attempt','cancelled','worker-cancelled','source',
    'tree','controller','workflow','artifact-id','digest','bytes','missing-worker','duplicate-artifact','duplicate-anchor',
    'expired','receipt-pin','foreign-artifact-run','foreign-artifact-sha','job-time','missing-independent-anchor','extra-artifact','root-run','root-attempt'])
def test_service_transport_negative_controls(data,tmp_path,attack):
    api=data['api'];prefix='/repos/'+data['root']['repository'];run=api.data[prefix+'/actions/runs/123/attempts/2']
    jobs=api.data[prefix+'/actions/runs/123/attempts/2/jobs']['jobs'];artifacts=api.data[prefix+'/actions/runs/123/artifacts']['artifacts']
    if attack=='run':run['id']=456
    elif attack=='attempt':run['run_attempt']=1
    elif attack=='stale-attempt':api.data[prefix+'/actions/runs/123']['run_attempt']=3
    elif attack=='job':jobs[1]['id']=999
    elif attack=='job-attempt':jobs[1]['run_attempt']=1
    elif attack=='cancelled':run['conclusion']='cancelled'
    elif attack=='worker-cancelled':jobs[1]['conclusion']='cancelled'
    elif attack=='source':run['head_sha']='f'*40
    elif attack=='tree':api.data[prefix+'/git/commits/'+data['root']['source']['head']]['tree']['sha']='f'*40
    elif attack=='controller':api.data[prefix+'/git/commits/'+data['root']['controller_head']]['tree']['sha']='f'*40
    elif attack=='workflow':api.data[prefix+'/actions/workflows/77']['path']='.github/workflows/other.yml'
    elif attack=='artifact-id':artifacts[1]['id']=999
    elif attack=='digest':artifacts[1]['digest']='sha256:'+'f'*64
    elif attack=='bytes':api.payloads[11]+=b'replacement'
    elif attack=='missing-worker':artifacts.pop()
    elif attack=='duplicate-artifact':artifacts.append(deepcopy(artifacts[1]))
    elif attack=='duplicate-anchor':data['anchors']['worker-1']['artifact_id']=11
    elif attack=='expired':artifacts[1]['expired']=True
    elif attack=='receipt-pin':data['anchors']['worker-0']['receipt_sha256']='f'*64
    elif attack=='foreign-artifact-run':artifacts[1]['workflow_run']['id']=456
    elif attack=='foreign-artifact-sha':artifacts[1]['workflow_run']['head_sha']='f'*40
    elif attack=='job-time':artifacts[1]['created_at']='2026-10-20T01:00:00Z'
    elif attack=='missing-independent-anchor':data['anchors'].pop('worker-2')
    elif attack=='extra-artifact':artifacts.append({**deepcopy(artifacts[1]),'id':999,'name':'ci-v3-unknown-123-2'})
    elif attack=='root-run':data['root']['run_id']=456
    elif attack=='root-attempt':data['root']['run_attempt']=1
    with pytest.raises((ContractError,KeyError)):transfer(data,tmp_path/'received')


@pytest.mark.parametrize('field',['inventory','policy','weights','isolation','environment'])
def test_substituted_approved_inputs_rejected(data,field):
    key=(data['root']['repository'],'e'*40,field+'.json');data['api'].contents[key]+=b' '
    with pytest.raises(ContractError,match='bundle substitution'):load_bundle(data['api'],data['root'])


def test_bundle_and_closed_admission(data,tmp_path):
    assert canonical_bytes(load_bundle(data['api'],data['root']))==canonical_bytes(data['bundle'])
    root=Path(__file__).resolve().parents[1]/'docs/ci_v3/phase3a/admission-root.closed.json'
    with pytest.raises(ContractError,match='closed'):load_root(root,sha(root.read_bytes()))
    with pytest.raises(ContractError,match='independent'):load_root(root,'')
    approved=tmp_path/'fixture-root.json';approved.write_bytes(canonical_bytes(data['root']))
    assert load_root(approved,sha(approved.read_bytes()))['enabled']
    with pytest.raises(ContractError,match='substitution'):load_root(approved,'f'*64)


def test_wrong_actual_controller_is_not_approved(data):
    with pytest.raises(ContractError,match='controller|dirty|working bytes'):validate_controller(data['root'])


def test_local_execution_cannot_claim_hosted_authentication(data,tmp_path):
    transport=transfer(data,tmp_path/'received');transport['provenance_authenticated']=True
    with pytest.raises(ContractError,match='cannot claim hosted'):
        aggregate(data['root'],data['root_sha'],data['bundle'],data['project'],tmp_path/'received',tmp_path/'out',123,2,transport,data['profile'])


def test_missing_original_native_evidence_rejected(data,tmp_path):
    transport=transfer(data,tmp_path/'received');(tmp_path/'received/worker-0/child/native.xml').unlink()
    with pytest.raises(ContractError,match='artifact differs'):
        aggregate(data['root'],data['root_sha'],data['bundle'],data['project'],tmp_path/'received',tmp_path/'out',123,2,transport,data['profile'])


@pytest.mark.parametrize('name',['../escape','/absolute','C:/drive','dir\\escape'])
def test_archive_traversal_rejected_before_writes(tmp_path,name):
    data=io.BytesIO()
    with zipfile.ZipFile(data,'w') as z:z.writestr(name,b'bad')
    # ZipInfo normalizes backslashes on Windows; mutate the wire member names
    # so the negative actually delivers the unsafe spelling to the receiver.
    wire=data.getvalue().replace(name.replace('\\','/').encode(),name.encode())
    with pytest.raises(ContractError,match='unsafe archive'):extract_archive(wire,tmp_path/'out')
    assert not (tmp_path/'out').exists()


def test_archive_symlink_rejected(tmp_path):
    data=io.BytesIO();info=zipfile.ZipInfo('link');info.external_attr=(stat.S_IFLNK|0o777)<<16
    with zipfile.ZipFile(data,'w') as z:z.writestr(info,b'../escape')
    with pytest.raises(ContractError,match='symlink'):extract_archive(data.getvalue(),tmp_path/'out')
