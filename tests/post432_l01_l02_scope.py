"""Closed post-#432 L01/L02 exact-source cohort: one narrow presentation correction, nothing else.

Authority: the Financial Owner's post-#432 live-acceptance correction brief (L01 sizing-target presentation
noise, L02 template-card rate unit). It is a presentation correction only: no financial methodology, engine,
security, tax, CSRF/route, expected financial value or CI-policy change.

``BASE`` is main after the #432 merge (``91e89bdd``): an ancestor of every head of this cohort, authenticated by
commit, tree AND the recorded BASE blob of every path this cohort supersedes. No older cohort's historical pin or
manifest is rewritten: each older guard follows this cohort only through its existing bounded one-way successor
hooks (``supersedes``/``allowed_path``), only while this cohort is exact, only for the exact pin recorded here.

What it owns: a literal, finite set (two presentation sources, the two regression modules, the two governance
glue modules that already hold the #432 successor connection, this cohort, its manifest and its tests).
Nothing else is admitted: no pattern, no wildcard, no ``financial_engine/``, ``finco_core/``, ``domain/``,
``.github/``, ``tools/``, ``frontend/``, ``static/``, ``tax_reference_registry/`` or ``main_web.py`` path, and no
other ``app/`` path (so no route, CSRF, router or lifecycle module can ride along).

Termination: every check is low level. It reads git objects and this cohort's manifest only; it never imports an
older cohort or the composite registry, so there is no recursive self-approval.
"""
from pathlib import Path
from contextlib import contextmanager
import hashlib
import json
import subprocess

ROOT = Path(__file__).resolve().parents[1]
BASE = '91e89bdd2127f5ec5d0e62833a1f9c3397ad5d14'
BASE_TREE = 'e9573d7802b319deb943dab60667778a431370e4'
MANIFEST = 'docs/react_migration/post432_l01_l02/SOURCE_SUCCESSOR.json'
SCHEMA = 'POST432_L01_L02_EXACT_SOURCE_V1'

