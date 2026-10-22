"""Exact-content successor for the conversation-approved PR #346 lifecycle pair.

The explicit Financial Owner statement is a conversation reference, not a
cryptographically signed GitHub attestation. This recognizes two approved blobs
for governance/CI closure only. Existing Radar/Model pins remain independent;
no namespace, deployment, hosted-run, activation or merge authority is granted.
"""
from __future__ import annotations

import hashlib
import json
import re
import subprocess
from pathlib import Path

APPROVED_LIFECYCLE_BLOBS = {'app/radar_rwa/r_live_snapshot_store.py': '4179c296c803f42040b2811dc70ef55a1cdfa1d0', 'app/radar_rwa/r_live_warming.py': '563c1a256886f7b26af21ac63e121216f908c840'}
ORIGINAL_REVIEWED_SOURCE = {'head': 'a0d243c7d9c88d16990da9115e00ed00e3ad8160', 'tree': '864382c8ac955c72ee6ccad15ee86be373de8edd'}
CORRECTED_PROTECTED_SOURCE = {'head': 'a385e67fb71acebe00b2fe6f2f23c3f248614a86', 'tree': '82f7f27d70285afcdab598c4e72f2770d808c2ec'}
APPROVAL_ORIGIN = {'kind': 'explicit-conversation-statement', 'reference': 'conversation:2026-10-22:PR346:Correction-D:section-1', 'request_sha256': 'e49043bc8e976becc2bbdae2291a1e33f35189f25b596bed3aa013a2aaefd0a4', 'github_signed_attestation': False}
APPROVAL_PATH = "docs/ci_v3/final/r-live-lifecycle-content-approval.json"
OWNER_APPROVAL_REFERENCE = 'conversation:2026-10-22:PR346:Correction-D:section-1'
OWNER_APPROVAL_SHA256 = '76ffdaaa0a78190e2c10fd3435b01afacd477a8ac4665041ff94899739cc3b60'


def _git(repo, *args):
    result = subprocess.run(["git", *args], cwd=repo, capture_output=True, timeout=5)
    if result.returncode:
        raise ValueError("unavailable Git authority")
    return result.stdout


def _pairs(items):
    result = {}
    for key, value in items:
        if key in result:
            raise ValueError("duplicate approval key")
        result[key] = value
    return result


def _blob(data):
    return hashlib.sha1(b"blob " + str(len(data)).encode() + b"\0" + data).hexdigest()


def expected_approval():
    """Pinned record schema; no caller-supplied authorization or environment gate."""
    return {"schema": 1, "kind": "r-live-lifecycle-exact-content-approval",
        "repository": "Finco-Protocol/FincoProtocol",
        "original_reviewed_source": ORIGINAL_REVIEWED_SOURCE,
        "corrected_protected_source": CORRECTED_PROTECTED_SOURCE,
        "blobs": APPROVED_LIFECYCLE_BLOBS,
        "Financial": {"approved": True, "reference": OWNER_APPROVAL_REFERENCE},
        "approval_origin": APPROVAL_ORIGIN,
        "scope": "PR346-exact-content-governance-and-CI-closure-only",
        "runtime_activation_authorized": False, "workflow_deployment_authorized": False,
        "hosted_shadow_authorized": False, "image_publication_authorized": False,
        "phase4_activation_authorized": False, "merge_authorized": False}


def reviewed_lifecycle_content_matches(path: str, *, repo: str | Path, ref="HEAD") -> bool:
    """Require the exact pair, immutable corrected-source anchor and owner record.

    Owner authority is the explicit statement recorded by the reviewed code pins,
    never a self-asserting JSON field. The source commit predates this governance
    record, avoiding circular provenance. Both anchors must exist with their exact
    trees and ancestry, and both source blobs must match at the corrected anchor
    AND tested commit. Current working source/record bytes must also be intact.
    """
    if path not in APPROVED_LIFECYCLE_BLOBS:
        return False
    try:
        head = _git(repo, "rev-parse", "--verify", "--end-of-options", f"{ref}^{{commit}}").decode().strip()
        if re.fullmatch("[0-9a-f]{40}", head) is None:
            return False
        for anchor in (ORIGINAL_REVIEWED_SOURCE, CORRECTED_PROTECTED_SOURCE):
            actual = _git(repo, "rev-parse", "--verify", anchor["head"] + "^{tree}").decode().strip()
            if actual != anchor["tree"]:
                return False
        _git(repo, "merge-base", "--is-ancestor", ORIGINAL_REVIEWED_SOURCE["head"],
             CORRECTED_PROTECTED_SOURCE["head"])
        _git(repo, "merge-base", "--is-ancestor", CORRECTED_PROTECTED_SOURCE["head"], head)
        raw = _git(repo, "show", f"{head}:{APPROVAL_PATH}")
        if hashlib.sha256(raw).hexdigest() != OWNER_APPROVAL_SHA256:
            return False
        if json.loads(raw, object_pairs_hook=_pairs) != expected_approval():
            return False
        current = _git(repo, "rev-parse", "--verify", "HEAD^{commit}").decode().strip()
        for name, pin in APPROVED_LIFECYCLE_BLOBS.items():
            for commit in (CORRECTED_PROTECTED_SOURCE["head"], head):
                entry = _git(repo, "ls-tree", commit, "--", name).decode().strip()
                if entry != f"100644 blob {pin}\t{name}":
                    return False
            if head == current:
                file = Path(repo) / name
                if file.is_symlink() or not file.is_file() or _blob(file.read_bytes()) != pin:
                    return False
        if head == current:
            record = Path(repo) / APPROVAL_PATH
            if record.is_symlink() or not record.is_file() or record.read_bytes() != raw:
                return False
        return True
    except (OSError, ValueError, TypeError, subprocess.TimeoutExpired):
        return False
