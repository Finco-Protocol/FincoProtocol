"""Authoritative pull-request history governance.

M-9 contract:
- the pull-request event's exact base/head SHAs are authoritative;
- missing commit/ancestry evidence fails closed instead of skipping;
- the exact PR base must be an ancestor of the exact PR head;
- frozen namespace policy is stream-specific, never a repository-global ban.

The workflow checking this module must provide full history (fetch-depth: 0).
The module itself still fails clearly when invoked from an insufficiently
shallow checkout so missing history can never become a false PASS.
"""
from __future__ import annotations

import argparse
from dataclasses import dataclass
import json
from pathlib import Path
import re
import subprocess
import sys
from typing import Sequence

_SHA = re.compile(r"[0-9a-f]{40}\Z")

RUNTIME_RADAR_STREAM = "opus/runtime-radar-hardening"
RUNTIME_RADAR_PROTECTED_PREFIXES = (
    "financial_engine/",
    "finco_core/",
    "app/model_validation/",
    "app/verified/",
)


class GovernanceEvidenceError(RuntimeError):
    """Required Git evidence is unavailable or incomplete."""


class GovernanceBehindBaseError(RuntimeError):
    """PR head does not contain the authoritative PR base."""


class GovernanceProtectedMutationError(RuntimeError):
    """Current stream modified a namespace it does not own."""


@dataclass(frozen=True)
class PullRequestIdentity:
    base_sha: str
    head_sha: str
    head_ref: str


@dataclass(frozen=True)
class GovernanceResult:
    base_sha: str
    head_sha: str
    checkout_sha: str
    merge_base_sha: str
    head_ref: str
    changed_paths: tuple[str, ...]
    protected_prefixes: tuple[str, ...]


def _validate_sha(value: str, label: str) -> str:
    normalized = value.strip().lower()
    if not _SHA.fullmatch(normalized):
        raise GovernanceEvidenceError(f"{label} must be an exact lowercase 40-character commit SHA")
    return normalized


def load_pr_identity(event_path: Path) -> PullRequestIdentity:
    """Resolve exact PR identity from GitHub's pull_request event payload."""
    try:
        payload = json.loads(event_path.read_text(encoding="utf-8"))
        pull_request = payload["pull_request"]
        base_sha = pull_request["base"]["sha"]
        head_sha = pull_request["head"]["sha"]
        head_ref = pull_request["head"]["ref"]
    except (OSError, json.JSONDecodeError, KeyError, TypeError) as exc:
        raise GovernanceEvidenceError("pull_request event identity is unavailable") from exc

    if not isinstance(base_sha, str) or not isinstance(head_sha, str) or not isinstance(head_ref, str):
        raise GovernanceEvidenceError("pull_request event identity has invalid types")
    if not head_ref.strip():
        raise GovernanceEvidenceError("pull_request head ref is empty")
    return PullRequestIdentity(
        base_sha=_validate_sha(base_sha, "PR base SHA"),
        head_sha=_validate_sha(head_sha, "PR head SHA"),
        head_ref=head_ref.strip(),
    )


def protected_prefixes_for_stream(head_ref: str) -> tuple[str, ...]:
    """Return only protections explicitly owned by a known correction stream."""
    if head_ref == RUNTIME_RADAR_STREAM:
        return RUNTIME_RADAR_PROTECTED_PREFIXES
    return ()


def protected_namespace_violations(
    changed_paths: Sequence[str], protected_prefixes: Sequence[str]
) -> tuple[str, ...]:
    return tuple(
        path
        for path in changed_paths
        if any(path.startswith(prefix) for prefix in protected_prefixes)
    )


def _git(repo_root: Path, *args: str) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        ["git", "-C", str(repo_root), *args],
        capture_output=True,
        text=True,
        check=False,
    )


def _require_commit(repo_root: Path, sha: str, label: str) -> None:
    result = _git(repo_root, "cat-file", "-e", f"{sha}^{{commit}}")
    if result.returncode != 0:
        raise GovernanceEvidenceError(
            f"{label} commit is unavailable; full ancestry is required"
        )


