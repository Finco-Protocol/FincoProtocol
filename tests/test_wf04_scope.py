"""WF-04 exact-source cohort: strict admission, predecessor re-pin lineage and the proof that no protected financial authority moved.

The cohort (tests/wf04_scope.py) is closed: one literal path set at exact Git blobs. These controls prove that a one-byte drift, a deletion, a
forged or malformed manifest, an unreviewed changed/untracked path, a wrong ancestry, an unregistered cohort or a tampered predecessor re-pin all
fail closed, and that the two protected paths WF-04 had to touch (workspace_repository.py, registry.py) changed only by the reviewed additive hunks.
"""
import ast
import difflib
import json

import pytest

from tests import fin_v2_cohorts as C
from tests import wf04_scope as W

ENGINE_PREFIXES = ('financial_engine/', 'finco_core/', 'domain/', '.github/')


# WF-04's own delta is what the merged PR #399 brought: it is verified at that immutable commit (WF03_PARENT), so a later, separately governed WF-03
# successor on top of it (tests/wf03_lifecycle_scope.py, which exact_blobs_ok() enforces on the tree) cannot blur or hide it.
REF = W.WF03_PARENT


def _changed():
    """The WF-04 delta: what differs from the approved main (with the merged WS-2 PR) this cohort was integrated with."""
    return W._git(W.ROOT, 'diff', '--name-only', W.APPROVED_MAIN, REF, '--').decode().splitlines()


def _changed_since_origin():
    """Everything that differs from WF-04's historical origin: the WS-2 sources arrive from main, the rest is the WF-04 delta."""
    return W._git(W.ROOT, 'diff', '--name-only', W.BASE, REF, '--').decode().splitlines()


def test_cohort_is_registered_exact_closed_and_excludes_every_financial_authority():
    assert W.__name__ in C.COHORT_MODULES and W in C.cohorts()
    assert W.exact_blobs_ok() and W.valid() and C.valid()
    assert W.protected_blobs() == {}
    assert set(W.manifest()['source_blobs']) == W.OWNED_PATHS
    # the ONLY forbidden-prefix path the cohort owns is the single Owner-approved workflow (Correction C timeout hunk), enforced byte-exactly by _workflow_hunk_ok
    assert {p for p in W.OWNED_PATHS if p.startswith(W.FORBIDDEN_PREFIXES)} == {W.WORKFLOW_PATH}
    assert not any(p in W.FORBIDDEN_PATHS for p in W.OWNED_PATHS)
    assert not any(p.startswith(ENGINE_PREFIXES) and p != W.WORKFLOW_PATH for p in _changed())            # the one approved workflow hunk is the sole exception
    assert not any(p.startswith(ENGINE_PREFIXES) and p != W.WORKFLOW_PATH for p in _changed_since_origin())


WS2_WRITER_PATHS = ('app/v2/grid_router.py', 'app/v2/react_workspace_router.py', 'app/v2/save_all_commands.py')
GUARDED_PATHS = ('app/v2/router.py', *WS2_WRITER_PATHS, 'app/v2/mutation_csrf.py', 'app/workbook/update_service.py',
                 'app/workbook/bankability_config.py', 'app/persistence/run_history_repository.py', 'app/services/run_intent_service.py',
                 'app/api/project_runner.py', 'app/input_adapter.py', 'main_web.py')
GUARDED_PREFIXES = ('app/run_integrity/', 'app/runtime/', 'app/export/', 'frontend/src/app/editing/')


def _blob_at(ref, path):
    return W._blob(W._git(W.ROOT, 'show', ref + ':' + path))


def test_no_writer_route_csrf_save_all_security_or_engine_file_is_changed_by_wf04():
    """Lineage-aware: the WS-2 writer/route/Save All/editing sources DID change since WF-04's origin (PR #397, in main) - WF-04 itself changed none."""
    changed = set(_changed())
    for path in GUARDED_PATHS:
        assert path not in changed, path
    assert not [p for p in changed if p.startswith(GUARDED_PREFIXES)]
    # every guarded path is byte-identical to the approved main, i.e. WF-04 contributes nothing to it ...
    tracked = [p for p in W._git(W.ROOT, 'ls-tree', '-r', '--name-only', REF).decode().splitlines() if p.startswith(GUARDED_PREFIXES) or p in GUARDED_PATHS]
    for path in tracked:
        assert W._blob(W._read(W.ROOT, path, REF)) == _blob_at(W.APPROVED_MAIN, path), path
    # ... and the arrival of the WS-2 sources is a fact of the lineage, not hidden: they are in the origin delta, not in the WF-04 delta
    origin = set(_changed_since_origin())
    assert set(WS2_WRITER_PATHS) <= origin and any(p.startswith('frontend/src/app/editing/') for p in origin)


