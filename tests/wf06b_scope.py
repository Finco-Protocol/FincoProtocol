"""Closed WF-06B exact-source cohort (PR #410): A+ cost workbench / Compact Inputs successor over the integrated PR #409 main.

Authority: Financial Owner decision WF06B-D3 (2026-11-01): a bounded, literal, authenticated successor; not a general waiver and no financial
methodology change. ``BASE`` is the merge of PR #409 (`main` at the time); it is an ancestor of every head of this cohort, authenticated by
commit, tree AND the recorded BASE blob of every path this cohort supersedes (so the #409 seal and every older cohort stay exactly as they were
reviewed: nothing in their manifests was edited, and their pins describe BASE).

What it owns: a literal, finite path set (new files, the reviewed edits of existing presentation / route sources, the rebuilt bundle, the tests and
documents, and the reviewed bounded hooks in the older scope modules and the registry). Nothing else is admitted: no ``financial_engine/``,
``finco_core/``, ``domain/``, ``.github/``, ``tools/`` or ``main_web.py`` path, no pattern, no wildcard.

Supersession (``SUPERSEDED``): the subset of owned paths that already exist at BASE and that older cohorts pin at their BASE blob. An older cohort
accepts a different current blob for such a path only through ``supersedes(path, blob)``, which is true only while THIS cohort is exact and pins
exactly that blob. It never admits a value for a path outside ``SUPERSEDED``.

PR-U1 successor (2026-11-02): the closed PR-U1 cohort (tests/u1_scope.py, base = the merge of PR #410) extends this cohort through three bounded hooks:
a path of this cohort may carry U1's exact blob (``_pin_ok``: only while U1 is exact, only U1's exact pin, and only when this manifest still holds the
historical blob that U1 re-verified against git at its BASE), a path owned by U1 is allowed only while U1 is exact (``_u1_owns``), and
``supersedes`` / ``allowed_path`` forward to U1 for the older cohorts. U1 never calls this module, so there is no recursion.

Termination: every check is low level. It reads git objects and this cohort's manifest only; it never calls an older cohort or the cohort
registry, so there is no recursive self-approval.

Amortisation (post-#410 CI correction): every older cohort's per-path hook re-asks ``exact_blobs_ok`` once per moved pin, so one outer governance
call re-ran this whole validation >1000 times (measured: 8,617 git spawns for one WF-03 exact check on the merged #410 tree). The fix is the
call-scope memo (``scoped``), now shared by nested enters within ONE outer call, plus one-outer-call scope entry in the upstream cohorts
(``tests/wf03_lifecycle_scope.py``). There is deliberately NO process-lifetime verdict cache here: a derived state key cannot prove it covers every
input the exact check reads, and two ordinary-git configurations hide real working-tree changes from ``git diff`` (``core.filemode false`` with a
mode change on a POSIX host; ``update-index --assume-unchanged`` with a byte change — both reproduced against the pre-correction head, where a
cached True masked the tamper). One memoised verdict per outer call is safe because the memo's lifetime is exactly one single-threaded outer
governance call in which no file is written; after the outermost exit every evaluation reads the real bytes, modes and git state again.
"""
from pathlib import Path
from contextlib import contextmanager
import hashlib
import json
import subprocess

ROOT = Path(__file__).resolve().parents[1]
BASE = 'b7bfc4ed0fd224618e42f80dcacb3e1076e772ff'
BASE_TREE = '32cf0ea11d06147fa339729d7dc855fcf13564ce'
MANIFEST = 'docs/react_migration/wf06b_a_plus/SOURCE_SUCCESSOR.json'
SCHEMA = 'WF06B_A_PLUS_EXACT_SOURCE_V1'

