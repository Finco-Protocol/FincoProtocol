"""Post-R12 P2 Correction — N03 ASGI event-loop responsiveness proof.

Exercises the REAL ``main_web.app`` ASGI stack with concurrent async
requests: a ~600 ms Radar refresh must NOT block a lightweight heartbeat
route.

Methodology (Correction A / section 9): the heartbeat's start timestamp
is captured BEFORE either request can block the event loop — both tasks
are created back-to-back and latency is measured end-to-end from that
pre-dispatch timestamp, so any event-loop blocking caused by the refresh
is INCLUDED in the heartbeat latency.

Sensitivity control: the same measurement against a deliberately
blocking ASGI route must show starvation (heartbeat latency >= the
blocking duration), proving this harness fails against the previous
direct ``get_service().acquire(...)`` implementation.

Deterministic offline; no live external network.
"""
from __future__ import annotations

import asyncio
import re
import time
from datetime import datetime, timezone

import httpx
import pytest

pytest.importorskip("httpx")

from app.radar_runtime.service import AcquisitionService, ServiceConfig
from app.radar_runtime.snapshot_store import SnapshotStore

NOW = datetime(2026, 9, 19, 12, 0, tzinfo=timezone.utc)

PROVIDER_DURATION = 0.6      # fake provider blocks its worker for 0.6 s
HEARTBEAT_THRESHOLD = 0.30   # heartbeat must finish well before that


def _fake_core(calls: list):
    def provider(request):
        calls.append(request)
        time.sleep(PROVIDER_DURATION)
        return {"evidence": {"price": "101.25"}, "observedAt":
                "2026-09-19T12:00:00+00:00"}
    return provider


@pytest.fixture
def wired_client(monkeypatch):
    from app.radar_ui import router as radar_router_module

    calls: list = []
    service = AcquisitionService(
        SnapshotStore(":memory:"), {"radar-core": _fake_core(calls)},
        config=ServiceConfig(per_provider_timeout_seconds=5.0,
                             total_budget_seconds=10.0,
                             max_concurrent_providers=2),
        clock=lambda: NOW)
    radar_router_module.set_service(service)
    monkeypatch.setenv("RADAR_V1_ASSET_UID", "AAPL")
    monkeypatch.setenv("RADAR_V1_ASSET_ADDRESS",
                       "0xaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaa")
    yield calls
    # section 10 test hygiene: release the service-owned executor and
    # reset the globally injected Radar service
    service.close()
    radar_router_module.set_service(None)


@pytest.mark.anyio
async def test_n03_refresh_offload_keeps_event_loop_responsive(
    wired_client):
    calls = wired_client
    from main_web import app  # the REAL product ASGI app

    transport = httpx.ASGITransport(app=app)
    limits = httpx.Limits(max_connections=10)
    async with httpx.AsyncClient(transport=transport,
                                 base_url="http://testserver",
                                 limits=limits) as client:
        # section 9 corrected methodology: t0 is captured BEFORE either
        # request can block the loop; the heartbeat latency therefore
        # includes any event-loop scheduling delay caused by the refresh.
        t0 = time.monotonic()
        refresh_task = asyncio.create_task(client.post(
            "/radar/refresh", data={"direction": "BUY", "size": "100"},
            headers={"HX-Request": "true"}))
        heartbeat_task = asyncio.create_task(client.get("/radar"))
        heartbeat = await heartbeat_task
        heartbeat_latency = time.monotonic() - t0
        refresh = await refresh_task

    assert heartbeat.status_code == 200
    assert refresh.status_code == 200
    # the heartbeat completed materially before the provider finished,
    # measured end-to-end from the pre-dispatch timestamp
    assert heartbeat_latency < HEARTBEAT_THRESHOLD, (
        f"event loop starved: heartbeat latency {heartbeat_latency:.3f}s "
        f">= threshold {HEARTBEAT_THRESHOLD}s")
    # exactly one acquisition, exactly one snapshot_id
    assert len(calls) == 1
    snapshot_ids = re.findall(r"acq-snap:[0-9a-f]{64}", refresh.text)
    assert snapshot_ids and len(set(snapshot_ids)) == 1


@pytest.mark.anyio
async def test_n03_harness_detects_blocking_route():
    """Sensitivity control: the SAME measurement against a deliberately
    event-loop-blocking route must show starvation.  This proves the
    corrected heartbeat test would FAIL against the previous direct
    ``get_service().acquire(...)`` implementation."""
    from fastapi import FastAPI

    blocking_app = FastAPI()

    @blocking_app.get("/block")
    async def block():
        time.sleep(PROVIDER_DURATION)  # blocks the event loop
        return {"ok": True}

    @blocking_app.get("/heartbeat")
    async def heartbeat_route():
        return {"ok": True}

    transport = httpx.ASGITransport(app=blocking_app)
    async with httpx.AsyncClient(transport=transport,
                                 base_url="http://testserver") as client:
        t0 = time.monotonic()
        block_task = asyncio.create_task(client.get("/block"))
        heartbeat_task = asyncio.create_task(client.get("/heartbeat"))
        heartbeat = await heartbeat_task
        heartbeat_latency = time.monotonic() - t0
        blocked = await block_task

    assert blocked.status_code == 200
    assert heartbeat.status_code == 200
    # the heartbeat could not even be dispatched until the blocking
    # handler finished — the harness detects event-loop starvation
    assert heartbeat_latency >= PROVIDER_DURATION * 0.8, (
        "harness sensitivity lost: blocking route was not detected "
        f"(heartbeat latency {heartbeat_latency:.3f}s)")
