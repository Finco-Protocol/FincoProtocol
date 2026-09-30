"""P0-C secure runtime / deployment: explicit secure mode, fail-closed startup, no secret values in
output, systemd hardening, launcher guard, docs/debug surface. All secrets here are fake fixtures."""
from __future__ import annotations

import configparser
import os
import re
import subprocess
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
STRONG_SECRET = "p0c-fake-fixture-3f9a1c7e5b2d4860a1e4c9b7d6f3e2a1c"
STRONG_PASSWORD = "p0c-fake-fixture-operator-9c4e7a1b"
DEFAULT_PASSWORD = "FINCO Model2026!"
BCRYPT = "$2b$12$" + "a" * 53


def _startup(extra: dict, probe: str = "import app.auth; print('P0C_OK')"):
    env = {k: v for k, v in os.environ.items() if not k.startswith("FINCO_")}
    env.update(extra)
    env["PYTHONPATH"] = str(ROOT)
    return subprocess.run([sys.executable, "-c", probe], capture_output=True, text=True,
                          cwd=str(ROOT), env=env, timeout=120)


def _pilot(**overrides):
    base = {"FINCO_APP_MODE": "pilot", "FINCO_SECRET_KEY": STRONG_SECRET,
            "FINCO_ADMIN_USER": "operator", "FINCO_ADMIN_PASSWORD": STRONG_PASSWORD}
    base.update(overrides)
    return {k: v for k, v in base.items() if v is not None}


def _assert_fails_without_values(proc, *secrets):
    out = proc.stdout + proc.stderr
    assert proc.returncode != 0 and "P0C_OK" not in proc.stdout
    for value in secrets:
        assert value not in out, "a secret value leaked into startup output"


def test_pilot_with_strong_credentials_starts():
    proc = _startup(_pilot())
    assert proc.returncode == 0 and "P0C_OK" in proc.stdout, proc.stderr


def test_pilot_accepts_bcrypt_hash_without_plain_password():
    proc = _startup(_pilot(FINCO_ADMIN_PASSWORD=None, FINCO_ADMIN_PASSWORD_HASH=BCRYPT))
    assert proc.returncode == 0, proc.stderr


def test_pilot_rejects_missing_admin_password():
    _assert_fails_without_values(_startup(_pilot(FINCO_ADMIN_PASSWORD=None)), STRONG_SECRET)


def test_pilot_rejects_repository_default_admin_password():
    proc = _startup(_pilot(FINCO_ADMIN_PASSWORD=DEFAULT_PASSWORD))
    _assert_fails_without_values(proc, DEFAULT_PASSWORD, STRONG_SECRET)
    assert "repository default" in proc.stderr


@pytest.mark.parametrize("bad", ["changeme_set_a_strong_password_here", "short1!", "changeme_but_long_enough_1"])
def test_pilot_rejects_placeholder_or_short_admin_password(bad):
    _assert_fails_without_values(_startup(_pilot(FINCO_ADMIN_PASSWORD=bad)), bad, STRONG_SECRET)


def test_pilot_rejects_non_bcrypt_hash():
    proc = _startup(_pilot(FINCO_ADMIN_PASSWORD=None, FINCO_ADMIN_PASSWORD_HASH="plaintext-not-a-hash"))
    _assert_fails_without_values(proc, "plaintext-not-a-hash")


@pytest.mark.parametrize("secret", [None, "changeme_generate_a_real_secret_key_here"])
def test_pilot_rejects_missing_or_placeholder_signing_secret(secret):
    proc = _startup(_pilot(FINCO_SECRET_KEY=secret))
    _assert_fails_without_values(proc, STRONG_PASSWORD)


def test_pilot_rejects_placeholder_csrf_secret():
    proc = _startup(_pilot(FINCO_CSRF_SECRET="changeme_csrf_secret_value"))
    _assert_fails_without_values(proc, STRONG_PASSWORD, STRONG_SECRET)


def test_pilot_rejects_insecure_cookie():
    proc = _startup(_pilot(FINCO_COOKIE_SECURE="false"))
    _assert_fails_without_values(proc, STRONG_PASSWORD, STRONG_SECRET)


def test_unrecognized_mode_is_secure_and_requires_real_admin_credential():
    proc = _startup(_pilot(FINCO_APP_MODE="production", FINCO_ADMIN_PASSWORD=DEFAULT_PASSWORD))
    _assert_fails_without_values(proc, DEFAULT_PASSWORD)


def test_development_mode_keeps_the_documented_dev_workflow():
    proc = _startup({"FINCO_APP_MODE": "development"})
    assert proc.returncode == 0 and "P0C_OK" in proc.stdout


def test_env_example_declares_secure_mode_and_its_placeholders_cannot_start():
    text = (ROOT / "deploy" / "env.example").read_text()
    assert re.search(r"^FINCO_APP_MODE=pilot$", text, re.M)
    values = dict(line.split("=", 1) for line in text.splitlines()
                  if re.match(r"^FINCO_[A-Z_]+=", line))
    proc = _startup({k: v for k, v in values.items() if k in
                     {"FINCO_APP_MODE", "FINCO_SECRET_KEY", "FINCO_ADMIN_USER",
                      "FINCO_ADMIN_PASSWORD", "FINCO_COOKIE_SECURE"}})
    assert proc.returncode != 0  # copying the example unchanged must never start


