"""Workstream-B exact-source cohort: positives and tamper negatives on REAL git worktrees (O1 + G7 + G-U2-1 + D7 Draft; no Owner decision is approved here).

Every negative mutates a real checkout of the committed HEAD (shared object database, private working tree) and asks the real cohort functions and the
real composite registry; each negative is followed by a restoration proof. The checks need only git objects, so they stay fast.
"""
import json
import subprocess

import pytest

from tests import fin_v2_cohorts as C
from tests import post413_o1_scope as O
from tests import u1_scope as U

BUNDLE = 'static/react/finco-react.js'
EDITOR = 'frontend/src/app/workflow/PPAEditorView.tsx'
ROUTE = 'app/v2/grid_router.py'
SERVICE = 'app/workbook/revenue_contracts_service.py'
SIBLINGS = {
    'docs/react_migration/post413_r17/SOURCE_SUCCESSOR.json', 'docs/react_migration/post413_r18/SOURCE_SUCCESSOR.json',
    'docs/react_migration/post413_r1/SOURCE_SUCCESSOR.json', 'docs/react_migration/u2_workbench/U2_EXACT_SOURCE.json', 'docs/ci_v4/SOURCE_SUCCESSOR.json',
}


def _git(root, *args):
    return subprocess.check_output(['git', *args], cwd=root, stderr=subprocess.STDOUT).decode()


@pytest.fixture(scope='module')
def _tree(tmp_path_factory):
    head = _git(O.ROOT, 'rev-parse', 'HEAD').strip()
    path = tmp_path_factory.mktemp('o1-wt') / 'wt'
    _git(O.ROOT, 'worktree', 'add', '--detach', str(path), head)
    yield path
    _git(O.ROOT, 'worktree', 'remove', '--force', str(path))


@pytest.fixture()
def wt(_tree):
    yield _tree
    _git(_tree, 'reset', '--hard', '-q')
    _git(_tree, 'clean', '-fdxq')


def _flip(path):
    path.write_bytes(path.read_bytes() + b'\n')


def test_positive_cohort_is_exact_registered_and_closed():
    assert O.exact_blobs_ok() and O.valid() and C.valid() and U.exact_blobs_ok()
    assert O.__name__ in C.COHORT_MODULES and O in C.cohorts() and O.__name__ in U.LATER_COHORTS and O.protected_blobs() == {}
    data = O.manifest()
    assert set(data['source_blobs']) == O.OWNED_PATHS - {O.MANIFEST} and set(data['base_blobs']) == O.SUPERSEDED
    assert all('*' not in p and not p.endswith('/') for p in O.OWNED_PATHS)
    assert not any(p.startswith(O.FORBIDDEN_PREFIXES) or p in O.FORBIDDEN_PATHS for p in O.OWNED_PATHS)
    assert O.SUPERSEDED <= O.OWNED_PATHS
    for stranger in ('app/library/router.py', 'app/v2/react_workspace_router.py', 'frontend/src/app/NewUnreviewed.tsx', 'tests/test_something_new.py',
                     'financial_engine/x.py', '.github/workflows/ci.yml', 'app/capex_profiles/binding.py'):
        assert not O.allowed_path(stranger) and not O.matches(stranger)
    for owned in (ROUTE, SERVICE, BUNDLE, EDITOR, 'app/capex_profiles/runtime.py', 'tests/post413_o1_scope.py'):
        assert O.matches(owned) and O.allowed_path(owned) and U.allowed_path(owned)


def test_the_ci_v4_governance_gate_passes_on_the_real_source():
    from tools import ci_v4_governance_gate as G
    record = G.run()
    assert record['verdict'] == 'PASS' and record['composite_valid'] and not record['mutation_violations'] and record['mutation_successor_valid']
    assert set(record['cohorts']) == set(record['registered']) == set(C.COHORT_MODULES) and all(record['cohorts'].values())


def test_base_is_the_merged_main_and_history_is_recorded_not_rewritten():
    assert _git(O.ROOT, 'rev-parse', O.BASE + '^{tree}').strip() == O.BASE_TREE
    subprocess.check_call(['git', 'merge-base', '--is-ancestor', O.BASE, 'HEAD'], cwd=O.ROOT)
    for path, blob in O.manifest()['base_blobs'].items():
        assert _git(O.ROOT, 'rev-parse', O.BASE + ':' + path).strip() == blob


