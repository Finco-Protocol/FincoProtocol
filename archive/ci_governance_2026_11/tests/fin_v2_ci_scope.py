"""Additive exact-blob FIN-V2 integration CI-diagnostics cohort (survivor attribution in the CI V3 calibration probe).

Recognition authorizes only the recorded diagnostic change: ``describe_group_members`` and a survivor description in the existing
"calibration left surviving descendants" failure. It does not relax that check, touch an engine path or activate anything. Pins are exact Git
blobs; any other changed path, byte, deletion or untracked protected source fails closed.
"""
from pathlib import Path
import hashlib
import json
import subprocess

ROOT = Path(__file__).resolve().parents[1]
BASE = 'f79e251903621c1a5c88501d51d6971960b612d3'          # main after merged PR #388 and #390
MANIFEST = 'docs/financial_validation/fin_v2_ci/SOURCE_SUCCESSOR.json'
SCHEMA = 'FIN_V2_CI_DIAGNOSTICS_EXACT_SOURCE_V1'
PROTECTED = ('app/', 'financial_engine/', 'finco_core/', 'domain/', '.github/', 'main_web.py')
DOC_PREFIX = 'docs/financial_validation/fin_v2_ci/'
DOC_EXACT = 'docs/ci_v3/phase4/CALIBRATION_CONTRACT_V2.md'

OWNED_PATHS = frozenset((
    'tests/fin_v2_ci_scope.py',
    'tests/test_ci_v3_calibration_contract_v2.py',
    'tests/test_fin_v2_ci_scope.py',
    'tools/ci_v3_calibrate.py',
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
    root = Path(repo) if repo is not None else ROOT
    pins = manifest(root, ref).get('source_blobs', {})
    if set(pins) != OWNED_PATHS:
        return False
    try:
        _git(root, 'merge-base', '--is-ancestor', BASE, ref or 'HEAD')
        if any(_blob(_read(root, p, ref)) != expected for p, expected in pins.items()):
            return False
        return not any(p.startswith(('financial_engine/', 'finco_core/', 'domain/')) for p in pins)      # this cohort never touches the engine
    except (OSError, ValueError, subprocess.CalledProcessError):
        return False


def allowed_path(path, repo=None, ref=None):
    return path in manifest(repo, ref).get('source_blobs', {}) or path.startswith(DOC_PREFIX) or path == DOC_EXACT


def _other_cohort_allows(path, root, ref):
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
    return {}          # no engine, core or domain path: nothing to add to the protected-namespace recognition
