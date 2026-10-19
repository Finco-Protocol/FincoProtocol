"""RC-7C release-closed candidate successor - exact-content RECOGNITION of the RC-7C quarterly candidate. Not an approval, not a release.

RC-7C (candidate policy ``rc7c-quarterly-candidate-v2``) changes exactly FOUR of the twelve protected RC-7B blobs. The RC-7B post-merge successor
(``rc7b_postmerge_successor``) deliberately recognises only the original twelve RC-7B blobs and is NOT widened here. This module is a separate,
explicitly scoped successor: it is true only while ALL of these hold (every uncertainty is a rejection):

1. authentic ancestry: the literal PR #320 merge commit (with its two parents) and the literal PR #326 merge commit ``RC7C_BASE_MAIN`` exist and are
   ancestors of the evaluated ref, and the immutable RC-7B predecessor content (twelve RC-7B blobs) is what the PR #320 merge carried;
2. the eight RC-7B blobs that RC-7C does not touch are still the exact RC-7B blobs, and the four RC-7C paths are exactly the pinned RC-7C blobs;
3. the protected-namespace diff against the RC-7B predecessor is exactly the twelve candidate paths, and against the PR #320 merge exactly the four
   RC-7C paths: no other ``financial_engine/``, ``finco_core/`` or ``domain/`` path may differ;
4. the historical authority files and the isolated quarterly research reference are byte-identical to the predecessor, ``ACTIVATION_ENABLED`` is a
   literal ``False`` and the RC-7C policy version literal is present in ``calendar_policy.py``.

It grants recognition of bytes ONLY. It is not Financial Owner approval of the four RC-7C blobs (the PR #320 owner decision does not cover them), not
D-01..D-12 approval, not Gate P, not product admission, not activation, not a financial release. Every approval state below is a constant ``False``:
adopting RC-7C as an approved candidate needs its own owner-attested and independently reviewed successor, which this module does not simulate and no
file in the repository can switch on.
"""
from __future__ import annotations

import subprocess
from pathlib import Path

try:
    import rc7b_quarterly_candidate_authority as A
    import rc7b_postmerge_successor as B
except ModuleNotFoundError:          # imported as ``tests.rc7c_candidate_successor``
    from tests import rc7b_quarterly_candidate_authority as A
    from tests import rc7b_postmerge_successor as B

ROOT = Path(__file__).resolve().parent.parent

RC7C_BASE_MAIN = "162a3d70ea0cf5b15024ecbe5f7dec33f447a48d"          # main after PR #326 (immutable history)
RC7C_POLICY_VERSION = "rc7c-quarterly-candidate-v2"
RC7C_CANDIDATE_SUCCESSOR = "RC7C_RELEASE_CLOSED_CANDIDATE_SUCCESSOR"
RC7C_CHANGED_PATHS = (
    "finco_core/engine/calendar_policy.py",
    "finco_core/engine/period_engine.py",
    "financial_engine/orchestrator.py",
    "financial_engine/senior_debt/project_adapter.py",
)
RC7C_CHANGED_BLOBS = {
    "finco_core/engine/calendar_policy.py": "7021648c8a354b928a1e6bd45a0c7b8c897cc8cc",
    "finco_core/engine/period_engine.py": "d72de84d082962d9c49a840178211602495c027a",
    "financial_engine/orchestrator.py": "b6dc102ea18be4d40adc4a7ad08f187af17c5076",
    "financial_engine/senior_debt/project_adapter.py": "7ffbf1a6de79f46a38f5bf58190b8a7d6e573a8b",
}
# The complete protected candidate: eight unchanged RC-7B blobs + the four RC-7C blobs (same twelve paths as RC-7B).
RC7C_UNCHANGED_RC7B_PATHS = tuple(p for p in A.RC7B_CANDIDATE_AUTHORITIES if p not in RC7C_CHANGED_BLOBS)
RC7C_CANDIDATE_AUTHORITIES = {p: RC7C_CHANGED_BLOBS.get(p, pin) for p, pin in A.RC7B_CANDIDATE_AUTHORITIES.items()}
assert len(RC7C_UNCHANGED_RC7B_PATHS) == 8 and set(RC7C_CANDIDATE_AUTHORITIES) == set(A.RC7B_CANDIDATE_AUTHORITIES)

_CACHE: dict = {}


