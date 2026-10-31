"""Closed WF03 exact-source successor; no financial/native namespace authority.

The reviewed parent is the actual #397 merge, not the old Phase A snapshot.
Historical manifests remain available by ancestry and literal historical maps.
Low-level checks never call the composite registry (no circular validity).
"""
from pathlib import Path
import hashlib
import json
import subprocess
from contextlib import contextmanager
from functools import lru_cache

ROOT=Path(__file__).resolve().parents[1]
BASE='8a74fcb5cd57e470cf83a458bd165ea14ad394fb'
BASE_TREE='a96566a21154fd8e673676c20bd2e4e093599330'
# PARENT: main after the merged PR #401 (CI V3 eight-worker) and PR #399 (WF-04), the parent this cohort's delta is now judged against. BASE (main
# at the merge of PR #397) keeps its historical proofs; PARENT adds one more authenticated layer on top of them. Both are checked by ancestry + tree.
PARENT='db504f6408cb456c617c9342a1ffa202ee455283'
PARENT_TREE='9b96717bae39a4dbb496879c7e6c028e675492d3'
MANIFEST='docs/react_migration/wf03_project_lifecycle/SOURCE_SUCCESSOR.json'
SCHEMA='WF03_LIFECYCLE_EXACT_SOURCE_V1'
OWNED_PATHS=frozenset((
    'app/demo_cleanup.py', 'app/library/router.py',
    'app/persistence/acquisition_repository.py', 'app/persistence/db.py',
    'app/persistence/project_lifecycle_repository.py', 'app/persistence/projects_repository.py',
    'app/persistence/records.py', 'app/persistence/setup_draft_repository.py',
    'app/persistence/workspace_repository.py',
    'app/services/blank_readiness_service.py', 'app/services/project_lifecycle_service.py',
    'app/services/run_service.py', 'app/services/save_run_service.py',
    'app/trust_readiness/registry.py', 'app/v2/react_new_project.py', 'app/v2/react_projects.py',
    'app/v2/react_workspace_router.py', 'app/v2/router.py', 'main_web.py',
    'frontend/src/app/LibraryView.tsx', 'frontend/src/app/WorkspaceView.tsx',
    'frontend/src/app/library/api.ts', 'frontend/src/app/library/types.ts',
    'frontend/src/app/newProject/NewProjectWizard.tsx',
    'static/react/finco-react.js', 'static/react/finco-react.css',
    'tests/fin_v2_cohorts.py', 'tests/model_mutation_security_successor.py',
    'tests/test_fin_v2_3_scope.py', 'tests/test_fin_v2_r1_scope.py',
    'tests/test_rcux_governance.py', 'tests/test_trust_readiness_registry.py',
    'tests/test_trust_readiness_controls.py', 'tests/test_model_workspace_consolidation_browser.py',
    'tests/test_project_lifecycle.py', 'tests/test_project_lifecycle_browser.py',
    'tests/model_react_rcux_product_acceptance.py',
    'tests/test_true_blank_readiness.py', 'tests/test_setup_draft_promotion.py',
    'tests/wf03_lifecycle_scope.py', 'tests/test_wf03_lifecycle_scope.py',
    # Three additional predecessor-consumer paths explicitly approved in chat.
    'tests/wsv2_core_scope.py', 'tools/ci_v3_production.py', 'tests/test_ci_v3_outcome_reconciliation.py',
    'docs/financial_validation/wf04_debt_metrics/SOURCE_SUCCESSOR.json',   # post-#399: WF-04's own pin map follows only the exact WF-03 pins
    # Post-merge fixture layer: tests that predate the WF-03 fences set up archived/foreign-owner state through the REAL lifecycle transition or the
    # scoped fixture-only forgery seam (tests/wf03_fixture_seams.py); every assertion and negative is unchanged unless the ledger says otherwise.
    'tests/test_model_insight_q3_scenario_reads.py',
    'tests/test_model_react_rcux_projects_v1.py',
    'tests/test_model_v2_metadata.py',
    'tests/test_portfolio_monitoring_real_runs.py',
    'tests/test_rc7b_quarterly_csrf_successor.py',
    'tests/test_sc34_effective_revenue_inputs.py',
    'tests/test_sc34_project_identity.py',
    'tests/test_wf07_revenue_workspace.py',
    'tests/test_m6_lifecycle_boundary.py',
    'tests/test_wsv2_core_scope.py',
    'tests/test_finv2_d01_governance.py',
    'frontend/src/app/workflow/PPAEditorView.tsx',   # PPA Save waits for a current revenue projection (stale-identity 409 under load)
    'tests/wf03_fixture_seams.py',
    # Owner-approved RCM adapter CSRF successor (PR #400 final correction): finite successor for app/v2/react_new_project.py (4 reviewed mutations, 2 validators, 1 ownership read)
    'tests/rcm_adapter_csrf_successor.py', 'tests/test_rcm_adapter_csrf_successor.py',
    # FIN-TRUTH-A (PR #402): ON-05 KPI/credit numerical-truth correction, six reviewed paths; no solver/engine/formula change
    'app/services/lender_case_service.py', 'app/services/rate_shock.py', 'app/services/sensitivity_service.py', 'app/templates/partials/credit_summary.html', 'app/templates/partials/scenario_sensitivity.html', 'tests/test_on05_numerical_truth.py',
    # D-029 executor-kill regression made deterministic (hold point inside the real worker; no production code, no weakened assertion)
    'tests/d029_executor_hold.py', 'tests/test_p0b_executor_recovery_d029.py',
    # PR #405 Correction A: bounded retry of transient GitHub API 5xx in the hosted transport (CI-only; no auth/origin/redirect/identity change)
    'tools/ci_v3_hosted_transport.py', 'tests/test_ci_v3_hosted_transport_retry.py',
    # Owner-directed 2x CI timeouts (Correction E): CI-only limits + the CI-340M workflow successor chain; no semantics, no coverage change
    '.github/workflows/ci_public_job.yml', '.github/workflows/ci_v3_required_job.yml', '.github/workflows/public_safety_and_smoke.yml', 'tests/test_ci_v3_production.py', 'tests/test_rc3_integration_inventory.py', 'tests/test_rc5_ci_successor_governance.py', 'tools/ci_v3_container.py',
    # Owner-authorized CI artifact run-attempt integrity repair (PR #400 incident, run 41099667692): attempt-scoped artifact identity end to end,
    # plus the RC-3 inventory test following the CI-340M chain like the RC-5 one (Correction F pattern). No .github/ path beyond the three above.
    'tools/ci_v3_source_reference.py',
    # Financial Owner approval 2026-10-30 (three finite exact-pin successors): the D-029 browser-identity and RC-M governance tests admit only the exact
    # WF-03 browser names / router blob; tests/test_rcux_governance.py (already owned) admits only the three exact WF-03 CI workflow pins.
    'tests/test_model_mutation_security_successor.py', 'tests/test_rcm_governance.py',
    # Post-#400 performance layer (Financial Owner approval 2026-10-30, separate Draft PR): WS-2 exact check memoised once per outer call + its evidence docs.
    'docs/ci_v3/incidents/pr400_performance/ROOT_CAUSE.md', 'docs/ci_v3/incidents/pr400_performance/TIMING_LEDGER.md',
    'docs/ci_v3/incidents/pr400_performance/FIX_AND_VALIDATION.md',
    'docs/ci_v3/incidents/pr400_artifact_attempt/ROOT_CAUSE.md',
    'docs/ci_v3/incidents/pr400_artifact_attempt/CHANGE_LEDGER.md',
    'docs/ci_v3/incidents/pr400_artifact_attempt/TEST_EVIDENCE.md',
    'tests/test_demo_history_retention.py',
    'tests/model_react_wsv2_acceptance.py',   # WS-1 acceptance: blank-path disclosure updated to the approved WF-03 non-runnable setup-draft contract
    'tests/test_ci_v3_reference_admission_successor.py',   # D-029 successor unit fixture supplies the WF-03 State C evidence nodes
    'tests/test_wf04_scope.py',   # post-#399: WF-04's own delta assertions are evaluated at the merged #399 commit
    'tests/wf04_scope.py',     # post-#399 successor: the WF-04 cohort follows only the exact WF-03 pins (tests/wf04_scope.py _downstream_* helpers)
    'docs/readiness/02_data_handling.md', 'docs/readiness/06_retention_and_deletion.md',
    'docs/financial_validation/fin_v2_3/SOURCE_SUCCESSOR.json',
    'docs/financial_validation/finv2_d01_d02/SOURCE_SUCCESSOR.json',
    'docs/financial_validation/fin_v2_r1/SOURCE_SUCCESSOR.json',
    'docs/react_migration/rc_ux_completion/SOURCE_SUCCESSOR.json',
    'docs/react_migration/wsv2_core/SOURCE_SUCCESSOR.json',
    'docs/react_migration/wsv2_editing/SOURCE_SUCCESSOR.json',
))
# ON-07 research layer (PR #403): research evidence ONLY, never financial authority. Closed literal list, exact blob pins in the manifest, two directories.
RESEARCH_PATHS=frozenset((
    'research/on07_baseline_post399/IMPLEMENTATION_GAP_SHORTLIST.md',
    'research/on07_baseline_post399/POST400_LIVE_PARITY_RUNBOOK.md',
    'research/on07_baseline_post399/README_FIRST.md',
    'research/on07_baseline_post399/U07_U08_FINDINGS.md',
    'research/on07_baseline_post399/WF04_VERIFICATION.md',
    'research/on07_baseline_post399/harness/analyze_captures.py',
    'research/on07_baseline_post399/harness/binding_probe.py',
    'research/on07_baseline_post399/harness/build_fixture_binding_audit.py',
    'research/on07_baseline_post399/harness/diagnose_refusal.py',
    'research/on07_baseline_post399/harness/on07_common.py',
    'research/on07_baseline_post399/harness/run_on07_workbook.py',
    'research/on07_correction_a/COST_LINE_ALLOCATION_LEDGER.csv',
    'research/on07_correction_a/FIXTURE_RUNS_AND_IDENTITIES.csv',
    'research/on07_correction_a/GOVERNANCE_DISPOSITION.md',
    'research/on07_correction_a/INPUTS_AND_PROVENANCE.md',
    'research/on07_correction_a/ON07_LOCAL_BASELINE_TRUE_ROUTE.csv',
    'research/on07_correction_a/ON07_PACKAGE_FILE_HASHES.md',
    'research/on07_correction_a/ORIGINAL_VS_REVISED_FIXTURE_DIFF.csv',
    'research/on07_correction_a/OUTPUT_EXPOSURE_REGISTER.csv',
    'research/on07_correction_a/OWNER_DECISION_REGISTER.md',
    'research/on07_correction_a/README_FIRST.md',
    'research/on07_correction_a/REPRODUCIBILITY_3_FRESH_DBS.csv',
    'research/on07_correction_a/SHA256SUMS.txt',
    'research/on07_correction_a/SOURCE_GOVERNANCE_DECISION.md',
    'research/on07_correction_a/TRUE_ROUTE_INPUT_LEDGER.csv',
    'research/on07_correction_a/WND02_SHL_MATURITY_FORENSICS.md',
    'research/on07_correction_a/captures/synthetic_variant_b_prior/SOL-01.json',
    'research/on07_correction_a/captures/synthetic_variant_b_prior/SOL-02.json',
    'research/on07_correction_a/captures/synthetic_variant_b_prior/WND-01.json',
    'research/on07_correction_a/captures/synthetic_variant_b_prior/WND-02.json',
    'research/on07_correction_a/captures/user_created_core_run/tr1_SOL-01.json',
    'research/on07_correction_a/captures/user_created_core_run/tr1_SOL-02.json',
    'research/on07_correction_a/captures/user_created_core_run/tr1_WND-01.json',
    'research/on07_correction_a/captures/user_created_core_run/tr1_WND-02.json',
    'research/on07_correction_a/captures/user_created_core_run/wr1_WND-02.json',
    'research/on07_correction_a/governance_probe/FAILING_ON_UNMODIFIED_MAIN_LOCAL_ENV.txt',
    'research/on07_correction_a/governance_probe/NEWLY_FAILING_AFTER_ONE_HARMLESS_FILE.txt',
    'research/on07_correction_a/governance_probe/cohort_probe.py',
    'research/on07_correction_a/governance_probe/guard_probe.py',
    'research/on07_correction_a/harness/analyze_ca.py',
    'research/on07_correction_a/harness/analyze_captures.py',
    'research/on07_correction_a/harness/build_handover.py',
    'research/on07_correction_a/harness/integrity_verdicts.py',
    'research/on07_correction_a/harness/on07_common.py',
    'research/on07_correction_a/harness/p90_probe.py',
    'research/on07_correction_a/harness/run_on07_workbook_helpers.py',
    'research/on07_correction_a/harness/shl_forensics.py',
    'research/on07_correction_a/harness/true_route.py',
    'research/on07_correction_a/harness/wnd02_levers.py',
    'research/on07_correction_a/harness/wnd02_rederived_diag.py',
    'research/on07_correction_a/harness/wnd_minimal_repro.py',
    'research/on07_correction_a/isolated_revised_copies/ON07_CHECKLIST_AUDIT.csv',
    'research/on07_correction_a/isolated_revised_copies/ON07_CHECKLIST_AUDIT.md',
    'research/on07_correction_a/isolated_revised_copies/ON07_FIELD_MAPPING_REVISED.csv',
    'research/on07_correction_a/isolated_revised_copies/ON07_GAP_REGISTER_UPDATED_PRIOR.md',
    'research/on07_correction_a/isolated_revised_copies/ON07_OUTPUT_COMPARISON_TEMPLATE_REVISED.csv',
    'research/on07_correction_a/isolated_revised_copies/ON07_PROJECT_FIXTURES_REVISED.csv',
    'research/on07_correction_a/isolated_revised_copies/ON07_RUNBOOK_REVISED.md',
    'research/on07_correction_a/isolated_revised_copies/ON07_UNVERIFIED_ASSUMPTIONS_REVISED.md',
    'research/on07_correction_a/probes/integrity_verdicts.json',
    'research/on07_correction_a/probes/min_solar.json',
    'research/on07_correction_a/probes/min_wind.json',
    'research/on07_correction_a/probes/p90_probe.json',
    'research/on07_correction_a/probes/shl_e1.json',
    'research/on07_correction_a/probes/wnd02_levers.json',
    'research/on07_correction_a/probes/wnd02_rederived.json',
))
# FIN-TRUTH-B1: literal source/test/document layer; no additional financial authority.
B1_BASE='ebf1f15113ec95d69d29e8aa4e4635686dd1f39a'
B1_MANIFEST='docs/financial_validation/fin_truth_b1/SOURCE_SUCCESSOR.json'
B1_PATHS=frozenset((
    B1_MANIFEST,
    'tests/fin_truth_b1/test_sensitivity_source.py',
    'tests/fin_truth_b1/test_source_successor.py',
    'docs/financial_validation/fin_truth_b1/README.md',
))
B1_REPINS=frozenset((
    'main_web.py', 'app/services/sensitivity_service.py', 'tests/wf03_lifecycle_scope.py',
    'docs/financial_validation/finv2_d01_d02/SOURCE_SUCCESSOR.json',
    'docs/react_migration/wsv2_core/SOURCE_SUCCESSOR.json',
    'docs/financial_validation/wf04_debt_metrics/SOURCE_SUCCESSOR.json',
))
OWNED_PATHS=OWNED_PATHS|B1_PATHS


