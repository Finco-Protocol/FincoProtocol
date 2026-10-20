"""The V9-P2a / OD-R successor proposal describes exact bytes only and grants nothing."""
from __future__ import annotations

from pathlib import Path

from tests import v9p2a_odr_candidate_proposal as proposal

ROOT = Path(__file__).resolve().parent.parent


def test_proposal_names_exactly_the_changed_protected_paths():
    assert set(proposal.CANDIDATE_BLOBS) == set(proposal.PREDECESSOR_BLOBS)
    for path, before in proposal.PREDECESSOR_BLOBS.items():
        assert proposal.blob(path, proposal.PREDECESSOR_MAIN) == before
    assert proposal.content_matches_proposal()


def test_proposal_grants_no_approval_and_is_not_wired_into_any_guard():
    states = proposal.states()
    for key in ("protected_content_approved", "independent_financial_review",
                "wired_into_current_authority_guards", "product_activation", "financial_release"):
        assert states[key] is False
    for guard in sorted((ROOT / "tests").glob("*.py")):
        if guard.name.startswith(("test_v9p2a_odr_candidate_proposal", "v9p2a_odr_candidate_proposal")):
            continue
        assert "v9p2a_odr_candidate_proposal" not in guard.read_text(encoding="utf-8", errors="replace"), guard.name
