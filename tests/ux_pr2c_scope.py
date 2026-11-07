"""UX-PR2c low-level closed successor: stacked on the verified unmerged PR2b head.

Exact blobs/modes/ancestry for the atomic CAPEX amount + monthly profile save
(OD-B2 gated; the flag OFF keeps the PR2b behavior byte-for-byte).  No
predecessor or registry evaluation below ``valid()``.  Superseded paths are
exactly the paths this cohort takes over from UX-PR2b, post413-O1/R1, the
RC-UX completion cohort, the U1/U2 workbenches and the project tree; every
older cohort (and the sibling post-#413 cohorts) keeps describing exactly
what it reviewed: no historical manifest or map is edited to widen anything.

A different current blob for a superseded path is admitted only through
``supersedes(path, blob)`` (reached from ``tests/u1_scope.py`` and the
``effective_pins`` of the direct predecessor), true only while THIS cohort is
exact and only for the exact pin recorded here.  ``scoped()`` memoises one
verdict per outer call and nests the direct predecessor's scope, so the call
graph stays acyclic; nothing is cached across calls.
"""
from pathlib import Path
from contextlib import contextmanager
import hashlib
import json
import subprocess

ROOT = Path(__file__).resolve().parents[1]
BASE = 'f0ead1687bafd41db7472e4009234d0410451210'
BASE_TREE = '584d29ee7873b143e140900c3af714ace2eec645'
MANIFEST = 'docs/react_migration/ux_pr2c/UX_PR2C_EXACT_SOURCE.json'
SCHEMA = 'UX_PR2C_COMBINED_SAVE_EXACT_SOURCE_V1'
OWNED_PATHS = frozenset((
    'P00_PR2C.md',
    'app/v2/react_capex.py',
    'app/v2/react_workspace_router.py',
    'docs/react_migration/ux_pr2c/IMPLEMENTATION.md',
    'frontend/src/app/capex/ProfileDraftProvider.tsx',
    'frontend/src/app/capex/__tests__/pr2cCombinedSave.test.mjs',
    'frontend/src/app/capex/profileDraft.ts',
    'frontend/src/app/capex/profilePublish.ts',
    'frontend/src/app/capex/types.ts',
    'frontend/src/app/editing/pendingEdits.ts',
    'frontend/src/app/editing/saveAll.ts',
    'static/react/finco-react.js',
    'tests/fin_v2_cohorts.py',
    'tests/fin_v2_rcux_scope.py',
    'tests/test_pr2c_combined_contract.py',
    'tests/test_ux_pr2c_scope.py',
    'tests/test_u2_scope.py',
    'tests/u1_scope.py',
    'tests/u2_scope.py',
    'tests/ux_pr2a_scope.py',
    'tests/ux_pr2b_scope.py',
    'tests/ux_pr2c_scope.py',
))
# Paths this cohort takes over from earlier closed cohorts (their historical pins
# move to these same bytes via INTEGRATION_MANIFESTS; nothing else in them changes).
SUPERSEDED = frozenset((
    'app/v2/react_capex.py',
    'app/v2/react_workspace_router.py',
    'frontend/src/app/capex/ProfileDraftProvider.tsx',
    'frontend/src/app/capex/profileDraft.ts',
    'frontend/src/app/capex/types.ts',
    'frontend/src/app/editing/pendingEdits.ts',
    'frontend/src/app/editing/saveAll.ts',
    'static/react/finco-react.js',
    'tests/fin_v2_cohorts.py',
    'tests/fin_v2_rcux_scope.py',
    'tests/test_u2_scope.py',
    'tests/u1_scope.py',
    'tests/u2_scope.py',
    'tests/ux_pr2a_scope.py',
    'tests/ux_pr2b_scope.py',
))
# Sibling manifests whose pins of OWNED paths may move to these same bytes
# (nothing else in them may change).
INTEGRATION_MANIFESTS = frozenset((
    'docs/ci_v4/SOURCE_SUCCESSOR.json',
    'docs/react_migration/g10_d8/G10_D8_EXACT_SOURCE.json',
    'docs/react_migration/post413_o1/SOURCE_SUCCESSOR.json',
    'docs/react_migration/post413_r1/SOURCE_SUCCESSOR.json',
    'docs/react_migration/post413_r17/SOURCE_SUCCESSOR.json',
    'docs/react_migration/post413_r18/SOURCE_SUCCESSOR.json',
    'docs/react_migration/rc_ux_completion/SOURCE_SUCCESSOR.json',
    'docs/react_migration/u1_workbench/SOURCE_SUCCESSOR.json',
    'docs/react_migration/u2_workbench/U2_EXACT_SOURCE.json',
    'docs/react_migration/ux_pr2b/UX_PR2B_EXACT_SOURCE.json',
))
FORBIDDEN_PREFIXES = ('financial_engine/', 'finco_core/', 'domain/', '.github/', 'migrations/', 'schemas/')
FORBIDDEN_PATHS = frozenset(('main_web.py', 'frontend/src/app/workflow/PPAEditorView.tsx',
                             'app/v2/save_all_commands.py', 'app/capex_profiles/service.py',
                             'app/v2/grid_router.py', 'app/v2/cost_batch_commands.py'))


def _git(root, *args):
    return subprocess.check_output(['git', *args], cwd=root, stderr=subprocess.DEVNULL)


_OBJECT_FACTORS = {}


def _base_fact(root, *args):
    key = (str(root),) + args
    if key not in _OBJECT_FACTORS:
        _OBJECT_FACTORS[key] = _git(root, *args)
    return _OBJECT_FACTORS[key]


