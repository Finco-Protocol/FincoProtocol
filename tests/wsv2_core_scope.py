"""Closed WS1 exact-source successor, Financial Owner approved section A at c848a979.

Only this literal path set is admitted. No writer, financial, CSRF, Run-integrity,
WS2 or workflow authority is added. Historical manifests/presentation layers remain
verifiable at AUTHORIZATION_HEAD. Low-level checks never call the cohort registry.
"""
from pathlib import Path
import hashlib
import json
import subprocess

ROOT = Path(__file__).resolve().parents[1]
BASE = 'b1a58681e41af9f1b4d52b176f0001725720b15c'
AUTHORIZATION_HEAD = 'c848a979b3322c53d02631a5f5897180fae9c1e3'
MANIFEST = 'docs/react_migration/wsv2_core/SOURCE_SUCCESSOR.json'
SCHEMA = 'WSV2_CORE_EXACT_SOURCE_V1'
OWNED_PATHS = frozenset((
    'app/templates/v2/react_poc.html',
    'app/v2/react_overview.py',
    'app/v2/react_rcux.py',
    'docs/financial_validation/fin_v2_3/SOURCE_SUCCESSOR.json',
    'docs/financial_validation/fin_v2_r1/SOURCE_SUCCESSOR.json',
    'docs/financial_validation/finv2_d01_d02/SOURCE_SUCCESSOR.json',
    'docs/react_migration/rc_ux_completion/SOURCE_SUCCESSOR.json',
    'docs/react_migration/wsv2_core/ACCEPTANCE_SUCCESSOR_PROPOSAL.patch',
    'docs/react_migration/wsv2_core/CANDIDATE_SOURCE_BLOBS.json',
    'docs/react_migration/wsv2_core/LOCAL_VALIDATION.md',
    'docs/react_migration/wsv2_core/P00_BASELINE_RECEIPT.md',
    'docs/react_migration/wsv2_core/PROTECTED_PATH_REQUEST.md',
    'docs/react_migration/wsv2_core/SHARED_FILE_INTEGRATION.md',
    'docs/react_migration/wsv2_core/WSV2_GAP_COVERAGE_GPT6.md',
    'docs/react_migration/wsv2_core/WSV2_INTERFACE_CONTRACT.md',
    'docs/react_migration/wsv2_core/WSV2_MASTER_GAP_LEDGER.md',
    'frontend/src/App.tsx',
    'frontend/src/app/FinancialOverview.tsx',
    'frontend/src/app/FinancialResults.tsx',
    'frontend/src/app/ReportPrecision.tsx',
    'frontend/src/app/RunFailureNotice.tsx',
    'frontend/src/app/WorkspaceSidebar.tsx',
    'frontend/src/app/WorkspaceView.tsx',
    'frontend/src/app/api.ts',
    'frontend/src/app/compare/CompareProjectsView.tsx',
    'frontend/src/app/financing/FinancingViews.tsx',
    'frontend/src/app/financing/InvestorsPanel.tsx',
    'frontend/src/app/financing/ReserveReturnsView.tsx',
    'frontend/src/app/inputLayout.ts',
    'frontend/src/app/insights/CreditEvidenceCards.tsx',
    'frontend/src/app/insights/CreditTimeline.tsx',
    'frontend/src/app/insights/FinancialInsights.tsx',
    'frontend/src/app/insights/MetricCards.tsx',
    'frontend/src/app/insights/ScenarioComparison.tsx',
    'frontend/src/app/insights/SponsorSchedules.tsx',
    'frontend/src/app/insights/presentation.ts',
    'frontend/src/app/newProject/NewProjectWizard.tsx',
    'frontend/src/app/reportFormatting.test.mjs',
    'frontend/src/app/reportFormatting.ts',
    'frontend/src/app/runs/CompareWorkspace.tsx',
    'frontend/src/app/units.ts',
    'frontend/src/app/workflow/WorkflowBar.tsx',
    'frontend/src/app/workspaceExtensions.ts',
    'frontend/src/app/workspaceNavigation.ts',
    'frontend/src/finco/_workbook/StatementWorkbook.tsx',
    'frontend/src/styles/wsv2-core.css',
    'static/react/finco-react.css',
    'static/react/finco-react.js',
    'tests/fin_v2_cohorts.py',
    'tests/model_mutation_security_successor.py',
    'tests/test_model_mutation_security_successor.py',
    'tests/model_react_mvp_acceptance.py',
    'tests/model_react_rcm_new_project_acceptance.py',
    'tests/model_react_rcm_themes_acceptance.py',
    'tests/model_react_rcux_navigation_acceptance.py',
    'tests/model_react_rcux_product_acceptance.py',
    'tests/test_model_react_poc_browser_acceptance.py',
    'tests/model_react_wf1_browser_acceptance.py',
    'tests/model_react_rcm_financing_acceptance.py',    # Correction H: Sources & Uses display follows the shared Report precision
    'tests/model_react_rcux_runs_acceptance.py',        # Correction H: Compare money cells follow the shared Report precision
    'tests/model_react_rcm_investors_acceptance.py',
    'tests/model_react_rcux_analysis_acceptance.py',
    'tests/model_react_wsv2_acceptance.py',
    'tests/test_model_react_overnight_b_governance.py',
    'tests/test_model_react_wsv2_overview.py',
    'tests/test_model_workspace_consolidation_browser.py',
    'tests/test_rcm_governance.py',
    'tests/test_rcux_governance.py',
    'tests/test_wsv2_core_scope.py',
    'tests/wsv2_core_scope.py',
))

