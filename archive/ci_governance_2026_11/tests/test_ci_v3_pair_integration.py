"""Full pair orchestration with real tiny tests and SYNTHETIC service authority.

No data from this fixture is production/hosted evidence or owner approval.
"""
from copy import deepcopy
import pytest
from tests.ci_v3_pair_fixtures import pair_bundle
from tools import ci_v3_pair_acceptance as pair
from tools import ci_v3_hosted_controller as hosted
from tools.ci_v3_schema import ContractError

@pytest.fixture(scope='module')
def original(tmp_path_factory):return pair_bundle(tmp_path_factory.mktemp('SYNTHETIC-pair-only'))

@pytest.fixture
def data(original,monkeypatch):
    data=dict(original);data['api']=deepcopy(original['api']);data['auth']=deepcopy(original['auth'])
    # Mock the service boundary only. Actual phase/JUnit/process/coverage checking remains real.
    data['api'].authenticated_service=True
    data['api'].observation_time=lambda path:'2026-10-21T10:30:00+00:00'
    monkeypatch.setattr(pair,'validate_controller',lambda root:None)
    original_receipt=hosted.validate_receipt;original_plan=hosted.read_plan;original_aggregate=hosted.aggregate
    def local_receipt(*args):
        value=original_receipt(*args,execution_profile=data['profile'])
        observation=value['observation']
        assert observation['descendant_cleanup_complete'] and not observation['surviving_descendants_at_parent_exit']
        return {**value,'observation':{**observation,'cleanup_verified':True}}
    monkeypatch.setattr(pair,'validate_receipt',local_receipt)
    monkeypatch.setattr(pair,'read_plan',lambda *args:original_plan(*args,execution_profile=data['profile']))
    def synthetic_aggregate(*args,**kwargs):
        values=list(args);values[-1]={**values[-1],'provenance_authenticated':False}
        return original_aggregate(*values,execution_profile=data['profile'])
    monkeypatch.setattr(pair,'aggregate',synthetic_aggregate)
    return data


def test_full_synthetic_pair_including_completed_aggregate_and_original_mandatory_control(data,tmp_path):
    result=pair.authenticate_pair(data['api'],data['auth'],data['auth_path'],data['project'],tmp_path/'proof')
    assert result['technical_validity'] and result['phase_comparison']['original_nodes']==6
    assert result['performance']['performance_success']
    assert not result['production_activation_authorized']
    assert result['browser_transport']['proof']['mandatory_roles'].keys()=={'protocol','import','grid','q4','outputs','consolidation'}

@pytest.mark.parametrize('attack',['wrong-baseline-workflow','missing-financial-policy','lifecycle-source','control-artifact',
    'browser-context','missing-browser-role','unauthenticated-service','pre-execution-budget'])
def test_orchestration_rejects_wrong_or_incomplete_exact_evidence(data,tmp_path,attack):
    api=data['api'];auth=data['auth'];prefix='/repos/'+data['root']['repository']
    if attack=='wrong-baseline-workflow':api.data[prefix+'/actions/workflows/88']['path']='.github/workflows/unrelated.yml'
    elif attack=='missing-financial-policy':auth['decisions']['nonpass']['sha256']='f'*64
    elif attack=='lifecycle-source':auth['lifecycle_evidence']['source']={'head':'f'*40,'tree':'f'*40}
    elif attack=='control-artifact':auth['control']['anchors']['control']['artifact_id']=999
    elif attack=='browser-context':auth['mandatory_browser_context']='source-safety'
    elif attack=='missing-browser-role':api.payloads[40]+=b'changed archive'
    elif attack=='unauthenticated-service':api.authenticated_service=False
    else:auth['budget_authorization']['pair_max_minutes']=589
    with pytest.raises((ContractError,KeyError,ValueError)):
        pair.authenticate_pair(api,auth,data['auth_path'],data['project'],tmp_path/'rejected')


