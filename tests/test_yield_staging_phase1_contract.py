"""Yield Phase 1 staging deployment contract.

These tests validate the staging isolation/configuration layer. Product behaviour
remains covered by the existing Yield and browser suites. Existing E5 corporate
staging invariants are regression-protected while runtime gates move to PR #152.
"""
from __future__ import annotations

import importlib.util
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
BASELINE_SHA = "cf65370f6fb46fc8a3facae5b9f34077b36651b8"


def _load_preflight():
    path = ROOT / "tools" / "staging_preflight.py"
    spec = importlib.util.spec_from_file_location("finco_staging_preflight", path)
    assert spec and spec.loader
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def _valid_env() -> dict[str, str]:
    return {
        "FINCO_ENV": "staging",
        "FINCO_APP_MODE": "pilot",
        "FINCO_STAGING_ROOT": "/opt/finco_staging",
        "FINCO_STAGING_PORT": "8100",
        "FINCO_STAGING_HOST": "staging.finco.one",
        "FINCO_DEPLOY_SHA": BASELINE_SHA,
        "FINCO_SECRET_KEY": "s" * 80,
        "FINCO_CSRF_SECRET": "c" * 80,
        "FINCO_ADMIN_USER": "staging_operator",
        "FINCO_ADMIN_PASSWORD": "phase-one-strong-credential-2026!",
        "FINCO_COOKIE_SECURE": "true",
        "FINCO_COOKIE_SAMESITE": "lax",
        "FINCO_SESSION_HOURS": "4",
        "FINCO_DEMO_RESET_ALLOWED": "true",
        "FINCO_WEB_HOST": "127.0.0.1",
        "FINCO_WEB_PORT": "8100",
        "FINCO_WEB_WORKERS": "2",
        "FINCO_WEB_GRACEFUL_SHUTDOWN_SECONDS": "30",
        "FINCO_MODEL_EXECUTION_CONCURRENCY": "2",
        "FINCO_MODEL_EXECUTION_MODE": "process",
        "FINCO_MODEL_EXECUTION_TIMEOUT_SECONDS": "180",
        "FINCO_YIELD_ENABLED": "1",
        "FINCO_YIELD_EXECUTION_ENABLED": "0",
        "FINCO_DB_PATH": "/opt/finco_staging/storage/finco_staging.db",
        "FINCO_STORAGE_PATH": "/opt/finco_staging/exports",
        "RADAR_BNB_INTELLIGENCE_DB_PATH": "/opt/finco_staging/storage/radar.db",
        "FINCO_EQUITY_FUNDAMENTALS_DB_PATH": "/opt/finco_staging/storage/equity.db",
        "FINCO_EQUITY_FUNDAMENTALS_DB_MODE": "snapshot",
        "FINCO_YIELD_HISTORY_PATH": "",
    }


def test_staging_example_is_current_secure_yield_phase1_contract():
    text = (ROOT / "deploy" / "staging.env.example").read_text()
    assert "FINCO_APP_MODE=pilot" in text
    assert "FINCO_WEB_HOST=127.0.0.1" in text
    assert "FINCO_WEB_PORT=8100" in text
    assert "FINCO_MODEL_EXECUTION_CONCURRENCY=" in text
    assert "FINCO_MODEL_EXECUTION_MODE=process" in text
    assert "FINCO_MAX_CONCURRENT_RUNS=" not in text  # stale pre-PR#152 variable
    assert "FINCO_DEMO_RESET_ALLOWED=true" in text  # preserve corporate staging contract
    assert "FINCO_EQUITY_FUNDAMENTALS_DB_MODE=snapshot" in text
    assert "FINCO_YIELD_ENABLED=1" in text
    assert "FINCO_YIELD_EXECUTION_ENABLED=0" in text
    assert "/opt/finco_protocol" not in text


def test_staging_systemd_isolated_and_reuses_canonical_secure_launcher():
    text = (ROOT / "deploy" / "systemd" / "finco-staging.service").read_text()
    for required in (
        "User=finco-staging",
        "Group=finco-staging",
        "WorkingDirectory=/opt/finco_staging",
        "EnvironmentFile=/opt/finco_staging/.env.staging",
        "ExecStart=/bin/bash /opt/finco_staging/deploy/scripts/run_web.sh",
        "ProtectSystem=strict",
        "NoNewPrivileges=true",
        "UMask=0077",
        "RuntimeDirectory=finco-staging",
    ):
        assert required in text
    assert "ExecStartPre=" in text and "staging_preflight.py" in text
    assert "ReadWritePaths=-/opt/finco_staging/storage" in text
    assert "ReadWritePaths=-/opt/finco_protocol" not in text
    assert "app.finco.one" not in text


