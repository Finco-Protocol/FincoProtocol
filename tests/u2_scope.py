"""Closed PR-U2 exact-source cohort: CAPEX & OPEX full-functionality completion, a UI + read-only-route successor over main after PR #413.

Authority: the 2026-11-03 PR-U2 brief and its mandatory addendum (D13 hard stop, D7 coordinated with R1, D14 existing backend tolerance). A bounded,
literal, authenticated successor; not a general waiver and no financial methodology, engine, schema or Save All change.

``BASE`` is main after the merge of PR #413; it is an ancestor of every head of this cohort, authenticated by commit, tree AND the recorded BASE blob
of every owned path that already exists at BASE (``SUPERSEDED``). The closed U1 cohort pins those paths at exactly these BASE blobs; U1 accepts the
U2 blob of such a path only through ``supersedes`` here, i.e. only while THIS cohort is exact and pins exactly that blob.

What it owns: a literal, finite path set. Nothing else is admitted: no ``financial_engine/``, ``finco_core/``, ``domain/``, ``.github/``, ``tools/``
or ``main_web.py`` path, no pattern, no wildcard. None of the R1-owned files (Save All / PPA / Changes) is owned or may change.

Termination: every check is low level. It reads git objects and this cohort's manifest only; it never imports U1, any older cohort or the registry
(only ``valid`` imports the registry lazily, and nothing low level calls ``valid``). No result cache outlives one outer governance call (``scoped``).
"""
from pathlib import Path
from contextlib import ExitStack, contextmanager
import hashlib
import json
import subprocess

ROOT = Path(__file__).resolve().parents[1]
BASE = '2c63750929477c618444e9d056030e054cc3a41c'
BASE_TREE = 'e7869fc8f4775b5ae62a5c75be60f2efef2cfd79'
# Named apart from the older ``SOURCE_SUCCESSOR.json`` manifests on purpose: the older cohorts' guards forbid any new or edited file of that name.
MANIFEST = 'docs/react_migration/u2_workbench/U2_EXACT_SOURCE.json'
SCHEMA = 'U2_COST_COMPLETION_EXACT_SOURCE_V1'

