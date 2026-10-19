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


# ═══════════════════════════ Gate R: candidate-boundary authorization (option A) ═══════════════════════════
#
# Gate R is NOT a financial approval. It authorizes exactly one thing: carrying the twelve reviewed blobs above as a RELEASE-CLOSED integration
# candidate. It never approves D-01..D-12, Gate P, activation of the quarterly Run, a financial-policy change, product admission, release or merge.
#
# It is INERT unless ALL of the following are verified, and every uncertainty (missing, unsigned, unverifiable, stale) means REJECT:
#   1. the exact-content facts above hold (twelve blobs, ancestry, change scope, literal ``ACTIVATION_ENABLED = False``, historical files unchanged);
#   2. a committed, SIGNED record ``GATE_R_RECORD`` names a human Financial Owner and a different human independent reviewer and repeats the exact
#      blobs, the M7 supersession, DEFERRED D-06/D-07 and grants that are all ``False`` except the release-closed boundary itself;
#   3. an authentic GitHub review (fetched from GitHub, not read from the repository) exists: state APPROVED, by the named reviewer, who is neither
#      the PR author nor the Financial Owner nor a bot, with a repository-collaborator association, on a commit whose twelve blobs equal the accepted
#      blobs and which is an ancestor of the evaluated ref (a review of other or older content is stale).
GATE_R_RECORD = "docs/model_v2/RC7B_GATE_R_AUTHORIZATION.json"
GATE_R_SCHEMA = "finco.rc7b.gate-r-candidate-boundary-authorization.v1"
GATE_R_RECORD_TYPE = "GATE_R_CANDIDATE_BOUNDARY_AUTHORIZATION"
GATE_R_SCOPE = "CANDIDATE_BOUNDARY_ONLY"
GATE_R_REPOSITORY = "Finco-Protocol/FincoProtocol"
GATE_R_PULL_NUMBER = 320
GATE_R_ACCEPTED_RESULT = "ACCEPTED_CANDIDATE_CONTENT"
GATE_R_GRANTS = {
    "release_closed_integration_of_listed_blobs": True,
    "financial_approval_of_d01_d12": False,
    "gate_p": False,
    "user_activation_of_quarterly_run": False,
    "financial_policy_change": False,
    "product_admission": False,
    "release": False,
    "merge_to_main": False,
}
GATE_R_ALLOWED_DECISION_VALUES = ("NOT_DECIDED_BY_THIS_RECORD", "DEFERRED")
GATE_R_DEFERRED = ("D-06", "D-07")
GATE_R_M7_SUPERSEDED = {
    "financial_engine/orchestrator.py": "be7ac31c6c4fed43b5fd7ca49fe53bfd1cc54c03",
    "financial_engine/adapters/project_inputs.py": "14bd759a9958515a7796626f93c1bd2233d69150",
}
GATE_R_REVIEWER_ASSOCIATIONS = ("OWNER", "MEMBER", "COLLABORATOR")
# The Gate R mechanism. An approval reviews THESE bytes together with the twelve blobs; a later change to any of them makes the review stale.
GATE_R_GOVERNANCE_FILES = (
    "tests/rc7b_quarterly_candidate_authority.py",
    "tests/finance_integrity_governance.py",
    "tests/rc3_authority_states.py",
    "tests/test_rc7b_gate_r_authorization.py",
)
_GITHUB_LOGIN = re.compile(r"^[A-Za-z0-9](?:[A-Za-z0-9-]{0,37}[A-Za-z0-9])?$")


def github_review_fetcher(pull_number: int = GATE_R_PULL_NUMBER):
    """Read-only live fetch of the PR and its reviews from GitHub; ``None`` on ANY problem (=> approval unverifiable => rejected)."""
    import os
    import urllib.request

    def get(path):
        request = urllib.request.Request(f"https://api.github.com/repos/{GATE_R_REPOSITORY}/{path}",
                                         headers={"Accept": "application/vnd.github+json", "User-Agent": "finco-gate-r-validator"})
        token = os.environ.get("GITHUB_TOKEN")
        if token:
            request.add_header("Authorization", f"Bearer {token}")
        with urllib.request.urlopen(request, timeout=10) as response:      # noqa: S310 - fixed https GitHub API host
            return json.loads(response.read().decode("utf-8"))

    try:
        return {"pull": get(f"pulls/{pull_number}"), "reviews": get(f"pulls/{pull_number}/reviews?per_page=100")}
    except Exception:                                                        # noqa: BLE001 - unverifiable evidence must never raise into approval
        return None


