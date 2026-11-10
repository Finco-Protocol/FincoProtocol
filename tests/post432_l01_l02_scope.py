"""Closed post-#434 L01/L02 exact-source cohort: one narrow presentation correction, nothing else.

Authority: the Financial Owner's post-#432 live-acceptance correction brief (L01 sizing-target presentation noise, L02 template-card rate
unit). Presentation only: no financial methodology, engine, security, tax, CSRF/route, expected financial value or CI-policy change.

``BASE`` is accepted main after the #434 merge (``ebb9c07c``), authenticated by commit, tree AND the recorded BASE blob of every path this cohort
supersedes. The two original L01/L02 commits (``ORIGINAL_PATCH``) are checked ancestors of every head and the two product sources must equal
the blobs those commits recorded, so the post-#434 baseline stays traceable to the reviewed patch instead of being recomputed over unreviewed bytes.

It is the tip of the successor chain ... -> on_bess01 (#433) -> onaccept01 (#434) -> this cohort. The two accepted predecessors learn of it only
through the literal, one-occurrence reviewed substitutions in ``HANDOFFS`` (verified byte for byte by ``reviewed_edits_ok``), the registry gains
exactly this module name, and the seven current-source maps move only the two pins of the handed-off files. No historical manifest field,
BASE/tree or tamper control is rewritten; no pattern or wildcard is admitted.

Termination: every check here is low level (git objects and this manifest); it never imports an older cohort or the composite registry.
"""
from pathlib import Path
from contextlib import contextmanager
import hashlib
import json
import subprocess

ROOT = Path(__file__).resolve().parents[1]
BASE = 'ebb9c07c30c733cbb39e9af58833f0b22baf7069'
BASE_TREE = 'b069d3d930bd41d56949c7afa86c779a539863e8'
ORIGINAL_PATCH = ('b5cd78765b013ea1f5fd1d1367d4d7a60ea94f43', 'e998cbc5a23cf600306e7942570809878398f991')
ORIGINAL_SOURCE_ANCHOR = ORIGINAL_PATCH[1]
MANIFEST = 'docs/react_migration/post432_l01_l02/SOURCE_SUCCESSOR.json'
SCHEMA = 'POST434_L01_L02_EXACT_SOURCE_V1'
REGISTRY = 'tests/fin_v2_cohorts.py'
REGISTRY_MARKER = "'tests.onaccept01_scope')"
REGISTRY_NEW = "'tests.onaccept01_scope', 'tests.post432_l01_l02_scope')"
SELF_MODULE = 'tests.post432_l01_l02_scope'

SOURCE_PATHS = frozenset(('app/v2/debt_metrics_projection.py', 'app/v2/react_projects.py'))
TEST_PATHS = frozenset((
    'tests/test_post432_l01_sizing_target_noise_v1.py',
    'tests/test_post432_l02_template_rate_percent_v1.py',
    'tests/post432_l02_full_oracle.py',
    'tests/test_post432_l01_l02_scope.py',
))
HANDOFF_FILES = frozenset(('tests/on_bess01_scope.py', 'tests/onaccept01_scope.py'))
GOVERNANCE_PATHS = HANDOFF_FILES | {REGISTRY, 'tests/post432_l01_l02_scope.py', 'tests/test_ux_pr3b2_scope.py'}
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
#: the only two handed-off pins a current map may move (the keys every map already records for them)
MAP_KEYS = (REGISTRY, 'tests/on_bess01_scope.py', 'tests/test_ux_pr3b2_scope.py')
OWNED_PATHS = SOURCE_PATHS | TEST_PATHS | GOVERNANCE_PATHS | CURRENT_MAPS
SUPERSEDED = SOURCE_PATHS | HANDOFF_FILES | {REGISTRY, 'tests/test_ux_pr3b2_scope.py'} | CURRENT_MAPS
FORBIDDEN_PREFIXES = ('financial_engine/', 'finco_core/', 'domain/', '.github/', 'tools/', 'frontend/', 'static/', 'tax_reference_registry/', 'scripts/')
FORBIDDEN_PATHS = frozenset(('main_web.py',))

