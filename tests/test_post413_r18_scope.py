"""R18 atomic reference clone exact-source cohort: positives and tamper negatives on REAL git worktrees (Financial Owner authorisation of 2026-11-03, PR #416).

Every negative mutates a real checkout of the committed HEAD (shared object database, private working tree) and asks the real cohort functions;
the checks need only git objects, so they stay fast.
"""
import json
import subprocess

import pytest

from tests import fin_v2_cohorts as C
from tests import post413_r18_scope as R
from tests import u1_scope as U

SUP = 'app/services/reference_seed_service.py'
NEW = 'tests/test_r18_atomic_reference_clone.py'


def _git(root, *args):
    return subprocess.check_output(['git', *args], cwd=root, stderr=subprocess.STDOUT).decode()


@pytest.fixture(scope='module')
def _tree(tmp_path_factory):
    head = _git(R.ROOT, 'rev-parse', 'HEAD').strip()
    path = tmp_path_factory.mktemp('r1-wt') / 'wt'
    _git(R.ROOT, 'worktree', 'add', '--detach', str(path), head)
    yield path
    _git(R.ROOT, 'worktree', 'remove', '--force', str(path))


@pytest.fixture()
def wt(_tree):
    yield _tree
    _git(_tree, 'reset', '--hard', '-q')
    _git(_tree, 'clean', '-fdxq')


def _flip(path):
    path.write_bytes(path.read_bytes() + b'\n')


def test_positive_cohort_is_exact_registered_and_closed():
    assert R.exact_blobs_ok() and R.valid() and C.valid() and U.exact_blobs_ok()
    assert R.__name__ in C.COHORT_MODULES and R in C.cohorts() and R.protected_blobs() == {}
    data = R.manifest()
    assert set(data['source_blobs']) == R.OWNED_PATHS - {R.MANIFEST} and set(data['base_blobs']) == R.SUPERSEDED
    assert all('*' not in p and not p.endswith('/') for p in R.OWNED_PATHS)
    assert not any(p.startswith(R.FORBIDDEN_PREFIXES) or p in R.FORBIDDEN_PATHS for p in R.OWNED_PATHS)
    for stranger in ('app/v2/router.py', 'frontend/src/app/NewUnreviewed.tsx', 'tests/test_something_new.py', 'financial_engine/x.py', '.github/workflows/ci.yml'):
        assert not R.allowed_path(stranger) and not R.matches(stranger) and not U.allowed_path(stranger)
    for owned in (SUP, NEW, 'tests/post413_r18_scope.py'):
        assert R.matches(owned) and R.allowed_path(owned) and U.allowed_path(owned)


def test_base_is_the_merged_413_main_and_history_is_recorded_not_rewritten():
    assert _git(R.ROOT, 'rev-parse', R.BASE + '^{tree}').strip() == R.BASE_TREE
    subprocess.check_call(['git', 'merge-base', '--is-ancestor', R.BASE, 'HEAD'], cwd=R.ROOT)
    for path, blob in R.manifest()['base_blobs'].items():
        assert _git(R.ROOT, 'rev-parse', R.BASE + ':' + path).strip() == blob


def test_supersession_is_bounded_to_the_exact_pin_of_a_superseded_path():
    pins = R.manifest()['source_blobs']
    for path in (SUP,):
        assert R.supersedes(path, pins[path]) and U.supersedes(path, pins[path]) and not R.supersedes(path, '0' * 40) and not U.supersedes(path, '0' * 40)
    assert not R.supersedes(NEW, pins[NEW])    # a new file supersedes nothing
    assert not R.supersedes('app/v2/router.py', pins[SUP]) and not U.supersedes('app/v2/router.py', pins[SUP])


@pytest.mark.parametrize('path', sorted(R.OWNED_PATHS))
def test_one_byte_in_each_owned_source_fails_closed(wt, path):
    _flip(wt / path)
    assert not R.exact_blobs_ok(wt)
    assert not R.matches(path, (wt / path).read_bytes(), repo=wt)


