"""Independent negative controls for the finite FIN-V2-3 successor cohort."""
import json
import subprocess

import pytest
from tests import fin_v2_3_scope as F
from tests import wf04_scope as WF04


def test_exact_cohort_requires_history_and_does_not_activate_native(tmp_path):
    assert F.valid()
    assert not F.valid(tmp_path)
    assert not F.matches('financial_engine/native_v11/config.py')
    assert not F.matches('app/persistence/workspace_repository.py')
    assert not F.matches('unreviewed/new_financial_authority.py')


@pytest.mark.parametrize('path', sorted(F.OWNED_PATHS))
def test_one_byte_or_deletion_in_each_owned_source_fails_closed(path,monkeypatch):
    raw=(F.ROOT/path).read_bytes()
    assert F.matches(path,raw)
    assert not F.matches(path,raw+b'\n')
    original=F._read
    def missing(root,p,ref):
        if p==path:raise FileNotFoundError(path)
        return original(root,p,ref)
    monkeypatch.setattr(F,'_read',missing)
    assert not F.valid()


def test_manifest_cannot_add_an_unreviewed_source_path(monkeypatch):
    original=F._read
    def altered(root,p,ref):
        raw=original(root,p,ref)
        if p==F.MANIFEST:
            data=json.loads(raw);data['source_blobs']['financial_engine/senior_debt/solver.py']='0'*40
            return json.dumps(data).encode()
        return raw
    monkeypatch.setattr(F,'_read',altered)
    assert not F.valid()


def test_native_and_historical_financial_authorities_are_not_rewritten():
    paths=['financial_engine/senior_debt/solver.py','financial_engine/native_v10/fk_v10_manifest.json',
           'financial_engine/native_v11/fk_v11_stage3_manifest.json','financial_engine/shl/maturity_authority.py',
           'app/persistence/workspace_repository.py','app/persistence/run_history_repository.py']
    for path in paths:
        before=subprocess.check_output(['git','show',F.BASE+':'+path],cwd=F.ROOT)
        current=(F.ROOT/path).read_bytes()
        # The ONE later, separately governed exception: the Owner-authorised WF-04 additive hunk in v2_atomic_run_commit (tests/wf04_scope.py pins the
        # exact blob; tests/test_wf04_scope.py proves the hunk is the only change). Any other byte, or any other path, still has to equal the base.
        if path=='app/persistence/workspace_repository.py' and WF04.matches(path,current):continue
        assert current==before


@pytest.mark.parametrize('path', sorted(F.INTEGRATED_DEPENDENCIES))
def test_integrated_pr390_dependency_rejects_one_byte_and_missing_path(path, monkeypatch):
    assert F.valid()
    original = F._read
    def mutated(root, p, ref):
        data = original(root, p, ref)
        return data + b'\n' if p == path else data
    monkeypatch.setattr(F, '_read', mutated)
    assert not F.valid()
    def missing(root, p, ref):
        if p == path:
            raise FileNotFoundError(path)
        return original(root, p, ref)
    monkeypatch.setattr(F, '_read', missing)
    assert not F.valid()


def test_extra_path_outside_integrated_exact_cohort_is_rejected(monkeypatch):
    assert F.valid()
    original = F._git
    def added_path(root, *args):
        data = original(root, *args)
        if args[:3] == ('diff', '--name-only', F.INTEGRATION_MAIN):
            return data + b'financial_engine/unreviewed_new_authority.py\n'
        return data
    monkeypatch.setattr(F, '_git', added_path)
    assert not F.valid()


def test_integration_parent_must_be_actual_merged_rcm_source(monkeypatch):
    assert F.valid()
    monkeypatch.setattr(F, "INTEGRATION_MAIN", F.BASE)
    # Reverting to the historical base cannot silently accept the newly
    # merged React source paths, which are outside FIN-V2-3's owned cohort.
    assert not F.valid()
