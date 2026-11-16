"""CI V5-3 gate: pure decision logic, authorization attacks, enforcement verification, V4 linkage, the gate end-to-end on synthetic repositories, the
``pull_request_target`` workflow's structure and the repository's own epoch checkpoint. Hermetic (temporary Git repositories, synthetic fixtures; the signed
approval test generates a THROWAWAY test key only where ``ssh-keygen`` exists; no real owner key is ever read or created).

Claim boundary: this proves the gate's LOGIC. It proves nothing about GitHub settings (enforcement is ``ENFORCEMENT_UNVERIFIED`` until the owner's read) and
nothing about a live ``pull_request_target`` run, which can only exist after this file is on the protected branch.
"""
import json
import os
import shutil
import subprocess
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "tools"))
import ci_v5_epoch as E          # noqa: E402
import ci_v5_shadow as SH        # noqa: E402

POLICY = E.POLICY
HEAD = "a" * 40
OWNER_B = "owner-b"
AUTHOR = "author-a"


# ---------------------------------------------------------------------------------------------------------------------------------- authorization
def review(user, state="APPROVED", commit=HEAD, assoc="COLLABORATOR", at="2026-11-16T10:00:00Z"):
    return {"user": {"login": user}, "state": state, "commit_id": commit, "author_association": assoc, "submitted_at": at}


def auth(reviews, **kw):
    return SH.authorize_reviews(reviews, kw.pop("author", AUTHOR), kw.pop("head", HEAD), approvers=kw.pop("approvers", (OWNER_B,)))


def test_no_configured_approver_is_blocked_never_a_default_allow():
    assert POLICY.APPROVERS == () and POLICY.ALLOWED_SIGNERS == ()                       # nothing is configured in trusted code yet: authorization cannot open
    assert SH.authorize_reviews([review(OWNER_B)], AUTHOR, HEAD) == ("AUTHORIZATION_BLOCKED", ["NO_APPROVER_CONFIGURED"])
    assert SH.verify_signed_head(".", HEAD)[0] == "AUTHORIZATION_BLOCKED"


@pytest.mark.parametrize("name,reviews,kw,state,fragment", [
    ("independent_approval_at_exact_head", [review(OWNER_B)], {}, "AUTHORIZATION_APPROVED", "APPROVED_AT_EXACT_HEAD"),
    ("author_self_approval", [review(AUTHOR)], {"approvers": (AUTHOR,)}, "AUTHORIZATION_BLOCKED", "SELF_REVIEW_IGNORED"),
    ("author_self_approval_case_change", [review(AUTHOR.upper())], {"approvers": (AUTHOR,)}, "AUTHORIZATION_BLOCKED", "SELF_REVIEW_IGNORED"),
    ("stale_review_other_sha", [review(OWNER_B, commit="b" * 40)], {}, "AUTHORIZATION_BLOCKED", "STALE_OR_OTHER_SHA_APPROVAL"),
    ("approval_made_before_latest_push", [review(OWNER_B, commit="c" * 40)], {}, "AUTHORIZATION_BLOCKED", "STALE_OR_OTHER_SHA_APPROVAL"),
    ("approval_of_a_different_delta_is_a_different_head", [review(OWNER_B, commit="d" * 40)], {}, "AUTHORIZATION_BLOCKED", "STALE_OR_OTHER_SHA_APPROVAL"),
    ("compromised_ci_token_actions_bot", [review("github-actions[bot]", assoc="NONE")], {}, "AUTHORIZATION_BLOCKED", "NOT_AN_ALLOW_LISTED_APPROVER"),
    ("random_user_approval", [review("someone-else")], {}, "AUTHORIZATION_BLOCKED", "NOT_AN_ALLOW_LISTED_APPROVER"),
    ("allow_listed_login_without_repo_association", [review(OWNER_B, assoc="NONE")], {}, "AUTHORIZATION_BLOCKED", "REVIEWER_ASSOCIATION_NOT_ACCEPTED"),
    ("dismissed_approval", [review(OWNER_B), review(OWNER_B, state="DISMISSED", at="2026-11-16T11:00:00Z")], {}, "AUTHORIZATION_BLOCKED", "APPROVAL_DISMISSED"),
    ("later_changes_requested_wins", [review(OWNER_B), review(OWNER_B, state="CHANGES_REQUESTED", at="2026-11-16T11:00:00Z")], {}, "AUTHORIZATION_DENIED", "CHANGES_REQUESTED_BY"),
    ("approve_then_request_changes_then_reapprove", [review(OWNER_B), review(OWNER_B, state="CHANGES_REQUESTED", at="2026-11-16T11:00:00Z"),
                                                      review(OWNER_B, at="2026-11-16T12:00:00Z")], {}, "AUTHORIZATION_APPROVED", "APPROVED_AT_EXACT_HEAD"),
    ("no_review_at_all", [], {}, "AUTHORIZATION_BLOCKED", "NO_APPROVAL_AT_EXACT_HEAD"),
    ("comment_only_review_is_nothing", [review(OWNER_B, state="COMMENTED")], {}, "AUTHORIZATION_BLOCKED", "NO_APPROVAL_AT_EXACT_HEAD"),
    ("malformed_review_payload", "not a list", {}, "AUTHORIZATION_BLOCKED", "REVIEW_EVIDENCE_UNAVAILABLE"),
    ("none_review_payload", None, {}, "AUTHORIZATION_BLOCKED", "REVIEW_EVIDENCE_UNAVAILABLE"),
    ("bad_head_sha", [review(OWNER_B)], {"head": "HEAD"}, "AUTHORIZATION_BLOCKED", "REVIEW_EVIDENCE_UNAVAILABLE"),
])
def test_review_authorization_attacks(name, reviews, kw, state, fragment):
    got, reasons = auth(reviews, **kw)
    assert got == state and any(fragment in r for r in reasons), (name, got, reasons)


