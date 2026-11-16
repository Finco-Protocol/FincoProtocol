"""CI V5 SHADOW lane, split by TRUST BOUNDARY (observational; never required here; V4 stays authoritative).

Three entry points, each meant for its OWN workflow job so that no PR-head code ever runs where the V5 verdict is computed or published:

  ``verdict``  (job 1) reads Git OBJECTS only: V5 integrity verdict + B5 report. Runs trusted-base tools. Executes NO code from the checkout.
  ``v4``       (job 2) runs the accepted V4 one-pass central gate FROM THE CHECKOUT (PR-head Python). Isolated; writes one artifact; judges nothing.
  ``compare``  (job 3) trusted code only: reads the two artifacts as DATA, writes the comparison record and the job summary.

The vocabulary is honest: ``integrity`` (INTEGRITY_PASS / INTEGRITY_FAIL / UNKNOWN) is separate from ``authorization`` (NOT_EVALUATED in the shadow lane)
and ``enforcement`` (SHADOW in the shadow lane). A V5 integrity pass can never suppress a V4 failure and is never merge authorization.

V5-3 adds ``gate`` (job 4, ``pull_request_target``: its definition is read from the protected base, the PR head is only ever read as Git objects) and
``enforcement`` (owner-run: verifies a branch-protection / ruleset read). The decision logic below is PURE (data in, decision out), so every attack on it
is a synthetic test: author self-approval, stale or wrong-sha approval, a non-allow-listed approver (including the Actions bot), an unsigned or foreign-signed
approval commit, a V4 check that is missing / skipped / red / for another sha, and a protection read that does not prove the gate is required.
"""
from __future__ import annotations

import argparse
import json
import os
import subprocess
import sys
import time

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import ci_v5_b5 as B5  # noqa: E402
import ci_v5_epoch as E  # noqa: E402

VERDICT_FILE, B5_FILE, V4_FILE, COMPARISON_FILE = "v5_verdict.json", "b5_report.json", "v4_result.json", "shadow_comparison.json"
V4_RAW_FILE = "v4_governance_gate.json"


def run_v4_gate(repo, out_path, timeout):
    """The accepted V4 central one-pass governance gate, run from the checkout under test (PR-head code: job 2 ONLY). Bounded; any problem is UNAVAILABLE, never PASS."""
    t0 = time.monotonic()
    env = dict(os.environ, PYTHONDONTWRITEBYTECODE="1")
    try:
        p = subprocess.run([sys.executable, "-m", "tools.ci_v4_governance_gate", "--output", out_path], cwd=repo, env=env, capture_output=True, timeout=timeout)
        rec = json.loads(open(out_path).read())
        verdict = rec.get("verdict") if rec.get("verdict") in ("PASS", "FAIL") else "UNAVAILABLE"
        return {"verdict": verdict, "exit_code": p.returncode, "wall_s": round(time.monotonic() - t0, 1),
                "non_exact_cohorts": sorted(k for k, v in rec.get("cohorts", {}).items() if not v), "composite_valid": rec.get("composite_valid"),
                "mutation_violations": len(rec.get("mutation_violations", [])), "mutation_successor_valid": rec.get("mutation_successor_valid"),
                "error": rec.get("error")}
    except subprocess.TimeoutExpired:
        return {"verdict": "UNAVAILABLE", "error": "timeout after %ds" % timeout, "wall_s": round(time.monotonic() - t0, 1)}
    except (OSError, ValueError) as exc:
        return {"verdict": "UNAVAILABLE", "error": "%s: %s" % (type(exc).__name__, exc), "wall_s": round(time.monotonic() - t0, 1)}


def _v5_state(v5):
    """Map the V5 integrity vocabulary onto the three states the comparison reasons about."""
    return {"INTEGRITY_PASS": "PASS", "INTEGRITY_FAIL": "FAIL"}.get(v5.get("integrity"), "UNKNOWN")


