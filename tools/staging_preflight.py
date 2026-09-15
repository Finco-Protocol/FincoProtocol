"""Fail-closed preflight checks for the FINCO Model corporate staging host.

This tool validates deployment identity and filesystem isolation before the
staging service is allowed to start. It intentionally never prints secret
values.
"""

from __future__ import annotations

import argparse
import os
import re
import stat
import subprocess
from pathlib import Path
from typing import Mapping

STAGING_ROOT = Path("/opt/finco_staging")
STAGING_PORT = "8100"
PRODUCTION_ROOT = Path("/opt/finco_protocol")
PLACEHOLDER_MARKERS = ("changeme", "replace_with", "example", "placeholder")
_SHA_RE = re.compile(r"^[0-9a-f]{40}$")


class StagingPreflightError(RuntimeError):
    """Raised when the corporate staging isolation contract is violated."""


def parse_env_file(path: Path) -> dict[str, str]:
    values: dict[str, str] = {}
    for raw_line in path.read_text(encoding="utf-8").splitlines():
        line = raw_line.strip()
        if not line or line.startswith("#"):
            continue
        if "=" not in line:
            raise StagingPreflightError(f"invalid environment line: {raw_line!r}")
        key, value = line.split("=", 1)
        key = key.strip()
        value = value.strip().strip('"').strip("'")
        if not key:
            raise StagingPreflightError("empty environment key")
        values[key] = value
    return values


def _is_placeholder(value: str) -> bool:
    lower = value.lower()
    return any(marker in lower for marker in PLACEHOLDER_MARKERS)


def _require_absolute_under(path_text: str, root: Path, field: str) -> Path:
    path = Path(path_text)
    if not path.is_absolute():
        raise StagingPreflightError(f"{field} must be an absolute path")
    resolved = path.resolve(strict=False)
    root_resolved = root.resolve(strict=False)
    try:
        resolved.relative_to(root_resolved)
    except ValueError as exc:
        raise StagingPreflightError(f"{field} must stay under {root_resolved}") from exc
    return resolved


