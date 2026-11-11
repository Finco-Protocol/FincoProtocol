"""CI V4 Correction P performance leaf: one bounded forward successor over accepted main 01a26f9a.

Owns literally (no pattern, no wildcard): the three performance-edited test modules, the four
recalibrated scheduler weights with PROJECTED provenance, the composite-registry registration
append, the reviewed BESS02 leaf forward-handoff edits (registry tail, bess02 successor pattern,
r02 closure recursion, the three handoff-test updates) and this cohort's own proof/tests/manifest.

It admits no app/, financial_engine/, finco_core/, domain/, .github/, frontend/ or static/ byte,
no selector/policy/workflow change and no test removal or skip. The predecessor BESS02 leaf
stays exact through the reviewed handoff: its frozen byte expectations are governed by THIS
cohort's literal substitutions over the same accepted BASE, and every foreign accepted byte,
mode and untracked path is re-verified against BASE on every full read.
"""
from contextlib import contextmanager
from functools import lru_cache
from pathlib import Path
import hashlib
import json
import subprocess

ROOT = Path(__file__).resolve().parents[1]
BASE = '01a26f9a87a12548c4f151caebe8ee933db7445c'
BASE_TREE = '0f84439efe6cb4ad920ea008eb739bbc7dbe07ab'
MANIFEST = 'docs/ci_v4/correction_p/SOURCE_SUCCESSOR.json'
SCHEMA = 'CI_V4_CORRECTION_P_PERFORMANCE_EXACT_SOURCE_V1'
MAP_KEYS = ('tests/fin_v2_cohorts.py', 'docs/ci_v4/module_weights.json', 'tests/ux_pr3b1_scope.py')
FORBIDDEN_PREFIXES = ('financial_engine/', 'finco_core/', 'domain/', '.github/', 'frontend/', 'static/')