def compare(v4, v5):
    """Relation of the two verdicts. Parity is NEVER declared from one run: it needs the owner-approved multi-PR window. A V4 verdict that is not
    present, not ``PASS``/``FAIL`` or not from the same head is INCOMPARABLE and is counted nowhere."""
    a, b = v4.get("verdict"), _v5_state(v5)
    if a not in ("PASS", "FAIL") or b == "UNKNOWN":
        relation = "INCOMPARABLE"
    elif a == b:
        relation = "MATCH_" + a
    elif a == "FAIL" and b == "PASS":
        relation = "MISMATCH_V5_WOULD_ADMIT_V4_FAIL"
    else:
        relation = "MISMATCH_V5_STRICTER_THAN_V4"
    return {"relation": relation, "parity": "PARITY_NOT_ESTABLISHED", "v4_remains_authoritative": True, "v5_authoritative": bool(v5.get("trust", {}).get("authoritative")),
            "v4_failure_attribution": ({"composite_valid": v4.get("composite_valid"), "non_exact_cohorts": len(v4.get("non_exact_cohorts", [])),
                                        "mutation_violations": v4.get("mutation_violations"), "successor_valid": v4.get("mutation_successor_valid")}
                                       if a == "FAIL" else None),
            "v4_ownership_failure_is_reported_separately_from_semantic_violations": True,
            "note": ("V5 would have admitted a head that V4 rejects: V5 must never override V4; classify the V4 failure (changed-path ownership vs semantic "
                     "violation) before any activation") if relation == "MISMATCH_V5_WOULD_ADMIT_V4_FAIL" else ""}


def summary(rec, b5_text):
    v5, v4, cmp_ = rec["v5"], rec["v4"], rec["comparison"]
    t = v5["trust"]
    L = ["## CI V5 shadow (observational - integrity is NOT authorization, NOT a required check)", "",
         "| | |", "|---|---|",
         "| **integrity** | **%s** (`effective`: %s) |" % (v5["integrity"], v5["effective"]),
         "| authorization / enforcement | `%s` / `%s` |" % (v5["authorization"], v5["enforcement"]),
         "| transition | `%s` |" % v5["transition"],
         "| **V4_VERDICT** (accepted one-pass central gate, separate job) | **%s** (%ss) |" % (v4.get("verdict"), v4.get("wall_s")),
         "| comparison | `%s` / `%s` |" % (cmp_["relation"], cmp_["parity"]),
         "| head SHA / tree | `%s` / `%s` |" % (v5["source_head_sha"], v5.get("source_tree")),
         "| trusted base tip | `%s` (%s) |" % (v5["base_sha"], t["base_state"]),
         "| tool source / epoch / guard | `%s` / `%s` / `%s` |" % (t["tool_source"], t["epoch_state"], t["guard_mode"]),
         "| guarded paths / delta changes | %d / %d |" % (v5["full_guard_count"], v5["delta_changes"]),
         "| epoch_sha / delta_digest | `%s` / `%s` |" % (v5.get("epoch_sha"), v5.get("delta_digest")),
         "| classes of changed paths | `%s` |" % json.dumps(v5.get("classes", {}), sort_keys=True), ""]
    if t["tool_source"] != "TRUSTED_BASE" or t["epoch_state"] != "TRUSTED_BASE":
        L += ["> **Not authoritative:** tool source `%s`, epoch `%s`. V5 is informational only; V4 decides." % (t["tool_source"], t["epoch_state"]), ""]
    if cmp_["note"]:
        L += ["> **%s** - %s" % (cmp_["relation"], cmp_["note"]), ""]
    if cmp_["v4_failure_attribution"]:
        L += ["V4 failure attribution (ownership vs semantics, never one raw count): `%s`" % json.dumps(cmp_["v4_failure_attribution"], sort_keys=True), ""]
    if v5["semantic_gaps"]:
        L += ["**Semantic gaps (V4 stays authoritative)** - %d, first 8: %s" % (len(v5["semantic_gaps"]), ", ".join("`%s`" % g for g in v5["semantic_gaps"][:8])), ""]
    if v5["failures"] or v5["unknowns"]:
        L += ["**V5 findings** (first 12):"] + ["- `%s` %s" % (f["code"], f["detail"][:140]) for f in (v5["failures"] + v5["unknowns"])[:12]] + [""]
    if rec.get("harness_errors"):
        L += ["**Harness errors:** " + "; ".join(rec["harness_errors"]), ""]
    L += ["---", b5_text, "", "_Labels: MEASURED_LOCAL = this runner, this process; SIMULATION = prediction; nothing here is merge approval._"]
    return "\n".join(L)


