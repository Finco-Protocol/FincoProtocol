"""Exact-blob PR #394 staging-correction cohort (F4 protected-source exception and the tests that bind it).

Recognition authorizes only the recorded successor: ONE user-safe-reason extension of ``app/services/run_intent_service.py`` (the D-029 Run
intent service) for the typed JSON Run outcome, the two test modules of this correction and this cohort itself.  It touches no router, CSRF,
persistence, schema, financial-engine, export or CI path, merges nothing and activates nothing.  Every owned path is pinned by its exact Git blob
(no pattern, no prefix, no wildcard); any other changed path, byte, deletion or untracked protected source fails closed.  The React presentation
sources and the committed bundle of the same correction are admitted by the RC-UX cohort and the RC_UX_SUCCESSORS layer, not here.
"""
from pathlib import Path
import hashlib
import json
import subprocess

ROOT = Path(__file__).resolve().parents[1]
# Accepted parent: main at the merge of PR #394 (RC-UX Completion V1). The diff of this cohort is judged against this commit only.
BASE = 'c129c54a6a0feae62d79bcb76e78b73560838af1'
MANIFEST = 'docs/react_migration/pr394_corrections/SOURCE_SUCCESSOR.json'
SCHEMA = 'PR394_CORRECTION_EXACT_SOURCE_V1'
PROTECTED = ('app/', 'financial_engine/', 'finco_core/', 'domain/', '.github/', 'main_web.py')

OWNED_PATHS = frozenset((
    'app/services/run_intent_service.py',
    'tests/fin_v2_pr394_corr_scope.py',
    'tests/test_fin_v2_pr394_corr_scope.py',
    'tests/test_pr394_f4_run_failure_reason_v1.py',
    'tests/test_pr394_staging_corrections_v1.py',
))


def _git(root, *args):
    return subprocess.check_output(['git', *args], cwd=root, stderr=subprocess.DEVNULL)


def _read(root, path, ref):
    return (root / path).read_bytes() if ref is None else _git(root, 'show', ref + ':' + path)


def _blob(data):
    return hashlib.sha1(b'blob ' + str(len(data)).encode() + b'\0' + data).hexdigest()


def manifest(repo=None, ref=None):
    root = Path(repo) if repo is not None else ROOT
    try:
        data = json.loads(_read(root, MANIFEST, ref))
        return data if data.get('schema_version') == SCHEMA and data.get('base') == BASE else {}
    except (OSError, ValueError, subprocess.CalledProcessError):
        return {}


def exact_blobs_ok(repo=None, ref=None):
    """History and every owned byte: the pin set equals the owned set and each pin is the exact Git blob."""
    root = Path(repo) if repo is not None else ROOT
    pins = manifest(root, ref).get('source_blobs', {})
    if set(pins) != OWNED_PATHS:
        return False
    try:
        _git(root, 'merge-base', '--is-ancestor', BASE, ref or 'HEAD')
        return all(_blob(_read(root, p, ref)) == expected for p, expected in pins.items())
    except (OSError, ValueError, subprocess.CalledProcessError):
        return False


def allowed_path(path, repo=None, ref=None):
    pins = manifest(repo, ref).get('source_blobs', {})
    return path in pins or path == MANIFEST


def _other_cohort_allows(path, root, ref):
    """A path owned by ANOTHER registered reviewed cohort (tests/fin_v2_cohorts.py) is that cohort's exact-blob responsibility."""
    try:
        from tests.fin_v2_cohorts import cohorts
    except ImportError:
        return False
    return any(m.__name__ != __name__ and m.allowed_path(path, root, ref) for m in cohorts())


def valid(repo=None, ref=None):
    root = Path(repo) if repo is not None else ROOT
    if not exact_blobs_ok(root, ref):
        return False
    try:
        changed = _git(root, 'diff', '--name-only', BASE, *([ref] if ref else []), '--').decode().splitlines()
        if any(not allowed_path(p, root, ref) and not _other_cohort_allows(p, root, ref) for p in changed):
            return False
        # Detect an untracked protected source as well as modifications/deletions.
        if ref is None:
            pins = manifest(root, ref).get('source_blobs', {})
            untracked = _git(root, 'ls-files', '--others', '--exclude-standard', '--', *PROTECTED).decode().splitlines()
            if any(p not in pins and not _other_cohort_allows(p, root, ref) for p in untracked):
                return False
        return True
    except (OSError, ValueError, subprocess.CalledProcessError):
        return False


def matches(path, source=None, *, repo=None, ref=None):
    pins = manifest(repo, ref).get('source_blobs', {})
    if path not in pins or not valid(repo, ref):
        return False
    if source is None:
        return True
    raw = source.encode() if isinstance(source, str) else source
    return _blob(raw) == pins[path]


def protected_blobs(repo=None, ref=None):
    """This cohort owns no financial_engine/finco_core/domain source; it can never widen the frozen financial namespace."""
    return {}
