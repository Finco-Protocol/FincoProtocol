"""M2-B / Correction B tests: FINCO_MOUNT_RADAR coexistence flag, guarded import-blocker boot,
Model v1.1 institutional route preservation, and private-network internal auth introspect."""
from __future__ import annotations

import json
import os
import subprocess
import sys
from pathlib import Path

from fastapi import FastAPI
from fastapi.testclient import TestClient

from app.auth import create_demo_session_token, create_session_token
from app.internal_auth_introspect import (
    INTERNAL_TOKEN_ENV,
    SCHEMA_VERSION,
    router as introspect_router,
)

REPO_ROOT = Path(__file__).resolve().parents[1]


def _probe_app_boot(module_name: str, mount_radar: str, block_radar_imports: bool = False) -> dict:
    env = os.environ.copy()
    env["FINCO_MOUNT_RADAR"] = mount_radar
    env["FINCO_RLIVE_WARMING_ENABLED"] = "0"
    env["PYTHONPATH"] = str(REPO_ROOT)
    code = (
        "import importlib, json, sys\n"
        f"if {block_radar_imports!r}:\n"
        "    class _Blocker:\n"
        "        def find_spec(self, fullname, path, target=None):\n"
        "            if fullname in ('finco_radar', 'finco_yield') or fullname.startswith(('finco_radar.', 'finco_yield.')):\n"
        "                raise ImportError(f'Blocked forbidden import: {fullname}')\n"
        "            return None\n"
        "    sys.meta_path.insert(0, _Blocker())\n"
        f"mod = importlib.import_module({module_name!r})\n"
        "from fastapi.testclient import TestClient\n"
        "paths = sorted(mod.app.openapi()['paths'].keys())\n"
        "leaked = sorted(m for m in sys.modules if m == 'finco_radar' or m.startswith('finco_radar.') or m == 'finco_yield' or m.startswith('finco_yield.'))\n"
        "c = TestClient(mod.app)\n"
        "probe_status = {}\n"
        "if 'main_api' == mod.__name__:\n"
        "    probe_status['health'] = c.get('/health').status_code\n"
        "    probe_status['supported_today'] = c.get('/api/v1.1/supported-today').status_code\n"
        "else:\n"
        "    probe_status['root'] = c.get('/').status_code\n"
        "print(json.dumps({'paths': paths, 'leaked': leaked, 'probe_status': probe_status}))\n"
    )
    out = subprocess.check_output([sys.executable, "-c", code], cwd=str(REPO_ROOT), env=env, text=True)
    return json.loads(out.strip().splitlines()[-1])


def test_main_web_flag_off_boots_with_import_blocker_and_zero_radar_imports() -> None:
    res = _probe_app_boot("main_web", "0", block_radar_imports=True)
    assert res["leaked"] == [], f"Unexpected Radar/Yield imports with FINCO_MOUNT_RADAR=0: {res['leaked']}"
    assert res["probe_status"]["root"] == 200
    paths = set(res["paths"])
    assert "/v2" in paths or any(p.startswith("/v2/") for p in paths)
    assert "/radar" not in paths
    assert "/yield" not in paths
    # Internal auth endpoint must be hidden from public OpenAPI schema
    assert "/internal/v1/auth/introspect" not in paths


def test_main_web_default_flag_on_preserves_coexistence_routes() -> None:
    res = _probe_app_boot("main_web", "1")
    paths = set(res["paths"])
    assert "/radar" in paths
    assert "/yield" in paths
    assert "/internal/v1/auth/introspect" not in paths


def test_main_api_flag_off_preserves_model_v1_1_institutional_and_omits_radar() -> None:
    res = _probe_app_boot("main_api", "0", block_radar_imports=True)
    assert res["leaked"] == []
    paths = set(res["paths"])
    assert "/health" in paths
    assert any(p.startswith("/api/v1/model/") for p in paths)
    # Correction B: Model institutional v1.1 surface MUST remain intact when FINCO_MOUNT_RADAR=0
    assert "/api/v1.1/supported-today" in paths
    assert "/api/v1.1/projects" in paths
    assert res["probe_status"]["health"] == 200
    assert res["probe_status"]["supported_today"] == 200
    assert "/api/v1/radar/assets" not in paths
    assert "/api/v1.1/radar/r-live/assets" not in paths
    assert "/internal/v1/auth/introspect" not in paths