def test_noncanonical_accepted_control_preserves_original_byte_pin(original,tmp_path):
    import base64,json
    from tools.ci_v3_mandatory import load_accepted_control
    from tools.ci_v3_hosted_transport import sha
    document=json.loads((original['auth_path'].parent/'control-root.json').read_text())
    raw=json.dumps(document,indent=4).encode()+b'\n\n'
    binding={'root_b64':base64.b64encode(raw).decode(),'root_sha256':sha(raw)}
    path=tmp_path/'original-root.json'
    value=load_accepted_control(binding,path)
    assert value['execution_mode']=='control' and path.read_bytes()==raw
    binding['root_b64']=base64.b64encode(raw+b' ').decode()
    with pytest.raises(ContractError):load_accepted_control(binding,tmp_path/'changed-root.json')


def test_deployed_sequential_uploader_keeps_independent_stable_context(data,tmp_path):
    from tools.ci_v3_hosted_transport import receive_mandatory_control
    api=data['api'];prefix='/repos/'+data['root']['repository']
    metadata=api.data[prefix+'/actions/runs/121/attempts/1/jobs']
    uploader=next(j for j in metadata['jobs'] if j['name']=='safety-and-smoke / tests')
    uploader['name']='safety-and-smoke / sequential / tests'
    metadata['jobs'].append({**uploader,'id':999,'name':'safety-and-smoke / tests',
                             'started_at':'2026-10-21T07:55:00Z','completed_at':'2026-10-21T07:56:00Z'})
    metadata['total_count']+=1
    result=receive_mandatory_control(api,data['root']['repository'],data['root']['source'],
                                    data['auth']['mandatory_sequential_baseline'],tmp_path/'baseline')
    assert result['provenance_authenticated']  # SYNTHETIC SERVICE STUB ONLY
    metadata['jobs'][-1]['conclusion']='failure'
    with pytest.raises(ContractError):receive_mandatory_control(api,data['root']['repository'],data['root']['source'],
                                    data['auth']['mandatory_sequential_baseline'],tmp_path/'bad-baseline')


@pytest.mark.parametrize('change',['identity','reason'])
def test_mandatory_collection_skip_substitution_rejected(data,tmp_path,monkeypatch,change):
    # Authenticated fixture transport remains real. Alter only mandatory skip
    # evidence at the comparison boundary; regenerate its native case/process
    # hash and original mandatory proof so those independent checks still pass.
    import os
    import xml.etree.ElementTree as ET
    from tools.ci_v3_schema import read_json,write_json
    from tools.ci_v3_real_contract import file_sha
    from tools.ci_v3_phase_compare import control_report,native_cases
    from tools.ci_single_gate import verify_control
    original_receive=pair.receive_mandatory_control
    def receive(*args,**kwargs):
        result=original_receive(*args,**kwargs)
        directory=args[-1]; folder=directory/'public-verification-results'
        inventory=read_json(folder/'inventory.json')
        skips=inventory['collection_skip_records']
        assert skips  # real tiny synthetic project has a collection skip
        record=dict(skips[0])
        if change=='identity':record['nodeid']='tests/test_changed_collection.py'
        else:record['reason']='changed mandatory-only collection reason'
        skips[0]=record
        inventory['collection_skips']=skips
        write_json(folder/'inventory.json',inventory)
        xml=ET.parse(folder/'results.xml')
        case=next(c for c in xml.getroot().iter('testcase') if not c.get('classname'))
        if change=='identity':case.set('name',record['nodeid'].removesuffix('.py').replace('/','.'))
        case.find('skipped').set('message',record['reason'])
        xml.write(folder/'results.xml',encoding='utf-8')
        native_cases((folder/'results.xml').read_bytes(),control_report(inventory))
        process=read_json(folder/'process.json');process['junit_sha256']=file_sha(folder/'results.xml')
        write_json(folder/'process.json',process)
        old=os.getcwd()
        try:
            os.chdir(data['project'])
            proof=verify_control(directory.resolve(),data['root']['source']['head'],'success','success')
        finally:os.chdir(old)
        write_json(directory/'public-shadow-proof/public-single-proof.json',proof)
        return result
    monkeypatch.setattr(pair,'receive_mandatory_control',receive)
    with pytest.raises(ContractError,match='mandatory/control collection skips differ'):
        pair.authenticate_pair(data['api'],data['auth'],data['auth_path'],data['project'],tmp_path/'rejected')