def _dump(path, obj):
    with open(path, "w") as fh:
        fh.write(json.dumps(obj, indent=2, sort_keys=True) + "\n")


def cmd_verdict(a):
    """Job 1: Git objects only. The only code that runs is the (trusted-base) evaluator and the B5 adapter; nothing from the checkout is imported or executed."""
    os.makedirs(a.out_dir, exist_ok=True)
    v5 = E.verify(a.repo, a.head_sha, a.base_tip_sha, trusted_ref_tip=a.base_tip_sha, tool_source=a.tools_provenance, check_worktree=True)
    b5 = B5.build(a.repo, a.base_tip_sha, a.head_sha, a.b3_report)
    errors = [] if b5.get("status") == "OK" else ["B5 report unavailable: %s" % b5.get("reason")]
    _dump(os.path.join(a.out_dir, VERDICT_FILE), v5)
    _dump(os.path.join(a.out_dir, B5_FILE), b5)
    _dump(os.path.join(a.out_dir, "verdict_harness.json"), {"harness_errors": errors})
    print("INTEGRITY=%s AUTHORIZATION=%s ENFORCEMENT=%s TRANSITION=%s tool_source=%s epoch=%s" % (
        v5["integrity"], v5["authorization"], v5["enforcement"], v5["transition"], v5["trust"]["tool_source"], v5["trust"]["epoch_state"]))
    for err in errors:
        print("::error::shadow harness: %s" % err)
    return 1 if errors else 0


def cmd_v4(a):
    """Job 2: PR-head code runs HERE and only here; the result is an artifact the compare job reads as data."""
    os.makedirs(a.out_dir, exist_ok=True)
    rec = run_v4_gate(a.repo, os.path.join(a.out_dir, V4_RAW_FILE), a.v4_timeout)
    rec["head_sha"] = a.head_sha
    _dump(os.path.join(a.out_dir, V4_FILE), rec)
    print("V4_VERDICT=%s head=%s" % (rec["verdict"], a.head_sha))
    return 0


def _load(path):
    try:
        return json.loads(open(path).read()), None
    except (OSError, ValueError) as exc:
        return None, "%s: %s" % (os.path.basename(path), type(exc).__name__)


def cmd_compare(a):
    """Job 3: trusted code only. A missing or foreign-head artifact is INCOMPARABLE / UNAVAILABLE, never PASS."""
    os.makedirs(a.out_dir, exist_ok=True)
    errors = []
    v5, err = _load(os.path.join(a.verdict_dir, VERDICT_FILE))
    if v5 is None:
        errors.append(err)
        v5 = {"integrity": "UNKNOWN", "authorization": "UNVERIFIED", "enforcement": "UNVERIFIED", "transition": "UNKNOWN", "source_head_sha": a.head_sha, "source_tree": None,
              "base_sha": None, "effective": "UNAVAILABLE", "full_guard_count": 0, "delta_changes": 0, "classes": {}, "semantic_gaps": [], "failures": [], "unknowns": [],
              "trust": {"tool_source": "UNAVAILABLE", "epoch_state": "UNAVAILABLE", "base_state": "UNAVAILABLE", "guard_mode": "UNAVAILABLE", "authoritative": False}}
    b5, err = _load(os.path.join(a.verdict_dir, B5_FILE))
    if b5 is None:
        errors.append(err)
        b5 = {"status": "UNAVAILABLE", "reason": "artifact missing"}
    elif b5.get("status") != "OK":
        errors.append("B5 report unavailable: %s" % b5.get("reason"))
    v4, err = _load(os.path.join(a.v4_dir, V4_FILE))
    if v4 is None:
        errors.append(err)
        v4 = {"verdict": "UNAVAILABLE", "error": "artifact missing"}
    elif v4.get("head_sha") != a.head_sha or v5.get("source_head_sha") != a.head_sha:
        errors.append("artifact head SHA does not match the evaluated head")      # a foreign or stale artifact is never compared
        v4 = {"verdict": "UNAVAILABLE", "error": "head SHA mismatch"}
    rec = {"schema": "FINCO_CI_V5_SHADOW_V2", "v4": v4, "v5": v5, "comparison": compare(v4, v5), "harness_errors": errors, "label": "OBSERVATIONAL_SHADOW"}
    _dump(os.path.join(a.out_dir, COMPARISON_FILE), rec)
    text = summary(rec, B5.summary_markdown(b5))
    if a.summary:
        with open(a.summary, "a") as fh:
            fh.write(text + "\n")
    print("V4=%s INTEGRITY=%s comparison=%s" % (v4.get("verdict"), v5["integrity"], rec["comparison"]["relation"]))
    for err in errors:
        print("::error::shadow harness: %s" % err)
    return 1 if errors else 0


