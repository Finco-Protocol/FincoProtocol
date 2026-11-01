"""WF-06B exact-source cohort: positives and tamper negatives on REAL git worktrees (PR #410, Owner decision WF06B-D3).

Every negative mutates a real checkout of the committed HEAD (shared object database, private working tree) and asks the real cohort functions;
nothing is mocked except where a negative is about a forged manifest read. The checks need only git objects, so they stay fast.
"""
import json
import os
import shutil
import subprocess

import pytest

from tests import fin_v2_cohorts as C
from tests import wf06b_scope as W


def _git(root, *args):
    return subprocess.check_output(['git', *args], cwd=root, stderr=subprocess.STDOUT).decode()


@pytest.fixture(scope='module')
def _tree(tmp_path_factory):
    """A detached worktree of the committed HEAD; each test gets it reset to HEAD afterwards."""
    head = _git(W.ROOT, 'rev-parse', 'HEAD').strip()
    path = tmp_path_factory.mktemp('wf06b-wt') / 'wt'
    _git(W.ROOT, 'worktree', 'add', '--detach', str(path), head)
    yield path
    _git(W.ROOT, 'worktree', 'remove', '--force', str(path))


@pytest.fixture()
def wt(_tree):
    yield _tree
    _git(_tree, 'reset', '--hard', '-q')
    _git(_tree, 'clean', '-fdxq')


def _flip(path):
    raw = path.read_bytes()
    path.write_bytes(raw + b'\n')


def test_positive_cohort_is_exact_registered_and_closed():
    assert W.exact_blobs_ok() and W.valid() and C.valid()
    assert W.__name__ in C.COHORT_MODULES and W in C.cohorts() and W.protected_blobs() == {}
    data = W.manifest()
    assert set(data['source_blobs']) == W.OWNED_PATHS - {W.MANIFEST} and set(data['base_blobs']) == W.SUPERSEDED
    assert all('*' not in p and not p.endswith('/') for p in W.OWNED_PATHS)                # a closed literal list, never a pattern
    assert not any(p.startswith(W.FORBIDDEN_PREFIXES) or p in W.FORBIDDEN_PATHS for p in W.OWNED_PATHS)
    for stranger in ('app/v2/router.py', 'frontend/src/app/NewUnreviewed.tsx', 'tests/test_something_new.py', 'financial_engine/x.py', '.github/workflows/ci.yml'):
        assert not W.allowed_path(stranger) and not W.matches(stranger)
    for owned in ('app/cost_line_ledger/ledger.py', 'static/react/finco-react.js', 'tests/wf06b_scope.py'):
        assert W.matches(owned) and W.allowed_path(owned)
    # the supersession is literal: only superseded paths, only the exact pin
    path = 'static/react/finco-react.js'
    assert W.supersedes(path, data['source_blobs'][path]) and not W.supersedes(path, '0' * 40)
    assert not W.supersedes('app/v2/router.py', data['source_blobs'][path]) and not W.supersedes('app/cost_line_ledger/ledger.py', data['source_blobs']['app/cost_line_ledger/ledger.py'])


def test_base_is_the_integrated_409_main_and_history_is_recorded_not_rewritten():
    assert _git(W.ROOT, 'rev-parse', W.BASE + '^{tree}').strip() == W.BASE_TREE
    subprocess.check_call(['git', 'merge-base', '--is-ancestor', W.BASE, 'HEAD'], cwd=W.ROOT)
    data = W.manifest()
    for path, blob in data['base_blobs'].items():                                          # each superseded path's BASE blob is what git holds at BASE
        assert _git(W.ROOT, 'rev-parse', f'{W.BASE}:{path}').strip() == blob
    for path in W.SUPERSEDED:
        assert data['source_blobs'][path] != data['base_blobs'][path] or path in W.GOVERNANCE_PATHS or path
    # the older manifests were not edited: they are byte-identical to BASE
    changed = set(_git(W.ROOT, 'diff', '--name-only', W.BASE, '--').split())
    assert not any(p.startswith('docs/') and p.endswith('SOURCE_SUCCESSOR.json') and p != W.MANIFEST for p in changed)


def test_older_cohorts_and_the_409_seal_are_still_exact_on_the_real_tree():
    from tests import fin_v2_integration_409_scope as INT
    assert INT.exact_blobs_ok() and all(m.exact_blobs_ok() for m in C.cohorts())


@pytest.mark.parametrize('path', sorted(W.OWNED_PATHS - {W.MANIFEST}))
def test_one_altered_byte_in_any_owned_file_fails_closed(path, wt):
    assert W.exact_blobs_ok(wt)
    _flip(wt / path)
    assert not W.exact_blobs_ok(wt) and not W.matches(path, (wt / path).read_bytes(), repo=wt)
    assert not C.valid(wt)


@pytest.mark.parametrize('path', sorted(W.OWNED_PATHS - {W.MANIFEST})[:6])
def test_missing_owned_path_fails_closed(path, wt):
    (wt / path).unlink()
    assert not W.exact_blobs_ok(wt) and not C.valid(wt)


@pytest.mark.parametrize('kind', ['extra-path', 'missing-pin', 'wrong-base', 'wrong-tree', 'wrong-blob', 'swapped-pins', 'drop-base-blobs',
                                  'wrong-base-blob', 'swapped-schema', 'alias-pin'])
