"""M2-B Model-side coexistence boundary (FINCO_MOUNT_RADAR=1/0) and fail-closed
internal auth introspection contract tests."""

from __future__ import annotations

import json
import os
from pathlib import Path
import subprocess
import sys

from fastapi import FastAPI
from fastapi.testclient import TestClient

from app.auth import create_demo_session_token, create_session_token
from app.internal_auth_introspect import INTERNAL_TOKEN_ENV, SCHEMA_VERSION, router as introspect_router

ROOT = Path(__file__).resolve().parents[1]


def _probe_app_boot(module_name: str, mount_radar: str) -> dict:
    env = dict(os.environ)
    env["FINCO_MOUNT_RADAR"] = mount_radar
    env["FINCO_RLIVE_WARMING_ENABLED"] = "0"
    env["PYTHONPATH"] = str(ROOT)
    code = f"""
import json, sys, {module_name} as mod
paths = sorted(mod.app.openapi()["paths"].keys())
radar_mods = sorted(m for m in sys.modules if m == "finco_radar" or m.startswith("finco_radar.") or m == "finco_yield" or m.startswith("finco_yield."))
print(json.dumps({{"paths": paths, "radar_mods": radar_mods}}))
"""
    out = subprocess.check_output([sys.executable, "-c", code], cwd=ROOT, env=env, text=True)
    return json.loads(out.splitlines()[-1])


def test_main_web_flag_off_boots_without_importing_radar_or_yield() -> None:
    res = _probe_app_boot("main_web", "0")
    assert res["radar_mods"] == [], f"Radar/Yield leaked into flag-off boot: {res['radar_mods']}"
    paths = set(res["paths"])
    # Model routes preserved
    assert any(p.startswith("/v2/") for p in paths)
    assert any(p.startswith("/api/v1/model/") for p in paths)
    assert "/.well-known/finco/keys.json" in paths
    assert "/internal/v1/auth/introspect" in paths
    # Radar/Crypto routes absent when flag is off
    assert "/radar" not in paths
    assert "/crypto" not in paths
    assert "/api/v1/radar/assets" not in paths
    assert "/api/v1.1/radar/r-live/assets" not in paths


def test_main_web_default_flag_on_preserves_coexistence_routes() -> None:
    res = _probe_app_boot("main_web", "1")
    paths = set(res["paths"])
    assert any(p.startswith("/v2/") for p in paths)
    assert any(p.startswith("/api/v1/model/") for p in paths)
    assert "/api/v1/radar/assets" in paths
    assert "/api/v1.1/radar/r-live/assets" in paths
    assert "/internal/v1/auth/introspect" in paths


def test_main_api_flag_off_keeps_model_api_and_omits_radar() -> None:
    res = _probe_app_boot("main_api", "0")
    assert res["radar_mods"] == [], f"Radar/Yield leaked into main_api flag-off: {res['radar_mods']}"
    paths = set(res["paths"])
    assert "/health" in paths
    assert any(p.startswith("/api/v1/model/") for p in paths)
    assert "/internal/v1/auth/introspect" in paths
    assert "/api/v1/radar/assets" not in paths


def test_internal_auth_introspect_fail_closed_and_valid_sessions(monkeypatch) -> None:
    app = FastAPI()
    app.include_router(introspect_router)
    client = TestClient(app)

    # 1. Disabled by default -> 503
    monkeypatch.delenv(INTERNAL_TOKEN_ENV, raising=False)
    r = client.post("/internal/v1/auth/introspect", json={"audience": "finco-radar-v1"})
    assert r.status_code == 503

    # Configure strong internal service token
    secret_token = "m2b-test-internal-service-token-32chars"
    monkeypatch.setenv(INTERNAL_TOKEN_ENV, secret_token)

    # 2. Missing / wrong internal token -> 401
    assert client.post("/internal/v1/auth/introspect", json={"audience": "finco-radar-v1"}).status_code == 401
    assert (
        client.post(
            "/internal/v1/auth/introspect",
            headers={"X-Finco-Internal-Token": "wrong-token"},
            json={"audience": "finco-radar-v1"},
        ).status_code
        == 401
    )

    # 3. Wrong audience -> 403
    assert (
        client.post(
            "/internal/v1/auth/introspect",
            headers={"X-Finco-Internal-Token": secret_token},
            json={"audience": "other-service"},
        ).status_code
        == 403
    )

    # 4. Extra unknown field -> 422 (strict schema)
    assert (
        client.post(
            "/internal/v1/auth/introspect",
            headers={"X-Finco-Internal-Token": secret_token},
            json={"audience": "finco-radar-v1", "unexpected": "x"},
        ).status_code
        == 422
    )

    # 5. Missing / tampered session token -> authenticated=False
    anon = client.post(
        "/internal/v1/auth/introspect",
        headers={"X-Finco-Internal-Token": secret_token},
        json={"audience": "finco-radar-v1", "session_token": "tampered.invalid.token"},
    )
    assert anon.status_code == 200
    assert anon.json()["authenticated"] is False
    assert anon.json()["session_kind"] == "anonymous"
    assert anon.json()["schema_version"] == SCHEMA_VERSION

    # 6. Valid admin session token -> authenticated=True, minimum claims, no token echo
    admin_tok = create_session_token(user_id="42", username="owner")
    ok_admin = client.post(
        "/internal/v1/auth/introspect",
        headers={"X-Finco-Internal-Token": secret_token},
        json={"audience": "finco-radar-v1", "session_token": admin_tok},
    )
    assert ok_admin.status_code == 200
    body = ok_admin.json()
    assert body["authenticated"] is True
    assert body["session_kind"] == "admin"
    assert body["user_id"] == "42"
    assert body["tenant_id"] == "42"
    assert "radar:read" in body["entitlements"]
    assert admin_tok not in ok_admin.text

    # 7. Valid demo session token -> authenticated=True, scoped demo entitlement
    demo_tok = create_demo_session_token("demo-u1")
    ok_demo = client.post(
        "/internal/v1/auth/introspect",
        headers={"X-Finco-Internal-Token": secret_token},
        json={"audience": "finco-radar-v1", "demo_session_token": demo_tok},
    )
    assert ok_demo.status_code == 200
    dbody = ok_demo.json()
    assert dbody["authenticated"] is True
    assert dbody["session_kind"] == "demo"
    assert dbody["entitlements"] == ["radar:read:public"]
    assert demo_tok not in ok_demo.text
