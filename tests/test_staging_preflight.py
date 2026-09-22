"""Staging preflight tests — P7 base contract + E5 equity fundamentals additive.

Coverage:
  P7 regression tests (validate_staging_env base contract):
    - missing required key
    - FINCO_ENV != staging
    - non-pilot app mode
    - insecure cookie
    - placeholder secret / admin / password
    - deploy SHA format and mismatch
    - staging root / port / host identity
    - path outside staging root (lexical and traversal)
    - DB / storage must be distinct
    - concurrency bounds
    - repo root must equal staging root
    - filesystem checks: env file permissions, directory existence
    - parse_env_file malformed / empty-key (no secret leakage)
    - _git_head is PATH-independent

  E5 equity fundamentals additive contract:
    - path missing / relative / empty
    - path outside staging root
    - symlink escape (6 scenarios)
    - path under production root
    - mode missing / invalid / 'live' rejected
    - mode case normalisation
    - filesystem checks: missing, not-a-file, unreadable
    - valid snapshot no-fs passes
    - FINCO_ENV=production → P7_STAGING_PREFLIGHT_BLOCKED exit 2
    - staging env example passes parse; placeholder contract prevents it from
      passing validate (intentional — example must not be deployable as-is)
"""
from __future__ import annotations

import os
from pathlib import Path

import pytest

import tools.staging_preflight as staging_preflight
from tools.staging_preflight import (
    StagingPreflightError,
    _git_head,
    parse_env_file,
    validate_staging_env,
)

ROOT = Path(__file__).resolve().parents[1]
HEAD = "a" * 40


# ── helpers ───────────────────────────────────────────────────────────────────

def _env() -> dict[str, str]:
    """Minimal fully-valid staging environment (no filesystem access needed)."""
    return {
        "FINCO_ENV": "staging",
        "FINCO_APP_MODE": "pilot",
        "FINCO_SECRET_KEY": "s" * 128,
        "FINCO_ADMIN_USER": "staging_admin",
        "FINCO_ADMIN_PASSWORD": "strong-staging-password-123",
        "FINCO_COOKIE_SECURE": "true",
        "FINCO_DB_PATH": "/opt/finco_staging/storage/finco_staging.db",
        "FINCO_STORAGE_PATH": "/opt/finco_staging/storage/exports",
        "FINCO_MAX_CONCURRENT_RUNS": "3",
        "FINCO_DEMO_RESET_ALLOWED": "true",
        "FINCO_STAGING_ROOT": "/opt/finco_staging",
        "FINCO_STAGING_PORT": "8100",
        "FINCO_STAGING_HOST": "staging.finco.one",
        "FINCO_DEPLOY_SHA": HEAD,
        "FINCO_EQUITY_FUNDAMENTALS_DB_PATH": "/opt/finco_staging/storage/equity_fundamentals.db",
        "FINCO_EQUITY_FUNDAMENTALS_DB_MODE": "snapshot",
    }


def _validate(env: dict[str, str], *, repo_root: Path | None = None) -> None:
    validate_staging_env(
        env,
        repo_root=repo_root or Path("/opt/finco_staging"),
        repo_head=HEAD,
        check_filesystem=False,
    )


# ── P7 regression: base contract ─────────────────────────────────────────────

def test_valid_staging_contract_passes() -> None:
    _validate(_env())


def test_missing_required_key_is_rejected() -> None:
    env = _env()
    del env["FINCO_SECRET_KEY"]
    with pytest.raises(StagingPreflightError, match="missing required staging keys"):
        _validate(env)


def test_production_environment_is_rejected() -> None:
    env = _env()
    env["FINCO_ENV"] = "production"
    with pytest.raises(StagingPreflightError, match="FINCO_ENV"):
        _validate(env)


def test_non_pilot_app_mode_is_rejected() -> None:
    env = _env()
    env["FINCO_APP_MODE"] = "production"
    with pytest.raises(StagingPreflightError, match="FINCO_APP_MODE"):
        _validate(env)


def test_demo_reset_opt_in_must_be_true() -> None:
    env = _env()
    env["FINCO_DEMO_RESET_ALLOWED"] = "false"
    with pytest.raises(StagingPreflightError, match="FINCO_DEMO_RESET_ALLOWED"):
        _validate(env)