def test_internal_auth_introspect_fail_closed_private_boundary_and_canonical_decisions(monkeypatch) -> None:
    app = FastAPI()
    app.include_router(introspect_router)
    client = TestClient(app)

    # Hidden from public OpenAPI
    assert "/internal/v1/auth/introspect" not in app.openapi()["paths"]

    # 1. Disabled by default -> 503
    monkeypatch.delenv(INTERNAL_TOKEN_ENV, raising=False)
    r = client.post("/internal/v1/auth/introspect", json={"audience": "radar"})
    assert r.status_code == 503

    secret_token = "m2b-test-internal-service-token-32chars"
    monkeypatch.setenv(INTERNAL_TOKEN_ENV, secret_token)

    # 2. Proxied request (X-Forwarded-For / Forwarded) -> 403 denied
    assert (
        client.post(
            "/internal/v1/auth/introspect",
            headers={"X-Finco-Internal-Token": secret_token, "X-Forwarded-For": "203.0.113.10"},
            json={"audience": "radar"},
        ).status_code
        == 403
    )

    # 3. Missing / wrong internal token -> 401
    assert client.post("/internal/v1/auth/introspect", json={"audience": "radar"}).status_code == 401
    assert (
        client.post(
            "/internal/v1/auth/introspect",
            headers={"X-Finco-Internal-Token": "wrong-token"},
            json={"audience": "radar"},
        ).status_code
        == 401
    )

    # 4. Wrong audience -> 403
    assert (
        client.post(
            "/internal/v1/auth/introspect",
            headers={"X-Finco-Internal-Token": secret_token},
            json={"audience": "other-service"},
        ).status_code
        == 403
    )

    # 5. Extra unknown field -> 422
    assert (
        client.post(
            "/internal/v1/auth/introspect",
            headers={"X-Finco-Internal-Token": secret_token},
            json={"audience": "radar", "unexpected": "x"},
        ).status_code
        == 422
    )

    # 6. Tampered cookie -> authenticated=False + canonical entitlement_decisions
    anon = client.post(
        "/internal/v1/auth/introspect",
        headers={"X-Finco-Internal-Token": secret_token},
        json={"audience": "radar", "session_cookie": "tampered.invalid.token"},
    )
    assert anon.status_code == 200
    assert anon.json()["authenticated"] is False
    assert anon.json()["schema"] == SCHEMA_VERSION
    assert "crypto.api" in anon.json()["entitlement_decisions"]

    # 7. Valid user session cookie -> authenticated=True, canonical decisions, no hardcoded excess entitlements, no token echo
    user_tok = create_session_token(user_id="42", username="owner")
    ok_user = client.post(
        "/internal/v1/auth/introspect",
        headers={"X-Finco-Internal-Token": secret_token},
        json={"audience": "radar", "session_cookie": user_tok},
    )
    assert ok_user.status_code == 200
    body = ok_user.json()
    assert body["authenticated"] is True
    assert body["session_kind"] == "user"
    assert body["user_id"] == "42"
    assert "crypto.api" in body["entitlement_decisions"]
    assert "tokenized.basic" in body["entitlement_decisions"]
    assert "yield.basic" in body["entitlement_decisions"]
    assert user_tok not in ok_user.text

    # 8. Valid demo session cookie -> authenticated=True, canonical decisions, no token echo
    demo_tok = create_demo_session_token("demo-u1")
    ok_demo = client.post(
        "/internal/v1/auth/introspect",
        headers={"X-Finco-Internal-Token": secret_token},
        json={"audience": "radar", "demo_cookie": demo_tok},
    )
    assert ok_demo.status_code == 200
    assert ok_demo.json()["authenticated"] is True
    assert ok_demo.json()["session_kind"] == "demo"
    assert demo_tok not in ok_demo.text
