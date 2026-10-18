"""RC-7B matched 3/3 successor governance contract - exact-content RECOGNITION only. Not an approval, not a release.

The RC-7B integration legitimately changes twelve protected financial paths (financial_engine / finco_core). Following the
RC-3 C2 PPA-01 precedent, this module keeps the questions apart and never collapses them into one boolean:

``research_isolated``                    the PR #313 research package under ``tools/quarterly_research/`` is byte-identical to the
                                        predecessor (research stays an independent validation reference, never production).
``candidate_content_matches_exactly``   the tree carries EXACTLY the twelve reviewed RC-7B blobs, no other protected path differs from the
                                        immutable predecessor (main ``5be8c4b1``), the reviewed source head is an ancestor, the historical
                                        authority maps are byte-identical and ``quarterly_frequency_config.ACTIVATION_ENABLED`` is a literal
                                        ``False``. This is a statement about bytes; it lets the frozen-scope gates tell "the candidate" from "an
                                        unauthorized change".
``candidate_is_financially_approved``   a SEPARATE committed record ``docs/model_v2/RC7B_QUARTERLY_FINANCIAL_ACCEPTANCE.json`` names a human
                                        independent reviewer AND the financial owner, the reviewed source head, the exact blobs and the owner
                                        decisions D-01..D-12. It does not exist: the answer is False.
``candidate_is_product_admitted``       approval AND the activation flag opened by a separate change. Unavailable while closed.
``candidate_is_released``               admission AND an explicit release authorization in the record. Unavailable.

The historical pin maps in ``tests/model_v2_governance.py`` (Developer Economics, F3, WF04, WF07, Revenue V2/V3, F3.5-A), the M7 eleven-blob
and PPA-01 three-blob candidates are not touched, extended or reinterpreted: each is judged at its own checkpoint. A changed byte in any of the
twelve blobs, a missing or substituted path, any other protected change, an opened flag or a forged record exempts NOTHING.
"""
from __future__ import annotations

import json
import re
import subprocess
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent

# Immutable predecessor (main after PR #313) and the reviewed RC-7B source head carrying the final protected content.
RC7B_PREDECESSOR = "5be8c4b149712dd39b38b54c6fabcf3fcf47ef0d"
RC7B_REVIEWED_SOURCE_HEAD = "4b086b83e207249c807cc0521a14f78812ac8be3"
PROTECTED_PREFIXES = ("financial_engine/", "finco_core/", "domain/")

# Predecessor blobs (``None`` = new file) and the exact RC-7B candidate blobs: the approved changed-file inventory.
RC7B_PREDECESSOR_BLOBS = {
    "financial_engine/adapters/project_inputs.py": "14bd759a9958515a7796626f93c1bd2233d69150",
    "financial_engine/adapters/tax_inputs.py": "0150eb1cdb9e7c0968e1f8dcbf754266d0158f8a",
    "financial_engine/financing/generic_product_policy.py": "2894334e7241c4ac9f8967d4ce4ca6ce77a32fa0",
    "financial_engine/financing/project.py": "30536cec8779fdb6a490d82fd80bfce2c09e16fe",
    "financial_engine/financing/quarterly_scope.py": None,
    "financial_engine/inputs.py": "8ba4cd3e7de248e163ba727a59e3faa6757edd03",
    "financial_engine/orchestrator.py": "be7ac31c6c4fed43b5fd7ca49fe53bfd1cc54c03",
    "financial_engine/senior_debt/project_adapter.py": "a73611a117f0c04ecc7bd7350eac64456520f265",
    "finco_core/engine/calendar_policy.py": None,
    "finco_core/engine/period_engine.py": "7a44c10b003aee9e8d41de33490db1bb0bdcfd71",
    "finco_core/inputs/_models.py": "b896d3c071ee22c1c82c48f23d4c169e058c7a7b",
    "finco_core/inputs/serialization.py": "31f70570376b2f5b50ece583c54c1d9811e90a3c",
}
RC7B_CANDIDATE_AUTHORITIES = {
    "financial_engine/adapters/project_inputs.py": "d97ae939559cbd6e031414192fa23fc40be1110f",
    "financial_engine/adapters/tax_inputs.py": "9e271f696b4dfa8dcfef44387b2b4b3c1842c63e",
    "financial_engine/financing/generic_product_policy.py": "59a2c1f868b4c12718a22919c3114f3af5af5120",
    "financial_engine/financing/project.py": "2e18a6e7c8ddfd85929d9b1906f91dd8858d0044",
    "financial_engine/financing/quarterly_scope.py": "0bcf6605c84d8716dc07a111cdf911eb0a6bac60",
    "financial_engine/inputs.py": "6fb5913a6cedec3b526b26fc4b55340a8a682361",
    "financial_engine/orchestrator.py": "07aa1e18cc72a1422fcf7fc779dd72ee835c8096",
    "financial_engine/senior_debt/project_adapter.py": "b2302be9d9760ab7a663ff873e95415a4bf18842",
    "finco_core/engine/calendar_policy.py": "91f55f9b8356ae0b8b1ca635b28d008949a8146f",
    "finco_core/engine/period_engine.py": "465c172d5d7176f294872fd2e9542315e3027db2",
    "finco_core/inputs/_models.py": "a48139b9e2aed875d6f3a8358f2c53e9489983c7",
    "finco_core/inputs/serialization.py": "7e678450304467fce435d6052e78af76171b03f7",
}
RESEARCH_PATHS = ("tools/quarterly_research/__init__.py", "tools/quarterly_research/calculation.py",
                  "tools/quarterly_research/calendar.py", "tools/quarterly_research/runtime.py")