def test_the_approved_main_is_the_authenticated_ancestor_and_the_origin_is_kept():
    assert W._lineage_ok(W.ROOT, None)
    assert W.manifest()['approved_main'] == W.APPROVED_MAIN and W.manifest()['base'] == W.BASE
    parents = W._git(W.ROOT, 'rev-list', '--parents', '-n', '1', 'HEAD').decode().split()[1:]
    # the integration is a normal merge: one parent is the approved main (or the WF-04 head already contains it)
    assert W.APPROVED_MAIN in parents or W._git(W.ROOT, 'merge-base', '--is-ancestor', W.APPROVED_MAIN, 'HEAD') == b''


@pytest.mark.parametrize('field,value', (('APPROVED_MAIN', '0' * 40), ('APPROVED_MAIN_TREE', '0' * 40), ('BASE', '1' * 40)))
def test_a_forged_swapped_or_unrelated_lineage_fails_closed(field, value, monkeypatch):
    monkeypatch.setattr(W, field, value)
    assert not W.exact_blobs_ok() and not C.valid()


def test_the_approved_main_must_descend_from_the_origin(monkeypatch):
    unrelated = W._git(W.ROOT, 'rev-list', '--max-parents=0', 'HEAD').decode().split()[0]
    monkeypatch.setattr(W, 'APPROVED_MAIN', unrelated)
    assert not W.exact_blobs_ok() and not C.valid()


@pytest.mark.parametrize('path', sorted(W.OWNED_PATHS))
@pytest.mark.parametrize('operation', ('drift', 'delete'))
def test_every_owned_byte_and_deletion_fails_closed(path, operation, monkeypatch):
    original = W._read

    def altered(root, p, ref):
        if p == path and ref is None:
            if operation == 'delete':
                raise FileNotFoundError(path)
            return original(root, p, ref) + b'\n'
        return original(root, p, ref)

    monkeypatch.setattr(W, '_read', altered)
    assert not W.exact_blobs_ok() and not C.valid()


@pytest.mark.parametrize('drop', (False, True))
def test_manifest_cannot_add_or_drop_any_pin(drop, monkeypatch):
    original = W._read

    def altered(root, path, ref):
        raw = original(root, path, ref)
        if path == W.MANIFEST and ref is None:
            data = json.loads(raw)
            if drop:
                data['source_blobs'].pop('app/workbook/dscr_contract_terms.py')
            else:
                data['source_blobs']['financial_engine/senior_debt/solver.py'] = '0' * 40
            return json.dumps(data).encode()
        return raw

    monkeypatch.setattr(W, '_read', altered)
    assert not W.exact_blobs_ok() and not C.valid()


@pytest.mark.parametrize('payload', ([], None, {'source_blobs': None}, {'source_blobs': []}, {'schema_version': 'other'}, {'base': '0' * 40}))
def test_malformed_manifest_shapes_return_false(payload, monkeypatch):
    original = W._read

    def altered(root, path, ref):
        if path == W.MANIFEST and ref is None:
            malformed = payload
            if isinstance(payload, dict):
                malformed = {**json.loads(original(root, path, ref)), **payload}
            return json.dumps(malformed).encode()
        return original(root, path, ref)

    monkeypatch.setattr(W, '_read', altered)
    assert not W.manifest() and not W.exact_blobs_ok() and not C.valid()