def test_modified_manifest_missing_or_extra_pin_and_wrong_base_fail_closed(wt):
    manifest = wt / R.MANIFEST
    original = json.loads(manifest.read_text())
    def write(data):
        manifest.write_text(json.dumps(data, indent=2) + '\n')
    pinned = sorted(original['source_blobs'])[0]
    changes = [
        lambda d: d['source_blobs'].__setitem__(pinned, '0' * 40),
        lambda d: d['source_blobs'].pop(pinned),
        lambda d: d['source_blobs'].__setitem__('app/v2/router.py', '1' * 40),
        lambda d: d['base_blobs'].__setitem__(SUP, '2' * 40),
        lambda d: d['base_blobs'].pop(SUP),
        lambda d: d.__setitem__('base', '3' * 40),
        lambda d: d.__setitem__('base_tree', '4' * 40),
        lambda d: d.__setitem__('schema_version', 'OTHER'),
    ]
    for change in changes:
        data = json.loads(json.dumps(original))
        change(data)
        write(data)
        assert not R.exact_blobs_ok(wt)
    manifest.write_text(json.dumps(original, indent=2) + '\n')
    assert R.exact_blobs_ok(wt)


def test_altered_predecessor_pin_or_hook_fails_closed(wt):
    _flip(wt / 'tests/u1_scope.py')
    assert not R.exact_blobs_ok(wt)
    _git(wt, 'checkout', '--', 'tests/u1_scope.py')
    u1_manifest = wt / U.MANIFEST
    data = json.loads(u1_manifest.read_text())
    data['source_blobs'][SUP if SUP in data['source_blobs'] else sorted(data['source_blobs'])[0]] = '0' * 40
    u1_manifest.write_text(json.dumps(data, indent=2) + '\n')
    assert not U.exact_blobs_ok(wt)


def test_changed_registry_entry_fails_closed(wt):
    registry = wt / 'tests/fin_v2_cohorts.py'
    registry.write_text(registry.read_text().replace("'tests.post413_r18_scope'", "'tests.post413_r18_scope_x'"))
    assert not R.exact_blobs_ok(wt)


def test_protected_path_executable_or_link_and_untracked_sources_fail_closed(wt):
    (wt / 'financial_engine').mkdir(exist_ok=True)
    (wt / 'financial_engine' / 'unreviewed.py').write_text('X = 1\n')
    _git(wt, 'add', 'financial_engine/unreviewed.py')
    assert not R.exact_blobs_ok(wt)
    _git(wt, 'reset', '--hard', '-q')
    (wt / SUP).chmod(0o755)
    assert not R.exact_blobs_ok(wt)
    _git(wt, 'checkout', '--', SUP)
    (wt / 'app').mkdir(exist_ok=True)
    (wt / 'app' / 'untracked_new_source.py').write_text('X = 1\n')
    assert not C.valid(wt)                                  # the composite refuses an untracked source outside every pin


def test_a_committed_mode_change_or_extra_owned_file_fails_closed(wt):
    _git(wt, 'update-index', '--chmod=+x', SUP)
    _git(wt, '-c', 'user.name=t', '-c', 'user.email=t@t', 'commit', '-q', '-m', 'mode')
    assert not R.exact_blobs_ok(wt, 'HEAD')


def test_the_cohort_is_acyclic_and_keeps_no_verdict_beyond_one_outer_call():
    source = (R.ROOT / 'tests/post413_r18_scope.py').read_text()
    head = source.split('def valid(', 1)[0].split('"""\n', 2)[2]      # code only, after the module docstring
    assert 'u1_scope' not in head and 'fin_v2_cohorts' not in head and 'importlib' not in head       # low level checks never call upward
    with R.scoped():
        assert R.exact_blobs_ok()
        assert len(R._SCOPE) == 1 and len(R._SCOPE[0]) == 1
    assert R._SCOPE == [] and U._SCOPE == []