RESEARCH_DIRECTORIES=('research/on07_baseline_post399/','research/on07_correction_a/')
assert all(p.startswith(RESEARCH_DIRECTORIES) for p in RESEARCH_PATHS)
OWNED_PATHS=OWNED_PATHS|RESEARCH_PATHS
WF04_MANIFEST='docs/financial_validation/wf04_debt_metrics/SOURCE_SUCCESSOR.json'   # introduced after BASE: pinned by blob, no BASE-layer history
PREDECESSOR_MANIFESTS=tuple(sorted(p for p in OWNED_PATHS if p.endswith('/SOURCE_SUCCESSOR.json') and p not in {WF04_MANIFEST,B1_MANIFEST}))
D029_APPROVED_PATHS=frozenset({'app/persistence/workspace_repository.py'})
# The ONLY workflow files this cohort may own: the Owner-directed 2x timeout successor (Correction E). Any other .github/ path stays unowned.
CI_TIMEOUT_WORKFLOWS=frozenset({'.github/workflows/ci_public_job.yml','.github/workflows/ci_v3_required_job.yml','.github/workflows/public_safety_and_smoke.yml'})
CSRF_PATHS=frozenset({'app/services/project_lifecycle_service.py','app/v2/react_new_project.py'})


def _git(root,*args):
    return subprocess.check_output(['git',*args],cwd=root,stderr=subprocess.DEVNULL)


