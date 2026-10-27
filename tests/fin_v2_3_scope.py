"""Additive exact-blob FIN-V2-3 cohort, Financial Owner prompt §0 / §8 / §9.

Recognition authorizes only the recorded source successor. It does not activate
native, quarterly, BESS or junior products, merge a PR, or alter historical pins.
"""
from pathlib import Path
import hashlib
import json
import subprocess

ROOT = Path(__file__).resolve().parents[1]
BASE = '128bf0c2b79af56985326543132cc806ff7f001c'
MANIFEST = 'docs/financial_validation/fin_v2_3/SOURCE_SUCCESSOR.json'
PROTECTED = ('app/', 'financial_engine/', 'finco_core/', 'domain/', '.github/', 'main_web.py')
# Accepted, already-merged #390 dependency; exact SHA-1 Git blob checks, not a scope exemption.
INTEGRATION_MAIN = 'f79e251903621c1a5c88501d51d6971960b612d3'
INTEGRATED_DEPENDENCIES = {
    'app/run_integrity/senior_debt_evidence.py': 'f9e0caefd74d86c368ae2b74cef2cfc035b937b1',
    'docs/financial_validation/finv2_c1_fix_1a/README.md': 'f420d28ec3c136324433ee262d018ed6f4d48aef',
    'docs/financial_validation/finv2_c1_fix_1a/dump_payload_digest.py': '23b45371d883109cfa80503cff9f87873d33cd58',
    'docs/financial_validation/finv2_c1_fix_1a/payload_digest_branch.json': 'ebd1bdb25b801fb3c7f1e99dea96e3b7905c0e26',
    'docs/financial_validation/finv2_c1_fix_1a/payload_digest_main_128bf0c.json': 'ebd1bdb25b801fb3c7f1e99dea96e3b7905c0e26',
    'docs/financial_validation/finv2_c1_fix_1a/reference_evidence_four_verticals.json': '5963517f28a1e0ae0a5b8b08124b0572268a9638',
    'tests/test_senior_debt_evidence_c1_fix_1a.py': '8fedb33e1daef62b5488b92a6539b0a19fd37866'
}

OWNED_PATHS = frozenset(('.github/workflows/fin_v2_3_oracle.yml', 'app/api/project_runner.py', 'app/export/financial_core_reporting.py', 'app/export/institutional_reporting_v3.py', 'app/export/run_evidence.py', 'app/input_adapter.py', 'app/services/clean_presentation_adapter.py', 'app/services/financial_core_evidence.py', 'app/services/financial_goal_seek.py', 'app/services/goal_seek.py', 'app/services/ic_report_service.py', 'app/services/sensitivity_execution.py', 'app/v2/react_goal_seek.py', 'app/v2/router.py', 'app/workbook/financial_core_config.py', 'app/workbook/registry.py', 'app/workbook/update_service.py', 'financial_engine/adapters/project_inputs.py', 'financial_engine/shl/timing_contract.py', 'financial_engine/valuation/loan_life.py', 'financial_engine/valuation/model.py', 'financial_engine/valuation/sponsor.py', 'finco_core/inputs/_models.py', 'finco_core/inputs/serialization.py', 'finco_core/inputs/shl_timing.py', 'finco_core/inputs/valuation.py', 'tests/fin_v2_3_oracle.py', 'tests/fin_v2_3_scope.py', 'tests/fin_v2_3_support.py', 'tests/finance_integrity_governance.py', 'tests/finval_f01_scope.py', 'tests/fixtures/fin_v2_3_baseline.json', 'tests/model_mutation_security_successor.py', 'tests/model_react_mvp_acceptance.py', 'tests/model_react_overnight_b_acceptance.py', 'tests/quarterly_candidate_recognition.py', 'tests/rcm_adapter_csrf_successor.py', 'tests/test_ci_acceptance.py', 'tests/test_fin_v2_3_contracts.py', 'tests/test_fin_v2_3_goal_seek.py', 'tests/test_fin_v2_3_lifecycle.py', 'tests/test_fin_v2_3_numerical.py', 'tests/test_fin_v2_3_scope.py', 'tests/test_finval_f01_fixture_integrity.py', 'tests/test_finval_rate_successor.py', 'tests/test_model_mutation_security_successor.py', 'tests/test_model_react_overnight_b_governance.py', 'tests/test_model_react_rcm_goal_seek_v1.py', 'tests/test_model_workspace_productivity_v1.py', 'tests/test_rcm_governance.py', 'tests/test_tax_wf10_candidate.py', 'tests/test_v11_stage3_successor.py', 'tests/v11_stage3_successor.py', 'tools/fin_v2_3_oracle_workbook.py'))


