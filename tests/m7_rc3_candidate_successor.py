"""M7 RC-3 candidate successor - INERT, fail-closed, NOT WIRED into any guard (review proposal, not an approval).

``M7_RC3_CANDIDATE_AUTHORITIES`` is a literal exact path -> exact Git blob map of the eleven M7 protected files at the reviewed M7
source head. It is deliberately independent of ``docs/model_v2/M7_BESS_FINANCIAL_CANDIDATE_MANIFEST.json`` (the manifest is the candidate's
own declaration and is never evidence of acceptance) and it never touches the historical pin maps (WF07, F3.5, Developer Economics,
Revenue V3). It authorises nothing by itself: ``acceptance_violations`` returns the approval gate as OPEN unless a SEPARATE record,
``docs/rc3/M7_FINANCIAL_ACCEPTANCE.json``, exists that identifies an independent reviewer and the reviewed source head and repeats the
exact blobs. That record does not exist, so the owner gates stay closed. Producing it is the independent reviewer's decision.
"""
from __future__ import annotations

import json
import re
import subprocess
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
M7_REVIEWED_SOURCE_HEAD = "62424a8b777133631f4253d75848ba8c846f83e6"
RC2_CHECKPOINT = "6fc77de98bc0562fb51efdbf96e1803a29b5b148"
ACCEPTANCE_RECORD = "docs/rc3/M7_FINANCIAL_ACCEPTANCE.json"
MANIFEST = "docs/model_v2/M7_BESS_FINANCIAL_CANDIDATE_MANIFEST.json"

M7_RC3_CANDIDATE_AUTHORITIES = {
    "domain/bess/__init__.py": "1905167cfb38bebb69f5f8b24f4100adf2b71f3d",
    "domain/bess/contracts.py": "1143dced2b27e3b7ed16754ccd3a17f6982d9f98",
    "domain/bess/dispatch.py": "ff2a9d2be76c2b1be308c596c42e32fe4276a9bc",
    "domain/bess/settlement.py": "e10829563e359f1766c6d8f98542e43107dac0dd",
    "domain/bess/synthetic.py": "427ad4589f9726c07e7c3723c2ff7ceed68c38ae",
    "finco_core/inputs/bess_native.py": "57ee798dbe4742c1b36acbfbc1412c90b172d3a2",
    "financial_engine/bess.py": "a07873816d97240ae02af106cd31b2135ee63316",
    "financial_engine/adapters/project_inputs.py": "14bd759a9958515a7796626f93c1bd2233d69150",
    "financial_engine/orchestrator.py": "be7ac31c6c4fed43b5fd7ca49fe53bfd1cc54c03",
    "app/run_integrity/evidence.py": "89faa2c9c3d4dfddb7b8a8096888f3aa7cf83610",
    "app/run_integrity/checks.py": "25e4c3aeb25893694681b4f819c663d1e24ac3a1",
}
FROZEN_PREFIXES = ("financial_engine/", "finco_core/", "domain/")
# Reviewer identities that can never count as an independent reviewer of this candidate.
NOT_INDEPENDENT = re.compile(r"claude|anthropic|assistant|agent|bot|\bai\b|author|self", re.I)


def _git(*args: str) -> str:
    return subprocess.run(["git", *args], cwd=ROOT, capture_output=True, text=True, check=True).stdout.strip()


def collect(ref: str = "HEAD") -> dict:
    blobs = {}
    for path in M7_RC3_CANDIDATE_AUTHORITIES:
        try:
            blobs[path] = _git("rev-parse", f"{ref}:{path}")
        except subprocess.CalledProcessError:
            continue
    try:
        record = json.loads(_git("show", f"{ref}:{ACCEPTANCE_RECORD}"))
    except (subprocess.CalledProcessError, ValueError):
        record = None
    changed = _git("diff", "--name-only", RC2_CHECKPOINT, ref).splitlines()
    return {
        "blobs": blobs,
        "source_blobs": {p: _git("rev-parse", f"{M7_REVIEWED_SOURCE_HEAD}:{p}") for p in M7_RC3_CANDIDATE_AUTHORITIES},
        "source_head_ancestor": subprocess.run(["git", "merge-base", "--is-ancestor", M7_REVIEWED_SOURCE_HEAD, ref],
                                               cwd=ROOT).returncode == 0,
        "frozen_changes": sorted(p for p in changed if p.startswith(FROZEN_PREFIXES)),
        "record": record,
        "manifest_text": _git("show", f"{ref}:{MANIFEST}"),
    }


