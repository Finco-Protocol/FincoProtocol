"""Staging preflight validator tests — E5 deployment contract correction.

Tests that the staging preflight fails closed when equity DB configuration
is absent, invalid, or points at wrong paths, and passes for correct staging
snapshot configuration.

T01  — FINCO_EQUITY_FUNDAMENTALS_DB_PATH missing → fails with MISSING
T02  — FINCO_EQUITY_FUNDAMENTALS_DB_MODE missing → fails with MISSING
T03  — equity DB path outside staging root → fails
T04  — equity DB path under production root → fails (belt-and-suspenders)
T05  — invalid mode value → fails with invalid
T06  — DB file missing when filesystem checks enabled → fails with not found
T07  — valid staging snapshot configuration passes (no-fs variant)
T08  — valid staging snapshot configuration passes (real file present)
T09  — relative path → fails (not absolute)
T10  — empty/whitespace path → treated as MISSING
T11  — mode 'live' → rejected for E5 staging (requires snapshot)
T12  — mode with surrounding whitespace → normalised, passes
T13  — FINCO_ENV=production → refused immediately (exit code 2)
T14  — equity DB path != FINCO_DB_PATH is valid (different databases)
T15  — readable file passes filesystem check
T16  — unreadable file fails filesystem check (skipped when running as root)
T17  — check_not_production: case-insensitive 'PRODUCTION' rejected
T18  — production refused before equity checks: only one failure returned
T19  — run_preflight exit via main() returns 1 on missing path
T20  — staging_preflight.py --no-fs passes without a real file
"""
from __future__ import annotations

import os
import subprocess
import sys
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parents[1]

from tools.staging_preflight import (  # noqa: E402
    PreflightFailure,
    check_equity_db_file,
    check_equity_db_mode,
    check_equity_db_path,
    check_not_production,
    run_preflight,
)

# Canonical test roots matching the real deployment topology
_STAGING = "/opt/finco_staging"
_PRODUCTION = "/opt/finco_protocol"
_VALID_PATH = f"{_STAGING}/storage/equity_fundamentals_20260922T191856Z.db"


def _env(**kwargs) -> dict[str, str]:
    """Minimal valid staging env with optional overrides."""
    base: dict[str, str] = {
        "FINCO_ENV": "staging",
        "FINCO_EQUITY_FUNDAMENTALS_DB_PATH": _VALID_PATH,
        "FINCO_EQUITY_FUNDAMENTALS_DB_MODE": "snapshot",
    }
    base.update(kwargs)
    return base


# ── T01: equity DB path missing ───────────────────────────────────────────────

def test_t01_equity_db_path_missing_raises():
    """T01: absent FINCO_EQUITY_FUNDAMENTALS_DB_PATH → PreflightFailure MISSING."""
    env = _env()
    del env["FINCO_EQUITY_FUNDAMENTALS_DB_PATH"]
    with pytest.raises(PreflightFailure, match="MISSING"):
        check_equity_db_path(env)


def test_t01b_equity_db_path_missing_in_run_preflight():
    env = _env()
    del env["FINCO_EQUITY_FUNDAMENTALS_DB_PATH"]
    failures = run_preflight(env, check_fs=False)
    assert failures, "expected at least one failure"
    assert any("MISSING" in f for f in failures)


# ── T02: equity DB mode missing ───────────────────────────────────────────────

def test_t02_equity_db_mode_missing_raises():
    """T02: absent FINCO_EQUITY_FUNDAMENTALS_DB_MODE → PreflightFailure MISSING."""
    env = _env()
    del env["FINCO_EQUITY_FUNDAMENTALS_DB_MODE"]
    with pytest.raises(PreflightFailure, match="MISSING"):
        check_equity_db_mode(env)


def test_t02b_mode_missing_in_run_preflight():
    env = _env()
    del env["FINCO_EQUITY_FUNDAMENTALS_DB_MODE"]
    failures = run_preflight(env, check_fs=False)
    assert failures
    assert any("MISSING" in f for f in failures)


# ── T03: path outside staging root ────────────────────────────────────────────

def test_t03_path_outside_staging_root():
    """T03: path not under /opt/finco_staging → fails."""
    env = _env(FINCO_EQUITY_FUNDAMENTALS_DB_PATH="/var/data/equity.db")
    with pytest.raises(PreflightFailure, match=_STAGING):
        check_equity_db_path(env, staging_root=_STAGING, production_root=_PRODUCTION)