def test_production_root_db_is_rejected() -> None:
    env = _env()
    env["FINCO_DB_PATH"] = "/opt/finco_protocol/storage/finco.db"
    with pytest.raises(StagingPreflightError, match="FINCO_DB_PATH"):
        _validate(env)


def test_path_traversal_out_of_staging_root_is_rejected() -> None:
    env = _env()
    env["FINCO_DB_PATH"] = "/opt/finco_staging/../finco_protocol/finco.db"
    with pytest.raises(StagingPreflightError, match="FINCO_DB_PATH"):
        _validate(env)


def test_database_and_storage_paths_must_be_distinct() -> None:
    env = _env()
    env["FINCO_STORAGE_PATH"] = env["FINCO_DB_PATH"]
    with pytest.raises(StagingPreflightError, match="must be distinct"):
        _validate(env)


def test_insecure_cookie_is_rejected() -> None:
    env = _env()
    env["FINCO_COOKIE_SECURE"] = "false"
    with pytest.raises(StagingPreflightError, match="FINCO_COOKIE_SECURE"):
        _validate(env)


def test_placeholder_secret_is_rejected() -> None:
    env = _env()
    env["FINCO_SECRET_KEY"] = "changeme_" + "x" * 80
    with pytest.raises(StagingPreflightError, match="FINCO_SECRET_KEY"):
        _validate(env)


def test_blank_admin_user_is_rejected() -> None:
    env = _env()
    env["FINCO_ADMIN_USER"] = "   "
    with pytest.raises(StagingPreflightError, match="FINCO_ADMIN_USER"):
        _validate(env)


def test_placeholder_admin_user_is_rejected() -> None:
    env = _env()
    env["FINCO_ADMIN_USER"] = "placeholder_admin"
    with pytest.raises(StagingPreflightError, match="FINCO_ADMIN_USER"):
        _validate(env)


def test_weak_admin_password_is_rejected() -> None:
    env = _env()
    env["FINCO_ADMIN_PASSWORD"] = "short"
    with pytest.raises(StagingPreflightError, match="FINCO_ADMIN_PASSWORD"):
        _validate(env)


def test_production_hostname_is_rejected() -> None:
    env = _env()
    env["FINCO_STAGING_HOST"] = "app.finco.one"
    with pytest.raises(StagingPreflightError, match="FINCO_STAGING_HOST"):
        _validate(env)


def test_unpinned_deploy_sha_is_rejected() -> None:
    env = _env()
    env["FINCO_DEPLOY_SHA"] = "main"
    with pytest.raises(StagingPreflightError, match="FINCO_DEPLOY_SHA"):
        _validate(env)


def test_checked_out_sha_mismatch_is_rejected() -> None:
    env = _env()
    env["FINCO_DEPLOY_SHA"] = "b" * 40
    with pytest.raises(StagingPreflightError, match="git HEAD"):
        _validate(env)


def test_staging_port_cannot_fall_back_to_production_port() -> None:
    env = _env()
    env["FINCO_STAGING_PORT"] = "8000"
    with pytest.raises(StagingPreflightError, match="FINCO_STAGING_PORT"):
        _validate(env)


def test_staging_root_is_fixed_and_separate() -> None:
    env = _env()
    env["FINCO_STAGING_ROOT"] = "/opt/finco_protocol"
    with pytest.raises(StagingPreflightError, match="FINCO_STAGING_ROOT"):
        _validate(env)


def test_actual_repo_root_must_equal_staging_root() -> None:
    with pytest.raises(StagingPreflightError, match="repository must be deployed"):
        _validate(_env(), repo_root=Path("/tmp/finco_staging"))


@pytest.mark.parametrize("value", ["not-an-int", "0", "9"])
def test_concurrency_must_be_integer_within_bounds(value: str) -> None:
    env = _env()
    env["FINCO_MAX_CONCURRENT_RUNS"] = value
    with pytest.raises(StagingPreflightError, match="FINCO_MAX_CONCURRENT_RUNS"):
        _validate(env)


