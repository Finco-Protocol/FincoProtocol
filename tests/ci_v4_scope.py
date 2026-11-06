"""Closed CI V4 exact-source cohort: the risk-driven PR acceptance (FAST/RISK), the FULL regression schedule and the exact-SHA release gate.

Also owns the two #419 Correction K test-determinism/active-path corrections (``tests/test_saas_revamp_entry.py``: the fault is injected on the
R18 active clone path, same 500/safe-body contract; ``tests/test_cost_batch_save_v1.py``: deterministic non-C.13 row selection). No older cohort pins
either file; no source file is changed by them.

Authority: Financial Owner CI policy decision of 2026-11-04 (CI V4) and #419 Correction K authorisation (2026-11-04): the full CI V3 regression is no longer required on every PR; it runs nightly, on
demand and is mandatory before a production release on the identical SHA. A bounded, literal, authenticated successor; no financial methodology,
security policy, expected financial value or authorization change.

``BASE`` is the merge of PR #413 (main), the same BASE as the sibling post-#413 cohorts, so the recorded BASE blob of every superseded governance path
equals the PR-U1 pin and U1 follows this cohort only through its bounded ``LATER_COHORTS`` hook.

What it owns: a literal, finite path set. ``CI_PATHS`` are the ONLY ``.github/`` and ``tools/`` paths it admits (new CI V4 files, no existing workflow
or CI V3 tool is edited); never a ``financial_engine/``, ``finco_core/``, ``domain/``, ``app/`` or ``main_web.py`` path, no pattern, no wildcard.
It does not police paths it does not own: the composite registry (``tests/fin_v2_cohorts.py``) requires every changed path to be allowed by a cohort.

Termination: every check is low level (git objects and this cohort's manifest only); it never imports an older cohort or the registry.
"""
from pathlib import Path
from contextlib import contextmanager
import hashlib
import json
import subprocess

ROOT = Path(__file__).resolve().parents[1]
BASE = '2c63750929477c618444e9d056030e054cc3a41c'
BASE_TREE = 'e7869fc8f4775b5ae62a5c75be60f2efef2cfd79'
MANIFEST = 'docs/ci_v4/SOURCE_SUCCESSOR.json'
SCHEMA = 'CI_V4_EXACT_SOURCE_V1'

CI_PATHS = frozenset((
    '.github/workflows/ci_v4_f01_job.yml',
    '.github/workflows/ci_v4_full.yml',
    '.github/workflows/ci_v4_pr.yml',
    '.github/workflows/ci_v4_release_gate.yml',
    '.github/workflows/ci_v4_shadow_split.yml',
    'tools/ci_v4_activate.py',
    'tools/ci_v4_aggregate.py',
    'tools/ci_v4_full_record.py',
    'tools/ci_v4_governance_gate.py',
    'tools/ci_v4_nodes.py',
    'tools/ci_v4_release_gate.py',
    'tools/ci_v4_schedule.py',
    'tools/ci_v4_select.py',
    'tools/ci_v4_shard.py',
))
TEST_AND_DOC_PATHS = frozenset((
    'docs/ci_v4/ci-v4-policy.json',
    'docs/ci_v4/full_skip_baseline.json',
    'docs/ci_v4/module_weights.json',
    'docs/ci_v4/node_split_policy.json',
    'docs/ci_v4/node_weights.json',
    'docs/ci_v4/CI_V4_NODE_SPLIT_HR.md',
    'docs/ci_v4/CI_V4_OWNER_DECISION_AND_RISK_MATRIX_HR.md',
    'docs/ci_v4/CI_V4_WORKER_BENCHMARK_AND_SCHEDULING_HR.md',
    'docs/ci_v4/FINAL_REPORT_HR.md',
    'tests/test_ci_v4_activate.py',
    'tests/test_ci_v4_aggregate.py',
    'tests/test_ci_v4_governance_gate.py',
    'tests/test_ci_v4_nodes.py',
    'tests/test_cost_batch_save_v1.py',
    'tests/test_saas_revamp_entry.py',
    'tests/test_ci_v4_release_gate.py',
    'tests/test_ci_v4_schedule.py',
    'tests/test_ci_v4_scope.py',
    'tests/test_ci_v4_select.py',
))
GOVERNANCE_PATHS = frozenset((
    'tests/ci_v4_scope.py',
    'tests/post413_r1_scope.py',
    'tests/post413_r17_scope.py',
    'tests/post413_r18_scope.py',
    'tests/u2_scope.py',
    'tests/wf06b_scope.py',
    'tests/fin_v2_integration_409_scope.py',
    'tests/fin_v2_cohorts.py',
    'tests/u1_scope.py',
))
OWNED_PATHS = CI_PATHS | TEST_AND_DOC_PATHS | GOVERNANCE_PATHS
SUPERSEDED = frozenset(('tests/fin_v2_cohorts.py', 'tests/u1_scope.py', 'tests/wf06b_scope.py', 'tests/fin_v2_integration_409_scope.py'))
# Never owned by this cohort. The financial core (ENGINE_PREFIXES) must also not have moved since BASE; ``app/`` may move only through sibling cohorts.
FORBIDDEN_PREFIXES = ('financial_engine/', 'finco_core/', 'domain/', 'app/')
ENGINE_PREFIXES = ('financial_engine/', 'finco_core/', 'domain/')
FORBIDDEN_PATHS = frozenset(('main_web.py',))
# Under these prefixes ONLY the literal CI_PATHS may differ from BASE.
CI_PREFIXES = ('.github/', 'tools/')


