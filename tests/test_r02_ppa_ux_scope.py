"""Governance tests for the R02 compact-PPA-UX exact-source cohort (tip of ... -> on_bess01 #433 -> onaccept01 #434 -> L01/L02 #435 -> R02).

Positives: the cohort is exact with accepted main 64a0d5b7 as checked ancestor; ONLY the listed UI sources, the new component, its JS test and the literal reviewed handoffs moved; the WF-React-2 component
file, every backend/engine/writer path and the frozen BESS module are byte-identical to BASE; the built bundle carries the compact UI and no cap/tier payload vocabulary.
Negatives run in a throw-away clone (never in the working tree), grouped per family so each is ONE test identity: one-byte drift of every owned or protected source, registry/handoff/map/base/tree
rewrites, foreign paths, executable modes, symlinks, unpublished untracked files and wrong ancestry all fail closed (each family starts with a positive control).
"""
import json
import re
import subprocess
from pathlib import Path

import pytest

from tests import fin_v2_cohorts as C
from tests import on_bess01_scope as B
from tests import onaccept01_scope as O
from tests import post432_l01_l02_scope as L
from tests import r02_ppa_ux_scope as X

ROOT = Path(__file__).resolve().parents[1]
TAIL = ('tests.tax_reference_registry_scope', 'tests.on_bess01_scope', 'tests.onaccept01_scope', 'tests.post432_l01_l02_scope', 'tests.r02_ppa_ux_scope')


def _git(root, *args):
    return subprocess.check_output(['git', '-c', 'user.name=t', '-c', 'user.email=t@t', *args], cwd=root, stderr=subprocess.DEVNULL).decode().strip()


@pytest.fixture(scope='module')
def clone(tmp_path_factory):
    dest = tmp_path_factory.mktemp('r02ppa') / 'repo'
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
    if not X.exact_blobs_ok(root):
        return True
    with C.call_scope():
        return not C.valid(root)


def test_cohort_is_exact_literal_ui_only_and_leaves_backend_and_the_legacy_component_untouched():
    assert X.exact_blobs_ok() and X.signature_ok()
    data = X.manifest()
    assert set(data['source_blobs']) == X.OWNED_PATHS - {X.MANIFEST} and set(data['base_blobs']) == X.SUPERSEDED
    assert not any(p.startswith(X.FORBIDDEN_PREFIXES) or p in X.FORBIDDEN_PATHS or '*' in p for p in X.OWNED_PATHS | {X.MANIFEST})
    assert X.BASE == '64a0d5b7b1ec7c989908d5f288a9ae440c663009' and _git(ROOT, 'rev-parse', X.BASE + '^{tree}') == X.BASE_TREE
    subprocess.check_call(['git', 'merge-base', '--is-ancestor', X.BASE, 'HEAD'], cwd=ROOT)
    changed = set(_git(ROOT, 'diff', '--name-only', '--no-renames', X.BASE).splitlines())
    assert changed <= X.OWNED_PATHS | {X.MANIFEST}
    # no server, engine, writer, parser or security source moved; the WF-React-2 editor file and the revenue contract parser are byte-identical to BASE
    assert not [p for p in changed if p.startswith(('app/', 'financial_engine/', 'finco_core/', 'domain/', '.github/', 'tools/', 'scripts/'))]
    for path in ('frontend/src/app/workflow/PPAEditorView.tsx', 'frontend/src/app/api.ts', 'frontend/src/app/editing/pendingEdits.ts', 'tests/on_bess01_scope.py'):
        assert _git(ROOT, 'rev-parse', 'HEAD:' + path) == _git(ROOT, 'rev-parse', X.BASE + ':' + path), path


def test_registry_keeps_every_accepted_cohort_in_order_and_appends_only_this_one():
    import ast
    base = subprocess.check_output(['git', 'show', X.BASE + ':tests/fin_v2_cohorts.py'], cwd=ROOT).decode()
    assert (ROOT / 'tests/fin_v2_cohorts.py').read_text() == base.replace(X.REGISTRY_MARKER, X.REGISTRY_NEW)
    old = next(ast.literal_eval(n.value) for n in ast.parse(base).body if isinstance(n, ast.Assign) and n.targets[0].id == 'COHORT_MODULES')
    assert C.COHORT_MODULES == old + ('tests.r02_ppa_ux_scope',) and C.COHORT_MODULES[-5:] == TAIL and len(set(C.COHORT_MODULES)) == len(C.COHORT_MODULES)


