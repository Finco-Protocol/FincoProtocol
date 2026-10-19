"""RC-7B Gate R (candidate-boundary authorization, option A): fail-closed negative controls.

Gate R authorizes ONLY the release-closed carrying of the twelve reviewed RC-7B blobs. These tests drive the REAL validator in
``tests/rc7b_quarterly_candidate_authority.py`` against a LOCAL CLONE of this repository (so exact blobs, ancestry and change scope are real Git
facts) with a synthetic record and a synthetic GitHub review fetcher. No signature, record or review is ever committed to the repository by
these tests; the synthetic reviewer names exist only inside a temporary clone.

The positive case below proves the mechanism can work once a REAL signed record and a REAL independent GitHub review exist. It is not
evidence that either exists: in the repository itself ``gate_r_active()`` is False.
"""
from __future__ import annotations

import copy
import json
import subprocess
from pathlib import Path

import pytest

from tests import rc7b_quarterly_candidate_authority as rc7b

ROOT = Path(__file__).resolve().parent.parent
TEMPLATE = ROOT / "docs/model_v2/RC7B_GATE_R_AUTHORIZATION.TEMPLATE.json"
OWNER, REVIEWER, AUTHOR = "owner-human", "reviewer-human", "pr-author-human"


def git(repo, *args, check=True):
    return subprocess.run(["git", *args], cwd=str(repo), capture_output=True, text=True, check=check).stdout.strip()


def signed_record(review_commit: str) -> dict:
    record = json.loads(TEMPLATE.read_text())
    record.pop("_comment", None)
    record["status"] = "SIGNED"
    record["financial_owner"].update(name="Owner Human", role="Financial Owner", identity_reference=OWNER, confirmed_at_utc="2026-10-20T08:00:00Z")
    record["independent_reviewer"].update(name="Reviewer Human", role="Independent reviewer", identity_reference=REVIEWER,
                                          reviewed_at_utc="2026-10-20T09:00:00Z", review_result=rc7b.GATE_R_ACCEPTED_RESULT,
                                          review_reference="synthetic")
    record["supersedes_candidate_blobs"]["m7_supersession_acknowledged_by_reviewer"] = True
    record["decision_reference"] = "synthetic-decision-1"
    record["github_review"] = {"pull_number": rc7b.GATE_R_PULL_NUMBER, "review_id": 4242, "reviewer_login": REVIEWER}
    return record


def evidence(commit: str, **override) -> dict:
    review = {"id": 4242, "state": "APPROVED", "user": {"login": REVIEWER}, "author_association": "COLLABORATOR", "commit_id": commit}
    review.update(override)
    return {"pull": {"number": rc7b.GATE_R_PULL_NUMBER, "user": {"login": AUTHOR}}, "reviews": [review]}


@pytest.fixture(scope="module")
def base_clone(tmp_path_factory):
    clone = tmp_path_factory.mktemp("gater") / "clone"
    subprocess.run(["git", "clone", "-q", "--no-hardlinks", str(ROOT), str(clone)], check=True, capture_output=True)
    git(clone, "config", "user.name", "Synthetic")
    git(clone, "config", "user.email", "synthetic@example.invalid")
    head = git(ROOT, "rev-parse", "HEAD")
    # the clone has every commit reachable from the local HEAD (the working branch), including the predecessor and reviewed source head
    git(clone, "checkout", "-q", "-B", "base", head)
    return clone, head


@pytest.fixture()
def clone(base_clone):
    repo, head = base_clone
    git(repo, "checkout", "-q", "-B", "work", head)
    git(repo, "reset", "-q", "--hard", head)
    return repo, head


def commit_record(repo, record):
    path = repo / rc7b.GATE_R_RECORD
    path.write_text(json.dumps(record, indent=2))
    git(repo, "add", rc7b.GATE_R_RECORD)
    git(repo, "commit", "-q", "-m", "synthetic gate r record")


def never_called(_pull):
    raise AssertionError("the network must not be touched for an invalid or missing record")


# ── the repository as it is: inert ──────────────────────────────────────────────

def test_real_repository_has_no_gate_r_and_is_inactive():
    assert rc7b.gate_r_active(fetcher=never_called) is False
    assert any("GATE_R_APPROVAL_REQUIRED" in v for v in rc7b.gate_r_violations(fetcher=never_called))


