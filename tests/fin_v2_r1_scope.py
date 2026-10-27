"""Additive exact-blob FIN-V2-R1 (Reserve R1) source cohort.

Recognition authorizes only the recorded source successor: typed reserve authority, forward calendar coverage and read-only Reserve Coverage
evidence. It does not activate Reserve funding, a DSRF/hybrid mechanism, a waterfall change, native or quarterly products, merge a PR, or alter
any historical pin. Pins are exact Git blobs; any other changed path, byte, deletion or untracked protected source fails closed.
"""
from pathlib import Path
import hashlib
import json
import subprocess

ROOT = Path(__file__).resolve().parents[1]
# Accepted parent: main after merged PR #388 (RC-M) and #390. The diff of the cohort is judged against this commit only.
BASE = 'f79e251903621c1a5c88501d51d6971960b612d3'
MANIFEST = 'docs/financial_validation/fin_v2_r1/SOURCE_SUCCESSOR.json'
SCHEMA = 'FIN_V2_R1_EXACT_SOURCE_V1'
PROTECTED = ('app/', 'financial_engine/', 'finco_core/', 'domain/', '.github/', 'main_web.py')
DOC_PREFIX = 'docs/financial_validation/fin_v2_r1/'

OWNED_PATHS = frozenset((
    'app/run_integrity/reserve_coverage_evidence.py',
    'app/workbook/bankability_config.py',
    'financial_engine/dsra/forward_coverage.py',
    'financial_engine/dsra/reserve_authority.py',
    'financial_engine/dsra/target.py',
    'tests/finance_integrity_governance.py',
    'tests/fin_v2_cohorts.py',
    'tests/fin_v2_r1_scope.py',
    'tests/quarterly_candidate_recognition.py',
    'tests/test_finance_integrity_governance.py',
    'tests/test_model_react_overnight_b_governance.py',
    'tests/test_ci_acceptance.py',
    'tests/test_fin_v2_r1_reserve_coverage.py',
    'tests/test_fin_v2_r1_reserve_workspace.py',
    'tests/test_fin_v2_r1_scope.py',
    'tests/test_rcm_governance.py',
    'tests/test_tax_wf10_candidate.py',
    'tests/test_v11_stage3_successor.py',
    'tests/v11_stage3_successor.py',
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
        if any(_blob(_read(root, p, ref)) != expected for p, expected in pins.items()):
            return False
        # No native/source activation surface can be hidden in this cohort.
        return not any(p.startswith(('financial_engine/native_v10/', 'financial_engine/native_v11/')) for p in pins)
    except (OSError, ValueError, subprocess.CalledProcessError):
        return False


def allowed_path(path, repo=None, ref=None):
    pins = manifest(repo, ref).get('source_blobs', {})
    return path in pins or path.startswith(DOC_PREFIX)


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
    if not valid(repo, ref):
        return {}
    return {p: b for p, b in manifest(repo, ref)['source_blobs'].items() if p.startswith(('financial_engine/', 'finco_core/', 'domain/'))}
