"""PPA-01 financial candidate authority - exact-content RECOGNITION only. It is not an approval and not a release (RC-3 / Correction C2).

Three separate questions are kept apart and are never collapsed into one boolean:

``candidate_content_matches_exactly``   the integrated tree carries EXACTLY the three reviewed PPA-01 blobs, no other protected
                                        (financial_engine / finco_core / domain) path differs from the base, and the reviewed source head is
                                        an ancestor. This is a statement about bytes. It is what lets the cross-stream frozen-scope gates
                                        distinguish "the candidate" from "an unauthorized change".
``candidate_is_financially_approved``   a SEPARATE, committed, independent acceptance record exists and is valid
                                        (``docs/rc3/PPA01_FINANCIAL_ACCEPTANCE.json``). It does not exist: the answer is False. Producing it is
                                        the independent reviewer's and the financial owner's decision.
``candidate_is_released``               approval AND an explicit release authorization in that record. Unavailable while no record exists.

The historical pin maps (WF07, Revenue V2 advanced, Revenue V3, F3.5/Junior, Developer Economics, ...) and the M7 eleven-blob candidate are not
touched, extended or reinterpreted by this module: the PPA-01 paths overlap two of them, but each is judged against its own checkpoint.
Any changed byte in any of the three blobs, or any missing path, makes ``candidate_content_matches_exactly`` False.
"""
from __future__ import annotations

import json
import re
import subprocess
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent

# The reviewed source head of PR #293 (the PPA-01 candidate) and the exact protected blobs it carries.
PPA01_REVIEWED_SOURCE_HEAD = "153a00384b2e4658863a967eec2184b5c5417eb4"
PPA01_CANDIDATE_AUTHORITIES = {
    "domain/revenue/multistream_runtime.py": "b1896bdb156a53c8371286bb4198381d0c7904fe",
    "domain/revenue/revenue_config.py": "d62fc2c7d97986d2c0aed6c0ac9068759011e1ef",
    "finco_core/revenue/generation.py": "8e23a949e72acc6422a6c7cd46f034b31f81fdfb",
}
PROTECTED_PREFIXES = ("financial_engine/", "finco_core/", "domain/")
ACCEPTANCE_RECORD = "docs/rc3/PPA01_FINANCIAL_ACCEPTANCE.json"
# Reviewer identities that can never count as an independent reviewer of this candidate.
NOT_INDEPENDENT = re.compile(r"claude|anthropic|assistant|agent|bot|\bai\b|author|self", re.I)


def _git(root, *args: str):
    proc = subprocess.run(["git", *args], cwd=str(root), capture_output=True, text=True)
    return proc.stdout.strip() if proc.returncode == 0 else None


def blob(path: str, *, repo=None, ref: str = "HEAD"):
    return _git(repo or ROOT, "rev-parse", f"{ref}:{path}")


def candidate_blobs_match(*, repo=None, ref: str = "HEAD") -> bool:
    """Blob-level identity of ALL THREE paths (one or two of three is not the candidate). No diff or provenance judgement."""
    return all(blob(p, repo=repo, ref=ref) == b for p, b in PPA01_CANDIDATE_AUTHORITIES.items())


def collect(*, repo=None, ref: str = "HEAD", base_ref: str = "origin/main") -> dict:
    root = repo or ROOT
    base = _git(root, "merge-base", base_ref, ref)
    changed = _git(root, "diff", "--name-only", base, ref, "--", *PROTECTED_PREFIXES) if base else None
    source_blobs = {p: _git(root, "rev-parse", f"{PPA01_REVIEWED_SOURCE_HEAD}:{p}") for p in PPA01_CANDIDATE_AUTHORITIES}
    record_text = _git(root, "show", f"{ref}:{ACCEPTANCE_RECORD}")
    try:
        record = json.loads(record_text) if record_text is not None else None
    except ValueError:
        record = "malformed"
    return {
        "blobs": {p: blob(p, repo=root, ref=ref) for p in PPA01_CANDIDATE_AUTHORITIES},
        "source_blobs": source_blobs,
        "source_head_ancestor": subprocess.run(["git", "merge-base", "--is-ancestor", PPA01_REVIEWED_SOURCE_HEAD, ref],
                                               cwd=str(root), capture_output=True).returncode == 0,
        "protected_changes": sorted(changed.splitlines()) if changed is not None else None,
        "record": record,
    }


