"""RC-7B post-merge release-closed successor - exact-content RECOGNITION of an already merged candidate. Not an approval, not a release.

PR #320 was merged through GitHub as a normal merge commit. The Gate R mechanism in ``rc7b_quarterly_candidate_authority`` is a PRE-merge
authorization process (signed Financial Owner attestation + authentic independent review). That process never ran, and this module neither
re-opens it nor fabricates any of its records: ``gate_r_active`` keeps its meaning and is still False in this repository.

``RC7B_POSTMERGE_RELEASE_CLOSED_SUCCESSOR`` answers one bounded question for the CURRENT-authority guards:

    "Is the tree under test exactly the release-closed RC-7B candidate that the historical merge integrated?"

It is true only while ALL of these hold (every uncertainty is a rejection):

1. the literal merge commit ``RC7B_MERGE_COMMIT`` exists, has exactly the parents (immutable predecessor, reviewed PR head) and is an ancestor of
   the evaluated ref (authentic merge ancestry);
2. the twelve protected blobs equal the pinned candidate blobs at the merge commit, at the PR head and at the evaluated ref, and the reviewed
   source head is an ancestor of the PR head;
3. the existing exact-content validator (``content_violations``) is empty: no other ``financial_engine/``, ``finco_core/`` or ``domain/`` path differs
   from the immutable predecessor, the historical authority maps (M7 / PPA-01 / radar) and the isolated quarterly research reference are
   byte-identical to the predecessor, and ``ACTIVATION_ENABLED`` is a literal ``False``.

It grants recognition of bytes on main ONLY. It is not Financial Owner approval, not D-01..D-12 approval, not Gate P, not product admission, not
activation and not a release; ``approved_frozen_path`` and ``released_engine_authority_matches`` never consult it, and a later quarterly change
(for example a different blob for any of the twelve paths) is rejected here and needs its own reviewed successor.
"""
from __future__ import annotations

import subprocess
from pathlib import Path

try:
    import rc7b_quarterly_candidate_authority as A
except ModuleNotFoundError:          # imported as ``tests.rc7b_postmerge_successor``
    from tests import rc7b_quarterly_candidate_authority as A

ROOT = Path(__file__).resolve().parent.parent

# Historical GitHub facts of PR #320 (verified live against GitHub at hotfix time; the merge is immutable history).
RC7B_MERGE_COMMIT = "bf0167a036a6e30d3225b901aeda1b353681171a"
RC7B_MERGED_PR_HEAD = "e9c3326a9f8b7791cd8032102347a735c12178e4"
RC7B_MERGE_PARENTS = (A.RC7B_PREDECESSOR, RC7B_MERGED_PR_HEAD)
RC7B_POSTMERGE_RELEASE_CLOSED_SUCCESSOR = "RC7B_POSTMERGE_RELEASE_CLOSED_SUCCESSOR"

_CACHE: dict = {}


def _run(root, *args):
    return subprocess.run(["git", *args], cwd=str(root), capture_output=True, text=True)


def _is_ancestor(root, ancestor: str, descendant: str) -> bool:
    return _run(root, "merge-base", "--is-ancestor", ancestor, descendant).returncode == 0