HISTORICAL_AUTHORITY_FILES = ("tests/model_v2_governance.py", "tests/m7_rc3_candidate_successor.py",
                              "tests/radar_authority_governance.py")
RELEASE_FLAG = ("app/workbook/quarterly_frequency_config.py", "ACTIVATION_ENABLED")
ACCEPTANCE_RECORD = "docs/model_v2/RC7B_QUARTERLY_FINANCIAL_ACCEPTANCE.json"
REQUIRED_DECISIONS = tuple(f"D-{n:02d}" for n in range(1, 13))
# Reviewer identities that can never count as an independent reviewer or the financial owner.
NOT_INDEPENDENT = re.compile(r"claude|anthropic|assistant|agent|bot|\bai\b|gpt|author|self", re.I)


def _git(root, *args: str):
    proc = subprocess.run(["git", *args], cwd=str(root), capture_output=True, text=True)
    return proc.stdout.strip() if proc.returncode == 0 else None


def blob(path: str, *, repo=None, ref: str = "HEAD"):
    return _git(repo or ROOT, "rev-parse", f"{ref}:{path}")


def candidate_blobs_match(*, repo=None, ref: str = "HEAD") -> bool:
    """Blob identity of ALL twelve paths (a partial slice is not the candidate)."""
    return all(blob(p, repo=repo, ref=ref) == b for p, b in RC7B_CANDIDATE_AUTHORITIES.items())


def collect(*, repo=None, ref: str = "HEAD") -> dict:
    root = repo or ROOT
    from tests.test_rc2_integration_manifest import activation_state
    predecessor_ok = _git(root, "rev-parse", f"{RC7B_PREDECESSOR}^{{commit}}") == RC7B_PREDECESSOR and subprocess.run(
        ["git", "merge-base", "--is-ancestor", RC7B_PREDECESSOR, ref], cwd=str(root), capture_output=True).returncode == 0
    changed = (_git(root, "diff", "--name-only", "--no-renames", RC7B_PREDECESSOR, ref, "--", *PROTECTED_PREFIXES)
               if predecessor_ok else None)
    flag_source = _git(root, "show", f"{ref}:{RELEASE_FLAG[0]}")
    record_text = _git(root, "show", f"{ref}:{ACCEPTANCE_RECORD}")
    try:
        record = json.loads(record_text) if record_text is not None else None
    except ValueError:
        record = "malformed"
    return {
        "blobs": {p: blob(p, repo=root, ref=ref) for p in RC7B_CANDIDATE_AUTHORITIES},
        "source_blobs": {p: blob(p, repo=root, ref=RC7B_REVIEWED_SOURCE_HEAD) for p in RC7B_CANDIDATE_AUTHORITIES},
        "predecessor_blobs": {p: blob(p, repo=root, ref=RC7B_PREDECESSOR) for p in RC7B_CANDIDATE_AUTHORITIES},
        "source_head_ancestor": subprocess.run(["git", "merge-base", "--is-ancestor", RC7B_REVIEWED_SOURCE_HEAD, ref],
                                               cwd=str(root), capture_output=True).returncode == 0,
        "predecessor_valid": predecessor_ok,
        "protected_changes": sorted(changed.splitlines()) if changed is not None else None,
        "historical_authorities_unchanged": all(
            blob(p, repo=root, ref=ref) is not None and blob(p, repo=root, ref=ref) == blob(p, repo=root, ref=RC7B_PREDECESSOR)
            for p in HISTORICAL_AUTHORITY_FILES),
        "research_unchanged": all(
            blob(p, repo=root, ref=ref) is not None and blob(p, repo=root, ref=ref) == blob(p, repo=root, ref=RC7B_PREDECESSOR)
            for p in RESEARCH_PATHS),
        "activation": activation_state(flag_source + "\n", RELEASE_FLAG[1]) if flag_source is not None else "MISSING",
        "record": record,
    }