def test_predecessors_and_older_guards_follow_this_cohort_only_through_the_reviewed_handoffs():
    from tests import tax_reference_registry_scope as T, ux_pr3b2_scope as U, u1_scope as U1
    pins = X.manifest()['source_blobs']
    with C.call_scope():
        assert L.exact_blobs_ok() and O.exact_blobs_ok() and B.exact_blobs_ok() and T.exact_blobs_ok() and U.exact_blobs_ok() and C.valid()
        assert X.reviewed_edits_ok() and L.closure_paths() == X.OWNED_PATHS | L.OWNED_PATHS | {X.MANIFEST, L.MANIFEST} and O.later_owned() == L.closure_paths()
        for path in sorted(X.SOURCE_PATHS - X.NEW_SOURCE_PATHS):
            assert B.supersedes(path, pins[path]) and U1.supersedes(path, pins[path]) and not B.supersedes(path, '0' * 40), path
        assert not B.supersedes('app/v2/router.py', pins['static/react/finco-react.js']) and not X.supersedes('app/v2/router.py', pins['static/react/finco-react.js'])
    for path in X.CURRENT_MAPS:
        assert X.manifest()['source_blobs'][path]


def test_built_bundle_and_component_carry_the_compact_ui_without_any_new_economics():
    bundle = (ROOT / 'static/react/finco-react.js').read_text()
    for needle in ('PPA type', '+ Add PPA', 'Awaiting approved volume-cap economics and numerical proof', 'Show notes', 'data-ppa-save'):
        assert needle in bundle, needle
    for forbidden in ('volume_tiers', 'cap_unit', 'cap_window', 'cap_kind', 'reduced_price_eur_mwh', 'cap_gwh'):
        assert forbidden not in bundle, forbidden
    editor = (ROOT / 'frontend/src/app/workflow/PpaContractsEditor.tsx').read_text()
    assert 'saveRevenueContracts' in editor and 'method: "POST"' not in editor and "method: 'POST'" not in editor      # one persistence path: the canonical writer
    assert re.search(r'readFreshRevenue', editor) and 'contracts_base_token' not in editor.replace('baseToken', '')
    ws = (ROOT / 'frontend/src/app/WorkspaceView.tsx').read_text()
    assert 'PpaContractsEditor' in ws and 'PPAEditorView' not in ws


def test_one_byte_drift_of_every_owned_or_protected_source_fails_closed(tree):
    assert not _bad(tree)      # positive control: the unmodified clone is accepted, so every refusal below is caused by its mutation
    paths = sorted(X.OWNED_PATHS | {X.MANIFEST} | L.OWNED_PATHS | {L.MANIFEST} | O.SOURCE_PATHS | B.APP_PATHS
                   | {'frontend/src/app/workflow/PPAEditorView.tsx', 'frontend/src/app/api.ts', 'tests/on_bess01_reviewed_successors.py'})
    survived = []
    for path in paths:
        _bump(tree, path)
        if not _bad(tree):
            survived.append(path)
        _reset(tree)
    assert not survived, survived


