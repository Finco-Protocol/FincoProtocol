"""Dormant deployment preserves contexts, permissions, fallback and no retry."""
from pathlib import Path
import yaml

ROOT=Path(__file__).resolve().parents[1]

def flow(name):
    return yaml.load((ROOT/'docs/ci_v3/phase4'/name).read_text(),Loader=yaml.BaseLoader)


def test_not_deployed_and_original_mandatory_still_sequential():
    assert not (ROOT/'.github/workflows/ci_v3_required_job.yml').exists()
    public=(ROOT/'.github/workflows/public_safety_and_smoke.yml').read_text()
    assert 'ci_v3' not in public and 'mode: control' in public


def test_reusable_permissions_and_stable_required_contexts():
    public=flow('public_safety_and_smoke.candidate.yml')
    required=flow('ci_v3_required_job.candidate.yml')
    assert set(public['jobs'])=={'source-safety','safety-and-smoke','mandatory-evidence'}
    assert public['jobs']['safety-and-smoke']['permissions']['actions']=='read'
    assert required['jobs']['tests']['name']=='tests'
    assert required['jobs']['sequential']['uses']=='./.github/workflows/ci_public_job.yml'
    assert required['jobs']['sequential']['with']['mode']=='control'
    assert required['jobs']['tests']['if']=='${{ always() }}'
    script=required['jobs']['tests']['steps'][0]['run']
    assert 'PARALLEL_RESULT' in script and 'SEQUENTIAL_RESULT' in script
    assert 'ci_pytest_runner' not in script  # never rerun tests after parallel failure


def test_exact_parallel_allocation_including_wrappers_and_source_proof():
    required=flow('ci_v3_required_job.candidate.yml');public=flow('public_safety_and_smoke.candidate.yml')
    total=sum(int(j['timeout-minutes']) for n,j in required['jobs'].items() if n!='sequential')
    total+=sum(int(j['timeout-minutes']) for n,j in public['jobs'].items() if n!='safety-and-smoke')
    assert total==375
    for i in range(3):assert required['jobs'][f'worker-{i}']['needs']==['route','plan']
    assert 'ci-v3-mandatory-admission' in required['jobs']['route']['environment']['name']