def _read(root,path,ref):
    if ref is None: return (root/path).read_bytes()
    if len(ref)==40 and all(c in '0123456789abcdef' for c in ref):
        return _immutable_git_bytes(root,path,ref,_git)
    return _git(root,'show',ref+':'+path)


@lru_cache(maxsize=512)
def _immutable_git_bytes(root,path,ref,git_reader):
    return git_reader(root,'show',ref+':'+path)


def _blob(raw):
    return hashlib.sha1(b'blob '+str(len(raw)).encode()+b'\0'+raw).hexdigest()


@lru_cache(maxsize=128)
def _baseline_bytes(root,path,base,reader,git_reader):
    # Immutable Git objects only. Never cache current source/manifest bytes.
    # Function identities are keys so injected read/ancestry negatives cannot
    # accidentally reuse an earlier proof.
    return reader(root,path,base)


def manifest(repo=None,ref=None):
    root=Path(repo) if repo is not None else ROOT
    try:
        data=json.loads(_read(root,MANIFEST,ref))
        return data if (data.get('schema_version')==SCHEMA and data.get('base')==BASE
                        and data.get('parent')==PARENT and data.get('parent_tree')==PARENT_TREE) else {}
    except (OSError,ValueError,subprocess.CalledProcessError):
        return {}