def test_t03b_tmp_path_outside_staging_root():
    env = _env(FINCO_EQUITY_FUNDAMENTALS_DB_PATH="/tmp/equity_fundamentals.db")
    failures = run_preflight(env, check_fs=False, staging_root=_STAGING, production_root=_PRODUCTION)
    assert failures
    assert any(_STAGING in f for f in failures)


def test_t03c_production_path_fails_staging_check():
    """T03c: path under production root also fails the staging-root check."""
    prod_path = f"{_PRODUCTION}/data/equity_fundamentals.db"
    env = _env(FINCO_EQUITY_FUNDAMENTALS_DB_PATH=prod_path)
    failures = run_preflight(env, check_fs=False, staging_root=_STAGING, production_root=_PRODUCTION)
    assert failures


# ── T04: path under production root (belt-and-suspenders) ────────────────────

def test_t04_path_under_production_root_rejected():
    """T04: path under production root rejected even when staging root is broad."""
    prod_path = f"{_PRODUCTION}/equity.db"
    env = _env(FINCO_EQUITY_FUNDAMENTALS_DB_PATH=prod_path)
    # Use broad staging_root so the path passes the staging check — only the
    # production-root guard should fire here.
    with pytest.raises(PreflightFailure, match="production"):
        check_equity_db_path(
            env,
            staging_root="/opt",
            production_root=_PRODUCTION,
        )


def test_t04b_production_root_guard_message():
    """T04b: error message explicitly names the production root."""
    prod_path = f"{_PRODUCTION}/storage/equity.db"
    env = _env(FINCO_EQUITY_FUNDAMENTALS_DB_PATH=prod_path)
    try:
        check_equity_db_path(env, staging_root="/opt", production_root=_PRODUCTION)
        pytest.fail("expected PreflightFailure")
    except PreflightFailure as exc:
        assert _PRODUCTION in str(exc)


# ── T05: invalid mode value ───────────────────────────────────────────────────

def test_t05_mode_walmode_invalid():
    """T05: mode 'walmode' is not a valid value."""
    env = _env(FINCO_EQUITY_FUNDAMENTALS_DB_MODE="walmode")
    with pytest.raises(PreflightFailure, match="invalid"):
        check_equity_db_mode(env)


def test_t05b_mode_readonly_invalid():
    env = _env(FINCO_EQUITY_FUNDAMENTALS_DB_MODE="readonly")
    failures = run_preflight(env, check_fs=False)
    assert failures
    assert any("invalid" in f.lower() for f in failures)


def test_t05c_mode_empty_string_after_strip():
    env = _env(FINCO_EQUITY_FUNDAMENTALS_DB_MODE="   ")
    with pytest.raises(PreflightFailure, match="MISSING"):
        check_equity_db_mode(env)


# ── T06: DB file missing when fs checks enabled ───────────────────────────────

def test_t06_db_file_missing_raises(tmp_path):
    """T06: non-existent file → PreflightFailure 'not found'."""
    nonexistent = str(tmp_path / "equity_fundamentals.db")
    with pytest.raises(PreflightFailure, match="not found"):
        check_equity_db_file(nonexistent)


def test_t06b_missing_file_in_run_preflight(tmp_path):
    staging_root = str(tmp_path / "finco_staging")
    prod_root = str(tmp_path / "finco_protocol")
    db_path = str(tmp_path / "finco_staging" / "equity.db")
    env = _env(
        FINCO_EQUITY_FUNDAMENTALS_DB_PATH=db_path,
        FINCO_EQUITY_FUNDAMENTALS_DB_MODE="snapshot",
    )
    failures = run_preflight(
        env,
        check_fs=True,
        staging_root=staging_root,
        production_root=prod_root,
    )
    assert failures
    assert any("not found" in f.lower() for f in failures)


# ── T07: valid staging snapshot passes (no-fs) ────────────────────────────────

def test_t07_valid_snapshot_no_fs_passes():
    """T07: valid env with check_fs=False → no failures."""
    env = _env()
    failures = run_preflight(env, check_fs=False, staging_root=_STAGING, production_root=_PRODUCTION)
    assert not failures, f"unexpected failures: {failures}"