PRESENTATION_PATHS = frozenset((
    'frontend/src/app/CostWorkbench.tsx',
    'frontend/src/app/capex/CapexStudio.tsx',
    'frontend/src/app/capex/__tests__/profileImport.test.mjs',
    'frontend/src/app/capex/profileFocus.ts',
    'frontend/src/app/capex/profileImport.ts',
    'frontend/src/app/editing/CostLinesGridView.tsx',
    'frontend/src/app/projection/OpexLineYears.tsx',
    'frontend/src/styles/compact-inputs.css',
    'static/react/finco-react.css',
    'static/react/finco-react.js',
))
SOURCE_PATHS = frozenset((
    'app/v2/react_opex_lines.py',
    'app/v2/react_workspace_router.py',
))
TEST_AND_DOC_PATHS = frozenset((
    'tests/test_wf06b_scope.py',
    'docs/react_migration/u2_workbench/D13_PROFILE_LIFECYCLE_CONTRACT.md',
    'docs/react_migration/u2_workbench/D13_PROFILE_LIFECYCLE_PROOF.md',
    'docs/react_migration/u2_workbench/D7_ATOMICITY_DECISION_PACKET.md',
    'docs/react_migration/u2_workbench/FINANCIAL_PARITY_LEDGER.md',
    'docs/react_migration/u2_workbench/G10_DECISION_PACKET.md',
    'docs/react_migration/u2_workbench/GPT6_REVIEW_PACKET.md',
    'docs/react_migration/u2_workbench/OPEN_GAPS.md',
    'docs/react_migration/u2_workbench/P00_U2.md',
    'docs/react_migration/u2_workbench/SAVE_ALL_ATOMICITY_CONTRACT.md',
    'docs/react_migration/u2_workbench/U2_ACCEPTANCE_MATRIX.md',
    'tests/model_react_u2_acceptance.py',
    'tests/test_u2_d13_profile_lifecycle.py',
    'tests/test_u2_opex_lines.py',
    'tests/test_u2_profile_import.py',
    'tests/test_u2_save_atomicity_oracle.py',
    'tests/test_u1_scope.py',
    'tests/test_u2_scope.py',
    'tests/u2_browser_role.py',
))
# Reviewed, bounded hooks in the U1 scope module and the registry; this cohort's own module is owned too.
GOVERNANCE_PATHS = frozenset((
    'tests/fin_v2_cohorts.py',
    'tests/u1_scope.py',
    'tests/u2_scope.py',
))
OWNED_PATHS = PRESENTATION_PATHS | SOURCE_PATHS | TEST_AND_DOC_PATHS | GOVERNANCE_PATHS
# Owned paths that exist at BASE (the U1 cohort pins every one of them at exactly the BASE blob recorded in the manifest).
# ``app/v2/react_workspace_router.py``: the U2 include sits in its own marked section BEFORE the historical RC-M block, so the RC-M
# (exactly its five includes) and RC-UX (exactly ``['_rcux_router']``) sentinel checks are unchanged; admitted only through this cohort's exact pin.
SUPERSEDED = frozenset((
    'tests/test_wf06b_scope.py',
    'app/v2/react_workspace_router.py',
    'frontend/src/app/CostWorkbench.tsx',
    'frontend/src/app/capex/CapexStudio.tsx',
    'frontend/src/app/editing/CostLinesGridView.tsx',
    'frontend/src/styles/compact-inputs.css',
    'static/react/finco-react.css',
    'static/react/finco-react.js',
    'tests/fin_v2_cohorts.py',
    'tests/test_u1_scope.py',     # one bounded successor assertion (later registered + exact cohort's finite set)
    'tests/u1_scope.py',
))
FORBIDDEN_PREFIXES = ('financial_engine/', 'finco_core/', 'domain/', '.github/', 'tools/')
FORBIDDEN_PATHS = frozenset(('main_web.py',))
# Owned by the parallel R1 PR (Save All / PPA lost update): U2 never owns or changes them (mandatory addendum, D7).
R1_PATHS = frozenset((
    'app/v2/save_all_commands.py',
    'frontend/src/app/editing/pendingEdits.ts',
    'frontend/src/app/editing/saveAll.ts',
    'frontend/src/app/editing/wsv2Extensions.tsx',
    'frontend/src/app/editing/ChangesProvider.tsx',
    'frontend/src/app/workflow/PPAEditorView.tsx',
    'frontend/src/app/WorkspaceView.tsx',
))

_CI_EVIDENCE_EXTENSIONS = ('.json', '.xml', '.png', '.webp', '.jpg', '.jpeg', '.txt', '.csv', '.svg', '.html', '.zip')


def _git(root, *args):
    return subprocess.check_output(['git', *args], cwd=root, stderr=subprocess.DEVNULL)


# Immutable git-object facts only: a commit id fixes its tree and the blobs below it for good, so ``rev-parse <BASE commit>^{tree}`` and
# ``rev-parse <BASE commit>:<path>`` can never change. Mutable state (ancestry of the evaluated head, the working tree, the index, modes, untracked
# files, the diff against BASE) is NEVER cached: those are read afresh on every call, so no verdict can outlive the state it judged.
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
                        and data.get('schema_version') == SCHEMA and data.get('base') == BASE and data.get('base_tree') == BASE_TREE) else {}
    except (OSError, ValueError, subprocess.CalledProcessError):
        return {}


def _owned_ok():
    paths = OWNED_PATHS | {MANIFEST}
    return (not any(p.startswith(FORBIDDEN_PREFIXES) or p in FORBIDDEN_PATHS or '..' in p.split('/') or p.startswith('/') or '*' in p for p in paths)
            and SUPERSEDED <= OWNED_PATHS and not (OWNED_PATHS & R1_PATHS))


_SCOPE = []


@contextmanager
def scoped():
    """Within ONE outer governance call ``exact_blobs_ok(root, ref)`` is computed once. Dropped on exit; never keeps bytes."""
    if _SCOPE:
        yield
        return
    _SCOPE.append({})
    try:
        yield
    finally:
        _SCOPE.pop()


# While an enclosing cohort module is inside its one-outer-call scope nothing is written or mutated (that scope's contract), so this verdict shares THAT
# scope's memo: it lives exactly as long as the enclosing outer call, is dropped with it and never outlives or crosses an outer call.
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
        key = (__name__ + '.exact_blobs_ok', str(repo if repo is not None else ROOT), ref)
        if key not in memo:
            memo[key] = _exact_blobs_ok(repo, ref)
        return memo[key]
    key = (str(repo if repo is not None else ROOT), ref)
    memo = _SCOPE[-1]
    if key not in memo:
        memo[key] = _exact_blobs_ok(repo, ref)
    return memo[key]


