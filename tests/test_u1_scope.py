"""PR-U1 exact-source cohort: positives and tamper negatives on REAL git worktrees (Owner decisions of 2026-11-02).

Every negative mutates a real checkout of the committed HEAD (shared object database, private working tree) and asks the real cohort functions;
nothing is mocked except where a negative is about a forged manifest read. The checks need only git objects, so they stay fast.
"""
import json
import subprocess

import pytest

from tests import fin_v2_cohorts as C
from tests import u1_scope as U
from tests import wf06b_scope as W


def _git(root, *args):
    return subprocess.check_output(['git', *args], cwd=root, stderr=subprocess.STDOUT).decode()


@pytest.fixture(scope='module')
def _tree(tmp_path_factory):
    head = _git(U.ROOT, 'rev-parse', 'HEAD').strip()
    path = tmp_path_factory.mktemp('u1-wt') / 'wt'
    _git(U.ROOT, 'worktree', 'add', '--detach', str(path), head)
    yield path
    _git(U.ROOT, 'worktree', 'remove', '--force', str(path))


@pytest.fixture()
def wt(_tree):
    yield _tree
    _git(_tree, 'reset', '--hard', '-q')
    _git(_tree, 'clean', '-fdxq')


def _flip(path):
    path.write_bytes(path.read_bytes() + b'\n')


def test_positive_cohort_is_exact_registered_and_closed():
    assert U.exact_blobs_ok() and U.valid() and C.valid() and W.exact_blobs_ok()
    assert U.__name__ in C.COHORT_MODULES and U in C.cohorts() and U.protected_blobs() == {}
    data = U.manifest()
    assert set(data['source_blobs']) == U.OWNED_PATHS - {U.MANIFEST} and set(data['base_blobs']) == U.SUPERSEDED
    assert all('*' not in p and not p.endswith('/') for p in U.OWNED_PATHS)
    assert not any(p.startswith(U.FORBIDDEN_PREFIXES) or p in U.FORBIDDEN_PATHS for p in U.OWNED_PATHS)
    for stranger in ('app/library/router.py', 'frontend/src/app/NewUnreviewed.tsx', 'tests/test_something_new.py', 'financial_engine/x.py', '.github/workflows/ci.yml'):
        assert not U.allowed_path(stranger) and not U.matches(stranger) and not W.allowed_path(stranger)
    for owned in ('app/cost_line_ledger/opex_bases.py', 'static/react/finco-react.js', 'tests/u1_scope.py'):
        assert U.matches(owned) and U.allowed_path(owned) and W.allowed_path(owned)
    path = 'static/react/finco-react.js'
    assert U.supersedes(path, data['source_blobs'][path]) and not U.supersedes(path, '0' * 40) and W.supersedes(path, data['source_blobs'][path])
    assert not U.supersedes('app/cost_line_ledger/opex_bases.py', data['source_blobs']['app/cost_line_ledger/opex_bases.py'])   # new at U1: nothing to supersede


def test_base_is_the_merged_410_main_and_history_is_recorded_not_rewritten():
    assert _git(U.ROOT, 'rev-parse', U.BASE + '^{tree}').strip() == U.BASE_TREE
    subprocess.check_call(['git', 'merge-base', '--is-ancestor', U.BASE, 'HEAD'], cwd=U.ROOT)
    data = U.manifest()
    for path, blob in data['base_blobs'].items():
        assert _git(U.ROOT, 'rev-parse', f'{U.BASE}:{path}').strip() == blob
    changed = set(_git(U.ROOT, 'diff', '--name-only', U.BASE, '--').split())
    moved_by_414 = set(_git(U.ROOT, 'diff', '--name-only', U.BASE, U.INTEGRATION, '--').split())     # the reviewed #414 amortisation moved the WF-06B seal
    later_manifests = {m.MANIFEST for m in U._later_modules()}                      # closed post-#413 cohorts register their OWN new manifest; none is an older one
    assert not any(p.startswith('docs/') and p.endswith('SOURCE_SUCCESSOR.json') and p != U.MANIFEST and p not in moved_by_414 and p not in later_manifests for p in changed)   # no older manifest was edited by U1
    since_414 = set(_git(U.ROOT, 'diff', '--name-only', U.INTEGRATION, '--').split())
    assert not any(p.startswith('docs/') and p.endswith('SOURCE_SUCCESSOR.json') and p != U.MANIFEST and p not in later_manifests for p in since_414)    # and none at all since main at #414
    # UI only - except the literal CI V4 paths of the exact, registered CI V4 cohort (Owner CI policy 2026-11-04); nothing else under .github/ or tools/.
    assert not any((p.startswith(U.FORBIDDEN_PREFIXES) or p in U.FORBIDDEN_PATHS) and not U._later_ci_owns(p, U.ROOT, None) for p in changed)
    for stranger in ('.github/workflows/public_safety_and_smoke.yml', 'tools/ci_v3_production.py', 'tools/ci_v4_unlisted.py', 'financial_engine/cfads.py'):
        assert not U._later_ci_owns(stranger, U.ROOT, None), stranger


