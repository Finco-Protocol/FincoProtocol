"""V9-P2a / OD-R chained successor PROPOSAL - exact-content description only. Not an approval, not wired, not a release.

The Financial Owner approved the OD-R policy ("Final-State SHL Maturity Authority") in principle. That approval does NOT cover
exact protected content. This module records, for independent review, the exact before/after blobs of the protected paths the
V9-P2a candidate changes on top of the RC-7C / main authority (main ``5996453b``).

It is deliberately NOT imported by ``tests/quarterly_candidate_recognition.py`` or any other current-authority guard: the guards
keep rejecting the changed protected blobs until a separate, owner-attested and independently reviewed successor adopts them.
Every content/release approval state below is a constant ``False``. Policy approval in principle is separate.
"""
from __future__ import annotations

import subprocess
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent

PREDECESSOR_MAIN = "5996453b8d5bbfaa48bc06922fc6963cf94d2f84"     # main after PR #325 (RC-7C)
INTEGRATION_MAIN = "96e5816478306e240a5872662eae449647921595"     # normal merge of PR #333; financial authority unchanged
INTEGRATION_PARENTS = (PREDECESSOR_MAIN, "78b2882859b65ee7569d5de5c925c66d4bb2bfee")
CANDIDATE_CHECKPOINT = "dddfff4ead725707bc53a37be1c5a87b8f596857"
POLICY = "OD_R_FINAL_STATE_SHL_MATURITY_V1"
RELEASE_STATE = "RELEASE_CLOSED_CANDIDATE_DEFAULT_POLICY_CANONICAL"

# Predecessor blobs at PREDECESSOR_MAIN (``None`` = new file).
PREDECESSOR_BLOBS = {
    "financial_engine/financing/generic_product_policy.py": "59a2c1f868b4c12718a22919c3114f3af5af5120",
    "financial_engine/financing/project.py": "2e18a6e7c8ddfd85929d9b1906f91dd8858d0044",
    "financial_engine/orchestrator.py": "b6dc102ea18be4d40adc4a7ad08f187af17c5076",
    "financial_engine/shareholder_waterfall/model.py": "e3473e1a2064c8310e41b434da2b0aff9d5753b8",
    "financial_engine/shl/maturity_authority.py": None,
    "financial_engine/shl/production.py": "744b384cfa1652588817e77b8f1c04f8a36fc75f",
}
# Exact candidate blobs proposed for review (filled from the committed candidate content).
CANDIDATE_BLOBS: dict[str, str] = {
    "financial_engine/financing/generic_product_policy.py": "293d896ac474f47ea74a93ac5ac5d7a587f1446b",
    "financial_engine/financing/project.py": "16ab1921b539ec3ed42d55554b1392ce781e6ce5",
    "financial_engine/orchestrator.py": "85c8008f2b4a656fd28eea1169689b19131576e4",
    "financial_engine/shareholder_waterfall/model.py": "6ab84043c0267832125a073a3a881e1e86ac0e3d",
    "financial_engine/shl/maturity_authority.py": "8383eb2d735f310a09d9f080134a314efb276ba6",
    "financial_engine/shl/production.py": "9bb852c235a988bff994c4327b3b63dd6d77ae20",
}
CANDIDATE_SOURCE_COMMIT = "84e17358ef739f422cda7bd546e5c2af23bf4506"   # Correction A, NOT a financial approval
# Superseded (stale) candidate blobs of d7995f30, before Correction A:
SUPERSEDED_CANDIDATE_BLOBS = {
    "financial_engine/financing/project.py": "75b18d4a840ed328b6b005e0cefca4db8741e069",
    "financial_engine/shl/maturity_authority.py": "be2e6d9bc946dddf1880e3a0b7b5f8b3414aeb1f",
}
# Non-protected application change carried by the same candidate (provenance metadata only).
APPLICATION_BLOBS = {
    "app/services/production_financial_authority.py": (
        "173991ca8107169672bbf977fe2fad91af520e9c", "89083cd41a4de029ae3c57ee0a4f4a871c7863bd"),
}

