"""Unapproved two-path successor proposal, deliberately NOT a release authority."""
from __future__ import annotations

import ast
import json
from pathlib import Path
import subprocess

BASE = "5996453b8d5bbfaa48bc06922fc6963cf94d2f84"
ROOT = Path(__file__).resolve().parents[1]
PROPOSAL = {
    "financial_engine/financing/project.py": "5d3e42863abddf0a75a05e6d7688aa76a6d41c50",
    "financial_engine/financing/speculative.py": "9d85dad49bd1014fa7d864fab6bd29649d214cd7",
}
RELEASE_APPROVED = False
FINANCIAL_OWNER_APPROVED = False
INDEPENDENT_CONTENT_ACCEPTED = False


def validate_facts(facts):
    if not isinstance(facts, dict):
        return False
    changes = facts.get("application_and_protected_changes")
    if not isinstance(changes, (tuple, list)) or len(changes) != len(PROPOSAL):
        return False
    return (facts.get("base") == BASE and facts.get("base_is_ancestor") is True
            and facts.get("immutable_rc7c_recognized") is True
            and facts.get("blobs") == PROPOSAL
            and set(changes) == set(PROPOSAL)
            and facts.get("historical_guards_unchanged") is True
            and facts.get("quarterly_activation") is False)


def collect_worktree():
    def git(*args):
        return subprocess.check_output(["git", "-C", str(ROOT), *args], text=True).strip()
    from tests.rc7c_candidate_successor import rc7c_recognized
    manifest = json.loads((ROOT / "docs/model_v2/V9P1_CANDIDATE_MANIFEST.json").read_text())
    if manifest["base"] != BASE or manifest["protected_files"] != {
        path: {"candidate": pin, "predecessor": (
            "2e18a6e7c8ddfd85929d9b1906f91dd8858d0044" if path.endswith("/project.py") else None)}
            for path, pin in PROPOSAL.items()}:
        return {}
    if any(manifest[k] is not False for k in (
            "financial_owner_approved", "independent_content_accepted", "release_approved",
            "quarterly_activation", "joint_solver_activation")):
        return {}
    prefixes = ("app", "financial_engine", "finco_core", "domain")
    changed = set(git("diff", "--name-only", "--no-renames", BASE, "--", *prefixes).splitlines())
    changed.update(git("ls-files", "--others", "--exclude-standard", "--", *prefixes).splitlines())
    source = (ROOT / "app/workbook/quarterly_frequency_config.py").read_text(encoding="utf-8")
    flags = [node.value.value for node in ast.walk(ast.parse(source))
             if isinstance(node, ast.Assign) and isinstance(node.value, ast.Constant)
             and any(isinstance(t, ast.Name) and t.id == "ACTIVATION_ENABLED" for t in node.targets)]
    blobs = {}
    for path in PROPOSAL:
        # Git's clean filters define the reviewed blob on both LF and CRLF
        # checkouts; raw Windows worktree bytes are a separate execution identity.
        blobs[path] = git("hash-object", "--path=" + path, path)
    changed_tests = git("diff", "--name-only", BASE, "--", "tests").splitlines()
    historical_changed = [path for path in changed_tests if subprocess.run(
        ["git", "-C", str(ROOT), "cat-file", "-e", f"{BASE}:{path}"],
        capture_output=True).returncode == 0]
    return {"base": BASE, "base_is_ancestor": subprocess.run(
        ["git", "-C", str(ROOT), "merge-base", "--is-ancestor", BASE, "HEAD"],
        capture_output=True).returncode == 0,
        "immutable_rc7c_recognized": rc7c_recognized(repo=ROOT, ref=BASE),
        "blobs": blobs, "application_and_protected_changes": sorted(changed),
        "historical_guards_unchanged": historical_changed == [],
        "quarterly_activation": False if flags == [False] else "UNVERIFIED"}
