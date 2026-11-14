"""Closed Workstream-B exact-source cohort (O1 + G7 + G-U2-1 + D7): server-derived document tokens, new-line amount validation, ledger-verified generated
profile keys and the (not enabled) atomic Save All profile document. A bounded successor over main after PR #420/#422 (CI V4 rules v2).

Authority: the Financial Owner's Workstream-B brief of 2026-11-04 allows DRAFT implementation; it does NOT approve OD-B1 (strict token), O-G7, O-G-U2-1 or
OD-B2 (D7). Every proposed behaviour is off by default or additive. This cohort is provenance only: it is not a financial approval, not a general waiver
and not a financial-engine change. No ``financial_engine/``, ``finco_core/``, ``domain/``, ``.github/``, ``tools/`` or ``main_web.py`` path is ever owned.

``BASE`` is the merge of PR #422 (main). It is an ancestor of every head of this cohort, authenticated by commit, tree AND the recorded BASE blob of
every path this cohort supersedes, so every older cohort (and the sibling post-#413 cohorts) keep describing exactly what they reviewed: no historical
manifest was edited to authorise different bytes. The few shared, jointly pinned post-#413 blobs (the registry, the U1 hook module, the rebuilt bundle and the
PPA editor modules) are re-pinned to the SAME literal blob in every sibling manifest that already pinned them (R17, R18, R1, U2, CI V4), exactly as the
earlier integration commits did; ``tests/test_post413_o1_scope.py`` proves each such pin equals this cohort's pin and that no other pin moved.

What it owns: a literal, finite path set. Nothing else is admitted: no pattern, no wildcard. It does NOT police the paths it does not own: the composite
registry (``tests/fin_v2_cohorts.py``) requires every changed path to be allowed by at least one registered cohort, so sibling cohorts compose.

Supersession (``SUPERSEDED``): the owned paths that exist at BASE and are pinned at their BASE blob by an older or sibling cohort. An older cohort accepts a
different current blob for such a path only through ``supersedes(path, blob)`` (reached from ``tests/u1_scope.py``), true only while THIS cohort is exact and
pins exactly that blob. It never admits a value for a path outside ``SUPERSEDED``.

Termination: every check is low level. It reads git objects and this cohort's manifest only; it never calls an older cohort or the registry (the composite
``valid`` imports the registry lazily and is never called from a low level check), so there is no recursive self-approval. ``scoped()`` memoises one verdict
per outer governance call and is dropped on exit; no verdict outlives an outer call.
"""
from pathlib import Path
from contextlib import contextmanager
import hashlib
import json
import subprocess

ROOT = Path(__file__).resolve().parents[1]
BASE = 'a059635e3a5b022dcf779aab80bd5c46d12cadcc'
BASE_TREE = '98ec006765f09f1fde6e9321c7e410d322af83c6'
MANIFEST = 'docs/react_migration/post413_o1/SOURCE_SUCCESSOR.json'
SCHEMA = 'POST413_O1_WORKSTREAM_B_EXACT_SOURCE_V1'