# ── T08: valid staging snapshot passes (real file) ────────────────────────────

def test_t08_valid_snapshot_with_real_file(tmp_path):
    """T08: valid env with an existing readable file → no failures."""
    staging_root = str(tmp_path / "finco_staging")
    storage = tmp_path / "finco_staging" / "storage"
    storage.mkdir(parents=True)
    db_file = storage / "equity_fundamentals_20260922T191856Z.db"
    db_file.write_bytes(b"SQLite format 3\x00")

    env = _env(FINCO_EQUITY_FUNDAMENTALS_DB_PATH=str(db_file))
    failures = run_preflight(
        env,
        check_fs=True,
        staging_root=staging_root,
        production_root=str(tmp_path / "finco_protocol"),
    )
    assert not failures, f"unexpected failures: {failures}"


# ── T09: relative path fails ─────────────────────────────────────────────────

def test_t09_relative_path_not_accepted():
    """T09: relative path is rejected — must be absolute."""
    env = _env(FINCO_EQUITY_FUNDAMENTALS_DB_PATH="storage/equity.db")
    with pytest.raises(PreflightFailure, match="absolute"):
        check_equity_db_path(env, staging_root=_STAGING, production_root=_PRODUCTION)


# ── T10: empty/whitespace path → MISSING ──────────────────────────────────────

def test_t10_whitespace_only_path_treated_as_missing():
    """T10: value of only whitespace is treated as absent."""
    env = _env(FINCO_EQUITY_FUNDAMENTALS_DB_PATH="   ")
    with pytest.raises(PreflightFailure, match="MISSING"):
        check_equity_db_path(env)


def test_t10b_empty_string_path_treated_as_missing():
    env = _env(FINCO_EQUITY_FUNDAMENTALS_DB_PATH="")
    with pytest.raises(PreflightFailure, match="MISSING"):
        check_equity_db_path(env)


# ── T11: mode 'live' rejected for E5 ─────────────────────────────────────────

def test_t11_live_mode_rejected_for_e5():
    """T11: 'live' is a valid mode name but rejected for E5 staging (requires snapshot)."""
    env = _env(FINCO_EQUITY_FUNDAMENTALS_DB_MODE="live")
    with pytest.raises(PreflightFailure, match="snapshot"):
        check_equity_db_mode(env)


def test_t11b_live_mode_failure_message_explains_requirement():
    env = _env(FINCO_EQUITY_FUNDAMENTALS_DB_MODE="live")
    try:
        check_equity_db_mode(env)
        pytest.fail("expected PreflightFailure")
    except PreflightFailure as exc:
        assert "snapshot" in str(exc).lower()


# ── T12: mode whitespace normalised ──────────────────────────────────────────

def test_t12_mode_whitespace_stripped_and_accepted():
    """T12: '  snapshot  ' is accepted after stripping."""
    env = _env(FINCO_EQUITY_FUNDAMENTALS_DB_MODE="  snapshot  ")
    mode = check_equity_db_mode(env)
    assert mode == "snapshot"


def test_t12b_mode_uppercase_normalised():
    """T12b: 'SNAPSHOT' is normalised to 'snapshot' and accepted."""
    env = _env(FINCO_EQUITY_FUNDAMENTALS_DB_MODE="SNAPSHOT")
    mode = check_equity_db_mode(env)
    assert mode == "snapshot"


# ── T13: FINCO_ENV=production → refused ──────────────────────────────────────

def test_t13_production_env_raises():
    """T13: FINCO_ENV=production → PreflightFailure before any other checks."""
    env = _env(FINCO_ENV="production")
    with pytest.raises(PreflightFailure, match="production"):
        check_not_production(env)


def test_t13b_production_refused_in_run_preflight():
    env = _env(FINCO_ENV="production")
    failures = run_preflight(env, check_fs=False)
    assert failures
    assert any("production" in f.lower() for f in failures)


def test_t13c_production_refused_exit_code_2():
    """T13c: staging_preflight.py main() exits 2 when FINCO_ENV=production."""
    env_copy = os.environ.copy()
    env_copy["FINCO_ENV"] = "production"
    result = subprocess.run(
        [sys.executable, "tools/staging_preflight.py"],
        capture_output=True,
        text=True,
        env=env_copy,
        cwd=str(REPO_ROOT),
        timeout=30,
    )
    assert result.returncode == 2