def content_violations(facts) -> list[str]:
    """Exact-content check ONLY. [] means the bytes are the reviewed release-closed candidate (not that they are accepted)."""
    try:
        bad = []
        if facts["predecessor_valid"] is not True:
            bad.append("the immutable predecessor main is unavailable or not an ancestor")
        if facts["source_head_ancestor"] is not True:
            bad.append("the reviewed RC-7B source head is not an ancestor")
        if facts["historical_authorities_unchanged"] is not True:
            bad.append("historical financial authority maps changed or are unavailable")
        if facts["research_unchanged"] is not True:
            bad.append("the isolated research reference under tools/quarterly_research changed")
        if facts["activation"] != "CLOSED":
            bad.append(f"quarterly activation is not a literal release-closed False ({facts['activation']})")
        for path, pin in RC7B_CANDIDATE_AUTHORITIES.items():
            if facts["blobs"].get(path) != pin:
                bad.append(f"{path}: not the exact reviewed candidate blob")
            if facts["source_blobs"].get(path) != pin:
                bad.append(f"{path}: the reviewed source head does not carry this blob")
            if facts["predecessor_blobs"].get(path) != RC7B_PREDECESSOR_BLOBS[path]:
                bad.append(f"{path}: predecessor identity differs from the recorded original authority")
        extra = set(facts["blobs"]) - set(RC7B_CANDIDATE_AUTHORITIES)
        if extra:
            bad.append(f"substituted or extra protected files: {sorted(extra)}")
        changes = facts["protected_changes"]
        if changes is None:
            bad.append("the protected-path diff against the immutable predecessor is unavailable")
        else:
            unlisted = [p for p in changes if p not in RC7B_CANDIDATE_AUTHORITIES]
            if unlisted:
                bad.append(f"unlisted financial/core/domain changes: {unlisted}")
            missing = [p for p in RC7B_CANDIDATE_AUTHORITIES if p not in changes]
            if missing:
                bad.append(f"partial slice: reviewed protected files are not part of the change: {missing}")
        return bad
    except (KeyError, TypeError, AttributeError) as exc:
        return [f"facts incomplete or malformed: {exc!r}"]


def acceptance_violations(facts) -> list[str]:
    """The financial approval gate: empty ONLY with a valid, separate, independent acceptance record."""
    problems = content_violations(facts)
    try:
        record = facts["record"]
        if record is None:
            return problems + ["FINANCIAL_OWNER_APPROVAL_REQUIRED: no independent RC-7B acceptance record exists"]
        if not isinstance(record, dict):
            return problems + ["acceptance record is malformed"]
        for label in ("independent_reviewer", "financial_owner"):
            who = record.get(label)
            if not isinstance(who, str) or not who.strip() or NOT_INDEPENDENT.search(who):
                problems.append(f"acceptance record does not identify a human {label.replace('_', ' ')}")
        if record.get("reviewed_source_head") != RC7B_REVIEWED_SOURCE_HEAD:
            problems.append("acceptance record names a different source head than the reviewed one")
        if record.get("accepted_blobs") != RC7B_CANDIDATE_AUTHORITIES:
            problems.append("acceptance record does not repeat the exact twelve blobs")
        decisions = record.get("owner_decisions")
        if not isinstance(decisions, dict) or set(decisions) != set(REQUIRED_DECISIONS) or any(
                not isinstance(v, str) or not v.strip() for v in decisions.values()):
            problems.append("acceptance record does not record owner decisions D-01..D-12")
        if record.get("scope") != "CANDIDATE_CONTENT_ONLY":
            problems.append("acceptance must be candidate-content only; admission and release stay separate decisions")
        if not isinstance(record.get("decision_reference"), str) or not record["decision_reference"].strip():
            problems.append("acceptance record carries no decision reference")
        return problems
    except (KeyError, TypeError, AttributeError) as exc:
        return problems + [f"acceptance facts incomplete or malformed: {exc!r}"]


def admission_violations(facts) -> list[str]:
    """Product admission needs approval AND a separately reviewed change opening the flag; content recognition requires it closed."""
    problems = acceptance_violations(facts)
    problems.append("PRODUCT_ADMISSION_NOT_GRANTED: quarterly activation is release-closed")
    return problems


def release_violations(facts) -> list[str]:
    problems = admission_violations(facts)
    record = facts.get("record") if isinstance(facts, dict) else None
    if not (isinstance(record, dict) and record.get("release_authorized") is True):
        problems.append("RELEASE_NOT_AUTHORIZED: acceptance of candidate content is not a release")
    return problems


def states(*, repo=None, ref: str = "HEAD") -> dict:
    """The separate research / content / acceptance / admission / release states (never one boolean)."""
    facts = collect(repo=repo, ref=ref)
    return {
        "research_isolated": facts["research_unchanged"] is True,
        "candidate_content_matches_exactly": content_violations(facts) == [],
        "candidate_is_financially_approved": acceptance_violations(facts) == [],
        "candidate_is_product_admitted": admission_violations(facts) == [],
        "candidate_is_released": release_violations(facts) == [],
    }


def candidate_content_matches_exactly(*, repo=None, ref: str = "HEAD") -> bool:
    return content_violations(collect(repo=repo, ref=ref)) == []


def frozen_scope_exempt(path: str, *, repo=None, ref: str = "HEAD") -> bool:
    """Frozen-namespace recognition for the current-integration guards: one of the twelve exact paths, and only while the WHOLE candidate
    content matches exactly (a modified, partial, substituted or activated candidate exempts nothing). NOT a release and not an approval."""
    return path in RC7B_CANDIDATE_AUTHORITIES and candidate_blobs_match(repo=repo, ref=ref) and candidate_content_matches_exactly(
        repo=repo, ref=ref)