# ============================================================================================================================ V5-3 gate (pure logic)
GATE_SCHEMA = "FINCO_CI_V5_GATE_V1"
ALLOWED_DEFERRAL_UNKNOWNS = ("SEMANTIC_INVARIANT_NOT_EVALUATED",)       # the ONLY unknown a verified V4 may cover (a recorded semantic gap), never a trust gap


def authorize_reviews(reviews, pr_author, head_sha, approvers=None, associations=None):
    """(state, reasons) from the GitHub review list of the PR (data the TRUSTED job fetched from the API, never data the PR head supplies).

    AUTHORIZATION_APPROVED needs an APPROVED review by an allow-listed login that is NOT the PR author, with a repository association of OWNER / MEMBER /
    COLLABORATOR, whose ``commit_id`` is EXACTLY the evaluated head (so a stale review, an approval made before the latest push, or an approval of another sha or
    another delta never counts: the head sha binds the tree and therefore the delta file), and whose latest state is not DISMISSED / CHANGES_REQUESTED.
    An empty allow-list is ``AUTHORIZATION_BLOCKED`` (no approver configured), never a default allow."""
    approvers = tuple(E.POLICY.APPROVERS if approvers is None else approvers)
    associations = tuple(E.POLICY.REVIEW_ASSOCIATIONS if associations is None else associations)
    if not approvers:
        return "AUTHORIZATION_BLOCKED", ["NO_APPROVER_CONFIGURED"]
    if not isinstance(reviews, list) or not isinstance(head_sha, str) or not E.SHA40.fullmatch(head_sha) or not isinstance(pr_author, str) or not pr_author:
        return "AUTHORIZATION_BLOCKED", ["REVIEW_EVIDENCE_UNAVAILABLE"]
    allow = {a.lower() for a in approvers}
    latest = {}
    for r in sorted((x for x in reviews if isinstance(x, dict)), key=lambda x: str(x.get("submitted_at") or "")):
        user = ((r.get("user") or {}).get("login") or "").lower()
        if user and r.get("state") in ("APPROVED", "CHANGES_REQUESTED", "DISMISSED"):
            latest[user] = r
    reasons, approved = [], False
    for user, r in sorted(latest.items()):
        if user == pr_author.lower():
            reasons.append("SELF_REVIEW_IGNORED:" + user)
        elif user not in allow:
            reasons.append("NOT_AN_ALLOW_LISTED_APPROVER:" + user)
        elif r.get("author_association") not in associations:
            reasons.append("REVIEWER_ASSOCIATION_NOT_ACCEPTED:" + user)
        elif r.get("state") == "CHANGES_REQUESTED":
            return "AUTHORIZATION_DENIED", ["CHANGES_REQUESTED_BY:" + user]
        elif r.get("state") == "DISMISSED":
            reasons.append("APPROVAL_DISMISSED:" + user)
        elif r.get("commit_id") != head_sha:
            reasons.append("STALE_OR_OTHER_SHA_APPROVAL:" + user)
        else:
            approved = True
    if approved:
        return "AUTHORIZATION_APPROVED", ["APPROVED_AT_EXACT_HEAD"]
    return "AUTHORIZATION_BLOCKED", reasons or ["NO_APPROVAL_AT_EXACT_HEAD"]