EVIDENCE_BLOBS = {
    "docs/model_v2/V9P2A_ODR_ACCEPTANCE_EVIDENCE.json": "707fb20a873a1f142cdde4735cfe0ab308cd123e",
    "tools/v9p2a_odr_acceptance.py": "4b03d1fa9cd17d24efc53fe1dc8bd603b58e4a25",
    "tests/test_v9p2a_odr_final_state_authority.py": "0612c3aa429c6bbecb80f500b2fa3ff4861653da",
    "tests/test_v9p2a_odr_run_commit_safety.py": "d7d265f2819fe69ee4189011739349eaded0dd12",
}
HISTORICAL_GUARDS = (
    "tests/model_v2_governance.py", "tests/finance_integrity_governance.py",
    "tests/m7_rc3_candidate_successor.py", "tests/ppa01_candidate_authority.py",
    "tests/rc3_authority_states.py", "tests/rc7b_quarterly_candidate_authority.py",
    "tests/rc7b_postmerge_successor.py", "tests/rc7c_candidate_successor.py",
    "tests/quarterly_candidate_recognition.py",
)
METADATA_PATHS = frozenset({
    "tests/v9p2a_odr_candidate_proposal.py", "tests/test_v9p2a_odr_candidate_proposal.py",
    "docs/model_v2/V9P2A_ODR_FINAL_STATE_SHL_AUTHORITY.md",
    "docs/model_v2/V9P2A_ODR_GOVERNANCE_CORRECTION_B.md",
})
PROTECTED_PREFIXES = ("financial_engine/", "finco_core/", "domain/")


def _git(*args: str, repo=None):
    try:
        proc = subprocess.run(["git", *args], cwd=str(repo or ROOT), capture_output=True,
                              text=True, encoding="utf-8", timeout=30)
        return proc.stdout.strip() if proc.returncode == 0 else None
    except (OSError, ValueError, subprocess.TimeoutExpired):
        return None


def blob(path: str, ref: str = "HEAD", *, repo=None):
    return _git("rev-parse", "--verify", "--end-of-options", f"{ref}:{path}", repo=repo)


def content_matches_proposal(ref: str = "HEAD", *, repo=None) -> bool:
    """Bytes only: the evaluated ref carries exactly the proposed candidate blobs."""
    return bool(CANDIDATE_BLOBS) and all(blob(p, ref, repo=repo) == b for p, b in CANDIDATE_BLOBS.items())