def _read(root, path, ref):
    return (Path(root) / path).read_bytes() if ref is None else _git(root, 'show', ref + ':' + path)


# CI generates untracked evidence before F01/static attribution. Follow the same finite
# artifact types as U2 / UX-PR2b; this never admits a changed tracked file or source.
_CI_EVIDENCE_EXTENSIONS = ('.json', '.xml', '.png', '.webp', '.jpg', '.jpeg', '.txt', '.csv', '.svg', '.html', '.zip')


def _ci_evidence_only(root, path):
    f = Path(root) / path
    return (path.startswith('evidence/') and path.endswith(_CI_EVIDENCE_EXTENSIONS)
            and f.is_file() and not f.is_symlink() and not f.stat().st_mode & 0o111)


def _blob(raw):
    return hashlib.sha1(b'blob ' + str(len(raw)).encode() + b'\0' + raw).hexdigest()


def manifest(repo=None, ref=None):
    try:
        d = json.loads(_read(Path(repo) if repo is not None else ROOT, MANIFEST, ref))
        return d if (set(d) == {'base', 'base_tree', 'schema_version', 'source_blobs', 'base_blobs'}
                     and d.get('schema_version') == SCHEMA and d.get('base') == BASE
                     and d.get('base_tree') == BASE_TREE) else {}
    except (OSError, ValueError, AttributeError, subprocess.CalledProcessError):
        return {}


_SCOPE = []


@contextmanager
def scoped():
    if _SCOPE:
        yield
        return
    _SCOPE.append({})
    try:
        yield
    finally:
        _SCOPE.pop()


def _pr2b():
    try:
        from tests import ux_pr2b_scope as S
        return S
    except ImportError:
        return None




def exact_blobs_ok(repo=None, ref=None):
    key = (str(repo if repo is not None else ROOT), ref)
    if not _SCOPE:
        with scoped():
            return exact_blobs_ok(repo, ref)
    if key not in _SCOPE[-1]:
        _SCOPE[-1][key] = _exact_blobs_ok(repo, ref)
    return _SCOPE[-1][key]


def _exact_blobs_ok(repo=None, ref=None):
    root = Path(repo) if repo is not None else ROOT
    try:
        d = manifest(repo, ref)
        if not d:
            return False
        pins = d.get('source_blobs', {})
        if set(pins) != OWNED_PATHS or set(d.get('base_blobs', {})) != set(SUPERSEDED):
            return False
        _git(root, 'merge-base', '--is-ancestor', BASE, ref or 'HEAD')
        if _base_fact(root, 'rev-parse', BASE + '^{tree}').decode().strip() != BASE_TREE:
            return False
        baseline = {}
        for line in _base_fact(root, 'ls-tree', '-r', BASE, '--', *sorted(OWNED_PATHS)).decode().splitlines():
            _, _, sha, path = line.split(None, 3)
            baseline[path] = sha
        if baseline != d['base_blobs']:
            return False
        for path, sha in pins.items():
            if _blob(_read(root, path, ref)) != sha:
                return False
        # Sibling manifests: only moved pins of paths this cohort owns may change.
        for sibling in INTEGRATION_MANIFESTS:
            before = json.loads(_base_fact(root, 'show', BASE + ':' + sibling))
            now = json.loads(_read(root, sibling, ref))
            if set(now) != set(before) or any(now[k] != before[k] for k in before if k != 'source_blobs'):
                return False
            old, new = before['source_blobs'], now['source_blobs']
            if any(new[p] != old[p] and (p not in pins or new[p] != pins[p]) for p in old):
                return False
        changed = _git(root, 'diff', '--name-only', '--no-renames', BASE,
                       *([ref] if ref else []), '--').decode().splitlines()
        if set(changed) - (OWNED_PATHS | INTEGRATION_MANIFESTS | {MANIFEST}):
            return False
        if ref is None:
            untracked = set(_git(root, 'ls-files', '--others', '--exclude-standard').decode().splitlines()) - \
                (OWNED_PATHS | INTEGRATION_MANIFESTS | {MANIFEST})
            if any(not _ci_evidence_only(root, p) for p in untracked):
                return False
        else:
            modes = _git(root, 'ls-tree', '-r', ref, '--', *sorted(OWNED_PATHS | {MANIFEST})).decode().splitlines()
            if len(modes) != len(OWNED_PATHS) + 1 or any(not line.startswith('100644 ') for line in modes):
                return False
        return True
    except (OSError, ValueError, KeyError, TypeError, AttributeError, subprocess.CalledProcessError):
        return False


def allowed_path(path, repo=None, ref=None):
    return path in OWNED_PATHS | INTEGRATION_MANIFESTS | {MANIFEST}


def base_blob(path, repo=None, ref=None):
    return manifest(repo, ref).get('base_blobs', {}).get(path)


def supersedes(path, value, repo=None, ref=None):
    return path in SUPERSEDED and exact_blobs_ok(repo, ref) and manifest(repo, ref).get('source_blobs', {}).get(path) == value


def valid(repo=None, ref=None):
    from tests.fin_v2_cohorts import valid as composite_valid
    return exact_blobs_ok(repo, ref) and composite_valid(repo, ref)


def matches(path, source=None, *, repo=None, ref=None):
    pins = manifest(repo, ref).get('source_blobs', {})
    raw = source.encode() if isinstance(source, str) else source
    return path in pins and valid(repo, ref) and (source is None or _blob(raw) == pins[path])


def protected_blobs(repo=None, ref=None):
    return {}


