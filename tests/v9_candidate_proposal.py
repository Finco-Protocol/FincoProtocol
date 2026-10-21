"""Exact V9 PROPOSAL-byte verification only. Never imported by historical authority guards.

This cannot approve, admit, activate or release financial code. Existing frozen
namespace checks deliberately remain unchanged and may reject this candidate.
"""
from __future__ import annotations

import ast
import json
from pathlib import Path
import subprocess

BASE = "5996453b8d5bbfaa48bc06922fc6963cf94d2f84"
PROTECTED = (
    "financial_engine/financing/project.py",
    "financial_engine/financing/v9_candidate.py",
    "financial_engine/financing/v9_numerics.py",
    "financial_engine/shareholder_waterfall/model.py",
)
APPLICATION = "app/services/production_financial_authority.py"
PATHS = (*PROTECTED, APPLICATION)
STATES = ("financial_owner_approved", "precision_approved", "failure_equivalence_proved",
          "release_approved", "production_activation")


def git(root, *args):
    try:
        result = subprocess.run(["git", *args], cwd=root, capture_output=True,
                                text=True, encoding="utf-8")
        return result.stdout.strip() if result.returncode == 0 else None
    except (OSError, UnicodeError):
        return None


def false_literals(source, names):
    try:
        tree = ast.parse(source)
    except (SyntaxError, TypeError):
        return False
    values = {}
    for node in tree.body:
        if isinstance(node, ast.Assign) and isinstance(node.value, ast.Constant):
            for target in node.targets:
                if isinstance(target, ast.Name):
                    values[target.id] = node.value.value
    return all(name in values and values[name] is False for name in names)


def collect(root, ref="HEAD"):
    base = git(root, "rev-parse", "--verify", BASE + "^{commit}")
    head = git(root, "rev-parse", "--verify", ref + "^{commit}")
    ancestry = subprocess.run(["git", "merge-base", "--is-ancestor", BASE, ref],
                              cwd=root, capture_output=True).returncode == 0
    changes = git(root, "diff", "--name-status", "--no-renames", "-z", BASE, ref)
    parts = changes.rstrip("\0").split("\0") if changes else []
    changed = dict(zip(parts[1::2], parts[::2], strict=True)) if changes is not None and len(parts) % 2 == 0 else None
    source = git(root, "show", ref + ":financial_engine/financing/v9_candidate.py")
    quarterly = git(root, "show", ref + ":app/workbook/quarterly_frequency_config.py")
    return {"base": base, "head": head, "ancestor": ancestry, "changes": changed,
            "blobs": {p: git(root, "rev-parse", "--verify", ref + ":" + p) for p in PATHS},
            "predecessors": {p: git(root, "rev-parse", "--verify", BASE + ":" + p) for p in PATHS},
            "closed": false_literals(source, ("ACTIVATION_ENABLED", "FINANCIAL_PRECISION_APPROVED",
                                              "INTERMEDIATE_FAILURE_EQUIVALENCE_PROVED")),
            "quarterly_closed": false_literals(quarterly, ("ACTIVATION_ENABLED",))}


def violations(manifest, facts):
    bad = []
    if manifest.get("base") != BASE or facts.get("base") != BASE or not facts.get("head"):
        bad.append("V9_PROVENANCE_MISSING_OR_CHANGED")
    if facts.get("ancestor") is not True:
        bad.append("V9_BASE_NOT_ANCESTOR")
    if any(manifest.get(name) is not False for name in STATES):
        bad.append("V9_NO_APPROVAL_OR_ACTIVATION_PERMITTED")
    entries = manifest.get("files", {})
    if set(entries) != set(PATHS):
        bad.append("V9_EXACT_PROPOSAL_SCOPE_REQUIRED")
    for path in PATHS:
        entry = entries.get(path, {})
        if entry.get("candidate") != facts.get("blobs", {}).get(path) or not entry.get("candidate"):
            bad.append("V9_CANDIDATE_BLOB_MISMATCH:" + path)
        if entry.get("predecessor") != facts.get("predecessors", {}).get(path):
            bad.append("V9_PREDECESSOR_BLOB_MISMATCH:" + path)
    changes = facts.get("changes")
    if changes is None:
        bad.append("V9_DIFF_UNAVAILABLE")
    else:
        protected = {p for p in changes if p.startswith(("financial_engine/", "finco_core/", "domain/"))}
        if protected != set(PROTECTED):
            bad.append("V9_UNEXPECTED_PROTECTED_DIFF")
        if {p for p in changes if p.startswith("app/")} != {APPLICATION}:
            bad.append("V9_UNEXPECTED_APPLICATION_DIFF")
        if any(p.startswith(".github/") or (p.startswith("tests/") and status != "A")
               for p, status in changes.items()):
            bad.append("V9_HISTORICAL_GOVERNANCE_OR_CI_MODIFIED")
    if facts.get("closed") is not True or facts.get("quarterly_closed") is not True:
        bad.append("V9_ACTIVATION_NOT_CLOSED")
    return bad


def repository_violations(root=None, ref="HEAD"):
    root = root or Path(__file__).resolve().parents[1]
    text = git(root, "show", ref + ":docs/model_v2/V9_CANDIDATE_BLOB_MANIFEST.json")
    try:
        manifest = json.loads(text)
    except (ValueError, TypeError):
        return ["V9_MANIFEST_MISSING_OR_INVALID"]
    return violations(manifest, collect(root, ref))
