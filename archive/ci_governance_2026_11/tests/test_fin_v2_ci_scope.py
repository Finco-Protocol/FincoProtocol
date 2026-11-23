"""Independent negative controls for the finite FIN-V2 CI-diagnostics exact-source cohort inside the integrated FIN-V2 registry."""
import json

import pytest

from tests import fin_v2_cohorts as C
from tests import fin_v2_ci_scope as F


def test_exact_cohort_requires_history_and_never_touches_the_engine(tmp_path):
    assert F.valid() and C.valid()
    assert not F.valid(tmp_path)
    assert F.protected_blobs() == {}
    assert not any(p.startswith(('financial_engine/', 'finco_core/', 'domain/', 'app/')) for p in F.OWNED_PATHS)
    assert not F.matches('financial_engine/valuation/model.py') and not F.matches('unreviewed/new_authority.py')


@pytest.mark.parametrize('path', sorted(F.OWNED_PATHS - {'tests/test_fin_v2_ci_scope.py'}))
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


def test_manifest_cannot_add_or_drop_a_path(monkeypatch):
    original = F._read

    def altered(drop):
        def read(root, p, ref):
            raw = original(root, p, ref)
            if p == F.MANIFEST:
                data = json.loads(raw)
                if drop:
                    data['source_blobs'].pop('tools/ci_v3_calibrate.py')
                else:
                    data['source_blobs']['financial_engine/senior_debt/solver.py'] = '0' * 40
                return json.dumps(data).encode()
            return raw
        return read
    for drop in (False, True):
        monkeypatch.setattr(F, '_read', altered(drop))
        assert not F.valid() and not C.valid()


def test_extra_path_outside_every_registered_cohort_is_rejected(monkeypatch):
    assert F.valid()
    original = F._git

    def extra(root, *args):
        out = original(root, *args)
        return out + b'\nfinancial_engine/valuation/unreviewed.py' if args[:2] == ('diff', '--name-only') else out
    monkeypatch.setattr(F, '_git', extra)
    assert not F.valid()


def test_a_non_ancestor_base_is_rejected(monkeypatch):
    monkeypatch.setattr(F, 'BASE', '0' * 40)
    assert not F.valid() and not F.exact_blobs_ok()
