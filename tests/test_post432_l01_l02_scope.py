"""Governance tests for the post-#432 L01/L02 exact-source cohort.

Positives: the cohort is exact at HEAD, the composite registry (all registered cohorts + every changed path) is valid with it, and the
older guards (WF-04, WF-03, RC-UX, T01-D) follow its pins only through their existing bounded successor hooks.

Negatives (every one runs in a throw-away clone, never in the working tree): a modified source byte, a source mode, a reverted source,
a foreign ``app/`` route/CSRF module, an unrelated ``financial_engine/``, ``finco_core/`` or tax-engine path, a wrong base / tree, a wrong
``SUPERSEDED`` base blob, a missing manifest, a wrong ancestry and a modified governance glue module all fail closed.
"""
import json
import subprocess
from pathlib import Path

import pytest

from tests import fin_v2_cohorts as C
from tests import post432_l01_l02_scope as X

ROOT = Path(__file__).resolve().parents[1]


def _git(root, *args):
    return subprocess.check_output(['git', *args], cwd=root, stderr=subprocess.DEVNULL).decode().strip()


@pytest.fixture(scope='module')
def clone(tmp_path_factory):
    dest = tmp_path_factory.mktemp('post432') / 'repo'
    subprocess.check_call(['git', 'clone', '-q', '--no-hardlinks', str(ROOT), str(dest)], stderr=subprocess.DEVNULL)
    _git(dest, 'checkout', '-q', '--detach', _git(ROOT, 'rev-parse', 'HEAD'))
    return dest


@pytest.fixture()
def tree(clone):
    _git(clone, 'checkout', '-q', '--', '.')
    _git(clone, 'clean', '-fdq')
    yield clone
    _git(clone, 'checkout', '-q', '--', '.')
    _git(clone, 'clean', '-fdq')


def _bump(root, path):
    f = root / path
    f.write_bytes(f.read_bytes() + b'\n# unreviewed\n')


def _manifest(root, mutate):
    f = root / X.MANIFEST
    data = json.loads(f.read_text())
    mutate(data)
    f.write_text(json.dumps(data, indent=2, sort_keys=True) + '\n')


def test_cohort_is_exact_and_owns_only_the_literal_set():
    assert X.exact_blobs_ok() and X.signature_ok()
    assert set(X.manifest()['source_blobs']) == X.OWNED_PATHS - {X.MANIFEST}
    assert set(X.manifest()['base_blobs']) == X.SUPERSEDED
    assert X.SOURCE_PATHS == {'app/v2/debt_metrics_projection.py', 'app/v2/react_projects.py'}
    assert not any(p.startswith(X.FORBIDDEN_PREFIXES) or p in X.FORBIDDEN_PATHS for p in X.OWNED_PATHS | {X.MANIFEST})
    assert not any('*' in p or p.endswith('/') for p in X.OWNED_PATHS)
    changed = set(_git(ROOT, 'diff', '--name-only', '--no-renames', X.BASE).splitlines())
    assert changed <= X.OWNED_PATHS | {X.MANIFEST}


def test_older_guards_follow_only_through_the_bounded_chain():
    from tests import tax_reference_registry_scope as T, ux_pr3b2_scope as U, wf04_scope as W4
    with C.call_scope():
        assert T.exact_blobs_ok() and U.exact_blobs_ok() and W4.exact_blobs_ok()
        assert C.valid()
        pins = X.manifest()['source_blobs']
        for path in X.SUPERSEDED:
            assert U.supersedes(path, pins[path]) or path in U.SUPERSEDED or T.supersedes(path, pins[path])
        assert not T.supersedes('app/v2/debt_metrics_projection.py', '0' * 40)
        assert not U.supersedes('app/v2/react_projects.py', '0' * 40)
    assert not X.supersedes('app/v2/router.py', X.manifest()['source_blobs']['app/v2/react_projects.py'])


def test_composite_valid_in_clone(tree):
    with C.call_scope():
        assert C.valid(tree)


