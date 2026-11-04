"""Exact-source integration seal for PR #409: WF-06A (#406) + FIN-TRUTH-B1 (#407) + ON-08 OD-1(A) (#408) over main ``ebf1f151``.

Each of the three PRs ships a closed single-PR seal ("my delta is the only delta"). This low-level module authorises exactly their union and nothing
else. It imports NO other cohort (no recursion with ``tests.fin_v2_cohorts``); other cohorts delegate to it only through the literal, bounded
functions ``allowed_path`` and ``admits_pin`` below, and only while ``exact_blobs_ok`` holds.

What it authenticates (all from immutable git objects, never from a branch name):
  1. the literal main commit/tree and the three literal PR head commits/trees, each an ancestor of the evaluated head;
  2. the authorised path set = diff(main, each PR head) united over the three heads + the literal ``PINNED_PATHS`` + ``SEAL_PATHS`` (no prefix, no wildcard);
  3. every path touched by exactly one PR and not in ``PINNED_PATHS`` has exactly that PR head's blob;
  4. every path in ``PINNED_PATHS`` has exactly the one blob pinned in the manifest, backed by a ledger row whose before/PR blobs equal git;
  5. every overlapping predecessor manifest keeps main's identity keys, every ``historical_source_blobs`` entry and the whole ``path_ledger`` prefix;
  6. nothing changed since main outside that set (so ``financial_engine/``, ``finco_core/``, ``domain/``, ``.github/`` can never move), no untracked source.
"""
from __future__ import annotations

import hashlib
import json
import subprocess
from contextlib import contextmanager
from functools import lru_cache
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
MAIN = 'ebf1f15113ec95d69d29e8aa4e4635686dd1f39a'
MAIN_TREE = '45e8efdd7e8b0fa8df6497c4e9510a7a27815f85'
SOURCES = {
    'PR406': ('500772e0bc865283e86bce36b070ba51b77dcd0b', '39957b6665d7d8e9b7ae614997af04525dc9b2bb'),
    'PR407': ('e985225acad51aa70401d30ddc50e740d2aac4df', 'a83917d49f7348fd8be316a288c6132f219d6941'),
    'PR408': ('67d75426043409730ee948200a61e7a70d42524f', 'f82ce5aef63b7f3560e61f7d2b8ee69f0ece6696'),
}
MANIFEST = 'docs/react_migration/fin_v2_integration_409/SOURCE_SUCCESSOR.json'
SCHEMA = 'FIN_V2_INTEGRATION_409_V1'
SEAL_PATHS = frozenset((
    MANIFEST,
    'tests/fin_v2_integration_409_scope.py',
    'tests/test_fin_v2_integration_409_scope.py',
    'docs/react_migration/fin_v2_integration_409/PR409_CORRECTION_A_EXACT_HEAD_REPORT.md',
))
# Paths whose integrated bytes legitimately differ from every single PR (touched by several PRs, or re-pinned / hooked for the composition).
# The manifest must pin exactly this set; adding a path here is a reviewed source change (this module is itself pinned by the WF-03 cohort).
PINNED_PATHS = frozenset((
    # touched by two or three of the PRs
    'docs/financial_validation/finv2_d01_d02/SOURCE_SUCCESSOR.json',
    'docs/financial_validation/wf04_debt_metrics/SOURCE_SUCCESSOR.json',
    'docs/react_migration/wf03_project_lifecycle/SOURCE_SUCCESSOR.json',
    'docs/react_migration/wsv2_core/SOURCE_SUCCESSOR.json',
    'tests/wf03_lifecycle_scope.py',
    # WF-06A's own manifest pins the live blobs of the overlapping files; scope modules receive the bounded delegation hooks
    'docs/react_migration/wf06a_ux/SOURCE_SUCCESSOR.json',
    'docs/financial_validation/fin_v2_r1/SOURCE_SUCCESSOR.json',
    'tests/fin_v2_cohorts.py',
    'tests/fin_v2_wf06a_scope.py',
    'tests/wf04_scope.py',
    'tests/wsv2_core_scope.py',
    # stand-alone negative/lineage tests of the older cohorts, made composition-aware without weakening them
    'tests/test_fin_v2_wf06a_scope.py',
    'tests/fin_truth_b1/test_source_successor.py',
    # B1's own seal: only its CURRENT pin of the test above follows the file; its historical maps and correction history are untouched
    'docs/financial_validation/fin_truth_b1/SOURCE_SUCCESSOR.json',
))
# Predecessor manifests that several PRs edit: their identity, history maps and ledger prefix must survive from main exactly.
HISTORY_MANIFESTS = (
    'docs/financial_validation/finv2_d01_d02/SOURCE_SUCCESSOR.json',
    'docs/financial_validation/wf04_debt_metrics/SOURCE_SUCCESSOR.json',
    'docs/react_migration/wf03_project_lifecycle/SOURCE_SUCCESSOR.json',
    'docs/react_migration/wsv2_core/SOURCE_SUCCESSOR.json',
)
BASE = MAIN
OWNED_PATHS = PINNED_PATHS | SEAL_PATHS
# Generated CI evidence (same closed rule as the older cohorts): untracked, under evidence/, non-executable extension only.
_CI_EVIDENCE_EXTENSIONS = ('.json', '.xml', '.png', '.webp', '.jpg', '.jpeg', '.txt', '.csv', '.svg', '.html', '.zip')