def _is_human_login(value) -> bool:
    return (isinstance(value, str) and bool(_GITHUB_LOGIN.match(value)) and not NOT_INDEPENDENT.search(value)
            and not value.lower().endswith("[bot]"))


def gate_r_record_violations(record) -> list[str]:
    """Structure and content of the signed record ONLY (no Git, no network)."""
    if record is None:
        return ["GATE_R_APPROVAL_REQUIRED: no signed Gate R authorization record exists"]
    if not isinstance(record, dict):
        return ["Gate R record is malformed"]
    bad = []
    if record.get("schema") != GATE_R_SCHEMA or record.get("record_type") != GATE_R_RECORD_TYPE:
        bad.append("Gate R record has the wrong schema or record type")
    if record.get("status") != "SIGNED":
        bad.append("Gate R record is not SIGNED (an unsigned template authorizes nothing)")
    if record.get("scope") != GATE_R_SCOPE:
        bad.append("Gate R scope must be CANDIDATE_BOUNDARY_ONLY")
    if record.get("predecessor_main") != RC7B_PREDECESSOR:
        bad.append("Gate R record names a different predecessor main")
    if record.get("reviewed_source_head") != RC7B_REVIEWED_SOURCE_HEAD:
        bad.append("Gate R record names a different reviewed source head")
    if record.get("accepted_blobs") != RC7B_CANDIDATE_AUTHORITIES:
        bad.append("Gate R record does not repeat the exact twelve candidate blobs")
    if record.get("predecessor_blobs") != RC7B_PREDECESSOR_BLOBS:
        bad.append("Gate R record does not repeat the exact predecessor blobs")
    supersession = record.get("supersedes_candidate_blobs")
    if (not isinstance(supersession, dict)
            or {k: v for k, v in supersession.items() if k in GATE_R_M7_SUPERSEDED} != GATE_R_M7_SUPERSEDED
            or supersession.get("m7_supersession_acknowledged_by_reviewer") is not True):
        bad.append("Gate R record does not explicitly acknowledge the supersession of the two shared M7 candidate blobs")
    people = {}
    for label, review_key in (("financial_owner", None), ("independent_reviewer", "review_result")):
        who = record.get(label)
        if not isinstance(who, dict):
            bad.append(f"Gate R record has no {label}")
            continue
        login = who.get("identity_reference")
        people[label] = login
        if not (isinstance(who.get("name"), str) and who["name"].strip() and not NOT_INDEPENDENT.search(who["name"])):
            bad.append(f"Gate R {label} is not a named human")
        if not _is_human_login(login):
            bad.append(f"Gate R {label}.identity_reference must be a human GitHub login")
        if not (isinstance(who.get("confirmed_at_utc" if label == "financial_owner" else "reviewed_at_utc"), str)
                and who.get("confirmed_at_utc" if label == "financial_owner" else "reviewed_at_utc").strip()):
            bad.append(f"Gate R {label} carries no confirmation timestamp")
        if review_key and who.get(review_key) != GATE_R_ACCEPTED_RESULT:
            bad.append("Gate R independent review result is not ACCEPTED_CANDIDATE_CONTENT")
    if people.get("financial_owner") and people.get("financial_owner") == people.get("independent_reviewer"):
        bad.append("the independent reviewer must not be the Financial Owner")
    if record.get("grants") != GATE_R_GRANTS:
        bad.append("Gate R grants must be exactly: release-closed integration true, every other grant false")
    decisions = record.get("owner_decisions")
    if not isinstance(decisions, dict):
        bad.append("Gate R record has no owner_decisions block")
    else:
        body = {k: v for k, v in decisions.items() if not k.startswith("_")}
        if set(body) != set(REQUIRED_DECISIONS) or any(v not in GATE_R_ALLOWED_DECISION_VALUES for v in body.values()):
            bad.append("Gate R decides no owner decision: every D-01..D-12 must be NOT_DECIDED_BY_THIS_RECORD or DEFERRED")
        if any(body.get(d) != "DEFERRED" for d in GATE_R_DEFERRED):
            bad.append("D-06 and D-07 must remain DEFERRED")
    if not (isinstance(record.get("decision_reference"), str) and record["decision_reference"].strip()):
        bad.append("Gate R record carries no decision reference")
    review = record.get("github_review")
    if not (isinstance(review, dict) and review.get("pull_number") == GATE_R_PULL_NUMBER
            and isinstance(review.get("review_id"), int) and not isinstance(review.get("review_id"), bool)
            and _is_human_login(review.get("reviewer_login"))):
        bad.append("Gate R record does not reference one GitHub review (pull_number, review_id, reviewer_login)")
    return bad


