"""PR-U2 exact-source cohort: positives and tamper negatives on REAL git worktrees (2026-11-03 brief + mandatory addendum).

Every negative mutates a real checkout of the committed HEAD (shared object database, private working tree) and asks the real cohort functions.
"""
import json
import subprocess

import pytest

from tests import fin_v2_cohorts as C
from tests import u1_scope as U1
from tests import u2_scope as U2
from tests import wf06b_scope as W


def _git(root, *args):
    return subprocess.check_output(['git', *args], cwd=root, stderr=subprocess.STDOUT).decode()


@pytest.fixture(scope='module')
def _tree(tmp_path_factory):
    head = _git(U2.ROOT, 'rev-parse', 'HEAD').strip()
    path = tmp_path_factory.mktemp('u2-wt') / 'wt'
    _git(U2.ROOT, 'worktree', 'add', '--detach', str(path), head)
    yield path
    _git(U2.ROOT, 'worktree', 'remove', '--force', str(path))


@pytest.fixture()
def wt(_tree):
    yield _tree
    _git(_tree, 'reset', '--hard', '-q')
    _git(_tree, 'clean', '-fdxq')


def _flip(path):
    path.write_bytes(path.read_bytes() + b'\n')


def test_positive_cohort_is_exact_registered_and_closed():
    assert U2.exact_blobs_ok() and U2.valid() and C.valid() and U1.exact_blobs_ok() and W.exact_blobs_ok()
    assert U2.__name__ in C.COHORT_MODULES and U2 in C.cohorts() and U2.protected_blobs() == {}
    data = U2.manifest()
    assert set(data['source_blobs']) == U2.OWNED_PATHS and set(data['base_blobs']) == U2.SUPERSEDED
    assert not any(p.startswith(U2.FORBIDDEN_PREFIXES) or p in U2.FORBIDDEN_PATHS for p in U2.OWNED_PATHS)
    assert not (U2.OWNED_PATHS & U2.R1_PATHS)                                                    # addendum: no R1-owned file
    for stranger in ('app/v2/router.py', 'app/v2/save_all_commands.py', 'frontend/src/app/editing/saveAll.ts', 'tests/test_something_new.py',
                     'financial_engine/x.py', '.github/workflows/ci.yml'):
        assert not U2.allowed_path(stranger) and not U1.allowed_path(stranger) and not W.allowed_path(stranger)
    for owned in ('app/v2/react_opex_lines.py', 'frontend/src/app/capex/profileImport.ts', 'tests/u2_scope.py'):
        assert U2.matches(owned) and U2.allowed_path(owned) and U1.allowed_path(owned) and W.allowed_path(owned)
    path = 'static/react/finco-react.js'
    pin = data['source_blobs'][path]
    assert U2.supersedes(path, pin) and U1.supersedes(path, pin) and W.supersedes(path, pin) and not U2.supersedes(path, '0' * 40)
    assert not U2.supersedes('app/v2/react_opex_lines.py', data['source_blobs']['app/v2/react_opex_lines.py'])   # new at U2: nothing to supersede


def test_base_is_main_after_413_and_u1_is_superseded_only_at_its_own_pins():
    assert _git(U2.ROOT, 'rev-parse', U2.BASE + '^{tree}').strip() == U2.BASE_TREE
    subprocess.check_call(['git', 'merge-base', '--is-ancestor', U2.BASE, 'HEAD'], cwd=U2.ROOT)
    u1_pins = U1.manifest()['source_blobs']
    for path, blob in U2.manifest()['base_blobs'].items():
        assert _git(U2.ROOT, 'rev-parse', f'{U2.BASE}:{path}').strip() == blob
        assert u1_pins.get(path) == blob, path                                                    # U2 supersedes exactly what U1 signed
    changed = set(_git(U2.ROOT, 'diff', '--name-only', U2.BASE, '--').split())
    assert not any(p.endswith('SOURCE_SUCCESSOR.json') for p in changed)                         # no older manifest edited
    assert not any(p.startswith(U2.FORBIDDEN_PREFIXES) or p in U2.FORBIDDEN_PATHS or p in U2.R1_PATHS for p in changed)
    assert changed <= U2.OWNED_PATHS | {U2.MANIFEST}


def test_older_cohorts_still_exact_through_the_bounded_hooks():
    assert all(m.exact_blobs_ok() for m in C.cohorts())


@pytest.mark.parametrize('path', sorted(U2.OWNED_PATHS))
def test_one_altered_byte_in_any_owned_file_fails_closed(path, wt):
    assert U2.exact_blobs_ok(wt)
    _flip(wt / path)
    assert not U2.exact_blobs_ok(wt) and not U2.matches(path, (wt / path).read_bytes(), repo=wt) and not C.valid(wt)
    if path in U1.OWNED_PATHS:
        assert not U1.exact_blobs_ok(wt)                                                          # U1 stops following a drifted U2 state