def _ci_evidence_only(path):
    return path.startswith('evidence/') and path.endswith(_CI_EVIDENCE_EXTENSIONS)


_PROTECTED_PREFIXES = ('financial_engine/', 'finco_core/', 'domain/', '.github/')


def _git(root, *args):
    return subprocess.check_output(['git', *args], cwd=root, stderr=subprocess.DEVNULL)


def _read(root, path, ref):
    return (Path(root) / path).read_bytes() if ref is None else _git(root, 'show', f'{ref}:{path}')


def _blob(raw: bytes) -> str:
    return hashlib.sha1(b'blob ' + str(len(raw)).encode() + b'\0' + raw).hexdigest()


def _rev(root, spec):
    try:
        return _git(root, 'rev-parse', spec).decode().strip()
    except subprocess.CalledProcessError:
        return None


def manifest(repo=None, ref=None):
    root = Path(repo) if repo is not None else ROOT
    try:
        data = json.loads(_read(root, MANIFEST, ref))
    except (OSError, ValueError, subprocess.CalledProcessError):
        return {}
    ok = (data.get('schema_version') == SCHEMA and data.get('main') == MAIN and data.get('main_tree') == MAIN_TREE
          and data.get('sources') == {k: {'head': h, 'tree': t} for k, (h, t) in SOURCES.items()})
    return data if ok else {}


def _union(root):
    """Paths touched by each authenticated PR head relative to main: {path: [owner,...]}. Derived from immutable commits only, so cached."""
    return {k: list(v) for k, v in _union_cached(str(root)).items()}


@lru_cache(maxsize=8)
def _union_cached(root):
    owners = {}
    for name, (head, _tree) in SOURCES.items():
        for path in _git(root, 'diff', '--name-only', '--no-renames', MAIN, head, '--').decode().splitlines():
            owners.setdefault(path, []).append(name)
    return {k: tuple(v) for k, v in owners.items()}


_RESULTS = {}


@lru_cache(maxsize=4096)
def _immutable_blob(root, sha, path):
    """Blob of ``path`` at an immutable commit (None if absent). Commits never change, so this is cached for the process."""
    return _rev(Path(root), f'{sha}:{path}')


def _state_key(root, ref):
    """A key that changes whenever ANY byte of the evaluated state changes.

    An explicit ref is an immutable commit. For the working tree the key is HEAD + the hash of every tracked difference (``git diff HEAD --binary``,
    staged or not, including deletions and mode changes) + the names and contents of every untracked file, so one flipped byte anywhere yields a new
    key and the exact check runs again. A cached verdict is therefore never reused for different bytes."""
    if ref is not None:
        sha = _rev(root, ref + '^{commit}')
        return None if sha is None else ('ref', str(root), sha)
    head = _rev(root, 'HEAD')
    digest = hashlib.sha1(_git(root, 'diff', 'HEAD', '--no-ext-diff', '--binary', '--')).hexdigest()
    names = _git(root, 'ls-files', '--others', '--exclude-standard', '-z').split(b'\0')
    untracked = hashlib.sha1()
    for name in sorted(n for n in names if n):
        untracked.update(name + b'\0')
        try:
            untracked.update((Path(root) / name.decode()).read_bytes())
        except OSError:
            untracked.update(b'<unreadable>')
    return ('wt', str(root), head, digest, untracked.hexdigest())


_SCOPE = []


def exact_blobs_ok(repo=None, ref=None):
    root = Path(repo) if repo is not None else ROOT
    if _SCOPE:       # one outer governance call (single-threaded, nothing is written meanwhile): the same call-scope memo the older cohorts use
        memo = _SCOPE[-1]
        skey = (str(root), ref)
        if skey not in memo:
            memo[skey] = _cached_exact(root, repo, ref)
        return memo[skey]
    return _cached_exact(root, repo, ref)


