"""RC-7B Gate R (candidate-boundary authorization): fail-closed negative controls.

Gate R authorizes ONLY the release-closed carrying of the twelve reviewed RC-7B blobs. These tests drive the REAL validator in
``tests/rc7b_quarterly_candidate_authority.py`` against a LOCAL CLONE of this repository (so exact blobs, ancestry and change scope are real Git
facts) with a synthetic record, a synthetic owner key and a synthetic GitHub review fetcher. No signature, key, record or review is ever committed to
the repository by these tests; the synthetic names and keys exist only inside a temporary clone or in memory.

The positive case proves the mechanism can work once a REAL owner signature and a REAL independent GitHub review exist. It is not evidence that
either exists: in the repository itself ``gate_r_active()`` is False and the Financial Owner registry is empty.

Authority comes only from a valid Ed25519 SSH signature by a key that is pinned in the reviewed registry AND currently registered on the owner's
GitHub account. A "SIGNED" status, a login, a commit author or any JSON the implementation agent can write is never authority.
"""
from __future__ import annotations

import copy
import hashlib
import json
import re
import shutil
import subprocess
import urllib.error
from datetime import datetime, timedelta, timezone
from pathlib import Path

import pytest

from tests import rc7b_owner_attestation as ssh
from tests import rc7b_quarterly_candidate_authority as rc7b

ROOT = Path(__file__).resolve().parent.parent
TEMPLATE = ROOT / "docs/model_v2/RC7B_GATE_R_AUTHORIZATION.TEMPLATE.json"
OWNER, REVIEWER, AUTHOR = "owner-human", "reviewer-human", "pr-author-human"
# Synthetic, test-only keys derived from fixed strings. They exist only in memory/temporary clones and are meaningless anywhere else.
OWNER_SEED = hashlib.sha256(b"finco-gate-r-SYNTHETIC-owner-key-tests-only").digest()
ATTACKER_SEED = hashlib.sha256(b"finco-gate-r-SYNTHETIC-attacker-key-tests-only").digest()
OWNER_KEY = ssh.key_line(ssh.public_key(OWNER_SEED), "synthetic-owner")
ATTACKER_KEY = ssh.key_line(ssh.public_key(ATTACKER_SEED), "synthetic-attacker")
OWNER_FP, ATTACKER_FP = ssh.fingerprint(OWNER_KEY), ssh.fingerprint(ATTACKER_KEY)
NS = rc7b.GATE_R_OWNER_NAMESPACE


def git(repo, *args, check=True):
    return subprocess.run(["git", *args], cwd=str(repo), capture_output=True, text=True, check=check).stdout.strip()


def stamp(delta_days: float) -> str:
    return (datetime.now(timezone.utc) + timedelta(days=delta_days)).strftime("%Y-%m-%dT%H:%M:%SZ")


def signed_record(review_commit: str) -> dict:
    """A complete record WITHOUT a signature; ``commit_record`` signs it (as the synthetic owner) at the clone's current HEAD."""
    record = json.loads(TEMPLATE.read_text())
    record.pop("_comment", None)
    record["status"] = "SIGNED"
    record["financial_owner"].update(name="Owner Human", role="Financial Owner", identity_reference=OWNER, confirmed_at_utc="2026-10-20T08:00:00Z",
                                     signing_key=OWNER_KEY, signing_key_fingerprint=OWNER_FP)
    record["independent_reviewer"].update(name="Reviewer Human", role="Independent reviewer", identity_reference=REVIEWER,
                                          reviewed_at_utc="2026-10-20T09:00:00Z", review_result=rc7b.GATE_R_ACCEPTED_RESULT,
                                          review_reference="synthetic")
    record["supersedes_candidate_blobs"]["m7_supersession_acknowledged_by_reviewer"] = True
    record["decision_reference"] = "synthetic-decision-1"
    record["github_review"] = {"pull_number": rc7b.GATE_R_PULL_NUMBER, "review_id": 4242, "reviewer_login": REVIEWER}
    record["owner_attestation"] = {"namespace": NS, "attestation_id": "a1" * 16, "signed_at_utc": stamp(-0.1), "expires_at_utc": stamp(30),
                                   "signature": None}
    return record


def evidence(commit: str, *, owner_keys=None, **override) -> dict:
    review = {"id": 4242, "state": "APPROVED", "user": {"login": REVIEWER}, "author_association": "COLLABORATOR", "commit_id": commit,
              "submitted_at": "2026-10-20T09:00:00Z"}
    review.update(override)
    return {"pull": {"number": rc7b.GATE_R_PULL_NUMBER, "user": {"login": AUTHOR}}, "reviews": [review],
            "owner_signing_keys": [OWNER_KEY] if owner_keys is None else owner_keys}


def registry(*entries) -> dict:
    return {"schema": rc7b.GATE_R_REGISTRY_SCHEMA, "financial_owners": list(entries)}


OWNER_ENTRY = {"login": OWNER, "ssh_signing_key_fingerprints": [OWNER_FP]}


@pytest.fixture(scope="module")
def base_clone(tmp_path_factory):
    clone = tmp_path_factory.mktemp("gater") / "clone"
    subprocess.run(["git", "clone", "-q", "--no-hardlinks", str(ROOT), str(clone)], check=True, capture_output=True)
    git(clone, "config", "user.name", "Synthetic")
    git(clone, "config", "user.email", "noreply@users.noreply.github.com")
    head = git(ROOT, "rev-parse", "HEAD")
    # the clone has every commit reachable from the local HEAD (the working branch), including the predecessor and reviewed source head
    git(clone, "checkout", "-q", "-B", "base", head)
    return clone, head


@pytest.fixture()
def clone(base_clone):
    """(repo, R): R is the commit a reviewer would review: the repository plus a registry pinning the synthetic owner and key."""
    repo, head = base_clone
    git(repo, "checkout", "-q", "-B", "work", head)
    git(repo, "reset", "-q", "--hard", head)
    (repo / rc7b.GATE_R_REGISTRY).write_text(json.dumps(registry(OWNER_ENTRY), indent=2))
    git(repo, "add", rc7b.GATE_R_REGISTRY)
    git(repo, "commit", "-q", "-m", "synthetic registry entry")
    return repo, git(repo, "rev-parse", "HEAD")