def test_supersession_is_bounded_to_the_exact_pin_of_a_superseded_path():
    pins = O.manifest()['source_blobs']
    for path in (ROUTE, SERVICE, 'app/v2/router.py', 'frontend/src/app/api.ts'):
        assert O.supersedes(path, pins[path]) and U.supersedes(path, pins[path])
        assert not O.supersedes(path, '0' * 40) and not U.supersedes(path, '0' * 40)
    assert not O.supersedes('app/v2/capex_router.py', pins['app/v2/capex_router.py'])           # no older cohort pins it: owned, never superseded
    assert not O.supersedes('app/library/router.py', pins[ROUTE]) and not U.supersedes('app/library/router.py', pins[ROUTE])
    assert not O.supersedes(ROUTE, pins[SERVICE])                                                # one path's pin is never another path's value


def test_shared_sibling_pins_equal_this_cohorts_pin_and_nothing_else_moved():
    """The jointly pinned blobs are re-pinned to the SAME literal blob in every sibling manifest; no other pin of any sibling manifest changed since BASE."""
    pins = O.manifest()['source_blobs']
    moved_total = 0
    for manifest in sorted(SIBLINGS):
        before = json.loads(_git(O.ROOT, 'show', O.BASE + ':' + manifest))
        now = json.loads((O.ROOT / manifest).read_text())
        for key in ('base', 'base_tree', 'base_blobs', 'schema_version'):
            assert before.get(key) == now.get(key), (manifest, key)
        assert set(before['source_blobs']) == set(now['source_blobs'])
        moved = {p for p in now['source_blobs'] if now['source_blobs'][p] != before['source_blobs'][p]}
        assert moved <= O.OWNED_PATHS and all(now['source_blobs'][p] == pins[p] for p in moved), manifest
        moved_total += len(moved)
    assert moved_total > 0


@pytest.mark.parametrize('path', sorted(O.OWNED_PATHS))
def test_one_byte_in_each_owned_source_fails_closed(wt, path):
    _flip(wt / path)
    assert not O.exact_blobs_ok(wt)
    assert not O.matches(path, (wt / path).read_bytes(), repo=wt)
    _git(wt, 'checkout', '--', path)
    assert O.exact_blobs_ok(wt)                                                                  # restoring the bytes restores validity


def test_modified_manifest_missing_or_extra_pin_and_wrong_base_fail_closed(wt):
    manifest = wt / O.MANIFEST
    original = json.loads(manifest.read_text())

    def write(data):
        manifest.write_text(json.dumps(data, indent=2) + '\n')
    pinned = sorted(original['source_blobs'])[0]
    changes = [
        lambda d: d['source_blobs'].__setitem__(pinned, '0' * 40),
        lambda d: d['source_blobs'].pop(pinned),
        lambda d: d['source_blobs'].__setitem__('app/library/router.py', '1' * 40),
        lambda d: d['base_blobs'].__setitem__(ROUTE, '2' * 40),
        lambda d: d['base_blobs'].pop(ROUTE),
        lambda d: d.__setitem__('base', '3' * 40),
        lambda d: d.__setitem__('base_tree', '4' * 40),
        lambda d: d.__setitem__('schema_version', 'OTHER'),
    ]
    for change in changes:
        data = json.loads(json.dumps(original))
        change(data)
        write(data)
        assert not O.exact_blobs_ok(wt)
    manifest.write_text(json.dumps(original, indent=2) + '\n')
    assert O.exact_blobs_ok(wt)


def test_altered_registry_hook_or_sibling_pin_fails_closed(wt):
    for path in ('tests/u1_scope.py', 'tests/fin_v2_cohorts.py'):
        _flip(wt / path)
        assert not O.exact_blobs_ok(wt) and not C.valid(wt)
        _git(wt, 'checkout', '--', path)
    registry = wt / 'tests/fin_v2_cohorts.py'
    registry.write_text(registry.read_text().replace("'tests.post413_o1_scope'", "'tests.post413_o1_scope_x'"))
    assert not O.exact_blobs_ok(wt) and not C.valid(wt)
    _git(wt, 'checkout', '--', 'tests/fin_v2_cohorts.py')
    assert O.exact_blobs_ok(wt) and C.valid(wt)
    for manifest in sorted(SIBLINGS):
        data = json.loads((wt / manifest).read_text())
        key = 'tests/u1_scope.py'
        data['source_blobs'][key] = '0' * 40
        (wt / manifest).write_text(json.dumps(data, indent=2, sort_keys=True) + '\n')
        assert not C.valid(wt), manifest                                                         # a stale/forged sibling pin of a shared blob fails the composite
        _git(wt, 'checkout', '--', manifest)
    assert C.valid(wt)


