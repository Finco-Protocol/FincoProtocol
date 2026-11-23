"""Negative controls for the finite PR #394 staging-correction exact-source cohort and its place in the FIN-V2 cohort registry."""
import json

import pytest

from tests import fin_v2_cohorts as C
from tests import fin_v2_pr394_corr_scope as F


def test_the_cohort_is_registered_valid_and_owns_no_financial_namespace(tmp_path):
    assert F.__name__ in C.COHORT_MODULES and F in C.cohorts()
    assert F.valid() and C.valid()
    assert not F.valid(tmp_path)
    assert F.protected_blobs() == {}
    assert not any(p.startswith(('financial_engine/', 'finco_core/', 'domain/', '.github/', 'app/workbook/', 'app/persistence/', 'app/runtime/'))
                   for p in F.OWNED_PATHS)
    assert not F.matches('financial_engine/dsra/target.py') and not C.matches('unreviewed/new_financial_authority.py')


def test_the_owned_set_is_exactly_the_one_protected_service_the_two_test_modules_and_the_cohort_itself():
    assert F.OWNED_PATHS == frozenset((
        'app/services/run_intent_service.py', 'tests/fin_v2_pr394_corr_scope.py', 'tests/test_fin_v2_pr394_corr_scope.py',
        'tests/test_pr394_f4_run_failure_reason_v1.py', 'tests/test_pr394_staging_corrections_v1.py'))
    assert [p for p in F.OWNED_PATHS if p.startswith('app/')] == ['app/services/run_intent_service.py']


@pytest.mark.parametrize('path', sorted(F.OWNED_PATHS - {'tests/test_fin_v2_pr394_corr_scope.py'}))
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
                    data['source_blobs'].pop('app/services/run_intent_service.py')
                else:
                    data['source_blobs']['app/v2/router.py'] = '0' * 40
                return json.dumps(data).encode()
            return raw
        return read
    for drop in (False, True):
        monkeypatch.setattr(F, '_read', altered(drop))
        assert not F.valid() and not C.valid()


@pytest.mark.parametrize('path', ['app/v2/router.py', 'app/runtime/model_execution.py', 'app/persistence/run_intent_repository.py',
                                  'app/persistence/run_history_repository.py', 'app/services/run_service.py', 'app/workbook/mutation_csrf.py',
                                  'app/services/run_intent_service_other.py', 'financial_engine/dsra/target.py', 'main_web.py',
                                  '.github/workflows/ci_public_job.yml', 'tests/test_pr394_unreviewed_v1.py', 'tests/fin_v2_pr394_other.py',
                                  'static/react/finco-react.js', 'frontend/src/app/WorkspaceView.tsx'])
def test_no_other_path_is_admitted_by_name_prefix_or_pattern(path):
    assert path not in F.OWNED_PATHS and not F.allowed_path(path) and not F.matches(path)


def test_extra_path_outside_every_registered_cohort_is_rejected(monkeypatch):
    assert F.valid()
    for extra_path in ('financial_engine/dsra/unreviewed_reserve_waterfall.py', 'app/v2/router_unreviewed.py', 'app/services/run_service.py'):
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


def test_the_f4_change_stays_inside_the_d029_service_contract():
    """Structural proof beside the behavioural ones: the service still imports only the repository functions it did, adds no route / SQL / token
    handling, and the lifecycle functions keep their released signatures."""
    import ast
    import inspect
    from app.services import run_intent_service as ri
    tree = ast.parse((F.ROOT / 'app/services/run_intent_service.py').read_text(encoding='utf-8'))
    source = ast.unparse(tree)
    for forbidden in ('sqlite3', 'execute(', 'INSERT ', 'UPDATE ', 'csrf', 'validate_mutation_token', 'request.', 'os.environ', 'open('):
        assert forbidden not in source, forbidden
    assert list(inspect.signature(ri.mark_failed).parameters) == ['reservation', 'code']
    assert list(inspect.signature(ri.payload).parameters) == ['decision', 'outcome']
    assert ri.OUTCOMES == ('COMMITTED', 'REPLAYED', 'IN_PROGRESS', 'FAILED', 'CONFLICT', 'HISTORY_UNAVAILABLE', 'INVALID', 'EXPIRED', 'REFUSED', 'UNAVAILABLE')
    assert ri.RELEASE_POLICY.enabled is False and ri.RELEASE_POLICY.failed_retry_behavior == 'NEW_INTENT_REQUIRED'
