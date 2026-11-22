"""Independent negative controls for the finite FIN-V2-R1 (Reserve R1) exact-source cohort and the FIN-V2 cohort registry."""
import json
import subprocess

import pytest

from tests import fin_v2_cohorts as C
from tests import fin_v2_r1_scope as F
from tests import wf04_scope as WF04


def test_exact_cohort_requires_history_and_does_not_activate_native(tmp_path):
    assert F.valid() and C.valid()
    assert not F.valid(tmp_path)
    assert not F.matches('financial_engine/native_v11/config.py')
    assert not F.matches('app/persistence/workspace_repository.py')
    assert not F.matches('unreviewed/new_financial_authority.py')
    assert not C.matches('financial_engine/native_v11/config.py') and not C.matches('unreviewed/new_financial_authority.py')


def test_the_protected_cohort_is_exactly_the_three_reserve_paths():
    assert set(F.protected_blobs()) == {'financial_engine/dsra/forward_coverage.py', 'financial_engine/dsra/reserve_authority.py',
                                        'financial_engine/dsra/target.py'}
    assert F.protected_blobs() == {p: b for p, b in C.protected_blobs().items() if p in F.OWNED_PATHS}


@pytest.mark.parametrize('path', sorted(F.OWNED_PATHS - {'tests/test_fin_v2_r1_scope.py'}))
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
                    data['source_blobs'].pop('financial_engine/dsra/target.py')
                else:
                    data['source_blobs']['financial_engine/senior_debt/solver.py'] = '0' * 40
                return json.dumps(data).encode()
            return raw
        return read
    for drop in (False, True):
        monkeypatch.setattr(F, '_read', altered(drop))
        assert not F.valid() and not C.valid()


def test_native_and_historical_financial_authorities_are_not_rewritten():
    paths = ['financial_engine/senior_debt/solver.py', 'financial_engine/native_v10/fk_v10_manifest.json',
             'financial_engine/native_v11/fk_v11_stage3_manifest.json', 'financial_engine/shl/maturity_authority.py',
             'financial_engine/shareholder_waterfall/model.py', 'financial_engine/financing/project.py',
             'app/persistence/workspace_repository.py', 'app/persistence/run_history_repository.py']
    for path in paths:
        before = subprocess.check_output(['git', 'show', F.BASE + ':' + path], cwd=F.ROOT)
        data = (F.ROOT / path).read_bytes()
        from tests import fin_v2_wsv2_scope as WS2
        from tests import wf03_lifecycle_scope as WF03
        # The later, separately governed exception: the Owner-authorised WF-04 additive hunk in v2_atomic_run_commit (tests/wf04_scope.py pins the exact blob).
        if path == 'app/persistence/workspace_repository.py' and WF04.matches(path, data):
            continue
        assert data == before or WS2.matches(path, data) or (path in WF03.D029_APPROVED_PATHS and WF03.matches(path, data)), path   # WS-2 exact blob, or the WF-03 exact blob


def test_extra_path_outside_the_exact_cohort_is_rejected(monkeypatch):
    assert F.valid()
    original = F._git

    def extra(root, *args):
        out = original(root, *args)
        return out + b'\nfinancial_engine/dsra/unreviewed_reserve_waterfall.py' if args[:2] == ('diff', '--name-only') else out
    monkeypatch.setattr(F, '_git', extra)
    assert not F.valid()


def test_a_non_ancestor_base_is_rejected(monkeypatch):
    monkeypatch.setattr(F, 'BASE', '0' * 40)
    assert not F.valid() and not F.exact_blobs_ok()


def test_the_registry_never_admits_a_path_no_cohort_owns(monkeypatch):
    assert C.valid() and not C.matches('financial_engine/dsra/unreviewed_reserve_waterfall.py')
    original = C._git

    def extra(root, *args):
        out = original(root, *args)
        return out + b'\nfinancial_engine/dsra/unreviewed_reserve_waterfall.py' if args[:2] == ('diff', '--name-only') else out
    monkeypatch.setattr(C, '_git', extra)
    assert not C.valid()


def test_reserve_authority_stays_closed_to_activation():
    text = (F.ROOT / 'financial_engine/dsra/reserve_authority.py').read_text(encoding='utf-8')
    assert 'waterfall' not in text.lower() or 'not' in text.lower()      # prose only; the authority never funds a reserve
    for forbidden in ('financial_engine.shareholder_waterfall', 'run_operating_model', 'save_project(', 'run_history'):
        assert forbidden not in text, forbidden
