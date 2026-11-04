"""Closed G10/D8 OPEX-completion cohort: read-only Last-Run OPEX adapter + truthful escalation copy (Draft).

Authority: the G10/D8 owner-decision packet (recommendations only — G10 Option A and D8 Option 1 are built
DRAFT and gated; no owner ratification is implied). Baseline ``BASE`` is main after the merge of PR #419;
it is an ancestor of every head of this cohort, authenticated by commit and tree.

What it owns: a literal, finite path set of NEW files only (no supersession — every changed pre-existing file
is owned and pinned by its own earlier cohort, whose exactness this PR preserves and whose manifests it does
not weaken). Nothing else is admitted: no ``financial_engine/``, ``finco_core/``, ``domain/``, ``.github/``,
``tools/`` or ``main_web.py`` path, no pattern, no wildcard. No R1-owned path (Save All / PPA / Changes) and
no Opus CI V4 path is owned or touched.

Termination: every check is low level — git objects and this cohort's manifest only. No result cache outlives
one outer governance call (``scoped``).
"""
from pathlib import Path
from contextlib import ExitStack, contextmanager
import hashlib
import json
import subprocess

ROOT = Path(__file__).resolve().parents[1]
BASE = 'cd125b5e08302ea1db7169e172fec288aa7acea5'
BASE_TREE = 'a9c14a0dfcc984780cba61bbf58e39e487a8d2fe'
MANIFEST = 'docs/react_migration/g10_d8/G10_D8_EXACT_SOURCE.json'
SCHEMA = 'G10_D8_OPEX_COMPLETION_EXACT_SOURCE_V1'

SOURCE_PATHS = frozenset((
    'app/v2/react_opex_run_projection.py',
    'frontend/src/app/projection/OpexRunProjection.tsx',
))
TEST_AND_DOC_PATHS = frozenset((
    'tests/test_g10_d8_opex_completion.py',
    'tests/test_g10_d8_scope.py',
    'tests/g10_d8_scope.py',
    'docs/react_migration/g10_d8/P00_G10_D8.md',
    'docs/react_migration/g10_d8/OPEX_RUN_AUTHORITY_TRACE.md',
    'docs/react_migration/g10_d8/G10_D8_OWNER_DECISION.md',
    'docs/react_migration/g10_d8/OPEX_RUN_AUTHORITY_TRACE.md',
    'docs/react_migration/g10_d8/G10_D8_OWNER_DECISION.md',
))
# Registered in ``tests/fin_v2_cohorts.py`` (a U2-owned governance path, admitted through U2's governed successor).
GOVERNANCE_PATHS = frozenset((
    'tests/fin_v2_cohorts.py',
))
OWNED_PATHS = SOURCE_PATHS | TEST_AND_DOC_PATHS | GOVERNANCE_PATHS
# Every owned path is NEW at BASE: this cohort supersedes nothing.
SUPERSEDED = frozenset()
FORBIDDEN_PREFIXES = ('financial_engine/', 'finco_core/', 'domain/', '.github/', 'tools/', 'docs/ci_v4/')
FORBIDDEN_PATHS = frozenset(('main_web.py', 'app/v2/save_all_commands.py', 'tests/ci_v4_scope.py'))
# Owned by parallel streams; never touched here (R1 = Save All/PPA; Opus = CI V4).
OTHER_STREAM_PATHS = frozenset((
    'app/v2/save_all_commands.py', 'frontend/src/app/editing/pendingEdits.ts', 'frontend/src/app/editing/saveAll.ts',
    'frontend/src/app/editing/wsv2Extensions.tsx', 'frontend/src/app/editing/ChangesProvider.tsx',
    'frontend/src/app/workflow/PPAEditorView.tsx', 'frontend/src/app/WorkspaceView.tsx',
    '.github/workflows/ci_v4_pr.yml', 'tools/ci_v4_governance_gate.py', 'tools/ci_v4_select.py', 'tests/ci_v4_scope.py',
))

