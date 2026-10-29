"""Closed WF-04 exact-source cohort: two contractual DSCR inputs, Run-bound terms, strict EoD/covenant evaluation and the Debt Metrics workspace.

Authority: Financial Owner V3 decision and the unified WF-04 prompt section 0A (2026-10-29). Only this literal path set is admitted. No
financial_engine, finco_core, domain, CI, security, Save All, writer-route or signed-certificate path is added, and no merge/deployment
authority is created. Historical predecessor manifests stay verifiable at BASE: only the named re-pins below may differ, and each one keeps its
previous pin map under ``historical_source_blobs[BASE]``. Low-level checks never call the cohort registry.
"""
from pathlib import Path
import hashlib
import json
import subprocess

ROOT = Path(__file__).resolve().parents[1]
BASE = 'b76ac65c99e7fc9b486a557ae3c5ba9a711f50b3'
MANIFEST = 'docs/financial_validation/wf04_debt_metrics/SOURCE_SUCCESSOR.json'
SCHEMA = 'WF04_DEBT_METRICS_EXACT_SOURCE_V1'
# @@OWNED_PATHS_BEGIN@@
OWNED_PATHS = frozenset((
    'app/persistence/workspace_repository.py',
    'app/v2/credit_decision_projection.py',
    'app/v2/debt_metrics_projection.py',
    'app/workbook/dscr_contract_terms.py',
    'app/workbook/registry.py',
    'docs/financial_validation/fin_v2_3/SOURCE_SUCCESSOR.json',
    'docs/financial_validation/fin_v2_r1/SOURCE_SUCCESSOR.json',
    'docs/financial_validation/wf04_debt_metrics/P00_VERIFIED_STATE.md',
    'docs/financial_validation/wf04_debt_metrics/TWO_DSCR_CONTRACT_MAPPING.md',
    'docs/react_migration/wsv2_core/SOURCE_SUCCESSOR.json',
    'frontend/src/app/FinancialOverview.tsx',
    'frontend/src/app/FinancialResults.tsx',
    'frontend/src/app/credit/CreditDecisionPanel.tsx',
    'frontend/src/app/debtmetrics/CovenantTable.tsx',
    'frontend/src/app/debtmetrics/DebtMetricsWorkspace.tsx',
    'frontend/src/app/debtmetrics/DscrProfileChart.tsx',
    'frontend/src/app/debtmetrics/KpiRow.tsx',
    'frontend/src/app/debtmetrics/PeriodSchedule.tsx',
    'frontend/src/app/debtmetrics/ReservesPanel.tsx',
    'frontend/src/app/debtmetrics/__tests__/debtMetrics.test.mjs',
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
    'tests/test_wf04_credit_debt_metrics.py',
    'tests/test_wf04_debt_metrics_browser.py',
    'tests/test_wf04_dscr_contract_terms.py',
    'tests/test_wf04_run_bound_terms.py',
    'tests/test_wsv2_core_scope.py',
    'tests/wf04_scope.py',
    'tests/wsv2_core_scope.py',
))
# @@OWNED_PATHS_END@@