def test_handoff_registry_map_and_historical_pin_rewrites_fail_closed(tree):
    assert not _bad(tree)
    cases = []
    registry = tree / 'tests/fin_v2_cohorts.py'
    text = registry.read_text()
    cases.append(('missing_cohort', lambda: registry.write_text(text.replace(", 'tests.r02_ppa_ux_scope'", ''))))
    cases.append(('missing_l_cohort', lambda: registry.write_text(text.replace(", 'tests.post432_l01_l02_scope'", ''))))
    cases.append(('extra_cohort', lambda: registry.write_text(text.replace("'tests.r02_ppa_ux_scope')", "'tests.r02_ppa_ux_scope', 'tests.fake_scope')"))))
    cases.append(('reordered', lambda: registry.write_text(text.replace("'tests.post432_l01_l02_scope', 'tests.r02_ppa_ux_scope'", "'tests.r02_ppa_ux_scope', 'tests.post432_l01_l02_scope'"))))
    cases.append(('map_registry_pin', lambda: _json(tree, 'docs/ci_v4/SOURCE_SUCCESSOR.json', lambda d: d['source_blobs'].update({X.REGISTRY: '0' * 40}))))
    cases.append(('map_bundle_pin', lambda: _json(tree, 'docs/react_migration/post413_o1/SOURCE_SUCCESSOR.json', lambda d: d['source_blobs'].update({'static/react/finco-react.js': '0' * 40}))))
    cases.append(('map_foreign_field', lambda: _json(tree, 'docs/react_migration/u2_workbench/U2_EXACT_SOURCE.json', lambda d: d.update(base='0' * 40))))
    cases.append(('historical_bess_manifest', lambda: _json(tree, 'docs/bess_setup/SOURCE_SUCCESSOR.json', lambda d: d.update(base='0' * 40))))
    cases.append(('historical_onaccept_manifest', lambda: _json(tree, 'docs/onaccept01/SOURCE_SUCCESSOR.json', lambda d: d.update(base='0' * 40))))
    cases.append(('historical_l_manifest', lambda: _json(tree, L.MANIFEST, lambda d: d.update(base='0' * 40))))
    cases.append(('wrong_base', lambda: _json(tree, X.MANIFEST, lambda d: d.update(base='0' * 40))))
    cases.append(('wrong_tree', lambda: _json(tree, X.MANIFEST, lambda d: d.update(base_tree='0' * 40))))
    cases.append(('wrong_superseded_base_blob', lambda: _json(tree, X.MANIFEST, lambda d: d['base_blobs'].update({'frontend/src/app/WorkspaceView.tsx': '0' * 40}))))
    cases.append(('dropped_superseded_pair', lambda: _json(tree, X.MANIFEST, lambda d: d['base_blobs'].pop('frontend/src/app/WorkspaceView.tsx'))))
    cases.append(('forged_source_pin', lambda: _json(tree, X.MANIFEST, lambda d: d['source_blobs'].update({'frontend/src/app/workflow/PpaContractsEditor.tsx': '0' * 40}))))
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
    assert not _bad(tree)
    survived = []
    for path in ('app/v2/router.py', 'app/workbook/revenue_contracts_service.py', 'domain/revenue/multistream_runtime.py', 'domain/revenue/plan_engine.py', 'financial_engine/__init__.py',
                 'finco_core/__init__.py', 'main_web.py', '.github/workflows/ci_v4_pr.yml', 'scripts/finco_live_acceptance/policy.py', 'frontend/src/app/editing/pendingEdits.ts',
                 'frontend/src/app/workflow/workflowShared.tsx', 'frontend/src/app/unreviewed_component.tsx'):
        f = tree / path
        f.parent.mkdir(parents=True, exist_ok=True)
        f.write_bytes((f.read_bytes() if f.exists() else b'') + b'\n// unreviewed\n')
        if not _bad(tree):
            survived.append(path)
        _reset(tree)
    for path in sorted(X.SOURCE_PATHS | {'tests/on_bess01_scope.py', 'tests/fin_v2_cohorts.py', X.MANIFEST}):
        (tree / path).chmod(0o755)
        if not _bad(tree):
            survived.append(('mode', path))
        _reset(tree)
        f = tree / path
        f.unlink()
        f.symlink_to(tree / 'README.md')
        if not _bad(tree):
            survived.append(('symlink', path))
        _reset(tree)
    for name in ('frontend/src/app/workflow/untracked_unpublished.tsx', 'tests/unpublished_helper.py', 'static/react/extra.js'):
        (tree / name).parent.mkdir(parents=True, exist_ok=True)
        (tree / name).write_text('x = 1\n')
        if not _bad(tree):
            survived.append(('untracked', name))
        _reset(tree)
    orphan = _git(tree, 'commit-tree', _git(tree, 'rev-parse', 'HEAD^{tree}'), '-m', 'orphan')
    assert not X.exact_blobs_ok(tree, orphan) and X.exact_blobs_ok(tree, 'HEAD')
    _git(tree, 'update-index', '--chmod=+x', 'frontend/src/app/WorkspaceView.tsx')
    _git(tree, 'commit', '-qm', 'mode')
    assert not X.exact_blobs_ok(tree, 'HEAD')
    assert not survived, survived