@pytest.mark.parametrize('path', (
    'app/v2/router.py', 'app/v2/save_all_commands.py', 'app/v2/grid_router.py', 'app/workbook/mutation_csrf.py', 'app/workbook/update_service.py',
    'app/persistence/projects_repository.py', 'financial_engine/senior_debt/solver.py', 'finco_core/inputs/_models.py',
    '.github/workflows/unreviewed.yml', 'frontend/src/app/editing/store.ts', 'tests/wf04_future_test.py',
    'docs/financial_validation/wf04_debt_metrics/unreviewed.md',
))
def test_unapproved_changed_or_untracked_path_is_refused(path, monkeypatch):
    assert not W.allowed_path(path)
    original = W._git

    def extra(root, *args):
        result = original(root, *args)
        if args[:2] == ('diff', '--name-only'):
            return result + b'\n' + path.encode()
        return result

    monkeypatch.setattr(W, '_git', extra)
    assert not W.exact_blobs_ok() and not C.valid()


@pytest.mark.parametrize('unreviewed', ('evidence/rogue.py', 'app/v2/new_writer.py', 'tests/new_financial_test.py', 'docs/stray.md'))
def test_untracked_source_is_strictly_rejected(unreviewed, monkeypatch):
    original = W._git

    def extra(root, *args):
        result = original(root, *args)
        return result + unreviewed.encode() + b'\n' if args[:3] == ('ls-files', '--others', '--exclude-standard') else result

    monkeypatch.setattr(W, '_git', extra)
    assert not W.exact_blobs_ok()


@pytest.mark.parametrize('artifact', ('evidence/source.json', 'evidence/browser/solar.png', 'evidence/financial-browser.xml'))
def test_generated_ci_evidence_is_not_source(artifact, monkeypatch):
    original = W._git

    def extra(root, *args):
        result = original(root, *args)
        return result + artifact.encode() + b'\n' if args[:3] == ('ls-files', '--others', '--exclude-standard') else result

    monkeypatch.setattr(W, '_git', extra)
    assert W.exact_blobs_ok() and C.valid()


@pytest.mark.parametrize('field', ('BASE', 'APPROVED_MAIN'))
def test_wrong_or_missing_ancestry_fails_closed(field, monkeypatch):
    monkeypatch.setattr(W, field, '0' * 40)
    assert not W.exact_blobs_ok() and not C.valid()


def test_absent_or_unregistered_cohort_cannot_be_silently_omitted(monkeypatch):
    original = C.importlib.import_module

    def missing(name):
        if name == W.__name__:
            raise ModuleNotFoundError(name=name)
        return original(name)

    with monkeypatch.context() as patch:
        patch.setattr(C.importlib, 'import_module', missing)
        assert not C.valid()
    monkeypatch.setattr(C, 'COHORT_MODULES', tuple(n for n in C.COHORT_MODULES if n != W.__name__))
    assert not C.valid()


def test_a_forbidden_namespace_can_never_be_owned(monkeypatch):
    monkeypatch.setattr(W, 'OWNED_PATHS', W.OWNED_PATHS | {'financial_engine/senior_debt/solver.py'})
    assert not W.exact_blobs_ok()
    monkeypatch.setattr(W, 'OWNED_PATHS', (W.OWNED_PATHS - {'financial_engine/senior_debt/solver.py'}) | {'app/v2/save_all_commands.py'})
    assert not W.exact_blobs_ok()


# ── predecessor manifests: only the named re-pins move, and the previous maps are preserved verbatim ──────────────────────────────────────
def test_predecessor_manifests_keep_their_approved_main_state_except_the_named_repins():
    assert W._historical_manifests_ok(W.ROOT, None)
    for path, allowed in W.PREDECESSOR_REPINS.items():
        old = json.loads(W._read(W.ROOT, path, W.APPROVED_MAIN))
        now = json.loads(W._read(W.ROOT, path, REF))
        assert now['historical_source_blobs'][W.APPROVED_MAIN] == old['source_blobs']
        moved = {p for p in old['source_blobs'] if old['source_blobs'][p] != now['source_blobs'][p]}
        assert moved <= allowed, moved - allowed
        for p in moved:                                                    # a re-pinned path is one WF-04 owns, at exactly the WF-04 pin
            assert now['source_blobs'][p] == W.manifest(ref=REF)['source_blobs'][p], p
            assert W._blob(W._read(W.ROOT, p, REF)) == now['source_blobs'][p], p
        # WF-04's historical origin map is kept verbatim where the manifest already existed there (WS-2's manifest is newer than BASE)
        try:
            origin = json.loads(W._read(W.ROOT, path, W.BASE))['source_blobs']
        except Exception:
            assert path == W.WSV2_EDITING_MANIFEST
        else:
            assert now['historical_source_blobs'][W.BASE] == origin


