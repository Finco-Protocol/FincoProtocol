"""Cross-system acceptance: saturation or outage in one subsystem must not degrade the others.

Subsystems: Model execution, Radar (R-LIVE), Verify / Signed Run verification, TypeSafe (JEV transport).
Verify is represented by the public reference certificate route (light, unauthenticated)."""
from __future__ import annotations

import asyncio
import subprocess
import sys
import threading
import time
from pathlib import Path

import pytest

import p0_exec_helpers as helpers
from app.radar_rwa import r_live_public_acquisition as acq
from app.radar_rwa import r_live_service
from app.radar_rwa.jev_intelligence.config import JevIntelligenceConfig
from app.radar_rwa.jev_intelligence.contracts import JevMode
from app.radar_rwa.jev_intelligence.service import evaluate_intelligence
from app.runtime import client_rate_limit as crl
from app.runtime import model_execution as me
from finco_radar.authority.r_live_policy import APPROVED_BY_CANONICAL_ID

ROOT = Path(__file__).resolve().parents[1]
CID = next(iter(APPROVED_BY_CANONICAL_ID))
VERIFY_URL = "/verify/reference/solar-reference-a/certificate.json"
FAST_SECONDS = 5.0


@pytest.fixture(autouse=True)
def _reset(monkeypatch):
    monkeypatch.setenv("ROBINHOOD_RPC_URL", "https://rpc.example.invalid/")
    crl.reset_client_limiter_for_tests()
    yield
    me.reset_model_executor_for_tests(None)
    crl.reset_client_limiter_for_tests()


@pytest.fixture
def client():
    import main_web
    from starlette.testclient import TestClient
    return TestClient(main_web.app, raise_server_exceptions=False)


def _executor(concurrency=1):
    executor = me.ModelExecutor(me.ModelExecutionConfig(concurrency, "thread", 60))
    me.reset_model_executor_for_tests(executor)
    return executor


class _Occupy:
    def __init__(self, executor):
        helpers.RELEASE.clear()
        self.executor = executor
        self.thread = threading.Thread(target=lambda: asyncio.run(executor.run_thread(helpers.hold_until_released)))
        self.thread.start()
        deadline = time.time() + 10
        while executor.stats()["active"] < 1 and time.time() < deadline:
            time.sleep(0.01)

    def release(self):
        helpers.RELEASE.set()
        self.thread.join(15)


def _timed(client, url):
    started = time.perf_counter()
    response = client.get(url)
    return response, time.perf_counter() - started


def _lightweight_ok(client):
    for url in ("/public-health", "/api/v1.1/radar/r-live/assets", VERIFY_URL):
        response, elapsed = _timed(client, url)
        assert response.status_code == 200, url
        assert elapsed < 30.0, url  # a saturated subsystem must not stall unrelated reads


def test_model_saturation_does_not_affect_radar_verify_or_health(client, monkeypatch):
    from app.api.v1_1 import institutional
    monkeypatch.setattr(institutional, "get_r_live", lambda uid: ("UNAVAILABLE", {"reason": "X"}))
    occupant = _Occupy(_executor(1))
    try:
        _lightweight_ok(client)
        radar, elapsed = _timed(client, f"/api/v1.1/radar/r-live/{CID}")
        assert radar.status_code == 200 and elapsed < FAST_SECONDS
        assert asyncio.run(_light_model_probe(occupied=True)) == "BUSY"
    finally:
        occupant.release()


async def _light_model_probe(occupied: bool) -> str:
    try:
        await me.get_model_executor().run_thread(helpers.add, 1, 2)
        return "OK"
    except me.ModelExecutionBusy:
        return "BUSY"


