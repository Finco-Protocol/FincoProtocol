"""Dormant activation rejects stale evidence; rollback selects original sequential."""
from copy import deepcopy
import pytest
from tools.ci_v3_activation import select_mode
from tools.ci_v3_schema import ContractError,seal


def fixture():
    source={'head':'a'*40,'tree':'b'*40};controller={'head':'c'*40,'tree':'d'*40}
    proof=seal({'schema':1,'kind':'ci-v3-pair-acceptance','source':source,'technical_validity':True,
        'phase_comparison':{'phase_equivalent':True,'process_cleanup_valid':True,'native_junit_valid':True},
        'performance':{'performance_success':True,'observed_speedup':2},
        'transports':{k:{'provenance_authenticated':True} for k in ['control','shadow']}})
    root={'schema':1,'kind':'ci-v3-mandatory-activation','enabled':True,'rollback':False,
        'deployment_review_reference':'SYNTHETIC ROUTING REVIEW ONLY',
        'owner_references':{k:'SYNTHETIC REVIEW ONLY' for k in ['Financial','Security','CI']},
        'source':source,'controller':controller,'mandatory_workflow_sha256':'e'*64,'accepted_pair_digest':proof['digest'],
        'workflow_governance_approved':True,'required_contexts_preserved':True,'browser_acceptance_preserved':True,
        'nonpass_policy_sha256':'f'*64,'isolation_policy_sha256':'1'*64,'environment_decision_sha256':'2'*64,
        'daemon_lifecycle_review_reference':'SYNTHETIC REVIEW ONLY'}
    proof=seal({**{k:v for k,v in proof.items() if k!='digest'},
        'accepted_decisions':{'nonpass':{'sha256':root['nonpass_policy_sha256']},
                             'isolation':{'sha256':root['isolation_policy_sha256']},
                             'environment':{'sha256':root['environment_decision_sha256']},
                             'daemon_lifecycle':{'reference':root['daemon_lifecycle_review_reference']}}})
    root['accepted_pair_digest']=proof['digest']
    kwargs={'source':source,'controller':controller,'workflow_sha256':'e'*64,'root_sha256':'3'*64,'expected_root_sha256':'3'*64}
    return root,proof,kwargs


def test_closed_and_rollback_select_sequential_before_execution():
    for value in [{'enabled':False},{'enabled':True,'rollback':True}]:
        result=select_mode(value,{},source={},controller={},workflow_sha256='',root_sha256='',expected_root_sha256='')
        assert result['mode']=='sequential' and not result['retry_on_parallel_failure']


def test_only_exact_protected_synthetic_fixture_can_select_parallel():
    root,proof,kwargs=fixture()
    result=select_mode(root,proof,**kwargs)
    assert result['mode']=='parallel' and not result['retry_on_parallel_failure']

@pytest.mark.parametrize('attack',['pin','source','controller','workflow','owner','native','cleanup','phase',
    'performance','transport','policy','governance','browser','proof-digest'])
def test_every_missing_gate_blocks_parallel_selection(attack):
    root,proof,kwargs=fixture()
    if attack=='pin':kwargs['expected_root_sha256']='9'*64
    elif attack in ['source','controller']:kwargs[attack]={'head':'9'*40,'tree':'8'*40}
    elif attack=='workflow':kwargs['workflow_sha256']='9'*64
    elif attack=='owner':del root['owner_references']['Security']
    elif attack=='policy':del root['nonpass_policy_sha256']
    elif attack in ['native','cleanup','phase']:
        field={'native':'native_junit_valid','cleanup':'process_cleanup_valid','phase':'phase_equivalent'}[attack]
        proof['phase_comparison'][field]=False
    elif attack=='performance':proof['performance']['observed_speedup']=1.99
    elif attack=='transport':proof['transports']['control']['provenance_authenticated']=False
    elif attack=='governance':root['workflow_governance_approved']=False
    elif attack=='browser':root['browser_acceptance_preserved']=False
    else:root['accepted_pair_digest']='9'*64
    if attack in ['native','cleanup','phase','performance','transport']:
        proof=seal({k:v for k,v in proof.items() if k!='digest'});root['accepted_pair_digest']=proof['digest']
    with pytest.raises(ContractError):select_mode(root,proof,**kwargs)