def validate_staging_env(
    env: Mapping[str, str],
    *,
    repo_root: Path,
    repo_head: str,
    check_filesystem: bool = False,
    env_file: Path | None = None,
) -> None:
    required = {
        "FINCO_ENV",
        "FINCO_APP_MODE",
        "FINCO_SECRET_KEY",
        "FINCO_ADMIN_USER",
        "FINCO_ADMIN_PASSWORD",
        "FINCO_COOKIE_SECURE",
        "FINCO_DB_PATH",
        "FINCO_STORAGE_PATH",
        "FINCO_MAX_CONCURRENT_RUNS",
        "FINCO_DEMO_RESET_ALLOWED",
        "FINCO_STAGING_ROOT",
        "FINCO_STAGING_PORT",
        "FINCO_DEPLOY_SHA",
    }
    missing = sorted(required - set(env))
    if missing:
        raise StagingPreflightError("missing required staging keys: " + ", ".join(missing))

    if env["FINCO_ENV"] != "staging":
        raise StagingPreflightError("FINCO_ENV must be exactly 'staging'")
    if env["FINCO_APP_MODE"] != "pilot":
        raise StagingPreflightError("FINCO_APP_MODE must be exactly 'pilot'")
    if env["FINCO_COOKIE_SECURE"].lower() != "true":
        raise StagingPreflightError("FINCO_COOKIE_SECURE must be true")
    if env["FINCO_DEMO_RESET_ALLOWED"].lower() != "true":
        raise StagingPreflightError("FINCO_DEMO_RESET_ALLOWED must be true on corporate staging")

    root = Path(env["FINCO_STAGING_ROOT"])
    if root != STAGING_ROOT:
        raise StagingPreflightError(f"FINCO_STAGING_ROOT must be {STAGING_ROOT}")
    if env["FINCO_STAGING_PORT"] != STAGING_PORT:
        raise StagingPreflightError(f"FINCO_STAGING_PORT must be {STAGING_PORT}")

    secret = env["FINCO_SECRET_KEY"]
    password = env["FINCO_ADMIN_PASSWORD"]
    if len(secret) < 64 or _is_placeholder(secret):
        raise StagingPreflightError("FINCO_SECRET_KEY must be a non-placeholder staging secret >=64 chars")
    if len(password) < 16 or _is_placeholder(password):
        raise StagingPreflightError("FINCO_ADMIN_PASSWORD must be a non-placeholder value >=16 chars")

    deploy_sha = env["FINCO_DEPLOY_SHA"].lower()
    if not _SHA_RE.fullmatch(deploy_sha):
        raise StagingPreflightError("FINCO_DEPLOY_SHA must be an exact 40-character commit SHA")
    if deploy_sha != repo_head.lower():
        raise StagingPreflightError("checked-out git HEAD does not match FINCO_DEPLOY_SHA")

    db_path = _require_absolute_under(env["FINCO_DB_PATH"], STAGING_ROOT, "FINCO_DB_PATH")
    storage_path = _require_absolute_under(
        env["FINCO_STORAGE_PATH"], STAGING_ROOT, "FINCO_STORAGE_PATH"
    )
    if db_path == storage_path:
        raise StagingPreflightError("database path and storage path must be distinct")
    if str(db_path).startswith(str(PRODUCTION_ROOT)) or str(storage_path).startswith(
        str(PRODUCTION_ROOT)
    ):
        raise StagingPreflightError("staging paths must never use the production root")

    try:
        concurrent_runs = int(env["FINCO_MAX_CONCURRENT_RUNS"])
    except ValueError as exc:
        raise StagingPreflightError("FINCO_MAX_CONCURRENT_RUNS must be an integer") from exc
    if concurrent_runs < 1 or concurrent_runs > 8:
        raise StagingPreflightError("FINCO_MAX_CONCURRENT_RUNS must be between 1 and 8")

    if repo_root.resolve(strict=False) != STAGING_ROOT.resolve(strict=False):
        raise StagingPreflightError(f"repository must be deployed at {STAGING_ROOT}")

    if check_filesystem:
        if env_file is None:
            raise StagingPreflightError("env_file is required for filesystem checks")
        mode = stat.S_IMODE(env_file.stat().st_mode)
        if mode & 0o077:
            raise StagingPreflightError("staging env file must not be group/world accessible")
        for directory in (db_path.parent, storage_path):
            if not directory.exists() or not directory.is_dir():
                raise StagingPreflightError(f"required staging directory missing: {directory}")
            if not os.access(directory, os.W_OK):
                raise StagingPreflightError(f"required staging directory is not writable: {directory}")


def _git_head(repo_root: Path) -> str:
    result = subprocess.run(
        ["git", "-C", str(repo_root), "rev-parse", "HEAD"],
        check=True,
        capture_output=True,
        text=True,
    )
    return result.stdout.strip()


def main() -> int:
    parser = argparse.ArgumentParser(description="Validate FINCO corporate staging isolation")
    parser.add_argument("--env-file", required=True, type=Path)
    parser.add_argument("--repo-root", default=STAGING_ROOT, type=Path)
    parser.add_argument(
        "--skip-filesystem-checks",
        action="store_true",
        help="Validate contract values only; intended for CI/tests, not deployment",
    )
    args = parser.parse_args()

    try:
        env = parse_env_file(args.env_file)
        head = _git_head(args.repo_root)
        validate_staging_env(
            env,
            repo_root=args.repo_root,
            repo_head=head,
            check_filesystem=not args.skip_filesystem_checks,
            env_file=args.env_file,
        )
    except (OSError, subprocess.CalledProcessError, StagingPreflightError) as exc:
        print(f"P7_STAGING_PREFLIGHT_BLOCKED: {exc}")
        return 2

    print("P7_STAGING_PREFLIGHT_PASS")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