# ── T14: equity DB != main DB is valid ───────────────────────────────────────

def test_t14_equity_db_different_from_main_db_passes():
    """T14: equity DB path distinct from FINCO_DB_PATH is correct and passes."""
    main_db = f"{_STAGING}/storage/finco_staging.db"
    equity_db = _VALID_PATH
    assert main_db != equity_db
    env = _env(
        FINCO_DB_PATH=main_db,
        FINCO_EQUITY_FUNDAMENTALS_DB_PATH=equity_db,
    )
    failures = run_preflight(env, check_fs=False, staging_root=_STAGING, production_root=_PRODUCTION)
    assert not failures, f"different DB paths should both pass: {failures}"


# ── T15: readable file passes fs check ───────────────────────────────────────

def test_t15_readable_file_passes_fs_check(tmp_path):
    """T15: existing, readable file passes check_equity_db_file."""
    db = tmp_path / "equity.db"
    db.write_bytes(b"SQLite format 3\x00")
    check_equity_db_file(str(db))  # must not raise


# ── T16: unreadable file fails fs check ──────────────────────────────────────

@pytest.mark.skipif(os.getuid() == 0, reason="root can read any file")
def test_t16_unreadable_file_fails_fs_check(tmp_path):
    """T16: file with mode 000 → PreflightFailure 'readable'."""
    db = tmp_path / "equity_noperm.db"
    db.write_bytes(b"SQLite")
    db.chmod(0o000)
    try:
        with pytest.raises(PreflightFailure, match="readable"):
            check_equity_db_file(str(db))
    finally:
        db.chmod(0o644)


# ── T17: case-insensitive production refusal ──────────────────────────────────

def test_t17_production_check_case_insensitive():
    """T17: FINCO_ENV='PRODUCTION' and 'Production' both refused."""
    for value in ("PRODUCTION", "Production", "pRoDuCtIoN"):
        env = _env(FINCO_ENV=value)
        with pytest.raises(PreflightFailure, match="production"):
            check_not_production(env)


# ── T18: production refusal short-circuits other checks ──────────────────────

def test_t18_production_refused_yields_exactly_one_failure():
    """T18: production refusal fires before equity checks — only one failure."""
    env = _env(
        FINCO_ENV="production",
        FINCO_EQUITY_FUNDAMENTALS_DB_PATH="",  # also broken — but not reached
        FINCO_EQUITY_FUNDAMENTALS_DB_MODE="bad",
    )
    failures = run_preflight(env, check_fs=False)
    assert len(failures) == 1
    assert "production" in failures[0].lower()


# ── T19: main() exits 1 on missing path ──────────────────────────────────────

def test_t19_main_exits_1_on_missing_path():
    """T19: main() returns 1 when equity DB path is not set."""
    env_copy = {k: v for k, v in os.environ.items() if "EQUITY" not in k}
    env_copy["FINCO_ENV"] = "staging"
    env_copy.pop("FINCO_EQUITY_FUNDAMENTALS_DB_PATH", None)
    result = subprocess.run(
        [sys.executable, "tools/staging_preflight.py", "--no-fs"],
        capture_output=True,
        text=True,
        env=env_copy,
        cwd=str(REPO_ROOT),
        timeout=30,
    )
    assert result.returncode == 1
    assert "MISSING" in result.stderr or "FAIL" in result.stderr


# ── T20: --no-fs passes with valid env but no real file ──────────────────────

def test_t20_no_fs_flag_passes_without_real_file():
    """T20: --no-fs skips filesystem access; valid env passes without a real file."""
    env_copy = os.environ.copy()
    env_copy["FINCO_ENV"] = "staging"
    env_copy["FINCO_EQUITY_FUNDAMENTALS_DB_PATH"] = _VALID_PATH
    env_copy["FINCO_EQUITY_FUNDAMENTALS_DB_MODE"] = "snapshot"
    result = subprocess.run(
        [sys.executable, "tools/staging_preflight.py", "--no-fs"],
        capture_output=True,
        text=True,
        env=env_copy,
        cwd=str(REPO_ROOT),
        timeout=30,
    )
    assert result.returncode == 0, f"stderr: {result.stderr}"
    assert "STAGING_PREFLIGHT_PASS" in result.stdout
    assert "CONFIGURED" in result.stdout