def test_radar_saturation_does_not_block_model_verify_or_typesafe(client, monkeypatch):
    coordinator = acq.PublicAcquisitionCoordinator(process_limit=1, max_coalesced_callers=4)
    monkeypatch.setattr(acq, "PUBLIC_RLIVE_ACQUISITION", coordinator)
    release, started = threading.Event(), threading.Event()

    def slow(**kwargs):
        started.set()
        release.wait(10)
        raise RuntimeError("done")

    monkeypatch.setattr(r_live_service, "collect_r_live", slow)
    monkeypatch.setattr(r_live_service, "collect_aapl_r_live", slow)
    _executor(1)
    other = [c for c in APPROVED_BY_CANONICAL_ID if c != CID][0]
    holder = threading.Thread(target=lambda: _swallow(acq.acquire_single_current, CID, "https://rpc.example.invalid/"))
    holder.start()
    assert started.wait(5)
    try:
        busy = client.get(f"/api/v1.1/radar/r-live/{other}")
        assert busy.status_code == 429 and busy.json()["state"] == "SERVICE_BUSY"
        assert asyncio.run(_light_model_probe(occupied=False)) == "OK"      # Model unaffected
        response, elapsed = _timed(client, VERIFY_URL)                       # Verify unaffected
        assert response.status_code == 200
        # TypeSafe (JEV transport) failure path is independent and typed
        result = evaluate_intelligence(
            other, config=JevIntelligenceConfig(mode=JevMode.VISIBLE),
            current_provider=lambda cid: ("UNAVAILABLE", {"reason": "X"}), environ={})
        assert result.state.value == "UNAVAILABLE"
    finally:
        release.set()
        holder.join(10)


def _swallow(fn, *args):
    try:
        fn(*args)
    except Exception:
        pass


def test_radar_rpc_outage_is_typed_and_isolated(client, monkeypatch):
    def down(**kwargs):
        raise ConnectionError("rpc down https://secret.example/key")

    monkeypatch.setattr(r_live_service, "collect_r_live", down)
    monkeypatch.setattr(r_live_service, "collect_aapl_r_live", down)
    response = client.get(f"/api/v1.1/radar/r-live/{CID}")
    assert response.status_code == 200
    body = response.json()
    assert body["state"] == "UNAVAILABLE" and body["data"]["reason"] == "RADAR_AUTHORITY_UNAVAILABLE"
    assert "secret.example" not in response.text
    assert asyncio.run(_light_model_probe(occupied=False)) == "OK"
    assert client.get(VERIFY_URL).status_code == 200


def test_typesafe_provider_failure_does_not_touch_radar_or_model(monkeypatch):
    class Boom:
        def evaluate(self, request):
            raise RuntimeError("provider exploded")

    result = evaluate_intelligence(
        CID, config=JevIntelligenceConfig(mode=JevMode.VISIBLE), transport=Boom(),
        current_provider=lambda cid: ("UNAVAILABLE", {"reason": "X"}), environ={"FINCO_JEV_API_KEY": "k"})
    assert result.state.value == "UNAVAILABLE"
    assert asyncio.run(_light_model_probe(occupied=False)) == "OK"


def test_health_and_verify_stay_responsive_during_model_saturation(client):
    occupant = _Occupy(_executor(1))
    try:
        _lightweight_ok(client)
    finally:
        occupant.release()


def test_bounded_load_harness_cases_a_b_c_pass():
    proc = subprocess.run([sys.executable, str(ROOT / "tools/load_p0_gate.py")], capture_output=True,
                          text=True, timeout=120, cwd=str(ROOT))
    assert proc.returncode == 0, proc.stdout[-800:] + proc.stderr[-400:]
    assert '"ok": true' in proc.stdout


def test_observability_carries_no_secrets_or_urls():
    executor = me.ModelExecutor(me.ModelExecutionConfig(1, "thread", 30))
    stats = executor.stats()
    assert set(stats) >= {"scope", "mode", "concurrency", "active"}
    assert stats["scope"] == "PROCESS_LOCAL"
    text = str(stats).lower()
    assert "http" not in text and "secret" not in text and "key" not in text
