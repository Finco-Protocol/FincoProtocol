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


def _changed():
    return W._git(W.ROOT, 'diff', '--name-only', W.BASE, '--').decode().splitlines()


def test_cohort_is_registered_exact_closed_and_excludes_every_financial_authority():
    assert W.__name__ in C.COHORT_MODULES and W in C.cohorts()
    assert W.exact_blobs_ok() and W.valid() and C.valid()
    assert W.protected_blobs() == {}
    assert set(W.manifest()['source_blobs']) == W.OWNED_PATHS
    assert not any(p.startswith(W.FORBIDDEN_PREFIXES) or p in W.FORBIDDEN_PATHS for p in W.OWNED_PATHS)
    assert not any(p.startswith(ENGINE_PREFIXES) for p in _changed())


def test_no_writer_route_csrf_save_all_security_or_engine_file_is_changed():
    changed = set(_changed())
    for path in ('app/v2/router.py', 'app/v2/grid_router.py', 'app/v2/react_workspace_router.py', 'app/v2/mutation_csrf.py',
                 'app/workbook/update_service.py', 'app/workbook/bankability_config.py', 'app/persistence/run_history_repository.py',
                 'app/services/run_intent_service.py', 'app/api/project_runner.py', 'app/input_adapter.py', 'main_web.py'):
        assert path not in changed, path
    assert not [p for p in changed if p.startswith(('app/run_integrity/', 'app/runtime/', 'app/export/', 'frontend/src/app/editing/'))]


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


def test_wrong_or_missing_ancestry_fails_closed(monkeypatch):
    monkeypatch.setattr(W, 'BASE', '0' * 40)
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


# ── predecessor manifests: only the named re-pins move, and the previous map is preserved verbatim ─────────────────────────────────────────
def test_predecessor_manifests_keep_their_base_state_except_the_named_repins():
    assert W._historical_manifests_ok(W.ROOT, None)
    for path, allowed in W.PREDECESSOR_REPINS.items():
        old = json.loads(W._read(W.ROOT, path, W.BASE))
        now = json.loads(W._read(W.ROOT, path, None))
        assert now['historical_source_blobs'][W.BASE] == old['source_blobs']
        moved = {p for p in old['source_blobs'] if old['source_blobs'][p] != now['source_blobs'][p]}
        assert moved <= allowed, moved - allowed
        for p in moved:                                                    # a re-pinned path is one WF-04 owns, at exactly the WF-04 pin
            assert now['source_blobs'][p] == W.manifest()['source_blobs'][p], p
            assert W._blob(W._read(W.ROOT, p, None)) == now['source_blobs'][p], p


def test_the_registry_and_workspace_repository_repins_are_the_only_financial_pin_moves():
    moved = {}
    for path in W.PREDECESSOR_REPINS:
        old = json.loads(W._read(W.ROOT, path, W.BASE))['source_blobs']
        now = json.loads(W._read(W.ROOT, path, None))['source_blobs']
        moved[path] = {p for p in old if old[p] != now[p] and p.startswith(('app/', 'financial_engine/', 'finco_core/', 'domain/', '.github/'))}
    assert moved[W.FIN_V2_3_MANIFEST] == {'app/workbook/registry.py'}
    assert moved[W.FIN_V2_R1_MANIFEST] == moved[W.FIN_V2_D01_MANIFEST] == moved[W.WSV2_CORE_MANIFEST] == set()


@pytest.mark.parametrize('tamper', ('history', 'history_missing', 'financial_pin', 'unnamed_repin', 'metadata', 'dropped_pin', 'added_pin'))
def test_historical_record_or_unnamed_repin_cannot_be_resealed(tamper, monkeypatch):
    original = W._read
    target = W.FIN_V2_3_MANIFEST

    def altered(root, path, ref):
        raw = original(root, path, ref)
        if path == target and ref is None:
            data = json.loads(raw)
            if tamper == 'history':
                data['historical_source_blobs'][W.BASE]['app/v2/router.py'] = '0' * 40
            elif tamper == 'history_missing':
                data['historical_source_blobs'].pop(W.BASE)
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
            data['source_blobs']['app/workbook/registry.py'] = data['historical_source_blobs'][W.BASE]['app/workbook/registry.py']
            return json.dumps(data).encode()
        return raw

    monkeypatch.setattr(F3, '_read', altered)
    assert not F3.exact_blobs_ok() and not C.valid()


# ── the two protected paths changed only by the reviewed additive hunks ───────────────────────────────────────────────────────────────────────
def _opcodes(path):
    before = W._read(W.ROOT, path, W.BASE).decode().splitlines()
    after = W._read(W.ROOT, path, None).decode().splitlines()
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
    assert after[:j1] + after[j2:] == before                                # removing the hunk gives back the accepted file line-for-line


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