def test_the_registry_and_workspace_repository_repins_are_the_only_financial_pin_moves():
    moved = {}
    for path in W.PREDECESSOR_REPINS:
        old = json.loads(W._read(W.ROOT, path, W.APPROVED_MAIN))['source_blobs']
        now = json.loads(W._read(W.ROOT, path, REF))['source_blobs']
        moved[path] = {p for p in old if old[p] != now[p] and p.startswith(('app/', 'financial_engine/', 'finco_core/', 'domain/', '.github/'))}
    assert moved[W.FIN_V2_3_MANIFEST] == {'app/workbook/registry.py'}
    assert moved[W.WSV2_EDITING_MANIFEST] == {'app/persistence/workspace_repository.py'}
    assert moved[W.FIN_V2_R1_MANIFEST] == moved[W.FIN_V2_D01_MANIFEST] == moved[W.WSV2_CORE_MANIFEST] == set()


def test_ws2_manifest_moves_only_the_run_identity_hunk_of_the_workspace_repository():
    old = json.loads(W._read(W.ROOT, W.WSV2_EDITING_MANIFEST, W.APPROVED_MAIN))
    now = json.loads(W._read(W.ROOT, W.WSV2_EDITING_MANIFEST, REF))
    assert {k: v for k, v in old.items() if k not in ('source_blobs', 'historical_source_blobs')} == \
        {k: v for k, v in now.items() if k not in ('source_blobs', 'historical_source_blobs')}
    assert [p for p in old['source_blobs'] if old['source_blobs'][p] != now['source_blobs'][p]] == ['app/persistence/workspace_repository.py']


@pytest.mark.parametrize('tamper', ('history', 'history_missing', 'origin_history', 'financial_pin', 'unnamed_repin', 'metadata', 'dropped_pin', 'added_pin'))
def test_historical_record_or_unnamed_repin_cannot_be_resealed(tamper, monkeypatch):
    original = W._read
    target = W.FIN_V2_3_MANIFEST

    def altered(root, path, ref):
        raw = original(root, path, ref)
        if path == target and ref is None:
            data = json.loads(raw)
            if tamper == 'history':
                data['historical_source_blobs'][W.APPROVED_MAIN]['app/v2/router.py'] = '0' * 40
            elif tamper == 'history_missing':
                data['historical_source_blobs'].pop(W.APPROVED_MAIN)
            elif tamper == 'origin_history':
                data['historical_source_blobs'][W.BASE]['app/v2/router.py'] = '0' * 40
            elif tamper == 'financial_pin':
                data['source_blobs']['app/v2/router.py'] = '0' * 40
            elif tamper == 'unnamed_repin':
                data['source_blobs']['tests/test_ci_acceptance.py'] = '0' * 40
            elif tamper == 'dropped_pin':
                data['source_blobs'].pop('app/workbook/registry.py')
            elif tamper == 'added_pin':
                data['source_blobs']['app/new_unreviewed.py'] = '0' * 40
            else:
                data['authorization'] = 'unreviewed'
            return json.dumps(data).encode()
        return raw

    monkeypatch.setattr(W, '_read', altered)
    assert not W._historical_manifests_ok(W.ROOT, None) and not W.exact_blobs_ok() and not C.valid()


def test_a_predecessor_pin_that_disagrees_with_the_real_bytes_breaks_that_cohort(monkeypatch):
    from tests import fin_v2_3_scope as F3
    original = F3._read

    def altered(root, path, ref):
        raw = original(root, path, ref)
        if path == F3.MANIFEST and ref is None:
            data = json.loads(raw)
            data['source_blobs']['app/workbook/registry.py'] = data['historical_source_blobs'][W.APPROVED_MAIN]['app/workbook/registry.py']
            return json.dumps(data).encode()
        return raw

    monkeypatch.setattr(F3, '_read', altered)
    assert not F3.exact_blobs_ok() and not C.valid()


