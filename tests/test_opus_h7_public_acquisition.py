"""Opus H-7 — bounded public R-LIVE acquisition/backpressure tests.

These tests exercise the operational wrapper only. Canonical market authority
math remains covered by the existing R-LIVE suites.
"""
from __future__ import annotations

import json
import threading
import time
from datetime import datetime, timezone

import pytest

from app.radar_rwa.r_live_public_acquisition import (
    CURRENT_CACHE,
    EFFECTIVE_HOST_MAX,
    MAX_COALESCED_CALLERS,
    PER_CLIENT_RATE_LIMIT,
    PROCESS_ACQUISITION_LIMIT,
    PUBLIC_RLIVE_ACQUISITION,
    R_LIVE_SERVICE_BUSY,
    RLiveBatchAcquisitionFailed,
    RLiveServiceBusy,
    WEB_WORKERS,
    PublicAcquisitionCoordinator,
)


def _wait_until(predicate, timeout: float = 2.0) -> None:
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        if predicate():
            return
        time.sleep(0.005)
    raise AssertionError("condition not reached before timeout")


def test_h7_20_identical_callers_coalesce_to_one_upstream_batch():
    coordinator = PublicAcquisitionCoordinator[dict](
        process_limit=2,
        max_coalesced_callers=32,
    )
    started = threading.Event()
    release = threading.Event()
    producer_calls = [0]
    original_timestamp = datetime(2026, 9, 29, 20, 0, tzinfo=timezone.utc).isoformat()

    def producer():
        producer_calls[0] += 1
        started.set()
        assert release.wait(timeout=2)
        yield {"canonical_id": "4663:0xabc", "observed_at": original_timestamp}

    first = coordinator.subscribe("same-current", producer)
    assert started.wait(timeout=1)
    subscriptions = [first]
    for _ in range(19):
        subscriptions.append(coordinator.subscribe("same-current", producer))

    assert producer_calls[0] == 1
    assert coordinator.active_expensive_acquisitions == 1
    release.set()

    results = [list(subscription) for subscription in subscriptions]
    assert producer_calls[0] == 1
    assert all(rows == [{"canonical_id": "4663:0xabc", "observed_at": original_timestamp}]
               for rows in results)
    _wait_until(lambda: coordinator.active_expensive_acquisitions == 0)
    assert coordinator.in_flight_key_count == 0


def test_h7_process_bound_rejects_distinct_work_without_queueing():
    coordinator = PublicAcquisitionCoordinator[int](
        process_limit=2,
        max_coalesced_callers=32,
    )
    release = threading.Event()
    started = [threading.Event(), threading.Event()]
    producer_calls = [0]

    def producer(index: int):
        def _producer():
            producer_calls[0] += 1
            started[index].set()
            assert release.wait(timeout=2)
            yield index
        return _producer

    subscriptions = [
        coordinator.subscribe("a", producer(0)),
        coordinator.subscribe("b", producer(1)),
    ]
    assert started[0].wait(timeout=1)
    assert started[1].wait(timeout=1)
    assert coordinator.active_expensive_acquisitions == 2

    rejected = 0
    before = time.monotonic()
    for index in range(18):
        with pytest.raises(RLiveServiceBusy) as exc:
            coordinator.subscribe(f"extra-{index}", lambda: iter((index,)))
        assert exc.value.reason == R_LIVE_SERVICE_BUSY
        rejected += 1
    elapsed = time.monotonic() - before

    assert rejected == 18
    assert producer_calls[0] == 2
    assert coordinator.active_expensive_acquisitions <= coordinator.process_limit
    assert elapsed < 1.0, "overload admission must fail quickly rather than queue indefinitely"

    release.set()
    for subscription in subscriptions:
        list(subscription)
    _wait_until(lambda: coordinator.active_expensive_acquisitions == 0)


def test_h7_coalesced_subscriber_bound_is_finite():
    coordinator = PublicAcquisitionCoordinator[int](
        process_limit=1,
        max_coalesced_callers=2,
    )
    release = threading.Event()
    started = threading.Event()

    def producer():
        started.set()
        assert release.wait(timeout=2)
        yield 1

    first = coordinator.subscribe("same", producer)
    assert started.wait(timeout=1)
    second = coordinator.subscribe("same", producer)
    with pytest.raises(RLiveServiceBusy):
        coordinator.subscribe("same", producer)

    release.set()
    assert list(first) == [1]
    assert list(second) == [1]


def test_h7_exception_cleans_key_and_slot_and_next_request_can_run():
    coordinator = PublicAcquisitionCoordinator[int](
        process_limit=1,
        max_coalesced_callers=4,
    )

    def broken():
        raise RuntimeError("secret upstream exception")
        yield 1

    subscription = coordinator.subscribe("key", broken)
    with pytest.raises(RLiveBatchAcquisitionFailed, match="R_LIVE_BATCH_ACQUISITION_FAILED"):
        list(subscription)
    _wait_until(lambda: coordinator.active_expensive_acquisitions == 0)
    assert coordinator.in_flight_key_count == 0

    healthy = coordinator.subscribe("key", lambda: iter((2,)))
    assert list(healthy) == [2]
    _wait_until(lambda: coordinator.active_expensive_acquisitions == 0)