def verify_signed_head(root, head_sha, signers=None, runner=None):
    """(state, reasons): option B, owner-signed approval commit. The owner SSH-signs the head commit with a key the agent never holds; trusted code verifies it
    against ``POLICY.ALLOWED_SIGNERS``. The signature binds the commit sha (tree, parents), so it cannot be replayed on another head and needs no
    self-referential ledger. No configured signer, no ``ssh-keygen`` or any verification failure is a block, never a pass."""
    import shutil
    import tempfile
    signers = tuple(E.POLICY.ALLOWED_SIGNERS if signers is None else signers)
    if not signers:
        return "AUTHORIZATION_BLOCKED", ["NO_SIGNER_CONFIGURED"]
    if not (isinstance(head_sha, str) and E.SHA40.fullmatch(head_sha)):
        return "AUTHORIZATION_BLOCKED", ["BAD_HEAD_SHA"]
    if runner is None and shutil.which("ssh-keygen") is None:
        return "AUTHORIZATION_BLOCKED", ["SIGNATURE_VERIFIER_UNAVAILABLE"]
    lines, principals = [], set()
    for principal, key in signers:
        if not (isinstance(principal, str) and principal.isascii() and principal.replace("-", "").replace("_", "").replace(".", "").replace("@", "").isalnum()
                and isinstance(key, str) and key.startswith("ssh-ed25519 ") and "\n" not in key):
            return "AUTHORIZATION_BLOCKED", ["MALFORMED_SIGNER_POLICY"]
        principals.add(principal)
        lines.append('%s namespaces="git" %s' % (principal, key))
    with tempfile.TemporaryDirectory() as td:
        allowed = os.path.join(td, "allowed_signers")
        with open(allowed, "w") as fh:
            fh.write("\n".join(lines) + "\n")
        try:
            run = runner or (lambda *args: E.Git(root).run(*args))
            out = run("-c", "gpg.format=ssh", "-c", "gpg.ssh.allowedSignersFile=" + allowed, "log", "-1", "--format=%G?%x00%GS%x00%H", head_sha)
        except (E.GitError, OSError, subprocess.TimeoutExpired):
            return "AUTHORIZATION_BLOCKED", ["SIGNATURE_VERIFICATION_ERROR"]
    status, _sep, rest = out.decode("utf-8", "replace").strip().partition("\0")
    principal, _sep, commit = rest.partition("\0")
    if status != "G":
        return "AUTHORIZATION_BLOCKED", ["SIGNATURE_STATUS_" + (status or "NONE")]
    if commit != head_sha or principal not in principals:
        return "AUTHORIZATION_BLOCKED", ["SIGNER_NOT_ALLOW_LISTED_OR_OTHER_COMMIT"]
    return "AUTHORIZATION_APPROVED", ["SIGNED_BY:" + principal]


def v4_linkage(check_runs, head_sha, required=None):
    """(ok, findings): every required V4 check has a COMPLETED run with conclusion ``success`` for THIS head. ``skipped`` / ``neutral`` / ``cancelled`` /
    ``in_progress`` / absent are all a failure of the linkage. Data comes from the trusted job's own API read of the head commit's check runs."""
    required = tuple(E.POLICY.V4_REQUIRED_CHECKS if required is None else required)
    if not isinstance(check_runs, list):
        return False, ["CHECK_RUN_EVIDENCE_UNAVAILABLE"]
    findings = []
    for name in required:
        runs = [r for r in check_runs if isinstance(r, dict) and r.get("name") == name and (r.get("head_sha") in (None, head_sha))]
        if not runs:
            findings.append("MISSING:" + name)
            continue
        last = sorted(runs, key=lambda r: str(r.get("completed_at") or r.get("started_at") or ""))[-1]
        if last.get("status") != "completed" or last.get("conclusion") != "success":
            findings.append("NOT_SUCCESS:%s:%s/%s" % (name, last.get("status"), last.get("conclusion")))
    return (not findings), findings


