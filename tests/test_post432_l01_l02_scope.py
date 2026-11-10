"""Governance tests for the post-#434 L01/L02 exact-source cohort (tip of ... -> on_bess01 #433 -> onaccept01 #434 -> L01/L02).

Positives: the cohort is exact at HEAD with the two ORIGINAL L01/L02 commits as checked ancestors and the product sources equal to the blobs those
commits recorded; every accepted cohort stays registered in its accepted order with this one appended last; the predecessors, the tax/ux guards, U1 and
WF-04 follow this cohort only through the literal reviewed handoffs; the composite verdict is valid.

Negatives run in a throw-away clone, never in the working tree, grouped so each family is one test identity (no extra autodiscovered node per case):
one-byte drift of every owned path, a protected #433/#434 source, a handed-off predecessor or the registry; fake/forged predecessor, wrong base/tree,
wrong superseded base blob; a foreign/protected path; a symlink, an executable mode and an unpublished untracked file; a missing or extra cohort; a
historical manifest/map pin rewrite.
"""
import json
import subprocess
from pathlib import Path

import pytest

from tests import fin_v2_cohorts as C
from tests import on_bess01_scope as B
from tests import onaccept01_scope as O
from tests import post432_l01_l02_scope as X
from tests import bess02_scope as N

ROOT = Path(__file__).resolve().parents[1]
ACCEPTED_ORDER_TAIL = ('tests.tax_reference_registry_scope', 'tests.on_bess01_scope', 'tests.onaccept01_scope', 'tests.post432_l01_l02_scope')


def _git(root, *args):
    return subprocess.check_output(['git', '-c', 'user.name=t', '-c', 'user.email=t@t', *args], cwd=root, stderr=subprocess.DEVNULL).decode().strip()      # no ambient identity on hosted runners


@pytest.fixture(scope='module')
def clone(tmp_path_factory):
    dest = tmp_path_factory.mktemp('post434') / 'repo'
    subprocess.check_call(['git', 'clone', '-q', '--no-hardlinks', str(ROOT), str(dest)], stderr=subprocess.DEVNULL)
    _git(dest, 'checkout', '-q', '--detach', _git(ROOT, 'rev-parse', 'HEAD'))
    return dest


def _reset(root):
    _git(root, 'reset', '-q', '--hard', 'HEAD')
    _git(root, 'clean', '-fdq')


@pytest.fixture()
def tree(clone):
    _reset(clone)
    yield clone
    _reset(clone)


def _bump(root, path):
    f = root / path
    f.write_bytes(f.read_bytes() + b'\n# unreviewed\n')


def _json(root, path, mutate):
    f = root / path
    data = json.loads(f.read_text())
    mutate(data)
    f.write_text(json.dumps(data, indent=2, sort_keys=True) + '\n')


def _bad(root):
    """True when the cohort OR the composite registry refuses this tree."""
    if not X.exact_blobs_ok(root):
        return True
    with C.call_scope():
        return not C.valid(root)


def test_cohort_is_exact_literal_and_traceable_to_the_original_patch():
    assert X.exact_blobs_ok() and X.signature_ok()
    data = X.manifest()
    assert set(data['source_blobs']) == X.OWNED_PATHS - {X.MANIFEST} and set(data['base_blobs']) == X.SUPERSEDED
    assert X.SOURCE_PATHS == {'app/v2/debt_metrics_projection.py', 'app/v2/react_projects.py'}
    assert not any(p.startswith(X.FORBIDDEN_PREFIXES) or p in X.FORBIDDEN_PATHS or '*' in p or p.endswith('/') for p in X.OWNED_PATHS | {X.MANIFEST})
    assert set(_git(ROOT, 'diff', '--name-only', '--no-renames', X.BASE).splitlines()) <= X.closure_paths()      # this cohort plus the later R02 cohort when it is exact
    # the accepted baseline is main after #434; the two original reviewed commits are ancestors of HEAD and own the product blobs
    assert X.BASE == 'ebb9c07c30c733cbb39e9af58833f0b22baf7069' and _git(ROOT, 'rev-parse', X.BASE + '^{tree}') == X.BASE_TREE
    for commit in (X.BASE,) + X.ORIGINAL_PATCH:
        subprocess.check_call(['git', 'merge-base', '--is-ancestor', commit, 'HEAD'], cwd=ROOT)
    assert X.ORIGINAL_PATCH[1] == 'e998cbc5a23cf600306e7942570809878398f991'
    for path in X.SOURCE_PATHS:
        assert _git(ROOT, 'rev-parse', X.ORIGINAL_PATCH[1] + ':' + path) == data['source_blobs'][path]
    # base blobs are the immutable post-#434 objects
    for path, blob in data['base_blobs'].items():
        assert _git(ROOT, 'rev-parse', X.BASE + ':' + path) == blob


