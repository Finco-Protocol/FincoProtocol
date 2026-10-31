"""Closed WF-04 exact-source cohort: two contractual DSCR inputs, Run-bound terms, strict EoD/covenant evaluation and the Debt Metrics workspace.

Authority: Financial Owner V3 decision and the unified WF-04 prompt section 0A (2026-10-29). Only this literal path set is admitted. No
financial_engine, finco_core, domain, CI, security, Save All, writer-route or signed-certificate path is added, and no merge/deployment
authority is created. Historical predecessor manifests stay verifiable: only the named re-pins below may differ from the approved main they were merged
with, and each one keeps its previous pin maps under ``historical_source_blobs`` (BASE = WF-04's historical origin, APPROVED_MAIN = main after the
merged WS-2 PR #397). Low-level checks never call the cohort registry.

Lineage: BASE is where WF-04 started; APPROVED_MAIN (main at the merge of PR #397, an ancestor of every WF-04 head from the post-#397 sync on) is
the parent this cohort's delta is judged against. The WS-2 editing/Save All bytes arrive from APPROVED_MAIN and are the WS-2 cohort's
responsibility (tests/fin_v2_wsv2_scope.py); WF-04 owns only what differs from APPROVED_MAIN.
"""
from pathlib import Path
import hashlib
import json
import subprocess