@pytest.mark.parametrize('path', ['app/v2/debt_metrics_projection.py', 'app/v2/react_projects.py', 'tests/tax_reference_registry_scope.py',
                                  'tests/ux_pr3b2_scope.py', 'tests/test_ux_pr3b2_scope.py', 'tests/post432_l01_l02_scope.py'])
def test_modified_owned_byte_fails(tree, path):
    _bump(tree, path)
    assert not X.exact_blobs_ok(tree)
    with C.call_scope():
        assert not C.valid(tree)


@pytest.mark.parametrize('path', sorted(X.SOURCE_PATHS | {'tests/tax_reference_registry_scope.py'}))
def test_source_mode_fails(tree, path):
    (tree / path).chmod(0o755)
    assert not X.exact_blobs_ok(tree)


def test_reverted_source_fails(tree):
    base = subprocess.check_output(['git', 'show', X.BASE + ':app/v2/react_projects.py'], cwd=ROOT)
    (tree / 'app/v2/react_projects.py').write_bytes(base)
    assert not X.exact_blobs_ok(tree)


@pytest.mark.parametrize('path', ['app/v2/router.py', 'app/v2/react_new_project.py', 'app/services/project_lifecycle_service.py',
                                  'app/security/csrf.py', 'financial_engine/__init__.py', 'finco_core/__init__.py',
                                  'tax_reference_registry/loader.py', 'main_web.py', '.github/workflows/ci_v4.yml', 'static/react/finco-react.js',
                                  'app/v2/unreviewed_route.py'])
def test_foreign_or_protected_path_fails(tree, path):
    f = tree / path
    f.parent.mkdir(parents=True, exist_ok=True)
    f.write_bytes((f.read_bytes() if f.exists() else b'') + b'\n# unreviewed\n')
    assert not X.exact_blobs_ok(tree)
    with C.call_scope():
        assert not C.valid(tree)


def test_wrong_base_or_tree_fails(tree):
    _manifest(tree, lambda d: d.update(base='0' * 40))
    assert not X.exact_blobs_ok(tree) and X.manifest(tree) == {}
    _git(tree, 'checkout', '-q', '--', '.')
    _manifest(tree, lambda d: d.update(base_tree='0' * 40))
    assert not X.exact_blobs_ok(tree)


def test_wrong_superseded_target_fails(tree):
    _manifest(tree, lambda d: d['base_blobs'].update({'app/v2/react_projects.py': '0' * 40}))
    assert not X.exact_blobs_ok(tree)
    _git(tree, 'checkout', '-q', '--', '.')
    _manifest(tree, lambda d: d['base_blobs'].pop('app/v2/react_projects.py'))
    assert not X.exact_blobs_ok(tree)
    _git(tree, 'checkout', '-q', '--', '.')
    _manifest(tree, lambda d: d['source_blobs'].update({'app/v2/react_projects.py': '0' * 40}))
    assert not X.exact_blobs_ok(tree)


def test_missing_manifest_and_extra_pin_fail(tree):
    _manifest(tree, lambda d: d['source_blobs'].update({'financial_engine/__init__.py': '0' * 40}))
    assert not X.exact_blobs_ok(tree)
    _git(tree, 'checkout', '-q', '--', '.')
    (tree / X.MANIFEST).unlink()
    assert not X.exact_blobs_ok(tree)
    with C.call_scope():
        assert not C.valid(tree)


def test_wrong_ancestry_fails(tree):
    orphan = _git(tree, 'commit-tree', _git(tree, 'rev-parse', 'HEAD^{tree}'), '-m', 'orphan')
    assert not X.exact_blobs_ok(tree, orphan)
    assert X.exact_blobs_ok(tree, 'HEAD')


def test_mode_in_ref_fails(tree):
    _git(tree, 'update-index', '--chmod=+x', 'app/v2/react_projects.py')
    _git(tree, '-c', 'user.name=t', '-c', 'user.email=t@t', 'commit', '-qm', 'mode')
    assert not X.exact_blobs_ok(tree, 'HEAD')