@pytest.mark.parametrize('kind', ['extra-path', 'missing-pin', 'wrong-base', 'wrong-tree', 'wrong-blob', 'swapped-pins', 'drop-base-blob',
                                  'wrong-base-blob', 'swapped-schema', 'alias-pin', 'extra-base-blob'])
def test_manifest_forgery_is_refused(kind, wt):
    mpath = wt / U2.MANIFEST
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
        d['source_blobs']['app/v2/react_opex_lines.py'] = '0' * 40
    elif kind == 'swapped-pins':
        a, b = 'static/react/finco-react.js', 'static/react/finco-react.css'
        d['source_blobs'][a], d['source_blobs'][b] = d['source_blobs'][b], d['source_blobs'][a]
    elif kind == 'drop-base-blob':
        d['base_blobs'].pop('app/v2/react_workspace_router.py')
    elif kind == 'wrong-base-blob':
        d['base_blobs']['app/v2/react_workspace_router.py'] = '0' * 40
    elif kind == 'swapped-schema':
        d['schema_version'] = U1.SCHEMA
    elif kind == 'alias-pin':
        d['source_blobs']['static/react/finco-react.JS'] = d['source_blobs']['static/react/finco-react.js']
    elif kind == 'extra-base-blob':
        d['base_blobs']['app/v2/save_all_commands.py'] = _git(U2.ROOT, 'rev-parse', f'{U2.BASE}:app/v2/save_all_commands.py').strip()
    mpath.write_text(json.dumps(d, indent=2, sort_keys=True) + '\n')
    assert not U2.exact_blobs_ok(wt) and not C.valid(wt) and not U1.exact_blobs_ok(wt) and not W.exact_blobs_ok(wt)


def test_u1_follows_u2_only_where_u2_recorded_exactly_the_u1_pin(wt, monkeypatch):
    path = 'frontend/src/app/capex/CapexStudio.tsx'
    assert U1.exact_blobs_ok(wt)
    # forge the U1 pin: U2's recorded BASE blob no longer equals it -> U1 must NOT follow U2
    upath = wt / U1.MANIFEST
    u = json.loads(upath.read_text())
    u['source_blobs'][path] = '1' * 40
    upath.write_text(json.dumps(u, indent=2, sort_keys=True) + '\n')
    assert not U1.exact_blobs_ok(wt) and not C.valid(wt)
    _git(wt, 'checkout', '--', U1.MANIFEST)
    assert U1.exact_blobs_ok(wt)
    # a U2 cohort that no longer supersedes the path is not followed either
    monkeypatch.setattr(U2, 'SUPERSEDED', frozenset(U2.SUPERSEDED - {path}))
    assert not U1.supersedes(path, U2.manifest(wt)['source_blobs'][path], repo=wt)


def test_extra_tracked_extra_untracked_r1_and_executable_paths_fail_closed(wt):
    (wt / 'frontend/src/app/Sneaky.tsx').write_text('export {}\n')
    assert not U2.exact_blobs_ok(wt)
    _git(wt, 'add', 'frontend/src/app/Sneaky.tsx')
    assert not U2.exact_blobs_ok(wt) and not C.valid(wt)
    _git(wt, 'reset', '-q')
    (wt / 'frontend/src/app/Sneaky.tsx').unlink()
    assert U2.exact_blobs_ok(wt)
    owned = wt / 'app/v2/react_opex_lines.py'
    owned.chmod(0o755)
    assert not U2.exact_blobs_ok(wt)
    owned.chmod(0o644)
    assert U2.exact_blobs_ok(wt)


@pytest.mark.parametrize('path', ['financial_engine/__init__.py', 'finco_core/__init__.py', 'domain/__init__.py', 'main_web.py', 'tools/ci_v3_schema.py',
                                  '.github/workflows/ci_v3_required_job.yml', 'app/v2/router.py', 'tests/conftest.py',
                                  'app/v2/save_all_commands.py', 'frontend/src/app/editing/saveAll.ts', 'frontend/src/app/editing/pendingEdits.ts',
                                  'frontend/src/app/editing/wsv2Extensions.tsx', 'frontend/src/app/workflow/PPAEditorView.tsx',
                                  'frontend/src/app/WorkspaceView.tsx', 'frontend/src/app/editing/ChangesProvider.tsx',
                                  'app/capex_profiles/config.py', 'app/v2/capex_router.py', 'app/v2/opex_router.py'])
def test_protected_r1_and_unowned_code_modified_after_signing_fails_closed(path, wt):
    assert U2.exact_blobs_ok(wt)
    _flip(wt / path)
    _git(wt, '-c', 'user.name=T', '-c', 'user.email=ci-test-identity', 'commit', '-qam', 'tamper', '--no-verify')
    assert not U2.exact_blobs_ok(wt) and not C.valid(wt)
    assert not U2.allowed_path(path)
    _git(wt, 'reset', '--hard', '-q', 'HEAD~1')