def test_git_head_is_independent_of_service_path(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    monkeypatch.setenv("PATH", str(tmp_path))
    head = _git_head(ROOT)
    assert len(head) == 40
    assert all(ch in "0123456789abcdef" for ch in head.lower())


def test_parse_env_malformed_line_does_not_echo_secret(tmp_path: Path) -> None:
    secret = "DO_NOT_ECHO_THIS_SECRET"
    env_file = tmp_path / ".env.staging"
    env_file.write_text(f"FINCO_SECRET_KEY: {secret}\n", encoding="utf-8")
    with pytest.raises(StagingPreflightError) as exc_info:
        parse_env_file(env_file)
    message = str(exc_info.value)
    assert "line 1" in message
    assert secret not in message


def test_parse_env_empty_key_reports_line_only(tmp_path: Path) -> None:
    secret = "DO_NOT_ECHO_THIS_VALUE"
    env_file = tmp_path / ".env.staging"
    env_file.write_text(f"={secret}\n", encoding="utf-8")
    with pytest.raises(StagingPreflightError) as exc_info:
        parse_env_file(env_file)
    message = str(exc_info.value)
    assert "line 1" in message
    assert secret not in message


def test_filesystem_checks_accept_secure_isolated_layout(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    staging_root = tmp_path / "finco_staging"
    storage_root = staging_root / "storage"
    exports = storage_root / "exports"
    exports.mkdir(parents=True)
    env_file = staging_root / ".env.staging"
    env_file.write_text("# secret values omitted in unit test\n", encoding="utf-8")
    env_file.chmod(0o600)
    equity_db = storage_root / "equity_fundamentals.db"
    equity_db.write_bytes(b"")
    equity_db.chmod(0o600)

    monkeypatch.setattr(staging_preflight, "STAGING_ROOT", staging_root)
    monkeypatch.setattr(staging_preflight, "PRODUCTION_ROOT", tmp_path / "finco_protocol")

    env = _env()
    env["FINCO_STAGING_ROOT"] = str(staging_root)
    env["FINCO_DB_PATH"] = str(storage_root / "finco_staging.db")
    env["FINCO_STORAGE_PATH"] = str(exports)
    env["FINCO_EQUITY_FUNDAMENTALS_DB_PATH"] = str(equity_db)

    validate_staging_env(
        env,
        repo_root=staging_root,
        repo_head=HEAD,
        check_filesystem=True,
        env_file=env_file,
    )


def test_filesystem_checks_reject_group_readable_env(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    staging_root = tmp_path / "finco_staging"
    storage_root = staging_root / "storage"
    exports = storage_root / "exports"
    exports.mkdir(parents=True)
    env_file = staging_root / ".env.staging"
    env_file.write_text("# unit test\n", encoding="utf-8")
    env_file.chmod(0o640)

    monkeypatch.setattr(staging_preflight, "STAGING_ROOT", staging_root)
    monkeypatch.setattr(staging_preflight, "PRODUCTION_ROOT", tmp_path / "finco_protocol")

    env = _env()
    env["FINCO_STAGING_ROOT"] = str(staging_root)
    env["FINCO_DB_PATH"] = str(storage_root / "finco_staging.db")
    env["FINCO_STORAGE_PATH"] = str(exports)
    env["FINCO_EQUITY_FUNDAMENTALS_DB_PATH"] = str(storage_root / "equity.db")

    with pytest.raises(StagingPreflightError, match="group/world accessible"):
        validate_staging_env(
            env,
            repo_root=staging_root,
            repo_head=HEAD,
            check_filesystem=True,
            env_file=env_file,
        )


def test_filesystem_checks_reject_missing_storage_directory(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    staging_root = tmp_path / "finco_staging"
    storage_root = staging_root / "storage"
    storage_root.mkdir(parents=True)
    missing_exports = storage_root / "exports"
    env_file = staging_root / ".env.staging"
    env_file.write_text("# unit test\n", encoding="utf-8")
    env_file.chmod(0o600)

    monkeypatch.setattr(staging_preflight, "STAGING_ROOT", staging_root)
    monkeypatch.setattr(staging_preflight, "PRODUCTION_ROOT", tmp_path / "finco_protocol")

    env = _env()
    env["FINCO_STAGING_ROOT"] = str(staging_root)
    env["FINCO_DB_PATH"] = str(storage_root / "finco_staging.db")
    env["FINCO_STORAGE_PATH"] = str(missing_exports)
    env["FINCO_EQUITY_FUNDAMENTALS_DB_PATH"] = str(storage_root / "equity.db")

    with pytest.raises(StagingPreflightError, match="required staging directory missing"):
        validate_staging_env(
            env,
            repo_root=staging_root,
            repo_head=HEAD,
            check_filesystem=True,
            env_file=env_file,
        )


def test_staging_env_example_declares_separate_operational_identity() -> None:
    path = ROOT / "deploy/staging.env.example"
    text = path.read_text(encoding="utf-8")
    assert "FINCO_ENV=staging" in text
    assert "FINCO_STAGING_ROOT=/opt/finco_staging" in text
    assert "FINCO_STAGING_PORT=8100" in text
    assert "FINCO_STAGING_HOST=staging.finco.one" in text
    assert "FINCO_DB_PATH=/opt/finco_staging/storage/finco_staging.db" in text

    example_env = parse_env_file(path)
    with pytest.raises(StagingPreflightError):
        validate_staging_env(
            example_env,
            repo_root=Path("/opt/finco_staging"),
            repo_head=HEAD,
            check_filesystem=False,
        )


# ── E5 equity fundamentals additive contract ─────────────────────────────────

def test_equity_path_missing_raises() -> None:
    env = _env()
    del env["FINCO_EQUITY_FUNDAMENTALS_DB_PATH"]
    with pytest.raises(StagingPreflightError, match="MISSING"):
        _validate(env)


def test_equity_path_empty_raises() -> None:
    env = _env()
    env["FINCO_EQUITY_FUNDAMENTALS_DB_PATH"] = "   "
    with pytest.raises(StagingPreflightError, match="MISSING"):
        _validate(env)


def test_equity_path_relative_raises() -> None:
    env = _env()
    env["FINCO_EQUITY_FUNDAMENTALS_DB_PATH"] = "storage/equity.db"
    with pytest.raises(StagingPreflightError, match="absolute"):
        _validate(env)


def test_equity_path_outside_staging_root_raises(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    staging_root = tmp_path / "finco_staging"
    staging_root.mkdir()
    monkeypatch.setattr(staging_preflight, "STAGING_ROOT", staging_root)
    monkeypatch.setattr(staging_preflight, "PRODUCTION_ROOT", tmp_path / "finco_protocol")

    env = _env()
    env["FINCO_STAGING_ROOT"] = str(staging_root)
    env["FINCO_DB_PATH"] = str(staging_root / "storage" / "finco_staging.db")
    env["FINCO_STORAGE_PATH"] = str(staging_root / "storage" / "exports")
    env["FINCO_EQUITY_FUNDAMENTALS_DB_PATH"] = str(tmp_path / "other" / "equity.db")

    with pytest.raises(StagingPreflightError, match="must be under"):
        validate_staging_env(
            env, repo_root=staging_root, repo_head=HEAD, check_filesystem=False
        )


def test_equity_path_under_production_root_raises(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    staging_root = tmp_path
    production_root = tmp_path / "finco_protocol"
    production_root.mkdir()

    monkeypatch.setattr(staging_preflight, "STAGING_ROOT", staging_root)
    monkeypatch.setattr(staging_preflight, "PRODUCTION_ROOT", production_root)

    env = _env()
    env["FINCO_STAGING_ROOT"] = str(staging_root)
    env["FINCO_DB_PATH"] = str(staging_root / "storage" / "finco_staging.db")
    env["FINCO_STORAGE_PATH"] = str(staging_root / "storage" / "exports")
    env["FINCO_EQUITY_FUNDAMENTALS_DB_PATH"] = str(
        production_root / "equity_fundamentals.db"
    )

    with pytest.raises(StagingPreflightError, match="production root"):
        validate_staging_env(
            env, repo_root=staging_root, repo_head=HEAD, check_filesystem=False
        )


# ── Symlink escape tests (6 scenarios) ───────────────────────────────────────

def test_equity_symlink_escape_outside_staging_root_rejected(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    """Symlink inside staging that resolves outside staging root must be rejected."""
    staging_root = tmp_path / "finco_staging"
    storage = staging_root / "storage"
    storage.mkdir(parents=True)
    outside = tmp_path / "outside_equity.db"
    outside.write_bytes(b"")
    link = storage / "equity.db"
    link.symlink_to(outside)

    monkeypatch.setattr(staging_preflight, "STAGING_ROOT", staging_root)
    monkeypatch.setattr(staging_preflight, "PRODUCTION_ROOT", tmp_path / "finco_protocol")

    env = _env()
    env["FINCO_STAGING_ROOT"] = str(staging_root)
    env["FINCO_DB_PATH"] = str(storage / "finco_staging.db")
    env["FINCO_STORAGE_PATH"] = str(storage / "exports")
    env["FINCO_EQUITY_FUNDAMENTALS_DB_PATH"] = str(link)

    with pytest.raises(StagingPreflightError, match="must be under"):
        validate_staging_env(
            env, repo_root=staging_root, repo_head=HEAD, check_filesystem=False
        )


def test_equity_symlink_to_production_root_rejected(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    """Symlink inside staging pointing into production root must be rejected."""
    staging_root = tmp_path / "finco_staging"
    storage = staging_root / "storage"
    storage.mkdir(parents=True)
    prod_root = tmp_path / "finco_protocol"
    prod_storage = prod_root / "storage"
    prod_storage.mkdir(parents=True)
    prod_equity = prod_storage / "equity.db"
    prod_equity.write_bytes(b"")
    link = storage / "equity_link.db"
    link.symlink_to(prod_equity)

    monkeypatch.setattr(staging_preflight, "STAGING_ROOT", staging_root)
    monkeypatch.setattr(staging_preflight, "PRODUCTION_ROOT", prod_root)

    env = _env()
    env["FINCO_STAGING_ROOT"] = str(staging_root)
    env["FINCO_DB_PATH"] = str(storage / "finco_staging.db")
    env["FINCO_STORAGE_PATH"] = str(storage / "exports")
    env["FINCO_EQUITY_FUNDAMENTALS_DB_PATH"] = str(link)

    with pytest.raises(StagingPreflightError):
        validate_staging_env(
            env, repo_root=staging_root, repo_head=HEAD, check_filesystem=False
        )


def test_equity_dotdot_traversal_outside_staging_rejected(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    """Lexical ../ traversal that resolves outside staging root must be rejected."""
    staging_root = tmp_path / "finco_staging"
    staging_root.mkdir()
    monkeypatch.setattr(staging_preflight, "STAGING_ROOT", staging_root)
    monkeypatch.setattr(staging_preflight, "PRODUCTION_ROOT", tmp_path / "finco_protocol")

    env = _env()
    env["FINCO_STAGING_ROOT"] = str(staging_root)
    env["FINCO_DB_PATH"] = str(staging_root / "storage" / "finco_staging.db")
    env["FINCO_STORAGE_PATH"] = str(staging_root / "storage" / "exports")
    env["FINCO_EQUITY_FUNDAMENTALS_DB_PATH"] = str(
        staging_root / ".." / "equity.db"
    )

    with pytest.raises(StagingPreflightError, match="must be under"):
        validate_staging_env(
            env, repo_root=staging_root, repo_head=HEAD, check_filesystem=False
        )


def test_equity_chained_symlink_escape_rejected(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    """Chained symlinks that ultimately resolve outside staging must be rejected."""
    staging_root = tmp_path / "finco_staging"
    storage = staging_root / "storage"
    storage.mkdir(parents=True)
    outside = tmp_path / "prod_data"
    outside.mkdir()
    real_equity = outside / "equity.db"
    real_equity.write_bytes(b"")
    intermediate = storage / "link_a"
    intermediate.symlink_to(outside)
    final_link = storage / "equity.db"
    final_link.symlink_to(intermediate / "equity.db")

    monkeypatch.setattr(staging_preflight, "STAGING_ROOT", staging_root)
    monkeypatch.setattr(staging_preflight, "PRODUCTION_ROOT", tmp_path / "finco_protocol")

    env = _env()
    env["FINCO_STAGING_ROOT"] = str(staging_root)
    env["FINCO_DB_PATH"] = str(storage / "finco_staging.db")
    env["FINCO_STORAGE_PATH"] = str(storage / "exports")
    env["FINCO_EQUITY_FUNDAMENTALS_DB_PATH"] = str(final_link)

    with pytest.raises(StagingPreflightError, match="must be under"):
        validate_staging_env(
            env, repo_root=staging_root, repo_head=HEAD, check_filesystem=False
        )


def test_equity_symlink_within_staging_allowed(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    """Symlink inside staging that resolves inside staging must be accepted."""
    staging_root = tmp_path / "finco_staging"
    storage = staging_root / "storage"
    storage.mkdir(parents=True)
    real_file = storage / "equity_real.db"
    real_file.write_bytes(b"")
    link = storage / "equity.db"
    link.symlink_to(real_file)

    monkeypatch.setattr(staging_preflight, "STAGING_ROOT", staging_root)
    monkeypatch.setattr(staging_preflight, "PRODUCTION_ROOT", tmp_path / "finco_protocol")

    env = _env()
    env["FINCO_STAGING_ROOT"] = str(staging_root)
    env["FINCO_DB_PATH"] = str(storage / "finco_staging.db")
    env["FINCO_STORAGE_PATH"] = str(storage / "exports")
    env["FINCO_EQUITY_FUNDAMENTALS_DB_PATH"] = str(link)

    validate_staging_env(
        env, repo_root=staging_root, repo_head=HEAD, check_filesystem=False
    )


def test_equity_nonexistent_path_under_staging_accepted_no_fs(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    """resolve(strict=False) allows paths that do not yet exist on this machine."""
    staging_root = tmp_path / "finco_staging"
    staging_root.mkdir()
    monkeypatch.setattr(staging_preflight, "STAGING_ROOT", staging_root)
    monkeypatch.setattr(staging_preflight, "PRODUCTION_ROOT", tmp_path / "finco_protocol")

    env = _env()
    env["FINCO_STAGING_ROOT"] = str(staging_root)
    env["FINCO_DB_PATH"] = str(staging_root / "storage" / "finco_staging.db")
    env["FINCO_STORAGE_PATH"] = str(staging_root / "storage" / "exports")
    env["FINCO_EQUITY_FUNDAMENTALS_DB_PATH"] = str(
        staging_root / "storage" / "equity_does_not_exist.db"
    )

    validate_staging_env(
        env, repo_root=staging_root, repo_head=HEAD, check_filesystem=False
    )


# ── Equity mode checks ────────────────────────────────────────────────────────

def test_equity_mode_missing_raises() -> None:
    env = _env()
    del env["FINCO_EQUITY_FUNDAMENTALS_DB_MODE"]
    with pytest.raises(StagingPreflightError, match="MISSING"):
        _validate(env)


def test_equity_mode_invalid_raises() -> None:
    env = _env()
    env["FINCO_EQUITY_FUNDAMENTALS_DB_MODE"] = "wal"
    with pytest.raises(StagingPreflightError, match="invalid"):
        _validate(env)


def test_equity_mode_live_rejected_for_e5() -> None:
    env = _env()
    env["FINCO_EQUITY_FUNDAMENTALS_DB_MODE"] = "live"
    with pytest.raises(StagingPreflightError, match="snapshot"):
        _validate(env)


def test_equity_mode_uppercase_normalised() -> None:
    env = _env()
    env["FINCO_EQUITY_FUNDAMENTALS_DB_MODE"] = "SNAPSHOT"
    _validate(env)


def test_equity_mode_whitespace_normalised() -> None:
    env = _env()
    env["FINCO_EQUITY_FUNDAMENTALS_DB_MODE"] = "  snapshot  "
    _validate(env)


# ── Equity filesystem checks ──────────────────────────────────────────────────

def test_equity_db_file_missing_with_fs_check_raises(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    staging_root = tmp_path / "finco_staging"
    storage = staging_root / "storage"
    exports = storage / "exports"
    exports.mkdir(parents=True)
    env_file = staging_root / ".env.staging"
    env_file.write_text("# unit test\n", encoding="utf-8")
    env_file.chmod(0o600)

    monkeypatch.setattr(staging_preflight, "STAGING_ROOT", staging_root)
    monkeypatch.setattr(staging_preflight, "PRODUCTION_ROOT", tmp_path / "finco_protocol")

    env = _env()
    env["FINCO_STAGING_ROOT"] = str(staging_root)
    env["FINCO_DB_PATH"] = str(storage / "finco_staging.db")
    env["FINCO_STORAGE_PATH"] = str(exports)
    env["FINCO_EQUITY_FUNDAMENTALS_DB_PATH"] = str(storage / "equity_missing.db")

    with pytest.raises(StagingPreflightError, match="file not found"):
        validate_staging_env(
            env,
            repo_root=staging_root,
            repo_head=HEAD,
            check_filesystem=True,
            env_file=env_file,
        )


def test_equity_db_not_a_file_raises(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    staging_root = tmp_path / "finco_staging"
    storage = staging_root / "storage"
    exports = storage / "exports"
    exports.mkdir(parents=True)
    equity_dir = storage / "equity_dir.db"
    equity_dir.mkdir()
    env_file = staging_root / ".env.staging"
    env_file.write_text("# unit test\n", encoding="utf-8")
    env_file.chmod(0o600)

    monkeypatch.setattr(staging_preflight, "STAGING_ROOT", staging_root)
    monkeypatch.setattr(staging_preflight, "PRODUCTION_ROOT", tmp_path / "finco_protocol")

    env = _env()
    env["FINCO_STAGING_ROOT"] = str(staging_root)
    env["FINCO_DB_PATH"] = str(storage / "finco_staging.db")
    env["FINCO_STORAGE_PATH"] = str(exports)
    env["FINCO_EQUITY_FUNDAMENTALS_DB_PATH"] = str(equity_dir)

    with pytest.raises(StagingPreflightError, match="not a regular file"):
        validate_staging_env(
            env,
            repo_root=staging_root,
            repo_head=HEAD,
            check_filesystem=True,
            env_file=env_file,
        )


@pytest.mark.skipif(os.getuid() == 0, reason="root can read any file")
def test_equity_db_unreadable_raises(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    staging_root = tmp_path / "finco_staging"
    storage = staging_root / "storage"
    exports = storage / "exports"
    exports.mkdir(parents=True)
    equity_db = storage / "equity.db"
    equity_db.write_bytes(b"")
    equity_db.chmod(0o000)
    env_file = staging_root / ".env.staging"
    env_file.write_text("# unit test\n", encoding="utf-8")
    env_file.chmod(0o600)

    monkeypatch.setattr(staging_preflight, "STAGING_ROOT", staging_root)
    monkeypatch.setattr(staging_preflight, "PRODUCTION_ROOT", tmp_path / "finco_protocol")

    env = _env()
    env["FINCO_STAGING_ROOT"] = str(staging_root)
    env["FINCO_DB_PATH"] = str(storage / "finco_staging.db")
    env["FINCO_STORAGE_PATH"] = str(exports)
    env["FINCO_EQUITY_FUNDAMENTALS_DB_PATH"] = str(equity_db)

    try:
        with pytest.raises(StagingPreflightError, match="not readable"):
            validate_staging_env(
                env,
                repo_root=staging_root,
                repo_head=HEAD,
                check_filesystem=True,
                env_file=env_file,
            )
    finally:
        equity_db.chmod(0o644)


def test_equity_valid_snapshot_no_fs_passes() -> None:
    _validate(_env())


# ── CLI regression ────────────────────────────────────────────────────────────

def test_main_exits_2_on_blocked(tmp_path: Path) -> None:
    import subprocess
    import sys

    env_file = tmp_path / ".env.staging"
    env_file.write_text(
        "FINCO_ENV=production\nFINCO_SECRET_KEY=x\n", encoding="utf-8"
    )
    result = subprocess.run(
        [
            sys.executable, "tools/staging_preflight.py",
            "--env-file", str(env_file),
            "--repo-root", str(tmp_path),
            "--skip-filesystem-checks",
        ],
        capture_output=True,
        text=True,
        cwd=str(ROOT),
    )
    assert result.returncode == 2
    assert "P7_STAGING_PREFLIGHT_BLOCKED" in result.stdout


# ── Staging env example has equity section ────────────────────────────────────

def test_staging_env_example_has_equity_section() -> None:
    text = (ROOT / "deploy/staging.env.example").read_text(encoding="utf-8")
    assert "FINCO_EQUITY_FUNDAMENTALS_DB_PATH" in text
    assert "FINCO_EQUITY_FUNDAMENTALS_DB_MODE=snapshot" in text
    assert "equity_fundamentals" in text