# ── the two protected paths changed only by the reviewed additive hunks ───────────────────────────────────────────────────────────────────────
def _opcodes(path):
    before = W._read(W.ROOT, path, W.APPROVED_MAIN).decode().splitlines()
    after = W._read(W.ROOT, path, REF).decode().splitlines()
    ops = [op for op in difflib.SequenceMatcher(None, before, after, autojunk=False).get_opcodes() if op[0] != 'equal']
    return before, after, ops


def test_workspace_repository_change_is_one_additive_hunk_inside_the_atomic_run_commit_only():
    path = 'app/persistence/workspace_repository.py'
    before, after, ops = _opcodes(path)
    assert [op[0] for op in ops] == ['insert']
    _, _, _, j1, j2 = ops[0]
    inserted = '\n'.join(after[j1:j2])
    assert 'dscr_contract_terms' in inserted and 'ROLLBACK' in inserted and j2 - j1 == 12
    tree = ast.parse('\n'.join(after))
    function = next(n for n in ast.walk(tree) if isinstance(n, ast.FunctionDef) and n.name == 'v2_atomic_run_commit')
    assert function.lineno <= j1 + 1 and j2 <= function.end_lineno
    assert after[:j1] + after[j2:] == before                                # removing the hunk gives back the approved-main file line-for-line (all WS-2 code kept)


def test_registry_change_is_the_two_contract_fields_and_the_sheet_line_only():
    path = 'app/workbook/registry.py'
    before, after, ops = _opcodes(path)
    removed = [l for op in ops for l in before[op[1]:op[2]]]
    assert len(removed) == 1 and removed[0].startswith('_SHEET_DEBT = _sheet(')            # the only pre-existing line that changes
    added = '\n'.join(l for op in ops for l in after[op[3]:op[4]])
    assert '_SHEET_DEBT = _sheet(_DT, "Senior Debt", [_dt_senior, _dt_contract]' in added
    assert added.count('kind=FieldKind.INPUT') == 2 and added.count('_f(f"{_DT}.contract.') == 2
    assert 'debt.contract.min_dscr_eod' not in '\n'.join(before)
    from app.workbook.registry import WORKBOOK
    contract = [f.field_id for f in WORKBOOK.all_fields() if f.field_id.startswith('debt.contract.')]
    assert sorted(contract) == ['debt.contract.contractual_dscr', 'debt.contract.min_dscr_eod']
    assert WORKBOOK.version == '2.3.0'


# ── the browser acceptance joins the existing mandatory role without a collection-time skip ──────────────────────────────────────────────
def test_browser_acceptance_is_an_additive_import_in_the_existing_role_with_no_skip_of_its_own():
    role = W._read(W.ROOT, W.ROLE_MODULE, REF).decode()
    helper = W._read(W.ROOT, W.ROLE_ACCEPTANCE, REF).decode()
    assert role.endswith('\n'.join(W.ROLE_IMPORT_BLOCK) + '\n') and role.count(W.ROLE_IMPORT_BLOCK[-1]) == 1
    original = W._read(W.ROOT, W.ROLE_MODULE, W.APPROVED_MAIN).decode()
    assert role.startswith(original.rstrip() + '\n')                       # nothing before the appended block changed
    tree = ast.parse(helper)
    tests = [n.name for n in tree.body if isinstance(n, ast.FunctionDef) and n.name.startswith('test_')]
    exported = next(ast.literal_eval(n.value) for n in tree.body if isinstance(n, ast.Assign)
                    and isinstance(n.targets[0], ast.Name) and n.targets[0].id == '__all__')
    assert len(tests) == 14 and exported == ['world'] + tests
    assert not any(token in helper for token in ('importorskip', 'pytest.skip', 'mark.skip', 'skipif', 'xfail', 'autouse'))
    assert not W.ROLE_ACCEPTANCE.rsplit('/', 1)[-1].startswith('test_')       # never collected on its own
    assert 'FINCO_MODEL_REACT_V1' not in helper                               # the flag is the shared per-test fixture, not a module side effect


def test_the_role_import_block_cannot_be_widened(monkeypatch):
    original = W._read

    def widened(root, path, ref):
        raw = original(root, path, ref)
        return raw + b'\nfrom tests.rogue_acceptance import *\n' if path == W.ROLE_MODULE and ref is None else raw

    monkeypatch.setattr(W, '_read', widened)
    assert not W.exact_blobs_ok() and not C.valid()


