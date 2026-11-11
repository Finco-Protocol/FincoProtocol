"""Closed T01-E exact-source cohort: the offline tax remediation diagnostic.

A bounded successor over main after the accepted F03 (#438) merge. The T01-D
cohort (``tests/tax_reference_registry_scope.py``) owns the reference registry
package and its original tests; this cohort owns ONLY the two new T01-E
diagnostic files plus its own governance proof.

Authority: the Financial Owner's T01-E brief of 2026-11-10 allows a dormant
remediation-report generator; it does NOT approve country activation, FX
defaults, financial engine hooks or any tax computation. This cohort is
provenance only.

Termination: every check is low level (git objects and this cohort's manifest
only); it never imports an older cohort or the composite registry.
"""
from pathlib import Path
from contextlib import contextmanager
import hashlib
import json
import subprocess

ROOT = Path(__file__).resolve().parents[1]
BASE = 'd17f46e5f3894dff59ff701c7b291bdf1e587891'
BASE_TREE = '80c62e2328ce78dc954649638a73abe86aa56fa5'
MANIFEST = 'docs/tax_reference_registry/t01e/SOURCE_SUCCESSOR.json'
SCHEMA = 'T01E_TAX_REMEDIATION_EXACT_SOURCE_V1'

SOURCE_PATHS = frozenset((
    'tax_reference_registry/remediation.py',
))
TEST_AND_DOC_PATHS = frozenset((
    'tests/tax_reference_registry/test_remediation.py',
    'tests/t01e_remediation_scope.py',
    'tests/test_t01e_remediation_scope.py',
))
OWNED_PATHS = SOURCE_PATHS | TEST_AND_DOC_PATHS
SUPERSEDED = frozenset()  # No shared files moved by T01-E; fin_v2_cohorts.py is owned by T01-D.
FORBIDDEN_PREFIXES = ('financial_engine/', 'finco_core/', 'domain/', '.github/', 'tools/', 'app/', 'frontend/', 'static/')
FORBIDDEN_PATHS = frozenset(('main_web.py',))


def _git(root, *args):
    return subprocess.check_output(['git', *args], cwd=root, stderr=subprocess.DEVNULL)


def _read(root, path, ref):
    return (Path(root) / path).read_bytes() if ref is None else _git('show', ref + ':' + path)


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
    _SCOPE.append({})
    try:
        yield
    finally:
        _SCOPE.pop()


def exact_blobs_ok(repo=None, ref=None):
    if _SCOPE:
        key = (str(repo if repo is not None else ROOT), ref)
        memo = _SCOPE[-1]
        if key not in memo:
            memo[key] = _exact_blobs_ok(repo, ref)
        return memo[key]
    return _exact_blobs_ok(repo, ref)


def _exact_blobs_ok(repo=None, ref=None):
    root = Path(repo) if repo is not None else ROOT
    data = manifest(root, ref)
    pins, base_blobs = data.get('source_blobs', {}), data.get('base_blobs', {})
    if not data or not _owned_ok() or set(pins) != OWNED_PATHS or base_blobs:
        return False
    try:
        head = ref or 'HEAD'
        _git(root, 'merge-base', '--is-ancestor', BASE, head)
        if _git(root, 'rev-parse', BASE + '^{tree}').decode().strip() != BASE_TREE:
            return False
        if ref is None:
            listed = {}
            for line in _git(root, 'ls-tree', '-r', 'HEAD', '--', *sorted(pins)).decode().splitlines():
                meta, name = line.split('\t', 1)
                listed[name] = meta.split()[2]
            if listed != pins:
                return False
        else:
            listed = {}
            for line in _git(root, 'ls-tree', '-r', ref, '--', *sorted(pins)).decode().splitlines():
                meta, name = line.split('\t', 1)
                listed[name] = meta.split()[2]
            if listed != pins:
                return False
        changed = _git(root, 'diff', '--name-only', '--no-renames', BASE, *([ref] if ref else []), '--',
                       *[p.rstrip('/') for p in FORBIDDEN_PREFIXES], *sorted(FORBIDDEN_PATHS)).decode().splitlines()
        if changed:
            return False
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
    return path in OWNED_PATHS or path == MANIFEST


def supersedes(path, value, repo=None, ref=None):
    return False  # T01-E moves no shared paths; supersession is not applicable.


def valid(repo=None, ref=None):
    from tests.fin_v2_cohorts import valid as composite_valid
    return exact_blobs_ok(repo, ref) and composite_valid(repo, ref)


def matches(path, source=None, *, repo=None, ref=None):
    pins = manifest(repo, ref).get('source_blobs', {})
    if path not in pins or not exact_blobs_ok(repo, ref):
        return False
    raw = source.encode() if isinstance(source, str) else source
    return source is None or _blob(raw) == pins[path]


def protected_blobs(repo=None, ref=None):
    return {}