def test_no_engine_schema_or_save_route_path_is_owned():
    for p in U.OWNED_PATHS:
        assert not p.startswith(('financial_engine/', 'finco_core/', 'domain/', '.github/', 'tools/', 'migrations/', 'schemas/')), p
    assert 'app/cost_line_ledger/ledger.py' not in U.OWNED_PATHS and 'app/cost_line_ledger/projection.py' not in U.OWNED_PATHS


def test_older_cohorts_still_exact_through_the_bounded_hooks():
    from tests import fin_v2_integration_409_scope as INT
    with C.call_scope():       # ONE outer governance call over this read-only enumeration: each cohort's verdict is computed once, dropped on exit
        assert INT.exact_blobs_ok() and all(m.exact_blobs_ok() for m in C.cohorts())


@pytest.mark.parametrize('path', sorted(U.OWNED_PATHS - {U.MANIFEST}))
def test_one_altered_byte_in_any_owned_file_fails_closed(path, wt):
    assert U.exact_blobs_ok(wt)
    _flip(wt / path)
    assert not U.exact_blobs_ok(wt) and not U.matches(path, (wt / path).read_bytes(), repo=wt)
    assert not C.valid(wt) and not W.exact_blobs_ok(wt)


@pytest.mark.parametrize('path', sorted(U.OWNED_PATHS - {U.MANIFEST})[:8])
def test_missing_owned_path_fails_closed(path, wt):
    (wt / path).unlink()
    assert not U.exact_blobs_ok(wt) and not C.valid(wt)


@pytest.mark.parametrize('kind', ['extra-path', 'missing-pin', 'wrong-base', 'wrong-tree', 'wrong-blob', 'swapped-pins', 'drop-base-blobs',
                                  'wrong-base-blob', 'swapped-schema', 'alias-pin', 'wrong-integration', 'wrong-integration-tree',
                                  'drop-integration-blobs', 'wrong-integration-blob', 'swapped-integration-blobs'])
def test_manifest_forgery_is_refused(kind, wt):
    mpath = wt / U.MANIFEST
    d = json.loads(mpath.read_text())
    if kind == 'extra-path':
        d['source_blobs']['financial_engine/unreviewed.py'] = '0' * 40
    elif kind == 'missing-pin':
        d['source_blobs'].pop('static/react/finco-react.js')
    elif kind == 'wrong-base':
        d['base'] = '0' * 40
    elif kind == 'wrong-tree':
        d['base_tree'] = '0' * 40
    elif kind == 'wrong-blob':
        d['source_blobs']['app/cost_line_ledger/opex_bases.py'] = '0' * 40
    elif kind == 'swapped-pins':
        a, b = 'static/react/finco-react.js', 'static/react/finco-react.css'
        d['source_blobs'][a], d['source_blobs'][b] = d['source_blobs'][b], d['source_blobs'][a]
    elif kind == 'drop-base-blobs':
        d['base_blobs'].pop('app/v2/react_workspace_router.py')
    elif kind == 'wrong-base-blob':
        d['base_blobs']['app/v2/react_workspace_router.py'] = '0' * 40
    elif kind == 'swapped-schema':
        d['schema_version'] = 'WF06B_A_PLUS_EXACT_SOURCE_V1'
    elif kind == 'alias-pin':
        d['source_blobs']['static/react/finco-react.JS'] = d['source_blobs']['static/react/finco-react.js']
    elif kind == 'wrong-integration':
        d['integration'] = '0' * 40
    elif kind == 'wrong-integration-tree':
        d['integration_tree'] = '0' * 40
    elif kind == 'drop-integration-blobs':
        d['integration_blobs'].pop('tests/wf06b_scope.py')
    elif kind == 'wrong-integration-blob':
        d['integration_blobs']['tests/wf06b_scope.py'] = '0' * 40
    elif kind == 'swapped-integration-blobs':
        a, b = 'tests/wf06b_scope.py', 'tests/test_wf06b_scope.py'
        d['integration_blobs'][a], d['integration_blobs'][b] = d['integration_blobs'][b], d['integration_blobs'][a]
    mpath.write_text(json.dumps(d, indent=2, sort_keys=True) + '\n')
    assert not U.exact_blobs_ok(wt) and not C.valid(wt) and not W.exact_blobs_ok(wt)


