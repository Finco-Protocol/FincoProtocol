"""Content-pinned PR #237 Radar authority governance.

Only exact reviewed file paths at exact reviewed Git blob content are exempt
from historical frozen-diff checks. This never authorizes future edits.
"""
from __future__ import annotations

import subprocess
from pathlib import Path

REPO = Path(__file__).resolve().parents[1]

REVIEWED_RADAR_AUTHORITY_BLOBS: dict[str, str] = {
    "app/radar_rwa/r_live_service.py": "6c0e291db48fd208ecd1dc59e39e16dc03df273e",
    "finco_radar/venues/intelligence.py": "d5673713d6fff4e14e039ffaea75482e67bc0008",
    "finco_radar/venues/robinhood_live.py": "85b6f951516f11e08c768a05e8c6e95e5c406a15",
}


def reviewed_radar_authority_matches(
    path: str, *, repo: str | Path | None = None, ref: str = "HEAD"
) -> bool:
    """Require exact path + exact blob; fail closed on bad refs/git errors."""
    pinned = REVIEWED_RADAR_AUTHORITY_BLOBS.get(path)
    if pinned is None:
        return False
    try:
        result = subprocess.run(
            ["git", "rev-parse", "--verify", f"{ref}:{path}"],
            capture_output=True, text=True,
            cwd=str(repo if repo is not None else REPO),
        )
    except (OSError, ValueError):
        return False
    return result.returncode == 0 and result.stdout.strip() == pinned