ROOT = Path(__file__).resolve().parents[1]
BASE = 'b76ac65c99e7fc9b486a557ae3c5ba9a711f50b3'
# PREVIOUS_APPROVED_MAIN: main at the merge of PR #397 (the lineage this cohort was approved against). APPROVED_MAIN: main at the merge of PR #401
# (CI V3 eight-worker routing, a CI-only successor whose bytes are owned by the CI/WS-2 cohorts); WF-04's delta is judged against it. Both layers are
# authenticated by ancestry + tree, and every predecessor manifest keeps its pin map for BOTH under ``historical_source_blobs``.
PREVIOUS_APPROVED_MAIN = '8a74fcb5cd57e470cf83a458bd165ea14ad394fb'
PREVIOUS_APPROVED_MAIN_TREE = 'a96566a21154fd8e673676c20bd2e4e093599330'
APPROVED_MAIN = '35848541f4d894f7e0a119ab8709276133d0da89'
APPROVED_MAIN_TREE = 'b2d001f934fa135ba7e501c8f63aca9d44ef2701'
# WF03_PARENT: main after the merged PR #399 (this cohort's own approved state); a later WF-03 successor may move only pins it owns and re-pins identically.
WF03_PARENT = 'db504f6408cb456c617c9342a1ffa202ee455283'
MANIFEST = 'docs/financial_validation/wf04_debt_metrics/SOURCE_SUCCESSOR.json'
SCHEMA = 'WF04_DEBT_METRICS_EXACT_SOURCE_V1'
# @@OWNED_PATHS_BEGIN@@
OWNED_PATHS = frozenset((
    '.github/workflows/protocol_ui_browser.yml',
    'app/persistence/workspace_repository.py',
    'app/v2/credit_decision_projection.py',
    'app/v2/debt_metrics_projection.py',
    'app/workbook/dscr_contract_terms.py',
    'app/workbook/registry.py',
    'docs/financial_validation/fin_v2_3/SOURCE_SUCCESSOR.json',
    'docs/financial_validation/fin_v2_r1/SOURCE_SUCCESSOR.json',
    'docs/financial_validation/finv2_d01_d02/SOURCE_SUCCESSOR.json',
    'docs/financial_validation/wf04_debt_metrics/CORRECTION_A_CI_AND_PERIOD_MATRIX.md',
    'docs/financial_validation/wf04_debt_metrics/INDEPENDENT_ORACLE_AND_PARITY.md',
    'docs/financial_validation/wf04_debt_metrics/OWNER_DECISION_AND_CONFLICT_REGISTER.md',
    'docs/financial_validation/wf04_debt_metrics/OWNER_PROTECTED_PATH_EXECUTION_LEDGER.md',
    'docs/financial_validation/wf04_debt_metrics/P00_VERIFIED_STATE.md',
    'docs/financial_validation/wf04_debt_metrics/POST_397_SYNC_AND_CORRECTION_B.md',
    'docs/financial_validation/wf04_debt_metrics/REVIEW_VERDICT.md',
    'docs/financial_validation/wf04_debt_metrics/TWO_DSCR_CONTRACT_MAPPING.md',
    'docs/financial_validation/wf04_debt_metrics/WF04_ACCEPTANCE_MATRIX.md',
    'docs/react_migration/wsv2_core/SOURCE_SUCCESSOR.json',
    'docs/react_migration/wsv2_editing/SOURCE_SUCCESSOR.json',
    'frontend/src/app/FinancialOverview.tsx',
    'frontend/src/app/FinancialResults.tsx',
    'frontend/src/app/credit/CreditDecisionPanel.tsx',
    'frontend/src/app/debtmetrics/CovenantTable.tsx',
    'frontend/src/app/debtmetrics/DebtMetricsWorkspace.tsx',
    'frontend/src/app/debtmetrics/DscrProfileChart.tsx',
    'frontend/src/app/debtmetrics/KpiRow.tsx',
    'frontend/src/app/debtmetrics/PeriodSchedule.tsx',
    'frontend/src/app/debtmetrics/PeriodStatusMatrix.tsx',
    'frontend/src/app/debtmetrics/ReservesPanel.tsx',
    'frontend/src/app/debtmetrics/__tests__/debtMetrics.test.mjs',
    'frontend/src/app/debtmetrics/__tests__/periodMatrix.test.mjs',
    'frontend/src/app/debtmetrics/api.ts',
    'frontend/src/app/debtmetrics/debtMetricsLink.ts',
    'frontend/src/app/debtmetrics/format.ts',
    'frontend/src/app/debtmetrics/types.ts',
    'frontend/src/app/financing/FinancingStudio.tsx',
    'frontend/src/app/workflow/WorkflowBar.tsx',
    'frontend/src/styles/rcm-debtmetrics.css',
    'static/react/finco-react.css',
    'static/react/finco-react.js',
    'tests/fin_v2_cohorts.py',
    'tests/model_react_rcm_financing_acceptance.py',
    'tests/model_react_wf04_debt_metrics_acceptance.py',
    'tests/test_fin_v2_3_scope.py',
    'tests/test_fin_v2_r1_scope.py',
    'tests/test_finval_f01_fixture_integrity.py',
    'tests/test_model_credit_decision_v3_real_runs.py',
    'tests/test_model_mutation_security_successor.py',
    'tests/test_model_react_insights_v1.py',
    'tests/test_model_workspace_consolidation_browser.py',
    'tests/test_model_workspace_productivity_v1.py',
    'tests/test_rcm_governance.py',
    'tests/test_rcux_governance.py',
    'tests/test_wf04_credit_debt_metrics.py',
    'tests/test_wf04_dscr_contract_terms.py',
    'tests/test_wf04_independent_oracle.py',
    'tests/test_wf04_period_matrix.py',
    'tests/test_wf04_run_bound_terms.py',
    'tests/test_wf04_save_all_integration.py',
    'tests/test_wf04_scope.py',
    'tests/test_wsv2_core_scope.py',
    'tests/wf04_scope.py',
    'tests/wsv2_core_scope.py',
    'tools/wf04_independent_dscr_oracle.py',
))
# @@OWNED_PATHS_END@@