# Sibling post-#413 data-integrity cohorts (closed, each pinned by its own manifest). Consulted through LOW LEVEL checks only (``allowed_path`` and
# ``exact_blobs_ok`` of the sibling, which never call this module or the registry), so the call stack stays acyclic; nothing is cached across calls.
SIBLING_COHORTS = ('tests.post413_r17_scope', 'tests.post413_r18_scope', 'tests.post413_r1_scope')


def _sibling_owns(path, root, ref):
    import importlib
    for name in SIBLING_COHORTS:
        try:
            m = importlib.import_module(name)
        except ModuleNotFoundError as exc:
            if exc.name != name:
                raise
            continue
        if m.allowed_path(path, root, ref) and m.exact_blobs_ok(root, ref):
            return True
    return False


def _sibling_modules():
    import importlib
    loaded = []
    for name in SIBLING_COHORTS:
        try:
            loaded.append(importlib.import_module(name))
        except ModuleNotFoundError as exc:
            if exc.name != name:
                raise
    return loaded


def _exact_blobs_ok(repo=None, ref=None):
    with ExitStack() as siblings:      # one verdict per sibling cohort for THIS check (dropped on exit; never kept across calls)
        for m in _sibling_modules():
            siblings.enter_context(m.scoped())
        return _exact_blobs_ok_inner(repo, ref)


def _exact_blobs_ok_inner(repo=None, ref=None):
    root = Path(repo) if repo is not None else ROOT
    data = manifest(root, ref)
    pins, base_blobs = data.get('source_blobs', {}), data.get('base_blobs', {})
    if not data or not _owned_ok() or set(pins) != OWNED_PATHS or set(base_blobs) != SUPERSEDED:
        return False
    try:
        head = ref or 'HEAD'
        # 1. immutable provenance: the literal base commit and tree are ancestors of the evaluated head
        _git(root, 'merge-base', '--is-ancestor', BASE, head)
        if _object_fact(root, 'rev-parse', BASE + '^{tree}').decode().strip() != BASE_TREE:
            return False
        # 2. the recorded BASE blob of every superseded path is what git holds at BASE
        paths = sorted(base_blobs)
        if _object_fact(root, 'rev-parse', *[BASE + ':' + p for p in paths]).decode().split() != [base_blobs[p] for p in paths]:
            return False
        # every owned path that is NOT superseded is new at BASE
        new = sorted(OWNED_PATHS - SUPERSEDED)
        at_base = {line.split('\t', 1)[1] for line in _git(root, 'ls-tree', '-r', BASE, '--', *new).decode().splitlines()}
        if at_base:
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
        # 4. nothing outside the literal set changed since BASE; protected prefixes and R1 files can never move
        changed = _git(root, 'diff', '--name-only', '--no-renames', BASE, *([ref] if ref else []), '--').decode().splitlines()
        # A path owned by a REGISTERED, EXACT sibling post-#413 cohort (R17 / R18 / R1) is that cohort's exact-blob responsibility; U2 itself still owns
        # none of the R1 files, and every other stranger path, protected prefix and forbidden path still fails closed.
        if any(((p not in OWNED_PATHS and p != MANIFEST and not _sibling_owns(p, root, ref)) or p.startswith(FORBIDDEN_PREFIXES) or p in FORBIDDEN_PATHS
                or (p in R1_PATHS and not _sibling_owns(p, root, ref))) for p in changed):
            return False
        # 5. no owned file is executable or a link; no unowned untracked file in a working tree
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
    except (OSError, ValueError, KeyError, TypeError, AttributeError, IndexError, subprocess.CalledProcessError):
        return False


def allowed_path(path, repo=None, ref=None):
    return path in OWNED_PATHS or path == MANIFEST


def base_blob(path, repo=None, ref=None):
    """The recorded BASE blob of a superseded path (re-verified against git inside ``exact_blobs_ok``), or ``None``."""
    return manifest(repo, ref).get('base_blobs', {}).get(path)


def supersedes(path, value, repo=None, ref=None):
    """Bounded supersession for U1: true only for a path of ``SUPERSEDED``, only while this cohort is exact, only for its exact pin."""
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