def _b1_layer_ok(root, ref, pins, data):
    """Preserve the complete pre-B1 layer and admit only this finite transition."""
    old=json.loads(_baseline_bytes(root, MANIFEST, B1_BASE, _read, _git))
    seal=json.loads(_read(root, B1_MANIFEST, ref))
    if seal.get('schema_version')!='FIN_TRUTH_B1_EXACT_SOURCE_V1' or seal.get('base')!=B1_BASE:
        return False
    if seal.get('historical_source_blobs')!={B1_BASE:old['source_blobs']}:
        return False
    if set(pins)!=set(old['source_blobs'])|B1_PATHS:
        return False
    if any(pins[p]!=value and p not in B1_REPINS for p,value in old['source_blobs'].items()):
        return False
    if any(data.get(k)!=v for k,v in old.items() if k not in ('source_blobs','path_ledger')):
        return False
    ledger=data.get('path_ledger',[])
    previous=old['path_ledger']
    additions=ledger[len(previous):]
    delta=B1_REPINS|B1_PATHS
    if (ledger[:len(previous)]!=previous or len(additions)!=len(delta)
            or {row.get('path') for row in additions}!=delta):
        return False
    if any(row.get('before_blob')!=old['source_blobs'].get(row['path'])
           or row.get('after_blob')!=pins[row['path']] for row in additions):
        return False
    expected=(B1_PATHS-{B1_MANIFEST})|{'main_web.py','app/services/sensitivity_service.py'}
    reviewed=seal.get('source_blobs',{})
    return set(reviewed)==expected and all(pins.get(p)==v for p,v in reviewed.items())