def candidate_violations(ref: str = "HEAD", *, repo=None) -> list[str]:
    """Exact, unapproved candidate recognition only; grants no guard exemption.

    Historical RC-7C is evaluated at its immutable checkpoints, not relabelled
    from the OD-R tree. Expected content is never inferred from arbitrary HEAD.
    """
    root = repo or ROOT
    resolve = lambda value: _git("rev-parse", "--verify", "--end-of-options",
                                 f"{value}^{{commit}}", repo=root)
    head = resolve(ref)
    if head is None:
        return ["ODR_REF_UNAVAILABLE"]
    bad = []
    for checkpoint in (PREDECESSOR_MAIN, INTEGRATION_MAIN, CANDIDATE_SOURCE_COMMIT, CANDIDATE_CHECKPOINT):
        if resolve(checkpoint) != checkpoint:
            bad.append(f"ODR_PREDECESSOR_MISSING: {checkpoint}")
        elif _git("merge-base", "--is-ancestor", checkpoint, head, repo=root) is None:
            bad.append(f"ODR_ANCESTRY_INVALID: {checkpoint}")
    if bad:
        return bad
    parents = _git("show", "-s", "--format=%P", INTEGRATION_MAIN, repo=root)
    if parents is None or tuple(parents.split()) != INTEGRATION_PARENTS:
        bad.append("ODR_INTEGRATION_LINEAGE_INVALID")
    if set(CANDIDATE_BLOBS) != set(PREDECESSOR_BLOBS) or len(CANDIDATE_BLOBS) != 6:
        bad.append("ODR_MANIFEST_PATHS_INVALID")
    for path, before in PREDECESSOR_BLOBS.items():
        if blob(path, PREDECESSOR_MAIN, repo=root) != before or blob(path, INTEGRATION_MAIN, repo=root) != before:
            bad.append(f"ODR_PREDECESSOR_BLOB_MISMATCH: {path}")
        expected = CANDIDATE_BLOBS.get(path)
        if (not expected or blob(path, CANDIDATE_SOURCE_COMMIT, repo=root) != expected
                or blob(path, CANDIDATE_CHECKPOINT, repo=root) != expected):
            bad.append(f"ODR_MANIFEST_STALE: {path}")
        if blob(path, head, repo=root) != expected:
            bad.append(f"ODR_CANDIDATE_BLOB_MISMATCH: {path}")
    unchanged = _git("diff", "--name-only", "--no-renames", PREDECESSOR_MAIN,
                     INTEGRATION_MAIN, "--", *PROTECTED_PREFIXES, repo=root)
    if unchanged != "":
        bad.append("ODR_INTEGRATION_FINANCIAL_PREDECESSOR_CHANGED")
    changed = _git("diff", "--name-only", "--no-renames", INTEGRATION_MAIN, head,
                   "--", *PROTECTED_PREFIXES, repo=root)
    if changed is None or set(changed.splitlines()) != set(PREDECESSOR_BLOBS):
        bad.append("ODR_PROTECTED_SCOPE_INVALID")
    for path, (before, after) in APPLICATION_BLOBS.items():
        if blob(path, INTEGRATION_MAIN, repo=root) != before or blob(path, head, repo=root) != after:
            bad.append(f"ODR_APPLICATION_BLOB_MISMATCH: {path}")
    for path, expected in EVIDENCE_BLOBS.items():
        if blob(path, CANDIDATE_CHECKPOINT, repo=root) != expected or blob(path, head, repo=root) != expected:
            bad.append(f"ODR_EVIDENCE_BLOB_MISMATCH: {path}")
    for path in HISTORICAL_GUARDS:
        historical = blob(path, PREDECESSOR_MAIN, repo=root)
        if (historical is None or blob(path, INTEGRATION_MAIN, repo=root) != historical
                or blob(path, head, repo=root) != historical):
            bad.append(f"ODR_HISTORICAL_GUARD_CHANGED: {path}")
    allowed = set(PREDECESSOR_BLOBS) | set(APPLICATION_BLOBS) | set(EVIDENCE_BLOBS) | METADATA_PATHS
    all_changes = _git("diff", "--name-only", "--no-renames", INTEGRATION_MAIN, head, repo=root)
    if all_changes is None or set(all_changes.splitlines()) - allowed:
        bad.append("ODR_UNLISTED_CHANGE")
    if not bad:
        try:
            from tests.rc7c_candidate_successor import rc7c_violations
            from tests.rc3_authority_states import release_closed_violations
            for checkpoint in (PREDECESSOR_MAIN, INTEGRATION_MAIN):
                if rc7c_violations(repo=root, ref=checkpoint):
                    bad.append(f"ODR_HISTORICAL_RC7C_INVALID: {checkpoint}")
            if release_closed_violations(repo=root, ref=head):
                bad.append("ODR_ACTIVATION_NOT_CLOSED")
        except Exception:
            bad.append("ODR_HISTORICAL_EVIDENCE_UNAVAILABLE")
    return bad


def candidate_recognized(ref: str = "HEAD", *, repo=None) -> bool:
    return not candidate_violations(ref, repo=repo)


def states(ref: str = "HEAD", *, repo=None) -> dict:
    return {
        "exact_candidate_content_present": content_matches_proposal(ref, repo=repo),
        "chained_candidate_recognized": candidate_recognized(ref, repo=repo),
        "od_r_policy_approved_in_principle": True,          # Financial Owner decision OD-R (policy only)
        "protected_content_approved": False,
        "independent_financial_review": False,
        "wired_into_current_authority_guards": False,
        "product_activation": False,
        "financial_release": False,
    }
