"""Closed PR-U1 exact-source cohort: the single CAPEX/OPEX workbench and Inputs overview, a UI-only successor over the merged PR #410 main.

Authority: Financial Owner decisions of 2026-11-02 (post-#410 owner decisions D1..D14, PR-U1 implementation brief): a bounded, literal, authenticated
successor; not a general waiver and no financial methodology change. ``BASE`` is the merge of PR #410; it is an ancestor of every head of this cohort,
authenticated by commit, tree AND the recorded BASE blob of every path this cohort supersedes (so the WF-06B cohort and every older cohort stay
exactly as they were reviewed: nothing in their manifests was edited, and their pins describe BASE).

What it owns: a literal, finite path set (new files, the reviewed edits of existing presentation / route sources, the rebuilt bundle, the tests and
documents, and the reviewed bounded hooks in the WF-06B scope module and the registry). Nothing else is admitted: no ``financial_engine/``,
``finco_core/``, ``domain/``, ``.github/``, ``tools/`` or ``main_web.py`` path, no pattern, no wildcard.

Supersession (``SUPERSEDED``): the subset of owned paths that already exist at BASE and that older cohorts pin at their BASE blob. An older cohort
accepts a different current blob for such a path only through ``supersedes(path, blob)``, which is true only while THIS cohort is exact and pins
exactly that blob. It never admits a value for a path outside ``SUPERSEDED``.

Termination: every check is low level. It reads git objects and this cohort's manifest only; it never calls an older cohort or the cohort registry
(the composite ``valid`` imports the registry lazily and is never called from a low level check), so there is no recursive self-approval. No result
cache outlives one outer governance call (``scoped``).
"""
from pathlib import Path
from contextlib import contextmanager
import hashlib
import json
import subprocess

ROOT = Path(__file__).resolve().parents[1]
BASE = '3e00acab71ea4c2bd9e7396e5bee609225212623'
BASE_TREE = '12cd2bfb89eac3e628da1bba80efd01b0c47af2f'
MANIFEST = 'docs/react_migration/u1_workbench/SOURCE_SUCCESSOR.json'
SCHEMA = 'U1_SINGLE_WORKBENCH_EXACT_SOURCE_V1'

