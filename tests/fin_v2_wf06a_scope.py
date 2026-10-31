"""Closed WF-06A exact-source cohort (PR #406): React presentation successor and the finite mechanics that admit it.

Authority: Financial Owner "Correction B" (2026-10-31): a narrowly scoped, additive, exact-blob successor. It is not a general waiver.

Lineage: BASE is main after the merged PR #405 (an ancestor of every head of this cohort, authenticated by ancestry AND tree). The cohort
owns exactly the literal path set below: the changed presentation sources and the rebuilt bundle, the new tests and documents, the reviewed
mechanical edits of the older scope modules and their tests, and the three predecessor manifests whose pins follow. Nothing else is admitted:
no ``app/``, ``financial_engine/``, ``finco_core/``, ``domain/``, ``.github/`` or ``main_web.py`` path, no wildcard, no pattern.

Predecessor repin relationship (``FOLLOWED_MOVES``): of the three followed manifests only the literal pins listed may differ from their BASE
state, every moved pin must equal this cohort's own pin of the same file, every other pin, every other key and every historical map must be
byte-identical to BASE, and the BASE pin values are recorded in this cohort's manifest (``predecessor_pins``) and re-verified against git.

Termination: every check here is low level. It reads git objects and this cohort's manifest only; it never calls an older cohort or the cohort
registry. The older guards call this module (bounded hooks), never the other way round, so there is no recursive self-approval.
"""
from pathlib import Path
from contextlib import contextmanager
import hashlib
import json
import subprocess

ROOT = Path(__file__).resolve().parents[1]
BASE = 'ebf1f15113ec95d69d29e8aa4e4635686dd1f39a'
BASE_TREE = '45e8efdd7e8b0fa8df6497c4e9510a7a27815f85'
MANIFEST = 'docs/react_migration/wf06a_ux/SOURCE_SUCCESSOR.json'
SCHEMA = 'WF06A_UX_EXACT_SOURCE_V1'

WF03_MANIFEST = 'docs/react_migration/wf03_project_lifecycle/SOURCE_SUCCESSOR.json'
WSV2_CORE_MANIFEST = 'docs/react_migration/wsv2_core/SOURCE_SUCCESSOR.json'
WF04_MANIFEST = 'docs/financial_validation/wf04_debt_metrics/SOURCE_SUCCESSOR.json'
FINV2_R1_MANIFEST = 'docs/financial_validation/fin_v2_r1/SOURCE_SUCCESSOR.json'

PRESENTATION_PATHS = frozenset((
    'frontend/src/app/InputsGuide.tsx',
    'frontend/src/app/RunFailureNotice.tsx',
    'frontend/src/app/editing/CostLinesGridView.tsx',
    'frontend/src/app/workflow/CostLineManager.tsx',
    'frontend/src/styles/ws2-editing.css',
    'static/react/finco-react.css',
    'static/react/finco-react.js',
))
TEST_AND_DOC_PATHS = frozenset((
    'frontend/src/app/__tests__/wf06a.test.mjs',
    'tests/model_react_wf06a_acceptance.py',
    'tests/test_fin_v2_wf06a_scope.py',
    'docs/react_migration/wf06a_ux/IMPLEMENTATION_EVIDENCE.md',
))
# Reviewed, mechanical edits of the older scope modules (hooks + additive negatives) and the registry; each is pinned below.
GOVERNANCE_PATHS = frozenset((
    'tests/fin_v2_cohorts.py',
    'tests/fin_v2_wf06a_scope.py',
    'tests/test_wf03_lifecycle_scope.py',
    'tests/test_wf04_scope.py',
    'tests/test_wsv2_core_scope.py',
    'tests/wf03_lifecycle_scope.py',
    'tests/wf04_scope.py',
    'tests/wsv2_core_scope.py',
))
FOLLOWED_MANIFESTS = frozenset((WF03_MANIFEST, WSV2_CORE_MANIFEST, WF04_MANIFEST, FINV2_R1_MANIFEST))
OWNED_PATHS = PRESENTATION_PATHS | TEST_AND_DOC_PATHS | GOVERNANCE_PATHS | FOLLOWED_MANIFESTS