def test_an_unrelated_approver_cannot_launder_a_self_approval():
    got, _r = auth([review(AUTHOR), review("someone-else")], approvers=(AUTHOR, OWNER_B))
    assert got == "AUTHORIZATION_BLOCKED"
    got, _r = auth([review(AUTHOR), review(OWNER_B)], approvers=(AUTHOR, OWNER_B))
    assert got == "AUTHORIZATION_APPROVED"


# ---- option B: owner-signed approval commit
def test_signed_head_logic_with_an_injected_verifier():
    ok = lambda *args: ("G\0owner-signer\0" + HEAD + "\n").encode()
    signers = (("owner-signer", "ssh-ed25519 AAAAC3NzaC1lZDI1NTE5AAAAItest"),)
    assert SH.verify_signed_head(".", HEAD, signers, runner=ok) == ("AUTHORIZATION_APPROVED", ["SIGNED_BY:owner-signer"])
    for out, why in ((b"N\0\0" + HEAD.encode(), "SIGNATURE_STATUS_N"), (b"B\0owner-signer\0" + HEAD.encode(), "SIGNATURE_STATUS_B"),
                     (b"U\0owner-signer\0" + HEAD.encode(), "SIGNATURE_STATUS_U"), (b"E\0owner-signer\0" + HEAD.encode(), "SIGNATURE_STATUS_E")):
        assert SH.verify_signed_head(".", HEAD, signers, runner=lambda *a, out=out: out)[1] == [why]
    assert SH.verify_signed_head(".", HEAD, signers, runner=lambda *a: b"G\0someone-else\0" + HEAD.encode())[1] == ["SIGNER_NOT_ALLOW_LISTED_OR_OTHER_COMMIT"]
    assert SH.verify_signed_head(".", HEAD, signers, runner=lambda *a: b"G\0owner-signer\0" + b"e" * 40)[1] == ["SIGNER_NOT_ALLOW_LISTED_OR_OTHER_COMMIT"]   # another commit
    def boom(*a):
        raise OSError("no ssh-keygen")
    assert SH.verify_signed_head(".", HEAD, signers, runner=boom)[1] == ["SIGNATURE_VERIFICATION_ERROR"]
    for bad in ((("owner signer", "ssh-ed25519 AAAA"),), (("owner", "ssh-rsa AAAA"),), (("owner", "ssh-ed25519 AAAA\nssh-ed25519 BBBB"),), (("o;rm", "ssh-ed25519 AAAA"),)):
        assert SH.verify_signed_head(".", HEAD, bad, runner=ok)[1] == ["MALFORMED_SIGNER_POLICY"]
    assert SH.verify_signed_head(".", "not-a-sha", signers, runner=ok)[1] == ["BAD_HEAD_SHA"]


def _git_env(tmp):
    env = {k: v for k, v in os.environ.items() if k in ("PATH", "LANG", "TMPDIR")}
    env.update(GIT_CONFIG_GLOBAL=os.devnull, GIT_CONFIG_NOSYSTEM="1", HOME=str(tmp))
    return env


def test_signed_head_with_real_ssh_signatures_where_the_tool_exists(tmp_path):
    """Real throwaway keys when ``ssh-keygen`` is present (hosted runners); where it is absent the verifier must fail CLOSED (never a pass) - asserted instead of skipped."""
    signers = (("owner-signer", "ssh-ed25519 AAAAC3NzaC1lZDI1NTE5AAAAItest"),)
    if shutil.which("ssh-keygen") is None:
        assert SH.verify_signed_head(str(tmp_path), HEAD, signers) == ("AUTHORIZATION_BLOCKED", ["SIGNATURE_VERIFIER_UNAVAILABLE"])
        return
    env = _git_env(tmp_path)

    def run(*a, cwd=tmp_path):
        return subprocess.run(a, cwd=cwd, env=env, capture_output=True, text=True, check=True).stdout.strip()
    keys = {}
    for who in ("owner", "other"):
        run("ssh-keygen", "-q", "-t", "ed25519", "-N", "", "-f", str(tmp_path / who), "-C", who + "-test")
        keys[who] = " ".join((tmp_path / (who + ".pub")).read_text().split()[:2])
    repo = tmp_path / "r"
    repo.mkdir()
    run("git", "init", "-q", "-b", "main", cwd=repo)
    run("git", "config", "user.name", "t", cwd=repo)
    run("git", "config", "user.email", "t@test.invalid", cwd=repo)
    run("git", "config", "gpg.format", "ssh", cwd=repo)
    (repo / "f").write_text("x\n")
    run("git", "add", "f", cwd=repo)

    def commit(key, msg, sign=True):
        run("git", "config", "user.signingkey", str(tmp_path / (key + ".pub")), cwd=repo)
        run("git", "commit", "-q", "--allow-empty", "-m", msg, *(["-S"] if sign else []), cwd=repo)
        return run("git", "rev-parse", "HEAD", cwd=repo)
    allowed = (("owner-signer", keys["owner"]),)
    good = commit("owner", "owner signed approval")
    assert SH.verify_signed_head(str(repo), good, allowed)[0] == "AUTHORIZATION_APPROVED"
    assert SH.verify_signed_head(str(repo), good, (("owner-signer", keys["other"]),))[0] == "AUTHORIZATION_BLOCKED"        # key not allow-listed
    foreign = commit("other", "signed by a key that is not allow-listed")
    assert SH.verify_signed_head(str(repo), foreign, allowed)[0] == "AUTHORIZATION_BLOCKED"
    unsigned = commit("owner", "unsigned", sign=False)
    assert SH.verify_signed_head(str(repo), unsigned, allowed)[0] == "AUTHORIZATION_BLOCKED"                              # unsigned
    run("git", "reset", "-q", "--soft", "HEAD~3", cwd=repo)                                                                # forge: re-commit the same content, unsigned
    forged = commit("owner", "owner signed approval", sign=False)
    assert forged != good and SH.verify_signed_head(str(repo), forged, allowed)[0] == "AUTHORIZATION_BLOCKED"              # the signature binds the exact commit