def test_h7_disconnect_cleanup_does_not_poison_future_request():
    coordinator = PublicAcquisitionCoordinator[int](
        process_limit=1,
        max_coalesced_callers=4,
    )
    release = threading.Event()
    started = threading.Event()

    def producer():
        started.set()
        assert release.wait(timeout=2)
        yield 1
        yield 2

    abandoned = coordinator.subscribe("key", producer)
    assert started.wait(timeout=1)
    abandoned.close()
    release.set()
    _wait_until(lambda: coordinator.active_expensive_acquisitions == 0)
    assert coordinator.in_flight_key_count == 0

    replacement = coordinator.subscribe("key", lambda: iter((3,)))
    assert list(replacement) == [3]


def test_h7_completed_result_is_not_cached_or_retimestamped():
    coordinator = PublicAcquisitionCoordinator[dict](
        process_limit=1,
        max_coalesced_callers=4,
    )
    calls = [0]
    timestamps = [
        "2026-09-29T20:00:00+00:00",
        "2026-09-29T20:10:00+00:00",
    ]

    def producer():
        value = timestamps[calls[0]]
        calls[0] += 1
        yield {
            "observed_at": value,
            "collected_at": value,
            "effective_evidence_at": value,
            "block_timestamp": value,
            "quote_updated_at": value,
            "last_pool_activity_at": value,
        }

    first = list(coordinator.subscribe("same", producer))
    _wait_until(lambda: coordinator.active_expensive_acquisitions == 0)
    second = list(coordinator.subscribe("same", producer))

    assert calls[0] == 2, "completed current batches must not become an operational cache"
    assert first[0]["observed_at"] == timestamps[0]
    assert second[0]["observed_at"] == timestamps[1]
    assert first[0]["effective_evidence_at"] == timestamps[0]
    assert second[0]["effective_evidence_at"] == timestamps[1]
    assert CURRENT_CACHE == "NONE"


def test_h7_worker_multiplication_is_explicit_and_process_local():
    assert PROCESS_ACQUISITION_LIMIT >= 1
    assert WEB_WORKERS >= 1
    assert EFFECTIVE_HOST_MAX == PROCESS_ACQUISITION_LIMIT * WEB_WORKERS
    assert MAX_COALESCED_CALLERS >= 20
    assert PER_CLIENT_RATE_LIMIT == "NOT_IMPLEMENTED"


def test_h7_public_route_returns_429_service_busy_not_market_unavailable(monkeypatch):
    monkeypatch.setenv("ROBINHOOD_RPC_URL", "https://rpc.example.com/")
    from fastapi import FastAPI
    from fastapi.testclient import TestClient
    from app.api.v1_1.r_live_public_router import router

    drained = []
    while PUBLIC_RLIVE_ACQUISITION._gate.acquire(blocking=False):
        drained.append(True)
    try:
        app = FastAPI()
        app.include_router(router)
        response = TestClient(app).get("/radar/r-live/current")
    finally:
        for _ in drained:
            PUBLIC_RLIVE_ACQUISITION._gate.release()

    assert response.status_code == 429
    assert response.headers.get("cache-control") == "no-store"
    body = response.json()
    assert body == {"state": "SERVICE_BUSY", "reason": R_LIVE_SERVICE_BUSY}
    assert body["state"] != "UNAVAILABLE"


def test_h7_public_current_still_streams_completion_rows_without_history_cache(monkeypatch):
    monkeypatch.setenv("ROBINHOOD_RPC_URL", "https://rpc.example.com/")
    from fastapi import FastAPI
    from fastapi.testclient import TestClient
    from app.api.v1_1.r_live_public_router import router
    from finco_radar.authority.r_live_policy import APPROVED_BY_CANONICAL_ID

    canonical_id = next(iter(APPROVED_BY_CANONICAL_ID))
    calls = [0]
    source_timestamp = "2026-09-29T20:00:00+00:00"

    def fake_batch(*, rpc_url):
        calls[0] += 1
        assert rpc_url == "https://rpc.example.com/"
        yield canonical_id, "STALE", {
            "observed_at": source_timestamp,
            "freshness": {"effective_evidence_at": source_timestamp},
        }

    app = FastAPI()
    app.include_router(router)
    client = TestClient(app)

    from unittest.mock import patch
    with patch("app.radar_rwa.r_live_service.collect_r_live_batch", side_effect=fake_batch):
        response = client.get("/radar/r-live/current")
        response2 = client.get("/radar/r-live/current")

    assert response.status_code == 200
    assert response.headers.get("cache-control") == "no-store"
    row = json.loads(response.text.strip())
    row2 = json.loads(response2.text.strip())
    assert row["state"] == "STALE"
    assert row["data"]["observed_at"] == source_timestamp
    assert row2["data"]["observed_at"] == source_timestamp
    assert calls[0] == 2, "sequential requests must perform independent current batches"
