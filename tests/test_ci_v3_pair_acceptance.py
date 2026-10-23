"""Budget, proof and authorization negatives; synthetic records never authorize runs."""
from copy import deepcopy
import pytest
from tools.ci_v3_pair_acceptance import check_budget,performance,runner_minutes,validate_authorization
from tools.ci_v3_schema import ContractError


def authorization():
    return {'schema':1,'kind':'ci-v3-pair-authorization','approved':True,'experiment_pairs':1,'workers':3,
        'owner_references':{k:'synthetic-review-only' for k in ['Financial','Security','CI']},
        'budget':{'shadow_max_minutes':350,'pair_max_minutes':590,'ancillary_accounting':'included-in-pair','ancillary_max_minutes':75},
        'decisions':{k:{'approved':True,'reference':'synthetic','sha256':'a'*64}
                     for k in ['environment','nonpass','isolation','daemon_lifecycle','workflow_governance']}}

@pytest.mark.parametrize('attack',['unapproved','missing-owner','policy','mode','shadow','pair','ancillary'])
def test_bad_authorization_rejected(attack):
    value=authorization()
    if attack=='unapproved':value['approved']=False
    elif attack=='missing-owner':del value['owner_references']['Security']
    elif attack=='policy':value['decisions']['nonpass']['approved']=False
    elif attack=='mode':value['budget'].pop('ancillary_accounting')
    elif attack=='ancillary':value['budget'].pop('ancillary_max_minutes')
    else:value['budget'][attack+'_max_minutes']+=1
    with pytest.raises(ContractError):validate_authorization(value)


def test_caps_are_distinct_from_actual_usage_and_include_companions():
    value=authorization();validate_authorization(value)
    result=check_budget(value,100,150,30)
    assert result['charged_pair_minutes']==280
    assert result['allocation']['pair_max_minutes']==590
    with pytest.raises(ContractError):check_budget(value,240,350,1)
    with pytest.raises(ContractError):check_budget(value,100,351,0)
    with pytest.raises(ContractError):check_budget(value,100,150,76)


def test_single_observation_does_not_establish_mandatory_acceleration_or_repeatability():
    result=performance('2026-01-01T00:00:00Z','2026-01-01T01:20:00Z',
                       '2026-01-01T02:00:00Z','2026-01-01T02:40:00Z')
    assert result['observed_speedup']==2 and result['performance_success']
    assert not result['repeatability_established'] and not result['mandatory_ci_acceleration_established']
    slower=performance('2026-01-01T00:00:00Z','2026-01-01T01:20:00Z',
                       '2026-01-01T02:00:00Z','2026-01-01T02:41:00Z')
    assert not slower['performance_success']


def test_billing_rounds_each_executed_job_and_does_not_count_skipped_jobs():
    job={'status':'completed','conclusion':'success','started_at':'2026-01-01T00:00:00Z','completed_at':'2026-01-01T00:00:01Z'}
    assert runner_minutes([job,deepcopy(job),{'conclusion':'skipped'}])==2
    with pytest.raises(ContractError):runner_minutes([{**job,'status':'in_progress'}])