@pytest.fixture(autouse=True)
def _isolated_evidence_cache():
    rc7b.invalidate_gate_r_evidence()
    yield
    rc7b.invalidate_gate_r_evidence()


def mechanism_at(repo, ref="HEAD"):
    return {p: rc7b.blob(p, repo=repo, ref=ref) for p in rc7b.GATE_R_GOVERNANCE_FILES}


def commit_record(repo, record, *, seed=OWNER_SEED, namespace=NS, sign=True, post=None):
    """Sign (as ``seed``) over the exact payload at the clone's current HEAD, then commit the record. ``post`` edits the record AFTER signing."""
    record = copy.deepcopy(record)
    if sign:
        payload = rc7b.owner_payload(record, mechanism_at(repo))
        record["owner_attestation"]["signature"] = ssh.make_signature(seed, payload, namespace)
    if post:
        post(record)
    path = repo / rc7b.GATE_R_RECORD
    path.write_text(json.dumps(record, indent=2))
    git(repo, "add", rc7b.GATE_R_RECORD)
    git(repo, "commit", "-q", "-m", "synthetic gate r record")
    return record


def fetch_of(make):
    return lambda _pull, _owner=None: make


def never_called(_pull, _owner=None):
    raise AssertionError("the network must not be touched for an invalid or missing record")


def active(repo, head, **kw):
    return rc7b.gate_r_active(repo=repo, fetcher=lambda _p, _o=None: evidence(head, **kw))


# ── the repository as it is: inert ──────────────────────────────────────────────

def test_real_repository_has_no_gate_r_and_is_inactive():
    assert rc7b.gate_r_active(fetcher=never_called) is False
    assert any("GATE_R_APPROVAL_REQUIRED" in v for v in rc7b.gate_r_violations(fetcher=never_called))


def test_the_real_owner_registry_is_empty_so_no_owner_attestation_can_verify():
    data = json.loads((ROOT / rc7b.GATE_R_REGISTRY).read_text())
    assert data["schema"] == rc7b.GATE_R_REGISTRY_SCHEMA and data["financial_owners"] == []
    assert not (ROOT / rc7b.GATE_R_RECORD).exists()


def test_unsigned_template_authorizes_nothing_and_is_never_read():
    template = json.loads(TEMPLATE.read_text())
    problems = rc7b.gate_r_record_violations(template)
    assert any("not SIGNED" in p for p in problems) and any("named human" in p for p in problems)
    assert any("OWNER_" in p for p in problems)
    assert rc7b.GATE_R_RECORD != str(TEMPLATE.relative_to(ROOT))
    assert TEMPLATE.name.endswith(".TEMPLATE.json")


def test_template_blobs_equal_the_validators_constants():
    template = json.loads(TEMPLATE.read_text())
    assert template["schema"] == rc7b.GATE_R_SCHEMA
    assert template["accepted_blobs"] == rc7b.RC7B_CANDIDATE_AUTHORITIES
    assert template["predecessor_blobs"] == rc7b.RC7B_PREDECESSOR_BLOBS
    assert template["grants"] == rc7b.GATE_R_GRANTS
    assert template["owner_attestation"]["namespace"] == rc7b.GATE_R_OWNER_NAMESPACE
    assert template["financial_owner"]["signing_key"] is None and template["owner_attestation"]["signature"] is None


def test_there_is_no_process_lifetime_positive_result_cache():
    assert not hasattr(rc7b, "_GATE_R_CACHE")


# ── mechanism in a clone ────────────────────────────────────────────────────────

def test_valid_signed_record_with_authentic_review_is_accepted(clone):
    repo, head = clone
    commit_record(repo, signed_record(head))
    assert rc7b.gate_r_violations(repo=repo, fetcher=lambda _p, _o=None: evidence(head)) == []
    assert active(repo, head) is True


def test_unsigned_template_committed_as_the_real_name_is_rejected_without_network(clone):
    repo, head = clone
    record = json.loads(TEMPLATE.read_text())
    commit_record(repo, record, sign=False)
    assert rc7b.gate_r_active(repo=repo, fetcher=never_called) is False