def postmerge_violations(*, repo=None, ref: str = "HEAD") -> list[str]:
    """[] only when ``ref`` is exactly the merged, release-closed RC-7B candidate. Pure Git facts; no network, no records."""
    root = repo or ROOT
    try:
        head = A._git(root, "rev-parse", f"{ref}^{{commit}}")
        if head is None:
            return ["POSTMERGE_REF_UNRESOLVABLE: the evaluated ref does not resolve"]
        key = (str(root), head)
        if key in _CACHE:
            return list(_CACHE[key])
        bad: list[str] = []
        merge = A._git(root, "rev-parse", f"{RC7B_MERGE_COMMIT}^{{commit}}")
        if merge != RC7B_MERGE_COMMIT:
            bad.append("POSTMERGE_PROVENANCE_MISSING: the PR #320 merge commit is not available")
        else:
            parents = (A._git(root, "show", "-s", "--format=%P", merge) or "").split()
            if tuple(parents) != RC7B_MERGE_PARENTS:
                bad.append("POSTMERGE_PROVENANCE_INVALID: the merge commit does not have the predecessor and the reviewed PR head as parents")
            if not _is_ancestor(root, merge, head):
                bad.append("POSTMERGE_ANCESTRY_MISSING: the PR #320 merge commit is not an ancestor of the evaluated ref")
            if not _is_ancestor(root, A.RC7B_REVIEWED_SOURCE_HEAD, RC7B_MERGED_PR_HEAD):
                bad.append("POSTMERGE_SOURCE_PROVENANCE_INVALID: the reviewed RC-7B source head is not an ancestor of the merged PR head")
            for label, rev in (("merge commit", merge), ("merged PR head", RC7B_MERGED_PR_HEAD), ("evaluated ref", head)):
                for path, pin in A.RC7B_CANDIDATE_AUTHORITIES.items():
                    if A.blob(path, repo=root, ref=rev) != pin:
                        bad.append(f"POSTMERGE_BLOB_MISMATCH: {path} at the {label} is not the exact RC-7B candidate blob")
        # exact content at the evaluated ref: twelve blobs, no other protected change, intact historical maps/research, literal-False flag
        bad += A.content_violations(A.collect(repo=root, ref=head))
        _CACHE[key] = tuple(bad)
        return bad
    except Exception as exc:                                   # noqa: BLE001 - fail closed
        return [f"POSTMERGE_FACTS_UNAVAILABLE: {exc!r}"]


def postmerge_recognized(*, repo=None, ref: str = "HEAD") -> bool:
    return postmerge_violations(repo=repo, ref=ref) == []


def candidate_recognized(*, repo=None, ref: str = "HEAD", fetcher=None) -> bool:
    """Release-closed RC-7B candidate recognition for the current-authority guards: the historical post-merge successor, or (unchanged, pre-merge
    machinery) a complete authentic Gate R. Neither is an approval."""
    return postmerge_recognized(repo=repo, ref=ref) or A.gate_r_active(repo=repo, ref=ref, fetcher=fetcher)


def scope_exempt(path: str, *, repo=None, ref: str = "HEAD", fetcher=None) -> bool:
    """One of the twelve exact paths while the whole exact candidate is recognised. Never consulted by ``approved_frozen_path``."""
    return path in A.RC7B_CANDIDATE_AUTHORITIES and candidate_recognized(repo=repo, ref=ref, fetcher=fetcher)


def superseded(path: str, *, repo=None, ref: str = "HEAD", fetcher=None) -> bool:
    return scope_exempt(path, repo=repo, ref=ref, fetcher=fetcher)


def current_expected_blob(path: str, historical_pin, *, repo=None, ref: str = "HEAD", fetcher=None):
    """The candidate blob for a recognised path, otherwise the historical pin (which is never rewritten)."""
    return A.RC7B_CANDIDATE_AUTHORITIES[path] if superseded(path, repo=repo, ref=ref, fetcher=fetcher) else historical_pin


def without_superseded(paths, *, repo=None, ref: str = "HEAD", fetcher=None) -> list[str]:
    return [p for p in paths if not superseded(p, repo=repo, ref=ref, fetcher=fetcher)]


def states(*, repo=None, ref: str = "HEAD") -> dict:
    """The independent states, never one boolean. Only the first three can be true; every approval, admission and release state is False."""
    root = repo or ROOT
    facts = A.collect(repo=root, ref=ref)
    recognised = postmerge_recognized(repo=root, ref=ref)
    return {
        "historical_pr320_integration_verified": recognised,
        "exact_rc7b_content_verified": A.content_violations(facts) == [],
        "release_closed_candidate_recognized": recognised,
        "financial_owner_approval": A.acceptance_violations(facts) == [],
        "gate_r_active": A.gate_r_active(repo=root, ref=ref),
        "d01_d12_financial_policy_approval": False,
        "gate_p": False,
        "product_admission": A.admission_violations(facts) == [],
        "quarterly_activation": facts["activation"] != "CLOSED",
        "financial_release": A.release_violations(facts) == [],
    }