SOURCE_PATHS = frozenset((
    'app/capex_profiles/config.py',
    'app/capex_profiles/runtime.py',
    'app/capex_profiles/service.py',
    'app/templates/v2/partials/bess_workspace.html',
    'app/templates/v2/partials/revenue_contracts.html',
    'app/v2/bess_workspace_router.py',
    'app/v2/capex_commands.py',
    'app/v2/capex_router.py',
    'app/v2/grid_router.py',
    'app/v2/opex_commands.py',
    'app/v2/opex_router.py',
    'app/v2/router.py',
    'app/v2/save_all_commands.py',
    'app/workbook/revenue_contracts_service.py',
    'frontend/src/app/api.ts',
    'frontend/src/app/editing/pendingEdits.ts',
    'frontend/src/app/editing/saveAll.ts',
    'frontend/src/app/workflow/PPAEditorView.tsx',
    'static/react/finco-react.js',
))
TEST_AND_DOC_PATHS = frozenset((
    'docs/react_migration/post413_o1/FINAL_REPORT_HR.md',
    'docs/react_migration/post413_o1/G7_GU2_KEY_LEDGER.md',
    'docs/react_migration/post413_o1/O1_D7_COMBINED_CONTRACT.md',
    'docs/react_migration/post413_o1/OWNER_DECISIONS_PENDING_HR.md',
    'docs/react_migration/post413_o1/TWO_WRITER_AND_FAULT_ORACLE.md',
    'frontend/src/app/editing/__tests__/editing.test.mjs',
    'tests/test_d7_save_all_profile_atomic.py',
    'tests/test_g7_add_line_amount.py',
    'tests/test_g_u2_1_generated_profile_keys.py',
    'tests/test_o1_bess_contracts_token.py',
    'tests/test_o1_contracts_base_token.py',
    'tests/test_post413_o1_scope.py',
    'tests/test_post413_r17_scope.py',
    'tests/test_post413_r18_scope.py',
    'tests/test_post413_r1_scope.py',
    'tests/test_rcux_governance.py',
    'tests/test_u1_scope.py',
    'tests/test_u2_scope.py',
    'tests/test_wf06b_scope.py',
))
# Reviewed, bounded hooks in the PR-U1 scope module and the registry (each pinned below). This cohort's own module is owned too.
GOVERNANCE_PATHS = frozenset((
    'tests/fin_v2_cohorts.py',
    'tests/post413_o1_scope.py',
    'tests/u1_scope.py',
    'tests/u2_scope.py',
))
OWNED_PATHS = SOURCE_PATHS | TEST_AND_DOC_PATHS | GOVERNANCE_PATHS
# Owned paths that exist at BASE and that another cohort pins at that BASE blob (older guards, sibling post-#413 cohorts). Each BASE blob is recorded in the
# manifest and re-verified against git. Paths no cohort pins (e.g. the CAPEX/OPEX routers) are owned for the composite path check only.
SUPERSEDED = frozenset((
    'app/v2/capex_commands.py',
    'app/v2/grid_router.py',
    'app/v2/router.py',
    'app/v2/save_all_commands.py',
    'app/workbook/revenue_contracts_service.py',
    'frontend/src/app/api.ts',
    'frontend/src/app/editing/__tests__/editing.test.mjs',
    'frontend/src/app/editing/pendingEdits.ts',
    'frontend/src/app/editing/saveAll.ts',
    'frontend/src/app/workflow/PPAEditorView.tsx',
    'static/react/finco-react.js',
    'tests/fin_v2_cohorts.py',
    'tests/u1_scope.py',
    'tests/u2_scope.py',
    'tests/test_post413_r17_scope.py',
    'tests/test_post413_r18_scope.py',
    'tests/test_post413_r1_scope.py',
    'tests/test_rcux_governance.py',
    'tests/test_u1_scope.py',
    'tests/test_u2_scope.py',
    'tests/test_wf06b_scope.py',
))
# No owned path may ever sit under a protected prefix; this is checked on the literal set.
FORBIDDEN_PREFIXES = ('financial_engine/', 'finco_core/', 'domain/', '.github/', 'tools/')
FORBIDDEN_PATHS = frozenset(('main_web.py',))

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
    return (not any(p.startswith(FORBIDDEN_PREFIXES) or p in FORBIDDEN_PATHS or '..' in p.split('/') or p.startswith('/') for p in OWNED_PATHS | {MANIFEST})
            and SUPERSEDED <= OWNED_PATHS)


_SCOPE = []


@contextmanager
def scoped():
    """Within ONE outer governance call the result of ``exact_blobs_ok(root, ref)`` is computed once. Dropped on exit; never keeps bytes."""
    if _SCOPE:        # a nested enter shares the outermost memo (never outlives the outermost exit, never shared between separate outer calls)
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
        if _object_fact(root, 'rev-parse', BASE + '^{tree}').decode().strip() != BASE_TREE:
            return False
        # 2. the blob recorded for every superseded path is what git holds at BASE (#413); history is not rewritten here
        paths = sorted(base_blobs)
        if _object_fact(root, 'rev-parse', *[BASE + ':' + p for p in paths]).decode().split() != [base_blobs[p] for p in paths]:
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
        # 4. no protected prefix ever moved since BASE (paths this cohort does not own are the composite registry's responsibility)
        # Only the protected subtrees can fail this check, so the diff is limited to them (same verdict as the whole-tree diff, without a full stat of the checkout).
        changed = _git(root, 'diff', '--name-only', '--no-renames', BASE, *([ref] if ref else []), '--',
                       *[p.rstrip('/') for p in FORBIDDEN_PREFIXES], *sorted(FORBIDDEN_PATHS)).decode().splitlines()
        # CI V4 (Owner CI policy 2026-11-04): a literal CI V4 path of the exact, low-level CI V4 cohort is the only admitted .github/ or tools/ move.
        if any((p.startswith(FORBIDDEN_PREFIXES) or p in FORBIDDEN_PATHS) and not _ci_v4_owns(p, root, ref) for p in changed):
            return False
        # 5. no owned file is executable or a link in the evaluated state
        if ref is None:
            for p in OWNED_PATHS | {MANIFEST}:
                f = root / p
                if f.is_symlink() or (f.exists() and f.stat().st_mode & 0o111):
                    return False
        else:
            modes = _git(root, 'ls-tree', '-r', ref, '--', *sorted(OWNED_PATHS | {MANIFEST})).decode().splitlines()
            if any(not line.startswith('100644 ') for line in modes):
                return False
        return True
    except (OSError, ValueError, KeyError, TypeError, AttributeError, subprocess.CalledProcessError):
        return False


def _ci_v4_owns(path, root, ref):
    """Only a literal CI V4 path (``.github/workflows/ci_v4_*`` / ``tools/ci_v4_*`` listed in ``tests/ci_v4_scope.CI_PATHS``) while that cohort is
    exact. The CI V4 cohort is low level (git objects and its own manifest only) and never imports this module, so the call graph stays acyclic."""
    if not path.startswith(('.github/', 'tools/')):
        return False
    try:
        from tests import ci_v4_scope
    except ModuleNotFoundError:
        return False
    return ci_v4_scope.ci_owns(path, root, ref)


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
