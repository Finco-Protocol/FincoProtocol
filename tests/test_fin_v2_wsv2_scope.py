"""Negative controls for the finite WS-2 Save All exact-source cohort and its place in the FIN-V2 cohort registry."""
import json

import pytest

from tests import fin_v2_cohorts as C
from tests import fin_v2_wsv2_scope as F

SOURCES = sorted(F.OWNED_PATHS - {'tests/test_fin_v2_wsv2_scope.py'})


def test_the_cohort_is_registered_valid_and_owns_no_financial_namespace(tmp_path):
    assert F.__name__ in C.COHORT_MODULES and F in C.cohorts()
    assert F.valid() and C.valid()
    assert not F.valid(tmp_path)
    assert F.protected_blobs() == {}
    assert not any(p.startswith(('financial_engine/', 'finco_core/', 'domain/', '.github/', 'app/runtime/', 'app/services/'))
                   for p in F.OWNED_PATHS)
    assert not F.matches('financial_engine/dsra/target.py') and not C.matches('unreviewed/new_financial_authority.py')


def test_the_owned_set_is_exactly_the_authorised_app_paths_the_cohort_and_its_tests():
    assert sorted(p for p in F.OWNED_PATHS if p.startswith('app/')) == [
        'app/persistence/db.py', 'app/persistence/workspace_repository.py', 'app/trust_readiness/registry.py', 'app/v2/capex_commands.py',
        'app/v2/cost_batch_commands.py', 'app/v2/grid_router.py', 'app/v2/react_workspace_router.py', 'app/v2/save_all_commands.py',
        'app/workbook/revenue_contracts_service.py']          # the eight Save All paths + the one reviewed Trust classification (gate C)
    assert sorted(p for p in F.OWNED_PATHS if not p.startswith('app/')) == [
        'docs/react_migration/wsv2_editing/WS2_CI_V3_TRUST_SUCCESSOR.json', 'docs/readiness/02_data_handling.md',
        'docs/readiness/06_retention_and_deletion.md', 'tests/fin_v2_wsv2_scope.py', 'tests/test_ci_v3_outcome_reconciliation.py',
        'tests/test_fin_v2_wsv2_scope.py', 'tests/test_save_all_atomic_v1.py', 'tests/test_trust_readiness_registry.py',
        'tools/ci_v3_production.py']


def test_the_presentation_list_is_closed_exact_and_present():
    assert all(not any(c in p for c in '*?[') and p.startswith('frontend/src/') for p in F.PRESENTATION_PATHS)
    assert all((F.ROOT / p).is_file() for p in F.PRESENTATION_PATHS)
    on_disk = {p for p in F._git(F.ROOT, 'ls-files', 'frontend/src/app/editing').decode().splitlines()}
    assert on_disk <= F.PRESENTATION_PATHS, sorted(on_disk - F.PRESENTATION_PATHS)       # a new editing file needs a reviewed list change
    assert not F.allowed_path('frontend/src/app/editing/rogue.ts') and not F.allowed_path('frontend/src/app/rogue.tsx')


@pytest.mark.parametrize('path', SOURCES)
def test_one_byte_or_deletion_in_each_owned_source_fails_closed(path, monkeypatch):
    raw = (F.ROOT / path).read_bytes()
    assert F.matches(path, raw)
    assert not F.matches(path, raw + b'\n')
    original = F._read

    def missing(root, p, ref):
        if p == path:
            raise FileNotFoundError(path)
        return original(root, p, ref)
    monkeypatch.setattr(F, '_read', missing)
    assert not F.valid() and not F.exact_blobs_ok()
    assert not C.valid()


def test_manifest_cannot_add_or_drop_a_source_path(monkeypatch):
    original = F._read

    def altered(drop):
        def read(root, p, ref):
            raw = original(root, p, ref)
            if p == F.MANIFEST:
                data = json.loads(raw)
                if drop:
                    data['source_blobs'].pop('app/v2/save_all_commands.py')
                else:
                    data['source_blobs']['app/v2/router.py'] = '0' * 40
                return json.dumps(data).encode()
            return raw
        return read
    for drop in (False, True):
        monkeypatch.setattr(F, '_read', altered(drop))
        assert not F.valid() and not C.valid()


@pytest.mark.parametrize('path', ['app/v2/router.py', 'app/workbook/mutation_csrf.py', 'app/workbook/financing_csrf.py', 'app/workbook/update_service.py',
                                  'app/persistence/projects_repository.py', 'app/v2/save_all_commands_other.py', 'app/v2/opex_commands.py',
                                  'financial_engine/dsra/target.py', 'main_web.py', '.github/workflows/ci_public_job.yml',
                                  'tests/test_save_all_unreviewed_v1.py', 'tests/fin_v2_wsv2_other.py', 'static/react/finco-react.js',
                                  'frontend/src/app/WorkspaceView.tsx', 'docs/react_migration/wsv2_editing/UNREVIEWED.md'])
def test_no_other_path_is_admitted_by_name_prefix_or_pattern(path):
    assert path not in F.OWNED_PATHS and not F.allowed_path(path) and not F.matches(path)


def test_extra_path_outside_every_registered_cohort_is_rejected(monkeypatch):
    assert F.valid()
    for extra_path in ('financial_engine/dsra/unreviewed_reserve_waterfall.py', 'app/v2/router_unreviewed.py', 'app/workbook/mutation_csrf.py'):
        original = F._git

        def extra(root, *args, _p=extra_path, _o=original):
            out = _o(root, *args)
            return out + b'\n' + _p.encode() if args[:2] == ('diff', '--name-only') else out
        monkeypatch.setattr(F, '_git', extra)
        assert not F.valid()
        monkeypatch.setattr(F, '_git', original)


def test_a_non_ancestor_base_is_rejected(monkeypatch):
    monkeypatch.setattr(F, 'BASE', '0' * 40)
    assert not F.valid() and not F.exact_blobs_ok()


def test_save_all_stays_inside_the_approved_contract():
    """Structural proof: the composing module opens exactly one exclusive transaction, never runs the model or touches Run history, and does not
    import the financial engine or the F3 candidate package."""
    import ast
    source = (F.ROOT / 'app/v2/save_all_commands.py').read_text(encoding='utf-8')
    tree = ast.parse(source)
    flat = ast.unparse(tree)
    assert flat.count("conn.execute('BEGIN EXCLUSIVE')") == 1 and flat.count("conn.execute('COMMIT')") == 1
    for forbidden in ('financial_engine', 'finco_core', 'run_project', 'project_runner', 'model_run_history', 'run_intent', 'MAX_ITEMS = 201'):
        assert forbidden not in flat, forbidden
    assert 'MAX_ITEMS = 200' in flat and "'debt.financing.instruments'" in flat
    router = (F.ROOT / 'app/v2/grid_router.py').read_text(encoding='utf-8')
    handler = router[router.index('async def workbook_save_all'):router.index('def _display')]
    assert 'extract_bound_token' in handler and 'validate_csrf_token' in handler and '_resolve(' in handler and 'owner != user.user_id' in handler
    assert 'run_model' not in handler and 'execute_run' not in handler
