"""Opt-in F3 authority has no blanket core/engine exemption."""
from pathlib import Path
import hashlib
import subprocess

import pytest
import model_v2_governance as governance
from finance_integrity_governance import approved_frozen_path, strictly_frozen_changes, unapproved_engine_changes
from tests.test_financing_f3_governance import git


PATHS = {
    'finco_core/inputs/multisenior.py', 'finco_core/inputs/_models.py',
    'finco_core/inputs/serialization.py', 'financial_engine/financing/multisenior.py',
    'financial_engine/financing/project.py', 'financial_engine/financing/generic_product_policy.py',
    'financial_engine/senior_debt/project_adapter.py',
}


def test_only_exact_seven_paths_at_their_pinned_content_are_authorized():
    assert set(governance.F3_2_4_FINANCING_AUTHORITIES) == PATHS
    assert strictly_frozen_changes(list(PATHS)) == []
    from rc7b_quarterly_candidate_authority import RC7B_CANDIDATE_AUTHORITIES
    from rc7b_postmerge_successor import superseded as superseded_by_gate_r
    for path, blob in governance.F3_2_4_FINANCING_AUTHORITIES.items():
        if superseded_by_gate_r(path, repo=governance.REPO):
            # RC-7B: only under an ACTIVE Gate R (signed record + authentic independent review + exact twelve blobs) does a superseding candidate
            # replace the historical pin. Release-closed candidate only: never the released pin, never an approved frozen path.
            assert git(governance.REPO, 'rev-parse', f'HEAD:{path}') == RC7B_CANDIDATE_AUTHORITIES[path]
            assert not governance.released_engine_authority_matches(path)
            continue
        current_blob = governance.F3_5_A_JUNIOR_AUTHORITIES.get(path,
            governance.WF07_REVENUE_AUTHORITIES.get(path, governance.WF04_NUMERIC_PRECISION_AUTHORITIES.get(path, blob)))
        assert git(governance.REPO, 'rev-parse', f'HEAD:{path}') == current_blob
        assert governance.released_engine_authority_matches(path)


@pytest.mark.parametrize('path', sorted(PATHS))
def test_any_edit_to_a_pinned_file_loses_approval(path, tmp_path, monkeypatch):
    repo = tmp_path / 'synthetic'
    repo.mkdir()
    git(repo, 'init')
    git(repo, 'config', 'core.autocrlf', 'false')
    git(repo, 'config', 'user.name', 'Synthetic Reviewer')
    git(repo, 'config', 'user.email', 'noreply@users.noreply.github.com')
    # Known-good baseline = the exact released blob object pinned for this path (immutable), NOT whatever the current integration HEAD carries.
    # A later integration candidate legitimately changes HEAD; the live HEAD authority is judged by test_only_exact_seven_paths_* above.
    pinned = governance.F3_5_A_JUNIOR_AUTHORITIES.get(path, governance.WF07_REVENUE_AUTHORITIES.get(
        path, governance.WF04_NUMERIC_PRECISION_AUTHORITIES.get(path, governance.F3_2_4_FINANCING_AUTHORITIES[path])))
    original = subprocess.run(['git', '-C', str(governance.REPO), 'cat-file', 'blob', pinned], check=True, capture_output=True).stdout
    assert hashlib.sha1(b'blob %d\0' % len(original) + original).hexdigest() == pinned        # the fixture IS the pinned object
    target = repo / path
    target.parent.mkdir(parents=True)
    target.write_bytes(original)
    git(repo, 'add', path)
    git(repo, 'commit', '-m', 'Synthetic pinned content')
    assert governance.released_engine_authority_matches(path, repo=repo)
    target.write_bytes(original + b'\n# Unapproved change\n')
    git(repo, 'add', path)
    git(repo, 'commit', '-m', 'Synthetic changed content')
    assert not governance.released_engine_authority_matches(path, repo=repo)
    assert governance.released_engine_authority_matches(path, repo=repo, ref='HEAD~1')
    monkeypatch.setattr(governance, 'REPO', Path(repo))
    if path.startswith('finco_core/'):
        assert strictly_frozen_changes([path]) == [path]
    else:
        assert unapproved_engine_changes([path]) == [path]
    assert not approved_frozen_path(path)


@pytest.mark.parametrize('path', [
    'financial_engine/orchestrator.py.bak', 'financial_engine/tax/engine.py',
    'financial_engine/senior_debt/solver.py', 'finco_core/inputs/accounting.py',
    'finco_core/inputs/multisenior.py/extra', 'finco_core/inputs/other_new.py',
    'finco_radar/engine.py',
])
def test_unrelated_financial_and_product_paths_remain_frozen(path):
    assert not governance.released_engine_authority_matches(path)
    assert not governance.approved_by_active_model_v2_scope(path)
    if path.startswith(('finco_core/', 'finco_radar/')):
        assert strictly_frozen_changes([path]) == [path]