def _historical_maps_ok(root,ref,pins,data):
    expected=data.get('predecessor_manifests',{})
    if set(expected)!=set(PREDECESSOR_MANIFESTS): return False
    for path in PREDECESSOR_MANIFESTS:
        # Layer 1 (unchanged proof): the pin map at BASE (main at the merge of PR #397) survives byte-for-byte under history[BASE].
        base_old=json.loads(_baseline_bytes(root,path,BASE,_read,_git))
        # Layer 2: the predecessor manifest at PARENT (main after PR #401 + PR #399). Its blob is recorded in this manifest.
        raw=_baseline_bytes(root,path,PARENT,_read,_git)
        if _blob(raw)!=expected[path]: return False
        old=json.loads(raw); current=json.loads(_read(root,path,ref))
        before=old['source_blobs']; after=current['source_blobs']
        if set(before)!=set(after): return False
        history=current.get('historical_source_blobs',{})
        if history.get(BASE)!=base_old['source_blobs']: return False
        if history.get(PARENT)!=before: return False
        old_history=old.get('historical_source_blobs',{})
        if set(history)!=set(old_history)|{BASE,PARENT}: return False
        if any(history.get(k)!=v for k,v in old_history.items()): return False
        if any(current.get(k)!=v for k,v in old.items() if k not in ('source_blobs','historical_source_blobs')): return False
        if set(current)!=set(old)|{'historical_source_blobs'} and set(current)!=set(old): return False
        for source,value in before.items():
            if after[source]!=value and (source not in OWNED_PATHS or after[source]!=pins[source]): return False
    return True