FIN_V2_3_MANIFEST = 'docs/financial_validation/fin_v2_3/SOURCE_SUCCESSOR.json'
FIN_V2_R1_MANIFEST = 'docs/financial_validation/fin_v2_r1/SOURCE_SUCCESSOR.json'
FIN_V2_D01_MANIFEST = 'docs/financial_validation/finv2_d01_d02/SOURCE_SUCCESSOR.json'
WSV2_CORE_MANIFEST = 'docs/react_migration/wsv2_core/SOURCE_SUCCESSOR.json'
WSV2_EDITING_MANIFEST = 'docs/react_migration/wsv2_editing/SOURCE_SUCCESSOR.json'
# Predecessor manifests that WF-04 re-pins, and the exact pins each one may move (everything else must stay byte-for-byte what it was at APPROVED_MAIN).
PREDECESSOR_REPINS = {
    FIN_V2_3_MANIFEST: frozenset(('app/workbook/registry.py', 'tests/test_fin_v2_3_scope.py', 'tests/test_rcm_governance.py',
                                  'tests/test_model_mutation_security_successor.py', 'tests/test_model_workspace_productivity_v1.py',
                                  'tests/test_finval_f01_fixture_integrity.py')),
    FIN_V2_R1_MANIFEST: frozenset(('tests/fin_v2_cohorts.py', 'tests/test_fin_v2_r1_scope.py', 'tests/test_rcm_governance.py')),
    FIN_V2_D01_MANIFEST: frozenset(('tests/test_rcm_governance.py', 'tests/test_model_mutation_security_successor.py')),
    WSV2_CORE_MANIFEST: frozenset((
        'docs/financial_validation/fin_v2_3/SOURCE_SUCCESSOR.json',
        'docs/financial_validation/fin_v2_r1/SOURCE_SUCCESSOR.json',
        'docs/financial_validation/finv2_d01_d02/SOURCE_SUCCESSOR.json',
        'frontend/src/app/FinancialOverview.tsx',
        'frontend/src/app/FinancialResults.tsx',
        'frontend/src/app/workflow/WorkflowBar.tsx',
        'static/react/finco-react.css',
        'static/react/finco-react.js',
        'tests/fin_v2_cohorts.py',
        'tests/model_react_rcm_financing_acceptance.py',
        'tests/test_rcm_governance.py',
        'tests/test_model_mutation_security_successor.py',
        'tests/test_model_workspace_consolidation_browser.py',
        'tests/test_rcux_governance.py',
        'tests/test_wsv2_core_scope.py',
        'tests/wsv2_core_scope.py',
    )),
    # The WS-2 Save All manifest: the one pin WF-04's additive Run-identity hunk forces (the file is also owned and pinned by this cohort).
    WSV2_EDITING_MANIFEST: frozenset(('app/persistence/workspace_repository.py',)),
}
# The additive block WF-04 appends to the existing mandatory consolidation browser role (the bodies live in a non-collected helper, so no
# collection-time skip is added: CI V3 collection governance).
ROLE_MODULE = 'tests/test_model_workspace_consolidation_browser.py'
ROLE_ACCEPTANCE = 'tests/model_react_wf04_debt_metrics_acceptance.py'
ROLE_IMPORT_BLOCK = ['', '', '# WF-04 Debt Metrics: Owner-authorised mandatory acceptance; additive import only.',
                     'from tests.model_react_wf04_debt_metrics_acceptance import *  # noqa: E402,F401,F403']
# No financial, security, CI or writer namespace may ever be owned by this cohort. The ONE exception to the `.github/` prohibition is the single workflow
# below, and only for the Financial-Owner-approved timeout hunk (Correction C, 2026-10-29); every other `.github/` path stays forbidden.
FORBIDDEN_PREFIXES = ('financial_engine/', 'finco_core/', 'domain/', '.github/', 'frontend/src/app/editing/')
WORKFLOW_PATH = '.github/workflows/protocol_ui_browser.yml'
WORKFLOW_OLD_BLOB = '097a1e3cfb1677294b8a59116f6a46d5a3751fda'      # the exact bytes at APPROVED_MAIN
# The approved hunk, as exact literal replacements of the approved-main text: (1) outer job limit 45 -> 105 minutes; (2) a role-local inner pytest budget -
# 3600 s for the consolidation role ONLY, 1200 s (the unchanged global value) for the five other roles - announced before the role starts.
WORKFLOW_HUNK = (
    ('    timeout-minutes: 45\n', '    timeout-minutes: 105\n'),
    ('            echo "CI_BROWSER_ROLE_START=$role HEAD=$HEAD_SHA"\n            python -m tools.ci_browser_job "$role" --expected "$HEAD_SHA"\n',
     '            echo "CI_BROWSER_ROLE_START=$role HEAD=$HEAD_SHA"\n'
     '            if [ "$role" = "consolidation" ]; then\n'
     '              export FINCO_CI_PYTEST_BUDGET_S=3600\n'
     '            else\n'
     '              export FINCO_CI_PYTEST_BUDGET_S=1200\n'
     '            fi\n'
     '            echo "CI_BROWSER_ROLE_BUDGET role=$role seconds=$FINCO_CI_PYTEST_BUDGET_S"\n'
     '            python -m tools.ci_browser_job "$role" --expected "$HEAD_SHA"\n'),
)
FORBIDDEN_PATHS = frozenset((
    'main_web.py', 'app/v2/router.py', 'app/v2/grid_router.py', 'app/v2/react_workspace_router.py', 'app/v2/save_all_commands.py',
    'app/v2/mutation_csrf.py', 'app/workbook/update_service.py', 'app/workbook/bankability_config.py',
))