# ---------------------------------------------------------------------------------------------------------------------------------- V4 linkage
def cr(name, status="completed", conclusion="success", head=HEAD, at="2026-11-16T12:00:00Z"):
    return {"name": name, "status": status, "conclusion": conclusion, "head_sha": head, "completed_at": at}


def all_green(head=HEAD):
    return [cr(n, head=head) for n in POLICY.V4_REQUIRED_CHECKS]


def test_v4_linkage_requires_every_required_check_green_at_the_exact_head():
    assert SH.v4_linkage(all_green(), HEAD) == (True, [])
    runs = all_green()
    assert SH.v4_linkage(runs[1:], HEAD)[1] == ["MISSING:" + POLICY.V4_REQUIRED_CHECKS[0]]
    for status, conclusion in (("completed", "failure"), ("completed", "skipped"), ("completed", "neutral"), ("completed", "cancelled"), ("completed", "timed_out"),
                               ("in_progress", None), ("queued", None)):
        runs = all_green()
        runs[2] = cr(POLICY.V4_REQUIRED_CHECKS[2], status, conclusion)
        ok, find = SH.v4_linkage(runs, HEAD)
        assert not ok and find[0].startswith("NOT_SUCCESS:" + POLICY.V4_REQUIRED_CHECKS[2]), (status, conclusion)
    assert SH.v4_linkage(all_green(head="b" * 40), HEAD)[0] is False                                       # green for ANOTHER sha
    stale_then_red = all_green() + [cr(POLICY.V4_REQUIRED_CHECKS[0], conclusion="failure", at="2026-11-16T13:00:00Z")]
    assert SH.v4_linkage(stale_then_red, HEAD)[0] is False                                                  # the latest run of a name decides
    red_then_green = [cr(POLICY.V4_REQUIRED_CHECKS[0], conclusion="failure", at="2026-11-16T11:00:00Z")] + all_green()
    assert SH.v4_linkage(red_then_green, HEAD)[0] is True
    assert SH.v4_linkage(None, HEAD) == (False, ["CHECK_RUN_EVIDENCE_UNAVAILABLE"])
    assert SH.v4_linkage([cr(POLICY.GATE_CHECK_NAME)], HEAD)[0] is False                                    # the gate's own check is not a V4 check
    assert SH.v4_linkage([cr("V5 shadow (a generated status message)")] + all_green()[:3], HEAD)[0] is False


# ---------------------------------------------------------------------------------------------------------------------------------- enforcement
def good_protection():
    contexts = [POLICY.GATE_CHECK_NAME, *POLICY.V4_REQUIRED_CHECKS]
    return {"required_status_checks": {"strict": True, "contexts": contexts, "checks": [{"context": c, "app_id": 15368} for c in contexts]},
            "enforce_admins": {"enabled": True},
            "required_pull_request_reviews": {"require_code_owner_reviews": True, "dismiss_stale_reviews": True, "require_last_push_approval": True, "required_approving_review_count": 1}}


def test_enforcement_is_unverified_without_a_read_and_incomplete_without_every_piece():
    assert SH.verify_enforcement(None, None) == ("ENFORCEMENT_UNVERIFIED", ["PROTECTION_AND_RULESETS_NOT_READ"])           # HTTP 403: nothing is inferred
    assert SH.verify_enforcement(good_protection(), []) == ("ENFORCEMENT_VERIFIED", [])
    muts = {
        "gate_not_required": lambda p: p["required_status_checks"].update(contexts=list(POLICY.V4_REQUIRED_CHECKS), checks=[]),
        "v4_check_dropped": lambda p: p["required_status_checks"].update(contexts=[c for c in p["required_status_checks"]["contexts"] if c != "CI V4 gate"], checks=[]),
        "not_strict": lambda p: p["required_status_checks"].update(strict=False),
        "admins_not_enforced": lambda p: p["enforce_admins"].update(enabled=False),
        "no_code_owner_review": lambda p: p["required_pull_request_reviews"].update(require_code_owner_reviews=False),
        "stale_not_dismissed": lambda p: p["required_pull_request_reviews"].update(dismiss_stale_reviews=False),
        "no_last_push_approval": lambda p: p["required_pull_request_reviews"].update(require_last_push_approval=False),
        "zero_required_reviews": lambda p: p["required_pull_request_reviews"].update(required_approving_review_count=0),
        "no_review_section": lambda p: p.pop("required_pull_request_reviews"),
    }
    for name, mut in muts.items():
        p = good_protection()
        mut(p)
        state, find = SH.verify_enforcement(p, [])
        assert state == "ENFORCEMENT_INCOMPLETE" and find, name
    assert SH.verify_enforcement({}, [])[0] == "ENFORCEMENT_INCOMPLETE"
    # a workflow that exists, ran and is green proves nothing: only the settings read does
    assert SH.verify_enforcement({"required_status_checks": {"strict": True, "contexts": list(POLICY.V4_REQUIRED_CHECKS)}}, None)[1][0].startswith("GATE_NOT_REQUIRED")