def test_registry_keeps_every_accepted_cohort_in_order_and_appends_only_this_one():
    base = subprocess.check_output(['git', 'show', X.BASE + ':tests/fin_v2_cohorts.py'], cwd=ROOT).decode()
    now = (ROOT / 'tests/fin_v2_cohorts.py').read_text()
    own = base.replace(X.REGISTRY_MARKER, X.REGISTRY_NEW)
    assert N.exact_blobs_ok() and now == N.expected_handoff(ROOT, X.REGISTRY).decode()
    import ast
    old = next(ast.literal_eval(n.value) for n in ast.parse(base).body if isinstance(n, ast.Assign) and n.targets[0].id == 'COHORT_MODULES')
    i = C.COHORT_MODULES.index('tests.post432_l01_l02_scope')
    assert C.COHORT_MODULES[:i + 1] == old + ('tests.post432_l01_l02_scope',) and C.COHORT_MODULES[i - 3:i + 1] == ACCEPTED_ORDER_TAIL
    assert len(set(C.COHORT_MODULES)) == len(C.COHORT_MODULES)


def test_the_accepted_runner_and_bess_preview_behaviour_is_unchanged():
    for path in sorted(O.SOURCE_PATHS | B.APP_PATHS):
        if path == 'app/services/bess_setup_preview.py':
            # One owner-approved nonpersisting preview source successor only.
            assert N.exact_blobs_ok() and path in N.SOURCE_PATHS and path in N.SUPERSEDED_SOURCE_PATHS
            assert _git(ROOT, 'rev-parse', 'HEAD:' + path) == N.manifest()['source_blobs'][path]
        else:
            assert _git(ROOT, 'rev-parse', 'HEAD:' + path) == _git(ROOT, 'rev-parse', X.BASE + ':' + path), path
    assert 'tests.on_bess01_scope' in C.COHORT_MODULES and 'tests.onaccept01_scope' in C.COHORT_MODULES
    assert C.COHORT_MODULES.index('tests.on_bess01_scope') < C.COHORT_MODULES.index('tests.onaccept01_scope') < C.COHORT_MODULES.index(X.SELF_MODULE)


def test_predecessors_and_older_guards_follow_this_cohort_only_through_the_reviewed_handoffs():
    from tests import tax_reference_registry_scope as T, ux_pr3b2_scope as U, wf04_scope as W4, u1_scope as U1
    pins = X.manifest()['source_blobs']
    with C.call_scope():
        assert B.exact_blobs_ok() and O.exact_blobs_ok() and T.exact_blobs_ok() and U.exact_blobs_ok() and W4.exact_blobs_ok() and C.valid()
        assert X.reviewed_edits_ok() and O.later_owned() == X.closure_paths()
        for path in sorted(X.SOURCE_PATHS):
            assert B.supersedes(path, pins[path]) and U1.supersedes(path, pins[path]) and not B.supersedes(path, '0' * 40)
        for path in (X.REGISTRY, 'tests/on_bess01_scope.py'):
            assert B.effective_pins()[path] == X.effective_pins()[path] and O.effective_pins()[path] == X.effective_pins()[path]      # follows this cohort, or the later R02 cohort when it is exact
        assert not B.supersedes('app/v2/router.py', pins['app/v2/react_projects.py']) and not X.supersedes('app/v2/router.py', pins['app/v2/react_projects.py'])
    # the only handed-off pins in the current maps are the registry's
    for path in X.CURRENT_MAPS:
        assert X.manifest()['source_blobs'][path] and json.loads((ROOT / path).read_text())['source_blobs'][X.REGISTRY] == X.effective_pins()[X.REGISTRY]


def test_one_byte_drift_of_every_owned_or_protected_source_fails_closed(tree):
    assert not _bad(tree)      # positive control: the unmodified clone is accepted, so every refusal below is caused by its mutation
    paths = sorted(X.OWNED_PATHS | {X.MANIFEST} | O.SOURCE_PATHS | B.APP_PATHS | {'tests/on_bess01_reviewed_successors.py'})
    survived = []
    for path in paths:
        _bump(tree, path)
        if not _bad(tree):
            survived.append(path)
        _reset(tree)
    assert not survived, survived