def test_extra_tracked_extra_untracked_and_executable_paths_fail_closed(wt):
    (wt / 'frontend/src/app/Sneaky.tsx').write_text('export {}\n')
    assert not U.exact_blobs_ok(wt)
    _git(wt, 'add', 'frontend/src/app/Sneaky.tsx')
    assert not U.exact_blobs_ok(wt) and not C.valid(wt)
    _git(wt, 'reset', '-q')
    (wt / 'frontend/src/app/Sneaky.tsx').unlink()
    assert U.exact_blobs_ok(wt)
    run = wt / 'app/cost_line_ledger/run.sh'
    run.write_text('#!/bin/sh\n')
    run.chmod(0o755)
    assert not U.exact_blobs_ok(wt)
    run.unlink()
    owned = wt / 'app/cost_line_ledger/opex_bases.py'
    owned.chmod(0o755)
    assert not U.exact_blobs_ok(wt)
    owned.chmod(0o644)
    assert U.exact_blobs_ok(wt)


@pytest.mark.parametrize('path', ['financial_engine/__init__.py', 'finco_core/__init__.py', 'domain/__init__.py', 'main_web.py', 'tools/ci_v3_schema.py',
                                  '.github/workflows/ci_v3_required_job.yml', 'app/library/router.py', 'tests/conftest.py',
                                  'app/cost_line_ledger/ledger.py', 'app/cost_line_ledger/projection.py'])
def test_protected_and_unowned_code_modified_after_signing_fails_closed(path, wt):
    assert U.exact_blobs_ok(wt)
    _flip(wt / path)
    assert not U.exact_blobs_ok(wt) and not C.valid(wt)
    assert not U.allowed_path(path)


@pytest.mark.parametrize('path', ['docs/react_migration/wf06b_a_plus/SOURCE_SUCCESSOR.json', 'docs/react_migration/fin_v2_integration_409/SOURCE_SUCCESSOR.json',
                                  'docs/react_migration/wf06a_ux/SOURCE_SUCCESSOR.json', 'frontend/src/app/CanonicalInputGrid.tsx',
                                  'tests/test_wf06b_scope.py'])
def test_the_410_manifest_and_unlisted_predecessor_files_cannot_be_bypassed(path, wt):
    _flip(wt / path)
    assert not U.exact_blobs_ok(wt) and not C.valid(wt)


def test_wf06b_follows_u1_only_for_the_exact_pin_and_only_the_recorded_historical_blob(wt):
    path = 'frontend/src/app/workflow/CostLineManager.tsx'          # superseded by U1 and by no later cohort (a later cohort's pin is the later cohort's own)
    assert W.exact_blobs_ok(wt)
    # forge the WF-06B pin: it no longer equals the historical blob U1 re-verified against git at its BASE -> WF-06B must NOT follow U1
    mpath = wt / W.MANIFEST
    d = json.loads(mpath.read_text())
    d['source_blobs'][path] = '1' * 40
    mpath.write_text(json.dumps(d, indent=2, sort_keys=True) + '\n')
    assert not W.exact_blobs_ok(wt) and not C.valid(wt)
    _git(wt, 'checkout', '--', W.MANIFEST)
    assert W.exact_blobs_ok(wt)
    # forge the U1 pin: U1 itself refuses, and WF-06B stops following it
    upath = wt / U.MANIFEST
    u = json.loads(upath.read_text())
    u['source_blobs'][path] = '2' * 40
    upath.write_text(json.dumps(u, indent=2, sort_keys=True) + '\n')
    assert not U.exact_blobs_ok(wt) and not W.exact_blobs_ok(wt) and not C.valid(wt)


