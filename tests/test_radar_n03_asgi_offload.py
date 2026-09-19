"""Post-R12 P2 Correction — N03 ASGI event-loop responsiveness proof.

Exercises the REAL ``main_web.app`` ASGI stack with concurrent async
requests: a ~600 ms Radar refresh must NOT block a lightweight heartbeat
route.  Against the previous direct blocking implementation the
heartbeat latency was >= the provider duration (the event loop was
starved), so this test fails on the old code and passes with
``run_in_threadpool`` offload.
"""
from __future__ import annotations

import asyncio
import re
import time
from datetime import datetime, timezone

import httpx
import pytest
import time

pytest.importorskip("httpx")

from app.radar_runtime.service import AcquisitionService, ServiceConfig
from app.radar_runtime.snapshot_store import SnapshotStore

NOW = datetime(2026, 9, 19, 12, 0, tzinfo=timezone.utc)

PROVIDER_DURATION = 0.6      # fake provider blocks the worker for 0.6 s
HEARTBEAT_DEADLINE = 0.30    # heartbeat must finish well before that


def _fake_core(calls: list):
    def provider(request):
        calls.append(request)
        time.sleep(PROVIDER_DURATION)
        return {"evidence": {"price": "101.25"}, "observedAt":
                "2026-09-19T12:00:00+00:00"}
    return provider


@pytest.fixture
def wired_client():
    from app.radar_ui import router as radar_router_module

    calls: list = []
    service = AcquisitionService(
        SnapshotStore(":memory:"), {"radar-core": _fake_core(calls)},
        config=ServiceConfig(per_provider_timeout_seconds=5.0,
                             total_budget_seconds=10.0,
                             max_concurrent_providers=2),
        clock=lambda: NOW)
    radar_router_module.set_service(service)
    yield calls


@pytest.mark.anyio
async def test_n03_refresh_offload_keeps_event_loop_responsive(
    wired_client, monkeypatch):
    calls = wired_client
    monkeypatch.setenv("RADAR_V1_ASSET_UID", "AAPL")
    monkeypatch.setenv("RADAR_V1_ASSET_ADDRESS",
                       "0xaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaa")

    from main_web import app  # the REAL product ASGI app

    transport = httpx.ASGITransport(app=app)
    limits = httpx.Limits(max_connections=10)
    async with httpx.AsyncClient(transport=transport,
                                 base_url="http://testserver",
                                 limits=limits) as client:
        refresh_task = asyncio.create_task(client.post(
            "/radar/refresh", data={"direction": "BUY", "size": "100"},
            headers={"HX-Request": "true"}))
        await asyncio.sleep(0.05)  # refresh is now inside its provider call
        heartbeat_started = time.monotonic()
        heartbeat = await client.get("/radar")
        heartbeat_latency = time.monotonic() - heartbeat_started
        refresh = await refresh_task

    assert heartbeat.status_code == 200
    assert refresh.status_code == 200
    # the heartbeat completed materially before the provider finished
    assert heartbeat_latency < PROVIDER_DURATION * 0.5, (
        f"event loop starved: heartbeat latency {heartbeat_latency:.3f}s "
        f">= half the provider duration")
    # exactly one acquisition, exactly one snapshot_id
    assert len(calls) == 1
    snapshot_ids = re.findall(r"acq-snap:[0-9a-f]{64}", refresh.text)
    assert snapshot_ids and len(set(snapshot_ids)) == 1