def test_unsigned_template_authorizes_nothing_and_is_never_read():
    template = json.loads(TEMPLATE.read_text())
    problems = rc7b.gate_r_record_violations(template)
    assert any("not SIGNED" in p for p in problems) and any("named human" in p for p in problems)
    assert rc7b.GATE_R_RECORD != str(TEMPLATE.relative_to(ROOT))
    assert TEMPLATE.name.endswith(".TEMPLATE.json")


def test_template_blobs_equal_the_validators_constants():
    template = json.loads(TEMPLATE.read_text())
    assert template["accepted_blobs"] == rc7b.RC7B_CANDIDATE_AUTHORITIES
    assert template["predecessor_blobs"] == rc7b.RC7B_PREDECESSOR_BLOBS
    assert template["grants"] == rc7b.GATE_R_GRANTS


# ── mechanism in a clone ────────────────────────────────────────────────────────

def test_valid_signed_record_with_authentic_review_is_accepted(clone):
    repo, head = clone
    commit_record(repo, signed_record(head))
    assert rc7b.gate_r_violations(repo=repo, fetcher=lambda _p: evidence(head)) == []
    assert rc7b.gate_r_active(repo=repo, fetcher=lambda _p: evidence(head)) is True


def test_unsigned_template_committed_as_the_real_name_is_rejected_without_network(clone):
    repo, head = clone
    record = json.loads(TEMPLATE.read_text())
    commit_record(repo, record)
    assert rc7b.gate_r_active(repo=repo, fetcher=never_called) is False


@pytest.mark.parametrize("mutate,expected", [
    (lambda r: r.update(status="UNSIGNED_TEMPLATE"), "not SIGNED"),
    (lambda r: r.update(scope="FINANCIAL_APPROVAL"), "scope"),
    (lambda r: r["accepted_blobs"].update({"financial_engine/orchestrator.py": "0" * 40}), "twelve"),
    (lambda r: r["accepted_blobs"].pop("finco_core/engine/period_engine.py"), "twelve"),
    (lambda r: r["accepted_blobs"].update({"financial_engine/extra.py": "1" * 40}), "twelve"),
    (lambda r: r.update(predecessor_main="1" * 40), "predecessor main"),
    (lambda r: r.update(reviewed_source_head="1" * 40), "source head"),
    (lambda r: r["supersedes_candidate_blobs"].update(m7_supersession_acknowledged_by_reviewer=False), "supersession"),
    (lambda r: r["financial_owner"].update(identity_reference=None), "financial_owner"),
    (lambda r: r["independent_reviewer"].update(identity_reference=OWNER), "must not be the Financial Owner"),
    (lambda r: r["independent_reviewer"].update(name="Claude Assistant"), "named human"),
    (lambda r: r["independent_reviewer"].update(identity_reference="release-bot[bot]"), "human GitHub login"),
    (lambda r: r["independent_reviewer"].update(identity_reference="claude-agent"), "human GitHub login"),
    (lambda r: r["independent_reviewer"].update(review_result="PENDING"), "review result"),
    (lambda r: r["independent_reviewer"].update(reviewed_at_utc=""), "timestamp"),
    (lambda r: r["grants"].update(gate_p=True), "grants"),
    (lambda r: r["grants"].update(merge_to_main=True), "grants"),
    (lambda r: r["grants"].update(release=True), "grants"),
    (lambda r: r["grants"].update(user_activation_of_quarterly_run=True), "grants"),
    (lambda r: r["grants"].update(financial_policy_change=True), "grants"),
    (lambda r: r["grants"].update(financial_approval_of_d01_d12=True), "grants"),
    (lambda r: r["grants"].update(product_admission=True), "grants"),
    (lambda r: r["owner_decisions"].update({"D-01": "APPROVED"}), "decides no owner decision"),
    (lambda r: r["owner_decisions"].update({"D-06": "NOT_DECIDED_BY_THIS_RECORD"}), "DEFERRED"),
    (lambda r: r["owner_decisions"].update({"D-07": "APPROVED"}), "decides no owner decision"),
    (lambda r: r["owner_decisions"].pop("D-12"), "decides no owner decision"),
    (lambda r: r.update(decision_reference=" "), "decision reference"),
    (lambda r: r.pop("github_review"), "GitHub review"),
    (lambda r: r["github_review"].update(pull_number=1), "GitHub review"),
])
def test_record_defects_are_each_rejected(clone, mutate, expected):
    repo, head = clone
    record = signed_record(head)
    mutate(record)
    commit_record(repo, record)
    problems = rc7b.gate_r_violations(repo=repo, fetcher=never_called)
    assert problems and any(expected in p for p in problems), problems
    assert rc7b.gate_r_active(repo=repo, fetcher=never_called) is False