_ONACC_TIP = (
    "def _tip():\n    from tests.fin_v2_cohorts import COHORT_MODULES\n    if 'tests.post432_l01_l02_scope' not in COHORT_MODULES:\n        return None\n"
    "    from tests import post432_l01_l02_scope\n    return post432_l01_l02_scope\n\n\n"
    "def _tip_pins(root, ref):\n    T = _tip()\n    if T is None or not T.signature_ok(root, ref):\n        return {}\n"
    "    return {p: b for p, b in T.manifest(root, ref)['source_blobs'].items() if p in T.SUPERSEDED}\n\n\n"
    "def later_owned(repo=None, ref=None):\n    root = Path(repo) if repo is not None else ROOT\n    T = _tip()\n"
    "    return (T.OWNED_PATHS | {T.MANIFEST}) if T is not None and T.signature_ok(root, ref) else frozenset()\n\n\n"
    "def later_supersedes(path, value, repo=None, ref=None):\n    root = Path(repo) if repo is not None else ROOT\n    T = _tip()\n"
    "    return T is not None and T.signature_ok(root, ref) and T.supersedes(path, value, root, ref)\n\n\n"
    "def effective_pins(repo=None, ref=None, *, signature=False):\n    root = Path(repo) if repo is not None else ROOT\n"
    "    pins = {p: b for p, b in manifest(root, ref).get('source_blobs', {}).items() if p in SUPERSEDED}\n    pins.update(_tip_pins(root, ref))\n    return pins\n\n\n"
    "def _reviewed_handoffs_ok(root, ref):\n    T = _tip()\n    if T is not None and T.signature_ok(root, ref):\n        return T.reviewed_edits_ok(root, ref)\n"
    "    for path, substitutions in HANDOFFS.items():"
)
HANDOFFS = {
    'tests/onaccept01_scope.py': (
        ("def _reviewed_handoffs_ok(root, ref):\n    for path, substitutions in HANDOFFS.items():", _ONACC_TIP),
        ("        allowed = OWNED_PATHS | {MANIFEST}\n        identity = allowed if closure else allowed - CURRENT_MAPS\n",
         "        allowed = OWNED_PATHS | {MANIFEST}\n        later = later_owned(root,ref)\n        cur = dict(pins, **_tip_pins(root,ref))\n        identity = allowed if closure else allowed - CURRENT_MAPS\n"),
        ("            if (any(value != pins[p] for p,value in zip(ordered,actual) if p != MANIFEST)", "            if (any(value != cur[p] for p,value in zip(ordered,actual) if p != MANIFEST)"),
        ("            if any(_blob(_read(root,p,ref)) != pins[p] for p in identity if p != MANIFEST):", "            if any(_blob(_read(root,p,ref)) != cur[p] for p in identity if p != MANIFEST):"),
        ("        if not _reviewed_handoffs_ok(root,ref) or not _maps_ok(root,ref,pins,closure):", "        if not _reviewed_handoffs_ok(root,ref) or not _maps_ok(root,ref,cur,closure):"),
        ("            if not changed <= allowed:", "            if not changed <= (allowed | later):"),
        ("                    if path in allowed:\n                        continue", "                    if path in allowed or path in later:\n                        continue"),
        ("    for path in CURRENT_MAPS:\n        expected = json.loads(_base(root,'show',BASE+':'+path))\n        for key in (SUPERSEDED - CURRENT_MAPS) & expected['source_blobs'].keys():",
         "    for path in CURRENT_MAPS:\n        expected = json.loads(_base(root,'show',BASE+':'+path))\n        for key in ((SUPERSEDED - CURRENT_MAPS) | (set(_tip_pins(root,ref)) - CURRENT_MAPS)) & expected['source_blobs'].keys():"),
        ("def nontrust_scope_authorized(changed, repo=None):\n    root = Path(repo) if repo is not None else ROOT\n    try:\n",
         "def nontrust_scope_authorized(changed, repo=None):\n    root = Path(repo) if repo is not None else ROOT\n    try:\n"
         "        T = _tip()\n        if T is not None and T.signature_ok(root) and T.nontrust_scope_authorized(changed, root):\n            return True\n"),
        ("def allowed_path(path, repo=None, ref=None):\n    return path in OWNED_PATHS | {MANIFEST}", "def allowed_path(path, repo=None, ref=None):\n    return path in OWNED_PATHS | {MANIFEST} or path in later_owned(repo, ref)"),
        ("return path in SUPERSEDED and signature_ok(repo,ref) and manifest(repo,ref)['source_blobs'].get(path)==value", "return path in SUPERSEDED and signature_ok(repo,ref) and effective_pins(repo,ref).get(path)==value"),
    ),
    'tests/on_bess01_scope.py': (
        ("        pins.update({p: b for p, b in S.manifest(repo, ref)['source_blobs'].items() if p in S.SUPERSEDED})", "        pins.update(S.effective_pins(repo, ref))"),
        ("        next_pins = S.manifest(root, ref)['source_blobs'] if next_ok else {}", "        next_pins = S.effective_pins(root, ref) if next_ok else {}"),
        ("            allowed = allowed | S.OWNED_PATHS | {S.MANIFEST}", "            allowed = allowed | S.OWNED_PATHS | {S.MANIFEST} | S.later_owned(root, ref)"),
        ("                if not _foreign_bytes_and_modes_ok(root):", "                if not _foreign_bytes_and_modes_ok(root, S.later_owned(root, ref) if next_ok else frozenset()):"),
        ("def _foreign_bytes_and_modes_ok(root):", "def _foreign_bytes_and_modes_ok(root, later=frozenset()):"),
        ("        if path in OWNED_PATHS | {MANIFEST}:\n            continue", "        if path in OWNED_PATHS | {MANIFEST} | later:\n            continue"),
        ("def supersedes(path, value, repo=None, ref=None):\n    return path in SUPERSEDED and exact_blobs_ok(repo, ref) and effective_pins(repo, ref).get(path) == value",
         "def supersedes(path, value, repo=None, ref=None):\n    if path in SUPERSEDED and exact_blobs_ok(repo, ref) and effective_pins(repo, ref).get(path) == value:\n        return True\n"
         "    S = _successor()\n    return S is not None and S.signature_ok(repo, ref) and S.later_supersedes(path, value, repo, ref)"),
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
        yield
    finally:
        _SCOPE.pop()


def exact_blobs_ok(repo=None, ref=None):
    return _verdict(repo, ref, True)


def signature_ok(repo=None, ref=None):
    """Source/base/mode/handoff authority only; the closed changed-set (full exactness) is not judged."""
    return _verdict(repo, ref, False)


def _exact_next_scoped(repo, ref, closure):
    # One evaluation of this cohort asks its successor for the same verdict many times; share one memo for exactly that evaluation.
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
    if 'tests.r02_ppa_ux_scope' not in COHORT_MODULES:
        return None
    from tests import r02_ppa_ux_scope
    return r02_ppa_ux_scope


def _next_pins(root, ref):
    N = _next()
    if N is None or not N.signature_ok(root, ref):
        return {}
    return dict(N.effective_pins(root, ref))


def map_keys(repo=None, ref=None):
    root = Path(repo) if repo is not None else ROOT
    N = _next()
    return tuple(MAP_KEYS) + (tuple(N.map_keys(root, ref)) if N is not None and N.signature_ok(root, ref) else ())


def _next_moved(root, ref):
    N = _next()
    if N is None or not N.signature_ok(root, ref):
        return {}
    return {k: v for k, v in _next_pins(root, ref).items() if k in N.map_keys(root, ref) and k not in CURRENT_MAPS}


def closure_paths(repo=None, ref=None):
    root = Path(repo) if repo is not None else ROOT
    N = _next()
    base = OWNED_PATHS | {MANIFEST}
    return base | (N.closure_paths(root, ref) if N is not None and N.signature_ok(root, ref) else frozenset())


def reviewed_edits_ok(repo=None, ref=None):
    """Both predecessor modules and the registry equal the literal reviewed substitutions over BASE, byte for byte."""
    root = Path(repo) if repo is not None else ROOT
    try:
        N = _next()
        if N is not None and N.signature_ok(root, ref):
            return N.reviewed_edits_ok(root, ref)
        for path in sorted(HANDOFF_FILES | {REGISTRY}):
            expected = expected_handoff(root, path)
            if expected is None or _read(root, path, ref) != expected:
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
        # 1. immutable provenance: accepted post-#434 main and the two ORIGINAL L01/L02 commits are ancestors of the evaluated head
        _git(root, 'merge-base', '--is-ancestor', BASE, head)
        for original in ORIGINAL_PATCH:
            _git(root, 'merge-base', '--is-ancestor', original, head)
        if _object_fact(root, 'rev-parse', BASE + '^{tree}').decode().strip() != BASE_TREE:
            return False
        # 2. the recorded BASE blob of every superseded path is what git holds at BASE
        paths = sorted(base_blobs)
        if _object_fact(root, 'rev-parse', *[BASE + ':' + p for p in paths]).decode().split() != [base_blobs[p] for p in paths]:
            return False
        # 3. the product sources are the blobs the reviewed ORIGINAL patch recorded (no recomputed-over-unreviewed pin)
        original = _object_fact(root, 'rev-parse', *[ORIGINAL_SOURCE_ANCHOR + ':' + p for p in sorted(SOURCE_PATHS)]).decode().split()
        if original != [pins[p] for p in sorted(SOURCE_PATHS)]:
            return False
        # 4. one exact blob per owned path (git's own hashing, so LF and CRLF checkouts agree)
        if ref is None:
            computed = {p: _git(root, 'hash-object', root / p).decode().strip() for p in sorted(pins)}
            if computed != cur:
                return False
        else:
            listed = {}
            for line in _git(root, 'ls-tree', '-r', ref, '--', *sorted(pins)).decode().splitlines():
                meta, name = line.split('\t', 1)
                listed[name] = meta.split()[2]
            if listed != cur:
                return False
        # 5. no owned file is executable or a link in the evaluated state
        if ref is None:
            for p in OWNED_PATHS | {MANIFEST}:
                f = root / p
                if f.is_symlink() or not f.is_file() or f.stat().st_mode & 0o111:
                    return False
        else:
            modes = _git(root, 'ls-tree', '-r', ref, '--', *sorted(OWNED_PATHS | {MANIFEST})).decode().splitlines()
            if len(modes) != len(OWNED_PATHS | {MANIFEST}) or any(not line.startswith('100644 ') for line in modes):
                return False
        # 6. the literal reviewed predecessor/registry substitutions and the pinned current maps
        if not reviewed_edits_ok(root, ref):
            return False
        for path in sorted(CURRENT_MAPS):
            expected = expected_map(root, path, cur, _next_moved(root, ref))
            if cur[path] != _blob(expected) or (closure and _read(root, path, ref) != expected):
                return False
        # 7. closed change set: since BASE nothing outside the literal owned set moved (full exactness only)
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
    root = Path(repo) if repo is not None else ROOT
    return N is not None and N.signature_ok(root, ref) and N.supersedes(path, value, root, ref)


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
    """The no-engine/writer/Radar scope obligation of the trust-readiness guard for THIS exact cohort: the real main merge-base diff, not an invented trigger."""
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