PRESENTATION_PATHS = frozenset((
    'frontend/src/app/CanonicalInputGrid.tsx',
    'frontend/src/app/CostUnit.tsx',
    'frontend/src/app/InputsOverview.tsx',
    'frontend/src/app/WorkspaceView.tsx',
    'frontend/src/app/costAmounts.ts',
    'frontend/src/app/editing/ChangesDrawer.tsx',
    'frontend/src/app/editing/CostLinesGridView.tsx',
    'frontend/src/app/saveAllBridge.ts',
    'frontend/src/app/timing/ConstructionTiming.tsx',
    'frontend/src/app/types.ts',
    'frontend/src/app/uiDensity.ts',
    'frontend/src/app/workflow/CostLineManager.tsx',
    'frontend/src/app/workflow/WorkflowBar.tsx',
    'frontend/src/styles/compact-inputs.css',
    'frontend/src/styles/ws2-editing.css',
    'static/react/finco-react.css',
    'static/react/finco-react.js',
))
SOURCE_PATHS = frozenset((
    'app/cost_line_ledger/__init__.py',
    'app/cost_line_ledger/capacity.py',
    'app/cost_line_ledger/ledger.py',
    'app/cost_line_ledger/projection.py',
    'app/v2/react_workspace_router.py',
))
TEST_AND_DOC_PATHS = frozenset((
    'docs/ci_v3/incidents/ci_v3_governance_amortization/GPT6_REVIEW_PACKET.md',
    'docs/ci_v3/incidents/ci_v3_governance_amortization/ROOT_CAUSE.md',
    'docs/ci_v3/incidents/ci_v3_governance_amortization/SECURITY_EQUIVALENCE.md',
    'docs/ci_v3/incidents/ci_v3_governance_amortization/TIMING_LEDGER.md',
    'docs/react_migration/wf06b_a_plus/GOVERNANCE_SUCCESSOR_PLAN.md',
    'docs/react_migration/wf06b_a_plus/P00.md',
    'tests/model_react_wf06b_acceptance.py',
    'tests/test_wf06b_capacity.py',
    'tests/test_wf06b_cost_line_ledger.py',
    'tests/test_wf06b_costlines_route.py',
    'tests/test_wf06b_line_commands.py',
    'tests/test_wf06b_no_source_provenance_ui.py',
    'tests/test_wf06b_run_parity.py',
    'tests/test_wf06b_scope.py',
    'tests/wf06b_browser_role.py',
))
# Reviewed, bounded hooks in the older scope modules and the registry (each pinned below). This cohort's own module is owned too.
GOVERNANCE_PATHS = frozenset((
    'tests/fin_v2_cohorts.py',
    'tests/fin_v2_3_scope.py',
    'tests/fin_v2_d01_scope.py',
    'tests/fin_v2_integration_409_scope.py',
    'tests/fin_v2_r1_scope.py',
    'tests/fin_v2_rcux_scope.py',
    'tests/fin_v2_wf06a_scope.py',
    'tests/fin_v2_wsv2_scope.py',
    'tests/test_fin_v2_integration_409_scope.py',
    'tests/test_rcm_governance.py',
    'tests/test_rcux_governance.py',
    'tests/test_wsv2_core_scope.py',
    'tests/wf03_lifecycle_scope.py',
    'tests/wf04_scope.py',
    'tests/wf06b_scope.py',
    'tests/wsv2_core_scope.py',
))
OWNED_PATHS = PRESENTATION_PATHS | SOURCE_PATHS | TEST_AND_DOC_PATHS | GOVERNANCE_PATHS
# Owned paths that exist at BASE. Older cohorts pin these at their BASE blob; the BASE blob of each is recorded in the manifest and re-verified.
SUPERSEDED = frozenset((
    'app/v2/react_workspace_router.py',
    'frontend/src/app/CanonicalInputGrid.tsx',
    'frontend/src/app/WorkspaceView.tsx',
    'frontend/src/app/editing/ChangesDrawer.tsx',
    'frontend/src/app/editing/CostLinesGridView.tsx',
    'frontend/src/app/timing/ConstructionTiming.tsx',
    'frontend/src/app/types.ts',
    'frontend/src/app/workflow/CostLineManager.tsx',
    'frontend/src/app/workflow/WorkflowBar.tsx',
    'frontend/src/styles/ws2-editing.css',
    'static/react/finco-react.css',
    'static/react/finco-react.js',
)) | (GOVERNANCE_PATHS - frozenset(('tests/wf06b_scope.py',)))
# No owned path may ever sit under a protected prefix; this is checked on the literal set and on every changed path.
FORBIDDEN_PREFIXES = ('financial_engine/', 'finco_core/', 'domain/', '.github/', 'tools/')
FORBIDDEN_PATHS = frozenset(('main_web.py',))

