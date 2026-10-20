"""V9-P2a / OD-R chained successor PROPOSAL - exact-content description only. Not an approval, not wired, not a release.

The Financial Owner approved the OD-R policy ("Final-State SHL Maturity Authority") in principle. That approval does NOT cover
exact protected content. This module records, for independent review, the exact before/after blobs of the protected paths the
V9-P2a candidate changes on top of the RC-7C / main authority (main ``5996453b``).

It is deliberately NOT imported by ``tests/quarterly_candidate_recognition.py`` or any other current-authority guard: the guards
keep rejecting the changed protected blobs until a separate, owner-attested and independently reviewed successor adopts them.
Every approval state below is a constant ``False``; no file in this branch can switch them on.
"""
from __future__ import annotations

import subprocess
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent

PREDECESSOR_MAIN = "5996453b8d5bbfaa48bc06922fc6963cf94d2f84"     # main after PR #325 (RC-7C)
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
    "financial_engine/financing/project.py": "75b18d4a840ed328b6b005e0cefca4db8741e069",
    "financial_engine/orchestrator.py": "85c8008f2b4a656fd28eea1169689b19131576e4",
    "financial_engine/shareholder_waterfall/model.py": "6ab84043c0267832125a073a3a881e1e86ac0e3d",
    "financial_engine/shl/maturity_authority.py": "be2e6d9bc946dddf1880e3a0b7b5f8b3414aeb1f",
    "financial_engine/shl/production.py": "9bb852c235a988bff994c4327b3b63dd6d77ae20",
}
CANDIDATE_SOURCE_COMMIT = "d7995f30"   # implementation commit carrying exactly these blobs
# Non-protected application change carried by the same candidate (provenance metadata only).
APPLICATION_BLOBS = {
    "app/services/production_financial_authority.py": (
        "173991ca8107169672bbf977fe2fad91af520e9c", "89083cd41a4de029ae3c57ee0a4f4a871c7863bd"),
}


def _git(*args: str):
    proc = subprocess.run(["git", *args], cwd=str(ROOT), capture_output=True, text=True)
    return proc.stdout.strip() if proc.returncode == 0 else None


def blob(path: str, ref: str = "HEAD"):
    return _git("rev-parse", f"{ref}:{path}")


def content_matches_proposal(ref: str = "HEAD") -> bool:
    """Bytes only: the evaluated ref carries exactly the proposed candidate blobs."""
    return bool(CANDIDATE_BLOBS) and all(blob(p, ref) == b for p, b in CANDIDATE_BLOBS.items())


def states(ref: str = "HEAD") -> dict:
    return {
        "exact_candidate_content_present": content_matches_proposal(ref),
        "od_r_policy_approved_in_principle": True,          # Financial Owner decision OD-R (policy only)
        "protected_content_approved": False,
        "independent_financial_review": False,
        "wired_into_current_authority_guards": False,
        "product_activation": False,
        "financial_release": False,
    }