def test_enforcement_from_rulesets_requires_the_same_pieces():
    rules = [{"type": "required_status_checks", "parameters": {"strict_required_status_checks_policy": True,
                                                              "required_status_checks": [{"context": c} for c in (POLICY.GATE_CHECK_NAME, *POLICY.V4_REQUIRED_CHECKS)]}},
             {"type": "pull_request", "parameters": {"require_code_owner_review": True, "dismiss_stale_reviews_on_push": True, "require_last_push_approval": True,
                                                      "required_approving_review_count": 1}}]
    assert SH.verify_enforcement(None, rules) == ("ENFORCEMENT_VERIFIED", [])
    broken = json.loads(json.dumps(rules))
    broken[0]["parameters"]["required_status_checks"].pop(0)
    assert SH.verify_enforcement(None, broken)[0] == "ENFORCEMENT_INCOMPLETE"


def test_enforcement_cli_exit_codes(tmp_path):
    prot = tmp_path / "p.json"
    prot.write_text(json.dumps(good_protection()))
    out = tmp_path / "o.json"
    assert SH.main(["enforcement", "--protection-json", str(prot), "--rules-json", str(prot.parent / "none.json"), "--output", str(out)]) == 0
    assert json.loads(out.read_text())["enforcement"] == "ENFORCEMENT_VERIFIED"
    assert SH.main(["enforcement", "--output", str(out)]) == 1 and json.loads(out.read_text())["enforcement"] == "ENFORCEMENT_UNVERIFIED"


# ---------------------------------------------------------------------------------------------------------------------------------- the decision table
def v5rec(integrity="INTEGRITY_PASS", unknowns=(), failures=(), epoch="TRUSTED_BASE", base="VERIFIED_TIP", guard="ALL_TRACKED", transition="NONE"):
    return {"integrity": integrity, "unknowns": [{"code": c, "detail": ""} for c in unknowns], "failures": [{"code": c, "detail": ""} for c in failures],
            "transition": transition, "trust": {"epoch_state": epoch, "base_state": base, "guard_mode": guard}}


@pytest.mark.parametrize("name,v5,authz,v4,kw,decision", [
    ("integrity_pass_and_authorized", v5rec(), "AUTHORIZATION_APPROVED", False, {}, "INTEGRITY_PASS_AUTHORIZED"),
    ("integrity_pass_needs_no_v4_linkage", v5rec(), "AUTHORIZATION_APPROVED", False, {}, "INTEGRITY_PASS_AUTHORIZED"),
    ("integrity_pass_without_authorization", v5rec(), "AUTHORIZATION_BLOCKED", True, {}, "BLOCK"),
    ("integrity_pass_denied", v5rec(), "AUTHORIZATION_DENIED", True, {}, "BLOCK"),
    ("integrity_fail_never_opens", v5rec("INTEGRITY_FAIL", failures=("UNDECLARED_CHANGE",)), "AUTHORIZATION_APPROVED", True, {}, "BLOCK"),
    ("semantic_gap_deferred_to_v4", v5rec("UNKNOWN", unknowns=("SEMANTIC_INVARIANT_NOT_EVALUATED",)), "AUTHORIZATION_APPROVED", True, {}, "DEFERRED_TO_V4_VERIFIED"),
    ("semantic_gap_without_v4_at_head", v5rec("UNKNOWN", unknowns=("SEMANTIC_INVARIANT_NOT_EVALUATED",)), "AUTHORIZATION_APPROVED", False, {}, "BLOCK"),
    ("semantic_gap_without_authorization", v5rec("UNKNOWN", unknowns=("SEMANTIC_INVARIANT_NOT_EVALUATED",)), "AUTHORIZATION_BLOCKED", True, {}, "BLOCK"),
    ("unknown_for_another_reason_is_not_deferrable", v5rec("UNKNOWN", unknowns=("SEMANTIC_INVARIANT_NOT_EVALUATED", "EPOCH_FULL_PROVENANCE_NOT_GREEN")), "AUTHORIZATION_APPROVED", True, {}, "BLOCK"),
    ("raw_unknown_never_a_pass", v5rec("UNKNOWN", unknowns=("NO_TRUSTED_EPOCH",)), "AUTHORIZATION_APPROVED", True, {}, "BLOCK"),
    ("untrusted_tool_unknown", v5rec("UNKNOWN", unknowns=("UNTRUSTED_TOOL_SOURCE",)), "AUTHORIZATION_APPROVED", True, {}, "BLOCK"),
    ("candidate_epoch", v5rec(epoch="CANDIDATE_UNTRUSTED"), "AUTHORIZATION_APPROVED", True, {}, "BLOCK"),
    ("no_epoch", v5rec(epoch="NO_EPOCH"), "AUTHORIZATION_APPROVED", True, {}, "BLOCK"),
    ("base_is_not_the_tip", v5rec(base="UNVERIFIED"), "AUTHORIZATION_APPROVED", True, {}, "BLOCK"),
    ("legacy_narrow_guard", v5rec(guard="LEGACY_NARROW_GUARD"), "AUTHORIZATION_APPROVED", True, {}, "BLOCK"),
    ("promotion_pr_can_never_open", v5rec("UNKNOWN", unknowns=("PROMOTION_REQUIRES_OWNER",), transition="PROMOTION_REQUIRES_OWNER"), "AUTHORIZATION_APPROVED", True, {}, "BLOCK"),
    ("head_ref_mismatch", v5rec(), "AUTHORIZATION_APPROVED", True, {"head_matches": False}, "BLOCK"),
    ("untrusted_tool_source_flag", v5rec(), "AUTHORIZATION_APPROVED", True, {"tool_source_trusted": False}, "BLOCK"),
    ("unrecognised_integrity", v5rec("PASS"), "AUTHORIZATION_APPROVED", True, {}, "BLOCK"),
    ("missing_trust_block", {"integrity": "INTEGRITY_PASS", "unknowns": [], "failures": []}, "AUTHORIZATION_APPROVED", True, {}, "BLOCK"),
])
def test_decision_table_never_opens_on_unknown_missing_or_ambiguous_evidence(name, v5, authz, v4, kw, decision):
    got, reasons = SH.decide(v5, authz, v4, **kw)
    assert got == decision and reasons, (name, got, reasons)
    assert got in ("INTEGRITY_PASS_AUTHORIZED", "DEFERRED_TO_V4_VERIFIED", "BLOCK") and "PASS" != got