FIN_V2_3_MANIFEST = 'docs/financial_validation/fin_v2_3/SOURCE_SUCCESSOR.json'
FIN_V2_R1_MANIFEST = 'docs/financial_validation/fin_v2_r1/SOURCE_SUCCESSOR.json'
WSV2_CORE_MANIFEST = 'docs/react_migration/wsv2_core/SOURCE_SUCCESSOR.json'
# Predecessor manifests that WF-04 re-pins, and the exact pins each one may move (everything else must stay byte-for-byte what it was at BASE).
PREDECESSOR_REPINS = {
    FIN_V2_3_MANIFEST: frozenset(('app/workbook/registry.py', 'tests/test_fin_v2_3_scope.py')),
    FIN_V2_R1_MANIFEST: frozenset(('tests/fin_v2_cohorts.py', 'tests/test_fin_v2_r1_scope.py')),
    WSV2_CORE_MANIFEST: frozenset((
        'docs/financial_validation/fin_v2_3/SOURCE_SUCCESSOR.json',
        'docs/financial_validation/fin_v2_r1/SOURCE_SUCCESSOR.json',
        'frontend/src/app/FinancialOverview.tsx',
        'frontend/src/app/FinancialResults.tsx',
        'frontend/src/app/workflow/WorkflowBar.tsx',
        'static/react/finco-react.css',
        'static/react/finco-react.js',
        'tests/fin_v2_cohorts.py',
        'tests/test_rcux_governance.py',
        'tests/test_wsv2_core_scope.py',
        'tests/wsv2_core_scope.py',
    )),
}
# No financial, security, CI or writer namespace may ever be owned by this cohort.
FORBIDDEN_PREFIXES = ('financial_engine/', 'finco_core/', 'domain/', '.github/', 'frontend/src/app/editing/')
FORBIDDEN_PATHS = frozenset((
    'main_web.py', 'app/v2/router.py', 'app/v2/grid_router.py', 'app/v2/react_workspace_router.py', 'app/v2/save_all_commands.py',
    'app/v2/mutation_csrf.py', 'app/workbook/update_service.py', 'app/workbook/bankability_config.py',
))


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
                        and data.get('schema_version') == SCHEMA and data.get('base') == BASE) else {}
    except (OSError, ValueError, subprocess.CalledProcessError):
        return {}


def _historical_manifests_ok(root, ref):
    """Each predecessor manifest equals its BASE self except the named re-pins, whose previous map is preserved under ``historical_source_blobs[BASE]``."""
    for path, allowed in PREDECESSOR_REPINS.items():
        old = json.loads(_read(root, path, BASE))
        now = json.loads(_read(root, path, ref))
        if not isinstance(now, dict) or not isinstance(now.get('source_blobs'), dict):
            return False
        before, after = old['source_blobs'], now['source_blobs']
        history = now.get('historical_source_blobs')
        if not isinstance(history, dict) or history.get(BASE) != before:
            return False
        if any(history.get(k) != v for k, v in (old.get('historical_source_blobs') or {}).items()):
            return False
        if set(before) != set(after):
            return False
        if any(before[p] != after[p] and p not in allowed for p in before):
            return False
        if any(now.get(k) != v for k, v in old.items() if k not in ('source_blobs', 'historical_source_blobs')):
            return False
    return True


def _owned_ok():
    return (not any(p.startswith(FORBIDDEN_PREFIXES) or p in FORBIDDEN_PATHS for p in OWNED_PATHS)
            and all(p == MANIFEST or '..' not in p.split('/') for p in OWNED_PATHS))


# F01/Browser attestations write untracked proof into evidence/ before the full acceptance suite; non-executable evidence is not source.
_CI_EVIDENCE_EXTENSIONS = ('.json', '.xml', '.png', '.webp', '.jpg', '.jpeg', '.txt', '.csv', '.svg', '.html', '.zip')


def _ci_evidence_only(path):
    return path.startswith('evidence/') and path.endswith(_CI_EVIDENCE_EXTENSIONS)


def exact_blobs_ok(repo=None, ref=None):
    root = Path(repo) if repo is not None else ROOT
    pins = manifest(root, ref).get('source_blobs', {})
    if set(pins) != OWNED_PATHS or not _owned_ok():
        return False
    try:
        _git(root, 'merge-base', '--is-ancestor', BASE, ref or 'HEAD')
        if any(_blob(_read(root, p, ref)) != b for p, b in pins.items()):
            return False
        if not _historical_manifests_ok(root, ref):
            return False
        changed = _git(root, 'diff', '--name-only', BASE, *([ref] if ref else []), '--').decode().splitlines()
        if any(p not in OWNED_PATHS and p != MANIFEST for p in changed):
            return False
        if ref is None:
            untracked = _git(root, 'ls-files', '--others', '--exclude-standard').decode().splitlines()
            if any(p not in OWNED_PATHS and p != MANIFEST and not _ci_evidence_only(p) for p in untracked):
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


def protected_blobs(repo=None, ref=None):
    return {}  # Never admit a financial_engine, finco_core or domain source.