@pytest.mark.parametrize("mutate,expected", [
    (lambda r: r.update(status="UNSIGNED_TEMPLATE"), "not SIGNED"),
    (lambda r: r.update(scope="FINANCIAL_APPROVAL"), "scope"),
    (lambda r: r.update(schema="finco.rc7b.gate-r-candidate-boundary-authorization.v1"), "schema"),
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
    commit_record(repo, record)                        # re-signed AFTER the defect, so the defect itself is what must be rejected
    problems = rc7b.gate_r_violations(repo=repo, fetcher=never_called)
    assert problems and any(expected in p for p in problems), problems
    assert rc7b.gate_r_active(repo=repo, fetcher=never_called) is False


# ── P0: the Financial Owner must be AUTHENTICATED, not merely named ─────────────

def test_a_record_with_no_attestation_is_rejected(clone):
    repo, head = clone
    record = signed_record(head)
    record.pop("owner_attestation")
    commit_record(repo, record, sign=False)
    assert any("OWNER_ATTESTATION_REQUIRED" in p for p in rc7b.gate_r_violations(repo=repo, fetcher=never_called))


def test_a_signed_status_with_an_empty_or_garbage_signature_is_rejected(clone):
    repo, head = clone
    for sig in (None, "", "SIGNED", "-----BEGIN SSH SIGNATURE-----\nAAAA\n-----END SSH SIGNATURE-----\n"):
        commit_record(repo, signed_record(head), sign=False, post=lambda r, s=sig: r["owner_attestation"].update(signature=s))
        problems = rc7b.gate_r_violations(repo=repo, fetcher=never_called)
        assert any("OWNER_SIGNATURE" in p for p in problems), (sig, problems)
        assert active(repo, head) is False


def test_forged_owner_identity_signed_by_the_implementation_agents_own_key_is_rejected(clone):
    """The record names the registered owner and the owner's key, but is signed with another key: the signature does not match."""
    repo, head = clone
    commit_record(repo, signed_record(head), seed=ATTACKER_SEED)
    problems = rc7b.gate_r_violations(repo=repo, fetcher=never_called)
    assert any("OWNER_SIGNATURE_INVALID" in p and "different key" in p for p in problems), problems
    assert active(repo, head) is False


def test_an_attacker_key_that_is_not_pinned_in_the_reviewed_registry_is_rejected(clone):
    """Even a perfectly valid signature by an unregistered key (the agent controls it) must not authorize anything."""
    repo, head = clone
    record = signed_record(head)
    record["financial_owner"].update(signing_key=ATTACKER_KEY, signing_key_fingerprint=ATTACKER_FP)
    commit_record(repo, record, seed=ATTACKER_SEED)
    problems = rc7b.gate_r_violations(repo=repo, fetcher=never_called)
    assert any("OWNER_KEY_NOT_REGISTERED" in p for p in problems), problems
    assert active(repo, head, owner_keys=[ATTACKER_KEY]) is False          # even if GitHub lists it: the registry pins who may be the owner


def test_an_unregistered_owner_login_is_rejected(clone):
    repo, head = clone
    record = signed_record(head)
    record["financial_owner"]["identity_reference"] = "someone-else"
    commit_record(repo, record)
    assert any("OWNER_NOT_REGISTERED" in p for p in rc7b.gate_r_violations(repo=repo, fetcher=never_called))


def test_an_empty_registry_makes_every_attestation_unverifiable(base_clone):
    repo, head = base_clone
    git(repo, "checkout", "-q", "-B", "empty", head)
    git(repo, "reset", "-q", "--hard", head)
    review_head = git(repo, "rev-parse", "HEAD")
    commit_record(repo, signed_record(review_head))
    problems = rc7b.gate_r_violations(repo=repo, fetcher=never_called)
    assert any("OWNER_NOT_REGISTERED" in p for p in problems), problems


def test_a_missing_or_malformed_registry_is_rejected(clone):
    repo, head = clone
    for text in (None, "not json", json.dumps({"schema": "wrong", "financial_owners": [OWNER_ENTRY]})):
        if text is None:
            git(repo, "rm", "-q", rc7b.GATE_R_REGISTRY)
        else:
            (repo / rc7b.GATE_R_REGISTRY).parent.mkdir(parents=True, exist_ok=True)
            (repo / rc7b.GATE_R_REGISTRY).write_text(text)
            git(repo, "add", rc7b.GATE_R_REGISTRY)
        git(repo, "commit", "-q", "-m", "registry variant", "--allow-empty")
        commit_record(repo, signed_record(head))
        assert rc7b.gate_r_active(repo=repo, fetcher=never_called) is False


@pytest.mark.parametrize("edit", [
    lambda r: r.update(decision_reference="a different decision after signing"),
    lambda r: r["grants"].update(product_admission=True),
    lambda r: r["owner_decisions"].update({"D-03": "DEFERRED"}),
    lambda r: r["github_review"].update(review_id=9999),
    lambda r: r["independent_reviewer"].update(identity_reference="another-reviewer"),
    lambda r: r["financial_owner"].update(name="Owner Human II"),
    lambda r: r["owner_attestation"].update(expires_at_utc=stamp(80)),
    lambda r: r["owner_attestation"].update(attestation_id="b2" * 16),
    lambda r: r["accepted_blobs"].update({"financial_engine/inputs.py": "2" * 40}),
])
def test_any_edit_of_the_record_after_the_owner_signed_invalidates_the_signature(clone, edit):
    repo, head = clone
    commit_record(repo, signed_record(head), post=edit)
    problems = rc7b.gate_r_violations(repo=repo, fetcher=never_called)
    assert any("OWNER_SIGNATURE_INVALID" in p for p in problems), problems


def test_a_signature_for_another_purpose_or_namespace_cannot_be_replayed(clone):
    repo, head = clone
    commit_record(repo, signed_record(head), namespace="git")
    assert any("wrong namespace" in p for p in rc7b.gate_r_violations(repo=repo, fetcher=never_called))
    commit_record(repo, signed_record(head), namespace="finco-rc7b-gate-r-owner-v2")
    assert any("wrong namespace" in p for p in rc7b.gate_r_violations(repo=repo, fetcher=never_called))


def test_a_signature_copied_from_another_record_is_rejected(clone):
    repo, head = clone
    other = signed_record(head)
    other["decision_reference"] = "a different record"
    donor = commit_record(repo, other)["owner_attestation"]["signature"]
    commit_record(repo, signed_record(head), sign=False, post=lambda r: r["owner_attestation"].update(signature=donor))
    assert any("OWNER_SIGNATURE_INVALID" in p for p in rc7b.gate_r_violations(repo=repo, fetcher=never_called))


def test_the_owner_attestation_binds_the_exact_mechanism_not_just_the_record(clone):
    """The owner signed while the mechanism was at one state; any later mechanism change (even if a fresh review of the new head exists) is not authorized."""
    repo, head = clone
    commit_record(repo, signed_record(head))
    assert active(repo, head) is True
    target = repo / "tests/stream_scope_proof.py"
    target.write_text(target.read_text() + "\n# provenance mechanism weakened after the owner signed\n")
    git(repo, "add", "-A")
    git(repo, "commit", "-q", "-m", "mechanism changed after the owner signed")
    new_review_head = git(repo, "rev-parse", "HEAD")
    problems = rc7b.gate_r_violations(repo=repo, fetcher=lambda _p, _o=None: evidence(new_review_head))
    assert any("OWNER_SIGNATURE_INVALID" in p for p in problems), problems


@pytest.mark.parametrize("signed,expires,expected", [
    (-40.0, -10.0, "OWNER_ATTESTATION_EXPIRED"),
    (-0.1, 100.0, "validity must be positive"),
    (-0.1, -0.2, "validity must be positive"),
    (1.0, 30.0, "signed in the future"),
])
def test_expired_overlong_or_future_dated_attestations_are_rejected(clone, signed, expires, expected):
    repo, head = clone
    record = signed_record(head)
    record["owner_attestation"].update(signed_at_utc=stamp(signed), expires_at_utc=stamp(expires))
    commit_record(repo, record)
    problems = rc7b.gate_r_violations(repo=repo, fetcher=never_called)
    assert any(expected in p for p in problems), problems


def test_the_attestation_expires_in_time(clone):
    repo, head = clone
    commit_record(repo, signed_record(head))
    fetch = lambda _p, _o=None: evidence(head)              # noqa: E731
    assert rc7b.gate_r_violations(repo=repo, fetcher=fetch) == []
    later = datetime.now(timezone.utc) + timedelta(days=31)
    assert any("OWNER_ATTESTATION_EXPIRED" in p for p in rc7b.gate_r_violations(repo=repo, fetcher=fetch, now=later))


def test_attestation_id_and_key_format_are_enforced(clone):
    repo, head = clone
    record = signed_record(head)
    record["owner_attestation"]["attestation_id"] = "1"
    commit_record(repo, record)
    assert any("attestation_id" in p for p in rc7b.gate_r_violations(repo=repo, fetcher=never_called))
    record = signed_record(head)
    record["financial_owner"]["signing_key"] = "ssh-rsa AAAAB3NzaC1yc2E"
    commit_record(repo, record)
    assert any("OWNER_KEY_INVALID" in p for p in rc7b.gate_r_violations(repo=repo, fetcher=never_called))
    record = signed_record(head)
    record["financial_owner"]["signing_key_fingerprint"] = ATTACKER_FP
    commit_record(repo, record)
    assert any("fingerprint" in p for p in rc7b.gate_r_violations(repo=repo, fetcher=never_called))


def test_the_owner_key_must_still_be_registered_on_the_owners_github_account(clone):
    repo, head = clone
    commit_record(repo, signed_record(head))
    assert active(repo, head) is True
    for keys in ([], [ATTACKER_KEY], None):
        problems = rc7b.gate_r_violations(repo=repo, fetcher=lambda _p, _o=None, k=keys: {**evidence(head), "owner_signing_keys": k})
        assert any("OWNER_KEY_REVOKED_OR_UNVERIFIABLE" in p for p in problems), (keys, problems)


def test_a_valid_owner_who_is_also_the_pr_author_is_authentic_only_through_the_key(clone):
    """PR authorship proves nothing in either direction. The owner may be the PR author; authority still comes only from the key."""
    repo, head = clone
    record = signed_record(head)
    commit_record(repo, record)
    same = lambda _p, _o=None: {**evidence(head), "pull": {"number": rc7b.GATE_R_PULL_NUMBER, "user": {"login": OWNER}}}   # noqa: E731
    assert rc7b.gate_r_violations(repo=repo, fetcher=same) == []
    commit_record(repo, record, seed=ATTACKER_SEED)                  # the PR author without the key cannot authorize
    assert rc7b.gate_r_active(repo=repo, fetcher=same) is False


# ── review-evidence defects ─────────────────────────────────────────────────────

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
    (lambda c: {**evidence(c), "reviews": [*evidence(c)["reviews"], {"id": 4243, "state": "CHANGES_REQUESTED", "user": {"login": REVIEWER},
                                                                   "author_association": "COLLABORATOR", "commit_id": c}]}, "SUPERSEDED_REVIEW"),
    (lambda c: {**evidence(c), "reviews": [*evidence(c)["reviews"], {"id": 4243, "state": "DISMISSED", "user": {"login": REVIEWER},
                                                                   "author_association": "COLLABORATOR", "commit_id": c}]}, "SUPERSEDED_REVIEW"),
    (lambda c: {**evidence(c), "reviews": [*evidence(c)["reviews"], {"id": "x", "state": "CHANGES_REQUESTED", "user": {"login": REVIEWER},
                                                                   "author_association": "COLLABORATOR", "commit_id": c}]}, "REVIEW_ORDER_UNVERIFIABLE"),
    (lambda c: {**evidence(c), "reviews": [*evidence(c)["reviews"], dict(evidence(c)["reviews"][0])]}, "REVIEW_ORDER_UNVERIFIABLE"),
    (lambda c: {**evidence(c), "reviews": [*evidence(c)["reviews"], {"id": 4000, "state": "COMMENTED", "user": {"login": "x-human"},
                                                                   "author_association": "MEMBER", "commit_id": c,
                                                                   "submitted_at": "2026-10-21T00:00:00Z"}]}, "REVIEW_ORDER_UNVERIFIABLE"),
    (lambda c: {**evidence(c), "reviews": [*evidence(c)["reviews"], {"id": 4300, "state": "CHANGES_REQUESTED", "user": {"login": "maintainer-human"},
                                                                   "author_association": "MEMBER", "commit_id": c,
                                                                   "submitted_at": "2026-10-21T00:00:00Z"}]}, "UNRESOLVED_CHANGES_REQUESTED"),
])
def test_review_evidence_defects_are_each_rejected(clone, make_evidence, expected):
    repo, head = clone
    commit_record(repo, signed_record(head))
    fetch = lambda _p, _o=None: make_evidence(head)         # noqa: E731
    problems = rc7b.gate_r_violations(repo=repo, fetcher=fetch)
    assert problems and any(expected in p for p in problems), problems
    assert rc7b.gate_r_active(repo=repo, fetcher=fetch) is False