# Files whose bytes this integration takes over from the accepted BESS02 leaf's frozen
# expectations. Each is proved by literal reviewed substitutions over BASE (expected_handoff).
HANDOFFS = {
    'tests/fin_v2_cohorts.py': [
        ("'tests.r02_ppa_ux_scope', 'tests.bess02_scope')",
         "'tests.r02_ppa_ux_scope', 'tests.bess02_scope', 'tests.ci_v4_perf_scope')"),
    ],
    'tests/bess02_scope.py': [
        ("def reviewed_edits_ok(repo=None, ref=None):\n    root = Path(repo) if repo is not None else ROOT\n    try:\n        return all(_read(root, p, ref) == expected_handoff(root, p) for p in HANDOFFS)",
         "def reviewed_edits_ok(repo=None, ref=None):\n    root = Path(repo) if repo is not None else ROOT\n    try:\n        N = _next()\n        if N is not None and N.signature_ok(root, ref):\n            return N.reviewed_edits_ok(root, ref) and all(\n                _read(root, p, ref) == expected_handoff(root, p) for p in HANDOFFS if p not in N.HANDOFFS)\n        return all(_read(root, p, ref) == expected_handoff(root, p) for p in HANDOFFS)"),
        ("def expected_map(root, path, pins):\n    d = json.loads(_base(root, 'show', BASE + ':' + path))\n    # Existing keys and every metadata/historical field remain byte-equivalent\n    # after canonical JSON serialization. Only finite handed-off source pins move.\n    for p in (SUPERSEDED - CURRENT_MAPS) & d['source_blobs'].keys():\n        d['source_blobs'][p] = pins[p]\n    return (json.dumps(d, indent=2, sort_keys=True) + '\\n').encode()",
         "def expected_map(root, path, pins, moved=None):\n    d = json.loads(_base(root, 'show', BASE + ':' + path))\n    # Existing keys and every metadata/historical field remain byte-equivalent\n    # after canonical JSON serialization. Only finite handed-off source pins move.\n    for p in (SUPERSEDED - CURRENT_MAPS) & d['source_blobs'].keys():\n        d['source_blobs'][p] = pins[p]\n    for key, blob in (moved or {}).items():\n        if key in d['source_blobs']:\n            d['source_blobs'][key] = blob\n    return (json.dumps(d, indent=2, sort_keys=True) + '\\n').encode()"),
        ("@contextmanager\ndef scoped():\n    if _SCOPE:\n        yield\n        return\n    _SCOPE.append({})\n    try:\n        yield\n    finally:\n        _SCOPE.pop()",
         "@contextmanager\ndef scoped():\n    if _SCOPE:\n        yield\n        return\n    _SCOPE.append({})\n    try:\n        # All successor signature/pin/map reads within this SAME outer read\n        # share its memo; it is dropped with the scope, never kept globally.\n        N = _next()\n        if N is None:\n            yield\n        else:\n            with N.scoped():\n                yield\n    finally:\n        _SCOPE.pop()"),
        ("def _verdict(repo, ref, closure):\n    key = (str(repo if repo is not None else ROOT), ref, closure)\n    if _SCOPE:\n        if key not in _SCOPE[-1]:\n            _SCOPE[-1][key] = _exact(repo, ref, closure)\n        return _SCOPE[-1][key]\n    return _exact(repo, ref, closure)",
         "def _exact_next_scoped(repo, ref, closure):\n    N = _next()\n    if N is None:\n        return _exact(repo, ref, closure)\n    with N.scoped():\n        return _exact(repo, ref, closure)\n\n\ndef _verdict(repo, ref, closure):\n    key = (str(repo if repo is not None else ROOT), ref, closure)\n    if _SCOPE:\n        if key not in _SCOPE[-1]:\n            _SCOPE[-1][key] = _exact_next_scoped(repo, ref, closure)\n        return _SCOPE[-1][key]\n    return _exact_next_scoped(repo, ref, closure)"),
        ("        head = ref or 'HEAD'\n        _git(root, 'merge-base', '--is-ancestor', BASE, head)",
         "        head = ref or 'HEAD'\n        nx = _next_pins(root, ref)\n        cur = {p: nx.get(p, b) for p, b in pins.items()}\n        _git(root, 'merge-base', '--is-ancestor', BASE, head)"),
        ("        for p in CURRENT_MAPS:\n            expected = expected_map(root, p, pins)\n            if pins[p] != _blob(expected) or (closure and _read(root, p, ref) != expected):\n                return False",
         "        for p in CURRENT_MAPS:\n            expected = expected_map(root, p, cur, _next_moved(root, ref))\n            if cur[p] != _blob(expected) or (closure and _read(root, p, ref) != expected):\n                return False"),
        ("            if p != MANIFEST and (closure or p not in CURRENT_MAPS) and _blob(_read(root, p, ref)) != pins[p]:",
         "            if p != MANIFEST and (closure or p not in CURRENT_MAPS) and _blob(_read(root, p, ref)) != cur[p]:"),
        ("            allowed = OWNED_PATHS | {MANIFEST}\n            if not changed <= allowed:",
         "            allowed = closure_paths(root, ref)\n            if not changed <= allowed:"),
        ("def allowed_path(path, repo=None, ref=None):\n    return path in OWNED_PATHS | {MANIFEST}",
         "def _next():\n    \"\"\"The one finite forward successor (CI V4 Correction P performance leaf). Low-level only: its signature never calls this module or the composite.\"\"\"\n    from tests.fin_v2_cohorts import COHORT_MODULES\n    if 'tests.ci_v4_perf_scope' not in COHORT_MODULES:\n        return None\n    from tests import ci_v4_perf_scope\n    return ci_v4_perf_scope\n\n\ndef _next_pins(root, ref):\n    N = _next()\n    return dict(N.effective_pins(root, ref)) if N is not None and N.signature_ok(root, ref) else {}\n\n\ndef _next_moved(root, ref):\n    N = _next()\n    if N is None or not N.signature_ok(root, ref):\n        return {}\n    return {k: v for k, v in _next_pins(root, ref).items() if k in N.MAP_KEYS and k not in CURRENT_MAPS}\n\n\ndef closure_paths(repo=None, ref=None):\n    \"\"\"This cohort's closed path set, gated by its OWN signature, plus the successor's closure; one shared read scope evaluates each signature once.\"\"\"\n    root = Path(repo) if repo is not None else ROOT\n    with scoped():\n        if not signature_ok(root, ref):\n            return frozenset()\n        N = _next()\n        return OWNED_PATHS | {MANIFEST} | (N.closure_paths(root, ref) if N is not None else frozenset())\n\n\ndef allowed_path(path, repo=None, ref=None):\n    return path in closure_paths(repo, ref)"),
        ("def supersedes(path, value, repo=None, ref=None):\n    return path in SUPERSEDED and signature_ok(repo, ref) and manifest(repo, ref)['source_blobs'].get(path) == value",
         "def supersedes(path, value, repo=None, ref=None):\n    if path in SUPERSEDED and signature_ok(repo, ref) and effective_pins(repo, ref).get(path) == value:\n        return True\n    N = _next()\n    return N is not None and N.signature_ok(repo, ref) and N.supersedes(path, value, repo, ref)"),
        ("def effective_pins(repo=None, ref=None, *, signature=False):\n    return dict(manifest(repo, ref).get('source_blobs', {}))",
         "def effective_pins(repo=None, ref=None, *, signature=False):\n    root = Path(repo) if repo is not None else ROOT\n    pins = dict(manifest(repo, ref).get('source_blobs', {}))\n    pins.update(_next_pins(root, ref))\n    return pins"),
        ("def nontrust_scope_authorized(changed, repo=None):\n    root = Path(repo) if repo is not None else ROOT\n    try:\n        if _git(root, 'merge-base', 'origin/main', 'HEAD').decode().strip() != BASE:",
         "def nontrust_scope_authorized(changed, repo=None):\n    root = Path(repo) if repo is not None else ROOT\n    try:\n        N = _next()\n        if N is not None and N.signature_ok(root) and N.nontrust_scope_authorized(changed, root):\n            return True\n        if _git(root, 'merge-base', 'origin/main', 'HEAD').decode().strip() != BASE:"),
    ],
    'tests/r02_ppa_ux_scope.py': [
        ("    return own | ((N.OWNED_PATHS | {N.MANIFEST}) if N is not None and N.signature_ok(root, ref) else frozenset())",
         "    return own | (N.closure_paths(root, ref) if N is not None else frozenset())"),
    ],
    'tests/test_bess02_scope.py': [
        ("    assert C.COHORT_MODULES == accepted + ('tests.bess02_scope',)\n    assert C.COHORT_MODULES[-3:] == ('tests.post432_l01_l02_scope', 'tests.r02_ppa_ux_scope', 'tests.bess02_scope')",
         "    from tests import ci_v4_perf_scope as F\n    own = accepted + ('tests.bess02_scope',)\n    # Exactly two states: the accepted BESS-only tail, or one reviewed CI-performance successor behind a complete signature.\n    assert C.COHORT_MODULES == own or (C.COHORT_MODULES == own + (F.__name__,) and F.signature_ok())\n    assert C.COHORT_MODULES[len(own) - 3:len(own)] == ('tests.post432_l01_l02_scope', 'tests.r02_ppa_ux_scope', 'tests.bess02_scope')"),
    ],
    'tests/test_r02_ppa_ux_scope.py': [
        ("    assert N.exact_blobs_ok() and (ROOT / X.REGISTRY).read_bytes() == N.expected_handoff(ROOT, X.REGISTRY)\n    old = next(ast.literal_eval(n.value) for n in ast.parse(base).body if isinstance(n, ast.Assign) and n.targets[0].id == 'COHORT_MODULES')\n    assert C.COHORT_MODULES == old + ('tests.r02_ppa_ux_scope', 'tests.bess02_scope') and C.COHORT_MODULES[-6:] == TAIL + ('tests.bess02_scope',) and len(set(C.COHORT_MODULES)) == len(C.COHORT_MODULES)",
         "    from tests import ci_v4_perf_scope as F\n    nxt = ('tests.ci_v4_perf_scope',) if 'tests.ci_v4_perf_scope' in C.COHORT_MODULES else ()\n    assert N.exact_blobs_ok() and (ROOT / X.REGISTRY).read_bytes() == (\n        F.expected_handoff(ROOT, X.REGISTRY) if nxt and F.signature_ok() else N.expected_handoff(ROOT, X.REGISTRY))\n    old = next(ast.literal_eval(n.value) for n in ast.parse(base).body if isinstance(n, ast.Assign) and n.targets[0].id == 'COHORT_MODULES')\n    core = C.COHORT_MODULES[:len(C.COHORT_MODULES) - len(nxt)]\n    assert C.COHORT_MODULES == old + ('tests.r02_ppa_ux_scope', 'tests.bess02_scope') + nxt and core[-6:] == TAIL + ('tests.bess02_scope',) and len(set(C.COHORT_MODULES)) == len(C.COHORT_MODULES)"),
    ],
    'tests/test_post432_l01_l02_scope.py': [
        ("    assert N.exact_blobs_ok() and now == N.expected_handoff(ROOT, X.REGISTRY).decode()",
         "    from tests import ci_v4_perf_scope as F\n    nxt = 'tests.ci_v4_perf_scope' in C.COHORT_MODULES\n    assert N.exact_blobs_ok() and now == (F.expected_handoff(ROOT, X.REGISTRY) if nxt and F.signature_ok() else N.expected_handoff(ROOT, X.REGISTRY)).decode()"),
    ],
}