# The presentation paths the earlier WS1 layers pin as an exact state, and which WF-04 legitimately moves to a later exact state.
PRESENTATION_SUCCESSOR_PATHS = frozenset(('frontend/src/app/FinancialResults.tsx', 'static/react/finco-react.css', 'static/react/finco-react.js',
                                          'tests/test_model_workspace_consolidation_browser.py'))


def _git(root, *args):
    return subprocess.check_output(['git', *args], cwd=root, stderr=subprocess.DEVNULL)


def _read(root, path, ref):
    return (root / path).read_bytes() if ref is None else _git(root, 'show', ref + ':' + path)


def _blob(raw):
    return hashlib.sha1(b'blob ' + str(len(raw)).encode() + b'\0' + raw).hexdigest()


def _wf03(root, ref):
    """The separately registered WF-03 lifecycle successor (tests/wf03_lifecycle_scope.py), only while it is itself exact. Its pins are the ONLY
    later state this cohort follows; a missing, altered or invalid WF-03 cohort widens nothing."""
    try:
        from tests import wf03_lifecycle_scope as WF03
    except ImportError:
        return None
    return WF03 if WF03.exact_blobs_ok(root, ref) else None


def _wf06a(root, ref):
    """The separately registered closed WF-06A cohort (tests/fin_v2_wf06a_scope.py, PR #406, Owner Correction B), only while it is itself exact. Its
    check is low level (never calls this module); a missing, forged, newer or altered cohort widens nothing."""
    try:
        from tests import fin_v2_wf06a_scope as WF06A
    except ImportError:
        return None
    return WF06A if WF06A.exact_blobs_ok(root, ref) else None


def _downstream_allows(path, root, ref):
    WF03 = _wf03(root, ref)
    if WF03 is not None and WF03.allowed_path(path, root, ref):
        return True
    WF06A = _wf06a(root, ref)
    return WF06A is not None and WF06A.allowed_path(path, root, ref)


def _downstream_pin(path, value, root, ref):
    """True when WF-03 (exact) owns ``path`` and pins exactly ``value``, or the closed WF-06A cohort (exact) pins exactly ``value`` for a path it owns."""
    WF03 = _wf03(root, ref)
    if WF03 is not None and path in WF03.OWNED_PATHS and WF03.manifest(root, ref).get('source_blobs', {}).get(path) == value:
        return True
    WF06A = _wf06a(root, ref)
    return WF06A is not None and path in WF06A.OWNED_PATHS and WF06A.manifest(root, ref).get('source_blobs', {}).get(path) == value


def _own_manifest_follows_only_wf03(root, ref):
    """This cohort's own pin map equals its state at the merged PR #399 main except pins the exact WF-03 successor now owns and pins identically;
    the previous map is then preserved byte-for-byte under ``historical_source_blobs[WF03_PARENT]``."""
    old = json.loads(_read(root, MANIFEST, WF03_PARENT))
    now = json.loads(_read(root, MANIFEST, ref))
    before, after = old['source_blobs'], now['source_blobs']
    if set(before) != set(after):
        return False
    moved = [p for p in before if before[p] != after[p]]
    if not moved:
        return True
    if (now.get('historical_source_blobs') or {}).get(WF03_PARENT) != before:
        return False
    if any(now.get(k) != v for k, v in old.items() if k not in ('source_blobs', 'historical_source_blobs')):
        return False
    return all(_downstream_pin(p, after[p], root, ref) for p in moved)


