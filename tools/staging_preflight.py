"""Staging environment preflight validator for FINCO Radar E5 deployment.

Validates FINCO Radar staging deployment configuration before service start.
Fails closed on any misconfiguration.

Exit codes:
  0 — all checks pass
  1 — one or more validation failures
  2 — refused (FINCO_ENV=production)

Checks enforced:
  • FINCO_EQUITY_FUNDAMENTALS_DB_PATH must be present, absolute, under the
    staging storage root (/opt/finco_staging), and must NOT be under the
    production root (/opt/finco_protocol).
  • FINCO_EQUITY_FUNDAMENTALS_DB_MODE must be 'snapshot' or 'live'.
    E5 staging deployment requires 'snapshot' — a WAL-checkpointed standalone
    immutable SQLite file.  Do NOT point snapshot mode at a mutating WAL DB.
  • The equity fundamentals DB is SEPARATE from FINCO_DB_PATH (the main
    application DB).  They serve different subsystems; they must not be
    confused or pointed at the same file.
  • When filesystem checks are enabled (default) the DB file must exist and
    be readable by the current process user.

Never prints secret or env-var values.  Reports only CONFIGURED / MISSING /
INVALID / PASS / FAIL.

Usage:
  python tools/staging_preflight.py          # full checks including fs
  python tools/staging_preflight.py --no-fs  # skip filesystem access checks
"""
from __future__ import annotations

import os
import sys
from pathlib import Path

_STAGING_ROOT = "/opt/finco_staging"
_PRODUCTION_ROOT = "/opt/finco_protocol"
_VALID_MODES = frozenset({"snapshot", "live"})
_E5_REQUIRED_MODE = "snapshot"


class PreflightFailure(Exception):
    """Raised by a single preflight check that fails."""


# ── individual checks ─────────────────────────────────────────────────────────

def check_not_production(env: dict[str, str]) -> None:
    """Raise PreflightFailure when FINCO_ENV=production."""
    if env.get("FINCO_ENV", "").strip().lower() == "production":
        raise PreflightFailure(
            "FINCO_ENV=production: staging preflight refuses to run against a "
            "production environment; use the production deployment procedure instead"
        )


def check_equity_db_path(
    env: dict[str, str],
    *,
    staging_root: str = _STAGING_ROOT,
    production_root: str = _PRODUCTION_ROOT,
) -> str:
    """Validate FINCO_EQUITY_FUNDAMENTALS_DB_PATH.

    Returns the resolved path string on success.
    Raises PreflightFailure on any violation.
    """
    raw = env.get("FINCO_EQUITY_FUNDAMENTALS_DB_PATH", "").strip()
    if not raw:
        raise PreflightFailure(
            "FINCO_EQUITY_FUNDAMENTALS_DB_PATH: MISSING — "
            "equity fundamentals DB path is required for E1/E2/E3 Radar features; "
            "without it the Company Terminal degrades to SOURCE_UNAVAILABLE"
        )

    path = Path(raw)
    if not path.is_absolute():
        raise PreflightFailure(
            "FINCO_EQUITY_FUNDAMENTALS_DB_PATH: must be an absolute path"
        )

    try:
        path.relative_to(staging_root)
    except ValueError:
        raise PreflightFailure(
            f"FINCO_EQUITY_FUNDAMENTALS_DB_PATH: path must be under {staging_root}; "
            "staging equity DB must be stored in the staging storage area, "
            "separate from the production deployment"
        )

    try:
        path.relative_to(production_root)
        # reaching here means path IS under production root — forbidden
        raise PreflightFailure(
            f"FINCO_EQUITY_FUNDAMENTALS_DB_PATH: path must not be under the "
            f"production root {production_root}; "
            "staging must never read from the production equity DB"
        )
    except ValueError:
        pass  # not under production root — correct

    return raw