# Correction R: the chain of older guards could not see this leaf's moved pins. Each addition below is
# one more literal, exactly-once substitution over the SAME accepted BASE bytes (applied after the
# substitutions above); none is a pattern and none widens a path set.
HANDOFFS['tests/bess02_scope.py'].append((
    "\n\ndef closure_paths(repo=None, ref=None):\n    \"\"\"This cohort's closed path set, gated by its OWN signature",
    "\n\ndef map_keys(repo=None, ref=None):\n    \"\"\"Every current-map key a forward leaf may move, own keys first; low level, gated by the successor's signature only.\"\"\"\n    root = Path(repo) if repo is not None else ROOT\n    N = _next()\n    return tuple(MAP_KEYS) + (tuple(N.map_keys(root, ref)) if N is not None and N.signature_ok(root, ref) else ())\n\n\ndef closure_paths(repo=None, ref=None):\n    \"\"\"This cohort's closed path set, gated by its OWN signature"))
HANDOFFS['tests/r02_ppa_ux_scope.py'].extend([
    ("\ndef map_keys(repo=None, ref=None):\n    root = Path(repo) if repo is not None else ROOT\n    N = _next()\n    return tuple(MAP_KEYS) + (tuple(N.MAP_KEYS) if N is not None and N.signature_ok(root, ref) else ())\n",
     "\ndef map_keys(repo=None, ref=None):\n    root = Path(repo) if repo is not None else ROOT\n    N = _next()\n    return tuple(MAP_KEYS) + (tuple(N.map_keys(root, ref)) if N is not None and N.signature_ok(root, ref) else ())\n"),
    ("\n    return {k: v for k, v in _next_pins(root, ref).items() if k in N.MAP_KEYS and k not in CURRENT_MAPS}\n\n\ndef closure_paths",
     "\n    return {k: v for k, v in _next_pins(root, ref).items() if k in N.map_keys(root, ref) and k not in CURRENT_MAPS}\n\n\ndef closure_paths"),
    ("\n                _read(root, p, ref) == _object_fact(root, 'show', BASE + ':' + p) for p in FROZEN))",
     "\n                _read(root, p, ref) == _object_fact(root, 'show', BASE + ':' + p)\n                or N.supersedes(p, _blob(_read(root, p, ref)), root, ref) for p in FROZEN))"),
])
# The older BESS01 guard freezes three test files at its own BASE; a forward leaf's exact reviewed pin is the only other accepted value.
HANDOFFS['tests/on_bess01_scope.py'] = [
    ("        if any(_read(root, p, ref) != _base(root, 'show', BASE + ':' + p) for p in FROZEN):\n            return False",
     "        if any(_read(root, p, ref) != _base(root, 'show', BASE + ':' + p)\n               and not (next_ok and S.later_supersedes(p, _blob(_read(root, p, ref)), root, ref)) for p in FROZEN):\n            return False"),
    # A current map may also carry a pin the forward chain moved (the leaf's own map keys), exactly its reviewed pin and no other value.
    ("        if any(b[p] != a[p] and (p not in SUPERSEDED - CURRENT_MAPS or b[p] != pins[p]) for p in a):",
     "        S = _successor()\n        later = set(S._tip_map_keys(root, ref)) if S is not None and S.signature_ok(root, ref) else set()\n        if any(b[p] != a[p] and (p not in (SUPERSEDED - CURRENT_MAPS) | later or b[p] != pins[p]) for p in a):"),
]
# The PR2a/PR2b/PR2c/PR3b1 era guards judge every moved pin of the shared integration manifests through the PR3b1 guard's
# supersession hook. That hook admits exactly one more path here: the module-weights pin this leaf moves, at the reviewed pin only.
HANDOFFS['tests/ux_pr3b1_scope.py'] = [
    ("def supersedes(path, value, repo=None, ref=None):\n    return path in SUPERSEDED and exact_blobs_ok(repo,ref) and effective_pins(repo,ref).get(path)==value",
     "def supersedes(path, value, repo=None, ref=None):\n    return (path in SUPERSEDED or path == 'docs/ci_v4/module_weights.json') and exact_blobs_ok(repo,ref) and effective_pins(repo,ref).get(path)==value"),
]

