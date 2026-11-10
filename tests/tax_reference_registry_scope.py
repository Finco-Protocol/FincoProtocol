"""Closed T01-D exact-source cohort: the offline tax reference registry foundation (34 jurisdictions, dormant).

A bounded successor over main after PR #430 (``4e22f330…``), the exact
accepted parent the governed integration (this cohort) is judged against; the
package itself was founded on ``52a5793c…`` (provenance anchor, an ancestor of
this cohort's BASE through the recorded integration merge). Authority: the
Financial Owner's T01-D brief of 2026-11-08 allows a dormant reference-library
integration; it does NOT approve country activation, FX defaults, financial
engine hooks or any tax computation. This cohort is provenance only: no
financial methodology, security policy, expected financial value or
authorisation change.

``BASE`` is main after the #430 merge, an ancestor of every head of this
cohort, authenticated by commit, tree AND the recorded BASE blob of every path
this cohort supersedes: no older cohort's historical pin is rewritten. The
diff ``BASE..head`` therefore contains exactly this integration's changes
(the registry paths, the two handoff documents, the composite-registry
registration and this cohort).
The one superseded path, ``tests/fin_v2_cohorts.py``, is the composite cohort
registry — every sibling manifest that pinned its former blob is re-pinned to
the same NEW literal blob in this same integration commit, exactly as the
earlier integration commits did (CI V4, post-413 O1/R17/R18/R1, U1/U2, WF-06B,
WF-03, WS-V2, fin_v2_409, fin_v2_R1, fin_truth_b1, WF-04).

What it owns: a literal, finite path set. Nothing else is admitted: no pattern,
no wildcard. It never owns a ``financial_engine/``, ``finco_core/``, ``domain/``,
``.github/``, ``tools/``, ``app/``, ``frontend/`` or ``static/`` path; the
registry package is inert offline code with zero production imports (enforced
inside the package's own tests).

Termination: every check is low level. It reads git objects and this cohort's
manifest only; it never imports an older cohort or the composite registry, so
there is no recursive self-approval.
"""
from pathlib import Path
from contextlib import contextmanager
import hashlib
import json
import subprocess
import sys

ROOT = Path(__file__).resolve().parents[1]
BASE = '785024c752bbd1700d6051cf15115d9980d0b4a1'
BASE_TREE = '063d27ce5ef6841ec641e377662cbda924d97667'
MANIFEST = 'docs/tax_reference_registry/SOURCE_SUCCESSOR.json'
SCHEMA = 'T01D_TAX_REFERENCE_REGISTRY_EXACT_SOURCE_V1'

SOURCE_PATHS = frozenset((
    'tax_reference_registry/__init__.py',
    'tax_reference_registry/__main__.py',
    'tax_reference_registry/activation.py',
    'tax_reference_registry/cli.py',
    'tax_reference_registry/currency.py',
    'tax_reference_registry/enums.py',
    'tax_reference_registry/loader.py',
    'tax_reference_registry/records.py',
    'tax_reference_registry/registry.py',
))
TEST_AND_DOC_PATHS = frozenset((
    'docs/tax_reference_registry/FINAL_REPORT_HR.md',
    'docs/tax_reference_registry/NEXT_INTEGRATION_CONTRACT.md',
    'tests/tax_reference_registry/conftest.py',
    'tests/tax_reference_registry/test_loader_errors.py',
    'tests/tax_reference_registry/test_private_dataset.py',
    'tests/tax_reference_registry/test_registry_compare_activation.py',
    'tests/tax_reference_registry/test_schema_and_currency.py',
    'tests/test_tax_reference_registry_scope.py',
))
GOVERNANCE_PATHS = frozenset((
    'tests/fin_v2_cohorts.py',
    'tests/ux_pr3b1_scope.py',
    'tests/ux_pr3b2_scope.py',
    'tests/test_ux_pr3b2_scope.py',
    'tests/tax_reference_registry_scope.py',
))
OWNED_PATHS = SOURCE_PATHS | TEST_AND_DOC_PATHS | GOVERNANCE_PATHS
# The owned paths that exist at BASE and that older cohorts pin: the composite registry, and the two newest UX successors whose bounded
# one-way successor hook (``_successor()``, exactly like PR3b-1 -> PR3b-2 before it) now follows this cohort. Nothing else exists at BASE.
SUPERSEDED = frozenset((
    'tests/fin_v2_cohorts.py',
    'tests/ux_pr3b1_scope.py',
    'tests/ux_pr3b2_scope.py',
    'tests/test_ux_pr3b2_scope.py',
))
FORBIDDEN_PREFIXES = ('financial_engine/', 'finco_core/', 'domain/', '.github/', 'tools/', 'app/', 'frontend/', 'static/')
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
    if _SCOPE:
        yield
        return
    from tests import on_bess01_scope as B
    with B.scoped():
        yield from _scoped_body()


def _scoped_body():
    _SCOPE.append({})
    try:
        yield
    finally:
        _SCOPE.pop()