# Exact historical manifest keys that may point at the newly authorized bytes.
OWNER_APPROVED_ACCEPTANCE_PIN = 'tests/model_react_mvp_acceptance.py'
# Owner-approved Chromium route-teardown correction (PR #397): the one acceptance source whose pin in the fin_v2_3 manifest may move.
ROUTE_TEARDOWN_PIN = 'tests/model_react_overnight_b_acceptance.py'

GOVERNANCE_PINS = frozenset((
    'tests/test_fin_v2_3_scope.py',                      # WS-2 gate A: exact successor-aware assertion in the predecessor cohort tests
    'tests/test_fin_v2_r1_scope.py',
    'tests/test_model_mutation_security_successor.py',  # Correction E exact path; no financial/app pins
    'tests/model_mutation_security_successor.py',
    'tests/fin_v2_cohorts.py',
    'tests/test_rcm_governance.py',
    'tests/test_model_react_overnight_b_governance.py',
))
PREDECESSOR_MANIFESTS = (
    'docs/financial_validation/fin_v2_3/SOURCE_SUCCESSOR.json',
    'docs/financial_validation/finv2_d01_d02/SOURCE_SUCCESSOR.json',
    'docs/financial_validation/fin_v2_r1/SOURCE_SUCCESSOR.json',
    'docs/react_migration/rc_ux_completion/SOURCE_SUCCESSOR.json',
)


# WF-04 successor lineage (tests/wf04_scope.py): the exact predecessor pins the Owner-authorised WF-04 change moves (each one is also an owned,
# exactly pinned path of that cohort, and tests/test_wf04_scope.py proves every other pin is unchanged).
WF04_SUCCESSOR_REPIN = {
    PREDECESSOR_MANIFESTS[0]: frozenset(('app/workbook/registry.py', 'tests/test_fin_v2_3_scope.py', 'tests/test_model_workspace_productivity_v1.py',
                                                'tests/test_finval_f01_fixture_integrity.py')),
    PREDECESSOR_MANIFESTS[2]: frozenset(('tests/test_fin_v2_r1_scope.py',)),
}


def _git(root, *args):
    return subprocess.check_output(['git', *args], cwd=root, stderr=subprocess.DEVNULL)


def _read(root, path, ref):
    return (root / path).read_bytes() if ref is None else _git(root, 'show', ref + ':' + path)


def _blob(raw):
    return hashlib.sha1(b'blob ' + str(len(raw)).encode() + b'\0' + raw).hexdigest()


def manifest(repo=None, ref=None):
    root = Path(repo) if repo is not None else ROOT
    try:
        data = json.loads(_read(root, MANIFEST, ref))
        return data if (isinstance(data, dict) and isinstance(data.get('source_blobs'), dict)
                        and data.get('schema_version') == SCHEMA and data.get('base') == BASE
                        and data.get('authorization_head') == AUTHORIZATION_HEAD) else {}
    except (OSError, ValueError, subprocess.CalledProcessError):
        return {}


def _historical_manifests_ok(root, ref):
    for path in PREDECESSOR_MANIFESTS:
        old = json.loads(_read(root, path, AUTHORIZATION_HEAD))
        now = json.loads(_read(root, path, ref))
        if not isinstance(now, dict) or not isinstance(now.get('source_blobs'), dict):
            return False
        before, after = old['source_blobs'], now['source_blobs']
        history = now.get('historical_source_blobs')
        if not isinstance(history, dict) or history.get(AUTHORIZATION_HEAD) != before:
            return False
        if set(before) != set(after):
            return False
        allowed = ({'app/v2/react_rcux.py', 'app/v2/react_workspace_router.py'} if path == PREDECESSOR_MANIFESTS[-1]
                   else GOVERNANCE_PINS | ({OWNER_APPROVED_ACCEPTANCE_PIN, ROUTE_TEARDOWN_PIN} if path == PREDECESSOR_MANIFESTS[0] else set())
                   | WF04_SUCCESSOR_REPIN.get(path, frozenset()))
        from tests import wf03_lifecycle_scope as WF03
        if any(before[p] != after[p] and p not in allowed
               and not WF03.historical_pin_successor(path, p, before[p], after[p], root, ref) for p in before):
            return False
        # Every pre-existing metadata field remains; only the live pin map changes.
        if any(now.get(k) != v for k, v in old.items() if k != 'source_blobs'):
            return False
    return True


# F01/Browser attestations write untracked proof into evidence/ before the full
# acceptance suite. Such non-executable evidence must not invalidate source pins.
# Every other untracked path remains rejected, including source-like files under evidence/.
_CI_EVIDENCE_EXTENSIONS = ('.json', '.xml', '.png', '.webp', '.jpg', '.jpeg', '.txt', '.csv', '.svg', '.html', '.zip')