# The ONLY pins of the followed manifests that may differ from their BASE state, and the cohort that pins the new value is this one.
FOLLOWED_MOVES = {
    WF03_MANIFEST: frozenset((
        'static/react/finco-react.css', 'static/react/finco-react.js',
        'tests/fin_v2_cohorts.py', 'tests/test_wf03_lifecycle_scope.py', 'tests/test_wsv2_core_scope.py',
        'tests/wf03_lifecycle_scope.py', 'tests/wsv2_core_scope.py', WSV2_CORE_MANIFEST, WF04_MANIFEST,
        'tests/test_wf04_scope.py', 'tests/wf04_scope.py', FINV2_R1_MANIFEST,
    )),
    WSV2_CORE_MANIFEST: frozenset((
        'frontend/src/app/RunFailureNotice.tsx', 'static/react/finco-react.css', 'static/react/finco-react.js',
        'tests/fin_v2_cohorts.py', 'tests/test_wsv2_core_scope.py', 'tests/wsv2_core_scope.py', FINV2_R1_MANIFEST,
    )),
    WF04_MANIFEST: frozenset((
        'static/react/finco-react.css', 'static/react/finco-react.js', WSV2_CORE_MANIFEST, FINV2_R1_MANIFEST,
        'tests/fin_v2_cohorts.py', 'tests/wf04_scope.py', 'tests/wsv2_core_scope.py', 'tests/test_wf04_scope.py', 'tests/test_wsv2_core_scope.py',
    )),
    FINV2_R1_MANIFEST: frozenset(('tests/fin_v2_cohorts.py',)),
}
# Pins that older cohorts keep for the same files and that this cohort re-pins (consumed by the bounded hook in tests/wf03_lifecycle_scope.py).
PREDECESSOR_REPINS = {WSV2_CORE_MANIFEST: frozenset(('frontend/src/app/RunFailureNotice.tsx',))}

_CI_EVIDENCE_EXTENSIONS = ('.json', '.xml', '.png', '.webp', '.jpg', '.jpeg', '.txt', '.csv', '.svg', '.html', '.zip')


def _git(root, *args):
    return subprocess.check_output(['git', *args], cwd=root, stderr=subprocess.DEVNULL)


def _read(root, path, ref):
    return (root / path).read_bytes() if ref is None else _git(root, 'show', ref + ':' + path)


def _blob(raw):
    return hashlib.sha1(b'blob ' + str(len(raw)).encode() + b'\0' + raw).hexdigest()


def _ci_evidence_only(path):
    return path.startswith('evidence/') and path.endswith(_CI_EVIDENCE_EXTENSIONS)


def manifest(repo=None, ref=None):
    root = Path(repo) if repo is not None else ROOT
    try:
        data = json.loads(_read(root, MANIFEST, ref))
        return data if (isinstance(data, dict) and isinstance(data.get('source_blobs'), dict) and data.get('schema_version') == SCHEMA
                        and data.get('base') == BASE and data.get('base_tree') == BASE_TREE) else {}
    except (OSError, ValueError, subprocess.CalledProcessError):
        return {}