@pytest.mark.parametrize("make_evidence,expected", [
    (lambda c: evidence(c, state="COMMENTED"), "APPROVED"),
    (lambda c: evidence(c, state="CHANGES_REQUESTED"), "APPROVED"),
    (lambda c: evidence(c, state="DISMISSED"), "APPROVED"),
    (lambda c: evidence(c, state="PENDING"), "APPROVED"),
    (lambda c: evidence(c, user={"login": "somebody-else"}), "named independent reviewer"),
    (lambda c: evidence(c, user=None), "named independent reviewer"),
    (lambda c: evidence(c, author_association="NONE"), "association"),
    (lambda c: evidence(c, author_association="CONTRIBUTOR"), "association"),
    (lambda c: evidence(c, id=1), "not found"),
    (lambda c: {**evidence(c), "pull": {"number": 320, "user": {"login": REVIEWER}}}, "PR author"),
    (lambda c: {**evidence(c), "pull": {"number": 320, "user": None}}, "PR author"),
    (lambda c: {**evidence(c), "pull": {"number": 999, "user": {"login": AUTHOR}}}, "integration PR"),
    (lambda c: {"pull": {}, "reviews": "garbage"}, "UNVERIFIABLE"),
    (lambda c: evidence(c, commit_id=None), "no commit"),
    (lambda c: evidence(c, commit_id="g" * 40), "no commit"),
    (lambda c: evidence(c, commit_id="1" * 40), "STALE_REVIEW"),
    (lambda c: evidence(c, commit_id=rc7b.RC7B_PREDECESSOR), "STALE_REVIEW"),
])
def test_review_evidence_defects_are_each_rejected(clone, make_evidence, expected):
    repo, head = clone
    commit_record(repo, signed_record(head))
    problems = rc7b.gate_r_violations(repo=repo, fetcher=lambda _p: make_evidence(head))
    assert problems and any(expected in p for p in problems), problems
    assert rc7b.gate_r_active(repo=repo, fetcher=lambda _p: make_evidence(head)) is False


def test_unreachable_or_failing_github_is_unverifiable_and_rejected(clone):
    repo, head = clone
    commit_record(repo, signed_record(head))
    assert rc7b.gate_r_active(repo=repo, fetcher=lambda _p: None) is False
    assert any("UNVERIFIABLE" in p for p in rc7b.gate_r_violations(repo=repo, fetcher=lambda _p: None))

    def boom(_pull):
        raise OSError("network down")
    assert rc7b.gate_r_active(repo=repo, fetcher=boom) is False


def test_a_review_of_the_reviewed_content_survives_later_unrelated_commits_but_not_candidate_changes(clone):
    repo, head = clone
    (repo / "docs" / "unrelated.md").write_text("docs only")
    git(repo, "add", "docs/unrelated.md")
    git(repo, "commit", "-q", "-m", "docs only after the review")
    commit_record(repo, signed_record(head))
    assert rc7b.gate_r_active(repo=repo, fetcher=lambda _p: evidence(head)) is True
    # now a candidate blob changes after the review: content no longer matches, so everything is rejected
    target = repo / "financial_engine/orchestrator.py"
    target.write_text(target.read_text() + "\n# changed after review\n")
    git(repo, "add", "financial_engine/orchestrator.py")
    git(repo, "commit", "-q", "-m", "post-review financial change")
    assert rc7b.gate_r_active(repo=repo, fetcher=lambda _p: evidence(head)) is False


# ── candidate content is part of Gate R ─────────────────────────────────────────

def _valid_then(repo, head, mutate):
    mutate(repo)
    git(repo, "add", "-A")
    git(repo, "commit", "-q", "-m", "mutation")
    commit_record(repo, signed_record(head))
    return rc7b.gate_r_active(repo=repo, fetcher=lambda _p: evidence(head))


@pytest.mark.parametrize("path", rc7b.GATE_R_GOVERNANCE_FILES)
def test_a_change_to_the_gate_r_mechanism_after_the_review_makes_the_review_stale(clone, path):
    repo, head = clone
    commit_record(repo, signed_record(head))
    assert rc7b.gate_r_active(repo=repo, fetcher=lambda _p: evidence(head)) is True
    target = repo / path
    target.write_text(target.read_text() + "\n# weakened after review\n")
    git(repo, "add", path)
    git(repo, "commit", "-q", "-m", "post-review governance change")
    problems = rc7b.gate_r_violations(repo=repo, fetcher=lambda _p: evidence(head))
    assert any("STALE_REVIEW" in p and path in p for p in problems), problems
    assert rc7b.gate_r_active(repo=repo, fetcher=lambda _p: evidence(head)) is False