def verify_enforcement(protection=None, rules=None, gate_name=None, v4_names=None):
    """(state, findings) from the owner's READ of the live GitHub settings. ``None`` (HTTP 403 / not read) is ``ENFORCEMENT_UNVERIFIED``; a read that does
    not prove the gate is required alongside every V4 check, strict, with enforced admins and review hardening is ``ENFORCEMENT_INCOMPLETE``. A workflow
    existing or having run is never evidence. Only a complete read is ``ENFORCEMENT_VERIFIED``."""
    gate_name = gate_name or E.POLICY.GATE_CHECK_NAME
    v4_names = tuple(E.POLICY.V4_REQUIRED_CHECKS if v4_names is None else v4_names)
    if protection is None and rules is None:
        return "ENFORCEMENT_UNVERIFIED", ["PROTECTION_AND_RULESETS_NOT_READ"]
    contexts, strict, admins, reviews = set(), False, False, {}
    if isinstance(protection, dict):
        rsc = protection.get("required_status_checks") or {}
        contexts |= set(rsc.get("contexts") or []) | {c.get("context") for c in (rsc.get("checks") or []) if isinstance(c, dict)}
        strict = bool(rsc.get("strict"))
        admins = bool((protection.get("enforce_admins") or {}).get("enabled"))
        reviews = protection.get("required_pull_request_reviews") or {}
    if isinstance(rules, list):
        for rule in rules:
            if not isinstance(rule, dict):
                continue
            prm = rule.get("parameters") or {}
            if rule.get("type") == "required_status_checks":
                contexts |= {c.get("context") for c in (prm.get("required_status_checks") or []) if isinstance(c, dict)}
                strict = strict or bool(prm.get("strict_required_status_checks_policy"))
            if rule.get("type") == "pull_request":
                reviews = reviews or {"require_code_owner_reviews": prm.get("require_code_owner_review"), "dismiss_stale_reviews": prm.get("dismiss_stale_reviews_on_push"),
                                      "require_last_push_approval": prm.get("require_last_push_approval"),
                                      "required_approving_review_count": prm.get("required_approving_review_count")}
    findings = []
    if gate_name not in contexts:
        findings.append("GATE_NOT_REQUIRED:" + gate_name)
    findings += ["V4_CHECK_NOT_REQUIRED:" + n for n in v4_names if n not in contexts]
    if not strict:
        findings.append("STRICT_UP_TO_DATE_OFF")
    if not admins and not (isinstance(rules, list) and rules):
        findings.append("ADMINS_NOT_ENFORCED")
    if not reviews.get("require_code_owner_reviews"):
        findings.append("CODE_OWNER_REVIEW_NOT_REQUIRED")
    if not reviews.get("dismiss_stale_reviews"):
        findings.append("STALE_APPROVALS_NOT_DISMISSED")
    if not reviews.get("require_last_push_approval"):
        findings.append("LAST_PUSH_APPROVAL_NOT_REQUIRED")
    if not (isinstance(reviews.get("required_approving_review_count"), int) and reviews["required_approving_review_count"] >= 1):
        findings.append("NO_APPROVING_REVIEW_REQUIRED")
    return ("ENFORCEMENT_VERIFIED", []) if not findings else ("ENFORCEMENT_INCOMPLETE", findings)