def manifest(repo=None, ref=None):
    root = Path(repo) if repo is not None else ROOT
    try:
        data = json.loads(_read(root, MANIFEST, ref))
        return data if (isinstance(data, dict) and isinstance(data.get('source_blobs'), dict)
                        and data.get('schema_version') == SCHEMA and data.get('base') == BASE
                        and data.get('approved_main') == APPROVED_MAIN and data.get('approved_main_tree') == APPROVED_MAIN_TREE) else {}
    except (OSError, ValueError, subprocess.CalledProcessError):
        return {}


def _lineage_ok(root, ref):
    """BASE (WF-04's origin) and APPROVED_MAIN (main with the merged WS-2 PR) are both ancestors of the head, APPROVED_MAIN is a descendant of BASE, and
    the recorded tree really is APPROVED_MAIN's tree: a swapped, forged or unrelated 'approved main' cannot authenticate."""
    head = ref or 'HEAD'
    _git(root, 'merge-base', '--is-ancestor', BASE, head)
    _git(root, 'merge-base', '--is-ancestor', APPROVED_MAIN, head)
    _git(root, 'merge-base', '--is-ancestor', BASE, APPROVED_MAIN)
    _git(root, 'merge-base', '--is-ancestor', PREVIOUS_APPROVED_MAIN, head)
    _git(root, 'merge-base', '--is-ancestor', PREVIOUS_APPROVED_MAIN, APPROVED_MAIN)
    return (_git(root, 'rev-parse', APPROVED_MAIN + '^{tree}').decode().strip() == APPROVED_MAIN_TREE
            and _git(root, 'rev-parse', PREVIOUS_APPROVED_MAIN + '^{tree}').decode().strip() == PREVIOUS_APPROVED_MAIN_TREE)


def _historical_manifests_ok(root, ref):
    """Each predecessor manifest equals its APPROVED_MAIN self except the named re-pins. Its previous pin map at APPROVED_MAIN is preserved under
    ``historical_source_blobs[APPROVED_MAIN]`` and, where the manifest already existed, its WF-04-origin map under ``historical_source_blobs[BASE]``."""
    for path, allowed in PREDECESSOR_REPINS.items():
        old = json.loads(_read(root, path, APPROVED_MAIN))
        now = json.loads(_read(root, path, ref))
        if not isinstance(now, dict) or not isinstance(now.get('source_blobs'), dict):
            return False
        before, after = old['source_blobs'], now['source_blobs']
        history = now.get('historical_source_blobs')
        if not isinstance(history, dict) or history.get(APPROVED_MAIN) != before:
            return False
        try:
            origin = json.loads(_read(root, path, BASE))['source_blobs']
        except subprocess.CalledProcessError:
            origin = None                                          # the manifest was introduced after BASE (WS-2): no WF-04-origin map exists
        if origin is not None and history.get(BASE) != origin:
            return False
        if any(history.get(k) != v for k, v in (old.get('historical_source_blobs') or {}).items()):
            return False
        try:
            previous = json.loads(_read(root, path, PREVIOUS_APPROVED_MAIN))['source_blobs']
        except subprocess.CalledProcessError:
            previous = None
        if previous is not None and history.get(PREVIOUS_APPROVED_MAIN) != previous:
            return False                                          # the pre-#401 approved-main pin map must survive byte-for-byte
        if set(before) != set(after):
            return False
        if any(before[p] != after[p] and p not in allowed and not _downstream_pin(p, after[p], root, ref) for p in before):
            return False
        if any(now.get(k) != v for k, v in old.items() if k not in ('source_blobs', 'historical_source_blobs')):
            return False
    return True