def test_an_older_cohort_accepts_a_superseded_blob_only_through_the_exact_cohort(wt):
    from tests import wsv2_core_scope as CORE
    assert CORE.exact_blobs_ok(wt)
    _flip(wt / 'static/react/finco-react.js')
    assert not U.exact_blobs_ok(wt) and not W.exact_blobs_ok(wt) and not CORE.exact_blobs_ok(wt)


def test_no_result_outlives_the_call_scope_and_a_mutation_is_never_masked(wt):
    assert U.exact_blobs_ok(wt)
    with U.scoped():
        assert U.exact_blobs_ok(wt)
        _flip(wt / 'app/cost_line_ledger/opex_bases.py')
        assert U.exact_blobs_ok(wt)
    assert not U.exact_blobs_ok(wt)
    assert not U._SCOPE


def test_evaluation_at_a_commit_ref_matches_the_working_tree_and_rejects_a_foreign_ref(wt):
    head = _git(wt, 'rev-parse', 'HEAD').strip()
    assert U.exact_blobs_ok(wt, head)
    assert not U.exact_blobs_ok(wt, U.BASE)
    _git(wt, '-c', 'user.email=t@t', '-c', 'user.name=t', 'commit', '--allow-empty', '-qm', 'noop')
    assert U.exact_blobs_ok(wt, 'HEAD')


def test_no_path_outside_the_superseded_set_is_ever_admitted_by_supersession():
    later_superseded = set().union(*(set(m.SUPERSEDED) for m in U._later_modules()))
    for path in U.OWNED_PATHS - U.SUPERSEDED - {U.MANIFEST} - later_superseded:
        raw = (U.ROOT / path).read_bytes()
        assert not U.supersedes(path, U._blob(raw)) and not W.supersedes(path, U._blob(raw + b'\n')), path


def test_integration_reference_is_main_after_414_and_everything_unowned_equals_it():
    assert _git(U.ROOT, 'rev-parse', U.INTEGRATION + '^{tree}').strip() == U.INTEGRATION_TREE
    subprocess.check_call(['git', 'merge-base', '--is-ancestor', U.BASE, U.INTEGRATION], cwd=U.ROOT)
    subprocess.check_call(['git', 'merge-base', '--is-ancestor', U.INTEGRATION, 'HEAD'], cwd=U.ROOT)
    data = U.manifest()
    for path, blob in data['integration_blobs'].items():
        assert _git(U.ROOT, 'rev-parse', f'{U.INTEGRATION}:{path}').strip() == blob
    changed = set(_git(U.ROOT, 'diff', '--name-only', U.INTEGRATION, '--').split())
    # Post-#413 successors: only the finite, closed path set of a later cohort that is REGISTERED and EXACT (each pinned by its own manifest).
    later_owned = set().union(*(set(m.OWNED_PATHS) | {m.MANIFEST} for m in U._later_modules() if m.__name__ in C.COHORT_MODULES and m.exact_blobs_ok()))
    assert changed <= U.OWNED_PATHS | {U.MANIFEST} | later_owned          # nothing else moved away from main at #414
    assert not any((p.startswith(U.FORBIDDEN_PREFIXES) or p in U.FORBIDDEN_PATHS) and not U._later_ci_owns(p, U.ROOT, None) for p in changed)


def test_an_unowned_path_that_moved_away_from_main_after_414_fails_closed(wt):
    assert U.exact_blobs_ok(wt)
    _flip(wt / 'app/cost_line_ledger/ledger.py')                            # not owned by U1: it must equal main at the integration commit
    assert not U.exact_blobs_ok(wt) and not C.valid(wt)
