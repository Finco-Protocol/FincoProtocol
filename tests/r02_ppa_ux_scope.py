"""Closed R02 compact-PPA-UX exact-source cohort: one UI-only increment of the guided Revenue/PPA contract editor (a new compact component; the WF-React-2 component file stays byte-identical), nothing else.

Authority: Owner approval of a single `PPA type` dropdown, compact contract list and `+ Add PPA` (Correction D). Presentation only: no financial
economics, parser, engine, writer, CAS/CSRF, schema or default changes; unavailable PPA types are displayed disabled and are never serialised.

``BASE`` is accepted main after the #435 merge (``64a0d5b7``), authenticated by commit, tree AND the recorded BASE blob of every path this cohort supersedes.
It is the tip of ... -> on_bess01 (#433) -> onaccept01 (#434) -> L01/L02 (#435) -> this cohort. The accepted predecessors learn of it only through the
literal, one-occurrence reviewed substitutions in ``HANDOFFS`` (verified byte for byte by ``reviewed_edits_ok``); the registry gains exactly this module
name; the eight current-source maps move only the registry pin. No historical manifest field, BASE/tree or tamper control is rewritten; no pattern is admitted.

Termination: every check here is low level (git objects and this manifest); it never imports an older cohort or the composite registry.
"""
from pathlib import Path
from contextlib import contextmanager
import hashlib
import json
import subprocess

ROOT = Path(__file__).resolve().parents[1]
BASE = '64a0d5b7b1ec7c989908d5f288a9ae440c663009'
BASE_TREE = '3ddd816c643013f787804229776b60c6252ed7b9'
MANIFEST = 'docs/react_migration/r02_ppa_ux/SOURCE_SUCCESSOR.json'
SCHEMA = 'R02_COMPACT_PPA_UX_EXACT_SOURCE_V1'
REGISTRY = 'tests/fin_v2_cohorts.py'
REGISTRY_MARKER = "'tests.post432_l01_l02_scope')"
REGISTRY_NEW = "'tests.post432_l01_l02_scope', 'tests.r02_ppa_ux_scope')"
SELF_MODULE = 'tests.r02_ppa_ux_scope'

SOURCE_PATHS = frozenset((
    'frontend/src/app/WorkspaceView.tsx',
    'frontend/src/app/workflow/PpaContractsEditor.tsx',
    'frontend/src/app/workflow/ModelWorkflowValidation.ts',
    'frontend/src/styles/wf-react-2.css',
    'static/react/finco-react.js',
    'static/react/finco-react.css',
))
TEST_PATHS = frozenset((
    'frontend/src/app/workflow/__tests__/ppaTypes.test.mjs',
    'tests/test_r02_ppa_ux_scope.py',
))
L_MODULE = 'tests/post432_l01_l02_scope.py'
L_TEST = 'tests/test_post432_l01_l02_scope.py'
O_MODULE = 'tests/onaccept01_scope.py'
T_MODULE = 'tests/tax_reference_registry_scope.py'
B_MODULE = 'tests/on_bess01_scope.py'
HANDOFF_FILES = frozenset((L_MODULE, O_MODULE, T_MODULE))
FROZEN = frozenset((B_MODULE,))        # read byte-identical to BASE; only checked, never edited
GOVERNANCE_PATHS = HANDOFF_FILES | {REGISTRY, L_TEST, 'tests/r02_ppa_ux_scope.py'}
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
MAP_KEYS = (REGISTRY, T_MODULE, 'static/react/finco-react.css', 'static/react/finco-react.js')
OWNED_PATHS = SOURCE_PATHS | TEST_PATHS | GOVERNANCE_PATHS | CURRENT_MAPS
NEW_SOURCE_PATHS = frozenset(('frontend/src/app/workflow/PpaContractsEditor.tsx',))      # new file: not present at BASE, so no base blob
SUPERSEDED = (SOURCE_PATHS - NEW_SOURCE_PATHS) | HANDOFF_FILES | {REGISTRY, L_TEST} | CURRENT_MAPS
FORBIDDEN_PREFIXES = ('app/', 'financial_engine/', 'finco_core/', 'domain/', '.github/', 'tools/', 'scripts/', 'tax_reference_registry/', 'migrations/', 'schemas/')
FORBIDDEN_PATHS = frozenset(('main_web.py',))

