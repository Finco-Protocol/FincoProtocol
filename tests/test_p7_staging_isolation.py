from pathlib import Path

import pytest

from tools.staging_preflight import StagingPreflightError, validate_staging_env

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


def _validate(env: dict[str, str]) -> None:
    validate_staging_env(
        env,
        repo_root=Path("/opt/finco_staging"),
        repo_head=HEAD,
        check_filesystem=False,
    )


def test_valid_staging_contract_passes() -> None:
    _validate(_env())


def test_production_environment_is_rejected() -> None:
    env = _env()
    env["FINCO_ENV"] = "production"
    with pytest.raises(StagingPreflightError, match="FINCO_ENV"):
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


def test_systemd_unit_is_staging_isolated() -> None:
    text = (ROOT / "deploy/systemd/finco-staging.service").read_text(encoding="utf-8")
    assert "User=finco-staging" in text
    assert "WorkingDirectory=/opt/finco_staging" in text
    assert "EnvironmentFile=/opt/finco_staging/.env.staging" in text
    assert "--port 8100" in text
    assert "staging_preflight.py" in text
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
    text = (ROOT / "deploy/staging.env.example").read_text(encoding="utf-8")
    assert "FINCO_ENV=staging" in text
    assert "FINCO_STAGING_ROOT=/opt/finco_staging" in text
    assert "FINCO_STAGING_PORT=8100" in text
    assert "FINCO_STAGING_HOST=staging.finco.one" in text
    assert "FINCO_DB_PATH=/opt/finco_staging/storage/finco_staging.db" in text
    assert "FINCO_DEPLOY_SHA=" in text