def decide(v5, authorization, v4_ok, *, head_matches=True, tool_source_trusted=True):
    """The gate decision. Never ``open`` on ``UNKNOWN`` unless the ONLY unknown is a recorded semantic gap AND the same exact head is verified by V4 AND an
    independent authorization exists; never open on INTEGRITY_FAIL, a promotion, a missing / untrusted epoch, an untrusted tool source, a stale head or
    ambiguous / absent authorization. Returns (decision, reasons)."""
    reasons = []
    if not head_matches:
        reasons.append("HEAD_SHA_DOES_NOT_MATCH_THE_PULL_REQUEST_REF")
    if not tool_source_trusted:
        reasons.append("TOOL_SOURCE_NOT_TRUSTED_BASE")
    t = v5.get("trust", {})
    if t.get("epoch_state") != "TRUSTED_BASE" or t.get("base_state") != "VERIFIED_TIP" or t.get("guard_mode") != "ALL_TRACKED":
        reasons.append("TRUST_NOT_ESTABLISHED:%s/%s/%s" % (t.get("epoch_state"), t.get("base_state"), t.get("guard_mode")))
    integrity = v5.get("integrity")
    if integrity == "INTEGRITY_FAIL":
        reasons.append("INTEGRITY_FAIL:" + ",".join(f["code"] for f in v5.get("failures", [])[:5]))
    if authorization != "AUTHORIZATION_APPROVED":
        reasons.append(authorization or "AUTHORIZATION_UNKNOWN")
    unknown_codes = [u["code"] for u in v5.get("unknowns", [])]
    if integrity == "UNKNOWN" and any(c not in ALLOWED_DEFERRAL_UNKNOWNS for c in unknown_codes):
        reasons.append("UNKNOWN_NOT_DEFERRABLE:" + ",".join(c for c in unknown_codes if c not in ALLOWED_DEFERRAL_UNKNOWNS))
    if integrity not in ("INTEGRITY_PASS", "UNKNOWN", "INTEGRITY_FAIL"):
        reasons.append("INTEGRITY_UNRECOGNISED")
    if v5.get("transition") not in (None, "NONE"):
        reasons.append("TRANSITION_" + str(v5.get("transition")))
    if reasons:
        return "BLOCK", reasons
    if integrity == "INTEGRITY_PASS":
        return "INTEGRITY_PASS_AUTHORIZED", ["INTEGRITY_PASS", "AUTHORIZATION_APPROVED"]
    if not v4_ok:
        return "BLOCK", ["DEFERRAL_NEEDS_V4_VERIFIED_AT_THE_SAME_HEAD"]
    return "DEFERRED_TO_V4_VERIFIED", ["SEMANTIC_GAP_COVERED_BY_V4_AT_THE_SAME_HEAD", "AUTHORIZATION_APPROVED"]


def _read_json(path):
    if not path:
        return None
    try:
        return json.loads(open(path).read())
    except (OSError, ValueError):
        return None


def cmd_gate(a):
    """Job 4 (``pull_request_target``): trusted-base tools, the PR head read ONLY as Git objects; every external fact comes from the API by the trusted job."""
    os.makedirs(a.out_dir, exist_ok=True)
    git = E.Git(a.repo)
    try:
        ref_sha = git.run("rev-parse", "--verify", a.head_ref + "^{commit}").decode().strip()
    except E.GitError:
        ref_sha = None
    head_matches = bool(ref_sha) and ref_sha == a.head_sha
    v5 = E.verify(a.repo, a.head_sha, a.base_tip_sha, trusted_ref_tip=a.base_tip_sha, tool_source=a.tools_provenance, check_worktree=False)
    v5.setdefault("notes", {})["worktree"] = "NOT_APPLICABLE: the head is never checked out in the gate lane"
    state, why = authorize_reviews(_read_json(a.reviews_json), a.pr_author, a.head_sha)
    source = "REVIEW"
    if state != "AUTHORIZATION_APPROVED" and state != "AUTHORIZATION_DENIED":
        s2, w2 = verify_signed_head(a.repo, a.head_sha)
        if s2 == "AUTHORIZATION_APPROVED":
            state, why, source = s2, w2, "SIGNED_COMMIT"
        else:
            why = why + w2
    v4_ok, v4_find = v4_linkage(_read_json(a.check_runs_json), a.head_sha)
    decision, reasons = decide(v5, state, v4_ok, head_matches=head_matches, tool_source_trusted=a.tools_provenance == "TRUSTED_BASE")
    rec = {"schema": GATE_SCHEMA, "decision": decision, "reasons": reasons, "integrity": v5["integrity"], "authorization": state, "authorization_source": source if state == "AUTHORIZATION_APPROVED" else "NONE",
           "authorization_findings": why, "v4_linkage": "V4_VERIFIED_AT_HEAD" if v4_ok else "V4_NOT_VERIFIED", "v4_findings": v4_find,
           "enforcement": "ENFORCEMENT_UNVERIFIED", "enforcement_note": "the gate cannot read branch protection with a read token; the owner verifies with the `enforcement` subcommand",
           "head_sha": a.head_sha, "head_ref_sha": ref_sha, "base_tip_sha": a.base_tip_sha, "pr_author": a.pr_author, "epoch_sha": v5.get("epoch_sha"), "delta_digest": v5.get("delta_digest"),
           "tool_source": a.tools_provenance, "semantic_gaps": v5.get("semantic_gaps", [])}
    _dump(os.path.join(a.out_dir, "gate_decision.json"), rec)
    _dump(os.path.join(a.out_dir, VERDICT_FILE), v5)
    line = "GATE decision=%s integrity=%s authorization=%s v4=%s enforcement=%s reasons=%s" % (decision, v5["integrity"], state, rec["v4_linkage"], rec["enforcement"], ";".join(reasons)[:300])
    print(line)
    if a.summary:
        with open(a.summary, "a") as fh:
            fh.write("## V5 gate (trusted base)\n\n| | |\n|---|---|\n| **decision** | **%s** |\n| integrity | `%s` |\n| authorization | `%s` (%s) |\n| V4 linkage at this head | `%s` |\n"
                     "| enforcement | `%s` (the gate cannot read branch protection) |\n| head / base tip | `%s` / `%s` |\n\n%s\n" % (
                         decision, v5["integrity"], state, ", ".join(why)[:200], rec["v4_linkage"], rec["enforcement"], a.head_sha, a.base_tip_sha, "Reasons: " + ", ".join(reasons)))
    return 0 if decision != "BLOCK" else 1


