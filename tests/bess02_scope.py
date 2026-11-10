"""Finite default-off BESS02 leaf after accepted #435 and #437 main.

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
BASE = 'c26b968683f1de63f73f92789dcef947e912822e'
BASE_TREE = 'bd65189555850dca7982ce9f5e9314a73b923eef'
MANIFEST = 'docs/bess02/SOURCE_SUCCESSOR.json'
SCHEMA = 'BESS02_DEFAULT_OFF_CANDIDATE_EXACT_SOURCE_V1'
MAP_KEYS = ('tests/fin_v2_cohorts.py', 'tests/test_ux_pr3b2_scope.py')
SOURCE_PATHS = frozenset(('app/services/bess_standalone_candidate.py', 'app/services/bess_setup_preview.py'))
# Existing accepted preview source: its exact main blob remains a base fact.
SUPERSEDED_SOURCE_PATHS = frozenset(('app/services/bess_setup_preview.py',))
TEST_PATHS = frozenset(('tests/test_bess_standalone_candidate.py', 'tests/test_bess02_scope.py', 'tests/test_bess_declared_preview.py'))
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
HANDOFFS = {'tests/fin_v2_cohorts.py': [["'tests.r02_ppa_ux_scope')", "'tests.r02_ppa_ux_scope', 'tests.bess02_scope')"]], 'tests/post432_l01_l02_scope.py': [["    return {p: b for p, b in N.manifest(root, ref)['source_blobs'].items() if p in N.SUPERSEDED}", '    return dict(N.effective_pins(root, ref))'], ['    return tuple(MAP_KEYS) + (tuple(N.MAP_KEYS) if N is not None and N.signature_ok(root, ref) else ())', '    return tuple(MAP_KEYS) + (tuple(N.map_keys(root, ref)) if N is not None and N.signature_ok(root, ref) else ())'], ['    return {k: v for k, v in _next_pins(root, ref).items() if k in N.MAP_KEYS and k not in CURRENT_MAPS}', '    return {k: v for k, v in _next_pins(root, ref).items() if k in N.map_keys(root, ref) and k not in CURRENT_MAPS}'], ['    return base | ((N.OWNED_PATHS | {N.MANIFEST}) if N is not None and N.signature_ok(root, ref) else frozenset())', '    return base | (N.closure_paths(root, ref) if N is not None and N.signature_ok(root, ref) else frozenset())']], 'tests/r02_ppa_ux_scope.py': [['\ndef reviewed_edits_ok(repo=None, ref=None):', "\ndef _next():\n    from tests.fin_v2_cohorts import COHORT_MODULES\n    if 'tests.bess02_scope' not in COHORT_MODULES:\n        return None\n    from tests import bess02_scope\n    return bess02_scope\n\n\ndef _next_pins(root, ref):\n    N = _next()\n    return dict(N.effective_pins(root, ref)) if N is not None and N.signature_ok(root, ref) else {}\n\n\ndef map_keys(repo=None, ref=None):\n    root = Path(repo) if repo is not None else ROOT\n    N = _next()\n    return tuple(MAP_KEYS) + (tuple(N.MAP_KEYS) if N is not None and N.signature_ok(root, ref) else ())\n\n\ndef _next_moved(root, ref):\n    N = _next()\n    if N is None or not N.signature_ok(root, ref):\n        return {}\n    return {k: v for k, v in _next_pins(root, ref).items() if k in N.MAP_KEYS and k not in CURRENT_MAPS}\n\n\ndef closure_paths(repo=None, ref=None):\n    root = Path(repo) if repo is not None else ROOT\n    N = _next()\n    own = OWNED_PATHS | {MANIFEST}\n    return own | ((N.OWNED_PATHS | {N.MANIFEST}) if N is not None and N.signature_ok(root, ref) else frozenset())\n\n\ndef reviewed_edits_ok(repo=None, ref=None):"], ['    try:\n        for path in sorted(HANDOFF_FILES | {REGISTRY}):', "    try:\n        N = _next()\n        if N is not None and N.signature_ok(root, ref):\n            return (N.reviewed_edits_ok(root, ref) and all(\n                _read(root, p, ref) == _object_fact(root, 'show', BASE + ':' + p) for p in FROZEN))\n        for path in sorted(HANDOFF_FILES | {REGISTRY}):"], ['def _verdict(repo, ref, closure):\n    if _SCOPE:\n        key = (str(repo if repo is not None else ROOT), ref, closure)\n        memo = _SCOPE[-1]\n        if key not in memo:\n            memo[key] = _exact(repo, ref, closure)\n        return memo[key]\n    return _exact(repo, ref, closure)\n', 'def _exact_next_scoped(repo, ref, closure):\n    N = _next()\n    if N is None:\n        return _exact(repo, ref, closure)\n    with N.scoped():\n        return _exact(repo, ref, closure)\n\n\ndef _verdict(repo, ref, closure):\n    if _SCOPE:\n        key = (str(repo if repo is not None else ROOT), ref, closure)\n        memo = _SCOPE[-1]\n        if key not in memo:\n            memo[key] = _exact_next_scoped(repo, ref, closure)\n        return memo[key]\n    return _exact_next_scoped(repo, ref, closure)\n'], ['@contextmanager\ndef scoped():\n    if _SCOPE:\n        yield\n        return\n    _SCOPE.append({})\n    try:\n        yield\n    finally:\n        _SCOPE.pop()\n', '@contextmanager\ndef scoped():\n    if _SCOPE:\n        yield\n        return\n    _SCOPE.append({})\n    try:\n        # All successor signature/pin/map reads within this SAME outer read\n        # share its memo; it is dropped with the scope, never kept globally.\n        N = _next()\n        if N is None:\n            yield\n        else:\n            with N.scoped():\n                yield\n    finally:\n        _SCOPE.pop()\n'], ["        head = ref or 'HEAD'\n        # 1. immutable provenance:", "        head = ref or 'HEAD'\n        nx = _next_pins(root, ref)\n        cur = {p: nx.get(p, b) for p, b in pins.items()}\n        # 1. immutable provenance:"], ['\n            if computed != pins:', '\n            if computed != cur:'], ['\n            if listed != pins:', '\n            if listed != cur:'], ['            expected = expected_map(root, path, pins)\n            if pins[path] != _blob(expected)', '            expected = expected_map(root, path, cur, _next_moved(root, ref))\n            if cur[path] != _blob(expected)'], ["def expected_map(root, path, pins):\n    old = json.loads(_object_fact(root, 'show', BASE + ':' + path))\n    for key in MAP_KEYS:\n        if key in old['source_blobs']:\n            old['source_blobs'][key] = pins[key]\n", "def expected_map(root, path, pins, moved=None):\n    old = json.loads(_object_fact(root, 'show', BASE + ':' + path))\n    for key in MAP_KEYS:\n        if key in old['source_blobs']:\n            old['source_blobs'][key] = pins[key]\n    for key, blob in (moved or {}).items():\n        if key in old['source_blobs']:\n            old['source_blobs'][key] = blob\n"], ['\n            if any(p not in OWNED_PATHS and p != MANIFEST for p in changed):', '\n            allowed = closure_paths(root, ref)\n            if any(p not in allowed for p in changed):'], ['\n                if any(p not in OWNED_PATHS and p != MANIFEST and not _evidence_only(root, p) for p in extra):', '\n                if any(p not in allowed and not _evidence_only(root, p) for p in extra):'], ['\n    return path in OWNED_PATHS or path == MANIFEST', '\n    return path in closure_paths(repo, ref)'], ["\n    return path in SUPERSEDED and exact_blobs_ok(repo, ref) and manifest(repo, ref).get('source_blobs', {}).get(path) == value", '\n    if path in SUPERSEDED and exact_blobs_ok(repo, ref) and effective_pins(repo, ref).get(path) == value:\n        return True\n    N = _next()\n    return N is not None and N.signature_ok(repo, ref) and N.supersedes(path, value, repo, ref)'], ["def effective_pins(repo=None, ref=None, *, signature=False):\n    return dict(manifest(repo, ref).get('source_blobs', {}))", "def effective_pins(repo=None, ref=None, *, signature=False):\n    root = Path(repo) if repo is not None else ROOT\n    pins = dict(manifest(repo, ref).get('source_blobs', {}))\n    pins.update(_next_pins(root, ref))\n    return pins"], ["    root = Path(repo) if repo is not None else ROOT\n    try:\n        if _git(root, 'merge-base', 'origin/main', 'HEAD')", "    root = Path(repo) if repo is not None else ROOT\n    try:\n        N = _next()\n        if N is not None and N.signature_ok(root) and N.nontrust_scope_authorized(changed, root):\n            return True\n        if _git(root, 'merge-base', 'origin/main', 'HEAD')"]], 'tests/test_ux_pr3b2_scope.py': [["    assert not any(p.startswith(('app/','financial_engine/','finco_core/','domain/','.github/','tools/','revenue_reference_core/','tax_reference_registry/')) and p not in t01d for p in changed)", "    from tests import bess02_scope as N\n    t01d = t01d | (N.SOURCE_PATHS if N.exact_blobs_ok() else frozenset())\n    assert not any(p.startswith(('app/','financial_engine/','finco_core/','domain/','.github/','tools/','revenue_reference_core/','tax_reference_registry/')) and p not in t01d for p in changed)"]], 'tests/test_post432_l01_l02_scope.py': [['from tests import post432_l01_l02_scope as X', 'from tests import post432_l01_l02_scope as X\nfrom tests import bess02_scope as N'], ['    assert now in (own, own.replace("\'tests.post432_l01_l02_scope\')", "\'tests.post432_l01_l02_scope\', \'tests.r02_ppa_ux_scope\')"))      # a later cohort may only append itself', '    assert N.exact_blobs_ok() and now == N.expected_handoff(ROOT, X.REGISTRY).decode()'], ["def test_the_accepted_runner_and_bess_preview_behaviour_is_unchanged():\n    for path in sorted(O.SOURCE_PATHS | B.APP_PATHS):\n        assert _git(ROOT, 'rev-parse', 'HEAD:' + path) == _git(ROOT, 'rev-parse', X.BASE + ':' + path), path\n    assert 'tests.on_bess01_scope' in C.COHORT_MODULES and 'tests.onaccept01_scope' in C.COHORT_MODULES\n    assert C.COHORT_MODULES.index('tests.on_bess01_scope') < C.COHORT_MODULES.index('tests.onaccept01_scope') < C.COHORT_MODULES.index(X.SELF_MODULE)", "def test_the_accepted_runner_and_bess_preview_behaviour_is_unchanged():\n    for path in sorted(O.SOURCE_PATHS | B.APP_PATHS):\n        if path == 'app/services/bess_setup_preview.py':\n            # One owner-approved nonpersisting preview source successor only.\n            assert N.exact_blobs_ok() and path in N.SOURCE_PATHS and path in N.SUPERSEDED_SOURCE_PATHS\n            assert _git(ROOT, 'rev-parse', 'HEAD:' + path) == N.manifest()['source_blobs'][path]\n        else:\n            assert _git(ROOT, 'rev-parse', 'HEAD:' + path) == _git(ROOT, 'rev-parse', X.BASE + ':' + path), path\n    assert 'tests.on_bess01_scope' in C.COHORT_MODULES and 'tests.onaccept01_scope' in C.COHORT_MODULES\n    assert C.COHORT_MODULES.index('tests.on_bess01_scope') < C.COHORT_MODULES.index('tests.onaccept01_scope') < C.COHORT_MODULES.index(X.SELF_MODULE)"]], 'tests/test_r02_ppa_ux_scope.py': [['from tests import r02_ppa_ux_scope as X', 'from tests import r02_ppa_ux_scope as X\nfrom tests import bess02_scope as N'], ['    assert changed <= X.OWNED_PATHS | {X.MANIFEST}', '    assert changed <= X.closure_paths()'], ["    assert not [p for p in changed if p.startswith(('app/', 'financial_engine/', 'finco_core/', 'domain/', '.github/', 'tools/', 'scripts/'))]", "    assert not [p for p in changed if p.startswith(('app/', 'financial_engine/', 'finco_core/', 'domain/', '.github/', 'tools/', 'scripts/'))\n                and not (N.exact_blobs_ok() and p in N.SOURCE_PATHS)]"], ["    assert (ROOT / 'tests/fin_v2_cohorts.py').read_text() == base.replace(X.REGISTRY_MARKER, X.REGISTRY_NEW)", '    assert N.exact_blobs_ok() and (ROOT / X.REGISTRY).read_bytes() == N.expected_handoff(ROOT, X.REGISTRY)'], ["    assert C.COHORT_MODULES == old + ('tests.r02_ppa_ux_scope',) and C.COHORT_MODULES[-5:] == TAIL and len(set(C.COHORT_MODULES)) == len(C.COHORT_MODULES)", "    assert C.COHORT_MODULES == old + ('tests.r02_ppa_ux_scope', 'tests.bess02_scope') and C.COHORT_MODULES[-6:] == TAIL + ('tests.bess02_scope',) and len(set(C.COHORT_MODULES)) == len(C.COHORT_MODULES)"], ["    pins = X.manifest()['source_blobs']", '    pins = X.effective_pins()'], ['        assert X.reviewed_edits_ok() and L.closure_paths() == X.OWNED_PATHS | L.OWNED_PATHS | {X.MANIFEST, L.MANIFEST} and O.later_owned() == L.closure_paths()', '        assert X.reviewed_edits_ok() and L.closure_paths() == X.closure_paths() | L.OWNED_PATHS | {L.MANIFEST} and O.later_owned() == L.closure_paths()'], ['    cases.append((\'extra_cohort\', lambda: registry.write_text(text.replace("\'tests.r02_ppa_ux_scope\')", "\'tests.r02_ppa_ux_scope\', \'tests.fake_scope\')"))))', '    last = C.COHORT_MODULES[-1]\n    assert text.count(f"\'{last}\')") == 1  # prove the negative mutation actually changes the current tail\n    cases.append((\'extra_cohort\', lambda: registry.write_text(text.replace(f"\'{last}\')", f"\'{last}\', \'tests.fake_scope\')"))))']]}

GOVERNANCE_PATHS = frozenset(HANDOFFS) | {'tests/bess02_scope.py'}
OWNED_PATHS = SOURCE_PATHS | TEST_PATHS | DOC_PATHS | GOVERNANCE_PATHS | CURRENT_MAPS
SUPERSEDED = frozenset(HANDOFFS) | CURRENT_MAPS | SUPERSEDED_SOURCE_PATHS
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
        N = _next()
        if N is not None and N.signature_ok(root, ref):
            return N.reviewed_edits_ok(root, ref) and all(
                _read(root, p, ref) == expected_handoff(root, p) for p in HANDOFFS if p not in N.HANDOFFS)
        return all(_read(root, p, ref) == expected_handoff(root, p) for p in HANDOFFS)
    except (OSError, ValueError, KeyError, TypeError, subprocess.CalledProcessError):
        return False


def expected_map(root, path, pins, moved=None):
    d = json.loads(_base(root, 'show', BASE + ':' + path))
    # Existing keys and every metadata/historical field remain byte-equivalent
    # after canonical JSON serialization. Only finite handed-off source pins move.
    for p in (SUPERSEDED - CURRENT_MAPS) & d['source_blobs'].keys():
        d['source_blobs'][p] = pins[p]
    for key, blob in (moved or {}).items():
        if key in d['source_blobs']:
            d['source_blobs'][key] = blob
    return (json.dumps(d, indent=2, sort_keys=True) + '\n').encode()


@contextmanager
def scoped():
    if _SCOPE:
        yield
        return
    _SCOPE.append({})
    try:
        # Successor reads inside this SAME outer read share its memo; dropped with the scope, never kept globally.
        N = _next()
        if N is None:
            yield
        else:
            with N.scoped():
                yield
    finally:
        _SCOPE.pop()


def _exact_next_scoped(repo, ref, closure):
    N = _next()
    if N is None:
        return _exact(repo, ref, closure)
    with N.scoped():
        return _exact(repo, ref, closure)


def _verdict(repo, ref, closure):
    key = (str(repo if repo is not None else ROOT), ref, closure)
    if _SCOPE:
        if key not in _SCOPE[-1]:
            _SCOPE[-1][key] = _exact_next_scoped(repo, ref, closure)
        return _SCOPE[-1][key]
    return _exact_next_scoped(repo, ref, closure)


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
        nx = _next_pins(root, ref)
        cur = {p: nx.get(p, b) for p, b in pins.items()}
        _git(root, 'merge-base', '--is-ancestor', BASE, head)
        if _base(root, 'rev-parse', BASE + '^{tree}').decode().strip() != BASE_TREE:
            return False
        old = {p: _base(root, 'rev-parse', BASE + ':' + p).decode().strip() for p in SUPERSEDED}
        if old != d['base_blobs']:
            return False
        if not reviewed_edits_ok(root, ref):
            return False
        for p in CURRENT_MAPS:
            expected = expected_map(root, p, cur, _next_moved(root, ref))
            if cur[p] != _blob(expected) or (closure and _read(root, p, ref) != expected):
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
            if p != MANIFEST and (closure or p not in CURRENT_MAPS) and _blob(_read(root, p, ref)) != cur[p]:
                return False
        # Safety authorities never join OWNED_PATHS. Prove default-off and
        # protected reference/financial engine boundaries from accepted bytes.
        if any(p.startswith(('financial_engine/', 'finco_core/', 'domain/', '.github/', 'frontend/', 'static/')) for p in OWNED_PATHS):
            return False
        if closure:
            changed = set(_git(root, 'diff', '--name-only', '--no-renames', BASE, *([ref] if ref else []), '--').decode().splitlines())
            allowed = closure_paths(root, ref)
            if not changed <= allowed:
                return False
            if ref is None:
                extra = set(_git(root, 'ls-files', '--others', '--exclude-standard').decode().splitlines())
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
                # Generated F01 artifacts are inert evidence, never source
                # authority. Reuse the accepted finite validator only AFTER
                # every foreign accepted byte/mode above has been verified.
                from tests.on_bess01_scope import _generated_evidence_ok
                if any(not _generated_evidence_ok(root, p) for p in extra - allowed):
                    return False
        return True
    except (OSError, ValueError, KeyError, TypeError, AttributeError, subprocess.CalledProcessError):
        return False


def _next():
    """The one finite forward successor (F03). Low-level only: its signature never calls this module or the composite."""
    from tests.fin_v2_cohorts import COHORT_MODULES
    if 'tests.f03_financing_scope' not in COHORT_MODULES:
        return None
    from tests import f03_financing_scope
    return f03_financing_scope


def _next_pins(root, ref):
    N = _next()
    return dict(N.effective_pins(root, ref)) if N is not None and N.signature_ok(root, ref) else {}


def _next_moved(root, ref):
    N = _next()
    if N is None or not N.signature_ok(root, ref):
        return {}
    return {k: v for k, v in _next_pins(root, ref).items() if k in N.MAP_KEYS and k not in CURRENT_MAPS}


def closure_paths(repo=None, ref=None):
    root = Path(repo) if repo is not None else ROOT
    N = _next()
    own = OWNED_PATHS | {MANIFEST}
    return own | (N.closure_paths(root, ref) if N is not None and N.signature_ok(root, ref) else frozenset())


def allowed_path(path, repo=None, ref=None):
    return path in closure_paths(repo, ref)


def base_blob(path, repo=None, ref=None):
    return manifest(repo, ref).get('base_blobs', {}).get(path)


def supersedes(path, value, repo=None, ref=None):
    if path in SUPERSEDED and signature_ok(repo, ref) and effective_pins(repo, ref).get(path) == value:
        return True
    N = _next()
    return N is not None and N.signature_ok(repo, ref) and N.supersedes(path, value, repo, ref)


def effective_pins(repo=None, ref=None, *, signature=False):
    root = Path(repo) if repo is not None else ROOT
    pins = dict(manifest(repo, ref).get('source_blobs', {}))
    pins.update(_next_pins(root, ref))
    return pins


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
        N = _next()
        if N is not None and N.signature_ok(root) and N.nontrust_scope_authorized(changed, root):
            return True
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