# ---------------------------------------------------------------------------------------------------------------------------------- the gate end to end
class Repo:
    def __init__(self, path):
        self.path = Path(path)
        self.path.mkdir(parents=True, exist_ok=True)
        self.git("init", "-q", "-b", "main")

    def git(self, *a):
        p = subprocess.run(["git", "-c", "user.name=t", "-c", "user.email=t\x40test.invalid", "-c", "commit.gpgsign=false", *a], cwd=self.path, capture_output=True, text=True)
        assert p.returncode == 0, (a, p.stderr)
        return p.stdout.strip()

    def write(self, rel, text):
        f = self.path / rel
        f.parent.mkdir(parents=True, exist_ok=True)
        f.write_text(text)

    def commit(self, msg="c"):
        self.git("add", "-A")
        self.git("commit", "-q", "--allow-empty", "-m", msg)
        return self.git("rev-parse", "HEAD")

    def checkout(self, sha):
        self.git("checkout", "-q", "--detach", sha)
        self.git("reset", "-q", "--hard", sha)
        self.git("clean", "-fdxq")


SEMANTIC_LITERAL = "app/library/router.py"


@pytest.fixture(scope="module")
def world(tmp_path_factory):
    r = Repo(tmp_path_factory.mktemp("v5g"))
    for rel, text in {"app/main.py": "MAIN = 1\n", "app/util.py": "UTIL = 1\n", SEMANTIC_LITERAL: "ROUTER = 1\n", "financial_engine/calc.py": "CALC = 1\n", "README.md": "x\n",
                      "tests/test_calc.py": "def test_calc():\n    assert True\n", ".gitignore": "__pycache__/\n"}.items():
        r.write(rel, text)
    e_sha = r.commit("accepted main E")
    git = E.Git(r.path)
    r.write(E.TRUSTED_EPOCH_PATH, E.canonical(E.make_epoch(git, e_sha, full_run={"status": "PASS", "run_id": "1", "sha": e_sha})).decode())
    m_sha = r.commit("trusted epoch accepted")                    # the trusted base tip M carries a GREEN-witnessed epoch
    r.checkout(e_sha)
    r.write(E.TRUSTED_EPOCH_PATH, E.canonical(E.make_epoch(git, e_sha, full_run={"status": "FULL_PROVENANCE_BLOCKED", "reason": "TIMEOUT", "sha": e_sha})).decode())
    blocked_tip = r.commit("epoch with a BLOCKED FULL witness accepted")
    r.checkout(m_sha)
    return {"r": r, "M": m_sha, "B": blocked_tip, "E": e_sha}


def make_head(w, base, files, delete=(), declare=True):
    r = w["r"]
    r.checkout(base)
    for rel, text in files.items():
        r.write(rel, text)
    for rel in delete:
        r.git("rm", "-q", rel)
    pre = r.commit("change")
    if declare:
        delta = E.make_delta(E.read_inventory(E.Git(r.path), base), E.read_inventory(E.Git(r.path), pre), base, r.git("rev-parse", base + "^{tree}"))
        r.write(E.DELTA_PATH, E.canonical(delta).decode())
        pre = r.commit("delta")
    r.git("update-ref", "refs/remotes/pr/head", pre)
    return pre


def run_gate(w, tmp_path, head, base, reviews, runs=None, *, author=AUTHOR, provenance="TRUSTED_BASE", head_ref=None, approvers=(OWNER_B,), monkeypatch=None):
    out = tmp_path / ("out_" + head[:8] + "_" + str(len(list(tmp_path.iterdir()))))
    out.mkdir()
    (out / "reviews.json").write_text(json.dumps(reviews))
    (out / "runs.json").write_text(json.dumps(all_green(head) if runs is None else runs))
    if monkeypatch is not None:
        monkeypatch.setattr(POLICY, "APPROVERS", approvers)
    rc = SH.main(["gate", "--repo", str(w["r"].path), "--head-sha", head, "--head-ref", head_ref or "refs/remotes/pr/head", "--base-tip-sha", base, "--pr-author", author,
                  "--reviews-json", str(out / "reviews.json"), "--check-runs-json", str(out / "runs.json"), "--tools-provenance", provenance, "--out-dir", str(out)])
    return rc, json.loads((out / "gate_decision.json").read_text())