def gate_r_review_violations(record, evidence, *, repo=None, ref: str = "HEAD") -> list[str]:
    """Authenticity of the independent review against LIVE GitHub evidence. ``evidence`` None/malformed => rejected."""
    root = repo or ROOT
    if not isinstance(record, dict) or not isinstance(record.get("github_review"), dict):
        return ["no GitHub review is referenced"]
    if not isinstance(evidence, dict) or not isinstance(evidence.get("reviews"), list) or not isinstance(evidence.get("pull"), dict):
        return ["REVIEW_EVIDENCE_UNVERIFIABLE: the GitHub review could not be fetched or is malformed"]
    ref_review = record["github_review"]
    matches = [r for r in evidence["reviews"] if isinstance(r, dict) and r.get("id") == ref_review.get("review_id")]
    if len(matches) != 1:
        return ["REVIEW_EVIDENCE_UNVERIFIABLE: the referenced GitHub review was not found"]
    review, pull = matches[0], evidence["pull"]
    bad = []
    login = (review.get("user") or {}).get("login") if isinstance(review.get("user"), dict) else None
    reviewer = record["independent_reviewer"]["identity_reference"]
    owner = record["financial_owner"]["identity_reference"]
    author = (pull.get("user") or {}).get("login") if isinstance(pull.get("user"), dict) else None
    if review.get("state") != "APPROVED":
        bad.append("the GitHub review is not an APPROVED review")
    # A later decisive review by the same reviewer (CHANGES_REQUESTED, DISMISSED or a newer APPROVED on other content) supersedes this one.
    later = [r for r in evidence["reviews"] if isinstance(r, dict) and isinstance(r.get("user"), dict) and isinstance(login, str)
             and str(r["user"].get("login", "")).lower() == login.lower() and r.get("state") in ("APPROVED", "CHANGES_REQUESTED", "DISMISSED")
             and (not isinstance(r.get("id"), int) or isinstance(r.get("id"), bool) or not isinstance(review.get("id"), int) or r["id"] > review["id"])
             and r is not review]
    if later:
        bad.append("SUPERSEDED_REVIEW: the reviewer submitted a later decisive review, or review ordering is unverifiable")
    if not isinstance(login, str) or login.lower() != reviewer.lower() or login.lower() != str(ref_review.get("reviewer_login")).lower():
        bad.append("the GitHub review was not written by the named independent reviewer")
    if not isinstance(author, str) or not author or login is None or login.lower() == author.lower():
        bad.append("the independent reviewer is the PR author or the author is unknown")
    if isinstance(login, str) and login.lower() == str(owner).lower():
        bad.append("the independent reviewer is the Financial Owner")
    if review.get("author_association") not in GATE_R_REVIEWER_ASSOCIATIONS:
        bad.append("the reviewer has no OWNER/MEMBER/COLLABORATOR association with the repository")
    if pull.get("number") != GATE_R_PULL_NUMBER:
        bad.append("the evidence is not about the integration PR")
    commit = review.get("commit_id")
    if not isinstance(commit, str) or not re.fullmatch(r"[0-9a-f]{40}", commit):
        return bad + ["the GitHub review names no commit"]
    if subprocess.run(["git", "merge-base", "--is-ancestor", commit, ref], cwd=str(root), capture_output=True).returncode != 0:
        bad.append("STALE_REVIEW: the reviewed commit is not an ancestor of the evaluated ref")
    for path, pin in RC7B_CANDIDATE_AUTHORITIES.items():
        if blob(path, repo=root, ref=commit) != pin:
            bad.append(f"STALE_REVIEW: {path} at the reviewed commit is not the accepted blob")
    # The review also covers the Gate R mechanism itself: validator and guard wiring must be byte-identical to what the reviewer saw.
    for path in GATE_R_GOVERNANCE_FILES:
        at_review, now = blob(path, repo=root, ref=commit), blob(path, repo=root, ref=ref)
        if at_review is None or at_review != now:
            bad.append(f"STALE_REVIEW: governance file {path} differs from (or is absent at) the reviewed commit")
    return bad


