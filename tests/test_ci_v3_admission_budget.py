"""Reject unauthorized allocation before a container or hosted worker may start."""
from copy import deepcopy
import pytest
from tools.ci_v3_admission_budget import validate_spending
from tools.ci_v3_schema import ContractError


def fixture():
    source={'head':'a'*40,'tree':'b'*40}
    return {'source':source,'execution_mode':'shadow','run_id':123,'run_attempt':1,
        'budget_authorization':{'approved':True,'review_reference':'SYNTHETIC ONLY','source':source,
            'control_run_id':122,'control_attempt':1,'shadow_run_id':123,'shadow_attempt':1,
            'shadow_max_minutes':350,'control_max_minutes':230,'pair_max_minutes':590,
            'ancillary_accounting':'separately-authorized','ancillary_max_minutes':315,
            'ancillary_review_reference':'SYNTHETIC ONLY'}}


def test_exact_prospective_allocation_binds_source_run_and_attempt():
    assert validate_spending(fixture())['shadow_max_minutes']==350

@pytest.mark.parametrize('attack',['approval','source','run','attempt','shadow','control','pair','ancillary'])
def test_bad_or_lower_allocation_never_admits_execution(attack):
    root=fixture();b=root['budget_authorization']
    if attack=='approval':b['approved']=False
    elif attack=='source':b['source']={'head':'c'*40,'tree':'d'*40}
    elif attack=='run':b['shadow_run_id']=124
    elif attack=='attempt':b['shadow_attempt']=2
    elif attack=='ancillary':b.pop('ancillary_review_reference')
    else:b[attack+'_max_minutes']-=1
    with pytest.raises(ContractError):validate_spending(root)


def test_nonpass_decisions_bind_every_exact_record_and_both_required_owners():
    from tools.ci_v3_admission_budget import validate_nonpass_decisions
    source=fixture()['source'];record={'status':'xfail','reason':'exact declared reason'}
    policy={'allowed_nonpass':{'tests/test_a.py::test_x':record}}
    decisions={'source':source,'records':{'tests/test_a.py::test_x':{'record':record,'Financial':'SYNTHETIC','CI':'SYNTHETIC'}}}
    validate_nonpass_decisions(policy,decisions,source)
    bad=deepcopy(decisions);bad['records']['tests/test_a.py::test_x']['record']['reason']='obsolete'
    with pytest.raises(ContractError):validate_nonpass_decisions(policy,bad,source)
    bad=deepcopy(decisions);bad['records']['tests/test_a.py::test_x'].pop('Financial')
    with pytest.raises(ContractError):validate_nonpass_decisions(policy,bad,source)
    with pytest.raises(ContractError):validate_nonpass_decisions(policy,{'source':source,'records':{}},source)