_L_HELPERS = (
    "def _next():\n    from tests.fin_v2_cohorts import COHORT_MODULES\n    if 'tests.r02_ppa_ux_scope' not in COHORT_MODULES:\n        return None\n"
    "    from tests import r02_ppa_ux_scope\n    return r02_ppa_ux_scope\n\n\n"
    "def _next_pins(root, ref):\n    N = _next()\n    if N is None or not N.signature_ok(root, ref):\n        return {}\n"
    "    return {p: b for p, b in N.manifest(root, ref)['source_blobs'].items() if p in N.SUPERSEDED}\n\n\n"
    "def map_keys(repo=None, ref=None):\n    root = Path(repo) if repo is not None else ROOT\n    N = _next()\n"
    "    return tuple(MAP_KEYS) + (tuple(N.MAP_KEYS) if N is not None and N.signature_ok(root, ref) else ())\n\n\n"
    "def _next_moved(root, ref):\n    N = _next()\n    if N is None or not N.signature_ok(root, ref):\n        return {}\n"
    "    return {k: v for k, v in _next_pins(root, ref).items() if k in N.MAP_KEYS and k not in CURRENT_MAPS}\n\n\n"
    "def closure_paths(repo=None, ref=None):\n    root = Path(repo) if repo is not None else ROOT\n    N = _next()\n"
    "    base = OWNED_PATHS | {MANIFEST}\n"
    "    return base | ((N.OWNED_PATHS | {N.MANIFEST}) if N is not None and N.signature_ok(root, ref) else frozenset())\n\n\n"
)
HANDOFFS = {
    'tests/post432_l01_l02_scope.py': (
        ('def reviewed_edits_ok(repo=None, ref=None):\n    """Both predecessor modules and the registry equal the literal reviewed substitutions over BASE, byte for byte."""\n    root = Path(repo) if repo is not None else ROOT\n    try:\n        for path in sorted(HANDOFF_FILES | {REGISTRY}):\n',
         _L_HELPERS + 'def reviewed_edits_ok(repo=None, ref=None):\n    """Both predecessor modules and the registry equal the literal reviewed substitutions over BASE, byte for byte."""\n    root = Path(repo) if repo is not None else ROOT\n    try:\n        N = _next()\n        if N is not None and N.signature_ok(root, ref):\n            return N.reviewed_edits_ok(root, ref)\n        for path in sorted(HANDOFF_FILES | {REGISTRY}):\n'),
        ("        head = ref or 'HEAD'\n        # 1. immutable provenance: accepted post-#434 main",
         "        head = ref or 'HEAD'\n        nx = _next_pins(root, ref)\n        cur = {p: nx.get(p, b) for p, b in pins.items()}\n        # 1. immutable provenance: accepted post-#434 main"),
        ("def _verdict(repo, ref, closure):\n    if _SCOPE:\n        key = (str(repo if repo is not None else ROOT), ref, closure)\n        memo = _SCOPE[-1]\n        if key not in memo:\n            memo[key] = _exact(repo, ref, closure)\n        return memo[key]\n    return _exact(repo, ref, closure)\n", "def _exact_next_scoped(repo, ref, closure):\n    # One evaluation of this cohort asks its successor for the same verdict many times; share one memo for exactly that evaluation.\n    N = _next()\n    if N is None:\n        return _exact(repo, ref, closure)\n    with N.scoped():\n        return _exact(repo, ref, closure)\n\n\ndef _verdict(repo, ref, closure):\n    if _SCOPE:\n        key = (str(repo if repo is not None else ROOT), ref, closure)\n        memo = _SCOPE[-1]\n        if key not in memo:\n            memo[key] = _exact_next_scoped(repo, ref, closure)\n        return memo[key]\n    return _exact_next_scoped(repo, ref, closure)\n"),
        ("            if computed != pins:\n                return False\n", "            if computed != cur:\n                return False\n"),
        ("            if listed != pins:\n                return False\n", "            if listed != cur:\n                return False\n"),
        ("            expected = expected_map(root, path, pins)\n            if pins[path] != _blob(expected) or (closure and _read(root, path, ref) != expected):\n",
         "            expected = expected_map(root, path, cur, _next_moved(root, ref))\n            if cur[path] != _blob(expected) or (closure and _read(root, path, ref) != expected):\n"),
        ("def expected_map(root, path, pins):\n    old = json.loads(_object_fact(root, 'show', BASE + ':' + path))\n    for key in MAP_KEYS:\n        if key in old['source_blobs']:\n            old['source_blobs'][key] = pins[key]\n",
         "def expected_map(root, path, pins, moved=None):\n    old = json.loads(_object_fact(root, 'show', BASE + ':' + path))\n    for key in MAP_KEYS:\n        if key in old['source_blobs']:\n            old['source_blobs'][key] = pins[key]\n    for key, blob in (moved or {}).items():\n        if key in old['source_blobs']:\n            old['source_blobs'][key] = blob\n"),
        ("            if any(p not in OWNED_PATHS and p != MANIFEST for p in changed):\n                return False\n",
         "            allowed = closure_paths(root, ref)\n            if any(p not in allowed for p in changed):\n                return False\n"),
        ("                if any(p not in OWNED_PATHS and p != MANIFEST and not _evidence_only(root, p) for p in extra):\n",
         "                if any(p not in allowed and not _evidence_only(root, p) for p in extra):\n"),
        ("def allowed_path(path, repo=None, ref=None):\n    return path in OWNED_PATHS or path == MANIFEST\n",
         "def allowed_path(path, repo=None, ref=None):\n    return path in closure_paths(repo, ref)\n"),
        ("    return path in SUPERSEDED and exact_blobs_ok(repo, ref) and manifest(repo, ref).get('source_blobs', {}).get(path) == value\n\n\ndef effective_pins(repo=None, ref=None, *, signature=False):\n    return dict(manifest(repo, ref).get('source_blobs', {}))\n",
         "    if path in SUPERSEDED and exact_blobs_ok(repo, ref) and effective_pins(repo, ref).get(path) == value:\n        return True\n    N = _next()\n    root = Path(repo) if repo is not None else ROOT\n    return N is not None and N.signature_ok(root, ref) and N.supersedes(path, value, root, ref)\n\n\ndef effective_pins(repo=None, ref=None, *, signature=False):\n    root = Path(repo) if repo is not None else ROOT\n    pins = dict(manifest(repo, ref).get('source_blobs', {}))\n    pins.update(_next_pins(root, ref))\n    return pins\n"),
        ("    root = Path(repo) if repo is not None else ROOT\n    try:\n        if _git(root, 'merge-base', 'origin/main', 'HEAD').decode().strip() != BASE:\n            return False\n        actual = _git(root, 'diff', BASE, '--name-only').decode().splitlines()\n",
         "    root = Path(repo) if repo is not None else ROOT\n    try:\n        N = _next()\n        if N is not None and N.signature_ok(root) and N.nontrust_scope_authorized(changed, root):\n            return True\n        if _git(root, 'merge-base', 'origin/main', 'HEAD').decode().strip() != BASE:\n            return False\n        actual = _git(root, 'diff', BASE, '--name-only').decode().splitlines()\n"),
    ),
    'tests/tax_reference_registry_scope.py': (
        ("        pins.update({p: b for p, b in B.effective_pins(repo, ref, signature=signature).items() if p in B.SUPERSEDED})\n",
         "        pins.update(dict(B.effective_pins(repo, ref, signature=signature)))\n"),
    ),
    'tests/onaccept01_scope.py': (
        ("    return {p: b for p, b in T.manifest(root, ref)['source_blobs'].items() if p in T.SUPERSEDED}\n", "    return dict(T.effective_pins(root, ref))\n\n\ndef _tip_map_keys(root, ref):\n    T = _tip()\n    return tuple(T.map_keys(root, ref)) if T is not None and T.signature_ok(root, ref) else ()\n"),
        ("        for key in ((SUPERSEDED - CURRENT_MAPS) | (set(_tip_pins(root,ref)) - CURRENT_MAPS)) & expected['source_blobs'].keys():",
         "        for key in ((SUPERSEDED - CURRENT_MAPS) | (set(_tip_pins(root,ref)) & set(_tip_map_keys(root,ref)))) & expected['source_blobs'].keys():"),
        ("    return (T.OWNED_PATHS | {T.MANIFEST}) if T is not None and T.signature_ok(root, ref) else frozenset()\n", "    return T.closure_paths(root, ref) if T is not None and T.signature_ok(root, ref) else frozenset()\n"),
    ),
}


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
        return data if (isinstance(data, dict) and set(data) == {'schema_version', 'base', 'base_tree', 'source_blobs', 'base_blobs'}
                        and isinstance(data['source_blobs'], dict) and isinstance(data['base_blobs'], dict)
                        and data['schema_version'] == SCHEMA and data['base'] == BASE and data['base_tree'] == BASE_TREE) else {}
    except (OSError, ValueError, TypeError, subprocess.CalledProcessError):
        return {}