def _git(root, *args):
    return subprocess.check_output(['git',*args],cwd=root,stderr=subprocess.DEVNULL)


def _read(root,path,ref):
    return (root/path).read_bytes() if ref is None else _git(root,'show',ref+':'+path)


def manifest(repo=None,ref=None):
    root=Path(repo) if repo is not None else ROOT
    try:
        data=json.loads(_read(root,MANIFEST,ref))
        return data if data.get('schema_version')=='FIN_V2_3_EXACT_SOURCE_V1' and data.get('base')==BASE else {}
    except (OSError,ValueError,subprocess.CalledProcessError):return {}


def _blob(data):
    return hashlib.sha1(b'blob '+str(len(data)).encode()+b'\0'+data).hexdigest()


def exact_blobs_ok(repo=None,ref=None):
    """History, the integrated #390 dependency and every owned byte: the pin set equals the owned set and each pin is the exact Git blob."""
    root=Path(repo) if repo is not None else ROOT
    data=manifest(root,ref);pins=data.get('source_blobs',{})
    if set(pins) != OWNED_PATHS:return False
    try:
        _git(root,'merge-base','--is-ancestor',BASE,ref or 'HEAD')
        _git(root,'merge-base','--is-ancestor',INTEGRATION_MAIN,ref or 'HEAD')
        if any(_blob(_read(root,p,ref))!=expected for p,expected in INTEGRATED_DEPENDENCIES.items()):return False
        if any(_blob(_read(root,p,ref))!=expected for p,expected in pins.items()):return False
        # No extra native/source activation surface can be hidden in this cohort.
        return not any(p.startswith(('financial_engine/native_v10/','financial_engine/native_v11/')) for p in pins)
    except (OSError,ValueError,subprocess.CalledProcessError):return False


def allowed_path(path,repo=None,ref=None):
    pins=manifest(repo,ref).get('source_blobs',{})
    return (path in pins or path in INTEGRATED_DEPENDENCIES or path.startswith('docs/financial_validation/fin_v2_3/')
            or path=='FIN_V2_3_INTEGRATION_HANDOFF.md')


def _other_cohort_allows(path,root,ref):
    """A path owned by ANOTHER registered reviewed cohort (tests/fin_v2_cohorts.py) is that cohort's exact-blob responsibility."""
    try:
        from tests.fin_v2_cohorts import cohorts
    except ImportError:return False
    return any(m.__name__!=__name__ and m.allowed_path(path,root,ref) for m in cohorts())


def valid(repo=None,ref=None):
    root=Path(repo) if repo is not None else ROOT
    if not exact_blobs_ok(root,ref):return False
    pins=manifest(root,ref).get('source_blobs',{})
    try:
        # Compare with the accepted RC-M integration parent, not the historical F01 base.
        # Every changed path must match an exact cohort blob of this cohort or of another registered reviewed cohort.
        changed=_git(root,'diff','--name-only',INTEGRATION_MAIN,*([ref] if ref else []),'--').decode().splitlines()
        if any(not allowed_path(p,root,ref) and not _other_cohort_allows(p,root,ref) for p in changed):return False
        # Detect an untracked protected source as well as modifications/deletions.
        if ref is None:
            untracked=_git(root,'ls-files','--others','--exclude-standard','--',*PROTECTED).decode().splitlines()
            if any(p not in pins and not _other_cohort_allows(p,root,ref) for p in untracked):return False
        return True
    except (OSError,ValueError,subprocess.CalledProcessError):return False


def matches(path,source=None,*,repo=None,ref=None):
    pins=manifest(repo,ref).get('source_blobs',{})
    if path not in pins or not valid(repo,ref):return False
    if source is None:return True
    raw=source.encode() if isinstance(source,str) else source
    return _blob(raw)==pins[path]


def protected_blobs(repo=None,ref=None):
    if not valid(repo,ref):return {}
    return {p:b for p,b in manifest(repo,ref)['source_blobs'].items()
            if p.startswith(('financial_engine/','finco_core/','domain/'))}
