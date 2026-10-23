"""Narrow exact-content SUCCESSOR of the PR #346 R-LIVE lifecycle pair for the Python 3.10 compatibility fix (issue #348).

Kept separate from the V10 successor. The PR #346 authority (``r_live_lifecycle_content_authority``), its owner record and its
historical assertions are never edited: they are judged unchanged AT the immutable checkpoint ``main`` ``0b57031a`` where PR #346
was merged. This successor recognises exactly one changed blob - ``app/radar_rwa/r_live_warming.py`` with the 3.10-safe
``sys.exc_info()[1]`` in place of ``sys.exception()`` - next to the unchanged ``r_live_snapshot_store.py``.

``py310_violations`` is ``[]`` only while ALL of these Git facts hold for the evaluated ref (every uncertainty rejects):

1. the immutable checkpoint and the reviewed source candidate exist with their exact trees and are ancestors in order:
   checkpoint -> source candidate -> evaluated ref; the PR #346 authority still recognises its own pair AT the checkpoint;
2. each path is its PR #346 blob at the checkpoint and EXACTLY the approved blob at the source candidate and at the evaluated ref;
   the source candidate carries no approval record (non-circular provenance);
3. the ``app/radar_rwa/`` diff from the checkpoint is exactly ``r_live_warming.py``;
4. the PR #346 authority module and owner record are byte-identical to the checkpoint; the guard adapter is exactly the reviewed
   successor blob;
5. the Financial Owner exact-content record is byte-exact (sha256 pinned here; owner authority is this reviewed code pin, never a
   self-asserting JSON field); when the evaluated ref is the checkout HEAD, the working bytes are exact too.

Recognition grants these two blobs their frozen-path place only. It never widens ``app/radar_rwa/``, never relabels the PR #346
approval and never authorizes activation, deployment, hosted runs or merge. The R-LIVE lease and publication fencing are unchanged.
"""
from __future__ import annotations

import hashlib
import json
import subprocess
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent

PR346_CHECKPOINT = {"head": "0b57031ae6949d8e7d187a1932c4451e213238f7", "tree": "608b4ae23169d2fbce084c6f63e4fd43925549b5"}
SOURCE_CANDIDATE = {"head": "f137aaccff601c2f86126e1215165a7edc81574d", "tree": "1bd953ed1967c82a76e8f7c0a84caa7347c027f1"}
# (PR #346 approved blob at the checkpoint, exact approved successor blob)
BLOBS = {
    "app/radar_rwa/r_live_snapshot_store.py": ("4179c296c803f42040b2811dc70ef55a1cdfa1d0", "4179c296c803f42040b2811dc70ef55a1cdfa1d0"),
    "app/radar_rwa/r_live_warming.py": ("563c1a256886f7b26af21ac63e121216f908c840", "c29fe4cdfe4e07df6ecd82a2a714f13f4b78d7e9"),
}
APPROVED_BLOBS = {path: after for path, (_before, after) in BLOBS.items()}
SCOPE_PREFIX = "app/radar_rwa/"
SCOPE_CHANGED = frozenset({"app/radar_rwa/r_live_warming.py"})
HISTORICAL = ("tests/r_live_lifecycle_content_authority.py", "docs/ci_v3/final/r-live-lifecycle-content-approval.json")
# Guard adapter: (checkpoint blob, exact reviewed successor blob)
WIRING_BLOBS = {"tests/r_live_lifecycle_governance.py": ("fc22ca6d34cc6de63a634503e339691ae0179744", "3ea649e983b2c634328ef24a312d49e06f408171")}
APPROVAL_PATH = "docs/ci_v3/final/r-live-lifecycle-py310-content-approval.json"
OWNER_APPROVAL_REFERENCE = "conversation:2026-10-23:PR347:Financial-Owner-Exact-Content-Approval:Decision-B"   # explicit Financial Owner exact-content decision (packet sha256 81e653c0)
OWNER_APPROVAL_SHA256 = "9a3d55ac1866381a67ecd394ed98377ea19c48f01a493f61c661778ccac17f64"

_CACHE: dict = {}


def _git(root, *args: str):
    try:
        proc = subprocess.run(["git", *args], cwd=str(root), capture_output=True, text=True, encoding="utf-8", timeout=60)
        return proc.stdout.strip() if proc.returncode == 0 else None
    except (OSError, ValueError, subprocess.TimeoutExpired):
        return None