def test_gate_opens_for_an_exactly_declared_nonsemantic_change_with_independent_approval(world, tmp_path, monkeypatch):
    head = make_head(world, world["M"], {"app/util.py": "UTIL = 2\n", "README.md": "changed\n"})
    rc, rec = run_gate(world, tmp_path, head, world["M"], [review(OWNER_B, commit=head)], monkeypatch=monkeypatch)
    assert rc == 0 and rec["decision"] == "INTEGRITY_PASS_AUTHORIZED" and rec["integrity"] == "INTEGRITY_PASS" and rec["authorization"] == "AUTHORIZATION_APPROVED", rec
    assert rec["enforcement"] == "ENFORCEMENT_UNVERIFIED" and rec["authorization_source"] == "REVIEW" and rec["tool_source"] == "TRUSTED_BASE"
    assert rec["head_sha"] == head and rec["base_tip_sha"] == world["M"] and rec["epoch_sha"] == world["E"] and rec["delta_digest"]


def test_gate_authorization_attacks_all_block(world, tmp_path, monkeypatch):
    head = make_head(world, world["M"], {"app/util.py": "UTIL = 3\n"})
    attacks = {
        "no_review": [],
        "author_self_approval": [review(AUTHOR, commit=head)],
        "approval_of_the_previous_head": [review(OWNER_B, commit="1" * 40)],
        "actions_bot_approval": [review("github-actions[bot]", commit=head, assoc="NONE")],
        "approval_then_dismissed": [review(OWNER_B, commit=head), review(OWNER_B, state="DISMISSED", commit=head, at="2026-11-16T11:00:00Z")],
    }
    for name, reviews in attacks.items():
        rc, rec = run_gate(world, tmp_path, head, world["M"], reviews, approvers=(OWNER_B, AUTHOR) if name == "author_self_approval" else (OWNER_B,), monkeypatch=monkeypatch)
        assert rc == 1 and rec["decision"] == "BLOCK" and rec["authorization"] != "AUTHORIZATION_APPROVED", (name, rec)


def test_gate_blocks_tampers_even_with_approval(world, tmp_path, monkeypatch):
    approved = lambda h: [review(OWNER_B, commit=h)]
    undeclared = make_head(world, world["M"], {"app/util.py": "UTIL = 4\n"}, declare=False)
    rc, rec = run_gate(world, tmp_path, undeclared, world["M"], approved(undeclared), monkeypatch=monkeypatch)
    assert rc == 1 and rec["integrity"] == "INTEGRITY_FAIL" and rec["decision"] == "BLOCK"
    replay = make_head(world, world["M"], {"app/util.py": "UTIL = 5\n"})
    r = world["r"]
    stale_delta = json.loads((r.path / E.DELTA_PATH).read_text())
    stale_delta["base_sha"] = world["E"]                                                 # replay of a delta bound to an older base
    r.write(E.DELTA_PATH, E.canonical(stale_delta).decode())
    replayed = r.commit("replayed delta")
    r.git("update-ref", "refs/remotes/pr/head", replayed)
    rc, rec = run_gate(world, tmp_path, replayed, world["M"], approved(replayed), monkeypatch=monkeypatch)
    assert rc == 1 and rec["integrity"] == "INTEGRITY_FAIL" and replay != replayed
    for files, delete in (({"sitecustomize.py": "import os\n"}, ()), ({"app/util.py": "UTIL = 6\n"}, ("tests/test_calc.py",))):
        head = make_head(world, world["M"], files, delete)
        rc, rec = run_gate(world, tmp_path, head, world["M"], approved(head), runs=[], monkeypatch=monkeypatch)     # a new root file / a deleted test, approved but no V4 at this head
        assert rc == 1 and rec["decision"] == "BLOCK", rec


def test_gate_semantic_deferral_needs_the_same_heads_v4_and_approval(world, tmp_path, monkeypatch):
    head = make_head(world, world["M"], {SEMANTIC_LITERAL: "ROUTER = 2\n"})
    approved = [review(OWNER_B, commit=head)]
    rc, rec = run_gate(world, tmp_path, head, world["M"], approved, monkeypatch=monkeypatch)
    assert rc == 0 and rec["decision"] == "DEFERRED_TO_V4_VERIFIED" and rec["integrity"] == "UNKNOWN" and rec["v4_linkage"] == "V4_VERIFIED_AT_HEAD"
    assert rec["semantic_gaps"] and rec["decision"] != "INTEGRITY_PASS_AUTHORIZED"                    # never relabelled as an integrity pass
    for name, runs in (("v4_missing", []), ("v4_for_another_sha", all_green(head="2" * 40)), ("one_v4_check_skipped", all_green()[:-1] + [cr(POLICY.V4_REQUIRED_CHECKS[-1], conclusion="skipped")]),
                       ("one_v4_check_red", all_green()[:-1] + [cr(POLICY.V4_REQUIRED_CHECKS[-1], conclusion="failure")]),
                       ("one_v4_check_running", all_green()[:-1] + [cr(POLICY.V4_REQUIRED_CHECKS[-1], "in_progress", None)])):
        rc, rec = run_gate(world, tmp_path, head, world["M"], approved, runs=runs, monkeypatch=monkeypatch)
        assert rc == 1 and rec["decision"] == "BLOCK" and "DEFERRAL_NEEDS_V4_VERIFIED_AT_THE_SAME_HEAD" in rec["reasons"], (name, rec["reasons"])
    rc, rec = run_gate(world, tmp_path, head, world["M"], [], monkeypatch=monkeypatch)                  # all V4 green but no independent authorization
    assert rc == 1 and rec["decision"] == "BLOCK"