HANDOFFS['tests/test_r02_ppa_ux_scope.py'].append((
    "    for path in ('frontend/src/app/workflow/PPAEditorView.tsx', 'frontend/src/app/api.ts', 'frontend/src/app/editing/pendingEdits.ts', 'tests/on_bess01_scope.py'):\n        assert _git(ROOT, 'rev-parse', 'HEAD:' + path) == _git(ROOT, 'rev-parse', X.BASE + ':' + path), path",
    "    for path in ('frontend/src/app/workflow/PPAEditorView.tsx', 'frontend/src/app/api.ts', 'frontend/src/app/editing/pendingEdits.ts'):\n        assert _git(ROOT, 'rev-parse', 'HEAD:' + path) == _git(ROOT, 'rev-parse', X.BASE + ':' + path), path\n    # the BESS01 guard stays at BASE except for the one reviewed CI-performance forward handoff of exactly those bytes\n    from tests import ci_v4_perf_scope as F\n    assert F.exact_blobs_ok() and (ROOT / 'tests/on_bess01_scope.py').read_bytes() == F.expected_handoff(ROOT, 'tests/on_bess01_scope.py')"))

# The current-map manifests whose registry pin moves with this integration: they are re-pinned
# to the NEW composite-registry blob in canonical form and owned literally by this leaf, exactly
# as the BESS02 integration re-pinned them for its own registration append.
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