PRESENTATION_PATHS = frozenset((
    'frontend/src/app/CostWorkbench.tsx',
    'frontend/src/app/InputsCostCards.tsx',
    'frontend/src/app/InputsGuide.tsx',
    'frontend/src/app/InputsOverview.tsx',
    'frontend/src/app/WorkspaceSidebar.tsx',
    'frontend/src/app/WorkspaceView.tsx',
    'frontend/src/app/capex/CapexStudio.tsx',
    'frontend/src/app/costGroupDisplay.ts',
    'frontend/src/app/editing/ChangesDrawer.tsx',
    'frontend/src/app/editing/CostLinesGridView.tsx',
    'frontend/src/app/editing/wsv2Extensions.tsx',
    'frontend/src/app/projection/OpexProjection.tsx',
    'frontend/src/app/types.ts',
    'frontend/src/app/workflow/CostLineManager.tsx',
    'frontend/src/app/workflow/workflowShared.tsx',
    'frontend/src/app/workspaceExtensions.ts',
    'frontend/src/app/workspaceNavigation.ts',
    'frontend/src/styles/compact-inputs.css',
    'static/react/finco-react.css',
    'static/react/finco-react.js',
))
SOURCE_PATHS = frozenset((
    'app/cost_line_ledger/opex_bases.py',
    'app/v2/react_workspace_router.py',
))
TEST_AND_DOC_PATHS = frozenset((
    'docs/react_migration/u1_workbench/P00.md',
    'tests/model_react_mvp_acceptance.py',
    'tests/model_react_overnight_b_acceptance.py',
    'tests/model_react_rcux_analysis_acceptance.py',
    'tests/model_react_rcux_capex_acceptance.py',
    'tests/model_react_rcux_import_acceptance.py',
    'tests/model_react_rcux_navigation_acceptance.py',
    'tests/model_react_u1_acceptance.py',
    'tests/model_react_u1_helpers.py',
    'tests/model_react_wf06a_acceptance.py',
    'tests/model_react_wf06b_acceptance.py',
    'tests/model_react_wf2_browser_acceptance.py',
    'tests/model_react_wf2_lifecycle_acceptance.py',
    'tests/test_u1_opex_bases.py',
    'tests/test_u1_scope.py',
    'tests/test_u1_static_guards.py',
    'tests/test_wsv2_core_scope.py',
    'tests/test_fin_v2_wf06a_scope.py',
    'tests/test_rcm_governance.py',
    'tests/test_model_react_overnight_b_governance.py',
    'tests/model_mutation_security_successor.py',
    'tests/test_wf06b_scope.py',
    'tests/u1_browser_role.py',
))
# Reviewed, bounded hooks in the WF-06B scope module and the registry (each pinned below). This cohort's own module is owned too.
GOVERNANCE_PATHS = frozenset((
    'tests/fin_v2_cohorts.py',
    'tests/u1_scope.py',
    'tests/wf06b_scope.py',
))
OWNED_PATHS = PRESENTATION_PATHS | SOURCE_PATHS | TEST_AND_DOC_PATHS | GOVERNANCE_PATHS
# Owned paths that exist at BASE. Older cohorts pin these at their BASE blob; the BASE blob of each is recorded in the manifest and re-verified.
SUPERSEDED = frozenset((
    'app/v2/react_workspace_router.py',
    'frontend/src/app/InputsGuide.tsx',
    'frontend/src/app/InputsOverview.tsx',
    'frontend/src/app/WorkspaceSidebar.tsx',
    'frontend/src/app/WorkspaceView.tsx',
    'frontend/src/app/capex/CapexStudio.tsx',
    'frontend/src/app/editing/ChangesDrawer.tsx',
    'frontend/src/app/editing/CostLinesGridView.tsx',
    'frontend/src/app/editing/wsv2Extensions.tsx',
    'frontend/src/app/projection/OpexProjection.tsx',
    'frontend/src/app/types.ts',
    'frontend/src/app/workflow/CostLineManager.tsx',
    'frontend/src/app/workflow/workflowShared.tsx',
    'frontend/src/app/workspaceExtensions.ts',
    'frontend/src/app/workspaceNavigation.ts',
    'frontend/src/styles/compact-inputs.css',
    'static/react/finco-react.css',
    'static/react/finco-react.js',
    'tests/fin_v2_cohorts.py',
    'tests/model_react_mvp_acceptance.py',
    'tests/model_react_overnight_b_acceptance.py',
    'tests/model_react_rcux_analysis_acceptance.py',
    'tests/model_react_rcux_capex_acceptance.py',
    'tests/model_react_rcux_import_acceptance.py',
    'tests/model_react_rcux_navigation_acceptance.py',
    'tests/model_react_wf06a_acceptance.py',
    'tests/model_react_wf06b_acceptance.py',
    'tests/model_react_wf2_browser_acceptance.py',
    'tests/model_react_wf2_lifecycle_acceptance.py',
    'tests/model_mutation_security_successor.py',
    'tests/test_model_react_overnight_b_governance.py',
    'tests/test_rcm_governance.py',
    'tests/test_fin_v2_wf06a_scope.py',
    'tests/test_wsv2_core_scope.py',
    'tests/test_wf06b_scope.py',
    'tests/wf06b_scope.py',
))
# No owned path may ever sit under a protected prefix; this is checked on the literal set and on every changed path.
FORBIDDEN_PREFIXES = ('financial_engine/', 'finco_core/', 'domain/', '.github/', 'tools/')
FORBIDDEN_PATHS = frozenset(('main_web.py',))

_CI_EVIDENCE_EXTENSIONS = ('.json', '.xml', '.png', '.webp', '.jpg', '.jpeg', '.txt', '.csv', '.svg', '.html', '.zip')


def _git(root, *args):
    return subprocess.check_output(['git', *args], cwd=root, stderr=subprocess.DEVNULL)


def _read(root, path, ref):
    return (Path(root) / path).read_bytes() if ref is None else _git(root, 'show', ref + ':' + path)


def _blob(raw):
    return hashlib.sha1(b'blob ' + str(len(raw)).encode() + b'\0' + raw).hexdigest()


def _ci_evidence_only(path):
    return path.startswith('evidence/') and path.endswith(_CI_EVIDENCE_EXTENSIONS)


def manifest(repo=None, ref=None):
    root = Path(repo) if repo is not None else ROOT
    try:
        data = json.loads(_read(root, MANIFEST, ref))
        return data if (isinstance(data, dict) and isinstance(data.get('source_blobs'), dict) and isinstance(data.get('base_blobs'), dict)
                        and data.get('schema_version') == SCHEMA and data.get('base') == BASE and data.get('base_tree') == BASE_TREE) else {}
    except (OSError, ValueError, subprocess.CalledProcessError):
        return {}