def _followed_ok(root, ref, pins, data):
    """Each followed manifest equals its BASE self except literal moved pins, which equal this cohort's own pins; BASE values are recorded."""
    recorded = data.get('predecessor_pins')
    if not isinstance(recorded, dict) or set(recorded) != set(FOLLOWED_MANIFESTS):
        return False
    for path in sorted(FOLLOWED_MANIFESTS):
        old = json.loads(_read(root, path, BASE))
        now = json.loads(_read(root, path, ref))
        before, after = old['source_blobs'], now['source_blobs']
        if set(before) != set(after):
            return False
        if any(now.get(k) != v for k, v in old.items() if k != 'source_blobs') or set(now) != set(old):
            return False                                   # every other key and every historical map is byte-identical to BASE
        moved = {p for p in before if before[p] != after[p]}
        if not moved <= FOLLOWED_MOVES[path]:
            return False
        if recorded[path] != {p: before[p] for p in sorted(moved)}:
            return False                                   # the BASE value of each moved pin is recorded and matches git
        if any(p not in pins or after[p] != pins[p] for p in moved):
            return False                                   # a moved pin must be this cohort's own exact pin of the live file
    return True


_SCOPE = []


@contextmanager
def scoped():
    """Within ONE outer governance call the result of ``exact_blobs_ok(root, ref)`` is computed once. Dropped on exit; never keeps bytes."""
    _SCOPE.append({})
    try:
        yield
    finally:
        _SCOPE.pop()


def exact_blobs_ok(repo=None, ref=None):
    if not _SCOPE:
        return _exact_blobs_ok(repo, ref)
    key = (str(repo if repo is not None else ROOT), ref)
    memo = _SCOPE[-1]
    if key not in memo:
        memo[key] = _exact_blobs_ok(repo, ref)
    return memo[key]


def _exact_blobs_ok(repo=None, ref=None):
    root = Path(repo) if repo is not None else ROOT
    data = manifest(root, ref)
    pins = data.get('source_blobs', {})
    if set(pins) != OWNED_PATHS - {MANIFEST}:
        return False
    try:
        head = ref or 'HEAD'
        _git(root, 'merge-base', '--is-ancestor', BASE, head)
        if _git(root, 'rev-parse', BASE + '^{tree}').decode().strip() != BASE_TREE:
            return False
        if any(_blob(_read(root, p, ref)) != sha for p, sha in pins.items()):
            return False
        if not _followed_ok(root, ref, pins, data):
            return False
        changed = _git(root, 'diff', '--name-only', BASE, *([ref] if ref else []), '--').decode().splitlines()
        if any(p not in OWNED_PATHS and p != MANIFEST for p in changed):
            return False
        if ref is None:
            untracked = _git(root, 'ls-files', '--others', '--exclude-standard').decode().splitlines()
            if any(p not in OWNED_PATHS and p != MANIFEST and not _ci_evidence_only(p) for p in untracked):
                return False
        return True
    except (OSError, ValueError, KeyError, TypeError, AttributeError, subprocess.CalledProcessError):
        return False


def allowed_path(path, repo=None, ref=None):
    return path in OWNED_PATHS or path == MANIFEST


def valid(repo=None, ref=None):
    from tests.fin_v2_cohorts import valid as composite_valid
    return exact_blobs_ok(repo, ref) and composite_valid(repo, ref)


def matches(path, source=None, *, repo=None, ref=None):
    pins = manifest(repo, ref).get('source_blobs', {})
    if path not in pins or not valid(repo, ref):
        return False
    raw = source.encode() if isinstance(source, str) else source
    return source is None or _blob(raw) == pins[path]


def pins_exactly(path, value, repo=None, ref=None):
    """True only while the whole cohort is exact and it pins ``path`` at exactly ``value`` (used by the bounded hooks of the older guards)."""
    return exact_blobs_ok(repo, ref) and manifest(repo, ref).get('source_blobs', {}).get(path) == value


def predecessor_repin(manifest_path, source, after, repo=None, ref=None):
    """The literal predecessor re-pin delegation: only ``PREDECESSOR_REPINS`` pairs, only to this cohort's exact pin, only while it is exact."""
    return source in PREDECESSOR_REPINS.get(manifest_path, ()) and pins_exactly(source, after, repo, ref)


def protected_blobs(repo=None, ref=None):
    return {}  # Never admits a financial_engine, finco_core or domain source.
