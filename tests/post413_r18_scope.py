"""Closed R18 atomic reference clone exact-source cohort (PR #416): a data-integrity successor over the merged PR #413 main.

Authority: Financial Owner authorisation of 2026-11-03 (post-#413 data-integrity corrections): a bounded, literal, authenticated successor; not a general
waiver, no financial methodology change, no engine, schema or workflow change.

``BASE`` is the merge of PR #413 (main). It is an ancestor of every head of this cohort, authenticated by commit, tree AND the recorded BASE blob of every
path this cohort supersedes, so the PR-U1 cohort and every older cohort stay exactly as they were reviewed: none of their manifests was edited.

What it owns: a literal, finite path set (the reference seed service of the atomic clone fix, its regression tests and the reviewed bounded hooks). Nothing else is admitted: no ``financial_engine/``,
``finco_core/``, ``domain/``, ``.github/``, ``tools/`` or ``main_web.py`` path, no pattern, no wildcard. It does NOT police the paths it does not own: the
composite registry (``tests/fin_v2_cohorts.py``) requires every changed path to be allowed by at least one registered cohort, so sibling post-#413 cohorts compose.

Supersession (``SUPERSEDED``): the owned paths that exist at BASE. An older cohort accepts a different current blob for such a path only through
``supersedes(path, blob)`` (reached from ``tests/u1_scope.py``), which is true only while THIS cohort is exact and pins exactly that blob.

Termination: every check is low level. It reads git objects and this cohort's manifest only; it never calls an older cohort or the cohort registry
(the composite ``valid`` imports the registry lazily and is never called from a low level check). ``scoped()`` memoises one verdict per outer governance
call and is dropped on exit; no verdict outlives an outer call.
"""
from pathlib import Path
from contextlib import contextmanager
import hashlib
import json
import subprocess

ROOT = Path(__file__).resolve().parents[1]
BASE = '2c63750929477c618444e9d056030e054cc3a41c'
BASE_TREE = 'e7869fc8f4775b5ae62a5c75be60f2efef2cfd79'
MANIFEST = 'docs/react_migration/post413_r18/SOURCE_SUCCESSOR.json'
SCHEMA = 'POST413_R18_EXACT_SOURCE_V1'

SOURCE_PATHS = frozenset((
    'app/services/reference_seed_service.py',
))
TEST_AND_DOC_PATHS = frozenset((
    'tests/test_wf06b_scope.py',
    'tests/test_u1_scope.py',
    'docs/react_migration/post413_r18/P00.md',
    'tests/test_post413_r18_scope.py',
    'tests/test_r18_atomic_reference_clone.py',
))
# Reviewed, bounded hooks in the PR-U1 scope module and the registry (each pinned below). This cohort's own module is owned too.
GOVERNANCE_PATHS = frozenset((
    'tests/fin_v2_cohorts.py',
    'tests/post413_r18_scope.py',
    'tests/u1_scope.py',
))
OWNED_PATHS = SOURCE_PATHS | TEST_AND_DOC_PATHS | GOVERNANCE_PATHS
# Owned paths that exist at BASE. Older cohorts pin these at their BASE blob; the BASE blob of each is recorded in the manifest and re-verified.
SUPERSEDED = frozenset((
    'tests/test_wf06b_scope.py',
    'tests/test_u1_scope.py',
    'app/services/reference_seed_service.py',
    'tests/fin_v2_cohorts.py',
    'tests/u1_scope.py',
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
            if any(_blob(_read(root, p, ref)) != sha and not _ux_pin(p, _blob(_read(root, p, ref)), root, ref) for p, sha in pins.items()):
                return False
        else:
            listed = {}
            for line in _git(root, 'ls-tree', '-r', ref, '--', *sorted(pins)).decode().splitlines():
                meta, name = line.split('\t', 1)
                listed[name] = meta.split()[2]
            if set(listed) != set(pins) or any(listed[p] != pins[p] and not _ux_pin(p, listed[p], root, ref) for p in pins):
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


def _ux_pin(path, blob, root, ref):
    """UX-FINAL-01: the finite signed successor chain (C06 forwards to it) may move this exact pin; history and every other pin stay unchanged."""
    from tests import ux_final01_scope as UX
    if path not in UX.SUPERSEDED:
        return False
    from tests import c06_cost_workspace_scope as C06
    return C06.signature_ok(root, ref) and C06.supersedes(path, blob, root, ref)


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