def test_a_resolved_or_unauthorized_change_request_from_another_person_does_not_block(clone):
    repo, head = clone
    commit_record(repo, signed_record(head))
    base = evidence(head)
    ok = {**base, "reviews": [*base["reviews"],
                              {"id": 4300, "state": "CHANGES_REQUESTED", "user": {"login": "maintainer-human"}, "author_association": "MEMBER"},
                              {"id": 4301, "state": "DISMISSED", "user": {"login": "maintainer-human"}, "author_association": "MEMBER"},
                              {"id": 4302, "state": "CHANGES_REQUESTED", "user": {"login": "stranger"}, "author_association": "NONE"}]}
    assert rc7b.gate_r_violations(repo=repo, fetcher=lambda _p, _o=None: ok) == []


def test_unreachable_or_failing_github_is_unverifiable_and_rejected(clone):
    repo, head = clone
    commit_record(repo, signed_record(head))
    assert rc7b.gate_r_active(repo=repo, fetcher=lambda _p, _o=None: None) is False
    assert any("UNVERIFIABLE" in p for p in rc7b.gate_r_violations(repo=repo, fetcher=lambda _p, _o=None: None))

    def boom(_pull, _owner=None):
        raise OSError("network down")
    assert rc7b.gate_r_active(repo=repo, fetcher=boom) is False
    for kind in ("RATE_LIMITED", "UNAUTHORIZED", "FORBIDDEN", "MALFORMED", "INCOMPLETE_PAGINATION", "NETWORK"):
        def failing(_pull, _owner=None, k=kind):
            raise rc7b.GateRFetchError(k, "synthetic")
        problems = rc7b.gate_r_violations(repo=repo, fetcher=failing)
        assert any(f"[{kind}]" in p for p in problems), (kind, problems)


