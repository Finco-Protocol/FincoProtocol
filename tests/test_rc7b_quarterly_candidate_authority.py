"""RC-7B successor governance contract: recognition is exact; approval, admission and release stay separate and closed."""
from __future__ import annotations

import copy

import pytest

import tests.rc7b_quarterly_candidate_authority as A

# The RC-7B exact-content contract describes the RC-7B candidate as merged by PR #320 and carried by main after PR #326 (immutable history). A later,
# separately scoped candidate (RC-7C) has its own contract in tests/rc7c_candidate_successor.py and is not judged against the RC-7B blobs.
RC7B_STATE_REF = "162a3d70ea0cf5b15024ecbe5f7dec33f447a48d"


@pytest.fixture(scope="module")
def facts():
    return A.collect(ref=RC7B_STATE_REF)


def test_inventory_is_exact_and_documents_predecessors():
    assert set(A.RC7B_CANDIDATE_AUTHORITIES) == set(A.RC7B_PREDECESSOR_BLOBS)
    assert len(A.RC7B_CANDIDATE_AUTHORITIES) == 12
    assert all(p.startswith(A.PROTECTED_PREFIXES) for p in A.RC7B_CANDIDATE_AUTHORITIES)
    assert [p for p, b in A.RC7B_PREDECESSOR_BLOBS.items() if b is None] == [
        "financial_engine/financing/quarterly_scope.py", "finco_core/engine/calendar_policy.py"]


def test_current_content_is_recognised_but_not_approved_admitted_or_released(facts):
    assert A.content_violations(facts) == []
    state = A.states(ref=RC7B_STATE_REF)
    assert state["research_isolated"] and state["candidate_content_matches_exactly"]
    assert not state["candidate_is_financially_approved"]
    assert not state["candidate_is_product_admitted"] and not state["candidate_is_released"]
    assert any(v.startswith("FINANCIAL_OWNER_APPROVAL_REQUIRED") for v in A.acceptance_violations(facts))


@pytest.mark.parametrize("mutate", [
    lambda f: f["blobs"].__setitem__("financial_engine/orchestrator.py", "0" * 40),
    lambda f: f["protected_changes"].append("financial_engine/tax/engine.py"),
    lambda f: f["protected_changes"].remove("finco_core/engine/period_engine.py"),
    lambda f: f.__setitem__("activation", "NOT_LITERAL_FALSE"),
    lambda f: f.__setitem__("research_unchanged", False),
    lambda f: f.__setitem__("historical_authorities_unchanged", False),
    lambda f: f.__setitem__("source_head_ancestor", False),
    lambda f: f["predecessor_blobs"].__setitem__("financial_engine/inputs.py", "1" * 40),
    lambda f: f.__setitem__("protected_changes", None),
])
def test_any_defect_breaks_recognition(facts, mutate):
    broken = copy.deepcopy(facts)
    mutate(broken)
    assert A.content_violations(broken) != []


def _record(**overrides):
    record = {"independent_reviewer": "Jane Reviewer", "financial_owner": "Owner Person",
              "reviewed_source_head": A.RC7B_REVIEWED_SOURCE_HEAD, "accepted_blobs": dict(A.RC7B_CANDIDATE_AUTHORITIES),
              "owner_decisions": {d: "ACCEPTED" for d in A.REQUIRED_DECISIONS}, "scope": "CANDIDATE_CONTENT_ONLY",
              "decision_reference": "OWNER-2026-RC7B"}
    record.update(overrides)
    return record


@pytest.mark.parametrize("override", [
    {"independent_reviewer": "Claude"}, {"financial_owner": "GPT agent"}, {"independent_reviewer": ""},
    {"reviewed_source_head": "0" * 40}, {"accepted_blobs": {}}, {"owner_decisions": {"D-01": "ACCEPTED"}},
    {"scope": "RELEASE"}, {"decision_reference": ""},
])
def test_forged_or_incomplete_records_are_rejected(facts, override):
    assert A.acceptance_violations({**facts, "record": _record(**override)}) != []


def test_even_a_valid_record_neither_admits_nor_releases(facts):
    complete = {**facts, "record": _record(release_authorized=True)}
    assert A.acceptance_violations(complete) == []
    assert "PRODUCT_ADMISSION_NOT_GRANTED: quarterly activation is release-closed" in A.admission_violations(complete)
    assert A.release_violations(complete) != []


def test_exemption_is_path_exact_and_never_a_released_authority():
    from finance_integrity_governance import approved_frozen_path
    from model_v2_governance import released_engine_authority_matches
    for path in A.RC7B_CANDIDATE_AUTHORITIES:
        assert A.frozen_scope_exempt(path, ref=RC7B_STATE_REF)
        assert not released_engine_authority_matches(path)
        assert not approved_frozen_path(path) or path in ("financial_engine/inputs.py",)
    for path in ("financial_engine/tax/engine.py", "finco_core/tax/engine.py", "app/workbook/registry.py"):
        assert not A.frozen_scope_exempt(path)