_CI_EVIDENCE_EXTENSIONS = ('.json', '.xml', '.png', '.webp', '.jpg', '.jpeg', '.txt', '.csv', '.svg', '.html', '.zip')


def _git(root, *args):
    return subprocess.check_output(['git', *args], cwd=root, stderr=subprocess.DEVNULL)


def _read(root, path, ref):
    return (Path(root) / path).read_bytes() if ref is None else _git(root, 'show', ref + ':' + path)


def _blob(raw):
    return hashlib.sha1(b'blob ' + str(len(raw)).encode() + b'\0' + raw).hexdigest()


def _ci_evidence_only(path):
    return path.startswith('evidence/') and path.endswith(_CI_EVIDENCE_EXTENSIONS)


def _u1():
    try:
        from tests import u1_scope as U
    except ImportError:
        return None
    return U


def _u1_owns(path, repo, ref):
    """A path of the closed PR-U1 cohort, only while that cohort is itself exact (its check is low level and never calls this module)."""
    U = _u1()
    return U is not None and U.allowed_path(path, repo, ref) and U.exact_blobs_ok(repo, ref)


def _pin_ok(path, blob, pin, repo, ref):
    """``blob`` is this cohort's pin, or the exact PR-U1 pin of a path U1 supersedes while this manifest still holds the historical blob U1 recorded."""
    if blob == pin:
        return True
    U = _u1()
    return U is not None and U.supersedes(path, blob, repo, ref) and pin in U.historical_blobs(path, repo, ref)


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
    """Within ONE outer governance call the result of ``exact_blobs_ok(root, ref)`` is computed once. Dropped on exit; never keeps bytes.

    A nested ``scoped()`` enter (the composite registry and the older guards' outer calls enter the downstream scopes they delegate to) SHARES the
    outermost memo instead of pushing a fresh one, so one outer operation computes each verdict at most once however deep the delegation; the memo
    still never outlives the outermost exit and is never shared between separate outer calls. There is deliberately NO process-lifetime verdict
    cache at this layer: a persistent cache keyed by a derived state key cannot prove it covers every input the exact check reads (git can be
    configured to hide real working-tree changes from ``git diff`` — ``core.filemode false`` with a mode change, or ``update-index --assume-unchanged``
    with a byte change — both demonstrated on the pre-correction head), so the only safe memo is one whose lifetime is a single outer governance
    call in which no file is written."""
    if _SCOPE:
        yield
        return
    _SCOPE.append({})
    try:
        yield
    finally:
        _SCOPE.pop()


def exact_blobs_ok(repo=None, ref=None):
    if _SCOPE:       # one outer governance call (single-threaded, nothing is written meanwhile): the same call-scope memo the older cohorts use
        memo = _SCOPE[-1]
        skey = (str(repo if repo is not None else ROOT), ref)
        if skey not in memo:
            memo[skey] = _exact_blobs_ok(repo, ref)
        return memo[skey]
    U = _u1()
    if U is not None and not U._SCOPE:     # PR-U1: one U1 verdict per outer call here (dropped on exit), never a process-lifetime cache
        with U.scoped():
            return _exact_blobs_ok(repo, ref)
    return _exact_blobs_ok(repo, ref)




