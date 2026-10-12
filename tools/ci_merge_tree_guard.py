"""Fail closed unless the PR HEAD and GitHub synthetic merge have identical Git trees.

Only equality of *content trees* allows avoiding redundant merge-result test execution.
A fresh normal main-to-branch merge and exact-head CI is required for unequal trees.
"""
from __future__ import annotations

import argparse
import re
import subprocess
import sys
from typing import Callable

from tools.ci_acceptance import EvidenceError, attest, write_json


def git(*args: str) -> str:
    return subprocess.check_output(["git", *args], text=True).strip()


def prove_merge_tree(expected: str, merge_sha: str = "", pr_number: str = "",
                     git_run: Callable[..., str] = git) -> dict:
    if not re.fullmatch(r"[0-9a-f]{40}", expected):
        raise EvidenceError("Invalid exact-head commit SHA")
    actual = git_run("rev-parse", "HEAD")
    if actual != expected:
        raise EvidenceError(f"Wrong tested HEAD: {actual}, expected {expected}")
    head_tree = git_run("rev-parse", "HEAD^{tree}")
    if not merge_sha and not pr_number:
        return {"head": expected, "tree": head_tree, "mode": "main-head",
                "merge_sha": None, "merge_tree": None, "equivalent": True}
    if not re.fullmatch(r"[0-9a-f]{40}", merge_sha) or not re.fullmatch(r"[1-9][0-9]*", pr_number):
        raise EvidenceError("PR merge SHA and PR number are both required")
    # Fetch the event-pinned synthetic merge ref (never assume local merge refs are current).
    git_run("fetch", "--no-tags", "origin", f"refs/pull/{pr_number}/merge")
    fetched = git_run("rev-parse", "FETCH_HEAD")
    if fetched != merge_sha:
        raise EvidenceError(f"Synthetic merge moved during verification: event={merge_sha}, fetched={fetched}")
    merge_tree = git_run("rev-parse", "FETCH_HEAD^{tree}")
    if merge_tree != head_tree:
        raise EvidenceError(
            f"DIFFERENT TREES: head={head_tree}, merge-result={merge_tree}. "
            "STOP: normal main synchronization and fresh exact-head CI are required."
        )
    return {"head": expected, "tree": head_tree, "mode": "identical-tree",
            "merge_sha": merge_sha, "merge_tree": merge_tree, "equivalent": True}


def main() -> int:
    p = argparse.ArgumentParser()
    p.add_argument("--expected", required=True)
    p.add_argument("--merge-sha", default="")
    p.add_argument("--pr-number", default="")
    p.add_argument("--output", required=True)
    args = p.parse_args()
    proof = prove_merge_tree(args.expected, args.merge_sha, args.pr_number)
    write_json(args.output, proof)
    return 0


if __name__ == "__main__":
    try:
        sys.exit(main())
    except (EvidenceError, subprocess.CalledProcessError, OSError) as exc:
        print(f"MERGE_TREE_GATE_FAILED: {exc}", file=sys.stderr)
        sys.exit(1)
