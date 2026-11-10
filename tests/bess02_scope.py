"""Finite default-off BESS02 candidate successor over accepted post-#435 main.

Signature reads immutable Git facts, literal reviewed handoffs and exact candidate
bytes only. It never invokes predecessors or composite source authority. Complete
closure additionally rejects every foreign byte/path/mode and preserves historical
manifests. No production activation, engine, tax, auth or shared React permission.
"""
from contextlib import contextmanager
from functools import lru_cache
from pathlib import Path
import hashlib
import json
import subprocess

ROOT = Path(__file__).resolve().parents[1]
BASE = '64a0d5b7b1ec7c989908d5f288a9ae440c663009'
BASE_TREE = '3ddd816c643013f787804229776b60c6252ed7b9'
MANIFEST = 'docs/bess02/SOURCE_SUCCESSOR.json'
SCHEMA = 'BESS02_DEFAULT_OFF_CANDIDATE_EXACT_SOURCE_V1'
SOURCE_PATHS = frozenset(('app/services/bess_standalone_candidate.py',))
TEST_PATHS = frozenset(('tests/test_bess_standalone_candidate.py', 'tests/test_bess02_scope.py'))
DOC_PATHS = frozenset(('docs/bess02/CANDIDATE_CONTRACT.md',))
CURRENT_MAPS = frozenset((
    'docs/ci_v4/SOURCE_SUCCESSOR.json',
    'docs/react_migration/g10_d8/G10_D8_EXACT_SOURCE.json',
    'docs/react_migration/post413_o1/SOURCE_SUCCESSOR.json',
    'docs/react_migration/post413_r1/SOURCE_SUCCESSOR.json',
    'docs/react_migration/post413_r17/SOURCE_SUCCESSOR.json',
    'docs/react_migration/post413_r18/SOURCE_SUCCESSOR.json',
    'docs/react_migration/u2_workbench/U2_EXACT_SOURCE.json',
    'docs/tax_reference_registry/SOURCE_SUCCESSOR.json',
))
HANDOFFS = {'tests/fin_v2_cohorts.py': [["'tests.post432_l01_l02_scope')", "'tests.post432_l01_l02_scope', 'tests.bess02_scope')"]], 'tests/post432_l01_l02_scope.py': [['def _exact(repo=None, ref=None, closure=True):', "def _successor():\n    from tests.fin_v2_cohorts import COHORT_MODULES\n    if 'tests.bess02_scope' not in COHORT_MODULES:\n        return None\n    from tests import bess02_scope\n    return bess02_scope\n\n\ndef later_owned(repo=None, ref=None):\n    S = _successor()\n    return (S.OWNED_PATHS | {S.MANIFEST}) if S is not None and S.signature_ok(repo, ref) else frozenset()\n\n\ndef _exact(repo=None, ref=None, closure=True):"], ["        # 4. one exact blob per owned path (git's own hashing, so LF and CRLF checkouts agree)", "        S = _successor()\n        next_ok = S is not None and S.signature_ok(root, ref)\n        next_pins = S.manifest(root, ref)['source_blobs'] if next_ok else {}\n        current_pins = dict(pins, **next_pins)\n        # 4. one exact blob per owned path (git's own hashing, so LF and CRLF checkouts agree)"], ['            if computed != pins:', '            if computed != {p: current_pins[p] for p in pins}:'], ['            if listed != pins:', '            if listed != {p: current_pins[p] for p in pins}:'], ['            expected = expected_map(root, path, pins)\n            if pins[path] != _blob(expected)', '            expected = expected_map(root, path, current_pins)\n            if current_pins[path] != _blob(expected)'], ['    try:\n        for path in sorted(HANDOFF_FILES | {REGISTRY}):', '    try:\n        S = _successor()\n        if S is not None and S.signature_ok(root, ref):\n            return S.reviewed_edits_ok(root, ref)\n        for path in sorted(HANDOFF_FILES | {REGISTRY}):'], ['            if any(p not in OWNED_PATHS and p != MANIFEST for p in changed):', '            allowed = OWNED_PATHS | {MANIFEST} | later_owned(root, ref)\n            if not changed <= allowed:'], ['                if any(p not in OWNED_PATHS and p != MANIFEST and not _evidence_only(root, p) for p in extra):', '                if any(p not in allowed and not _evidence_only(root, p) for p in extra):'], ['    return path in OWNED_PATHS or path == MANIFEST', '    return path in OWNED_PATHS | {MANIFEST} or path in later_owned(repo, ref)'], ["    return path in SUPERSEDED and exact_blobs_ok(repo, ref) and manifest(repo, ref).get('source_blobs', {}).get(path) == value", '    return path in SUPERSEDED and exact_blobs_ok(repo, ref) and effective_pins(repo, ref).get(path) == value'], ["def effective_pins(repo=None, ref=None, *, signature=False):\n    return dict(manifest(repo, ref).get('source_blobs', {}))", "def effective_pins(repo=None, ref=None, *, signature=False):\n    pins = dict(manifest(repo, ref).get('source_blobs', {}))\n    S = _successor()\n    if S is not None and S.signature_ok(repo, ref):\n        pins.update(S.manifest(repo, ref)['source_blobs'])\n    return pins"], ["    root = Path(repo) if repo is not None else ROOT\n    try:\n        if _git(root, 'merge-base', 'origin/main', 'HEAD')", "    root = Path(repo) if repo is not None else ROOT\n    try:\n        S = _successor()\n        if S is not None and S.signature_ok(root) and S.nontrust_scope_authorized(changed, root):\n            return True\n        if _git(root, 'merge-base', 'origin/main', 'HEAD')"]], 'tests/onaccept01_scope.py': [["    return {p: b for p, b in T.manifest(root, ref)['source_blobs'].items() if p in T.SUPERSEDED}", '    return T.effective_pins(root, ref)'], ['    return (T.OWNED_PATHS | {T.MANIFEST}) if T is not None and T.signature_ok(root, ref) else frozenset()', '    return (T.OWNED_PATHS | {T.MANIFEST} | T.later_owned(root, ref)) if T is not None and T.signature_ok(root, ref) else frozenset()']], 'tests/test_ux_pr3b2_scope.py': [["    assert not any(p.startswith(('app/','financial_engine/','finco_core/','domain/','.github/','tools/','revenue_reference_core/','tax_reference_registry/')) and p not in t01d for p in changed)", "    from tests import bess02_scope as N\n    t01d = t01d | (N.SOURCE_PATHS if N.exact_blobs_ok() else frozenset())\n    assert not any(p.startswith(('app/','financial_engine/','finco_core/','domain/','.github/','tools/','revenue_reference_core/','tax_reference_registry/')) and p not in t01d for p in changed)"]], 'tests/test_post432_l01_l02_scope.py': [['from tests import post432_l01_l02_scope as X', 'from tests import post432_l01_l02_scope as X\nfrom tests import bess02_scope as N'], ["    assert set(_git(ROOT, 'diff', '--name-only', '--no-renames', X.BASE).splitlines()) <= X.OWNED_PATHS | {X.MANIFEST}", "    assert set(_git(ROOT, 'diff', '--name-only', '--no-renames', X.BASE).splitlines()) <= X.OWNED_PATHS | {X.MANIFEST} | X.later_owned()"], ['    assert now == base.replace(X.REGISTRY_MARKER, X.REGISTRY_NEW)', '    assert N.exact_blobs_ok() and now == N.expected_handoff(ROOT, X.REGISTRY).decode()'], ["    assert C.COHORT_MODULES == old + ('tests.post432_l01_l02_scope',) and C.COHORT_MODULES[-4:] == ACCEPTED_ORDER_TAIL", "    assert C.COHORT_MODULES == old + ('tests.post432_l01_l02_scope', 'tests.bess02_scope') and C.COHORT_MODULES[-5:] == ACCEPTED_ORDER_TAIL + ('tests.bess02_scope',)"], ["    pins = X.manifest()['source_blobs']", '    pins = X.effective_pins()'], ['        assert X.reviewed_edits_ok() and O.later_owned() == X.OWNED_PATHS | {X.MANIFEST}', '        assert X.reviewed_edits_ok() and O.later_owned() == X.OWNED_PATHS | {X.MANIFEST} | X.later_owned()'], ['    cases.append((\'extra_cohort\', lambda: registry.write_text(text.replace("\'tests.post432_l01_l02_scope\')", "\'tests.post432_l01_l02_scope\', \'tests.fake_scope\')"))))', '    extra_marker = "\'tests.bess02_scope\')"\n    assert text.count(extra_marker) == 1  # prove the negative mutation is not a no-op\n    cases.append((\'extra_cohort\', lambda: registry.write_text(text.replace(extra_marker, "\'tests.bess02_scope\', \'tests.fake_scope\')"))))']]}