_R1_NOTE = ()
_CI_EXTENSIONS = ('.json', '.xml', '.png', '.webp', '.jpg', '.jpeg', '.txt', '.csv', '.svg', '.html', '.zip')


def _git(root, *args):
    return subprocess.check_output(['git', *args], cwd=root, stderr=subprocess.DEVNULL)


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


def manifest(repo=None, ref=None):
    root = Path(repo) if repo is not None else ROOT
    try:
        data = json.loads(_read(root, MANIFEST, ref))
        return data if (isinstance(data, dict) and isinstance(data.get('source_blobs'), dict)
                        and data.get('schema_version') == SCHEMA and data.get('base') == BASE
                        and data.get('base_tree') == BASE_TREE) else {}
    except (OSError, ValueError, subprocess.CalledProcessError):
        return {}


def _owned_ok():
    paths = OWNED_PATHS | {MANIFEST}
    return (not any(p.startswith(FORBIDDEN_PREFIXES) or p in FORBIDDEN_PATHS or '..' in p.split('/')
                    or p.startswith('/') or '*' in p for p in paths)
            and SUPERSEDED <= OWNED_PATHS and not (OWNED_PATHS & OTHER_STREAM_PATHS))


_SCOPE = []


@contextmanager
def scoped():
    """One outer governance call computes ``exact_blobs_ok`` once; the memo is dropped on exit and never keeps bytes."""
    if _SCOPE:
        yield
        return
    _SCOPE.append({})
    try:
        yield
    finally:
        _SCOPE.pop()


def _exact_blobs_ok(repo=None, ref=None):
    root = Path(repo) if repo is not None else ROOT
    data = manifest(root, ref)
    pins = data.get('source_blobs', {})
    if not data or not _owned_ok() or set(pins) != OWNED_PATHS - {MANIFEST} or data.get('base_blobs', {}) != {}:
        return False
    try:
        head = ref or 'HEAD'
        _git(root, 'merge-base', '--is-ancestor', BASE, head)
        if _git(root, 'rev-parse', BASE + '^{tree}').decode().strip() != BASE_TREE:
            return False
        for path in sorted(SUPERSEDED):  # empty today; kept for the closed-cohort contract
            if _git(root, 'rev-parse', BASE + ':' + path).decode().strip() != data['base_blobs'].get(path):
                return False
        if ref is None:
            if any(_blob(_read(root, p, ref)) != sha for p, sha in pins.items()):
                return False
        else:
            listed = {line.split(' ', 3)[3] for line in
                      _git(root, 'ls-tree', '-r', ref, '--').decode().splitlines() if line}
            if set(pins) - listed:
                return False
            for p, sha in pins.items():
                if _git(root, 'rev-parse', ref + ':' + p).decode().strip() != sha:
                    return False
        # nothing owned may disappear from the evaluated tree
        if ref is not None:
            return True
        return all((root / p).exists() for p in pins)
    except (OSError, ValueError, subprocess.CalledProcessError):
        return False


def exact_blobs_ok(repo=None, ref=None):
    if not _SCOPE:
        return _exact_blobs_ok(repo, ref)
    key = (str(repo if repo is not None else ROOT), ref)
    memo = _SCOPE[-1]
    if key not in memo:
        memo[key] = _exact_blobs_ok(repo, ref)
    return memo[key]


def allowed_path(path, repo=None, ref=None):
    return path in OWNED_PATHS or path == MANIFEST


def base_blob(path, repo=None, ref=None):
    return manifest(repo, ref).get('base_blobs', {}).get(path)


def supersedes(path, value, repo=None, ref=None):
    """This cohort supersedes nothing (all owned paths are new at BASE)."""
    return False


def matches(path, source=None, *, repo=None, ref=None):
    pins = manifest(repo, ref).get('source_blobs', {})
    if path not in pins or not exact_blobs_ok(repo, ref):
        return False
    raw = source.encode() if isinstance(source, str) else source
    return source is None or _blob(raw) == pins[path]


def protected_blobs(repo=None, ref=None):
    return {}  # Never admits a financial_engine, finco_core or domain source.