def _cached_exact(root, repo, ref):
    try:
        key = _state_key(root, ref)
    except (OSError, subprocess.CalledProcessError):
        return False
    if key is None:
        return False
    if key not in _RESULTS:
        if len(_RESULTS) > 64:
            _RESULTS.clear()
        _RESULTS[key] = _exact_blobs_ok(repo, ref)
    return _RESULTS[key]


@contextmanager
def scoped():
    """Within ONE outer governance call the verdict is computed once. Dropped on exit; never keeps bytes; never shared between separate outer
    calls. A nested ``scoped()`` enter (the composite registry and the older guards' outer calls) SHARES the outermost memo instead of pushing a
    fresh one, so one outer operation computes each verdict at most once however deep the delegation."""
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
    if not data or set(pins) != PINNED_PATHS | (SEAL_PATHS - {MANIFEST}):
        return False
    try:
        head = ref or 'HEAD'
        # 1. immutable provenance: literal commits/trees, all ancestors of the evaluated head
        if _rev(root, MAIN + '^{tree}') != MAIN_TREE:
            return False
        _git(root, 'merge-base', '--is-ancestor', MAIN, head)
        for _name, (sha, tree) in SOURCES.items():
            if _rev(root, sha + '^{commit}') != sha or _rev(root, sha + '^{tree}') != tree:
                return False
            _git(root, 'merge-base', '--is-ancestor', sha, head)
        owners = _union(root)
        # 4. one exact blob per pinned path, backed by a verified ledger row
        if any(_blob(_read(root, p, ref)) != b and not _wf06b_supersedes(p, _blob(_read(root, p, ref)), root, ref) for p, b in pins.items()):
            return False
        ledger = {row.get('path'): row for row in data.get('repin_ledger', [])}
        if set(ledger) != PINNED_PATHS or len(data.get('repin_ledger', [])) != len(PINNED_PATHS):
            return False
        for path, row in ledger.items():
            expected = {'path': path, 'base_blob': _rev(root, f'{MAIN}:{path}'), 'owner_prs': sorted(owners.get(path, [])),
                        'integrated_blob': pins[path]}
            for name, (sha, _t) in SOURCES.items():
                expected[name.lower() + '_blob'] = _immutable_blob(str(root), sha, path)
            if any(row.get(k) != v for k, v in expected.items()) or not row.get('resolution'):
                return False
        # 3. every other path touched by exactly one PR is that PR's reviewed bytes
        for path, who in owners.items():
            if path in PINNED_PATHS or path in SEAL_PATHS:
                continue
            if len(who) != 1:
                return False
            if _blob(_read(root, path, ref)) != _immutable_blob(str(root), SOURCES[who[0]][0], path) and not _wf06b_supersedes(path, _blob(_read(root, path, ref)), root, ref):
                return False
        # 5. historical preservation of the shared predecessor manifests
        for path in HISTORY_MANIFESTS:
            old = json.loads(_read(root, path, MAIN))
            cur = json.loads(_read(root, path, ref))
            if any(cur.get(k) != old.get(k) for k in ('schema_version', 'base', 'base_tree', 'parent', 'parent_tree') if k in old):
                return False
            old_hist, cur_hist = old.get('historical_source_blobs', {}), cur.get('historical_source_blobs', {})
            if any(cur_hist.get(k) != v for k, v in old_hist.items()):
                return False
            old_ledger, cur_ledger = old.get('path_ledger', []), cur.get('path_ledger', [])
            if cur_ledger[:len(old_ledger)] != old_ledger:
                return False
        # 6. nothing outside the authorised finite set changed since main; protected prefixes can never move
        allowed = set(owners) | PINNED_PATHS | SEAL_PATHS
        changed = _git(root, 'diff', '--name-only', '--no-renames', MAIN, *([ref] if ref else []), '--').decode().splitlines()
        if any((p not in allowed and not _wf06b_allows(p, root, ref)) or (p.startswith(_PROTECTED_PREFIXES) and not _wf06b_ci_owns(p, root, ref)) for p in changed):
            return False
        if ref is None:
            untracked = _git(root, 'ls-files', '--others', '--exclude-standard').decode().splitlines()
            if any(p not in allowed and not _ci_evidence_only(p) and not _wf06b_allows(p, root, ref) for p in untracked):
                return False
        return True
    except (OSError, ValueError, KeyError, TypeError, AttributeError, subprocess.CalledProcessError):
        return False