def _changed_paths(repo_root: Path, base_sha: str, head_sha: str) -> tuple[str, ...]:
    result = subprocess.run(
        ["git", "-C", str(repo_root), "diff", "--name-only", "-z", f"{base_sha}...{head_sha}", "--"],
        capture_output=True,
        check=False,
    )
    if result.returncode != 0:
        raise GovernanceEvidenceError("base-to-head diff could not be established from Git history")
    return tuple(
        raw.decode("utf-8")
        for raw in result.stdout.split(b"\0")
        if raw
    )


def verify_governance(
    *,
    repo_root: Path,
    identity: PullRequestIdentity,
) -> GovernanceResult:
    """Fail closed unless exact PR ancestry and stream policy are provable."""
    repo_root = repo_root.resolve()
    base_sha = _validate_sha(identity.base_sha, "PR base SHA")
    head_sha = _validate_sha(identity.head_sha, "PR head SHA")

    _require_commit(repo_root, base_sha, "PR base")
    _require_commit(repo_root, head_sha, "PR head")

    checkout = _git(repo_root, "rev-parse", "HEAD")
    if checkout.returncode != 0:
        raise GovernanceEvidenceError("checked-out HEAD cannot be resolved")
    checkout_sha = _validate_sha(checkout.stdout.strip(), "checked-out HEAD")
    if checkout_sha != head_sha:
        raise GovernanceEvidenceError(
            "checked-out revision is not the exact pull-request head"
        )

    merge_base = _git(repo_root, "merge-base", base_sha, head_sha)
    if merge_base.returncode != 0 or not merge_base.stdout.strip():
        raise GovernanceEvidenceError(
            "PR base/head ancestry cannot be established; full history is required"
        )
    merge_base_sha = _validate_sha(merge_base.stdout.strip(), "merge base SHA")
    if merge_base_sha != base_sha:
        raise GovernanceBehindBaseError(
            "pull-request head does not contain the authoritative pull-request base"
        )

    changed_paths = _changed_paths(repo_root, base_sha, head_sha)
    protected_prefixes = protected_prefixes_for_stream(identity.head_ref)
    violations = protected_namespace_violations(changed_paths, protected_prefixes)
    if violations:
        raise GovernanceProtectedMutationError(
            "stream protected namespace mutation: " + ", ".join(violations)
        )

    return GovernanceResult(
        base_sha=base_sha,
        head_sha=head_sha,
        checkout_sha=checkout_sha,
        merge_base_sha=merge_base_sha,
        head_ref=identity.head_ref,
        changed_paths=changed_paths,
        protected_prefixes=protected_prefixes,
    )


def _print_result(result: GovernanceResult) -> None:
    print(f"GOVERNANCE_PR_BASE_SHA={result.base_sha}")
    print(f"GOVERNANCE_PR_HEAD_SHA={result.head_sha}")
    print(f"GOVERNANCE_CHECKOUT_SHA={result.checkout_sha}")
    print(f"GOVERNANCE_MERGE_BASE_SHA={result.merge_base_sha}")
    print(f"GOVERNANCE_HEAD_REF={result.head_ref}")
    print(f"GOVERNANCE_CHANGED_PATH_COUNT={len(result.changed_paths)}")
    if result.protected_prefixes:
        print("GOVERNANCE_STREAM_POLICY=RUNTIME_RADAR_HARDENING")
        print("GOVERNANCE_PROTECTED_NAMESPACE=PASS")
    else:
        print("GOVERNANCE_STREAM_POLICY=NO_STREAM_SPECIFIC_FREEZE")
    print("GOVERNANCE_HISTORY_EVIDENCE=PASS")
    print("GOVERNANCE_REQUIRED_HISTORY_SKIPS=ZERO")


def main(argv: Sequence[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--event-path", type=Path, required=True)
    parser.add_argument("--repo-root", type=Path, default=Path("."))
    args = parser.parse_args(argv)

    try:
        identity = load_pr_identity(args.event_path)
        result = verify_governance(repo_root=args.repo_root, identity=identity)
    except GovernanceEvidenceError as exc:
        print(f"GOVERNANCE_HISTORY_EVIDENCE_MISSING: {exc}", file=sys.stderr)
        return 2
    except GovernanceBehindBaseError as exc:
        print(f"GOVERNANCE_BRANCH_BEHIND_BASE: {exc}", file=sys.stderr)
        return 3
    except GovernanceProtectedMutationError as exc:
        print(f"GOVERNANCE_PROTECTED_NAMESPACE_MUTATION: {exc}", file=sys.stderr)
        return 4

    _print_result(result)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