def _exact_blobs_ok(repo=None, ref=None):
    root = Path(repo) if repo is not None else ROOT
    data = manifest(root, ref)
    pins, base_blobs = data.get('source_blobs', {}), data.get('base_blobs', {})
    if not data or not _owned_ok() or set(pins) != OWNED_PATHS - {MANIFEST} or set(base_blobs) != SUPERSEDED:
        return False
    try:
        head = ref or 'HEAD'
        # 1. immutable provenance: the literal base commit and tree are ancestors of the evaluated head
        _git(root, 'merge-base', '--is-ancestor', BASE, head)
        if _git(root, 'rev-parse', BASE + '^{tree}').decode().strip() != BASE_TREE:
            return False
        paths = sorted(base_blobs)
        # 2. the BASE blob recorded for every superseded path is what git holds at BASE (history is not rewritten here)
        at_base = _git(root, 'rev-parse', *[BASE + ':' + p for p in paths]).decode().split()
        if at_base != [base_blobs[p] for p in paths]:
            return False
        # 3. one exact blob per owned path
        if ref is None:
            if any(not _pin_ok(p, _blob(_read(root, p, ref)), sha, root, ref) for p, sha in pins.items()):
                return False
        else:
            listed = {}
            for line in _git(root, 'ls-tree', '-r', ref, '--', *sorted(pins)).decode().splitlines():
                meta, name = line.split('\t', 1)
                listed[name] = meta.split()[2]
            if set(listed) != set(pins) or any(not _pin_ok(p, listed[p], pins[p], root, ref) for p in pins):
                return False
        # 4. nothing outside the literal set changed since BASE; protected prefixes can never move
        changed = _git(root, 'diff', '--name-only', '--no-renames', BASE, *([ref] if ref else []), '--').decode().splitlines()
        if any((p not in OWNED_PATHS and p != MANIFEST and not _u1_owns(p, root, ref)) or p.startswith(FORBIDDEN_PREFIXES) or p in FORBIDDEN_PATHS
               for p in changed):
            return False
        # 5. no owned file is executable or a link in the evaluated state
        if ref is None:
            for p in OWNED_PATHS | {MANIFEST}:
                f = root / p
                if f.is_symlink() or (f.exists() and f.stat().st_mode & 0o111):
                    return False
            untracked = _git(root, 'ls-files', '--others', '--exclude-standard').decode().splitlines()
            if any(p not in OWNED_PATHS and p != MANIFEST and not _ci_evidence_only(p) and not _u1_owns(p, root, ref) for p in untracked):
                return False
        else:
            modes = _git(root, 'ls-tree', '-r', ref, '--', *sorted(OWNED_PATHS | {MANIFEST})).decode().splitlines()
            if any(not line.startswith('100644 ') for line in modes):
                return False
        return True
    except (OSError, ValueError, KeyError, TypeError, AttributeError, subprocess.CalledProcessError):
        return False


def allowed_path(path, repo=None, ref=None):
    return path in OWNED_PATHS or path == MANIFEST or _u1_owns(path, repo, ref)


def supersedes(path, value, repo=None, ref=None):
    """Bounded supersession for the older guards: true only for a path of ``SUPERSEDED``, only while this cohort is exact, only for its exact pin."""
    if path in SUPERSEDED and exact_blobs_ok(repo, ref) and manifest(repo, ref).get('source_blobs', {}).get(path) == value:
        return True
    U = _u1()
    return U is not None and U.supersedes(path, value, repo, ref)


def valid(repo=None, ref=None):
    from tests.fin_v2_cohorts import valid as composite_valid
    return exact_blobs_ok(repo, ref) and composite_valid(repo, ref)


def matches(path, source=None, *, repo=None, ref=None):
    pins = manifest(repo, ref).get('source_blobs', {})
    raw = source.encode() if isinstance(source, str) else source
    if path in pins and valid(repo, ref) and (source is None or _blob(raw) == pins[path]):
        return True
    # PR #413 Correction H: the exact later state of a path the closed PR-U1 cohort supersedes (its pin, while U1 is exact and the composite is valid).
    U = _u1()
    return bool(U is not None and source is not None and path in U.SUPERSEDED and U.supersedes(path, _blob(raw), repo, ref) and valid(repo, ref))


def protected_blobs(repo=None, ref=None):
    return {}  # Never admits a financial_engine, finco_core or domain source.
