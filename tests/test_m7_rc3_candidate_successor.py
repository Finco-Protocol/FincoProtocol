"""Negative and fail-closed tests for the INERT M7 RC-3 candidate successor (see tests/m7_rc3_candidate_successor.py)."""
import copy
import json
import subprocess
from pathlib import Path

import pytest

import tests.m7_rc3_candidate_successor as S
from tests import ppa01_candidate_authority as ppa01

ROOT = Path(__file__).resolve().parent.parent
GOOD_RECORD = {
    "independent_reviewer": "Jane Example (independent financial reviewer)", "reviewed_source_head": S.M7_REVIEWED_SOURCE_HEAD,
    "accepted_blobs": dict(S.M7_RC3_CANDIDATE_AUTHORITIES), "scope": "CANDIDATE_CONTENT_ONLY", "activation_approved": False,
    "derived_from_manifest": False, "decision_reference": "SYNTHETIC-TEST-REFERENCE",
}


@pytest.fixture(scope="module")
def facts():
    facts = S.collect()
    # RC-3 C2 coexistence: the exact PPA-01 candidate (tests/ppa01_candidate_authority.py) is a SEPARATE, independently exact slice. It is not an M7
    # change, so it is excluded from the M7 frozen-change facts ONLY while its own three blobs are exactly the reviewed ones; a modified, partial or
    # substituted PPA-01 slice stays in the facts and makes the M7 content check fail. Neither slice confers approval on the other.
    if ppa01.candidate_content_matches_exactly():
        facts["frozen_changes"] = [p for p in facts["frozen_changes"] if p not in ppa01.PPA01_CANDIDATE_AUTHORITIES]
    return facts


# Immutable main after PR #313: it carries exactly the integrated M7 candidate and the PPA-01 candidate. The validator-mutation tests below need a
# KNOWN-GOOD fact set; building it from today's moving integration HEAD makes them fail before any mutation is tried. The LIVE HEAD content is
# still judged by test_the_integrated_content_is_exactly_the_eleven_reviewed_blobs (unchanged, uses ``facts``).
KNOWN_GOOD_MAIN = "5be8c4b149712dd39b38b54c6fabcf3fcf47ef0d"


@pytest.fixture(scope="module")
def known_good_facts():
    assert subprocess.run(["git", "merge-base", "--is-ancestor", KNOWN_GOOD_MAIN, "HEAD"], cwd=ROOT).returncode == 0
    good = S.collect(KNOWN_GOOD_MAIN)
    assert ppa01.candidate_content_matches_exactly(ref=KNOWN_GOOD_MAIN)
    good["frozen_changes"] = [p for p in good["frozen_changes"] if p not in ppa01.PPA01_CANDIDATE_AUTHORITIES]
    assert S.content_violations(good) == []                                  # the baseline really IS the reviewed candidate
    return good


def _bad(facts, fn, **changes):
    mutated = copy.deepcopy(facts)
    mutated.update(changes)
    problems = fn(mutated)
    assert problems, changes
    return problems


def test_the_integrated_content_is_exactly_the_eleven_reviewed_blobs(facts):
    observed = copy.deepcopy(facts)
    from rc7b_quarterly_candidate_authority import RC7B_CANDIDATE_AUTHORITIES
    from quarterly_candidate_recognition import candidate_blobs, candidate_recognized
    if candidate_recognized():
        # A release-closed quarterly candidate is recognised (the RC-7B candidate merged by PR #320, or the RC-7C candidate; exact blobs, merge
        # ancestry, closed flag): it may replace exactly the two shared M7 blobs and add the other ten listed paths. Each superseded path must be
        # EXACTLY the recognised candidate blob; the remaining nine M7 blobs are still judged byte-for-byte against the reviewed M7 pins.
        shared = sorted(p for p in S.M7_RC3_CANDIDATE_AUTHORITIES if p in RC7B_CANDIDATE_AUTHORITIES)
        assert shared == ["financial_engine/adapters/project_inputs.py", "financial_engine/orchestrator.py"]
        for path in shared:
            assert observed["blobs"][path] == candidate_blobs()[path]
            observed["blobs"][path] = S.M7_RC3_CANDIDATE_AUTHORITIES[path]
        # the ten non-M7 quarterly paths and the separately recognised PPA-01 slice are not M7 changes; the two shared M7 paths stay listed
        separate = (set(RC7B_CANDIDATE_AUTHORITIES) - set(S.M7_RC3_CANDIDATE_AUTHORITIES)) | set(ppa01.PPA01_CANDIDATE_AUTHORITIES)
        assert all(ppa01.blob(p) == pin for p, pin in ppa01.PPA01_CANDIDATE_AUTHORITIES.items())
        observed["frozen_changes"] = [p for p in observed["frozen_changes"] if p not in separate]
    assert S.content_violations(observed) == []
    assert len(S.M7_RC3_CANDIDATE_AUTHORITIES) == 11


def test_the_authorities_come_from_the_source_head_not_from_the_manifest(facts):
    manifest = json.loads(facts["manifest_text"])
    assert manifest["protected_blobs"] == S.M7_RC3_CANDIDATE_AUTHORITIES            # equal by content, independent by construction
    assert facts["source_blobs"] == S.M7_RC3_CANDIDATE_AUTHORITIES