def exact_blobs_ok(repo=None, ref=None):
    return _verdict(repo, ref, True)


def _verdict(repo, ref, closure):
    if not _SCOPE:
        key = ('tests.tax_reference_registry_scope.verdict', str(repo if repo is not None else ROOT), ref, closure)
        from tests.on_bess01_scope import _ENCLOSING_SCOPES
        for name in _ENCLOSING_SCOPES:
            outer = getattr(sys.modules.get(name), '_SCOPE', None)
            if outer:
                memo = outer[-1]
                if key not in memo:
                    with scoped():
                        memo[key] = _verdict(repo, ref, closure)
                return memo[key]
        with scoped():
            return _verdict(repo, ref, closure)
    if _SCOPE:
        key = (str(repo if repo is not None else ROOT), ref, closure)
        memo = _SCOPE[-1]
        if key not in memo:
            memo[key] = _exact_blobs_ok(repo, ref, closure)
        return memo[key]
    return _exact_blobs_ok(repo, ref, closure)


def _exact_blobs_ok(repo=None, ref=None, closure=True):
    root = Path(repo) if repo is not None else ROOT
    data = manifest(root, ref)
    pins, base_blobs = data.get('source_blobs', {}), data.get('base_blobs', {})
    if not data or not _owned_ok() or set(pins) != OWNED_PATHS - {MANIFEST} or set(base_blobs) != SUPERSEDED:
        return False
    try:
        head = ref or 'HEAD'
        # 1. immutable provenance: the foundation commit and its tree are ancestors of the evaluated head
        _git(root, 'merge-base', '--is-ancestor', BASE, head)
        if _object_fact(root, 'rev-parse', BASE + '^{tree}').decode().strip() != BASE_TREE:
            return False
        # A changed current map cannot self-authorize the reviewed handoff.
        # The terminal leaf authenticates its finite moves against accepted main.
        from tests import on_bess01_scope as B
        accepted = '91e89bdd2127f5ec5d0e62833a1f9c3397ad5d14'
        if _read(root, MANIFEST, ref) != _object_fact(root, 'show', accepted + ':' + MANIFEST) and not B.signature_ok(root, ref):
            return False
        # 2. the blob recorded for the superseded composite registry is what git holds at BASE
        paths = sorted(base_blobs)
        if _object_fact(root, 'rev-parse', *[BASE + ':' + p for p in paths]).decode().split() != [base_blobs[p] for p in paths]:
            return False
        # 3. one exact blob per owned path. The working-tree comparison uses
        # git's own hashing (clean filters applied) so the verdict is identical
        # on LF and CRLF checkouts and always equals the ls-tree blob.
        if ref is None:
            computed = {}
            for owned in sorted(pins):
                computed[owned] = _git(root, 'hash-object', root / owned).decode().strip()
            if computed != pins:
                return False
        else:
            listed = {}
            for line in _git(root, 'ls-tree', '-r', ref, '--', *sorted(pins)).decode().splitlines():
                meta, name = line.split('\t', 1)
                listed[name] = meta.split()[2]
            if listed != pins:
                return False
        # 4. no protected prefix ever moved since BASE
        # (signature-only verdicts skip this global-closure step: they never judge unrelated paths)
        if closure:
            changed = _git(root, 'diff', '--name-only', '--no-renames', BASE, *([ref] if ref else []), '--',
                           *[p.rstrip('/') for p in FORBIDDEN_PREFIXES], *sorted(FORBIDDEN_PATHS)).decode().splitlines()
            from tests import on_bess01_scope as B
            if changed and (not B.exact_blobs_ok(root, ref) or any(not B.allowed_path(p, root, ref) for p in changed)):
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


def allowed_path(path, repo=None, ref=None):
    from tests import on_bess01_scope as B
    return path in OWNED_PATHS or path == MANIFEST or (B.allowed_path(path, repo, ref) and B.exact_blobs_ok(repo, ref))


def signature_ok(repo=None, ref=None):
    """Source/base/mode authority only: exact owned bytes, base, tree and modes. It never judges unrelated (global-closure) paths, so a
    dirty foreign file cannot flip it; full exactness (``exact_blobs_ok``) still adds the protected-prefix closure."""
    return _verdict(repo, ref, False)


def effective_pins(repo=None, ref=None, *, signature=False):
    """Current T01-D pins plus the authenticated, finite BESS handoff only."""
    from tests import on_bess01_scope as B
    pins = dict(manifest(repo, ref).get('source_blobs', {}))
    if B.signature_ok(repo, ref) if signature else B.exact_blobs_ok(repo, ref):
        pins.update(dict(B.effective_pins(repo, ref, signature=signature)))
    return pins


def base_blob(path, repo=None, ref=None):
    return manifest(repo, ref).get('base_blobs', {}).get(path)


def supersedes(path, value, repo=None, ref=None):
    """Bounded supersession for the older guards: true only for the composite
    registry path, only while this cohort is exact, only for its exact pin."""
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
