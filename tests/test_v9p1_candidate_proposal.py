from copy import deepcopy

import pytest

from tests import v9p1_candidate_proposal as proposal


def facts():
    return {"base": proposal.BASE, "base_is_ancestor": True, "immutable_rc7c_recognized": True,
            "blobs": dict(proposal.PROPOSAL), "application_and_protected_changes": list(proposal.PROPOSAL),
            "historical_guards_unchanged": True, "quarterly_activation": False}


def test_exact_two_path_proposal_is_not_a_release_or_effective_exemption():
    assert proposal.validate_facts(facts())
    assert not proposal.RELEASE_APPROVED
    assert not proposal.FINANCIAL_OWNER_APPROVED
    assert not proposal.INDEPENDENT_CONTENT_ACCEPTED


@pytest.mark.parametrize("path", list(proposal.PROPOSAL))
def test_changed_blob_or_missing_path_is_rejected(path):
    value = facts()
    value["blobs"][path] = "0" * 40
    assert not proposal.validate_facts(value)
    del value["blobs"][path]
    assert not proposal.validate_facts(value)


@pytest.mark.parametrize("path", ["financial_engine/orchestrator.py", "finco_core/inputs/_models.py",
                                  "domain/revenue/revenue_config.py", "app/v2/router.py"])
def test_unrelated_engine_core_domain_or_writer_changes_are_rejected(path):
    value = facts()
    value["application_and_protected_changes"].append(path)
    assert not proposal.validate_facts(value)


@pytest.mark.parametrize("key,value", [
    ("base", "0" * 40), ("base_is_ancestor", False),
    ("immutable_rc7c_recognized", False), ("historical_guards_unchanged", False),
    ("quarterly_activation", True), ("quarterly_activation", None),
])
def test_missing_provenance_changed_historical_authority_and_activation_fail_closed(key, value):
    data = facts()
    data[key] = value
    assert not proposal.validate_facts(data)


def test_missing_facts_are_not_an_authorization():
    assert not proposal.validate_facts({})
    assert not proposal.validate_facts(None)
    bad = facts()
    bad["application_and_protected_changes"] = None
    assert not proposal.validate_facts(bad)
    for key in facts():
        value = deepcopy(facts())
        del value[key]
        assert not proposal.validate_facts(value)


def test_actual_worktree_matches_only_the_unapproved_proposal():
    assert proposal.validate_facts(proposal.collect_worktree())
