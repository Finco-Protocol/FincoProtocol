"""The Finance Integrity governance contract protects unrelated engine modules."""
from __future__ import annotations

from tests.rc3_authority_states import (
    INTEGRATED_RELEASE_CLOSED_CANDIDATE, M7_CANDIDATE, authority_state, release_closed_violations,
)
from finance_integrity_governance import (
    APPROVED_FINANCE_INTEGRITY_ENGINE_PATHS as APPROVED,
    strictly_frozen_changes,
    unapproved_engine_changes,
)


def test_approved_engine_paths_are_allowed():
    # Approved paths whose content is a RELEASED authority are allowed. The approved-list paths that now carry the integrated, RELEASE-CLOSED
    # M7 candidate (PR #284) are exactly the ones the released-authority guard still rejects: candidate presence is not release approval.
    candidate = sorted(p for p in APPROVED if p in M7_CANDIDATE)
    assert candidate == ["financial_engine/adapters/project_inputs.py", "financial_engine/orchestrator.py"]
    # RC-7B Gate R: paths superseded by the twelve-blob quarterly candidate are recognised ONLY while a complete, authentic Gate R is active; they are
    # then a release-closed candidate (never released). With no Gate R this set is empty and every original expectation below applies unchanged.
    from rc7b_postmerge_successor import superseded as superseded_by_gate_r
    from rc7b_postmerge_successor import without_superseded as without_gate_r_superseded
    superseded = {p for p in APPROVED if superseded_by_gate_r(p)}
    assert without_gate_r_superseded(unapproved_engine_changes(sorted(APPROVED))) == sorted(set(candidate) - superseded)
    assert without_gate_r_superseded(unapproved_engine_changes(sorted(set(APPROVED) - set(candidate)))) == []
    for path in candidate:
        assert authority_state(path) == INTEGRATED_RELEASE_CLOSED_CANDIDATE
    for path in set(APPROVED) - set(candidate):
        assert (authority_state(path) == INTEGRATED_RELEASE_CLOSED_CANDIDATE) == (path in superseded)
    assert release_closed_violations() == []


def test_unrelated_engine_modules_stay_protected():
    for path in (
        "financial_engine/tax/atad.py",
        "financial_engine/shl/waterfall.py",
        "financial_engine/operating/model.py",
        "financial_engine/sponsor_returns/model.py",
    ):
        assert unapproved_engine_changes([path]) == [path]


def test_core_and_radar_have_no_exception():
    assert strictly_frozen_changes(["finco_core/tax/engine.py"]) == ["finco_core/tax/engine.py"]
    assert strictly_frozen_changes(["finco_radar/x.py"]) == ["finco_radar/x.py"]


def test_this_branch_stays_within_the_governance_contract():
    from rc7b_postmerge_successor import without_superseded as without_gate_r_superseded
    # RC-7B: paths superseded by an ACTIVE Gate R (release-closed candidate, never released) are removed from the result; with no Gate R it is identity.
    assert without_gate_r_superseded(unapproved_engine_changes()) == []
    assert strictly_frozen_changes() == []


def test_allow_list_entries_exist():
    from finance_integrity_governance import REPO
    for path in APPROVED:
        assert (REPO / path).is_file(), path


def test_stream_guard_exemption_covers_only_allow_listed_engine_files():
    """approved_frozen_path is what the per-stream 'frozen namespace' guards consult."""
    from finance_integrity_governance import approved_frozen_path

    candidate = {p for p in APPROVED if p in M7_CANDIDATE}
    from rc7b_postmerge_successor import superseded as superseded_by_gate_r
    superseded = {p for p in APPROVED if superseded_by_gate_r(p)}          # empty unless a complete, authentic Gate R is active
    assert all(approved_frozen_path(path) for path in set(APPROVED) - candidate - superseded)
    assert not any(approved_frozen_path(path) for path in superseded)     # a Gate R candidate is never a released exemption
    # the release-closed M7 candidate is NOT a released exemption: stream guards must keep treating it as not-approved
    assert candidate and not any(approved_frozen_path(path) for path in candidate)
    assert all(authority_state(path) == INTEGRATED_RELEASE_CLOSED_CANDIDATE for path in candidate)
    for path in (
        "financial_engine/tax/atad.py",        # engine module NOT on the allow-list
        "finco_core/tax/engine.py",            # strictly frozen
        "finco_radar/venues/registry.py",
        "app/services/anything.py",
    ):
        assert not approved_frozen_path(path), path


def test_candidate_state_never_widens_the_released_allow_list():
    """The M7 candidate does not enter APPROVED_FINANCE_INTEGRITY_ENGINE_PATHS and unreviewed engine/core changes stay rejected."""
    assert "financial_engine/bess.py" not in APPROVED
    for path in ("financial_engine/bess.py", "financial_engine/new_unreviewed.py", "financial_engine/senior_debt/other.py"):
        assert unapproved_engine_changes([path]) == [path]
    assert strictly_frozen_changes(["finco_core/inputs/bess_native.py", "finco_core/inputs/unrelated.py"]) == [
        "finco_core/inputs/bess_native.py", "finco_core/inputs/unrelated.py"]