def test_a_review_of_the_reviewed_content_survives_later_unrelated_commits_but_not_candidate_changes(clone):
    repo, head = clone
    (repo / "docs" / "unrelated.md").write_text("docs only")
    git(repo, "add", "docs/unrelated.md")
    git(repo, "commit", "-q", "-m", "docs only after the review")
    commit_record(repo, signed_record(head))
    assert active(repo, head) is True
    (repo / "docs" / "unrelated2.md").write_text("more docs after the record")
    git(repo, "add", "docs/unrelated2.md")
    git(repo, "commit", "-q", "-m", "docs only after the record")
    assert active(repo, head) is True                      # documentation-only commits never stale the review or the attestation
    # now a candidate blob changes after the review: content no longer matches, so everything is rejected
    target = repo / "financial_engine/orchestrator.py"
    target.write_text(target.read_text() + "\n# changed after review\n")
    git(repo, "add", "financial_engine/orchestrator.py")
    git(repo, "commit", "-q", "-m", "post-review financial change")
    assert active(repo, head) is False


# ── candidate content is part of Gate R ─────────────────────────────────────────

def _valid_then(repo, head, mutate):
    mutate(repo)
    git(repo, "add", "-A")
    git(repo, "commit", "-q", "-m", "mutation")
    commit_record(repo, signed_record(head))
    return rc7b.gate_r_active(repo=repo, fetcher=lambda _p, _o=None: evidence(head))


@pytest.mark.parametrize("path", rc7b.GATE_R_GOVERNANCE_FILES)
def test_a_change_to_the_gate_r_mechanism_after_the_review_makes_the_review_stale(clone, path):
    repo, head = clone
    commit_record(repo, signed_record(head))
    assert active(repo, head) is True
    target = repo / path
    if path.endswith(".json"):
        data = json.loads(target.read_text())
        data["_note"] = "weakened after review"
        target.write_text(json.dumps(data, indent=2))
    else:
        target.write_text(target.read_text() + "\n# weakened after review\n")
    git(repo, "add", path)
    git(repo, "commit", "-q", "-m", "post-review governance change")
    # the owner attestation covers the mechanism too: the old record no longer verifies ...
    assert any("OWNER_SIGNATURE_INVALID" in p for p in rc7b.gate_r_violations(repo=repo, fetcher=lambda _p, _o=None: evidence(head)))
    # ... and even if the owner re-signs at the new state, the independent review of the OLD mechanism is stale
    commit_record(repo, signed_record(head))
    problems = rc7b.gate_r_violations(repo=repo, fetcher=lambda _p, _o=None: evidence(head))
    assert any("STALE_REVIEW" in p and path in p for p in problems), problems
    assert active(repo, head) is False


def test_review_is_not_circular_with_the_record(clone):
    """The record cites only the review id; the review cites the commit BEFORE the record. The record's own commit never needs to be known."""
    repo, head = clone
    record = signed_record(head)
    assert "commit" not in json.dumps(record["github_review"]).lower()
    commit_record(repo, record)
    record_commit = git(repo, "rev-parse", "HEAD")
    assert record_commit != head
    assert subprocess.run(["git", "merge-base", "--is-ancestor", head, record_commit], cwd=str(repo)).returncode == 0
    assert active(repo, head) is True
    # a review that names the record commit itself is also acceptable only if every blob/governance file is identical (it is): no hash cycle
    assert active(repo, record_commit) is True


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
    assert active(repo, head) is True
    states = rc7b.states(repo=repo)
    assert states["candidate_is_financially_approved"] is False
    assert states["candidate_is_product_admitted"] is False
    assert states["candidate_is_released"] is False


# ── P1: revocation and stale approval cache ─────────────────────────────────────

class Sequence:
    """A mutable GitHub: the default fetcher is replaced by one that returns whatever ``current`` is, and the evidence clock is controlled."""

    def __init__(self, monkeypatch, head):
        self.head, self.now, self.calls, self.current = head, 1000.0, 0, evidence(head)
        monkeypatch.setattr(rc7b, "github_review_fetcher", self._fetch)
        monkeypatch.setattr(rc7b, "_clock", lambda: self.now)

    def _fetch(self, pull_number=None, owner_login=None):
        self.calls += 1
        if isinstance(self.current, Exception):
            raise self.current
        return copy.deepcopy(self.current)

    def advance(self, seconds):
        self.now += seconds

    def expire_cache(self):
        self.advance(rc7b.GATE_R_EVIDENCE_TTL_SECONDS + 1)