def _blob_at(root, ref: str, path: str):
    return _git(root, "rev-parse", "--verify", "--quiet", "--end-of-options", f"{ref}:{path}")


def _show_bytes(root, ref: str, path: str):
    try:
        proc = subprocess.run(["git", "show", f"{ref}:{path}"], cwd=str(root), capture_output=True, timeout=60)
        return proc.stdout if proc.returncode == 0 else None
    except (OSError, ValueError, subprocess.TimeoutExpired):
        return None


def _hash_blob(data: bytes) -> str:
    return hashlib.sha1(b"blob " + str(len(data)).encode() + b"\0" + data).hexdigest()


def _no_duplicates(items):
    out = {}
    for key, value in items:
        if key in out:
            raise ValueError("duplicate approval key")
        out[key] = value
    return out


def _pr346_authority():
    import importlib
    import sys
    name = "r_live_lifecycle_content_authority"
    if name in sys.modules:
        return sys.modules[name]
    try:
        return importlib.import_module(name)
    except ModuleNotFoundError:
        return importlib.import_module(f"tests.{name}")


def expected_approval() -> dict:
    """Pinned record schema; no caller-supplied authorization or environment gate."""
    return {"schema": 1, "kind": "r-live-lifecycle-py310-exact-content-approval",
            "repository": "Finco-Protocol/FincoProtocol", "pull_request": 347, "issue": 348,
            "pr346_checkpoint": PR346_CHECKPOINT, "source_candidate": SOURCE_CANDIDATE,
            "predecessor_blobs": {path: before for path, (before, _after) in BLOBS.items()},
            "blobs": APPROVED_BLOBS,
            "Financial": {"approved": True, "reference": OWNER_APPROVAL_REFERENCE},
            "scope": "PR347-issue348-R-LIVE-python310-exact-content-governance-and-CI-closure-only",
            "runtime_activation_authorized": False, "workflow_deployment_authorized": False,
            "hosted_shadow_authorized": False, "image_publication_authorized": False,
            "phase4_activation_authorized": False, "merge_authorized": False}


def py310_violations(*, repo=None, ref: str = "HEAD") -> list[str]:
    """[] only when ``ref`` carries exactly the owner-accepted R-LIVE 3.10 successor on the exact historical chain."""
    root = Path(repo) if repo is not None else ROOT
    head = _git(root, "rev-parse", "--verify", "--end-of-options", f"{ref}^{{commit}}")
    if head is None:
        return ["RLIVE310_REF_UNAVAILABLE"]
    key = (str(root), head, OWNER_APPROVAL_SHA256, OWNER_APPROVAL_REFERENCE, tuple(sorted(BLOBS.items())),
           tuple(sorted(WIRING_BLOBS.items())), tuple(PR346_CHECKPOINT.items()), tuple(SOURCE_CANDIDATE.items()))
    bad = list(_CACHE[key]) if key in _CACHE else _committed_violations(root, head, key)
    # working-tree bytes of the checkout HEAD are re-checked on every call (committed facts are cached)
    if head == _git(root, "rev-parse", "--verify", "HEAD^{commit}"):
        for path, pin in APPROVED_BLOBS.items():
            file = root / path
            if file.is_symlink() or not file.is_file() or _hash_blob(file.read_bytes()) != pin:
                bad.append(f"RLIVE310_WORKING_BLOB_MISMATCH: {path}")
        raw = _show_bytes(root, head, APPROVAL_PATH)
        record = root / APPROVAL_PATH
        if raw is not None and (record.is_symlink() or not record.is_file() or record.read_bytes() != raw):
            bad.append("RLIVE310_WORKING_RECORD_MISMATCH")
    return bad


