"""RC-3 historical-stream anchor (not an approval).

Two different questions must not be conflated on the integrated RC-3 branch:

* HISTORICAL STREAM SCOPE - did an original stream (Crypto, Radar, Opus, Staging, P-series, cost templates ...) change financial
  authority? Those guards diff ``merge-base(origin/main, HEAD)..HEAD``. On the integrated branch HEAD also contains the M7 BESS
  financial candidate, which none of those streams own, so they would report a change they did not make.
* CURRENT INTEGRATION AUTHORITY - are the M7 financial changes independently accepted and exactly protected? That is answered by
  the owner gates (tests/finance_integrity_governance.py consumers, WF07, CI acceptance - all still red until an approval exists)
  and by tests/test_rc3_integration_inventory.py (exact paths and blobs).

While the RC-3 integration is still pending, the historical stream guards therefore evaluate the immutable pre-M7 integration tip
(the merge of #280, #279, #281 and #282: every accepted stream, no financial-namespace change). The anchor falls back to plain HEAD -
the original behaviour - on ANY uncertainty, and permanently once that tip is contained in origin/main.
"""
from __future__ import annotations

import subprocess
from pathlib import Path

REPO = Path(__file__).resolve().parents[1]
# Merge commit of PR #282 inside the RC-3 integration: contains R4, R5, Diagnostics V2 and M6, NOT the M7 financial candidate.
STREAM_TIP = "f2a1e386481b11a0a2b5fb8a73206403c839a480"
# RC-3 / C2: merge commit of PR #292 inside the model/radar integration RC (#294). It contains the accepted Radar R6 (#290), Radar closeout (#291)
# and Run-Provenance/Statements (#292) streams and NOT the PPA-01 financial candidate (#293), which none of those streams own. Verified: no
# financial_engine/, finco_core/ or domain/ path differs from origin/main at this commit. Newest first; the first usable tip wins.
PPA01_PRE_INTEGRATION_TIP = "30473e36de681040a79efb381eddd3968f12af3e"
STREAM_TIPS = (PPA01_PRE_INTEGRATION_TIP, STREAM_TIP)


def _rc(*args: str) -> int:
    return subprocess.run(["git", *args], cwd=REPO, capture_output=True).returncode


def _out(*args: str) -> str:
    return subprocess.run(["git", *args], cwd=REPO, capture_output=True, text=True, check=True).stdout.strip()


def _usable(tip: str) -> bool:
    if _rc("cat-file", "-e", f"{tip}^{{commit}}") != 0:
        return False
    if _rc("merge-base", "--is-ancestor", tip, "HEAD") != 0:
        return False
    if _rc("rev-parse", "--verify", "-q", "origin/main") != 0:
        return False
    return _rc("merge-base", "--is-ancestor", tip, "origin/main") != 0      # already landed on main: the original guards apply to HEAD again


def anchored_head(tip: str | None = None) -> str:
    """The newest usable pre-candidate tip while the integration is pending and verifiably part of this history; otherwise ``HEAD`` (fail closed).

    With an explicit ``tip`` only that tip is considered (historical call sites). Missing provenance of every tip yields ``HEAD``, so a guard that
    cannot prove its historical boundary evaluates the full current tree and fails rather than silently passing.
    """
    try:
        for candidate in ((tip,) if tip else STREAM_TIPS):
            if _usable(candidate):
                return candidate
        return "HEAD"
    except OSError:
        return "HEAD"


def merge_base(tip: str | None = None) -> str:
    return _out("merge-base", "origin/main", tip or anchored_head())


def changed_paths(*pathspec: str) -> list[str]:
    """Paths changed on the branch side up to the anchored tip (same boundary rule as ``changed_paths_vs_main``)."""
    tip = anchored_head()
    args = ["diff", "--name-only", merge_base(tip), tip]
    if pathspec:
        args += ["--", *pathspec]
    return [line.strip() for line in _out(*args).splitlines() if line.strip()]


def branch_side_only(paths: list[str], tip: str | None = None) -> list[str]:
    """Keep only paths the branch itself changed relative to origin/main at ``tip`` (differs from main or absent there).

    Used by guards that diff against an older epic ref: paths byte-identical to origin/main are main-side history, not a change
    made by the stream under test. Anything the branch changed is still returned and must pass the unchanged approval check.
    """
    tip = tip or anchored_head()
    kept = []
    for path in paths:
        here = subprocess.run(["git", "rev-parse", f"{tip}:{path}"], cwd=REPO, capture_output=True, text=True)
        main = subprocess.run(["git", "rev-parse", f"origin/main:{path}"], cwd=REPO, capture_output=True, text=True)
        if here.returncode != 0 or main.returncode != 0 or here.stdout.strip() != main.stdout.strip():
            kept.append(path)
    return kept