def gate_r_violations(*, repo=None, ref: str = "HEAD", fetcher=None) -> list[str]:
    """Everything that must hold for Gate R. [] means the release-closed candidate boundary is authorized (nothing more)."""
    facts = collect(repo=repo, ref=ref)
    bad = content_violations(facts)
    record_text = _git(repo or ROOT, "show", f"{ref}:{GATE_R_RECORD}")
    try:
        record = json.loads(record_text) if record_text is not None else None
    except ValueError:
        record = "malformed"
    bad += gate_r_record_violations(record)
    if bad:
        return bad                                   # never touch the network for a record that is already invalid
    evidence = (fetcher or github_review_fetcher)(record["github_review"]["pull_number"])
    return gate_r_review_violations(record, evidence, repo=repo, ref=ref)


def gate_r_scope_exempt(path: str, *, repo=None, ref: str = "HEAD", fetcher=None) -> bool:
    """Frozen-scope recognition for the CURRENT-authority guards: one of the twelve exact paths, and only under an active Gate R (which itself
    requires the whole exact candidate, a signed record and an authentic independent review). NOT an approval, NOT a release, NOT a pin: it is
    never consulted by ``approved_frozen_path`` or ``released_engine_authority_matches``."""
    return path in RC7B_CANDIDATE_AUTHORITIES and gate_r_active(repo=repo, ref=ref, fetcher=fetcher)


_GATE_R_CACHE: dict = {}


def gate_r_active(*, repo=None, ref: str = "HEAD", fetcher=None) -> bool:
    """True only when :func:`gate_r_violations` is empty. Fails closed on any error. Cheap when no record is committed (no network)."""
    try:
        root = repo or ROOT
        head = _git(root, "rev-parse", ref)
        if head is None or _git(root, "cat-file", "-e", f"{ref}:{GATE_R_RECORD}") is None:
            return False                                # no committed record: reject without any network access
        key = (str(root), head)
        if fetcher is None and key in _GATE_R_CACHE:
            return _GATE_R_CACHE[key]
        result = gate_r_violations(repo=repo, ref=ref, fetcher=fetcher) == []
        if fetcher is None:
            _GATE_R_CACHE[key] = result
        return result
    except Exception:                                # noqa: BLE001 - fail closed
        return False


def superseded_by_gate_r(path: str, *, repo=None, ref: str = "HEAD", fetcher=None) -> bool:
    """True only for one of the twelve paths while a complete, authentic Gate R is active.

    Historical exact-content guards (F3 / WF04 / WF07 / M7 / PPA-01 / RC-3 inventory) keep asserting the original pin for every other path and for
    every tree without an active Gate R. For a superseded path they instead assert the Gate R candidate blob AND that the path is only a
    release-closed candidate (never released, never ``approved_frozen_path``). This is recognition of bytes, not financial approval."""
    return path in RC7B_CANDIDATE_AUTHORITIES and gate_r_active(repo=repo, ref=ref, fetcher=fetcher)


def current_expected_blob(path: str, historical_pin, *, repo=None, ref: str = "HEAD", fetcher=None):
    """The blob a current-authority guard must see at ``path``: the Gate R candidate blob for a superseded path, otherwise the historical pin."""
    return RC7B_CANDIDATE_AUTHORITIES[path] if superseded_by_gate_r(path, repo=repo, ref=ref, fetcher=fetcher) else historical_pin


def without_gate_r_superseded(paths, *, repo=None, ref: str = "HEAD", fetcher=None) -> list[str]:
    """``paths`` minus those superseded by an ACTIVE Gate R (identity when Gate R is inactive). Used by the current-authority guards on the OUTPUT of
    ``unapproved_engine_changes`` so that function itself stays byte-identical to its historical checkpoint."""
    return [p for p in paths if not superseded_by_gate_r(p, repo=repo, ref=ref, fetcher=fetcher)]