def test_invalid_model_execution_config_fails_startup_without_echoing_value():
    proc = _startup({"FINCO_MODEL_EXECUTION_CONCURRENCY": "banana-9f3"},
                    "import app.runtime.model_execution as m; m.validate_model_execution_config(); print('P0C_OK')")
    assert proc.returncode != 0
    assert "banana-9f3" not in proc.stdout + proc.stderr


# ---- launcher ------------------------------------------------------------------------------

def _launcher(env_extra: dict):
    env = {k: v for k, v in os.environ.items() if not k.startswith("FINCO_")}
    env.update({"FINCO_SECRET_KEY": STRONG_SECRET, "FINCO_ADMIN_USER": "operator",
                "FINCO_ADMIN_PASSWORD": STRONG_PASSWORD})
    env.update(env_extra)
    return subprocess.run(["bash", str(ROOT / "deploy/scripts/run_web.sh")], capture_output=True,
                          text=True, env=env, timeout=60)


@pytest.mark.parametrize("mode", [None, "", "development", "internal", "staging"])
def test_launcher_refuses_anything_but_pilot(mode):
    proc = _launcher({} if mode is None else {"FINCO_APP_MODE": mode})
    assert proc.returncode == 78
    assert STRONG_SECRET not in proc.stdout + proc.stderr
    assert STRONG_PASSWORD not in proc.stdout + proc.stderr


def test_launcher_refuses_placeholder_admin_password_without_echo():
    proc = _launcher({"FINCO_APP_MODE": "pilot", "FINCO_ADMIN_PASSWORD": "changeme_x"})
    assert proc.returncode == 78 and "changeme_x" not in proc.stdout + proc.stderr


# ---- systemd -------------------------------------------------------------------------------

def _unit():
    parser = configparser.RawConfigParser(strict=False)
    parser.optionxform = str
    parser.read_string((ROOT / "deploy/systemd/finco-web.service").read_text())
    return parser["Service"]


def test_systemd_sets_secure_mode_and_hardening():
    text = (ROOT / "deploy/systemd/finco-web.service").read_text()
    assert re.search(r"^Environment=FINCO_APP_MODE=pilot$", text, re.M)
    required = {
        "NoNewPrivileges": "true", "ProtectSystem": "strict", "ProtectHome": "true",
        "PrivateTmp": "true", "ProtectKernelTunables": "true", "ProtectKernelModules": "true",
        "ProtectControlGroups": "true", "LockPersonality": "true", "RestrictRealtime": "true",
        "RestrictSUIDSGID": "true", "UMask": "0077",
    }
    unit = _unit()
    for key, value in required.items():
        assert unit.get(key) == value, key
    assert unit.get("CapabilityBoundingSet") == ""
    assert "AF_INET" in unit.get("RestrictAddressFamilies")
    assert "AF_NETLINK" not in unit.get("RestrictAddressFamilies")


def test_systemd_writable_paths_are_explicit_and_exclude_code_and_secrets():
    paths = _unit().get("ReadWritePaths").split()
    assert paths, "ProtectSystem=strict needs explicit writable paths"
    for path in paths:
        bare = path.lstrip("-")
        assert bare.startswith(("/opt/finco_protocol/storage", "/opt/finco_protocol/data", "/var/lib/finco"))
        assert bare not in ("/opt/finco_protocol", "/", "/etc")


def test_systemd_still_launches_via_canonical_launcher_and_omissions_are_documented():
    assert _unit().get("ExecStart").endswith("deploy/scripts/run_web.sh")
    text = (ROOT / "deploy/systemd/finco-web.service").read_text()
    for omitted in ("PrivateDevices", "MemoryDenyWriteExecute", "SystemCallFilter", "PrivateNetwork"):
        assert omitted in text  # named in the "deliberately NOT enabled" block
        assert not re.search(rf"^{omitted}=", text, re.M)


# ---- debug / documentation surface ----------------------------------------------------------

def test_production_app_has_no_debug_mode_and_no_default_docs_routes():
    import main_web
    assert main_web.app.debug is False
    assert main_web.app.docs_url is None and main_web.app.redoc_url is None
    assert main_web.app.openapi_url is None


def test_public_openapi_schema_lists_only_public_v1_paths():
    import main_web
    from fastapi.testclient import TestClient
    body = TestClient(main_web.app).get("/api/openapi.json").json()
    assert body["paths"] and all(p.startswith("/api/v1") for p in body["paths"])


def test_collector_unit_keeps_its_hardening():
    text = (ROOT / "deploy/r_live_collector_v1/finco-r-live-collector.service").read_text() \
        if (ROOT / "deploy/r_live_collector_v1/finco-r-live-collector.service").exists() else ""
    if text:
        for directive in ("NoNewPrivileges=true", "ProtectSystem=strict", "UMask=0077"):
            assert directive in text