def _owned_ok():
    return (not any(p.startswith(FORBIDDEN_PREFIXES) or p in FORBIDDEN_PATHS or '..' in p.split('/') or p.startswith('/') or '*' in p
                    for p in OWNED_PATHS | {MANIFEST})
            and SUPERSEDED <= OWNED_PATHS)


_SCOPE = []


@contextmanager
def scoped():
    if _SCOPE:
        yield
        return
    _SCOPE.append({})
    try:
        # All successor signature/pin/map reads within this SAME outer read
        # share its memo; it is dropped with the scope, never kept globally.
        N = _next()
        if N is None:
            yield
        else:
            with N.scoped():
                yield
    finally:
        _SCOPE.pop()


def exact_blobs_ok(repo=None, ref=None):
    return _verdict(repo, ref, True)


def signature_ok(repo=None, ref=None):
    """Source/base/mode/handoff authority only; the closed changed-set (full exactness) is not judged."""
    return _verdict(repo, ref, False)


def _exact_next_scoped(repo, ref, closure):
    N = _next()
    if N is None:
        return _exact(repo, ref, closure)
    with N.scoped():
        return _exact(repo, ref, closure)


def _verdict(repo, ref, closure):
    if _SCOPE:
        key = (str(repo if repo is not None else ROOT), ref, closure)
        memo = _SCOPE[-1]
        if key not in memo:
            memo[key] = _exact_next_scoped(repo, ref, closure)
        return memo[key]
    return _exact_next_scoped(repo, ref, closure)