def _wf06b_ci_owns(path, root, ref):
    """CI V4 (Owner CI policy 2026-11-04): only a literal CI V4 ``.github/`` path, through WF-06B -> U1 -> the exact low-level CI V4 cohort."""
    try:
        from tests import wf06b_scope as W
    except ModuleNotFoundError:
        return False
    return callable(getattr(W, '_u1_ci_owns', None)) and W._u1_ci_owns(path, root, ref)


def _wf06b_supersedes(path, value, root, ref):
    """Bounded WF-06B hook (PR #410, Owner decision WF06B-D3): a different current blob is accepted for ``path`` only while the closed WF-06B cohort
    (tests/wf06b_scope.py) is itself exact and pins exactly this value. The cohort check is low level (never calls this module); a missing, forged or
    altered cohort admits nothing, and the pin held here still describes the reviewed state it always did."""
    try:
        from tests import wf06b_scope as W
    except ImportError:
        return False
    return W.supersedes(path, value, root, ref)


def _wf06b_allows(path, root, ref):
    """Bounded WF-06B hook: a path of the closed WF-06B cohort, only while that cohort is itself exact."""
    try:
        from tests import wf06b_scope as W
    except ImportError:
        return False
    return W.allowed_path(path, root, ref) and W.exact_blobs_ok(root, ref)


def _wf06a_owned():
    """Paths the closed WF-06A cohort owns (its literal constants only; no cohort function is called, so no recursion). ``None`` = cohort absent."""
    try:
        from tests import fin_v2_wf06a_scope as W6
    except ImportError:
        return None
    return frozenset(W6.OWNED_PATHS) | {W6.MANIFEST}


def _delegable(path):
    """Delegation precedence (PR #409 Correction B): a path the WF-06A cohort owns is authorised ONLY by that cohort (which must itself be exact);
    this seal never substitutes for a missing, forged or broken WF-06A cohort. Integration-only paths remain eligible through this seal."""
    owned = _wf06a_owned()
    return owned is not None and path not in owned


def allowed_path(path, repo=None, ref=None):
    """Literal, bounded: a path of the authenticated three-PR union or of this seal that no older cohort owns exclusively. Callers must also require
    ``exact_blobs_ok``."""
    root = Path(repo) if repo is not None else ROOT
    if not _delegable(path):
        return False
    if path in SEAL_PATHS or path in PINNED_PATHS:
        return True
    try:
        return path in _union(root)
    except (OSError, subprocess.CalledProcessError):
        return False


def admits_pin(path, value, repo=None, ref=None):
    """True only while the seal is exact and ``value`` is the one blob this seal authorises for ``path`` (its literal pin, or the single owning PR's
    reviewed blob). It never admits a value for a path outside the union."""
    if not _delegable(path) or not exact_blobs_ok(repo, ref):
        return False
    root = Path(repo) if repo is not None else ROOT
    pins = manifest(root, ref).get('source_blobs', {})
    if path in pins:
        return pins[path] == value
    who = _union(root).get(path, [])
    return len(who) == 1 and _immutable_blob(str(root), SOURCES[who[0]][0], path) == value


def followed_manifest_ok(path, repo=None, ref=None):
    """Structure-only relaxation for the shared predecessor manifests: this seal is exact and pins the manifest's current blob. Its exactness already
    proved main's identity keys, every historical map and the whole ledger prefix survived. It authorises NO path and no pin by itself."""
    if path not in HISTORY_MANIFESTS or not exact_blobs_ok(repo, ref):
        return False
    root = Path(repo) if repo is not None else ROOT
    return manifest(root, ref).get('source_blobs', {}).get(path) == _blob(_read(root, path, ref))


def source_blob(name, path, repo=None):
    """The blob a literal source PR head holds for ``path`` (None if absent): the immutable provenance of a historical ledger row."""
    root = Path(repo) if repo is not None else ROOT
    return _immutable_blob(str(root), SOURCES[name][0], path)


def owns(path, repo=None, ref=None):
    return allowed_path(path, repo, ref) and exact_blobs_ok(repo, ref)


def valid(repo=None, ref=None):
    from tests.fin_v2_cohorts import valid as composite_valid
    return exact_blobs_ok(repo, ref) and composite_valid(repo, ref)


def matches(path, source=None, *, repo=None, ref=None):
    root = Path(repo) if repo is not None else ROOT
    if not exact_blobs_ok(root, ref):
        return False
    pins = manifest(root, ref).get('source_blobs', {})
    if path not in pins:
        return False
    raw = source.encode() if isinstance(source, str) else source
    return source is None or _blob(raw) == pins[path]


def protected_blobs(repo=None, ref=None):
    return {}      # this seal authorises no financial_engine/, finco_core/, domain/ or workflow path
