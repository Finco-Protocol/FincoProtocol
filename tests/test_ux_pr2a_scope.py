"""UX-PR2a closed successor: positives and tamper controls on actual git worktrees (committed HEAD)."""
import json
import subprocess
import pytest
from tests import ux_pr2a_scope as U
from tests import ux_pr1_scope as P1
from tests import fin_v2_cohorts as C


def git(root, *args):
    return subprocess.check_output(['git', *args], cwd=root, text=True, stderr=subprocess.STDOUT)


@pytest.fixture(scope='module')
def tree(tmp_path_factory):
    path = tmp_path_factory.mktemp('ux-pr2a-scope') / 'tree'
    git(U.ROOT, 'worktree', 'add', '--detach', str(path), 'HEAD')
    yield path
    git(U.ROOT, 'worktree', 'remove', '--force', str(path))


@pytest.fixture
def wt(tree):
    yield tree
    git(tree, 'reset', '--hard', '-q')
    git(tree, 'clean', '-fdxq')


def test_exact_registered_acyclic_and_base_is_the_merged_pr1_main():
    assert U.exact_blobs_ok() and U.valid() and U.__name__ in C.COHORT_MODULES and U.protected_blobs() == {}
    assert P1.exact_blobs_ok() and all(m.exact_blobs_ok() for m in C.cohorts())
    d = U.manifest()
    assert set(d['source_blobs']) == U.OWNED_PATHS and set(d['base_blobs']) == U.SUPERSEDED
    subprocess.check_call(['git', 'merge-base', '--is-ancestor', U.BASE, 'HEAD'], cwd=U.ROOT)
    assert git(U.ROOT, 'rev-parse', U.BASE + '^{tree}').strip() == U.BASE_TREE
    assert git(U.ROOT, 'rev-parse', U.BASE + '^2').strip() == 'ef485b98431c3d36a71b68a861237b5ff9f01a3f'      # the merged UX-PR1 head
    for p in U.SUPERSEDED:
        assert d['base_blobs'][p] == git(U.ROOT, 'rev-parse', U.BASE + ':' + p).strip()
        assert U.supersedes(p, d['source_blobs'][p]) and not U.supersedes(p, '0' * 40)
    source = (U.ROOT / 'tests/ux_pr2a_scope.py').read_text()
    assert 'ux_pr1_scope' not in source.split('"""', 2)[2] and 'fin_v2_cohorts' not in source.split('def valid(', 1)[0]   # one-way: PR2a never calls PR1 or the registry
    for stranger in ('app/v2/react_capex.py', 'financial_engine/x.py', '.github/workflows/ci_v4_pr.yml', 'main_web.py', 'frontend/src/app/editing/saveAll.ts',
                     'frontend/src/app/capex/CapexStudio.tsx', 'frontend/src/app/CostWorkbench.tsx'):
        assert not U.allowed_path(stranger) and not U.matches(stranger)


def test_pr1_follows_pr2a_only_for_literal_pr2a_paths_at_their_exact_pin():
    pins = U.manifest()['source_blobs']
    for p in U.SUPERSEDED:
        assert P1._pr2a_pin_ok(U.ROOT, p, pins[p], None) and not P1._pr2a_pin_ok(U.ROOT, p, '0' * 40, None)
    assert not P1._pr2a_pin_ok(U.ROOT, 'frontend/src/app/CostWorkbench.tsx', pins['static/react/finco-react.js'], None)
    assert not P1._pr2a_owns(U.ROOT, 'frontend/src/app/CostWorkbench.tsx', None)


@pytest.mark.parametrize('path', sorted(U.OWNED_PATHS))
def test_one_byte_in_each_owned_source_fails_closed_and_restores(path, wt):
    assert U.exact_blobs_ok(wt)
    p = wt / path
    original = p.read_bytes()
    p.write_bytes(original + b'\n')
    assert not U.exact_blobs_ok(wt) and not C.valid(wt)
    p.write_bytes(original)
    assert U.exact_blobs_ok(wt)


@pytest.mark.parametrize('change', ['missing', 'extra', 'base', 'tree', 'history', 'schema', 'key', 'mode', 'symlink', 'foreign', 'deregister', 'forbidden'])
def test_forgery_modes_registration_and_foreign_paths_fail_closed(change, wt):
    assert U.exact_blobs_ok(wt)
    path = wt / U.MANIFEST
    d = json.loads(path.read_text())
    if change == 'missing': d['source_blobs'].pop(next(iter(d['source_blobs'])))
    elif change == 'extra': d['source_blobs']['financial_engine/new.py'] = '0' * 40
    elif change == 'base': d['base'] = '0' * 40
    elif change == 'tree': d['base_tree'] = '0' * 40
    elif change == 'history': d['base_blobs'][next(iter(d['base_blobs']))] = '0' * 40
    elif change == 'schema': d['schema_version'] = 'OTHER'
    elif change == 'key': d['unexpected'] = True
    elif change == 'mode': (wt / 'frontend/src/app/capex/savedTimeline.ts').chmod(0o755)
    elif change == 'symlink':
        target = wt / 'frontend/src/app/projection/opexLineTimeline.ts'
        target.unlink(); target.symlink_to(wt / 'tests/ux_pr2a_scope.py')
    elif change == 'foreign': (wt / 'frontend/src/app/Unsigned.tsx').write_text('export {}\n')
    elif change == 'deregister':
        p = wt / 'tests/fin_v2_cohorts.py'; p.write_text(p.read_text().replace(", 'tests.ux_pr2a_scope'", ''))
    elif change == 'forbidden': (wt / 'app').mkdir(exist_ok=True); (wt / 'app' / 'unsigned_new.py').write_text('X = 1\n')
    path.write_text(json.dumps(d, indent=2) + '\n')
    assert not U.exact_blobs_ok(wt) and not C.valid(wt)


@pytest.mark.parametrize('path', sorted(U.INTEGRATION_MANIFESTS))
def test_sibling_pin_and_historical_map_tamper_fail_closed(path, wt):
    p = wt / path; old = p.read_bytes(); d = json.loads(old)
    owned = next(k for k in d['source_blobs'] if k in U.OWNED_PATHS)
    d['source_blobs'][owned] = '0' * 40; p.write_text(json.dumps(d) + '\n')
    assert not U.exact_blobs_ok(wt) and not C.valid(wt)
    p.write_bytes(old); d = json.loads(old); d['base'] = '0' * 40; p.write_text(json.dumps(d) + '\n')
    assert not U.exact_blobs_ok(wt)


def test_altered_pr1_predecessor_module_or_manifest_fails_closed(wt):
    for rel in ('tests/ux_pr1_scope.py', 'docs/react_migration/ux_pr1/UX_PR1_EXACT_SOURCE.json'):
        p = wt / rel; original = p.read_bytes()
        p.write_bytes(original + b'\n')
        assert not C.valid(wt), rel
        p.write_bytes(original)
    assert C.valid(wt)


def test_ci_artifacts_are_not_source_exemptions(wt):
    evidence = wt / 'evidence' / 'ux-pr2a-probe'; evidence.mkdir(parents=True, exist_ok=True)
    artifact = evidence / 'source.json'; artifact.write_text('{"synthetic": true}\n')
    assert U.exact_blobs_ok(wt) and C.valid(wt)
    for suffix in ('.py', '.tsx', '.mjs'):
        source = evidence / ('unsigned' + suffix); source.write_text('unsigned\n')
        assert not U.exact_blobs_ok(wt) and not C.valid(wt)
        source.unlink()