GOVERNANCE_PATHS = frozenset(HANDOFFS) | {'tests/bess02_scope.py'}
OWNED_PATHS = SOURCE_PATHS | TEST_PATHS | DOC_PATHS | GOVERNANCE_PATHS | CURRENT_MAPS
SUPERSEDED = frozenset(HANDOFFS) | CURRENT_MAPS
_SCOPE = []


def _git(root, *args):
    return subprocess.check_output(['git', *map(str, args)], cwd=root, stderr=subprocess.DEVNULL)


@lru_cache(maxsize=128)
def _base(root, *args):
    return _git(root, *args)  # immutable BASE objects only


def _blob(raw):
    return hashlib.sha1(b'blob ' + str(len(raw)).encode() + b'\0' + raw).hexdigest()


def _read(root, path, ref):
    return (root / path).read_bytes() if ref is None else _git(root, 'show', ref + ':' + path)


def manifest(repo=None, ref=None):
    root = Path(repo) if repo is not None else ROOT
    try:
        d = json.loads(_read(root, MANIFEST, ref))
        return d if (set(d) == {'schema_version', 'base', 'base_tree', 'source_blobs', 'base_blobs'}
            and d['schema_version'] == SCHEMA and d['base'] == BASE and d['base_tree'] == BASE_TREE
            and isinstance(d['source_blobs'], dict) and isinstance(d['base_blobs'], dict)) else {}
    except (OSError, ValueError, TypeError, subprocess.CalledProcessError):
        return {}