def _ci_evidence_only(path):
    return path.startswith('evidence/') and path.endswith(_CI_EVIDENCE_EXTENSIONS)


def _successor_allows(path, root, ref):
    """A path owned by the closed WF-04 successor cohort is that cohort's exact-blob responsibility; a missing or altered cohort widens nothing."""
    try:
        from tests import wf04_scope
    except ImportError:
        return False
    return wf04_scope.allowed_path(path, root, ref)


#: The three gate A/D test sources the WS-2 correction edits that are exact-pinned by OTHER registered cohorts (fin_v2_3, fin_v2_r1, rc_ux).
#: Closed list: each is admitted only while a registered cohort pins it (that cohort re-verifies the exact blob inside the composite).
WS2_GATE_TESTS = frozenset((
    'tests/model_react_overnight_b_acceptance.py',    # Owner-approved Chromium route-teardown correction (pinned by the fin_v2_3 cohort)
    'tests/model_react_wf2_browser_acceptance.py',
    'tests/test_fin_v2_3_scope.py',
    'tests/test_fin_v2_r1_scope.py',
))


def _ws2_allows(path, root, ref):
    """ONLY the separately registered WS-2 Save All cohort (tests/fin_v2_wsv2_scope.py), and only while it is itself exact: its manifest identity, every
    pinned blob and its ancestry hold, and the path is one of its enumerated paths (pinned sources, its manifest, its documents, its closed
    presentation list).  Anything else - another cohort, a pattern, a new file, an absent or altered WS-2 cohort - fails closed."""
    # Additive WF03 layer. The old WS1/WS2 branches and historical constants
    # below remain intact; a partial, forged or non-ancestor layer is refused.
    try:
        from tests import wf03_lifecycle_scope as WF03
        if WF03.allowed_path(path, root, ref) and WF03.exact_blobs_ok(root, ref):
            return True
    except ImportError:
        pass
    try:
        from tests import fin_v2_wsv2_scope as WS2
        from tests.fin_v2_cohorts import cohorts
    except ImportError:
        return False
    if WS2 not in cohorts() or not _ws2_exact(WS2, root, ref):
        return False
    if path in WS2_GATE_TESTS:
        return any(m.__name__ != __name__ and m is not WS2 and m.allowed_path(path, root, ref) for m in cohorts())
    return WS2.allowed_path(path, root, ref)


_WS2_SCOPE = []   # call-scope memo stack for the WS-2 exact check: see exact_blobs_ok()


def _ws2_exact(WS2, root, ref):
    """WS2.exact_blobs_ok(root, ref), evaluated once per outer exact_blobs_ok() call instead of once per changed path (the same
    single-threaded call-scope memo as WF03.scoped(): dropped on exit, keeps no bytes, never shared between calls)."""
    if not _WS2_SCOPE:
        return WS2.exact_blobs_ok(root, ref)
    key = (str(root), ref)
    memo = _WS2_SCOPE[-1]
    if key not in memo:
        memo[key] = WS2.exact_blobs_ok(root, ref)
    return memo[key]


def exact_blobs_ok(repo=None, ref=None):
    _WS2_SCOPE.append({})
    try:
        try:
            from tests import wf03_lifecycle_scope as WF03
        except ImportError:
            return _exact_blobs_ok(repo, ref)
        with WF03.scoped():        # the exact WF-03 check runs once per call, not once per changed path
            return _exact_blobs_ok(repo, ref)
    finally:
        _WS2_SCOPE.pop()


def _exact_blobs_ok(repo=None, ref=None):
    root = Path(repo) if repo is not None else ROOT
    pins = manifest(root, ref).get('source_blobs', {})
    if set(pins) != OWNED_PATHS:
        return False
    try:
        _git(root, 'merge-base', '--is-ancestor', BASE, ref or 'HEAD')
        _git(root, 'merge-base', '--is-ancestor', AUTHORIZATION_HEAD, ref or 'HEAD')
        if any(_blob(_read(root, p, ref)) != b for p, b in pins.items()):
            return False
        if not _historical_manifests_ok(root, ref):
            return False
        changed = _git(root, 'diff', '--name-only', BASE, *([ref] if ref else []), '--').decode().splitlines()
        if any(p not in OWNED_PATHS and p != MANIFEST and not _ws2_allows(p, root, ref) and not _successor_allows(p, root, ref) for p in changed):
            return False
        if ref is None:
            untracked = _git(root, 'ls-files', '--others', '--exclude-standard').decode().splitlines()
            if any(p not in OWNED_PATHS and p != MANIFEST and not _ci_evidence_only(p) and not _ws2_allows(p, root, ref)
                   and not _successor_allows(p, root, ref) for p in untracked):
                return False
        return True
    except (OSError, ValueError, KeyError, subprocess.CalledProcessError):
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


def protected_blobs(repo=None, ref=None):
    return {}  # Never admit a financial_engine, finco_core or domain source.