@pytest.fixture()
def live(clone, monkeypatch):
    repo, head = clone
    commit_record(repo, signed_record(head))
    return repo, head, Sequence(monkeypatch, head)


def test_cache_1_approved_is_accepted(live):
    repo, head, gh = live
    assert rc7b.gate_r_active(repo=repo) is True


def test_cache_2_approved_then_dismissed_is_rejected(live):
    repo, head, gh = live
    assert rc7b.gate_r_active(repo=repo) is True
    gh.current = evidence(head, state="DISMISSED")
    gh.expire_cache()
    assert rc7b.gate_r_active(repo=repo) is False


def test_cache_3_approved_then_changes_requested_is_rejected(live):
    repo, head, gh = live
    assert rc7b.gate_r_active(repo=repo) is True
    later = evidence(head)
    later["reviews"].append({"id": 4243, "state": "CHANGES_REQUESTED", "user": {"login": REVIEWER}, "author_association": "COLLABORATOR",
                             "submitted_at": "2026-10-20T10:00:00Z"})
    gh.current = later
    gh.expire_cache()
    assert rc7b.gate_r_active(repo=repo) is False


def test_cache_4_approved_then_api_unavailable_is_rejected(live):
    repo, head, gh = live
    assert rc7b.gate_r_active(repo=repo) is True
    gh.current = rc7b.GateRFetchError("NETWORK", "down")
    gh.expire_cache()
    assert rc7b.gate_r_active(repo=repo) is False
    gh.current = rc7b.GateRFetchError("RATE_LIMITED", "HTTP 403")
    assert rc7b.gate_r_active(repo=repo) is False
    assert any("[RATE_LIMITED]" in p for p in rc7b.gate_r_violations(repo=repo))


def test_cache_5_initially_unavailable_then_genuine_approval_is_reevaluated(live):
    repo, head, gh = live
    gh.current = rc7b.GateRFetchError("NETWORK", "down")
    assert rc7b.gate_r_active(repo=repo) is False
    gh.current = evidence(head)                              # no clock advance: a failure is never cached
    assert rc7b.gate_r_active(repo=repo) is True


def test_a_revoked_owner_key_is_rejected_after_the_cache_expires(live):
    repo, head, gh = live
    assert rc7b.gate_r_active(repo=repo) is True
    gh.current = evidence(head, owner_keys=[])
    gh.expire_cache()
    assert rc7b.gate_r_active(repo=repo) is False


def test_fresh_bypasses_the_evidence_cache_at_a_decision_boundary(live):
    repo, head, gh = live
    assert rc7b.gate_r_active(repo=repo) is True
    calls = gh.calls
    assert rc7b.gate_r_active(repo=repo) is True and gh.calls == calls              # within the TTL: evidence reused
    gh.current = evidence(head, state="DISMISSED")
    assert rc7b.gate_r_active(repo=repo, fresh=True) is False                        # decision boundary: rechecked immediately
    assert rc7b.gate_r_active(repo=repo) is False                                    # and the stale positive was dropped


def test_the_evidence_cache_is_bounded_by_the_ttl(live):
    repo, head, gh = live
    assert rc7b.gate_r_active(repo=repo) is True
    gh.advance(rc7b.GATE_R_EVIDENCE_TTL_SECONDS - 1)
    assert rc7b.gate_r_active(repo=repo) is True and gh.calls == 1
    gh.advance(2)
    assert rc7b.gate_r_active(repo=repo) is True and gh.calls == 2
    gh.advance(-10_000)                                                              # a clock that goes backwards is never trusted
    assert rc7b.gate_r_active(repo=repo) is True and gh.calls == 3


def test_an_injected_fetcher_never_uses_or_fills_the_default_cache(live):
    repo, head, gh = live
    assert rc7b.gate_r_active(repo=repo, fetcher=lambda _p, _o=None: evidence(head, state="DISMISSED")) is False
    assert gh.calls == 0 and rc7b.gate_r_active(repo=repo) is True


# ── P1: complete GitHub review history ──────────────────────────────────────────

def paged_http(total, *, last_state="CHANGES_REQUESTED", head="0" * 40, size=100, extra_pages=0, owner_keys=None, bad_page=None):
    """A fake GitHub REST API with ``total`` reviews: #1 is the reviewer's APPROVED review (id 4242), the final one a later review."""
    requested = []
    items = [{"id": 4242, "state": "APPROVED", "user": {"login": REVIEWER}, "author_association": "COLLABORATOR", "commit_id": head,
              "submitted_at": "2026-10-20T09:00:00Z"}]
    for n in range(1, total - 1):
        items.append({"id": 4242 + n, "state": "COMMENTED", "user": {"login": f"commenter-{n}"}, "author_association": "NONE",
                      "submitted_at": "2026-10-20T09:00:00Z"})
    if total > 1:
        items.append({"id": 4242 + total, "state": last_state, "user": {"login": REVIEWER}, "author_association": "COLLABORATOR",
                      "submitted_at": "2026-10-20T10:00:00Z"})

    def http(path):
        requested.append(path)
        if path.endswith(f"/pulls/{rc7b.GATE_R_PULL_NUMBER}"):
            return {"number": rc7b.GATE_R_PULL_NUMBER, "user": {"login": AUTHOR}}
        if "/reviews" in path:
            page = int(re.search(r"[?&]page=(\d+)", path).group(1))
            if bad_page == page:
                return {"message": "not a list"}
            if extra_pages:
                return [dict(items[0], id=10_000 * page + i) for i in range(size)]
            return items[(page - 1) * size: page * size]
        if "/ssh_signing_keys" in path:
            return [{"key": k} for k in (owner_keys if owner_keys is not None else [OWNER_KEY])]
        raise AssertionError(path)
    return http, requested