def test_one_byte_in_the_workstream_b_route_or_service_fails_the_composite_and_restores(wt):
    for path in (ROUTE, SERVICE, 'app/v2/save_all_commands.py', 'app/capex_profiles/runtime.py'):
        _flip(wt / path)
        assert not C.valid(wt), path
        _git(wt, 'checkout', '--', path)
    assert C.valid(wt)


def test_unauthorised_extra_source_changed_unowned_file_and_foreign_prefix_fail_closed(wt):
    (wt / 'app').mkdir(exist_ok=True)
    (wt / 'app' / 'untracked_new_source.py').write_text('X = 1\n')
    assert not C.valid(wt)                                                                       # untracked source outside every pin
    _git(wt, 'clean', '-fdxq')
    _flip(wt / 'app/library/router.py')                                                          # an unowned, historically pinned file
    assert not C.valid(wt)
    _git(wt, 'checkout', '--', 'app/library/router.py')
    (wt / 'financial_engine').mkdir(exist_ok=True)
    (wt / 'financial_engine' / 'unreviewed.py').write_text('X = 1\n')
    _git(wt, 'add', 'financial_engine/unreviewed.py')
    assert not O.exact_blobs_ok(wt) and not C.valid(wt)
    _git(wt, 'reset', '--hard', '-q')
    _git(wt, 'clean', '-fdxq')
    assert C.valid(wt)


def test_altered_ci_v4_workflow_or_selector_and_a_stale_historical_pin_fail_closed(wt):
    for path in ('.github/workflows/ci_v4_pr.yml', 'tools/ci_v4_select.py'):
        _flip(wt / path)
        assert not C.valid(wt), path
        _git(wt, 'checkout', '--', path)
    historical = wt / 'docs/react_migration/wsv2_editing/SOURCE_SUCCESSOR.json'
    data = json.loads(historical.read_text())
    data['source_blobs'][ROUTE] = '0' * 40
    historical.write_text(json.dumps(data, indent=2, sort_keys=True) + '\n')
    assert not C.valid(wt)
    _git(wt, 'checkout', '--', str(historical.relative_to(wt)))
    assert C.valid(wt)


def test_a_deregistered_cohort_or_a_hook_without_it_fails_and_an_executable_or_committed_mode_change_fails(wt):
    registry = wt / 'tests/fin_v2_cohorts.py'
    original = registry.read_text()
    registry.write_text(original.replace(",\n                  'tests.post413_o1_scope')", ")"))            # deregistered: the real registry file no longer lists the cohort
    assert "post413_o1_scope" not in registry.read_text()
    assert not O.exact_blobs_ok(wt) and not C.valid(wt)
    registry.write_text(original)
    hook = wt / 'tests/u1_scope.py'
    hook_original = hook.read_text()
    hook.write_text(hook_original.replace(", 'tests.post413_o1_scope')", ")"))                                  # U1 hook no longer follows the cohort
    assert not O.exact_blobs_ok(wt) and not C.valid(wt)
    hook.write_text(hook_original)
    assert O.exact_blobs_ok(wt) and C.valid(wt)
    (wt / ROUTE).chmod(0o755)
    assert not O.exact_blobs_ok(wt)
    _git(wt, 'checkout', '--', ROUTE)
    _git(wt, 'update-index', '--chmod=+x', ROUTE)
    _git(wt, '-c', 'user.name=t', '-c', 'user.email=t@t', 'commit', '-q', '-m', 'mode')
    assert not O.exact_blobs_ok(wt, 'HEAD')


def test_the_cohort_is_acyclic_and_keeps_no_verdict_beyond_one_outer_call():
    source = (O.ROOT / 'tests/post413_o1_scope.py').read_text()
    head = source.split('def valid(', 1)[0].split('"""\n', 2)[2]      # code only, after the module docstring
    assert 'u1_scope' not in head.replace("'tests.u1_scope'", '') and 'fin_v2_cohorts' not in head and 'importlib' not in head
    with O.scoped():
        assert O.exact_blobs_ok()
        assert len(O._SCOPE) == 1 and len(O._SCOPE[0]) == 1
    assert O._SCOPE == [] and U._SCOPE == []