SOURCE_PATHS = frozenset((
    'app/v2/debt_metrics_projection.py',
    'app/v2/react_projects.py',
))
TEST_PATHS = frozenset((
    'tests/test_post432_l01_sizing_target_noise_v1.py',
    'tests/test_post432_l02_template_rate_percent_v1.py',
    'tests/post432_l02_full_oracle.py',
    'tests/test_post432_l01_l02_scope.py',
))
GOVERNANCE_PATHS = frozenset((
    'tests/post432_l01_l02_scope.py',
    'tests/tax_reference_registry_scope.py',
    'tests/ux_pr3b2_scope.py',
    'tests/test_ux_pr3b2_scope.py',
    'tests/test_tax_reference_registry_scope.py',
))
OWNED_PATHS = SOURCE_PATHS | TEST_PATHS | GOVERNANCE_PATHS
# Owned paths that already exist at BASE (older cohorts pin them): their BASE blob is recorded in the manifest.
SUPERSEDED = frozenset((
    'app/v2/debt_metrics_projection.py',
    'app/v2/react_projects.py',
    'tests/tax_reference_registry_scope.py',
    'tests/ux_pr3b2_scope.py',
    'tests/test_ux_pr3b2_scope.py',
    'tests/test_tax_reference_registry_scope.py',
))
FORBIDDEN_PREFIXES = ('financial_engine/', 'finco_core/', 'domain/', '.github/', 'tools/', 'frontend/', 'static/', 'tax_reference_registry/')
FORBIDDEN_PATHS = frozenset(('main_web.py',))


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
    return (not any(p.startswith(FORBIDDEN_PREFIXES) or p in FORBIDDEN_PATHS or '..' in p.split('/') or p.startswith('/')
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
    """Source/base/mode authority only; the closed changed-set (full exactness) is not judged."""
    return _verdict(repo, ref, False)


def _verdict(repo, ref, closure):
    if _SCOPE:
        key = (str(repo if repo is not None else ROOT), ref, closure)
        memo = _SCOPE[-1]
        if key not in memo:
            memo[key] = _exact(repo, ref, closure)
        return memo[key]
    return _exact(repo, ref, closure)


def _exact(repo=None, ref=None, closure=True):
    root = Path(repo) if repo is not None else ROOT
    data = manifest(root, ref)
    pins, base_blobs = data.get('source_blobs', {}), data.get('base_blobs', {})
    if not data or not _owned_ok() or set(pins) != OWNED_PATHS - {MANIFEST} or set(base_blobs) != SUPERSEDED:
        return False
    try:
        head = ref or 'HEAD'
        # 1. immutable provenance: the #432 merge and its tree are ancestors of the evaluated head
        _git(root, 'merge-base', '--is-ancestor', BASE, head)
        if _object_fact(root, 'rev-parse', BASE + '^{tree}').decode().strip() != BASE_TREE:
            return False
        # 2. the recorded BASE blob of every superseded path is what git holds at BASE
        paths = sorted(base_blobs)
        if _object_fact(root, 'rev-parse', *[BASE + ':' + p for p in paths]).decode().split() != [base_blobs[p] for p in paths]:
            return False
        # 3. one exact blob per owned path (git's own hashing, so LF and CRLF checkouts agree)
        if ref is None:
            computed = {p: _git(root, 'hash-object', root / p).decode().strip() for p in sorted(pins)}
            if computed != pins:
                return False
        else:
            listed = {}
            for line in _git(root, 'ls-tree', '-r', ref, '--', *sorted(pins)).decode().splitlines():
                meta, name = line.split('\t', 1)
                listed[name] = meta.split()[2]
            if listed != pins:
                return False
        # 4. no owned file is executable or a link in the evaluated state
        if ref is None:
            for p in OWNED_PATHS | {MANIFEST}:
                f = root / p
                if f.is_symlink() or (f.exists() and f.stat().st_mode & 0o111):
                    return False
        else:
            modes = _git(root, 'ls-tree', '-r', ref, '--', *sorted(OWNED_PATHS | {MANIFEST})).decode().splitlines()
            if len(modes) != len(OWNED_PATHS | {MANIFEST}) or any(not line.startswith('100644 ') for line in modes):
                return False
        # 5. closed change set: since BASE nothing outside the literal owned set moved (full exactness only)
        if closure:
            changed = set(_git(root, 'diff', '--name-only', '--no-renames', BASE, *([ref] if ref else []), '--').decode().splitlines())
            if any(p not in OWNED_PATHS and p != MANIFEST for p in changed):
                return False
            if ref is None:
                extra = set(_git(root, 'ls-files', '--others', '--exclude-standard').decode().splitlines())
                if any(p not in OWNED_PATHS and p != MANIFEST and not _evidence_only(root, p) for p in extra):
                    return False
        return True
    except (OSError, ValueError, KeyError, TypeError, AttributeError, subprocess.CalledProcessError):
        return False


def _evidence_only(root, p):
    f = Path(root) / p
    return (p.startswith('evidence/') and p.endswith(('.json', '.xml', '.png', '.txt', '.csv', '.html', '.zip'))
            and f.is_file() and not f.is_symlink() and not f.stat().st_mode & 0o111)


def allowed_path(path, repo=None, ref=None):
    return path in OWNED_PATHS or path == MANIFEST


def base_blob(path, repo=None, ref=None):
    return manifest(repo, ref).get('base_blobs', {}).get(path)


def supersedes(path, value, repo=None, ref=None):
    """Bounded supersession for the older guards: true only for a path of ``SUPERSEDED``, only while this cohort is exact, only for its exact pin."""
    return path in SUPERSEDED and exact_blobs_ok(repo, ref) and manifest(repo, ref).get('source_blobs', {}).get(path) == value


def effective_pins(repo=None, ref=None):
    return dict(manifest(repo, ref).get('source_blobs', {}))


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