def expected_handoff(root, path):
    raw = _base(root, 'show', BASE + ':' + path).decode()
    for old, new in HANDOFFS[path]:
        if raw.count(old) != 1:
            raise ValueError('reviewed handoff is missing or ambiguous')
        raw = raw.replace(old, new)
    return raw.encode()


def reviewed_edits_ok(repo=None, ref=None):
    root = Path(repo) if repo is not None else ROOT
    try:
        return all(_read(root, p, ref) == expected_handoff(root, p) for p in HANDOFFS)
    except (OSError, ValueError, KeyError, TypeError, subprocess.CalledProcessError):
        return False


def expected_map(root, path, pins):
    d = json.loads(_base(root, 'show', BASE + ':' + path))
    # Existing keys and every metadata/historical field remain byte-equivalent
    # after canonical JSON serialization. Only finite handed-off source pins move.
    for p in (SUPERSEDED - CURRENT_MAPS) & d['source_blobs'].keys():
        d['source_blobs'][p] = pins[p]
    return (json.dumps(d, indent=2, sort_keys=True) + '\n').encode()


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


def _verdict(repo, ref, closure):
    key = (str(repo if repo is not None else ROOT), ref, closure)
    if _SCOPE:
        if key not in _SCOPE[-1]:
            _SCOPE[-1][key] = _exact(repo, ref, closure)
        return _SCOPE[-1][key]
    return _exact(repo, ref, closure)


def signature_ok(repo=None, ref=None):
    return _verdict(repo, ref, False)


def exact_blobs_ok(repo=None, ref=None):
    return _verdict(repo, ref, True)


