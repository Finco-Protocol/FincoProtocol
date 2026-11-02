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

Termination: every check is low level. It reads git objects and this cohort's manifest only; it never calls an older cohort or the cohort
registry, so there is no recursive self-approval. No result cache outlives one outer governance call (``scoped``).
"""
from pathlib import Path
from contextlib import contextmanager
from functools import lru_cache
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
ON09C_ADDED = frozenset((
    'tests/on09c_source_state.py',
    'tests/test_on09c_source_state.py',
    'docs/ci_v3/on09c/SOURCE_STATE.md',
))
ON09C_CHANGED = ON09C_ADDED | frozenset((
    'tests/fin_v2_integration_409_scope.py',
    'tests/fin_v2_wf06a_scope.py',
    'tests/wf03_lifecycle_scope.py',
    'tests/wf06b_scope.py',
    'tests/test_wf06b_scope.py',
))
OWNED_PATHS = PRESENTATION_PATHS | SOURCE_PATHS | TEST_AND_DOC_PATHS | GOVERNANCE_PATHS | ON09C_ADDED
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
    """Call memo only; every request still reconstructs fresh source identity."""
    _SCOPE.append({})
    try:
        yield
    finally:
        _SCOPE.pop()


def proof_identity():
    """Leaf dependencies only; observing them cannot approve source or recurse."""
    return (_read, _git, BASE, BASE_TREE, SCHEMA, OWNED_PATHS, SUPERSEDED,
            FORBIDDEN_PREFIXES, FORBIDDEN_PATHS, ON09C_ADDED, ON09C_CHANGED,
            manifest, _owned_ok, _on09c_paths, _exact_blobs_ok)


def exact_blobs_ok(repo=None, ref=None):
    root = Path(repo) if repo is not None else ROOT
    try:
        from tests import on09c_source_state as S
        state = S.state_key(root, ref, _git)
        if state is None:
            return False
        key = (str(root), ref, state, proof_identity())
    except (ImportError, OSError, ValueError, TypeError, KeyError, subprocess.CalledProcessError):
        return False
    if not _SCOPE:
        result = _exact_blobs_ok(repo, ref)
        try:
            return result and key == (str(root), ref, S.state_key(root, ref, _git), proof_identity())
        except (OSError, ValueError, TypeError, KeyError, subprocess.CalledProcessError):
            return False
    memo = _SCOPE[-1]
    if key not in memo:
        result = _exact_blobs_ok(repo, ref)
        try:
            if key != (str(root), ref, S.state_key(root, ref, _git), proof_identity()):
                return False
        except (OSError, ValueError, TypeError, KeyError, subprocess.CalledProcessError):
            return False
        memo[key] = result
    return memo[key]


@lru_cache(maxsize=16)
def _accepted_manifest_bytes(root, reader):
    from tests import on09c_source_state as S
    return reader(root, 'show', S.ACCEPTED + ':' + MANIFEST)


def _on09c_paths(root, ref, data):
    """One finite successor of the accepted #410 manifest; no older pin changes."""
    from tests import on09c_source_state as S
    if _git(root, 'rev-parse', S.ACCEPTED + '^{tree}').decode().strip() != S.ACCEPTED_TREE:
        return None
    _git(root, 'merge-base', '--is-ancestor', S.ACCEPTED, ref or 'HEAD')
    old = json.loads(_accepted_manifest_bytes(str(root), _git))
    if ref is not None and _git(root, 'rev-parse', ref + '^{commit}').decode().strip() == S.ACCEPTED:
        return OWNED_PATHS - ON09C_ADDED if data == old else None
    extras = {'on09c_history', 'on09c_path_ledger'}
    if set(data) != set(old) | extras or data.get('on09c_history') != {S.ACCEPTED: old}:
        return None
    if any(data.get(k) != v for k, v in old.items() if k != 'source_blobs'):
        return None
    pins = data.get('source_blobs', {})
    if set(pins) != set(old['source_blobs']) | ON09C_ADDED:
        return None
    if any(pins[p] != b and p not in ON09C_CHANGED for p, b in old['source_blobs'].items()):
        return None
    ledger = data.get('on09c_path_ledger', [])
    if (not isinstance(ledger, list) or len(ledger) != len(ON09C_CHANGED)
            or {row.get('path') for row in ledger} != ON09C_CHANGED):
        return None
    for row in ledger:
        path = row['path']
        if (set(row) != {'path', 'before_blob', 'after_blob', 'mode'}
                or row['before_blob'] != old['source_blobs'].get(path)
                or row['after_blob'] != pins[path] or row['mode'] != '100644'):
            return None
    return OWNED_PATHS