# Files pinned literally at their exact current bytes (no handoff substitution needed).
DIRECT_PATHS = frozenset((
    'tests/ci_v4_perf_scope.py',
    'tests/test_ci_v4_perf_scope.py',
    'tests/test_trust_readiness_controls.py',
    'tests/test_rc_sec_csrf_successor.py',
    'tests/test_finval_f01_fixture_integrity.py',
    'docs/ci_v4/module_weights.json',
))

#: pre-existing files this leaf edits directly (the other two DIRECT paths are new files with no BASE blob)
DIRECT_EDITS = DIRECT_PATHS - {'tests/ci_v4_perf_scope.py', 'tests/test_ci_v4_perf_scope.py'}
SUPERSEDED = frozenset(HANDOFFS) | DIRECT_EDITS
OWNED_PATHS = frozenset(HANDOFFS) | DIRECT_PATHS | CURRENT_MAPS
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
            raise ValueError('reviewed handoff is missing or ambiguous: %s' % path)
        raw = raw.replace(old, new)
    return raw.encode()


def reviewed_edits_ok(repo=None, ref=None):
    root = Path(repo) if repo is not None else ROOT
    try:
        return all(_read(root, p, ref) == expected_handoff(root, p) for p in HANDOFFS)
    except (OSError, ValueError, KeyError, TypeError, subprocess.CalledProcessError):
        return False


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
            if p != MANIFEST and _blob(_read(root, p, ref)) != pins[p]:
                return False
        # No safety authority ever joins this cohort: no engine, core, domain, workflow,
        # frontend or static byte is owned, so none can be admitted through it.
        if any(p.startswith(FORBIDDEN_PREFIXES) for p in OWNED_PATHS | {MANIFEST}):
            return False
        if closure:
            changed = set(_git(root, 'diff', '--name-only', '--no-renames', BASE, *([ref] if ref else []), '--').decode().splitlines())
            allowed = OWNED_PATHS | {MANIFEST}
            if not changed <= allowed:
                return False
            # Foreign accepted bytes/modes are re-verified against BASE by the BESS02 root leaf's
            # closure leg inside the same composite (this leaf follows the F03 successor convention:
            # it owns its literal set and defers whole-tree byte/mode parity to the root).
            if ref is None:
                extra = set(_git(root, 'ls-files', '--others', '--exclude-standard').decode().splitlines())
                from tests.on_bess01_scope import _generated_evidence_ok
                if any(not _generated_evidence_ok(root, p) for p in extra - allowed):
                    return False
        return True
    except (OSError, ValueError, KeyError, TypeError, AttributeError, subprocess.CalledProcessError):
        return False


