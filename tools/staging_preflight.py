"""Fail-closed preflight checks for the FINCO Model corporate staging host.

Validates deployment identity, filesystem isolation, and the E1/E2/E3 equity
fundamentals DB contract before the staging service is allowed to start.
Intentionally never prints secret values.

Exit codes:
  0 — all checks pass
  2 — blocked (any misconfiguration; refused production environment)

P7 base contract (validate_staging_env):
  FINCO_ENV, FINCO_APP_MODE, FINCO_SECRET_KEY, FINCO_ADMIN_USER,
  FINCO_ADMIN_PASSWORD, FINCO_COOKIE_SECURE, FINCO_DB_PATH,
  FINCO_STORAGE_PATH, FINCO_MAX_CONCURRENT_RUNS, FINCO_DEMO_RESET_ALLOWED,
  FINCO_STAGING_ROOT, FINCO_STAGING_PORT, FINCO_STAGING_HOST, FINCO_DEPLOY_SHA

Additive E5 equity contract (_validate_equity_fundamentals):
  FINCO_EQUITY_FUNDAMENTALS_DB_PATH  — absolute path under /opt/finco_staging,
    never under /opt/finco_protocol; validated with resolve(strict=False) so
    symlinks cannot escape the staging root.
  FINCO_EQUITY_FUNDAMENTALS_DB_MODE  — must be 'snapshot' for E5 staging.

Usage:
  python tools/staging_preflight.py --env-file /opt/finco_staging/.env.staging
  python tools/staging_preflight.py --env-file ... --repo-root /opt/finco_staging
  python tools/staging_preflight.py --env-file ... --skip-filesystem-checks
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
STAGING_HOST = "staging.finco.one"
PRODUCTION_ROOT = Path("/opt/finco_protocol")
GIT_BIN = Path("/usr/bin/git")
PLACEHOLDER_MARKERS = ("changeme", "replace_with", "example", "placeholder")
_SHA_RE = re.compile(r"^[0-9a-f]{40}$")
_EQUITY_VALID_MODES = frozenset({"snapshot", "live"})
_E5_REQUIRED_MODE = "snapshot"


class StagingPreflightError(RuntimeError):
    """Raised when the corporate staging isolation contract is violated."""


def parse_env_file(path: Path) -> dict[str, str]:
    values: dict[str, str] = {}
    for line_number, raw_line in enumerate(
        path.read_text(encoding="utf-8").splitlines(), start=1
    ):
        line = raw_line.strip()
        if not line or line.startswith("#"):
            continue
        if "=" not in line:
            raise StagingPreflightError(
                f"invalid environment syntax at line {line_number}"
            )
        key, value = line.split("=", 1)
        key = key.strip()
        value = value.strip().strip('"').strip("'")
        if not key:
            raise StagingPreflightError(
                f"empty environment key at line {line_number}"
            )
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


def _validate_equity_fundamentals(
    env: Mapping[str, str],
    *,
    staging_root: Path = STAGING_ROOT,
    production_root: Path = PRODUCTION_ROOT,
    check_filesystem: bool = False,
) -> None:
    """Additive equity fundamentals contract for E1/E2/E3 Radar features.

    Uses resolve(strict=False) so symlinks inside staging_root that resolve
    outside it are caught and rejected — lexical Path.relative_to alone would
    miss a symlink escape.
    """
    raw_path = env.get("FINCO_EQUITY_FUNDAMENTALS_DB_PATH", "").strip()
    if not raw_path:
        raise StagingPreflightError(
            "FINCO_EQUITY_FUNDAMENTALS_DB_PATH: MISSING — required for E1/E2/E3 "
            "Radar features; without it the Company Terminal degrades to "
            "SOURCE_UNAVAILABLE"
        )

    eq_path = Path(raw_path)
    if not eq_path.is_absolute():
        raise StagingPreflightError(
            "FINCO_EQUITY_FUNDAMENTALS_DB_PATH: must be an absolute path"
        )

    resolved = eq_path.resolve(strict=False)
    staging_resolved = staging_root.resolve(strict=False)
    production_resolved = production_root.resolve(strict=False)

    try:
        resolved.relative_to(staging_resolved)
    except ValueError:
        raise StagingPreflightError(
            f"FINCO_EQUITY_FUNDAMENTALS_DB_PATH: must be under {staging_resolved}; "
            "staging equity DB must be stored in the staging storage area, "
            "separate from the production deployment"
        )

    # resolved outside staging_root may still be under production_root
    try:
        resolved.relative_to(production_resolved)
        raise StagingPreflightError(
            f"FINCO_EQUITY_FUNDAMENTALS_DB_PATH: must not be under the "
            f"production root {production_resolved}; "
            "staging must never read from the production equity DB"
        )
    except ValueError:
        pass  # correct — not under production root

    raw_mode = env.get("FINCO_EQUITY_FUNDAMENTALS_DB_MODE", "").strip()
    if not raw_mode:
        raise StagingPreflightError(
            f"FINCO_EQUITY_FUNDAMENTALS_DB_MODE: MISSING — "
            f"must be '{_E5_REQUIRED_MODE}' for E5 staging deployment"
        )
    mode = raw_mode.lower()
    if mode not in _EQUITY_VALID_MODES:
        raise StagingPreflightError(
            f"FINCO_EQUITY_FUNDAMENTALS_DB_MODE: invalid value {raw_mode!r}; "
            f"must be one of {sorted(_EQUITY_VALID_MODES)}"
        )
    if mode != _E5_REQUIRED_MODE:
        raise StagingPreflightError(
            f"FINCO_EQUITY_FUNDAMENTALS_DB_MODE: E5 staging deployment requires "
            f"'{_E5_REQUIRED_MODE}' (WAL-checkpointed standalone immutable SQLite "
            f"snapshot); got '{mode}'"
        )

    if check_filesystem:
        db = Path(str(resolved))
        if not db.exists():
            raise StagingPreflightError(
                "FINCO_EQUITY_FUNDAMENTALS_DB_PATH: file not found at configured "
                "path; upload/transfer the versioned equity snapshot before "
                "starting the service"
            )
        if not db.is_file():
            raise StagingPreflightError(
                "FINCO_EQUITY_FUNDAMENTALS_DB_PATH: configured path is not a "
                "regular file"
            )
        if not os.access(str(db), os.R_OK):
            raise StagingPreflightError(
                "FINCO_EQUITY_FUNDAMENTALS_DB_PATH: file exists but is not "
                "readable by the service user; check ownership and permissions"
            )


def validate_staging_env(
    env: Mapping[str, str],
    *,
    repo_root: Path,
    repo_head: str,
    check_filesystem: bool = False,
    env_file: Path | None = None,
) -> None:
    """Validate the full staging environment contract (P7 base + E5 equity additive).

    Raises StagingPreflightError on the first violation found.
    """
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
        "FINCO_STAGING_HOST",
        "FINCO_DEPLOY_SHA",
    }
    missing = sorted(required - set(env))
    if missing:
        raise StagingPreflightError(
            "missing required staging keys: " + ", ".join(missing)
        )

    if env["FINCO_ENV"] != "staging":
        raise StagingPreflightError("FINCO_ENV must be exactly 'staging'")
    if env["FINCO_APP_MODE"] != "pilot":
        raise StagingPreflightError("FINCO_APP_MODE must be exactly 'pilot'")
    if env["FINCO_COOKIE_SECURE"].lower() != "true":
        raise StagingPreflightError("FINCO_COOKIE_SECURE must be true")
    if env["FINCO_DEMO_RESET_ALLOWED"].lower() != "true":
        raise StagingPreflightError(
            "FINCO_DEMO_RESET_ALLOWED must be true on corporate staging"
        )

    root = Path(env["FINCO_STAGING_ROOT"])
    if root != STAGING_ROOT:
        raise StagingPreflightError(f"FINCO_STAGING_ROOT must be {STAGING_ROOT}")
    if env["FINCO_STAGING_PORT"] != STAGING_PORT:
        raise StagingPreflightError(f"FINCO_STAGING_PORT must be {STAGING_PORT}")
    if env["FINCO_STAGING_HOST"].lower() != STAGING_HOST:
        raise StagingPreflightError(f"FINCO_STAGING_HOST must be {STAGING_HOST}")

    admin_user = env["FINCO_ADMIN_USER"].strip()
    secret = env["FINCO_SECRET_KEY"]
    password = env["FINCO_ADMIN_PASSWORD"]
    if not admin_user or _is_placeholder(admin_user):
        raise StagingPreflightError(
            "FINCO_ADMIN_USER must be a non-placeholder staging account"
        )
    if len(secret) < 64 or _is_placeholder(secret):
        raise StagingPreflightError(
            "FINCO_SECRET_KEY must be a non-placeholder staging secret >=64 chars"
        )
    if len(password) < 16 or _is_placeholder(password):
        raise StagingPreflightError(
            "FINCO_ADMIN_PASSWORD must be a non-placeholder value >=16 chars"
        )

    deploy_sha = env["FINCO_DEPLOY_SHA"].lower()
    if not _SHA_RE.fullmatch(deploy_sha):
        raise StagingPreflightError(
            "FINCO_DEPLOY_SHA must be an exact 40-character commit SHA"
        )
    if deploy_sha != repo_head.lower():
        raise StagingPreflightError(
            "checked-out git HEAD does not match FINCO_DEPLOY_SHA"
        )

    db_path = _require_absolute_under(
        env["FINCO_DB_PATH"], STAGING_ROOT, "FINCO_DB_PATH"
    )
    storage_path = _require_absolute_under(
        env["FINCO_STORAGE_PATH"], STAGING_ROOT, "FINCO_STORAGE_PATH"
    )
    if db_path == storage_path:
        raise StagingPreflightError("database path and storage path must be distinct")
    if str(db_path).startswith(str(PRODUCTION_ROOT)) or str(storage_path).startswith(
        str(PRODUCTION_ROOT)
    ):
        raise StagingPreflightError(
            "staging paths must never use the production root"
        )

    # Equity DB must be a different file from the main application DB.
    # Compare resolved paths so a symlink alias cannot bypass the check.
    equity_raw = env.get("FINCO_EQUITY_FUNDAMENTALS_DB_PATH", "").strip()
    if equity_raw:
        equity_resolved = Path(equity_raw).resolve(strict=False)
        if equity_resolved == db_path:
            raise StagingPreflightError(
                "FINCO_EQUITY_FUNDAMENTALS_DB_PATH must be distinct from "
                "FINCO_DB_PATH; the equity time-series DB and the main "
                "application DB are separate subsystems and must never share "
                "a file"
            )

    try:
        concurrent_runs = int(env["FINCO_MAX_CONCURRENT_RUNS"])
    except ValueError as exc:
        raise StagingPreflightError(
            "FINCO_MAX_CONCURRENT_RUNS must be an integer"
        ) from exc
    if concurrent_runs < 1 or concurrent_runs > 8:
        raise StagingPreflightError(
            "FINCO_MAX_CONCURRENT_RUNS must be between 1 and 8"
        )

    if repo_root.resolve(strict=False) != STAGING_ROOT.resolve(strict=False):
        raise StagingPreflightError(
            f"repository must be deployed at {STAGING_ROOT}"
        )

    if check_filesystem:
        if env_file is None:
            raise StagingPreflightError(
                "env_file is required for filesystem checks"
            )
        mode = stat.S_IMODE(env_file.stat().st_mode)
        if mode & 0o077:
            raise StagingPreflightError(
                "staging env file must not be group/world accessible"
            )
        for directory in (db_path.parent, storage_path):
            if not directory.exists() or not directory.is_dir():
                raise StagingPreflightError(
                    f"required staging directory missing: {directory}"
                )
            if not os.access(directory, os.W_OK):
                raise StagingPreflightError(
                    f"required staging directory is not writable: {directory}"
                )

    # Additive E5 equity fundamentals contract (E1/E2/E3 Radar features).
    # Pass module globals explicitly so monkeypatching in tests takes effect.
    _validate_equity_fundamentals(
        env,
        staging_root=STAGING_ROOT,
        production_root=PRODUCTION_ROOT,
        check_filesystem=check_filesystem,
    )


def _git_head(repo_root: Path) -> str:
    """Resolve the deployed revision via absolute git binary (PATH-independent).

    The systemd unit intentionally uses a minimal PATH containing only the
    staging virtualenv; this calls /usr/bin/git directly so that path is never
    required on PATH.
    """
    result = subprocess.run(
        [str(GIT_BIN), "-C", str(repo_root), "rev-parse", "HEAD"],
        check=True,
        capture_output=True,
        text=True,
    )
    return result.stdout.strip()


def main() -> int:
    parser = argparse.ArgumentParser(
        description="Validate FINCO corporate staging isolation (P7 + E5 equity)"
    )
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
