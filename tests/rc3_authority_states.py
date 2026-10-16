"""Financial-authority STATE classifier for the post-RC-3 main (not an approval, adds no allowlist).

The historical guards asked one question of every protected path - "is this blob a *released* authority?" - and so mislabelled content that is
deliberately in a different state. Three states are kept apart and are never collapsed into a single "approved" boolean:

HISTORICAL_RELEASED                  the exact blob is in a released pin map (WF07, F3.5, Developer Economics, Revenue V2/V3, ...), judged by
                                     ``model_v2_governance.released_engine_authority_matches`` against its own historical checkpoint.
INTEGRATED_RELEASE_CLOSED_CANDIDATE  the exact M7 candidate blob that PR #284 put on main, or one of the three exact PPA-01 candidate blobs
                                     (tests/ppa01_candidate_authority.py, RC-3 C2): present, byte-identical to the reviewed source head,
                                     NOT released, NOT activated. Requires every release flag to be literal False.
ACTIVATED_FINANCIAL_AUTHORITY        needs a separate independent financial AND production-release approval. No code path here can return it for
                                     M7: it is unavailable by construction.

Any other content is UNAUTHORIZED. ``released_engine_authority_matches`` and every pin map are untouched.
"""
from __future__ import annotations

import subprocess
from pathlib import Path

from tests.m7_rc3_candidate_successor import (
    M7_RC3_CANDIDATE_AUTHORITIES as M7_CANDIDATE, M7_REVIEWED_SOURCE_HEAD, RC2_CHECKPOINT,
)

HISTORICAL_RELEASED = "HISTORICAL_RELEASED"
INTEGRATED_RELEASE_CLOSED_CANDIDATE = "INTEGRATED_RELEASE_CLOSED_CANDIDATE"
ACTIVATED_FINANCIAL_AUTHORITY = "ACTIVATED_FINANCIAL_AUTHORITY"
UNAUTHORIZED = "UNAUTHORIZED"

REPO = Path(__file__).resolve().parent.parent
# Release flags that must stay a literal ``False`` for the candidate state to exist at all.
RELEASE_FLAGS = {
    "app/workbook/bess_config.py": "ACTIVATION_ENABLED",
    "app/model_v2/acquisition/economics.py": "ACTIVATION_ENABLED",
    "app/workbook/junior_debt_config.py": "ACTIVATION_ENABLED",
    "domain/revenue/advanced_products.py": "ACTIVATION_ENABLED",
}
MANIFEST = "docs/model_v2/M7_BESS_FINANCIAL_CANDIDATE_MANIFEST.json"


def _blob(path: str, repo, ref: str):
    proc = subprocess.run(["git", "rev-parse", f"{ref}:{path}"], cwd=str(repo or REPO), capture_output=True, text=True)
    return proc.stdout.strip() if proc.returncode == 0 else None


def candidate_matches(path: str, *, repo=None, ref: str = "HEAD") -> bool:
    """Exact-content test of the M7 candidate blob ONLY. This is not an authority check."""
    pinned = M7_CANDIDATE.get(path)
    return pinned is not None and _blob(path, repo, ref) == pinned


def release_closed_violations(*, repo=None, ref: str = "HEAD") -> list[str]:
    """What must hold for the candidate state to exist: every flag literal False, manifest closed. [] means release-closed."""
    import json
    from tests.test_rc2_integration_manifest import activation_state
    bad = []
    root = Path(repo or REPO)
    for path, name in RELEASE_FLAGS.items():
        shown = subprocess.run(["git", "show", f"{ref}:{path}"], cwd=str(root), capture_output=True, text=True)
        if shown.returncode != 0 or activation_state(shown.stdout + "\n", name) != "CLOSED":
            bad.append(f"{path}: {name} is not a literal release-closed False")
    shown = subprocess.run(["git", "show", f"{ref}:{MANIFEST}"], cwd=str(root), capture_output=True, text=True)
    try:
        if json.loads(shown.stdout).get("release_approved") is not False:
            bad.append("the M7 manifest asserts a release it does not have")
    except ValueError:
        bad.append("the M7 manifest is missing or malformed")
    return bad


def authority_state(path: str, *, repo=None, ref: str = "HEAD") -> str:
    """HISTORICAL_RELEASED, INTEGRATED_RELEASE_CLOSED_CANDIDATE or UNAUTHORIZED. Never ACTIVATED_FINANCIAL_AUTHORITY for M7."""
    import model_v2_governance as governance
    if governance.released_engine_authority_matches(path, repo=repo, ref=ref):
        return HISTORICAL_RELEASED
    if candidate_matches(path, repo=repo, ref=ref) and not release_closed_violations(repo=repo, ref=ref):
        return INTEGRATED_RELEASE_CLOSED_CANDIDATE
    if ppa01_candidate_matches(path, repo=repo, ref=ref) and not release_closed_violations(repo=repo, ref=ref):
        return INTEGRATED_RELEASE_CLOSED_CANDIDATE
    return UNAUTHORIZED


def ppa01_candidate_matches(path: str, *, repo=None, ref: str = "HEAD") -> bool:
    """Exact-content test of the PPA-01 candidate: the path is one of the three AND all three blobs are the reviewed ones. Not an authority check."""
    from ppa01_candidate_authority import frozen_scope_exempt
    return frozen_scope_exempt(path, repo=repo, ref=ref)


def historical_checkpoint() -> str:
    """The commit at which the original pin maps were accepted (RC-2 main merge)."""
    return RC2_CHECKPOINT