def _owned_ok():
    return (not any(p.startswith(FORBIDDEN_PREFIXES) or p in FORBIDDEN_PATHS or '..' in p.split('/') or p.startswith('/') for p in OWNED_PATHS | {MANIFEST})
            and SUPERSEDED <= OWNED_PATHS)


_SCOPE = []


@contextmanager
def scoped():
    """Within ONE outer governance call the result of ``exact_blobs_ok(root, ref)`` is computed once. Dropped on exit; never keeps bytes."""
    _SCOPE.append({})
    try:
        yield
    finally:
        _SCOPE.pop()


def exact_blobs_ok(repo=None, ref=None):
    if not _SCOPE:
        return _exact_blobs_ok(repo, ref)
    key = (str(repo if repo is not None else ROOT), ref)
    memo = _SCOPE[-1]
    if key not in memo:
        memo[key] = _exact_blobs_ok(repo, ref)
    return memo[key]


def _exact_blobs_ok(repo=None, ref=None):
    root = Path(repo) if repo is not None else ROOT
    data = manifest(root, ref)
    pins, base_blobs = data.get('source_blobs', {}), data.get('base_blobs', {})
    if not data or not _owned_ok() or set(pins) != OWNED_PATHS - {MANIFEST} or set(base_blobs) != SUPERSEDED:
        return False
    try:
        head = ref or 'HEAD'
        # 1. immutable provenance: the literal base commit and tree are ancestors of the evaluated head
        _git(root, 'merge-base', '--is-ancestor', BASE, head)
        if _git(root, 'rev-parse', BASE + '^{tree}').decode().strip() != BASE_TREE:
            return False
        # 2. the BASE blob recorded for every superseded path is what git holds at BASE (history is not rewritten here)
        paths = sorted(base_blobs)
        at_base = _git(root, 'rev-parse', *[BASE + ':' + p for p in paths]).decode().split()
        if at_base != [base_blobs[p] for p in paths]:
            return False
        # 3. one exact blob per owned path
        if ref is None:
            if any(_blob(_read(root, p, ref)) != sha for p, sha in pins.items()):
                return False
        else:
            listed = {}
            for line in _git(root, 'ls-tree', '-r', ref, '--', *sorted(pins)).decode().splitlines():
                meta, name = line.split('\t', 1)
                listed[name] = meta.split()[2]
            if listed != pins:
                return False
        # 4. nothing outside the literal set changed since BASE; protected prefixes can never move
        changed = _git(root, 'diff', '--name-only', '--no-renames', BASE, *([ref] if ref else []), '--').decode().splitlines()
        if any((p not in OWNED_PATHS and p != MANIFEST) or p.startswith(FORBIDDEN_PREFIXES) or p in FORBIDDEN_PATHS for p in changed):
            return False
        # 5. no owned file is executable or a link in the evaluated state
        if ref is None:
            for p in OWNED_PATHS | {MANIFEST}:
                f = root / p
                if f.is_symlink() or (f.exists() and f.stat().st_mode & 0o111):
                    return False
            untracked = _git(root, 'ls-files', '--others', '--exclude-standard').decode().splitlines()
            if any(p not in OWNED_PATHS and p != MANIFEST and not _ci_evidence_only(p) for p in untracked):
                return False
        else:
            modes = _git(root, 'ls-tree', '-r', ref, '--', *sorted(OWNED_PATHS | {MANIFEST})).decode().splitlines()
            if any(not line.startswith('100644 ') for line in modes):
                return False
        return True
    except (OSError, ValueError, KeyError, TypeError, AttributeError, subprocess.CalledProcessError):
        return False


def allowed_path(path, repo=None, ref=None):
    return path in OWNED_PATHS or path == MANIFEST


def base_blob(path, repo=None, ref=None):
    """The recorded BASE blob of a superseded path (re-verified against git inside ``exact_blobs_ok``), or ``None``."""
    return manifest(repo, ref).get('base_blobs', {}).get(path)


def supersedes(path, value, repo=None, ref=None):
    """Bounded supersession for the older guards: true only for a path of ``SUPERSEDED``, only while this cohort is exact, only for its exact pin."""
    return path in SUPERSEDED and exact_blobs_ok(repo, ref) and manifest(repo, ref).get('source_blobs', {}).get(path) == value


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
    return {}  # Never admits a financial_engine, finco_core or domain source.