def test_the_fetcher_reads_every_page_and_the_101st_review_is_seen(clone):
    repo, head = clone
    commit_record(repo, signed_record(head))
    http, requested = paged_http(101, head=head)
    ev = rc7b.github_review_fetcher(320, OWNER, http=http)
    assert len(ev["reviews"]) == 101 and ev["owner_signing_keys"] == [OWNER_KEY]
    assert any("page=2" in p for p in requested)
    problems = rc7b.gate_r_violations(repo=repo, fetcher=lambda _p, _o=None: rc7b.github_review_fetcher(320, OWNER, http=http))
    assert any("SUPERSEDED_REVIEW" in p for p in problems), problems          # APPROVED followed by CHANGES_REQUESTED as the 101st review
    assert any("UNRESOLVED_CHANGES_REQUESTED" in p for p in problems)


def test_a_first_page_only_reader_would_have_been_fooled_and_this_one_is_not(clone):
    repo, head = clone
    commit_record(repo, signed_record(head))
    http, _ = paged_http(101, head=head)
    first_page_only = lambda _p, _o=None: {**rc7b.github_review_fetcher(320, OWNER, http=http), "reviews": http("x/reviews?per_page=100&page=1")[:100]}   # noqa: E731
    assert rc7b.gate_r_violations(repo=repo, fetcher=first_page_only) == []           # the truncated history looks approved ...
    full = lambda _p, _o=None: rc7b.github_review_fetcher(320, OWNER, http=http)         # noqa: E731
    assert rc7b.gate_r_active(repo=repo, fetcher=full) is False                           # ... the complete one is not


@pytest.mark.parametrize("total", [1, 2, 99, 100, 101, 250])
def test_pagination_boundaries_return_exactly_the_whole_history(total):
    http, requested = paged_http(total, last_state="COMMENTED")
    ev = rc7b.github_review_fetcher(320, None, http=http)
    assert len(ev["reviews"]) == total and ev["owner_signing_keys"] is None


def test_exactly_one_hundred_reviews_needs_a_second_empty_page_to_prove_completeness():
    http, requested = paged_http(100, last_state="COMMENTED")
    assert len(rc7b.github_review_fetcher(320, None, http=http)["reviews"]) == 100
    assert any("page=2" in p for p in requested)


def test_incomplete_or_malformed_pagination_fails_closed():
    http, _ = paged_http(10, extra_pages=1)
    with pytest.raises(rc7b.GateRFetchError) as err:
        rc7b.github_review_fetcher(320, None, http=http)
    assert err.value.kind == "INCOMPLETE_PAGINATION"
    http, _ = paged_http(150, bad_page=2)
    with pytest.raises(rc7b.GateRFetchError) as err:
        rc7b.github_review_fetcher(320, None, http=http)
    assert err.value.kind == "MALFORMED"
    http, _ = paged_http(5, owner_keys=[OWNER_KEY] * 100)
    with pytest.raises(rc7b.GateRFetchError) as err:
        rc7b.github_review_fetcher(320, OWNER, http=http)
    assert err.value.kind == "INCOMPLETE_PAGINATION"
    http, _ = paged_http(5)
    with pytest.raises(rc7b.GateRFetchError):
        rc7b.github_review_fetcher(320, "not a login!", http=http)


# ── P1: GitHub API access (read-only; token only when provided; failures classified) ─

class FakeResponse:
    def __init__(self, payload):
        self.payload = payload

    def __enter__(self):
        return self

    def __exit__(self, *exc):
        return False

    def read(self):
        return self.payload if isinstance(self.payload, bytes) else json.dumps(self.payload).encode()


def _http_error(code, headers=None):
    import email.message
    message = email.message.Message()
    for key, value in (headers or {}).items():
        message[key] = value
    return urllib.error.HTTPError("https://api.github.com/x", code, "synthetic", message, None)


@pytest.mark.parametrize("error,kind", [
    (lambda: _http_error(403, {"X-RateLimit-Remaining": "0"}), "RATE_LIMITED"),
    (lambda: _http_error(429), "RATE_LIMITED"),
    (lambda: _http_error(403, {"X-RateLimit-Remaining": "12"}), "FORBIDDEN"),
    (lambda: _http_error(401), "UNAUTHORIZED"),
    (lambda: _http_error(404), "NOT_FOUND"),
    (lambda: _http_error(500), "HTTP_ERROR"),
    (lambda: urllib.error.URLError("dns"), "NETWORK"),
    (lambda: TimeoutError("slow"), "NETWORK"),
])
def test_github_failures_are_classified_and_never_accepted(monkeypatch, error, kind):
    def urlopen(request, timeout=None):
        raise error()
    monkeypatch.setattr("urllib.request.urlopen", urlopen)
    with pytest.raises(rc7b.GateRFetchError) as err:
        rc7b._http_get_json("repos/x/y")
    assert err.value.kind == kind


def test_non_json_github_responses_are_malformed(monkeypatch):
    monkeypatch.setattr("urllib.request.urlopen", lambda request, timeout=None: FakeResponse(b"<html>"))
    with pytest.raises(rc7b.GateRFetchError) as err:
        rc7b._http_get_json("repos/x/y")
    assert err.value.kind == "MALFORMED"


def test_the_token_is_sent_only_as_a_bearer_header_and_never_leaked(monkeypatch):
    seen = []

    def urlopen(request, timeout=None):
        seen.append(request)
        if len(seen) == 2:
            raise _http_error(401)
        return FakeResponse({"ok": True})
    monkeypatch.setattr("urllib.request.urlopen", urlopen)
    monkeypatch.delenv("GH_TOKEN", raising=False)
    monkeypatch.setenv("GITHUB_TOKEN", "synthetic-token-value")
    assert rc7b._http_get_json("repos/x/y") == {"ok": True}
    assert seen[0].get_header("Authorization") == "Bearer synthetic-token-value"
    assert seen[0].get_method() == "GET" and seen[0].data is None                      # read-only
    with pytest.raises(rc7b.GateRFetchError) as err:
        rc7b._http_get_json("repos/x/y")
    assert "synthetic-token-value" not in str(err.value)
    monkeypatch.delenv("GITHUB_TOKEN")
    seen.clear()
    rc7b._http_get_json("repos/x/y")
    assert seen[0].get_header("Authorization") is None