def _exact(repo=None, ref=None, closure=True):
    root = Path(repo) if repo is not None else ROOT
    try:
        from tests.fin_v2_cohorts import COHORT_MODULES
        if __name__ not in COHORT_MODULES:
            return False
        d = manifest(root, ref)
        pins = d.get('source_blobs', {})
        if set(pins) != OWNED_PATHS or set(d.get('base_blobs', {})) != SUPERSEDED:
            return False
        head = ref or 'HEAD'
        _git(root, 'merge-base', '--is-ancestor', BASE, head)
        if _base(root, 'rev-parse', BASE + '^{tree}').decode().strip() != BASE_TREE:
            return False
        old = {p: _base(root, 'rev-parse', BASE + ':' + p).decode().strip() for p in SUPERSEDED}
        if old != d['base_blobs']:
            return False
        if not reviewed_edits_ok(root, ref):
            return False
        for p in CURRENT_MAPS:
            expected = expected_map(root, p, pins)
            if pins[p] != _blob(expected) or (closure and _read(root, p, ref) != expected):
                return False
        for p in OWNED_PATHS | {MANIFEST}:
            if p.startswith('/') or '..' in p.split('/') or '*' in p:
                return False
            if ref is None:
                f = root / p
                if not f.is_file() or f.is_symlink() or f.stat().st_mode & 0o111:
                    return False
            else:
                rows = _git(root, 'ls-tree', ref, '--', p).decode().splitlines()
                if len(rows) != 1 or not rows[0].startswith('100644 blob '):
                    return False
            if p != MANIFEST and (closure or p not in CURRENT_MAPS) and _blob(_read(root, p, ref)) != pins[p]:
                return False
        # Safety authorities never join OWNED_PATHS. Prove default-off and
        # protected reference/financial engine boundaries from accepted bytes.
        if any(p.startswith(('financial_engine/', 'finco_core/', 'domain/', '.github/', 'frontend/', 'static/')) for p in OWNED_PATHS):
            return False
        if closure:
            changed = set(_git(root, 'diff', '--name-only', '--no-renames', BASE, *([ref] if ref else []), '--').decode().splitlines())
            allowed = OWNED_PATHS | {MANIFEST}
            if not changed <= allowed:
                return False
            if ref is None:
                extra = set(_git(root, 'ls-files', '--others', '--exclude-standard').decode().splitlines())
                if not extra <= allowed:
                    return False
                # Check all foreign accepted bytes AND modes directly; do not
                # trust assume-unchanged index bits or a narrow diff alone.
                for row in _base(root, 'ls-tree', '-r', BASE).decode().splitlines():
                    meta, p = row.split('\t', 1)
                    if p in allowed:
                        continue
                    mode, kind, pin = meta.split()
                    f = root / p
                    if (kind != 'blob' or mode not in ('100644', '100755') or not f.is_file()
                            or f.is_symlink() or _blob(f.read_bytes()) != pin
                            or bool(f.stat().st_mode & 0o111) != (mode == '100755')):
                        return False
        return True
    except (OSError, ValueError, KeyError, TypeError, AttributeError, subprocess.CalledProcessError):
        return False


def allowed_path(path, repo=None, ref=None):
    return path in OWNED_PATHS | {MANIFEST}


def base_blob(path, repo=None, ref=None):
    return manifest(repo, ref).get('base_blobs', {}).get(path)


def supersedes(path, value, repo=None, ref=None):
    return path in SUPERSEDED and signature_ok(repo, ref) and manifest(repo, ref)['source_blobs'].get(path) == value


def effective_pins(repo=None, ref=None, *, signature=False):
    return dict(manifest(repo, ref).get('source_blobs', {}))


def valid(repo=None, ref=None):
    from tests.fin_v2_cohorts import valid as composite
    return exact_blobs_ok(repo, ref) and composite(repo, ref)


def matches(path, source=None, *, repo=None, ref=None):
    pins = manifest(repo, ref).get('source_blobs', {})
    raw = source.encode() if isinstance(source, str) else source
    return path in pins and valid(repo, ref) and (source is None or _blob(raw) == pins[path])


def protected_blobs(repo=None, ref=None):
    return {}  # No new financial_engine/finco_core/domain authority.


def nontrust_scope_authorized(changed, repo=None):
    root = Path(repo) if repo is not None else ROOT
    try:
        if _git(root, 'merge-base', 'origin/main', 'HEAD').decode().strip() != BASE:
            return False
        actual = _git(root, 'diff', BASE, '--name-only').decode().splitlines()
        if not actual or sorted(changed) != sorted(actual) or not set(actual) <= OWNED_PATHS | {MANIFEST}:
            return False
        from tests import fin_v2_cohorts as C
        with C.call_scope():
            return exact_blobs_ok(root) and C.valid(root)
    except (OSError, ValueError, TypeError, subprocess.CalledProcessError):
        return False