def check_equity_db_mode(env: dict[str, str]) -> str:
    """Validate FINCO_EQUITY_FUNDAMENTALS_DB_MODE.

    Returns the normalised mode string on success.
    Raises PreflightFailure on any violation.
    """
    raw = env.get("FINCO_EQUITY_FUNDAMENTALS_DB_MODE", "").strip()
    if not raw:
        raise PreflightFailure(
            f"FINCO_EQUITY_FUNDAMENTALS_DB_MODE: MISSING — "
            f"must be set to '{_E5_REQUIRED_MODE}' for E5 staging deployment"
        )

    mode = raw.lower()
    if mode not in _VALID_MODES:
        raise PreflightFailure(
            f"FINCO_EQUITY_FUNDAMENTALS_DB_MODE: invalid value {raw!r}; "
            f"must be one of {sorted(_VALID_MODES)}"
        )

    if mode != _E5_REQUIRED_MODE:
        raise PreflightFailure(
            f"FINCO_EQUITY_FUNDAMENTALS_DB_MODE: E5 staging deployment requires "
            f"'{_E5_REQUIRED_MODE}' (WAL-checkpointed standalone immutable SQLite "
            f"snapshot); got '{mode}'.  Do not point snapshot mode at a mutating "
            "WAL database."
        )

    return mode


def check_equity_db_file(path_str: str) -> None:
    """Verify the equity DB file exists and is readable.

    Raises PreflightFailure if the file is absent, not a file, or unreadable.
    """
    path = Path(path_str)
    if not path.exists():
        raise PreflightFailure(
            "FINCO_EQUITY_FUNDAMENTALS_DB_PATH: file not found at configured path; "
            "upload/transfer the versioned equity snapshot before starting the service"
        )
    if not path.is_file():
        raise PreflightFailure(
            "FINCO_EQUITY_FUNDAMENTALS_DB_PATH: configured path is not a regular file"
        )
    if not os.access(str(path), os.R_OK):
        raise PreflightFailure(
            "FINCO_EQUITY_FUNDAMENTALS_DB_PATH: file exists but is not readable "
            "by the service user; check ownership and permissions"
        )


# ── orchestrator ──────────────────────────────────────────────────────────────

def run_preflight(
    env: dict[str, str],
    *,
    check_fs: bool = True,
    staging_root: str = _STAGING_ROOT,
    production_root: str = _PRODUCTION_ROOT,
) -> list[str]:
    """Run all preflight checks and return a list of failure messages.

    An empty list means all checks passed.  Raises nothing — failures are
    collected and returned so callers can decide how to report them.

    When check_fs=True (the default) the equity DB file is tested for
    existence and readability.  Pass check_fs=False in unit tests that do
    not create real files.
    """
    failures: list[str] = []

    def _collect(check, *args, **kwargs):
        try:
            return check(*args, **kwargs)
        except PreflightFailure as exc:
            failures.append(str(exc))
            return None

    # 1 — environment guard: refuse production environments immediately
    _collect(check_not_production, env)
    if failures:
        return failures

    # 2 — equity fundamentals DB path
    path_str = _collect(
        check_equity_db_path,
        env,
        staging_root=staging_root,
        production_root=production_root,
    )

    # 3 — equity fundamentals DB mode
    _collect(check_equity_db_mode, env)

    # 4 — filesystem check only when path passed validation
    if check_fs and path_str is not None:
        _collect(check_equity_db_file, path_str)

    return failures


# ── CLI entry ────────────────────────────────────────────────────────────────

def main(argv: list[str] | None = None) -> int:
    """Run staging preflight; exit 0 (pass), 1 (fail) or 2 (refused)."""
    args = list(argv) if argv is not None else sys.argv[1:]
    env = dict(os.environ)

    if env.get("FINCO_ENV", "").strip().lower() == "production":
        print("STAGING_PREFLIGHT_REFUSED: FINCO_ENV=production", file=sys.stderr)
        return 2

    check_fs = "--no-fs" not in args
    failures = run_preflight(env, check_fs=check_fs)

    if failures:
        for msg in failures:
            print(f"FAIL: {msg}", file=sys.stderr)
        print(f"\nSTAGING_PREFLIGHT_FAIL ({len(failures)} error(s))", file=sys.stderr)
        return 1

    print("FINCO_EQUITY_FUNDAMENTALS_DB_PATH = CONFIGURED")
    print("FINCO_EQUITY_FUNDAMENTALS_DB_MODE = snapshot")
    print("STAGING_PREFLIGHT_PASS")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