def map_keys(repo=None, ref=None):
    return tuple(MAP_KEYS)


def closure_paths(repo=None, ref=None):
    """This leaf's closed path set, gated by its OWN signature (no successor below it on this branch)."""
    root = Path(repo) if repo is not None else ROOT
    with scoped():
        if not signature_ok(root, ref):
            return frozenset()
        return OWNED_PATHS | {MANIFEST}


def allowed_path(path, repo=None, ref=None):
    return path in closure_paths(repo, ref)


def base_blob(path, repo=None, ref=None):
    return manifest(repo, ref).get('base_blobs', {}).get(path)


def supersedes(path, value, repo=None, ref=None):
    return path in SUPERSEDED and signature_ok(repo, ref) and effective_pins(repo, ref).get(path) == value


def effective_pins(repo=None, ref=None, *, signature=False):
    return dict(manifest(repo, ref).get('source_blobs', {}))


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


def valid(repo=None, ref=None):
    from tests.fin_v2_cohorts import valid as composite
    return exact_blobs_ok(repo, ref) and composite(repo, ref)


def matches(path, source=None, *, repo=None, ref=None):
    pins = manifest(repo, ref).get('source_blobs', {})
    raw = source.encode() if isinstance(source, str) else source
    return path in pins and valid(repo, ref) and (source is None or _blob(raw) == pins[path])


def protected_blobs(repo=None, ref=None):
    return {}  # No financial_engine/finco_core/domain authority.