def _owned_ok():
    return (not any((p.startswith(FORBIDDEN_PREFIXES) and p != WORKFLOW_PATH) or p in FORBIDDEN_PATHS for p in OWNED_PATHS)
            and all(p == MANIFEST or '..' not in p.split('/') for p in OWNED_PATHS))


def _workflow_hunk_ok(root, ref):
    """The approved-main workflow with exactly the approved hunk applied equals the current bytes; the old blob is the approved-main blob; any other
    byte (permissions, triggers, pinned actions, checkout SHA, role list, verification steps, a second budget change) fails closed."""
    old = _read(root, WORKFLOW_PATH, APPROVED_MAIN)
    if _blob(old) != WORKFLOW_OLD_BLOB:
        return False
    text = old.decode()
    for before, after in WORKFLOW_HUNK:
        if text.count(before) != 1:
            return False
        text = text.replace(before, after, 1)
    return _read(root, WORKFLOW_PATH, ref) == text.encode()


# F01/Browser attestations write untracked proof into evidence/ before the full acceptance suite; non-executable evidence is not source.
_CI_EVIDENCE_EXTENSIONS = ('.json', '.xml', '.png', '.webp', '.jpg', '.jpeg', '.txt', '.csv', '.svg', '.html', '.zip')


def _ci_evidence_only(path):
    return path.startswith('evidence/') and path.endswith(_CI_EVIDENCE_EXTENSIONS)


def exact_blobs_ok(repo=None, ref=None):
    try:
        from tests import wf03_lifecycle_scope as WF03
    except ImportError:
        return _exact_blobs_ok(repo, ref)
    try:
        from tests import fin_v2_wf06a_scope as WF06A
    except ImportError:
        with WF03.scoped():
            return _exact_blobs_ok(repo, ref)
    with WF03.scoped(), WF06A.scoped():        # the exact WF-03 / WF-06A checks run once per call, not once per changed path
        return _exact_blobs_ok(repo, ref)


def _exact_blobs_ok(repo=None, ref=None):
    root = Path(repo) if repo is not None else ROOT
    pins = manifest(root, ref).get('source_blobs', {})
    if set(pins) != OWNED_PATHS or not _owned_ok():
        return False
    try:
        if not _lineage_ok(root, ref):
            return False
        if any(_blob(_read(root, p, ref)) != b for p, b in pins.items()):
            return False
        if not _historical_manifests_ok(root, ref) or not _workflow_hunk_ok(root, ref):
            return False
        changed = _git(root, 'diff', '--name-only', APPROVED_MAIN, *([ref] if ref else []), '--').decode().splitlines()
        if any(p not in OWNED_PATHS and p != MANIFEST and not _downstream_allows(p, root, ref) for p in changed):
            return False
        if not _own_manifest_follows_only_wf03(root, ref):
            return False
        if ref is None:
            untracked = _git(root, 'ls-files', '--others', '--exclude-standard').decode().splitlines()
            if any(p not in OWNED_PATHS and p != MANIFEST and not _ci_evidence_only(p) and not _downstream_allows(p, root, ref) for p in untracked):
                return False
        return True
    except (OSError, ValueError, KeyError, TypeError, subprocess.CalledProcessError):
        return False


def allowed_path(path, repo=None, ref=None):
    return path in OWNED_PATHS or path == MANIFEST


def valid(repo=None, ref=None):
    from tests.fin_v2_cohorts import valid as composite_valid
    return exact_blobs_ok(repo, ref) and composite_valid(repo, ref)


def matches(path, source=None, *, repo=None, ref=None):
    pins = manifest(repo, ref).get('source_blobs', {})
    if path not in pins or not valid(repo, ref):
        return False
    raw = source.encode() if isinstance(source, str) else source
    return source is None or _blob(raw) == pins[path]


def presentation_successor(path, source, *, repo=None, ref=None):
    """True only for one of the three presentation paths, at exactly the WF-04 pinned bytes, while the whole cohort is valid."""
    return path in PRESENTATION_SUCCESSOR_PATHS and matches(path, source, repo=repo, ref=ref)


def protected_blobs(repo=None, ref=None):
    return {}  # Never admit a financial_engine, finco_core or domain source.