# ── post-#397 lineage: every WS-2 predecessor source stays pinned by its own cohort inside the integrated head ────────────────────────────
def _ws2_sources():
    from tests import fin_v2_wsv2_scope as WS2
    return sorted(WS2.OWNED_PATHS)


@pytest.mark.parametrize('path', _ws2_sources())
def test_one_byte_corruption_of_each_ws2_predecessor_source_fails_closed(path, monkeypatch):
    from tests import fin_v2_wsv2_scope as WS2
    assert WS2.exact_blobs_ok() and W.exact_blobs_ok() and C.valid()
    for module in (WS2, W):
        original = module._read

        def drift(root, p, ref, _o=original):
            raw = _o(root, p, ref)
            return raw + b'\n' if p == path and ref is None else raw

        monkeypatch.setattr(module, '_read', drift)
    assert not WS2.exact_blobs_ok() and not C.valid()


def test_the_ws2_cohort_is_valid_with_the_wf04_delta_present_and_wf04_is_not_a_wildcard():
    from tests import fin_v2_wsv2_scope as WS2
    assert WS2.valid() and W.valid() and C.valid()
    delta = set(_changed())
    assert delta and delta <= W.OWNED_PATHS | {W.MANIFEST}
    assert not [p for p in delta if p in WS2.OWNED_PATHS and p != 'app/persistence/workspace_repository.py'], \
        'WF-04 may only touch the one WS-2 source it was authorised to add a hunk to'
    assert not any(any(c in p for c in '*?[') for p in W.OWNED_PATHS)


def test_the_two_accidental_empty_files_are_gone_and_lost_nothing():
    tracked = set(W._git(W.ROOT, 'ls-files').decode().splitlines())
    assert not ({'per1_fail.txt', 'per2_fail.txt'} & tracked) and not ({'per1_fail.txt', 'per2_fail.txt'} & W.OWNED_PATHS)
    for name in ('per1_fail.txt', 'per2_fail.txt'):                       # they were zero-byte in every commit that ever contained them
        for ref in W._git(W.ROOT, 'log', '--format=%H', '--', name).decode().split():
            try:
                assert W._git(W.ROOT, 'show', ref + ':' + name) == b''
            except Exception:                                              # the deleting commit has no such path
                pass


# ── Correction C: the single Owner-approved workflow hunk (consolidation budget 3600 s, outer limit 105 min) ─────────────────────────────────
def _workflow_text():
    return W._read(W.ROOT, W.WORKFLOW_PATH, None).decode()


def test_the_workflow_is_the_only_github_path_owned_and_is_exactly_the_approved_main_bytes_plus_the_literal_hunk():
    assert [p for p in W.OWNED_PATHS if p.startswith('.github/')] == [W.WORKFLOW_PATH]
    assert [p for p in _changed() if p.startswith('.github/')] == [W.WORKFLOW_PATH]
    old = W._read(W.ROOT, W.WORKFLOW_PATH, W.APPROVED_MAIN)
    assert W._blob(old) == W.WORKFLOW_OLD_BLOB and W._workflow_hunk_ok(W.ROOT, None)
    text = _workflow_text()
    assert text.count('timeout-minutes: 105') == 1 and 'timeout-minutes: 45' not in text
    assert text.count("FINCO_CI_PYTEST_BUDGET_S: '1200'") == 1 and text.count("FINCO_CI_EXIT_GRACE_S: '180'") == 1       # global value and grace unchanged
    assert text.count('export FINCO_CI_PYTEST_BUDGET_S=3600') == 1 and text.count('export FINCO_CI_PYTEST_BUDGET_S=1200') == 1
    assert 'if [ "$role" = "consolidation" ]; then' in text and 'for role in protocol import grid q4 outputs consolidation; do' in text
    assert text.index('CI_BROWSER_ROLE_BUDGET') < text.index('python -m tools.ci_browser_job "$role" --expected "$HEAD_SHA"')    # announced before the role starts
    assert 'continue-on-error' not in text
    assert 105 * 60 > 3600 + 180                                         # the outer job limit exceeds the inner budget plus the exit grace
    import re
    removed = [l for l in old.decode().splitlines() if l not in text.splitlines()]
    assert removed == ['    timeout-minutes: 45']                         # nothing else of the approved-main workflow was removed or changed