def test_handoff_registry_and_historical_pin_rewrites_fail_closed(tree):
    assert not _bad(tree)      # positive control: the unmodified clone is accepted, so every refusal below is caused by its mutation
    cases = []
    registry = tree / 'tests/fin_v2_cohorts.py'
    text = registry.read_text()
    cases.append(('missing_cohort', lambda: registry.write_text(text.replace(", 'tests.post432_l01_l02_scope'", ''))))
    cases.append(('missing_onaccept01', lambda: registry.write_text(text.replace(", 'tests.onaccept01_scope'", ''))))
    last = C.COHORT_MODULES[-1]
    cases.append(('extra_cohort', lambda: registry.write_text(text.replace(f"'{last}')", f"'{last}', 'tests.fake_scope')"))))
    cases.append(('reordered', lambda: registry.write_text(text.replace("'tests.on_bess01_scope', 'tests.onaccept01_scope'", "'tests.onaccept01_scope', 'tests.on_bess01_scope'"))))
    cases.append(('map_pin', lambda: _json(tree, 'docs/ci_v4/SOURCE_SUCCESSOR.json', lambda d: d['source_blobs'].update({X.REGISTRY: '0' * 40}))))
    cases.append(('map_foreign_key', lambda: _json(tree, 'docs/react_migration/u2_workbench/U2_EXACT_SOURCE.json', lambda d: d.update(base='0' * 40))))
    cases.append(('historical_bess_manifest', lambda: _json(tree, 'docs/bess_setup/SOURCE_SUCCESSOR.json', lambda d: d.update(base='0' * 40))))
    cases.append(('historical_onaccept_manifest', lambda: _json(tree, 'docs/onaccept01/SOURCE_SUCCESSOR.json', lambda d: d['base_blobs'].update({'tests/on_bess01_scope.py': '0' * 40}))))
    cases.append(('historical_tax_manifest', lambda: _json(tree, 'docs/tax_reference_registry/SOURCE_SUCCESSOR.json', lambda d: d.update(base='0' * 40))))
    cases.append(('wrong_base', lambda: _json(tree, X.MANIFEST, lambda d: d.update(base='0' * 40))))
    cases.append(('wrong_tree', lambda: _json(tree, X.MANIFEST, lambda d: d.update(base_tree='0' * 40))))
    cases.append(('wrong_superseded_base_blob', lambda: _json(tree, X.MANIFEST, lambda d: d['base_blobs'].update({'app/v2/react_projects.py': '0' * 40}))))
    cases.append(('dropped_superseded_pair', lambda: _json(tree, X.MANIFEST, lambda d: d['base_blobs'].pop('app/v2/react_projects.py'))))
    cases.append(('forged_source_pin', lambda: _json(tree, X.MANIFEST, lambda d: d['source_blobs'].update({'app/v2/react_projects.py': '0' * 40}))))
    cases.append(('foreign_pin', lambda: _json(tree, X.MANIFEST, lambda d: d['source_blobs'].update({'financial_engine/__init__.py': '0' * 40}))))
    cases.append(('missing_manifest', lambda: (tree / X.MANIFEST).unlink()))
    survived = []
    for name, mutate in cases:
        mutate()
        if not _bad(tree):
            survived.append(name)
        _reset(tree)
    assert not survived, survived


def test_foreign_paths_modes_links_untracked_and_wrong_ancestry_fail_closed(tree):
    assert not _bad(tree)      # positive control: the unmodified clone is accepted, so every refusal below is caused by its mutation
    survived = []
    for path in ('app/v2/router.py', 'app/v2/react_new_project.py', 'app/services/project_lifecycle_service.py', 'app/security/csrf.py',
                 'financial_engine/__init__.py', 'finco_core/__init__.py', 'tax_reference_registry/loader.py', 'main_web.py',
                 '.github/workflows/ci_v4_pr.yml', 'static/react/finco-react.js', 'app/v2/unreviewed_route.py', 'scripts/finco_live_acceptance/policy.py'):
        f = tree / path
        f.parent.mkdir(parents=True, exist_ok=True)
        f.write_bytes((f.read_bytes() if f.exists() else b'') + b'\n# unreviewed\n')
        if not _bad(tree):
            survived.append(path)
        _reset(tree)
    for path in sorted(X.SOURCE_PATHS | {'tests/on_bess01_scope.py', 'tests/onaccept01_scope.py', 'tests/fin_v2_cohorts.py'}):
        (tree / path).chmod(0o755)
        if not _bad(tree):
            survived.append(('mode', path))
        _reset(tree)
        f = tree / path
        data = f.read_bytes()
        f.unlink()
        f.symlink_to(tree / 'README.md')
        if not _bad(tree):
            survived.append(('symlink', path))
        _reset(tree)
        assert f.read_bytes() == data
    for name in ('app/v2/untracked_unpublished.py', 'tests/unpublished_helper.py', 'scripts/untracked.py'):
        (tree / name).parent.mkdir(parents=True, exist_ok=True)
        (tree / name).write_text('x = 1\n')
        if not _bad(tree):
            survived.append(('untracked', name))
        _reset(tree)
    orphan = _git(tree, 'commit-tree', _git(tree, 'rev-parse', 'HEAD^{tree}'), '-m', 'orphan')
    assert not X.exact_blobs_ok(tree, orphan) and X.exact_blobs_ok(tree, 'HEAD')
    _git(tree, 'update-index', '--chmod=+x', 'app/v2/react_projects.py')
    _git(tree, '-c', 'user.name=t', '-c', 'user.email=t@t', 'commit', '-qm', 'mode')
    assert not X.exact_blobs_ok(tree, 'HEAD')
    assert not survived, survived