def _apply(base_text, substitutions):
    for old, new in substitutions:
        if base_text.count(old) != 1:
            return None
        base_text = base_text.replace(old, new)
    return base_text


def expected_handoff(root, path):
    """The reviewed post-handoff bytes of a handed-off predecessor file, derived from the immutable BASE object only."""
    base = _object_fact(root, 'show', BASE + ':' + path).decode()
    if path == REGISTRY:
        if base.count(REGISTRY_MARKER) != 1:
            return None
        return base.replace(REGISTRY_MARKER, REGISTRY_NEW).encode()
    text = _apply(base, HANDOFFS[path])
    return None if text is None else text.encode()


def _next():
    from tests.fin_v2_cohorts import COHORT_MODULES
    if 'tests.bess02_scope' not in COHORT_MODULES:
        return None
    from tests import bess02_scope
    return bess02_scope


def _next_pins(root, ref):
    N = _next()
    return dict(N.effective_pins(root, ref)) if N is not None and N.signature_ok(root, ref) else {}


def map_keys(repo=None, ref=None):
    root = Path(repo) if repo is not None else ROOT
    N = _next()
    return tuple(MAP_KEYS) + (tuple(N.MAP_KEYS) if N is not None and N.signature_ok(root, ref) else ())


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


def reviewed_edits_ok(repo=None, ref=None):
    """Both predecessor modules and the registry equal the literal reviewed substitutions over BASE; the frozen BESS module is byte-identical to BASE."""
    root = Path(repo) if repo is not None else ROOT
    try:
        N = _next()
        if N is not None and N.signature_ok(root, ref):
            return (N.reviewed_edits_ok(root, ref) and all(
                _read(root, p, ref) == _object_fact(root, 'show', BASE + ':' + p) for p in FROZEN))
        for path in sorted(HANDOFF_FILES | {REGISTRY}):
            expected = expected_handoff(root, path)
            if expected is None or _read(root, path, ref) != expected:
                return False
        for path in sorted(FROZEN):
            if _read(root, path, ref) != _object_fact(root, 'show', BASE + ':' + path):
                return False
        return True
    except (OSError, ValueError, KeyError, subprocess.CalledProcessError):
        return False


def expected_map(root, path, pins, moved=None):
    old = json.loads(_object_fact(root, 'show', BASE + ':' + path))
    for key in MAP_KEYS:
        if key in old['source_blobs']:
            old['source_blobs'][key] = pins[key]
    for key, blob in (moved or {}).items():
        if key in old['source_blobs']:
            old['source_blobs'][key] = blob
    return (json.dumps(old, indent=2, sort_keys=True) + '\n').encode()