def content_violations(f) -> list[str]:
    """Exact-content check of the eleven blobs only. [] means the CONTENT is the reviewed candidate (not that it is accepted)."""
    try:
        bad = []
        if f["source_head_ancestor"] is not True:
            bad.append("the reviewed M7 source head is not an ancestor")
        for path, blob in M7_RC3_CANDIDATE_AUTHORITIES.items():
            if f["blobs"].get(path) != blob:
                bad.append(f"{path}: not the exact reviewed candidate blob")
            if f["source_blobs"].get(path) != blob:
                bad.append(f"{path}: the reviewed source head does not carry this blob")
        extra = set(f["blobs"]) - set(M7_RC3_CANDIDATE_AUTHORITIES)
        if extra:
            bad.append(f"substituted or extra protected files: {sorted(extra)}")
        # the candidate may change ONLY these frozen-namespace paths (no namespace-wide permission)
        unlisted = [p for p in f["frozen_changes"] if p not in M7_RC3_CANDIDATE_AUTHORITIES]
        if unlisted:
            bad.append(f"unlisted financial/core/domain changes: {unlisted}")
        missing = [p for p in M7_RC3_CANDIDATE_AUTHORITIES if p.startswith(FROZEN_PREFIXES) and p not in f["frozen_changes"]]
        if missing:
            bad.append(f"partial slice: reviewed protected files are not part of the change: {missing}")
        return bad
    except (KeyError, TypeError, AttributeError) as exc:
        return [f"facts incomplete or malformed: {exc!r}"]


def acceptance_violations(f) -> list[str]:
    """The approval gate. Empty ONLY with a valid, separate, independent acceptance record; otherwise it states what is missing."""
    problems = content_violations(f)
    try:
        record = f["record"]
        if record is None:
            return problems + ["APPROVAL_REQUIRED: no independent acceptance record exists"]
        if not isinstance(record, dict):
            return problems + ["acceptance record is malformed"]
        reviewer = record.get("independent_reviewer")
        if not isinstance(reviewer, str) or not reviewer.strip() or NOT_INDEPENDENT.search(reviewer):
            problems.append("acceptance record does not identify an independent human reviewer")
        if record.get("reviewed_source_head") != M7_REVIEWED_SOURCE_HEAD:
            problems.append("acceptance record names a different source head than the reviewed one")
        if record.get("accepted_blobs") != M7_RC3_CANDIDATE_AUTHORITIES:
            problems.append("acceptance record does not repeat the exact eleven blobs")
        if record.get("scope") != "CANDIDATE_CONTENT_ONLY" or record.get("activation_approved") is not False:
            problems.append("acceptance must be candidate-content only; production activation stays separate and closed")
        if record.get("derived_from_manifest") is not False:
            problems.append("acceptance must not be inferred from the candidate manifest")
        if not isinstance(record.get("decision_reference"), str) or not record["decision_reference"].strip():
            problems.append("acceptance record carries no decision reference")
        return problems
    except (KeyError, TypeError, AttributeError) as exc:
        return problems + [f"acceptance facts incomplete or malformed: {exc!r}"]


def current_acceptance_granted(ref: str = "HEAD") -> bool:
    """Fail closed. True only when content and a valid independent acceptance record both hold."""
    try:
        return not acceptance_violations(collect(ref))
    except Exception:  # noqa: BLE001 - any evidence failure is not an authorization
        return False