def _merge_event_successor():
    # One-way low-level proof: PR2b reads git + its own manifest, never this cohort.
    from tests import ux_pr2b_scope as B
    return B


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
    bad = lambda p: p.startswith(FORBIDDEN_PREFIXES) or p in FORBIDDEN_PATHS or '..' in p.split('/') or p.startswith('/') or '*' in p
    return (not any(bad(p) for p in OWNED_PATHS | {MANIFEST}) and SUPERSEDED <= OWNED_PATHS
            and all(p in CI_PATHS for p in OWNED_PATHS if p.startswith(CI_PREFIXES))
            and all(p.startswith(('.github/workflows/ci_v4_', 'tools/ci_v4_')) for p in CI_PATHS))


_SCOPE = []


@contextmanager
def scoped():
    """One verdict per outer governance call; dropped on exit."""
    if _SCOPE:
        yield
        return
    with _merge_event_successor().scoped():
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
    successor = _merge_event_successor()
    successor_ok = successor.exact_blobs_ok(root, ref)
    authorized_ci = successor.CI_PATHS if successor_ok else frozenset()
    data = manifest(root, ref)
    pins, base_blobs = data.get('source_blobs', {}), data.get('base_blobs', {})
    if not data or not _owned_ok() or set(pins) != OWNED_PATHS - {MANIFEST} or set(base_blobs) != SUPERSEDED:
        return False
    try:
        head = ref or 'HEAD'
        _git(root, 'merge-base', '--is-ancestor', BASE, head)
        if _object_fact(root, 'rev-parse', BASE + '^{tree}').decode().strip() != BASE_TREE:
            return False
        paths = sorted(base_blobs)
        if _object_fact(root, 'rev-parse', *[BASE + ':' + p for p in paths]).decode().split() != [base_blobs[p] for p in paths]:
            return False
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
        # engine/core/domain never moved; under .github/ and tools/ only the literal CI_PATHS differ from BASE
        changed = _git(root, 'diff', '--name-only', '--no-renames', BASE, *([ref] if ref else []), '--',
                       *[p.rstrip('/') for p in ENGINE_PREFIXES + CI_PREFIXES]).decode().splitlines()
        if any(p.startswith(ENGINE_PREFIXES) or (p.startswith(CI_PREFIXES) and p not in CI_PATHS and p not in authorized_ci) for p in changed):
            return False
        if ref is None:
            for p in OWNED_PATHS | {MANIFEST}:
                f = root / p
                if f.is_symlink() or (f.exists() and f.stat().st_mode & 0o111):
                    return False
            untracked = _git(root, 'ls-files', '--others', '--exclude-standard', '--', *[p.rstrip('/') for p in CI_PREFIXES]).decode().splitlines()
            if any(p not in CI_PATHS for p in untracked):
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


def ci_owns(path, repo=None, ref=None):
    """A literal CI V4 path or the exact owner-authorized merge-guard successor; never a wildcard CI admission."""
    return (path in CI_PATHS or _merge_event_successor().ci_owns(path, repo, ref)) and exact_blobs_ok(repo, ref)


def base_blob(path, repo=None, ref=None):
    return manifest(repo, ref).get('base_blobs', {}).get(path)


def supersedes(path, value, repo=None, ref=None):
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
    return {}


def write_manifest(repo=None):
    """Maintainer helper (python -m tests.ci_v4_scope): pin the CURRENT working-tree blobs. Never called by any check."""
    root = Path(repo) if repo is not None else ROOT
    data = {'schema_version': SCHEMA, 'base': BASE, 'base_tree': BASE_TREE,
            'authorization': 'Financial Owner CI policy decision 2026-11-04 (CI V4); CI schedule/selection/worker scaling only; no financial semantics.',
            'base_blobs': {p: _git(root, 'rev-parse', BASE + ':' + p).decode().strip() for p in sorted(SUPERSEDED)},
            'source_blobs': {p: _blob((root / p).read_bytes()) for p in sorted(OWNED_PATHS - {MANIFEST})}}
    (root / MANIFEST).write_text(json.dumps(data, indent=2, sort_keys=True) + '\n')
    return data


if __name__ == '__main__':
    write_manifest()
