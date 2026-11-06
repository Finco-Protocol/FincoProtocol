"""Fail closed unless the PR HEAD and GitHub synthetic merge have identical Git trees.

Only equality of *content trees* allows avoiding redundant merge-result test execution.
A fresh normal main-to-branch merge and exact-head CI is required for unequal trees.
"""
from __future__ import annotations

import argparse
import json
import os
from pathlib import Path
import re
import subprocess
import sys
from typing import Callable

from tools.ci_acceptance import EvidenceError, attest, write_json


def git(*args: str) -> str:
    return subprocess.check_output(["git", *args], text=True).strip()


def _github_event():
    """Runner-provided context only; local/legacy callers never get a drift exception."""
    if os.environ.get("GITHUB_ACTIONS") != "true":
        return None
    try:
        return json.loads(Path(os.environ["GITHUB_EVENT_PATH"]).read_text())
    except (KeyError, OSError, ValueError) as exc:
        raise EvidenceError("Missing or invalid GitHub event context") from exc


def _authenticate_drift(expected, event_sha, fetched, number, tree, event, env, git_run):
    """Allow metadata-only regeneration, never a different PR/base/head/content/ref."""
    moved = f"Synthetic merge moved during verification: event={event_sha}, fetched={fetched}"
    if event is None:
        raise EvidenceError(moved + "; no authenticated event context")
    try:
        pr = event["pull_request"]
        base, base_ref = pr["base"]["sha"], pr["base"]["ref"]
        repository = event["repository"]["full_name"]
        if (env.get("GITHUB_ACTIONS") != "true" or env.get("GITHUB_EVENT_NAME") != "pull_request"
            or env.get("GITHUB_SHA") != event_sha or env.get("GITHUB_REF") != f"refs/pull/{number}/merge"
            or env.get("GITHUB_REPOSITORY") != repository or env.get("GITHUB_SERVER_URL") != "https://github.com"
            or event.get("action") not in ("opened", "reopened", "synchronize")
            or str(event["number"]) != number or str(pr["number"]) != number
            or pr["head"]["sha"] != expected or pr["merge_commit_sha"] != event_sha
            or pr["base"]["repo"]["full_name"] != repository
            or not re.fullmatch(r"[0-9a-f]{40}", base)
            or not re.fullmatch(r"[A-Za-z0-9_.-]+/[A-Za-z0-9_.-]+", repository)
            or not re.fullmatch(r"[A-Za-z0-9][A-Za-z0-9._/-]*", base_ref)):
            raise EvidenceError(moved + "; event identity does not match the invocation")
        git_run("check-ref-format", "refs/heads/" + base_ref)
        origin = git_run("remote", "get-url", "origin").removesuffix(".git")
        ssh_origin = "git" + chr(64) + "github.com:" + repository
        if origin not in ("https://github.com/" + repository, ssh_origin):
            raise EvidenceError("Event repository does not match origin")
        refs = {"refs/heads/" + base_ref: base, f"refs/pull/{number}/head": expected,
                f"refs/pull/{number}/merge": fetched}

        def snapshot():
            lines = git_run("ls-remote", "--exit-code", "origin", *refs).splitlines()
            entries = [line.split() for line in lines]
            if any(len(e) != 2 for e in entries) or len(entries) != len(refs):
                raise EvidenceError("Missing or ambiguous PR/base refs")
            current = {name: sha for sha, name in entries}
            if current != refs:
                raise EvidenceError("PR head, base or merge ref changed; fresh event required")
            return current

        before = snapshot()
        # Both immutable objects must be actual two-parent merges of this exact base/head.
        git_run("fetch", "--no-tags", "origin", event_sha)
        if git_run("rev-parse", "FETCH_HEAD") != event_sha:
            raise EvidenceError("Fetched event object does not match event SHA")
        for sha in (event_sha, fetched):
            if git_run("rev-list", "--parents", "-n", "1", sha).split() != [sha, base, expected]:
                raise EvidenceError("Synthetic merge parents do not match event base/head")
            if git_run("rev-parse", sha + "^{tree}") != tree:
                raise EvidenceError("DIFFERENT TREES: event/current merge and HEAD must be byte-identical")
        git_run("merge-base", "--is-ancestor", base, expected)
        after = snapshot()
        if git_run("rev-parse", "HEAD") != expected:
            raise EvidenceError("Tested HEAD changed during merge verification")
        return {"event_merge_sha": event_sha, "fetched_merge_sha": fetched, "base_sha": base,
                "head_sha": expected, "pr_number": number, "repository": repository,
                "refs_before": before, "refs_after": after, "reason": "authenticated-metadata-only-regeneration"}
    except (KeyError, TypeError, AttributeError) as exc:
        raise EvidenceError(moved + "; incomplete event identity") from exc


def prove_merge_tree(expected: str, merge_sha: str = "", pr_number: str = "",
                     git_run: Callable[..., str] = git, *, event: dict | None = None,
                     environment: dict | None = None) -> dict:
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
    drift = None
    if fetched != merge_sha:
        drift = _authenticate_drift(expected, merge_sha, fetched, pr_number, head_tree,
                                    event, environment or {}, git_run)
    merge_tree = git_run("rev-parse", fetched + "^{tree}") if drift else git_run("rev-parse", "FETCH_HEAD^{tree}")
    if merge_tree != head_tree:
        raise EvidenceError(
            f"DIFFERENT TREES: head={head_tree}, merge-result={merge_tree}. "
            "STOP: normal main synchronization and fresh exact-head CI are required."
        )
    proof = {"head": expected, "tree": head_tree, "mode": "identical-tree",
             "merge_sha": merge_sha, "merge_tree": merge_tree, "equivalent": True}
    if drift:
        proof["authenticated_drift"] = drift
    return proof


def main() -> int:
    p = argparse.ArgumentParser()
    p.add_argument("--expected", required=True)
    p.add_argument("--merge-sha", default="")
    p.add_argument("--pr-number", default="")
    p.add_argument("--output", required=True)
    args = p.parse_args()
    proof = prove_merge_tree(args.expected, args.merge_sha, args.pr_number,
                             event=_github_event(), environment=dict(os.environ))
    write_json(args.output, proof)
    return 0


if __name__ == "__main__":
    try:
        sys.exit(main())
    except (EvidenceError, subprocess.CalledProcessError, OSError) as exc:
        print(f"MERGE_TREE_GATE_FAILED: {exc}", file=sys.stderr)
        sys.exit(1)