def test_staging_nginx_is_hostname_port_and_log_isolated():
    text = (ROOT / "deploy" / "nginx" / "staging.conf").read_text()
    assert text.count("server_name staging.finco.one;") == 2
    assert "proxy_pass http://127.0.0.1:8100;" in text
    assert "/var/log/nginx/finco-staging.access.log" in text
    assert "/var/log/nginx/finco-staging.error.log" in text
    assert "/opt/finco_staging/static/" in text
    assert "app.finco.one" not in text


def test_preflight_accepts_phase1_contract_without_filesystem_probe():
    preflight = _load_preflight()
    preflight.validate_staging_env(
        _valid_env(),
        repo_root=Path("/opt/finco_staging"),
        repo_head=BASELINE_SHA,
        check_filesystem=False,
    )


def test_preflight_accepts_bcrypt_hash_instead_of_plain_password():
    preflight = _load_preflight()
    env = _valid_env()
    del env["FINCO_ADMIN_PASSWORD"]
    env["FINCO_ADMIN_PASSWORD_HASH"] = "$2b$12$" + "a" * 53
    preflight.validate_staging_env(
        env,
        repo_root=Path("/opt/finco_staging"),
        repo_head=BASELINE_SHA,
        check_filesystem=False,
    )


@pytest.mark.parametrize(
    ("key", "value"),
    [
        ("FINCO_APP_MODE", "development"),
        ("FINCO_COOKIE_SECURE", "false"),
        ("FINCO_DEMO_RESET_ALLOWED", "false"),
        ("FINCO_WEB_HOST", "0.0.0.0"),
        ("FINCO_WEB_PORT", "8000"),
        ("FINCO_YIELD_ENABLED", "0"),
        ("FINCO_YIELD_EXECUTION_ENABLED", "1"),
        ("FINCO_MODEL_EXECUTION_MODE", "thread"),
        ("FINCO_DB_PATH", "/opt/finco_protocol/storage/prod.db"),
        ("FINCO_EQUITY_FUNDAMENTALS_DB_MODE", "live"),
    ],
)
def test_preflight_fails_closed_on_phase1_or_isolation_violation(key, value):
    preflight = _load_preflight()
    env = _valid_env()
    env[key] = value
    with pytest.raises(preflight.StagingPreflightError):
        preflight.validate_staging_env(
            env,
            repo_root=Path("/opt/finco_staging"),
            repo_head=BASELINE_SHA,
            check_filesystem=False,
        )


def test_preflight_preserves_equity_snapshot_separation():
    preflight = _load_preflight()
    env = _valid_env()
    env["FINCO_EQUITY_FUNDAMENTALS_DB_PATH"] = env["FINCO_DB_PATH"]
    with pytest.raises(preflight.StagingPreflightError):
        preflight.validate_staging_env(
            env,
            repo_root=Path("/opt/finco_staging"),
            repo_head=BASELINE_SHA,
            check_filesystem=False,
        )


def test_preflight_fails_closed_on_sha_mismatch():
    preflight = _load_preflight()
    with pytest.raises(preflight.StagingPreflightError):
        preflight.validate_staging_env(
            _valid_env(),
            repo_root=Path("/opt/finco_staging"),
            repo_head="0" * 40,
            check_filesystem=False,
        )


def test_yield_repository_defaults_remain_off(monkeypatch):
    monkeypatch.delenv("FINCO_YIELD_ENABLED", raising=False)
    monkeypatch.delenv("FINCO_YIELD_EXECUTION_ENABLED", raising=False)
    from finco_yield.flags import execution_enabled, yield_enabled

    assert yield_enabled() is False
    assert execution_enabled() is False


def test_direct_erc4626_remains_non_signable_preview_only():
    text = (ROOT / "finco_yield" / "execution.py").read_text()
    assert "UNPROTECTED_PREVIEW_ONLY" in text
    assert "user_signable=False" in text


def test_phase1_changes_are_deployment_only_not_product_forks():
    assert not (ROOT / "finco_yield_staging").exists()
    assert (ROOT / "finco_yield" / "web.py").exists()
    assert (ROOT / "deploy" / "scripts" / "run_web.sh").exists()