def content_violations(facts) -> list[str]:
    """Exact-content check of the three blobs ONLY. [] means the CONTENT is the reviewed candidate (not that it is accepted)."""
    try:
        bad = []
        if facts["source_head_ancestor"] is not True:
            bad.append("the reviewed PPA-01 source head is not an ancestor")
        for path, pin in PPA01_CANDIDATE_AUTHORITIES.items():
            if facts["blobs"].get(path) != pin:
                bad.append(f"{path}: not the exact reviewed candidate blob")
            if facts["source_blobs"].get(path) != pin:
                bad.append(f"{path}: the reviewed source head does not carry this blob")
        extra = set(facts["blobs"]) - set(PPA01_CANDIDATE_AUTHORITIES)
        if extra:
            bad.append(f"substituted or extra protected files: {sorted(extra)}")
        changes = facts["protected_changes"]
        if changes is None:
            bad.append("the protected-path diff against the base is unavailable")
        else:
            unlisted = [p for p in changes if p not in PPA01_CANDIDATE_AUTHORITIES]
            if unlisted:
                bad.append(f"unlisted financial/core/domain changes: {unlisted}")
            missing = [p for p in PPA01_CANDIDATE_AUTHORITIES if p not in changes]
            if missing:
                bad.append(f"partial slice: reviewed protected files are not part of the change: {missing}")
        return bad
    except (KeyError, TypeError, AttributeError) as exc:
        return [f"facts incomplete or malformed: {exc!r}"]


def acceptance_violations(facts) -> list[str]:
    """The approval gate. Empty ONLY with a valid, separate, independent acceptance record; otherwise it states what is missing."""
    problems = content_violations(facts)
    try:
        record = facts["record"]
        if record is None:
            return problems + ["FINANCIAL_OWNER_APPROVAL_REQUIRED: no independent acceptance record exists"]
        if not isinstance(record, dict):
            return problems + ["acceptance record is malformed"]
        reviewer, owner = record.get("independent_reviewer"), record.get("financial_owner")
        for label, who in (("independent reviewer", reviewer), ("financial owner", owner)):
            if not isinstance(who, str) or not who.strip() or NOT_INDEPENDENT.search(who):
                problems.append(f"acceptance record does not identify a human {label}")
        if record.get("reviewed_source_head") != PPA01_REVIEWED_SOURCE_HEAD:
            problems.append("acceptance record names a different source head than the reviewed one")
        if record.get("accepted_blobs") != PPA01_CANDIDATE_AUTHORITIES:
            problems.append("acceptance record does not repeat the exact three blobs")
        if record.get("scope") != "CANDIDATE_CONTENT_ONLY":
            problems.append("acceptance must be candidate-content only; release stays a separate explicit decision")
        if not isinstance(record.get("decision_reference"), str) or not record["decision_reference"].strip():
            problems.append("acceptance record carries no decision reference")
        return problems
    except (KeyError, TypeError, AttributeError) as exc:
        return problems + [f"acceptance facts incomplete or malformed: {exc!r}"]


def release_violations(facts) -> list[str]:
    """Release is approval PLUS an explicit release authorization in that same record. Approval alone never releases."""
    problems = acceptance_violations(facts)
    record = facts.get("record") if isinstance(facts, dict) else None
    if not problems and not (isinstance(record, dict) and record.get("release_authorized") is True):
        problems.append("RELEASE_NOT_AUTHORIZED: acceptance of the candidate content is not a release")
    return problems


def candidate_content_matches_exactly(*, repo=None, ref: str = "HEAD", base_ref: str = "origin/main") -> bool:
    return content_violations(collect(repo=repo, ref=ref, base_ref=base_ref)) == []


def candidate_is_financially_approved(*, repo=None, ref: str = "HEAD", base_ref: str = "origin/main") -> bool:
    return acceptance_violations(collect(repo=repo, ref=ref, base_ref=base_ref)) == []


def candidate_is_released(*, repo=None, ref: str = "HEAD", base_ref: str = "origin/main") -> bool:
    return release_violations(collect(repo=repo, ref=ref, base_ref=base_ref)) == []


def frozen_scope_exempt(path: str, *, repo=None, ref: str = "HEAD") -> bool:
    """Frozen-namespace exemption for the CURRENT-integration guards: only one of the three exact paths, and only while all three are exactly the
    reviewed candidate blobs (a modified, partial or substituted candidate exempts nothing). It is NOT a release and not an approval."""
    return path in PPA01_CANDIDATE_AUTHORITIES and candidate_blobs_match(repo=repo, ref=ref)
