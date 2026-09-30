"""Fail-closed preflight checks for FINCO corporate staging.

Preserves the existing P7/E5 staging isolation and Equity Fundamentals snapshot
contract while updating runtime variables to the PR #152 secure execution
contract and adding Yield Phase 1 gates. Secret values are never printed.

Exit codes:
  0 — all checks pass
  2 — blocked (misconfiguration / isolation violation)

Yield Phase 1 requires:
  FINCO_YIELD_ENABLED=1
  FINCO_YIELD_EXECUTION_ENABLED=0

The exact checked-out Git HEAD must equal FINCO_DEPLOY_SHA.
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
PLACEHOLDER_MARKERS = (
    "changeme",
    "replace_with",
    "example",
    "placeholder",
    "finco model2026",
)
_SHA_RE = re.compile(r"^[0-9a-f]{40}$")
_BCRYPT_RE = re.compile(r"^\$2[aby]\$\d{2}\$[./A-Za-z0-9]{53}$")
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
    lower = value.strip().lower()
    return any(marker in lower for marker in PLACEHOLDER_MARKERS)


def _require_absolute_under(path_text: str, root: Path, field: str) -> Path:
    path = Path(path_text)
    if not path.is_absolute():
        raise StagingPreflightError(f"{field} must be an absolute path")
    resolved = path.resolve(strict=False)
    root_resolved = root.resolve(strict=False)
    production_resolved = PRODUCTION_ROOT.resolve(strict=False)
    try:
        resolved.relative_to(root_resolved)
    except ValueError as exc:
        raise StagingPreflightError(f"{field} must stay under {root_resolved}") from exc
    try:
        resolved.relative_to(production_resolved)
    except ValueError:
        pass
    else:
        raise StagingPreflightError(f"{field} must never use the production root")
    return resolved


def _required_int(env: Mapping[str, str], field: str, low: int, high: int) -> int:
    try:
        value = int(env[field])
    except (KeyError, ValueError) as exc:
        raise StagingPreflightError(f"{field} must be an integer") from exc
    if not low <= value <= high:
        raise StagingPreflightError(f"{field} must be between {low} and {high}")
    return value


def _validate_equity_fundamentals(
    env: Mapping[str, str],
    *,
    staging_root: Path = STAGING_ROOT,
    production_root: Path = PRODUCTION_ROOT,
    check_filesystem: bool = False,
) -> Path:
    """Preserve the E5 staging snapshot contract for Radar equity fundamentals."""
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
    except ValueError as exc:
        raise StagingPreflightError(
            f"FINCO_EQUITY_FUNDAMENTALS_DB_PATH: must be under {staging_resolved}; "
            "staging equity DB must be separate from production"
        ) from exc

    try:
        resolved.relative_to(production_resolved)
    except ValueError:
        pass
    else:
        raise StagingPreflightError(
            f"FINCO_EQUITY_FUNDAMENTALS_DB_PATH: must not be under the "
            f"production root {production_resolved}"
        )

    raw_mode = env.get("FINCO_EQUITY_FUNDAMENTALS_DB_MODE", "").strip()
    if not raw_mode:
        raise StagingPreflightError(
            f"FINCO_EQUITY_FUNDAMENTALS_DB_MODE: MISSING — must be "
            f"'{_E5_REQUIRED_MODE}' for E5 staging deployment"
        )
    mode = raw_mode.lower()
    if mode not in _EQUITY_VALID_MODES:
        raise StagingPreflightError(
            f"FINCO_EQUITY_FUNDAMENTALS_DB_MODE: invalid value {raw_mode!r}; "
            f"must be one of {sorted(_EQUITY_VALID_MODES)}"
        )
    if mode != _E5_REQUIRED_MODE:
        raise StagingPreflightError(
            f"FINCO_EQUITY_FUNDAMENTALS_DB_MODE: E5 staging requires "
            f"'{_E5_REQUIRED_MODE}'"
        )

    if check_filesystem:
        if not resolved.exists():
            raise StagingPreflightError(
                "FINCO_EQUITY_FUNDAMENTALS_DB_PATH: file not found; transfer the "
                "versioned equity snapshot before starting staging"
            )
        if not resolved.is_file():
            raise StagingPreflightError(
                "FINCO_EQUITY_FUNDAMENTALS_DB_PATH: configured path is not a regular file"
            )
        if not os.access(str(resolved), os.R_OK):
            raise StagingPreflightError(
                "FINCO_EQUITY_FUNDAMENTALS_DB_PATH: file is not readable by service user"
            )
    return resolved


def validate_staging_env(
    env: Mapping[str, str],
    *,
    repo_root: Path,
    repo_head: str,
    check_filesystem: bool = False,
    env_file: Path | None = None,
) -> None:
    """Validate current secure staging + E5 + Yield Phase 1 contracts."""
    required = {
        "FINCO_ENV",
        "FINCO_APP_MODE",
        "FINCO_STAGING_ROOT",
        "FINCO_STAGING_PORT",
        "FINCO_STAGING_HOST",
        "FINCO_DEPLOY_SHA",
        "FINCO_SECRET_KEY",
        "FINCO_CSRF_SECRET",
        "FINCO_ADMIN_USER",
        "FINCO_COOKIE_SECURE",
        "FINCO_COOKIE_SAMESITE",
        "FINCO_SESSION_HOURS",
        "FINCO_DEMO_RESET_ALLOWED",
        "FINCO_WEB_HOST",
        "FINCO_WEB_PORT",
        "FINCO_WEB_WORKERS",
        "FINCO_WEB_GRACEFUL_SHUTDOWN_SECONDS",
        "FINCO_MODEL_EXECUTION_CONCURRENCY",
        "FINCO_MODEL_EXECUTION_MODE",
        "FINCO_MODEL_EXECUTION_TIMEOUT_SECONDS",
        "FINCO_YIELD_ENABLED",
        "FINCO_YIELD_EXECUTION_ENABLED",
        "FINCO_DB_PATH",
        "FINCO_STORAGE_PATH",
        "FINCO_EQUITY_FUNDAMENTALS_DB_PATH",
        "FINCO_EQUITY_FUNDAMENTALS_DB_MODE",
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
    if env["FINCO_COOKIE_SAMESITE"].lower() not in {"lax", "strict"}:
        raise StagingPreflightError("FINCO_COOKIE_SAMESITE must be lax or strict")
    # Preserve the established corporate-staging demo-reset second factor.
    if env["FINCO_DEMO_RESET_ALLOWED"].lower() != "true":
        raise StagingPreflightError(
            "FINCO_DEMO_RESET_ALLOWED must be true on corporate staging"
        )

    if env["FINCO_STAGING_ROOT"] != str(STAGING_ROOT):
        raise StagingPreflightError(f"FINCO_STAGING_ROOT must be {STAGING_ROOT}")
    if env["FINCO_STAGING_PORT"] != STAGING_PORT:
        raise StagingPreflightError(f"FINCO_STAGING_PORT must be {STAGING_PORT}")
    if env["FINCO_STAGING_HOST"].lower() != STAGING_HOST:
        raise StagingPreflightError(f"FINCO_STAGING_HOST must be {STAGING_HOST}")
    if env["FINCO_WEB_HOST"] != "127.0.0.1":
        raise StagingPreflightError("FINCO_WEB_HOST must be loopback 127.0.0.1")
    if env["FINCO_WEB_PORT"] != STAGING_PORT:
        raise StagingPreflightError("FINCO_WEB_PORT must match FINCO_STAGING_PORT")

    if env["FINCO_YIELD_ENABLED"] != "1":
        raise StagingPreflightError("FINCO_YIELD_ENABLED must be 1 for Phase 1")
    if env["FINCO_YIELD_EXECUTION_ENABLED"] != "0":
        raise StagingPreflightError(
            "FINCO_YIELD_EXECUTION_ENABLED must be 0 for Phase 1"
        )

    admin_user = env["FINCO_ADMIN_USER"].strip()
    secret = env["FINCO_SECRET_KEY"].strip()
    csrf_secret = env["FINCO_CSRF_SECRET"].strip()
    if not admin_user or _is_placeholder(admin_user):
        raise StagingPreflightError(
            "FINCO_ADMIN_USER must be a non-placeholder staging account"
        )
    if len(secret) < 64 or _is_placeholder(secret):
        raise StagingPreflightError(
            "FINCO_SECRET_KEY must be a non-placeholder staging secret >=64 chars"
        )
    if len(csrf_secret) < 64 or _is_placeholder(csrf_secret):
        raise StagingPreflightError(
            "FINCO_CSRF_SECRET must be a non-placeholder staging secret >=64 chars"
        )

    plain = env.get("FINCO_ADMIN_PASSWORD", "").strip()
    password_hash = env.get("FINCO_ADMIN_PASSWORD_HASH", "").strip()
    if bool(plain) == bool(password_hash):
        raise StagingPreflightError(
            "configure exactly one of FINCO_ADMIN_PASSWORD or FINCO_ADMIN_PASSWORD_HASH"
        )
    if plain and (len(plain) < 16 or _is_placeholder(plain)):
        raise StagingPreflightError(
            "FINCO_ADMIN_PASSWORD must be a non-placeholder value >=16 chars"
        )
    if password_hash and not _BCRYPT_RE.fullmatch(password_hash):
        raise StagingPreflightError(
            "FINCO_ADMIN_PASSWORD_HASH must be a canonical bcrypt hash"
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

    _required_int(env, "FINCO_SESSION_HOURS", 1, 168)
    _required_int(env, "FINCO_WEB_WORKERS", 1, 8)
    _required_int(env, "FINCO_WEB_GRACEFUL_SHUTDOWN_SECONDS", 1, 300)
    _required_int(env, "FINCO_MODEL_EXECUTION_CONCURRENCY", 1, 8)
    _required_int(env, "FINCO_MODEL_EXECUTION_TIMEOUT_SECONDS", 1, 900)
    if env["FINCO_MODEL_EXECUTION_MODE"] != "process":
        raise StagingPreflightError(
            "FINCO_MODEL_EXECUTION_MODE must be process for corporate staging"
        )

    db_path = _require_absolute_under(
        env["FINCO_DB_PATH"], STAGING_ROOT, "FINCO_DB_PATH"
    )
    storage_path = _require_absolute_under(
        env["FINCO_STORAGE_PATH"], STAGING_ROOT, "FINCO_STORAGE_PATH"
    )
    if db_path == storage_path:
        raise StagingPreflightError("database path and storage path must be distinct")

    equity_path = _validate_equity_fundamentals(
        env,
        staging_root=STAGING_ROOT,
        production_root=PRODUCTION_ROOT,
        check_filesystem=check_filesystem,
    )
    if equity_path == db_path:
        raise StagingPreflightError(
            "FINCO_EQUITY_FUNDAMENTALS_DB_PATH must be distinct from FINCO_DB_PATH"
        )

    optional_paths: dict[str, Path] = {}
    for field in ("RADAR_BNB_INTELLIGENCE_DB_PATH", "FINCO_YIELD_HISTORY_PATH"):
        value = env.get(field, "").strip()
        if value:
            path = _require_absolute_under(value, STAGING_ROOT, field)
            optional_paths[field] = path
            if path in {db_path, equity_path}:
                raise StagingPreflightError(
                    f"{field} must be distinct from application/equity DB paths"
                )

    if repo_root.resolve(strict=False) != STAGING_ROOT.resolve(strict=False):
        raise StagingPreflightError(f"repository must be deployed at {STAGING_ROOT}")

    if check_filesystem:
        if env_file is None:
            raise StagingPreflightError("env_file is required for filesystem checks")
        mode = stat.S_IMODE(env_file.stat().st_mode)
        if mode & 0o077:
            raise StagingPreflightError(
                "staging env file must not be group/world accessible"
            )

        writable_dirs = {db_path.parent, storage_path}
        for path in optional_paths.values():
            writable_dirs.add(path.parent)
        for directory in sorted(writable_dirs, key=str):
            if not directory.exists() or not directory.is_dir():
                raise StagingPreflightError(
                    f"required staging directory missing: {directory}"
                )
            if not os.access(directory, os.W_OK):
                raise StagingPreflightError(
                    f"required staging directory is not writable: {directory}"
                )


def _git_head(repo_root: Path) -> str:
    result = subprocess.run(
        [str(GIT_BIN), "-C", str(repo_root), "rev-parse", "HEAD"],
        check=True,
        capture_output=True,
        text=True,
    )
    return result.stdout.strip()


def main() -> int:
    parser = argparse.ArgumentParser(
        description="Validate FINCO corporate staging (secure runtime + E5 + Yield Phase 1)"
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
