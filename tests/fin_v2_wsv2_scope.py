"""Exact-blob WS-2 (Editing & atomic Save All) cohort.

Recognition authorizes only the recorded Financial-Owner-approved successor (2026-10-28): the factoring of the existing validated writers into
bodies that run on a caller's cursor, ONE composing module (``app/v2/save_all_commands.py``), its single route, the ``save_all`` capability
descriptor, the idempotency ledger table, and the tests and documents that bind them.  It changes no financial formula, Senior/SHL rule, Run
Integrity rule, golden, native gate, CSRF module or CI workflow.  Every owned source is pinned by its exact Git blob (no pattern, no prefix, no
wildcard); the WS-2 documents are admitted by exact path.  The React presentation sources and the committed bundle are admitted by the RC-UX
cohort and the successor layers, not here.  Any other changed path, byte, deletion or untracked protected source fails closed.
"""
from pathlib import Path
import hashlib
import json
import subprocess

ROOT = Path(__file__).resolve().parents[1]
# Accepted parent: main at the merge of PR #396. The diff of this cohort is judged against this commit only.
BASE = 'b1a58681e41af9f1b4d52b176f0001725720b15c'
MANIFEST = 'docs/react_migration/wsv2_editing/SOURCE_SUCCESSOR.json'
SCHEMA = 'WSV2_SAVE_ALL_EXACT_SOURCE_V1'
PROTECTED = ('app/', 'financial_engine/', 'finco_core/', 'domain/', '.github/', 'main_web.py')

OWNED_PATHS = frozenset((
    'app/persistence/db.py',
    'app/persistence/workspace_repository.py',
    'app/v2/capex_commands.py',
    'app/v2/cost_batch_commands.py',
    'app/v2/grid_router.py',
    'app/v2/react_workspace_router.py',
    'app/v2/save_all_commands.py',
    'app/workbook/revenue_contracts_service.py',
    'tests/fin_v2_wsv2_scope.py',
    'tests/test_fin_v2_wsv2_scope.py',
    'tests/test_save_all_atomic_v1.py',
))

#: WS-2 documents (not executable): admitted by EXACT path only, no blob pin, so prose can be corrected without re-pinning code.
DOC_PATHS = frozenset('docs/react_migration/wsv2_editing/' + name for name in (
    'GOVERNANCE_PIN_REQUEST.md', 'P00_BASELINE_RECEIPT.md', 'PROTECTED_PATH_REQUEST_SAVE_ALL.md', 'SAVE_ALL_TRANSACTION_DESIGN.md',
    'SHARED_FILE_INTEGRATION.md', 'WSV2_GAP_COVERAGE_SONNET.md', 'WSV2_INTERFACE_CONTRACT.md'))


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
    return path in pins or path == MANIFEST or path in DOC_PATHS


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