def cmd_enforcement(a):
    state, findings = verify_enforcement(_read_json(a.protection_json), _read_json(a.rules_json))
    print("ENFORCEMENT=%s %s" % (state, ";".join(findings)))
    if a.output:
        _dump(a.output, {"schema": "FINCO_CI_V5_ENFORCEMENT_V1", "enforcement": state, "findings": findings})
    return 0 if state == "ENFORCEMENT_VERIFIED" else 1


def main(argv=None):
    ap = argparse.ArgumentParser(description="CI V5 shadow lane (observational), one subcommand per job.")
    sub = ap.add_subparsers(dest="cmd", required=True)
    v = sub.add_parser("verdict")
    v.add_argument("--repo", default=".")
    v.add_argument("--head-sha", required=True)
    v.add_argument("--base-tip-sha", required=True, help="current tip of the protected ref (the base is never a caller-supplied merge-base)")
    v.add_argument("--out-dir", required=True)
    v.add_argument("--b3-report", required=True)
    v.add_argument("--tools-provenance", choices=("TRUSTED_BASE", "UNTRUSTED_TOOL_SOURCE"), required=True)
    g = sub.add_parser("v4")
    g.add_argument("--repo", default=".")
    g.add_argument("--head-sha", required=True)
    g.add_argument("--out-dir", required=True)
    g.add_argument("--v4-timeout", type=int, default=300)
    c = sub.add_parser("compare")
    c.add_argument("--head-sha", required=True)
    c.add_argument("--verdict-dir", required=True)
    c.add_argument("--v4-dir", required=True)
    c.add_argument("--out-dir", required=True)
    c.add_argument("--summary")
    g4 = sub.add_parser("gate")
    g4.add_argument("--repo", default=".")
    g4.add_argument("--head-sha", required=True)
    g4.add_argument("--head-ref", required=True, help="the locally fetched pull-request ref (objects only); must resolve to --head-sha")
    g4.add_argument("--base-tip-sha", required=True)
    g4.add_argument("--pr-author", required=True)
    g4.add_argument("--reviews-json")
    g4.add_argument("--check-runs-json")
    g4.add_argument("--tools-provenance", choices=("TRUSTED_BASE", "UNTRUSTED_TOOL_SOURCE"), required=True)
    g4.add_argument("--out-dir", required=True)
    g4.add_argument("--summary")
    en = sub.add_parser("enforcement")
    en.add_argument("--protection-json", help="owner's `gh api repos/<o>/<r>/branches/main/protection` output (omit if it returns 403)")
    en.add_argument("--rules-json", help="owner's `gh api repos/<o>/<r>/rules/branches/main` output")
    en.add_argument("--output")
    a = ap.parse_args(argv)
    return {"verdict": cmd_verdict, "v4": cmd_v4, "compare": cmd_compare, "gate": cmd_gate, "enforcement": cmd_enforcement}[a.cmd](a)


if __name__ == "__main__":
    sys.exit(main())