def test_there_is_no_acceptance_record_so_the_approval_gate_is_open(facts):
    assert facts["record"] is None
    assert any("APPROVAL_REQUIRED" in p for p in S.acceptance_violations(facts))
    assert S.current_acceptance_granted() is False


@pytest.mark.parametrize("path", sorted(S.M7_RC3_CANDIDATE_AUTHORITIES))
def test_every_blob_change_or_omission_is_rejected(facts, path):
    assert any(path in p for p in _bad(facts, S.content_violations, blobs={**facts["blobs"], path: "1" * 40}))
    _bad(facts, S.content_violations, blobs={k: v for k, v in facts["blobs"].items() if k != path})
    _bad(facts, S.content_violations, source_blobs={**facts["source_blobs"], path: "2" * 40})        # wrong source head content


def test_extra_unlisted_and_partial_changes_are_rejected(known_good_facts):
    facts = known_good_facts
    _bad(facts, S.content_violations, blobs={**facts["blobs"], "financial_engine/unreviewed.py": "3" * 40})
    for path in ("financial_engine/cfads.py", "finco_core/inputs/_models.py", "domain/revenue/plan.py", "financial_engine/tax/engine.py"):
        assert any(path in p for p in _bad(facts, S.content_violations, frozen_changes=[*facts["frozen_changes"], path]))
    only_some = facts["frozen_changes"][:-1]
    assert any("partial slice" in p for p in _bad(facts, S.content_violations, frozen_changes=only_some))
    _bad(facts, S.content_violations, source_head_ancestor=False)


def test_missing_or_malformed_facts_never_authorise(facts):
    assert S.content_violations({}) and S.acceptance_violations({})
    for key in facts:
        assert S.acceptance_violations({k: v for k, v in facts.items() if k != key}), key


def test_a_complete_independent_record_is_required_and_each_defect_is_rejected(known_good_facts):
    accepted = copy.deepcopy(known_good_facts)
    accepted["record"] = copy.deepcopy(GOOD_RECORD)
    assert S.acceptance_violations(accepted) == []                       # only a synthetic record in a synthetic fact set
    defects = {
        "independent_reviewer": ["", None, "Claude", "the AI agent", "self-review by author"],
        "reviewed_source_head": ["0" * 40, "", None],
        "accepted_blobs": [{**GOOD_RECORD["accepted_blobs"], "financial_engine/bess.py": "4" * 40}, {}, None],
        "scope": ["PRODUCTION_ACTIVATION", None],
        "activation_approved": [True, None],
        "derived_from_manifest": [True, None],
        "decision_reference": ["", None],
    }
    for key, values in defects.items():
        for value in values:
            mutated = copy.deepcopy(accepted)
            mutated["record"][key] = value
            assert S.acceptance_violations(mutated), (key, value)
    for key in GOOD_RECORD:
        mutated = copy.deepcopy(accepted)
        del mutated["record"][key]
        assert S.acceptance_violations(mutated), key
    mutated = copy.deepcopy(accepted)
    mutated["record"] = "approved"
    assert S.acceptance_violations(mutated)


def test_a_valid_record_never_covers_changed_content(facts):
    accepted = copy.deepcopy(facts)
    accepted["record"] = copy.deepcopy(GOOD_RECORD)
    path = "financial_engine/orchestrator.py"
    accepted["blobs"][path] = "5" * 40                                    # one additional byte invalidates the successor
    assert any(path in p for p in S.acceptance_violations(accepted))


def test_the_successor_is_not_wired_into_any_guard_and_touches_no_historical_pin_map():
    for name in ("model_v2_governance.py", "finance_integrity_governance.py", "test_finance_integrity_governance.py",
                 "test_wf07_revenue_governance.py", "test_ci_acceptance.py", "radar_authority_governance.py"):
        assert "m7_rc3_candidate_successor" not in (ROOT / "tests" / name).read_text(encoding="utf-8"), name
    # The historical pin maps and the central guards stay byte-identical to the RC-2 checkpoint. Two central guards were extended ADDITIVELY by RC-3 C2
    # to recognise the exact PPA-01 candidate (finance_integrity_governance.strictly_frozen_changes, test_ci_acceptance's slice check): for those the
    # contract is that every top-level literal (pin maps, allow-lists, constants) is unchanged, and neither imports the M7 successor (checked above).
    import ast

    def literals(text):
        return [ast.dump(node) for node in ast.parse(text).body if isinstance(node, (ast.Assign, ast.AnnAssign))]

    for name in ("model_v2_governance.py", "radar_authority_governance.py"):
        blob = subprocess.run(["git", "rev-parse", f"{S.RC2_CHECKPOINT}:tests/{name}"], cwd=ROOT, capture_output=True, text=True,
                              check=True).stdout.strip()
        assert subprocess.run(["git", "hash-object", f"tests/{name}"], cwd=ROOT, capture_output=True, text=True,
                              check=True).stdout.strip() == blob, name
    for name in ("finance_integrity_governance.py", "test_ci_acceptance.py"):
        historical = subprocess.run(["git", "show", f"{S.RC2_CHECKPOINT}:tests/{name}"], cwd=ROOT, capture_output=True, text=True, check=True).stdout
        assert literals((ROOT / "tests" / name).read_text(encoding="utf-8")) == literals(historical), name
    from app.workbook.bess_config import ACTIVATION_ENABLED
    assert ACTIVATION_ENABLED is False
