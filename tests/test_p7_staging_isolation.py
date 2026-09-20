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


def _env() -> dict[str, str]:
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
    }


def _validate(env: dict[str, str], *, repo_root: Path | None = None) -> None:
    validate_staging_env(
        env,
        repo_root=repo_root or Path("/opt/finco_staging"),
        repo_head=HEAD,
        check_filesystem=False,
    )


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


def test_git_head_is_independent_of_service_path(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    # Regression for independent-review MAJOR-1: systemd intentionally exposes
    # only the venv on PATH. _git_head must still resolve the reviewed /usr/bin/git.
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

    monkeypatch.setattr(staging_preflight, "STAGING_ROOT", staging_root)
    monkeypatch.setattr(staging_preflight, "PRODUCTION_ROOT", tmp_path / "finco_protocol")

    env = _env()
    env["FINCO_STAGING_ROOT"] = str(staging_root)
    env["FINCO_DB_PATH"] = str(storage_root / "finco_staging.db")
    env["FINCO_STORAGE_PATH"] = str(exports)

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

    with pytest.raises(StagingPreflightError, match="required staging directory missing"):
        validate_staging_env(
            env,
            repo_root=staging_root,
            repo_head=HEAD,
            check_filesystem=True,
            env_file=env_file,
        )


def test_systemd_unit_is_staging_isolated() -> None:
    text = (ROOT / "deploy/systemd/finco-staging.service").read_text(encoding="utf-8")
    assert "User=finco-staging" in text
    assert "WorkingDirectory=/opt/finco_staging" in text
    assert "EnvironmentFile=/opt/finco_staging/.env.staging" in text
    assert "--port 8100" in text
    assert "staging_preflight.py" in text
    assert "PYTHONDONTWRITEBYTECODE=1" in text
    assert "ProtectSystem=strict" in text
    assert "ReadWritePaths=/opt/finco_staging/storage" in text
    assert "/opt/finco_protocol" not in text


def test_nginx_vhost_is_staging_only() -> None:
    text = (ROOT / "deploy/nginx/staging.conf").read_text(encoding="utf-8")
    assert "server_name staging.finco.one;" in text
    assert "proxy_pass http://127.0.0.1:8100;" in text
    assert "/opt/finco_staging/static/" in text
    assert "finco-staging.access.log" in text
    assert "server_name app.finco.one;" not in text
    assert "/etc/letsencrypt/live/app.finco.one/" not in text


def test_production_deploy_templates_remain_distinct() -> None:
    prod_service = (ROOT / "deploy/systemd/finco-web.service").read_text(encoding="utf-8")
    prod_nginx = (ROOT / "deploy/nginx/app.conf").read_text(encoding="utf-8")
    staging_service = (ROOT / "deploy/systemd/finco-staging.service").read_text(encoding="utf-8")
    staging_nginx = (ROOT / "deploy/nginx/staging.conf").read_text(encoding="utf-8")

    assert "127.0.0.1:8000" in prod_service
    assert "app.finco.one" in prod_nginx
    assert "--port 8100" in staging_service
    assert "staging.finco.one" in staging_nginx
    assert prod_service != staging_service
    assert prod_nginx != staging_nginx


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