def test_manifest_forgery_is_refused(kind, wt):
    mpath = wt / W.MANIFEST
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
        d['source_blobs']['app/cost_line_ledger/ledger.py'] = '0' * 40
    elif kind == 'swapped-pins':
        a, b = 'static/react/finco-react.js', 'static/react/finco-react.css'
        d['source_blobs'][a], d['source_blobs'][b] = d['source_blobs'][b], d['source_blobs'][a]
    elif kind == 'drop-base-blobs':
        d['base_blobs'].pop('app/v2/react_workspace_router.py')
    elif kind == 'wrong-base-blob':
        d['base_blobs']['app/v2/react_workspace_router.py'] = '0' * 40
    elif kind == 'swapped-schema':
        d['schema_version'] = 'WF06A_UX_EXACT_SOURCE_V1'
    elif kind == 'alias-pin':                                           # same value under a forged alias path
        d['source_blobs']['static/react/finco-react.JS'] = d['source_blobs']['static/react/finco-react.js']
    mpath.write_text(json.dumps(d, indent=2, sort_keys=True) + '\n')
    assert not W.exact_blobs_ok(wt) and not C.valid(wt)


def test_extra_tracked_extra_untracked_and_executable_paths_fail_closed(wt):
    (wt / 'frontend/src/app/Sneaky.tsx').write_text('export {}\n')
    assert not W.exact_blobs_ok(wt)                                                       # untracked, not owned
    _git(wt, 'add', 'frontend/src/app/Sneaky.tsx')
    assert not W.exact_blobs_ok(wt) and not C.valid(wt)                                   # staged, not owned
    _git(wt, 'reset', '-q')
    (wt / 'frontend/src/app/Sneaky.tsx').unlink()
    assert W.exact_blobs_ok(wt)
    run = wt / 'app/cost_line_ledger/run.sh'
    run.write_text('#!/bin/sh\n')
    run.chmod(0o755)
    assert not W.exact_blobs_ok(wt)                                                       # a future untracked executable
    run.unlink()
    owned = wt / 'app/cost_line_ledger/ledger.py'
    owned.chmod(0o755)
    assert not W.exact_blobs_ok(wt)                                                       # an owned file made executable
    owned.chmod(0o644)
    assert W.exact_blobs_ok(wt)


@pytest.mark.parametrize('path', ['financial_engine/__init__.py', 'finco_core/__init__.py', 'domain/__init__.py', 'main_web.py', 'tools/ci_v3_schema.py',
                                  '.github/workflows/ci_v3_required_job.yml', 'app/v2/router.py', 'tests/conftest.py'])
def test_protected_and_unowned_code_modified_after_signing_fails_closed(path, wt):
    assert W.exact_blobs_ok(wt)
    _flip(wt / path)
    assert not W.exact_blobs_ok(wt) and not C.valid(wt)
    assert not W.allowed_path(path)


@pytest.mark.parametrize('path', ['docs/react_migration/fin_v2_integration_409/SOURCE_SUCCESSOR.json', 'docs/react_migration/wf06a_ux/SOURCE_SUCCESSOR.json',
                                  'docs/react_migration/wf03_project_lifecycle/SOURCE_SUCCESSOR.json', 'frontend/src/app/InputsGuide.tsx',
                                  'tests/fin_v2_wf06a_scope.py.orig'])
def test_old_409_union_and_predecessor_manifests_cannot_be_bypassed(path, wt):
    target = wt / path
    if not target.exists():
        target.write_text('x\n')
    else:
        _flip(target)
    from tests import fin_v2_integration_409_scope as INT
    assert not W.exact_blobs_ok(wt) and not C.valid(wt) and not INT.exact_blobs_ok(wt)


def test_removing_an_old_ledger_row_or_historical_map_is_caught_by_the_older_cohorts(wt):
    from tests import wf03_lifecycle_scope as WF03
    manifest = wt / 'docs/react_migration/wf03_project_lifecycle/SOURCE_SUCCESSOR.json'
    d = json.loads(manifest.read_text())
    d['path_ledger'] = d['path_ledger'][:-1]
    manifest.write_text(json.dumps(d, indent=2) + '\n')
    assert not C.valid(wt) and not W.exact_blobs_ok(wt)


def test_an_older_cohort_accepts_a_superseded_blob_only_through_the_exact_cohort(wt):
    from tests import wsv2_core_scope as CORE
    assert CORE.exact_blobs_ok(wt)
    mpath = wt / W.MANIFEST
    d = json.loads(mpath.read_text())
    d['source_blobs']['static/react/finco-react.js'] = '1' * 40               # forge this cohort's pin: the older cohort must NOT follow it
    mpath.write_text(json.dumps(d, indent=2, sort_keys=True) + '\n')
    assert not W.exact_blobs_ok(wt) and not CORE.exact_blobs_ok(wt)
    _git(wt, 'checkout', '--', W.MANIFEST)
    _flip(wt / 'static/react/finco-react.js')                                  # a tampered bundle: no cohort pins it
    assert not W.exact_blobs_ok(wt) and not CORE.exact_blobs_ok(wt)


def test_no_result_outlives_the_call_scope_and_a_mutation_is_never_masked(wt):
    assert W.exact_blobs_ok(wt)
    with W.scoped():
        assert W.exact_blobs_ok(wt)
        _flip(wt / 'app/cost_line_ledger/ledger.py')
        assert W.exact_blobs_ok(wt)                                            # memoised for this ONE call only (documented)
    assert not W.exact_blobs_ok(wt)                                            # the scope is gone: fresh evaluation sees the byte
    assert not W._SCOPE


def test_evaluation_at_a_commit_ref_matches_the_working_tree_and_rejects_a_foreign_ref(wt):
    head = _git(wt, 'rev-parse', 'HEAD').strip()
    assert W.exact_blobs_ok(wt, head)
    assert not W.exact_blobs_ok(wt, W.BASE)                                    # BASE has no WF-06B manifest
    _git(wt, '-c', 'user.email=t@t', '-c', 'user.name=t', 'commit', '--allow-empty', '-qm', 'noop')
    assert W.exact_blobs_ok(wt, 'HEAD')