_SCOPE=[]   # call-scope memo stack: see scoped()


@contextmanager
def scoped():
    """Within ONE outer governance call (single-threaded, no file is written meanwhile) the result of ``exact_blobs_ok(root, ref)`` is computed once
    instead of once per changed path. The memo lives only for that call: it is dropped on exit, never keeps bytes, and is never shared between calls."""
    _SCOPE.append({})
    try:
        yield
    finally:
        _SCOPE.pop()


def exact_blobs_ok(repo=None,ref=None):
    if not _SCOPE: return _exact_blobs_ok(repo,ref)
    key=(str(repo if repo is not None else ROOT),ref)
    memo=_SCOPE[-1]
    if key not in memo: memo[key]=_exact_blobs_ok(repo,ref)
    return memo[key]


def _exact_blobs_ok(repo=None,ref=None):
    root=Path(repo) if repo is not None else ROOT
    data=manifest(root,ref); pins=data.get('source_blobs',{})
    if set(pins)!=OWNED_PATHS: return False
    try:
        _git(root,'merge-base','--is-ancestor',BASE,ref or 'HEAD')
        if _git(root,'rev-parse',BASE+'^{tree}').decode().strip()!=BASE_TREE: return False
        _git(root,'merge-base','--is-ancestor',PARENT,ref or 'HEAD')
        _git(root,'merge-base','--is-ancestor',BASE,PARENT)
        if _git(root,'rev-parse',PARENT+'^{tree}').decode().strip()!=PARENT_TREE: return False
        if any(_blob(_read(root,p,ref))!=sha for p,sha in pins.items()): return False
        return _historical_maps_ok(root,ref,pins,data) and _b1_layer_ok(root,ref,pins,data)
    except (OSError,ValueError,KeyError,TypeError,subprocess.CalledProcessError):
        return False


def allowed_path(path,repo=None,ref=None):
    return path in OWNED_PATHS or path==MANIFEST


def valid(repo=None,ref=None):
    root=Path(repo) if repo is not None else ROOT
    if not exact_blobs_ok(root,ref): return False
    try:
        changed=_git(root,'diff','--name-only',PARENT,*([ref] if ref else []),'--').decode().splitlines()
        if any(not allowed_path(p) for p in changed): return False
        if ref is None:
            untracked=_git(root,'ls-files','--others','--exclude-standard').decode().splitlines()
            if any(not allowed_path(p) for p in untracked): return False
        return True
    except (OSError,ValueError,subprocess.CalledProcessError): return False


def matches(path,source=None,*,repo=None,ref=None):
    pins=manifest(repo,ref).get('source_blobs',{})
    if path not in pins or not valid(repo,ref): return False
    raw=source.encode('utf-8') if isinstance(source,str) else source
    return raw is None or _blob(raw)==pins[path]


def historical_pin_successor(manifest_path,path,before,after,repo=None,ref=None):
    if manifest_path not in PREDECESSOR_MANIFESTS or path not in OWNED_PATHS: return False
    root=Path(repo) if repo is not None else ROOT
    try:
        old=json.loads(_read(root,manifest_path,'c848a979b3322c53d02631a5f5897180fae9c1e3'))
        return (old['source_blobs'].get(path)==before and manifest(repo,ref).get('source_blobs',{}).get(path)==after
                and exact_blobs_ok(root,ref))
    except (OSError,ValueError,KeyError,subprocess.CalledProcessError): return False


def protected_blobs(repo=None,ref=None):
    return {}  # No financial_engine/, finco_core/, domain/, native or CI workflow authority.


