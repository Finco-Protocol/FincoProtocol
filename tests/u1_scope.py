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

Post-#413 successors (``LATER_COHORTS``; PR-U2 2026-11-03): each closed later cohort, pinned by its own manifest and registered in the registry,
extends this cohort through bounded hooks (``_later_supersedes`` for an owned pin, ``_later_owns`` for a path it adds). U1 follows a later cohort
only while it is exact, only for a path it supersedes, only for its exact pin, and only where its recorded BASE blob equals this cohort's own pin.
Later cohorts are low level: they never import this module or the registry, so the call graph stays acyclic.
"""
from pathlib import Path
from contextlib import ExitStack, contextmanager
import hashlib
import json
import subprocess

ROOT = Path(__file__).resolve().parents[1]
BASE = '3e00acab71ea4c2bd9e7396e5bee609225212623'
BASE_TREE = '12cd2bfb89eac3e628da1bba80efd01b0c47af2f'
# Integration point (PR #413 Correction I): main after PR #414 (the CI V3 governance amortisation). ``BASE`` stays the literal #410 merge: nothing historical is
# rewritten. ``INTEGRATION`` is a second, immutable reference: everything this cohort does not own must equal main at this commit, and the older cohorts'
# pins of the superseded paths describe either BASE (before #414) or INTEGRATION (after #414).
INTEGRATION = '8b311c00fea6ca2683974f5a1a963346614730ad'
INTEGRATION_TREE = 'aa8430e2c450511da78a0c080918b5f4c3111bb7'
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
    'tests/test_wf04_scope.py',
    'tests/test_wf06b_no_source_provenance_ui.py',
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
    'tests/test_wf04_scope.py',
    'tests/test_wf06b_no_source_provenance_ui.py',
    'tests/test_wf06b_scope.py',
    'tests/wf06b_scope.py',
))
# No owned path may ever sit under a protected prefix; this is checked on the literal set and on every changed path.
FORBIDDEN_PREFIXES = ('financial_engine/', 'finco_core/', 'domain/', '.github/', 'tools/')
FORBIDDEN_PATHS = frozenset(('main_web.py',))

_CI_EVIDENCE_EXTENSIONS = ('.json', '.xml', '.png', '.webp', '.jpg', '.jpeg', '.txt', '.csv', '.svg', '.html', '.zip')


def _git(root, *args):
    return subprocess.check_output(['git', *args], cwd=root, stderr=subprocess.DEVNULL)


# Immutable git-object facts only: a commit id fixes its tree, the blobs below it and its ancestry relative to another FIXED commit for good, so these
# answers can never change. Mutable state (ancestry of the evaluated head, the working tree, the index, modes, untracked files, the diff against BASE)
# is NEVER cached: those are read afresh on every call, so no verdict can outlive the state it judged.
_OBJECT_FACTS = {}


def _object_fact(root, *args):
    key = (str(root),) + args
    if key not in _OBJECT_FACTS:
        _OBJECT_FACTS[key] = _git(root, *args)
    return _OBJECT_FACTS[key]



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
                        and isinstance(data.get('integration_blobs'), dict)
                        and data.get('schema_version') == SCHEMA and data.get('base') == BASE and data.get('base_tree') == BASE_TREE
                        and data.get('integration') == INTEGRATION and data.get('integration_tree') == INTEGRATION_TREE) else {}
    except (OSError, ValueError, subprocess.CalledProcessError):
        return {}


def _owned_ok():
    return (not any(p.startswith(FORBIDDEN_PREFIXES) or p in FORBIDDEN_PATHS or '..' in p.split('/') or p.startswith('/') for p in OWNED_PATHS | {MANIFEST})
            and SUPERSEDED <= OWNED_PATHS)


_SCOPE = []


LATER_COHORTS = ('tests.post413_r17_scope', 'tests.post413_r18_scope', 'tests.post413_r1_scope', 'tests.u2_scope', 'tests.ci_v4_scope', 'tests.g10_d8_scope', 'tests.post413_o1_scope', 'tests.ux_pr1_scope', 'tests.ux_pr2a_scope', 'tests.ux_pr2b_scope', 'tests.ux_pr2c_scope', 'tests.ux_pr3b1_scope')


def _later_modules():
    import importlib
    loaded = []
    for name in LATER_COHORTS:
        try:
            loaded.append(importlib.import_module(name))
        except ModuleNotFoundError as exc:
            if exc.name != name:
                raise
    return loaded


def _later_follows(path, blob, pin, root, ref):
    """A U1 pin is followed by a later exact state only where that later cohort supersedes the path at exactly this U1 pin."""
    return any(path in m.SUPERSEDED and m.base_blob(path, root, ref) == pin and m.supersedes(path, blob, root, ref) for m in _later_modules())


def _later_owns(path, repo, ref):
    return any(m.allowed_path(path, repo, ref) and m.exact_blobs_ok(repo, ref) for m in _later_modules())


def _later_ci_owns(path, repo, ref):
    """CI V4 (2026-11-04): the ONLY admission of a protected ``.github/``/``tools/`` path - a literal CI path of an exact later CI cohort."""
    return path.startswith(('.github/', 'tools/')) and any(callable(getattr(m, 'ci_owns', None)) and m.ci_owns(path, repo, ref) for m in _later_modules())


def _later_supersedes(path, value, repo, ref):
    """A registered, exact later cohort pins ``value`` for a path of ITS superseded set that THIS cohort does not own (an older guard, WF-06B, owns it)."""
    return any(m.supersedes(path, value, repo, ref) for m in _later_modules())


@contextmanager
def scoped():
    """Within ONE outer governance call the result of ``exact_blobs_ok(root, ref)`` is computed once. Dropped on exit; never keeps bytes."""
    if _SCOPE:        # a nested enter shares the outermost memo (never outlives the outermost exit, never shared between separate outer calls)
        yield
        return
    with ExitStack() as later:       # each later cohort's verdict is shared for the same outer call only (PR #414 call scope)
        for m in _later_modules():
            later.enter_context(m.scoped())
        _SCOPE.append({})
        try:
            yield
        finally:
            _SCOPE.pop()


# Cohort modules ABOVE this one in the delegation chain that open a one-outer-call scope for their own verdicts. While one of them is inside its
# scope no file is written and nothing is mutated (that is the scope's contract), so this cohort's verdict can share THAT scope's memo: it lives
# exactly as long as the enclosing outer call, is dropped with it, and never outlives or crosses an outer call. Outside every scope nothing is shared.
_ENCLOSING_SCOPE_MODULES = ('tests.wf06b_scope', 'tests.wf03_lifecycle_scope', 'tests.fin_v2_wf06a_scope', 'tests.fin_v2_integration_409_scope')


def _enclosing_call_memo():
    import sys
    for name in _ENCLOSING_SCOPE_MODULES:
        scope = getattr(sys.modules.get(name), '_SCOPE', None)
        if scope:
            return scope[-1]
    return None


def exact_blobs_ok(repo=None, ref=None):
    if not _SCOPE:
        memo = _enclosing_call_memo()
        if memo is None:
            return _exact_blobs_ok(repo, ref)
        key = ('tests.u1_scope.exact_blobs_ok', str(repo if repo is not None else ROOT), ref)
        if key not in memo:
            memo[key] = _exact_blobs_ok(repo, ref)
        return memo[key]
    key = (str(repo if repo is not None else ROOT), ref)
    memo = _SCOPE[-1]
    if key not in memo:
        memo[key] = _exact_blobs_ok(repo, ref)
    return memo[key]




def _exact_blobs_ok(repo=None, ref=None):
    with ExitStack() as later:       # one verdict per later cohort for this U1 check (dropped on exit)
        for m in _later_modules():
            later.enter_context(m.scoped())
        return _exact_blobs_ok_inner(repo, ref)


def _exact_blobs_ok_inner(repo=None, ref=None):
    root = Path(repo) if repo is not None else ROOT
    data = manifest(root, ref)
    pins, base_blobs = data.get('source_blobs', {}), data.get('base_blobs', {})
    integration_blobs = data.get('integration_blobs', {})
    if (not data or not _owned_ok() or set(pins) != OWNED_PATHS - {MANIFEST} or set(base_blobs) != SUPERSEDED
            or set(integration_blobs) != SUPERSEDED):
        return False
    try:
        head = ref or 'HEAD'
        # 1. immutable provenance: the literal base commit and tree are ancestors of the evaluated head
        _git(root, 'merge-base', '--is-ancestor', BASE, head)
        _git(root, 'merge-base', '--is-ancestor', INTEGRATION, head)
        _object_fact(root, 'merge-base', '--is-ancestor', BASE, INTEGRATION)
        if _object_fact(root, 'rev-parse', BASE + '^{tree}').decode().strip() != BASE_TREE:
            return False
        if _object_fact(root, 'rev-parse', INTEGRATION + '^{tree}').decode().strip() != INTEGRATION_TREE:
            return False
        paths = sorted(base_blobs)
        # 2. the blob recorded for every superseded path is what git holds at BASE (#410) and at INTEGRATION (#414); history is not rewritten here
        at_base = _object_fact(root, 'rev-parse', *[BASE + ':' + p for p in paths]).decode().split()
        if at_base != [base_blobs[p] for p in paths]:
            return False
        at_integration = _object_fact(root, 'rev-parse', *[INTEGRATION + ':' + p for p in paths]).decode().split()
        if at_integration != [integration_blobs[p] for p in paths]:
            return False
        # 3. one exact blob per owned path
        if ref is None:
            current = {p: _blob(_read(root, p, ref)) for p in pins}
        else:
            current = {}
            for line in _git(root, 'ls-tree', '-r', ref, '--', *sorted(pins)).decode().splitlines():
                meta, name = line.split('\t', 1)
                current[name] = meta.split()[2]
            if set(current) != set(pins):
                return False
        if any(current[p] != sha and not _later_follows(p, current[p], sha, root, ref) for p, sha in pins.items()):
            return False
        # 4. nothing outside the literal set changed since BASE; protected prefixes can never move
        changed_since_base = _git(root, 'diff', '--name-only', '--no-renames', BASE, *([ref] if ref else []), '--').decode().splitlines()
        if any((p.startswith(FORBIDDEN_PREFIXES) or p in FORBIDDEN_PATHS) and not _later_ci_owns(p, root, ref) for p in changed_since_base):
            return False
        # everything this cohort does not own equals main at the integration commit (the reviewed #414 state), byte for byte
        changed = _git(root, 'diff', '--name-only', '--no-renames', INTEGRATION, *([ref] if ref else []), '--').decode().splitlines()
        if any((p not in OWNED_PATHS and p != MANIFEST and not _later_owns(p, root, ref)) or ((p.startswith(FORBIDDEN_PREFIXES) or p in FORBIDDEN_PATHS) and not _later_ci_owns(p, root, ref))
               for p in changed):
            return False
        # 5. no owned file is executable or a link in the evaluated state
        if ref is None:
            for p in OWNED_PATHS | {MANIFEST}:
                f = root / p
                if f.is_symlink() or (f.exists() and f.stat().st_mode & 0o111):
                    return False
            untracked = _git(root, 'ls-files', '--others', '--exclude-standard').decode().splitlines()
            if any(p not in OWNED_PATHS and p != MANIFEST and not _ci_evidence_only(p) and not _later_owns(p, root, ref) for p in untracked):
                return False
        else:
            modes = _git(root, 'ls-tree', '-r', ref, '--', *sorted(OWNED_PATHS | {MANIFEST})).decode().splitlines()
            if any(not line.startswith('100644 ') for line in modes):
                return False
        return True
    except (OSError, ValueError, KeyError, TypeError, AttributeError, subprocess.CalledProcessError):
        return False


def allowed_path(path, repo=None, ref=None):
    return path in OWNED_PATHS or path == MANIFEST or _later_owns(path, repo, ref)


def base_blob(path, repo=None, ref=None):
    """The recorded BASE blob of a superseded path (re-verified against git inside ``exact_blobs_ok``), or ``None``."""
    return manifest(repo, ref).get('base_blobs', {}).get(path)


def historical_blobs(path, repo=None, ref=None):
    """The reviewed blobs an older cohort may still pin for a superseded path: main at #410 (BASE) or main at #414 (INTEGRATION)."""
    data = manifest(repo, ref)
    found = {b for b in (data.get('base_blobs', {}).get(path), data.get('integration_blobs', {}).get(path)) if b}
    # A registered later cohort that supersedes ``path`` has recorded its #413 BASE blob and re-verified it against git inside its own exact check; that
    # BASE blob is the reviewed state an older guard (WF-06B) may still hold. Only while that later cohort is exact, only for a path it supersedes.
    for later in _later_modules():
        if path in later.SUPERSEDED and later.exact_blobs_ok(repo, ref):
            blob = later.base_blob(path, repo, ref)
            if blob:
                found.add(blob)
    return found


def supersedes(path, value, repo=None, ref=None):
    """Bounded supersession for the older guards: true only for a path of ``SUPERSEDED``, only while this cohort is exact, only for its exact pin."""
    if path in SUPERSEDED:
        if not exact_blobs_ok(repo, ref):
            return False
        pin = manifest(repo, ref).get('source_blobs', {}).get(path)
        return pin == value or (pin is not None and _later_follows(path, value, pin, repo, ref))
    # PR2c Correction B: a governance manifest the exact tip cohort moves (one of its
    # INTEGRATION_MANIFESTS) is admitted at its current bytes only while that cohort is
    # exact — its own sibling-leg check proves the manifest's only change is exactly the
    # moved pins to its exact pins, so any other content drift fails closed with the
    # whole cohort.  Everything else keeps the later-cohort supersession chain.
    try:
        from tests import ux_pr2c_scope as S
    except ImportError:
        return _later_supersedes(path, value, repo, ref)
    if path in S.INTEGRATION_MANIFESTS and S.exact_blobs_ok(repo, ref) and S.allowed_path(path, repo, ref):
        return True
    return _later_supersedes(path, value, repo, ref)      # a path an older guard owns (e.g. WF-06B / tests/test_rcux_governance.py): the later cohort's exact pin only


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