def _exact_blobs_ok(repo=None, ref=None):
    root = Path(repo) if repo is not None else ROOT
    try:
        from tests import on09c_source_state as S
        if not S.authenticated_state_ok(root, ref, _git):
            return False
        data = manifest(root, ref)
        paths_owned = _on09c_paths(root, ref, data)
        pins, base_blobs = data.get('source_blobs', {}), data.get('base_blobs', {})
        if not data or paths_owned is None or not _owned_ok() or set(pins) != paths_owned - {MANIFEST} or set(base_blobs) != SUPERSEDED:
            return False
        head = ref or 'HEAD'
        # 1. immutable provenance: the literal base commit and tree are ancestors of the evaluated head
        _git(root, 'merge-base', '--is-ancestor', BASE, head)
        if _git(root, 'rev-parse', BASE + '^{tree}').decode().strip() != BASE_TREE:
            return False
        # 2. the BASE blob recorded for every superseded path is what git holds at BASE (history is not rewritten here)
        paths = sorted(base_blobs)
        at_base = _git(root, 'rev-parse', *[BASE + ':' + p for p in paths]).decode().split()
        if at_base != [base_blobs[p] for p in paths]:
            return False
        # 3. one exact blob per owned path
        if ref is None:
            if any(_blob(_read(root, p, ref)) != sha for p, sha in pins.items()):
                return False
        else:
            listed = {}
            for line in _git(root, 'ls-tree', '-r', ref, '--', *sorted(pins)).decode().splitlines():
                meta, name = line.split('\t', 1)
                listed[name] = meta.split()[2]
            if listed != pins:
                return False
        # 4. nothing outside the literal set changed since BASE; protected prefixes can never move
        changed = _git(root, 'diff', '--name-only', '--no-renames', BASE, *([ref] if ref else []), '--').decode().splitlines()
        if any((p not in paths_owned and p != MANIFEST) or p.startswith(FORBIDDEN_PREFIXES) or p in FORBIDDEN_PATHS for p in changed):
            return False
        # 5. no owned file is executable or a link in the evaluated state
        if ref is None:
            for p in paths_owned | {MANIFEST}:
                f = root / p
                if f.is_symlink() or (f.exists() and f.stat().st_mode & 0o111):
                    return False
            untracked = _git(root, 'ls-files', '--others', '--exclude-standard').decode().splitlines()
            if any(p not in paths_owned and p != MANIFEST and not _ci_evidence_only(p) for p in untracked):
                return False
        else:
            modes = _git(root, 'ls-tree', '-r', ref, '--', *sorted(paths_owned | {MANIFEST})).decode().splitlines()
            if any(not line.startswith('100644 ') for line in modes):
                return False
        return True
    except (ImportError, OSError, ValueError, KeyError, TypeError, AttributeError, subprocess.CalledProcessError):
        return False


def allowed_path(path, repo=None, ref=None):
    return path in OWNED_PATHS or path == MANIFEST


def supersedes(path, value, repo=None, ref=None):
    """Bounded supersession for the older guards: true only for a path of ``SUPERSEDED``, only while this cohort is exact, only for its exact pin."""
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