def trust_registry_successor(original,current):
    """Exact append-only successor of actual merged WS2, plus old-chain proof."""
    import difflib
    path='app/trust_readiness/registry.py'
    text=current if current.endswith('\n') else current+'\n'  # git helper historically strips its final newline
    if not matches(path,text): return False
    try:
        parent=_read(ROOT,path,BASE).decode('utf-8')
        removed=[line for line in difflib.unified_diff(parent.splitlines(),text.splitlines())
                 if line.startswith('-') and not line.startswith('---')]
        if removed: return False
        # Transformations and original constants are unchanged, exact-pinned
        # historical proofs; this does not recognize arbitrary "old text".
        from tests import test_trust_readiness_registry as T
        demo=T._git('show',f'{T.DEMO_RETENTION_BASE}:{path}')
        rc1=T._git('show',f'{T.RC1_BASE_MAIN}:{path}')
        old_chain=T._f4_csrf_registry(T._demo_retention_registry(demo))
        allowed=(parent,rc1,old_chain,T._git('cat-file','blob',T.D029_TRUST_REGISTRY_BLOB),
                 T._git('cat-file','blob',T.WS2_TRUST_REGISTRY_BLOB))
        return original.strip() in {old.strip() for old in allowed}
    except (OSError,ValueError,KeyError,subprocess.CalledProcessError): return False


CI_TRUST_PATHS=('app/trust_readiness/registry.py','docs/readiness/02_data_handling.md',
                'docs/readiness/06_retention_and_deletion.md','tests/test_trust_readiness_controls.py',
                'tests/test_trust_readiness_registry.py')
CI_EVIDENCE_NODES=(
    'tests/test_wf03_lifecycle_scope.py::test_complete_closed_successor_and_unchanged_historical_maps',
    'tests/test_wf03_lifecycle_scope.py::test_trust_successor_preserves_the_actual_ws2_parent_byte_content',
    'tests/test_ci_v3_outcome_reconciliation.py::test_wf03_ci_state_rejects_mixed_blobs_and_missing_same_run_evidence',
)


def ci_source_facts():
    try:
        head=_git(ROOT,'rev-parse','HEAD').decode().strip()
        if not exact_blobs_ok(ref=head): return None
        return {'schema':SCHEMA,'base':BASE,'base_tree':BASE_TREE,
                'current_blobs':{p:_git(ROOT,'rev-parse','HEAD:'+p).decode().strip() for p in CI_TRUST_PATHS},
                'parent_blobs':{p:_git(ROOT,'rev-parse',BASE+':'+p).decode().strip() for p in CI_TRUST_PATHS},
                'manifest_blob':_git(ROOT,'rev-parse','HEAD:'+MANIFEST).decode().strip()}
    except (OSError,ValueError,subprocess.CalledProcessError): return None


def accepts_ci_trust_state(facts,phases,native):
    proposed=facts.get('wf03_state')
    if not proposed: return False
    actual=ci_source_facts()
    if actual is None or proposed!=actual: return False
    from tools import ci_v3_production as P
    pins=actual['current_blobs']
    expected={p:pins[p] for p in (*P.D029_BLOBS,*P.D029_TRUST_CHANGED_BLOBS)}
    if facts.get('blobs')!=expected: return False
    if facts.get('ws2_extra_blobs')!={p:pins[p] for p in P.WS2_TRUST_EXTRA_BLOBS}: return False
    if facts.get('record_blob')!=P.WS2_RECORD_BLOB or facts.get('ws2_receipt')!=P.ws2_expected_receipt(): return False
    if facts.get('ws2_manifest_pins')!={p:pins[p] for p in (*P.WS2_TRUST_BLOBS,*P.WS2_TRUST_EXTRA_BLOBS)}: return False
    parent={**P.WS2_TRUST_BLOBS,**P.WS2_TRUST_EXTRA_BLOBS,**P.D029_TRUST_CHANGED_BLOBS}
    if actual['parent_blobs']!=parent: return False
    for node in CI_EVIDENCE_NODES:
        event=phases.get(node)
        if (not event or [(p.get('when'),p.get('outcome'),p.get('wasxfail')) for p in event]
                !=[('setup','passed',None),('call','passed',None),('teardown','passed',None)]
                or tuple(native.get(node,('missing',)))[0]!='passed'): return False
    return True