def test_gate_trust_prerequisites_block(world, tmp_path, monkeypatch):
    head = make_head(world, world["M"], {"app/util.py": "UTIL = 7\n"})
    approved = [review(OWNER_B, commit=head)]
    rc, rec = run_gate(world, tmp_path, head, world["M"], approved, provenance="UNTRUSTED_TOOL_SOURCE", monkeypatch=monkeypatch)
    assert rc == 1 and any("TOOL_SOURCE" in x for x in rec["reasons"])
    rc, rec = run_gate(world, tmp_path, head, world["M"], approved, head_ref="refs/remotes/does-not-exist", monkeypatch=monkeypatch)       # the PR ref does not resolve to the event head
    assert rc == 1 and "HEAD_SHA_DOES_NOT_MATCH_THE_PULL_REQUEST_REF" in rec["reasons"]
    world["r"].git("update-ref", "refs/remotes/pr/head", world["M"])                                      # the PR ref moved (a push raced the event): the event head is stale
    rc, rec = run_gate(world, tmp_path, head, world["M"], approved, monkeypatch=monkeypatch)
    assert rc == 1 and "HEAD_SHA_DOES_NOT_MATCH_THE_PULL_REQUEST_REF" in rec["reasons"]
    stale_base = make_head(world, world["M"], {"app/util.py": "UTIL = 8\n"})
    rc, rec = run_gate(world, tmp_path, stale_base, world["E"], [review(OWNER_B, commit=stale_base)], monkeypatch=monkeypatch)             # base is not the head's merge base / tip
    assert rc == 1 and rec["decision"] == "BLOCK"


def test_a_blocked_full_witness_keeps_the_epoch_non_authoritative(world, tmp_path, monkeypatch):
    """FULL_PROVENANCE_BLOCKED: an epoch accepted without a green FULL can never open the gate (the honest state of this repository today)."""
    head = make_head(world, world["B"], {"app/util.py": "UTIL = 9\n"})
    rc, rec = run_gate(world, tmp_path, head, world["B"], [review(OWNER_B, commit=head)], monkeypatch=monkeypatch)
    assert rc == 1 and rec["decision"] == "BLOCK" and rec["integrity"] == "UNKNOWN"
    assert any("EPOCH_FULL_PROVENANCE_NOT_GREEN" in x or "UNKNOWN_NOT_DEFERRABLE" in x for x in rec["reasons"])


def test_a_promotion_pr_never_opens_the_gate(world, tmp_path, monkeypatch):
    r = world["r"]
    r.checkout(world["E"])                                                                                # a base WITHOUT an anchor
    epoch = E.make_epoch(E.Git(r.path), world["E"], full_run={"status": "PASS", "run_id": "9", "sha": world["E"]})
    r.write(E.TRUSTED_EPOCH_PATH, E.canonical(epoch).decode())
    head = r.commit("promotion")
    r.git("update-ref", "refs/remotes/pr/head", head)
    rc, rec = run_gate(world, tmp_path, head, world["E"], [review(OWNER_B, commit=head)], monkeypatch=monkeypatch)
    assert rc == 1 and rec["decision"] == "BLOCK" and any("PROMOTION" in x or "TRUST_NOT_ESTABLISHED" in x or "TRANSITION" in x for x in rec["reasons"])
    # the combined single-PR case: an epoch edit PLUS another guarded change can never reach an authoritative integrity pass
    r.checkout(world["M"])
    r.write(E.TRUSTED_EPOCH_PATH, E.canonical(E.make_epoch(E.Git(r.path), world["M"], full_run={"status": "PASS", "run_id": "9", "sha": world["M"]})).decode())
    r.write("app/util.py", "UTIL = 10\n")
    head2 = r.commit("epoch edit and another guarded file")
    r.git("update-ref", "refs/remotes/pr/head", head2)
    v5 = E.verify(r.path, head2, world["M"], trusted_ref_tip=world["M"], tool_source="TRUSTED_BASE")
    assert v5["integrity"] != "INTEGRITY_PASS" and v5["transition"] == "PROMOTION_REQUIRES_OWNER" and "PROMOTION_NOT_ISOLATED" in {f["code"] for f in v5["failures"]}
    rc, rec = run_gate(world, tmp_path, head2, world["M"], [review(OWNER_B, commit=head2)], monkeypatch=monkeypatch)
    assert rc == 1 and rec["decision"] == "BLOCK"


def test_the_gate_record_never_claims_enforcement_and_has_no_bare_pass(world, tmp_path, monkeypatch):
    head = make_head(world, world["M"], {"README.md": "again\n"})
    _rc, rec = run_gate(world, tmp_path, head, world["M"], [review(OWNER_B, commit=head)], monkeypatch=monkeypatch)
    assert rec["enforcement"] == "ENFORCEMENT_UNVERIFIED" and "PASS" not in json.dumps(rec).replace("INTEGRITY_PASS", "")
    assert {rec["decision"]} <= {"INTEGRITY_PASS_AUTHORIZED", "DEFERRED_TO_V4_VERIFIED", "BLOCK"}


# ---------------------------------------------------------------------------------------------------------------------------------- epoch + full provenance
def test_epoch_without_a_green_full_witness_is_never_authoritative(world):
    r = world["r"]
    r.checkout(world["B"])
    head = r.commit("noop")
    rec = E.verify(r.path, head, world["B"], trusted_ref_tip=world["B"], tool_source="TRUSTED_BASE")
    codes = {u["code"] for u in rec["unknowns"]}
    assert rec["integrity"] == "UNKNOWN" and "EPOCH_FULL_PROVENANCE_NOT_GREEN" in codes and rec["epoch"]["full_witness"] == "FULL_PROVENANCE_BLOCKED"
    r.checkout(world["M"])
    head = r.commit("noop2")
    rec = E.verify(r.path, head, world["M"], trusted_ref_tip=world["M"], tool_source="TRUSTED_BASE")
    assert rec["integrity"] == "INTEGRITY_PASS" and rec["epoch"]["full_witness"] == "FULL_WITNESS_ATTESTED_GREEN"
    ep = json.loads(E.canonical(E.make_epoch(E.Git(r.path), world["M"], full_run={"status": "PASS", "run_id": "", "sha": world["M"]})))
    assert not E.epoch_full_provenance(ep)[0] and not E.epoch_full_provenance({})[0] and not E.epoch_full_provenance(None)[0]