def test_no_workflow_grants_the_validator_write_access_or_a_token():
    """Documented, verified behaviour: the test job passes no token (unauthenticated read-only calls) and its token is contents:read."""
    text = (ROOT / ".github/workflows/ci_public_job.yml").read_text()
    assert "permissions:\n  contents: read" in text
    assert "GITHUB_TOKEN" not in text and "pull-requests: write" not in text and "contents: write" not in text


# ── owner-attestation primitives ────────────────────────────────────────────────

def test_ed25519_matches_the_rfc_8032_vectors():
    seed = bytes.fromhex("9d61b19deffd5a60ba844af492ec2cc44449c5697b326919703bac031cae7f60")
    assert ssh.public_key(seed).hex() == "d75a980182b10ab7d54bfed3c964073a0ee172f3daa62325af021a68f707511a"
    sig = ssh.sign(seed, b"")
    assert sig.hex() == ("e5564300c360ac729086e2cc806e828a84877f1eb8e5d974d873e065224901555fb8821590a33bacc61e39701cf9b46bd25bf5f0595bbe24655141438e7a100b")
    assert ssh.verify(ssh.public_key(seed), b"", sig) and not ssh.verify(ssh.public_key(seed), b"x", sig)
    seed2 = bytes.fromhex("4ccd089b28ff96da9db6c346ec114e0f5b8a319f35aba624da8cf6ed4fb8a6fb")
    assert ssh.public_key(seed2).hex() == "3d4017c3e843895a92b70aa74d1b7ebc9c982ccf2ec4968cc0cd55f12af4660c"
    assert ssh.sign(seed2, bytes.fromhex("72")).hex().startswith("92a009a9f0d4cab8720e820b5f642540a2b27b5416503f8fb3762223ebdb69da")


def test_ed25519_agrees_with_an_independent_implementation_when_available():
    cryptography = pytest.importorskip("cryptography.hazmat.primitives.asymmetric.ed25519")
    key = cryptography.Ed25519PrivateKey.from_private_bytes(OWNER_SEED)
    for message in (b"", b"a", b"gate r" * 50):
        assert key.sign(message) == ssh.sign(OWNER_SEED, message)


def test_the_verifier_rejects_hostile_input_without_raising():
    good = ssh.make_signature(OWNER_SEED, b"payload", NS)
    assert ssh.verification_problems(good, b"payload", NS, OWNER_KEY) == []
    hostile = [None, 5, "", "garbage", good.replace("SSH SIGNATURE", "X"), good[:-30], good.replace("A", "B", 3), good + "trailing",
               "-----BEGIN SSH SIGNATURE-----\n!!!!\n-----END SSH SIGNATURE-----\n"]
    for item in hostile:
        assert ssh.verification_problems(item, b"payload", NS, OWNER_KEY), item
    for key in (None, "", "ssh-rsa AAAA", "ssh-ed25519", "ssh-ed25519 AAAA", ATTACKER_KEY):
        assert ssh.verification_problems(good, b"payload", NS, key), key
    assert ssh.verification_problems(good, "not bytes", NS, OWNER_KEY)
    assert ssh.verification_problems(good, b"payload2", NS, OWNER_KEY)
    sha256 = ssh.make_signature(OWNER_SEED, b"payload", NS, "sha256")
    assert ssh.verification_problems(sha256, b"payload", NS, OWNER_KEY) == []
    assert ssh.verification_problems(ssh.make_signature(OWNER_SEED, b"payload", NS, "sha512"), b"payload", NS + "x", OWNER_KEY)


@pytest.mark.skipif(shutil.which("ssh-keygen") is None, reason="ssh-keygen not installed")
def test_interoperates_with_real_openssh(tmp_path):
    key = tmp_path / "owner"
    subprocess.run(["ssh-keygen", "-q", "-t", "ed25519", "-N", "", "-C", "synthetic", "-f", str(key)], check=True)
    pub = (tmp_path / "owner.pub").read_text().strip()
    payload = tmp_path / "payload.bin"
    payload.write_bytes(b"real openssh payload")
    subprocess.run(["ssh-keygen", "-Y", "sign", "-q", "-n", NS, "-f", str(key), str(payload)], check=True)
    assert ssh.verification_problems((tmp_path / "payload.bin.sig").read_text(), payload.read_bytes(), NS, pub) == []
    # and a signature made by this module is accepted by real OpenSSH
    signature = tmp_path / "ours.sig"
    signature.write_text(ssh.make_signature(OWNER_SEED, b"ours", NS))
    allowed = tmp_path / "allowed"
    allowed.write_text(f'{OWNER} namespaces="{NS}" {OWNER_KEY}\n')
    done = subprocess.run(["ssh-keygen", "-Y", "verify", "-f", str(allowed), "-I", OWNER, "-n", NS, "-s", str(signature)],
                          input=b"ours", capture_output=True)
    assert done.returncode == 0, done.stderr


def test_the_owner_payload_cli_prints_exactly_the_bytes_that_must_be_signed(clone, tmp_path):
    repo, head = clone
    record = signed_record(head)
    path = tmp_path / "record.json"
    path.write_text(json.dumps(record))
    out = subprocess.run(["python3", str(repo / "tests/rc7b_quarterly_candidate_authority.py"), "owner-payload", str(path)], cwd=str(repo),
                         capture_output=True, check=True).stdout
    assert out == rc7b.owner_payload(record, mechanism_at(repo))
    # the payload is independent of any signature already present
    signed = copy.deepcopy(record)
    signed["owner_attestation"]["signature"] = "something"
    assert rc7b.owner_payload(signed, mechanism_at(repo)) == out