def _committed_violations(root: Path, head: str, key) -> list[str]:
    bad: list[str] = []
    try:
        # 1. authentic chain; PR #346 judged on its own bytes at its checkpoint
        for name, anchor in (("PR346_CHECKPOINT", PR346_CHECKPOINT), ("SOURCE_CANDIDATE", SOURCE_CANDIDATE)):
            if _git(root, "rev-parse", "--verify", anchor["head"] + "^{commit}") != anchor["head"] or \
                    _git(root, "rev-parse", "--verify", anchor["head"] + "^{tree}") != anchor["tree"]:
                bad.append(f"RLIVE310_CHECKPOINT_MISSING: {name}")
        if bad:
            _CACHE[key] = tuple(bad)
            return bad
        for older, newer in ((PR346_CHECKPOINT["head"], SOURCE_CANDIDATE["head"]), (SOURCE_CANDIDATE["head"], head)):
            if _git(root, "merge-base", "--is-ancestor", older, newer) is None:
                bad.append(f"RLIVE310_ANCESTRY_INVALID: {older[:12]} -> {newer[:12]}")
        authority = _pr346_authority()
        if not all(authority.reviewed_lifecycle_content_matches(path, repo=root, ref=PR346_CHECKPOINT["head"])
                   for path in BLOBS):
            bad.append("RLIVE310_HISTORICAL_PR346_INVALID")
        # 2. exact blobs
        for path, (before, after) in BLOBS.items():
            if _blob_at(root, PR346_CHECKPOINT["head"], path) != before:
                bad.append(f"RLIVE310_PREDECESSOR_BLOB_MISMATCH: {path}")
            if _blob_at(root, SOURCE_CANDIDATE["head"], path) != after:
                bad.append(f"RLIVE310_SOURCE_CANDIDATE_NOT_APPROVED_CONTENT: {path}")
            if _blob_at(root, head, path) != after:
                bad.append(f"RLIVE310_BLOB_MISMATCH: {path}")
        if _blob_at(root, SOURCE_CANDIDATE["head"], APPROVAL_PATH) is not None:
            bad.append("RLIVE310_APPROVAL_RECORD_IN_SOURCE_CANDIDATE")
        # 3. scope: exactly the one changed R-LIVE file
        changed = _git(root, "diff", "--name-only", "--no-renames", PR346_CHECKPOINT["head"], head, "--", SCOPE_PREFIX)
        if changed is None or set(changed.splitlines()) != set(SCOPE_CHANGED):
            bad.append(f"RLIVE310_SCOPE_INVALID: {sorted(set((changed or '').splitlines()) ^ set(SCOPE_CHANGED))}")
        # 4. PR #346 authority and record unchanged; adapter exact
        for path in HISTORICAL:
            historical = _blob_at(root, PR346_CHECKPOINT["head"], path)
            if historical is None or _blob_at(root, head, path) != historical:
                bad.append(f"RLIVE310_HISTORICAL_GUARD_CHANGED: {path}")
        for path, (before, after) in WIRING_BLOBS.items():
            if after is None or _blob_at(root, PR346_CHECKPOINT["head"], path) != before or _blob_at(root, head, path) != after:
                bad.append(f"RLIVE310_WIRING_NOT_EXACT: {path}")
        # 5. Financial Owner exact-content record
        raw = _show_bytes(root, head, APPROVAL_PATH)
        if OWNER_APPROVAL_SHA256 is None or OWNER_APPROVAL_REFERENCE is None or raw is None:
            bad.append("RLIVE310_OWNER_EXACT_CONTENT_DECISION_ABSENT")
        elif hashlib.sha256(raw).hexdigest() != OWNER_APPROVAL_SHA256:
            bad.append("RLIVE310_OWNER_RECORD_NOT_EXACT")
        elif json.loads(raw, object_pairs_hook=_no_duplicates) != expected_approval():
            bad.append("RLIVE310_OWNER_RECORD_SCHEMA_MISMATCH")
    except Exception as exc:                                    # noqa: BLE001 - fail closed
        bad.append(f"RLIVE310_FACTS_UNAVAILABLE: {exc!r}")
    _CACHE[key] = tuple(bad)
    return list(bad)


def py310_content_matches(path: str, *, repo=None, ref: str = "HEAD") -> bool:
    """True only for one of the two exact paths while the whole successor is recognised (either mutation revokes both)."""
    return path in APPROVED_BLOBS and py310_violations(repo=repo, ref=ref) == []


def historical_subject(*, repo=None, ref: str = "HEAD") -> str:
    """The ref the PR #346 contract is judged at: ``ref`` itself, or - only while ``ref`` is the recognised successor - its
    immutable PR #346 checkpoint. Never a relabelling: PR #346 stays judged on PR #346 bytes."""
    return PR346_CHECKPOINT["head"] if py310_violations(repo=repo, ref=ref) == [] else ref