def _exact(repo=None, ref=None, closure=True):
    root = Path(repo) if repo is not None else ROOT
    data = manifest(root, ref)
    pins, base_blobs = data.get('source_blobs', {}), data.get('base_blobs', {})
    if not data or not _owned_ok() or set(pins) != OWNED_PATHS - {MANIFEST} or set(base_blobs) != SUPERSEDED:
        return False
    try:
        head = ref or 'HEAD'
        nx = _next_pins(root, ref)
        cur = {p: nx.get(p, b) for p, b in pins.items()}
        # 1. immutable provenance: accepted post-#435 main is an ancestor of the evaluated head
        _git(root, 'merge-base', '--is-ancestor', BASE, head)
        if _object_fact(root, 'rev-parse', BASE + '^{tree}').decode().strip() != BASE_TREE:
            return False
        # 2. the recorded BASE blob of every superseded path is what git holds at BASE
        paths = sorted(base_blobs)
        if _object_fact(root, 'rev-parse', *[BASE + ':' + p for p in paths]).decode().split() != [base_blobs[p] for p in paths]:
            return False
        # 3. one exact blob per owned path (git's own hashing, so LF and CRLF checkouts agree)
        if ref is None:
            ordered = sorted(pins)
            hashed = subprocess.run(['git', 'hash-object', '--stdin-paths'], cwd=root, input=''.join(str(root / p) + '\n' for p in ordered).encode(), stdout=subprocess.PIPE, stderr=subprocess.DEVNULL, check=True).stdout.decode().split()
            computed = dict(zip(ordered, hashed)) if len(hashed) == len(ordered) else None
            if computed != cur:
                return False
        else:
            listed = {}
            for line in _git(root, 'ls-tree', '-r', ref, '--', *sorted(pins)).decode().splitlines():
                meta, name = line.split('\t', 1)
                listed[name] = meta.split()[2]
            if listed != cur:
                return False
        # 4. no owned file is executable or a link in the evaluated state
        if ref is None:
            for p in OWNED_PATHS | {MANIFEST}:
                f = root / p
                if f.is_symlink() or not f.is_file() or f.stat().st_mode & 0o111:
                    return False
        else:
            modes = _git(root, 'ls-tree', '-r', ref, '--', *sorted(OWNED_PATHS | {MANIFEST})).decode().splitlines()
            if len(modes) != len(OWNED_PATHS | {MANIFEST}) or any(not line.startswith('100644 ') for line in modes):
                return False
        # 5. the literal reviewed predecessor/registry substitutions, the frozen BESS module and the pinned current maps
        if not reviewed_edits_ok(root, ref):
            return False
        for path in sorted(CURRENT_MAPS):
            expected = expected_map(root, path, cur, _next_moved(root, ref))
            if cur[path] != _blob(expected) or (closure and _read(root, path, ref) != expected):
                return False
        # 6. closed change set: since BASE nothing outside the literal owned set moved (full exactness only)
        if closure:
            changed = set(_git(root, 'diff', '--name-only', '--no-renames', BASE, *([ref] if ref else []), '--').decode().splitlines())
            allowed = closure_paths(root, ref)
            if any(p not in allowed for p in changed):
                return False
            if ref is None:
                extra = set(_git(root, 'ls-files', '--others', '--exclude-standard').decode().splitlines())
                if any(p not in allowed and not _evidence_only(root, p) for p in extra):
                    return False
        return True
    except (OSError, ValueError, KeyError, TypeError, AttributeError, subprocess.CalledProcessError):
        return False


def _evidence_only(root, p):
    f = Path(root) / p
    return (p.startswith('evidence/') and p.endswith(('.json', '.xml', '.png', '.txt', '.csv', '.html', '.zip'))
            and f.is_file() and not f.is_symlink() and not f.stat().st_mode & 0o111)


def allowed_path(path, repo=None, ref=None):
    return path in closure_paths(repo, ref)


def base_blob(path, repo=None, ref=None):
    return manifest(repo, ref).get('base_blobs', {}).get(path)


def supersedes(path, value, repo=None, ref=None):
    """Bounded supersession for the older guards: true only for a path of ``SUPERSEDED``, only while this cohort is exact, only for its exact pin."""
    if path in SUPERSEDED and exact_blobs_ok(repo, ref) and effective_pins(repo, ref).get(path) == value:
        return True
    N = _next()
    return N is not None and N.signature_ok(repo, ref) and N.supersedes(path, value, repo, ref)


def effective_pins(repo=None, ref=None, *, signature=False):
    root = Path(repo) if repo is not None else ROOT
    pins = dict(manifest(repo, ref).get('source_blobs', {}))
    pins.update(_next_pins(root, ref))
    return pins


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


def nontrust_scope_authorized(changed, repo=None):
    """The no-engine/writer/Radar scope obligation of the trust-readiness guard for THIS exact cohort: the real main merge-base diff."""
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