_WORKFLOW_TAMPER = {
    'outer_limit_changed': lambda t: t.replace('timeout-minutes: 105', 'timeout-minutes: 106'),
    'outer_limit_reverted': lambda t: t.replace('timeout-minutes: 105', 'timeout-minutes: 45'),
    'consolidation_budget_raised': lambda t: t.replace('=3600', '=3601'),
    'other_roles_budget_raised': lambda t: t.replace('export FINCO_CI_PYTEST_BUDGET_S=1200', 'export FINCO_CI_PYTEST_BUDGET_S=3600'),
    'global_budget_raised': lambda t: t.replace("FINCO_CI_PYTEST_BUDGET_S: '1200'", "FINCO_CI_PYTEST_BUDGET_S: '3600'"),
    'grace_changed': lambda t: t.replace("FINCO_CI_EXIT_GRACE_S: '180'", "FINCO_CI_EXIT_GRACE_S: '600'"),
    'role_selector_widened': lambda t: t.replace('"$role" = "consolidation"', '"$role" != "protocol"'),
    'role_dropped': lambda t: t.replace('for role in protocol import grid q4 outputs consolidation; do', 'for role in protocol import grid q4 consolidation; do'),
    'continue_on_error_added': lambda t: t.replace('    runs-on: ubuntu-24.04\n', '    runs-on: ubuntu-24.04\n    continue-on-error: true\n', 1),
    'permissions_widened': lambda t: t.replace('permissions:\n  contents: read', 'permissions:\n  contents: write', 1),
    'trigger_added': lambda t: t.replace('  pull_request:\n', '  pull_request:\n  pull_request_target:\n', 1),
    'checkout_ref_changed': lambda t: t.replace("fetch-depth: 0", "fetch-depth: 1", 1),
    'aggregate_job_result_changed': lambda t: t.replace('--job-result success', '--job-result failure'),
    'verification_step_removed': lambda t: t.replace('python -m tools.ci_browser_job aggregate', 'echo skipped'),
    'unrelated_step_appended': lambda t: t + '      - run: echo unreviewed\n',
    'byte_appended': lambda t: t + '\n',
}


@pytest.mark.parametrize('name', sorted(_WORKFLOW_TAMPER))
def test_any_other_workflow_byte_than_the_approved_hunk_fails_closed(name, monkeypatch):
    changed = _WORKFLOW_TAMPER[name](_workflow_text())
    assert changed != _workflow_text(), name
    original = W._read

    def altered(root, path, ref):
        return changed.encode() if path == W.WORKFLOW_PATH and ref is None else original(root, path, ref)

    monkeypatch.setattr(W, '_read', altered)
    assert not W._workflow_hunk_ok(W.ROOT, None) and not W.exact_blobs_ok() and not C.valid()


def test_the_pre_change_approved_main_workflow_is_no_longer_accepted_and_the_hunk_cannot_be_dropped(monkeypatch):
    old = W._read(W.ROOT, W.WORKFLOW_PATH, W.APPROVED_MAIN)
    original = W._read
    monkeypatch.setattr(W, '_read', lambda root, path, ref: old if path == W.WORKFLOW_PATH and ref is None else original(root, path, ref))
    assert not W._workflow_hunk_ok(W.ROOT, None) and not W.exact_blobs_ok()


@pytest.mark.parametrize('other', ('.github/workflows/ci_browser_job.yml', '.github/workflows/ci_public_job.yml', '.github/workflows/pr_compile_and_safety.yml',
                                   '.github/workflows/new_unreviewed.yml', '.github/CODEOWNERS', '.github/workflows/protocol_ui_browser.yml.bak'))
def test_every_other_github_path_stays_forbidden(other, monkeypatch):
    assert not W.allowed_path(other)
    monkeypatch.setattr(W, 'OWNED_PATHS', W.OWNED_PATHS | {other})
    assert not W._owned_ok() and not W.exact_blobs_ok()


def test_a_wrong_old_blob_pin_for_the_workflow_fails_closed(monkeypatch):
    monkeypatch.setattr(W, 'WORKFLOW_OLD_BLOB', '0' * 40)
    assert not W._workflow_hunk_ok(W.ROOT, None) and not W.exact_blobs_ok()