def test_repository_epoch_checkpoint_is_a_truthful_v2_snapshot_with_an_honest_full_witness():
    raw = (ROOT / E.TRUSTED_EPOCH_PATH).read_bytes()
    epoch, problems = E.load_epoch(raw)
    assert epoch is not None and not epoch["legacy"] and epoch["guard"]["mode"] == "ALL_TRACKED", problems
    assert epoch["policy_version"] == POLICY.POLICY_VERSION and sorted(epoch["guard"]["exempt"]) == sorted({E.DELTA_PATH, *POLICY.V4_BOUND_EXEMPT})
    fr = epoch["full_run"]
    assert fr["status"] == "FULL_PROVENANCE_BLOCKED" and fr["sha"] == epoch["base_commit"] and fr["reason"] and not E.epoch_full_provenance(epoch)[0]    # honest: blocked, never PASS
    git = E.Git(ROOT)
    assert git.run("cat-file", "-t", epoch["base_commit"]).strip() == b"commit" and git.run("rev-parse", epoch["base_commit"] + "^{tree}").decode().strip() == epoch["base_tree"]
    snap = {p: v for p, v in E.read_inventory(git, epoch["base_commit"]).items() if E.is_guarded(p)}
    assert snap == E.epoch_map(epoch)                                                                                                         # exactly the accepted base's ALL_TRACKED inventory
    git.run("merge-base", "--is-ancestor", epoch["base_commit"], "HEAD")                                                                     # accepted history of this checkout
    assert raw == E.canonical(json.loads(raw)) and not any(e.endswith("\t" + E.TRUSTED_EPOCH_PATH) or e.endswith("\t" + E.DELTA_PATH) for e in epoch["entries"])


# ---------------------------------------------------------------------------------------------------------------------------------- workflow structure
def test_gate_workflow_cannot_be_rewritten_by_the_pr_and_never_executes_the_head():
    import yaml
    path = ROOT / ".github/workflows/ci_v5_gate.yml"
    text = path.read_text()
    wf = yaml.safe_load(text)
    on = wf.get("on", wf.get(True))
    jobs = wf["jobs"]
    # its OWN file, ONE event: no `pull_request` => no skipped same-named check run that a required-status rule would count as passing
    assert set(on) == {"pull_request_target"} and on["pull_request_target"]["branches"] == ["main"] and list(jobs) == ["gate"]
    assert on["pull_request_target"]["types"] == ["opened", "synchronize", "reopened", "ready_for_review"]
    shadow = yaml.safe_load((ROOT / ".github/workflows/ci_v5_shadow.yml").read_text())
    assert set(shadow.get("on", shadow.get(True))) == {"pull_request"} and "gate" not in shadow["jobs"]
    names = [j.get("name") for f in (wf, shadow) for j in f["jobs"].values()]
    assert names.count(POLICY.GATE_CHECK_NAME) == 1, "the required-check name is produced by exactly one job in the whole repository's V5 workflows"
    gate = jobs["gate"]
    assert "if" not in gate and gate["name"] == POLICY.GATE_CHECK_NAME
    assert gate["permissions"] == {"contents": "read", "pull-requests": "read", "checks": "read"} and wf["permissions"] == {"contents": "read"}
    steps = gate["steps"]
    checkout = next(s for s in steps if s.get("uses", "").startswith("actions/checkout"))
    assert "ref" not in checkout["with"] and "repository" not in checkout["with"], "the gate checks out the protected BASE (the default for this event), never the head"
    runs = "\n".join(s.get("run", "") for s in steps)
    assert "refs/pull/${PR_NUMBER}/head:refs/remotes/pr/head" in runs and "python -I tools/ci_v5_shadow.py gate" in runs
    for banned in ("git checkout", "git switch", "git merge ", "git pull", "pip ", "npm ", "pytest", "python -m", "python tools/", "bash tools", "sh tools", "./tools", "eval ", "source "):
        assert banned not in runs, banned
    assert not any("${{" in s.get("run", "") for s in steps), "no expression is interpolated into a script: context reaches scripts only through env:"
    env = gate["env"]
    assert set(env) == {"PR_NUMBER", "HEAD_SHA", "PR_AUTHOR", "GH_TOKEN", "GH_REPO", "PYTHONDONTWRITEBYTECODE"}
    assert env["GH_TOKEN"] == "${{ github.token }}" and not any(w in text for w in ("secrets.", "workflow_dispatch", "contents: write", "pull-requests: write", "pull_request_review", "workflow_run:"))
    for forbidden in ("github.event.pull_request.title", "github.event.pull_request.body", "github.event.pull_request.head.ref", "github.head_ref", "head.repo", "comment.body"):
        assert forbidden not in text, forbidden
    assert wf["concurrency"]["group"] == "ci-v5-gate-${{ github.event.pull_request.number }}"
    assert all(len(u.split("@")[1]) == 40 for u in (s["uses"] for s in steps if "uses" in s))
    assert "FINCO_CI_V5_DELTA_V2" in runs and "TRUSTED_BASE" in runs and "UNTRUSTED_TOOL_SOURCE" in runs