def rc7c_violations(*, repo=None, ref: str = "HEAD") -> list[str]:
    """[] only when ``ref`` is exactly the release-closed RC-7C candidate. Pure Git facts; no network, no records."""
    root = repo or ROOT
    try:
        head = A._git(root, "rev-parse", f"{ref}^{{commit}}")
        if head is None:
            return ["RC7C_REF_UNRESOLVABLE: the evaluated ref does not resolve"]
        key = (str(root), head)
        if key in _CACHE:
            return list(_CACHE[key])
        bad: list[str] = []
        # 1. authentic ancestry and immutable RC-7B predecessor content
        merge = A._git(root, "rev-parse", f"{B.RC7B_MERGE_COMMIT}^{{commit}}")
        if merge != B.RC7B_MERGE_COMMIT:
            bad.append("RC7C_PROVENANCE_MISSING: the PR #320 merge commit is not available")
        else:
            parents = (A._git(root, "show", "-s", "--format=%P", merge) or "").split()
            if tuple(parents) != B.RC7B_MERGE_PARENTS:
                bad.append("RC7C_PROVENANCE_INVALID: the PR #320 merge commit does not have the predecessor and the reviewed PR head as parents")
            if not B._is_ancestor(root, merge, head):
                bad.append("RC7C_ANCESTRY_MISSING: the PR #320 merge commit is not an ancestor of the evaluated ref")
            for path, pin in A.RC7B_CANDIDATE_AUTHORITIES.items():
                if A.blob(path, repo=root, ref=merge) != pin:
                    bad.append(f"RC7C_PREDECESSOR_CONTENT_CHANGED: {path} at the PR #320 merge is not the RC-7B blob")
        base = A._git(root, "rev-parse", f"{RC7C_BASE_MAIN}^{{commit}}")
        if base != RC7C_BASE_MAIN:
            bad.append("RC7C_BASE_MISSING: the PR #326 merge commit is not available")
        elif not B._is_ancestor(root, base, head):
            bad.append("RC7C_BASE_ANCESTRY_MISSING: the PR #326 merge commit is not an ancestor of the evaluated ref")
        # 2. exact blobs: eight unchanged RC-7B, four RC-7C
        for path in RC7C_UNCHANGED_RC7B_PATHS:
            if A.blob(path, repo=root, ref=head) != A.RC7B_CANDIDATE_AUTHORITIES[path]:
                bad.append(f"RC7C_BLOB_MISMATCH: {path} is not the exact unchanged RC-7B blob")
        for path in RC7C_CHANGED_PATHS:
            if A.blob(path, repo=root, ref=head) != RC7C_CHANGED_BLOBS[path]:
                bad.append(f"RC7C_BLOB_MISMATCH: {path} is not the exact RC-7C candidate blob")
        # 3. change scope: against the RC-7B predecessor exactly the twelve paths; against the PR #320 merge exactly the four RC-7C paths
        facts = A.collect(repo=root, ref=head)
        changes = facts["protected_changes"]
        if changes is None:
            bad.append("RC7C_SCOPE_UNAVAILABLE: the protected-path diff against the immutable predecessor is unavailable")
        else:
            unlisted = [p for p in changes if p not in A.RC7B_CANDIDATE_AUTHORITIES]
            if unlisted:
                bad.append(f"RC7C_UNLISTED_CHANGES: unlisted financial/core/domain changes against the predecessor: {unlisted}")
            if [p for p in A.RC7B_CANDIDATE_AUTHORITIES if p not in changes]:
                bad.append("RC7C_PARTIAL_SLICE: reviewed protected files are not part of the change")
        if merge == B.RC7B_MERGE_COMMIT:
            since = A._git(root, "diff", "--name-only", "--no-renames", merge, head, "--", *A.PROTECTED_PREFIXES)
            if since is None:
                bad.append("RC7C_SCOPE_UNAVAILABLE: the protected-path diff against the PR #320 merge is unavailable")
            elif sorted(since.splitlines()) != sorted(RC7C_CHANGED_PATHS):
                bad.append(f"RC7C_SCOPE_MISMATCH: protected changes since the PR #320 merge are {sorted(since.splitlines())}, "
                           f"not exactly the four RC-7C paths")
        # 4. historical authorities, research reference, closed flag, policy version
        if facts["predecessor_valid"] is not True:
            bad.append("RC7C_PREDECESSOR_UNAVAILABLE: the immutable RC-7B predecessor is unavailable or not an ancestor")
        if facts["source_head_ancestor"] is not True:
            bad.append("RC7C_SOURCE_PROVENANCE_INVALID: the reviewed RC-7B source head is not an ancestor")
        if facts["historical_authorities_unchanged"] is not True:
            bad.append("RC7C_HISTORICAL_AUTHORITY_CHANGED: historical financial authority maps changed or are unavailable")
        if facts["research_unchanged"] is not True:
            bad.append("RC7C_RESEARCH_CHANGED: the isolated research reference under tools/quarterly_research changed")
        if facts["activation"] != "CLOSED":
            bad.append(f"RC7C_ACTIVATION_NOT_CLOSED: quarterly activation is not a literal release-closed False ({facts['activation']})")
        policy_source = A._git(root, "show", f"{head}:finco_core/engine/calendar_policy.py") or ""
        if f'"{RC7C_POLICY_VERSION}"' not in policy_source:
            bad.append("RC7C_POLICY_VERSION_MISSING: the exact RC-7C policy version literal is absent from calendar_policy.py")
        _CACHE[key] = tuple(bad)
        return bad
    except Exception as exc:                                   # noqa: BLE001 - fail closed
        return [f"RC7C_FACTS_UNAVAILABLE: {exc!r}"]


def rc7c_recognized(*, repo=None, ref: str = "HEAD") -> bool:
    return rc7c_violations(repo=repo, ref=ref) == []


def states(*, repo=None, ref: str = "HEAD") -> dict:
    """Independent states, never one boolean. Recognition may be true; every approval, admission and release state is a constant False."""
    recognised = rc7c_recognized(repo=repo, ref=ref)
    return {
        "historical_pr320_integration_verified": recognised,
        "exact_rc7c_content_verified": recognised,
        "release_closed_candidate_recognized": recognised,
        "financial_owner_approval_of_rc7c_blobs": False,          # the PR #320 owner decision does not cover the four RC-7C blobs
        "d01_d12_financial_policy_approval": False,
        "gate_p": False,
        "product_admission": False,
        "quarterly_activation": A.collect(repo=repo, ref=ref)["activation"] != "CLOSED",
        "financial_release": False,
    }