def test_review_is_not_circular_with_the_record(clone):
    """The record cites only the review id; the review cites the commit BEFORE the record. The record's own commit never needs to be known."""
    repo, head = clone
    record = signed_record(head)
    assert "commit" not in json.dumps(record["github_review"]).lower()
    commit_record(repo, record)
    record_commit = git(repo, "rev-parse", "HEAD")
    assert record_commit != head
    assert subprocess.run(["git", "merge-base", "--is-ancestor", head, record_commit], cwd=str(repo)).returncode == 0
    assert rc7b.gate_r_active(repo=repo, fetcher=lambda _p: evidence(head)) is True
    # a review that names the record commit itself is also acceptable only if every blob/governance file is identical (it is): no hash cycle
    assert rc7b.gate_r_active(repo=repo, fetcher=lambda _p: evidence(record_commit)) is True


def test_one_additional_protected_financial_file_is_rejected(clone):
    repo, head = clone
    assert _valid_then(repo, head, lambda r: (r / "financial_engine/extra_unreviewed.py").write_text("x = 1\n")) is False


def test_an_additional_core_or_domain_file_is_rejected(clone):
    repo, head = clone
    def add(r):
        (r / "finco_core/extra_unreviewed.py").write_text("x = 1\n")
        (r / "domain/extra_unreviewed.py").write_text("x = 1\n")
    assert _valid_then(repo, head, add) is False


def test_a_modified_candidate_blob_is_rejected(clone):
    repo, head = clone
    def edit(r):
        p = r / "financial_engine/senior_debt/project_adapter.py"
        p.write_text(p.read_text() + "\n# tweak\n")
    assert _valid_then(repo, head, edit) is False


def test_a_missing_candidate_file_is_rejected(clone):
    repo, head = clone
    assert _valid_then(repo, head, lambda r: (r / "financial_engine/financing/quarterly_scope.py").unlink()) is False


def test_a_changed_existing_6_6_authority_file_is_rejected(clone):
    repo, head = clone
    def edit(r):
        p = r / "financial_engine/senior_debt/solver.py"
        p.write_text(p.read_text() + "\n# unauthorized solver change\n")
    assert _valid_then(repo, head, edit) is False


@pytest.mark.parametrize("path", ["financial_engine/tax/engine.py", "financial_engine/dsra/target.py", "financial_engine/construction/adapter.py",
                                  "financial_engine/senior_debt/policy.py", "financial_engine/financing/reserve_policy.py",
                                  "financial_engine/financing/project_uses.py", "financial_engine/senior_debt/solver.py"])
def test_unauthorized_dscr_tax_idc_reserve_or_repayment_change_is_rejected(clone, path):
    repo, head = clone
    target = repo / path
    assert target.exists(), path
    def edit(r):
        target.write_text(target.read_text() + "\n# unauthorized policy change\n")
    assert _valid_then(repo, head, edit) is False


def test_opened_quarterly_activation_is_rejected(clone):
    repo, head = clone
    flag = repo / "app/workbook/quarterly_frequency_config.py"
    def open_flag(r):
        flag.write_text(flag.read_text().replace("ACTIVATION_ENABLED = False", "ACTIVATION_ENABLED = True"))
    assert "ACTIVATION_ENABLED = False" in flag.read_text()
    assert _valid_then(repo, head, open_flag) is False


def test_a_changed_historical_authority_file_is_rejected(clone):
    repo, head = clone
    def edit(r):
        p = r / "tests/model_v2_governance.py"
        p.write_text(p.read_text() + "\n# repinned\n")
    assert _valid_then(repo, head, edit) is False


def test_validator_never_reports_financial_approval_admission_or_release(clone):
    repo, head = clone
    commit_record(repo, signed_record(head))
    assert rc7b.gate_r_active(repo=repo, fetcher=lambda _p: evidence(head)) is True
    states = rc7b.states(repo=repo)
    assert states["candidate_is_financially_approved"] is False
    assert states["candidate_is_product_admitted"] is False
    assert states["candidate_is_released"] is False
