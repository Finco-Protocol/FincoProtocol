"""R-LIVE batch acquisition and public-route regression tests.

A-Q preserve the PR #141 canonical batch/authority contract. Opus H-7 public
admission, coalescing, overload and process/worker bounds are covered separately
by ``test_opus_h7_public_acquisition.py`` because SERVICE_BUSY is operational and
must never be encoded as market UNAVAILABLE.
"""
from __future__ import annotations

import threading
import time
from datetime import datetime, timezone
from typing import Any
from unittest.mock import MagicMock, patch

import pytest

from finco_radar.authority.contracts import AuthoritySnapshot, AuthorityState
from finco_radar.authority.r_live_onchain import OnchainReferenceObservation
from finco_radar.authority.r_live_policy import APPROVED_BY_CANONICAL_ID
from finco_radar.assets.contracts import AssetKey
from finco_radar.assets.registry import RegistrySnapshot

from app.radar_rwa.r_live_service import (
    RLiveResult,
    _CURRENT_WORKERS,
    _format_freshness,
    collect_r_live_batch,
    format_r_live_result,
)


_APPROVED_IDS = list(APPROVED_BY_CANONICAL_ID)
_APPROVED_COUNT = len(_APPROVED_IDS)


def _fake_asset(key: AssetKey, uid: str) -> MagicMock:
    asset = MagicMock()
    asset.asset_uid = uid
    return asset


def _fake_registry(keys_present: list[AssetKey] | None = None) -> RegistrySnapshot:
    snap = MagicMock(spec=RegistrySnapshot)
    snap.source = "ROBINHOOD_STOCK_TOKEN_ASSETS_API"
    snap.observed_at = datetime.now(timezone.utc)
    if keys_present is not None:
        def _get_by_key(key):
            for check in keys_present:
                if check == key:
                    policy = APPROVED_BY_CANONICAL_ID.get(key.canonical_id)
                    if policy:
                        return _fake_asset(key, policy.economic_asset_uid)
            return None
        snap.get_by_key.side_effect = _get_by_key
    else:
        snap.get_by_key.return_value = None
    return snap


def _fake_r_live_result(canonical_id: str) -> RLiveResult:
    policy = APPROVED_BY_CANONICAL_ID[canonical_id]
    key = policy.asset_key
    onchain = OnchainReferenceObservation(
        state=AuthorityState.UNAVAILABLE,
        asset_key=key,
        registry_asset_uid=policy.economic_asset_uid,
        reason="TEST_FIXTURE",
    )
    authority = MagicMock(spec=AuthoritySnapshot)
    authority.token = MagicMock()
    authority.token.state = AuthorityState.UNAVAILABLE
    authority.token.price_usd_per_token = None
    authority.token.source = None
    authority.token.observed_at = None
    authority.token.reason = "TEST_FIXTURE"
    authority.underlying = MagicMock()
    authority.underlying.state = AuthorityState.UNAVAILABLE
    authority.underlying.price_usd_per_token = None
    authority.underlying.source = None
    authority.underlying.observed_at = None
    authority.underlying.reason = "TEST_FIXTURE"
    authority.premium = MagicMock()
    authority.premium.state = AuthorityState.UNAVAILABLE
    authority.premium.value_bps = None
    authority.premium.formula = None
    authority.premium.reason = "TEST_FIXTURE"
    authority.economic_asset_uid = policy.economic_asset_uid
    authority.canonical_token = key
    return RLiveResult(onchain=onchain, authority=authority, history_digest=None)


def _mock_adapter(snapshot: RegistrySnapshot | None = None) -> MagicMock:
    adapter = MagicMock()
    adapter.__enter__ = lambda s: s
    adapter.__exit__ = MagicMock(return_value=False)
    adapter.fetch_snapshot.return_value = snapshot if snapshot is not None else _fake_registry()
    adapter.fetch_bound_reference.side_effect = Exception("no underlying")
    return adapter


# A. One registry snapshot per canonical batch.
def test_A_registry_fetched_once_per_batch():
    fetch_count = [0]
    adapter = _mock_adapter()

    def fetch():
        fetch_count[0] += 1
        return _fake_registry()

    adapter.fetch_snapshot.side_effect = fetch
    with patch("app.radar_rwa.r_live_service.RobinhoodAssetRegistryAdapter", return_value=adapter), \
         patch("app.radar_rwa.r_live_service.compose_r_live",
               return_value=_fake_r_live_result(_APPROVED_IDS[0])):
        results = list(collect_r_live_batch(rpc_url="https://rpc.example.com/"))
    assert fetch_count[0] == 1
    assert len(results) == _APPROVED_COUNT


# B. Each exact identity still receives source-bound validation.
def test_B_per_asset_source_bound_reference_validation():
    calls: list[str] = []
    snapshot = _fake_registry([p.asset_key for p in APPROVED_BY_CANONICAL_ID.values()])
    adapter = _mock_adapter(snapshot)

    def bound_ref(registry, key):
        calls.append(key.canonical_id)
        raise Exception("no bound ref in test")

    adapter.fetch_bound_reference.side_effect = bound_ref
    with patch("app.radar_rwa.r_live_service.RobinhoodAssetRegistryAdapter", return_value=adapter), \
         patch("app.radar_rwa.r_live_service.compose_r_live",
               return_value=_fake_r_live_result(_APPROVED_IDS[0])):
        list(collect_r_live_batch(rpc_url="https://rpc.example.com/"))
    assert len(calls) == _APPROVED_COUNT
    assert set(calls) == set(_APPROVED_IDS)


# C. Batch identity remains exact/fail-closed.
def test_C_unknown_canonical_id_not_yielded():
    adapter = _mock_adapter()
    with patch("app.radar_rwa.r_live_service.RobinhoodAssetRegistryAdapter", return_value=adapter), \
         patch("app.radar_rwa.r_live_service.compose_r_live",
               return_value=_fake_r_live_result(_APPROVED_IDS[0])):
        results = list(collect_r_live_batch(rpc_url="https://rpc.example.com/"))
    assert {row[0] for row in results} == set(_APPROVED_IDS)
    assert "4663:0x0000000000000000000000000000000000000000" not in {row[0] for row in results}


# D. Registry failure never reuses hidden previous state.
def test_D_registry_failure_does_not_reuse_previous_state():
    adapter = _mock_adapter()
    adapter.fetch_snapshot.side_effect = Exception("REGISTRY_UNAVAILABLE")
    registries: list[Any] = []

    def capture(**kwargs):
        registries.append(kwargs.get("registry"))
        return _fake_r_live_result(kwargs["key"].canonical_id)

    with patch("app.radar_rwa.r_live_service.RobinhoodAssetRegistryAdapter", return_value=adapter), \
         patch("app.radar_rwa.r_live_service.compose_r_live", side_effect=capture):
        list(collect_r_live_batch(rpc_url="https://rpc.example.com/"))
    assert len(registries) == _APPROVED_COUNT
    assert all(registry is None for registry in registries)


# E. Public batch remains read-only / zero history writes.
def test_E_batch_performs_zero_history_writes():
    adapter = _mock_adapter()
    history_args: list[Any] = []

    def capture(**kwargs):
        history_args.append(kwargs.get("history"))
        return _fake_r_live_result(kwargs["key"].canonical_id)

    with patch("app.radar_rwa.r_live_service.RobinhoodAssetRegistryAdapter", return_value=adapter), \
         patch("app.radar_rwa.r_live_service.compose_r_live", side_effect=capture):
        list(collect_r_live_batch(rpc_url="https://rpc.example.com/"))
    assert len(history_args) == _APPROVED_COUNT
    assert all(value is None for value in history_args)


# F. Shared RPC transport closes on both success and failure paths.
@pytest.mark.parametrize("raise_compose", [False, True])
def test_F_shared_rpc_client_closed_on_success_and_failure(raise_compose):
    import httpx

    closed = [0]
    original_close = httpx.Client.close

    def counted_close(self):
        closed[0] += 1
        return original_close(self)

    adapter = _mock_adapter()
    compose = (MagicMock(side_effect=Exception("rpc down")) if raise_compose
               else MagicMock(return_value=_fake_r_live_result(_APPROVED_IDS[0])))
    with patch.object(httpx.Client, "close", counted_close), \
         patch("app.radar_rwa.r_live_service.RobinhoodAssetRegistryAdapter", return_value=adapter), \
         patch("app.radar_rwa.r_live_service.compose_r_live", compose):
        results = list(collect_r_live_batch(rpc_url="https://rpc.example.com/"))
    assert closed[0] >= 1
    if raise_compose:
        assert all(state == "UNAVAILABLE" for _, state, _ in results)


# G. One asset exception cannot abort unrelated assets.
def test_G_per_asset_exception_does_not_abort_batch():
    if _APPROVED_COUNT < 2:
        pytest.skip("needs at least 2 approved assets")
    target = _APPROVED_IDS[0]
    adapter = _mock_adapter()

    def selective(**kwargs):
        canonical_id = kwargs["key"].canonical_id
        if canonical_id == target:
            raise Exception("SIMULATED_ASSET_FAILURE")
        return _fake_r_live_result(canonical_id)

    with patch("app.radar_rwa.r_live_service.RobinhoodAssetRegistryAdapter", return_value=adapter), \
         patch("app.radar_rwa.r_live_service.compose_r_live", side_effect=selective):
        results = list(collect_r_live_batch(rpc_url="https://rpc.example.com/"))
    assert len(results) == _APPROVED_COUNT
    failed = [row for row in results if row[0] == target]
    assert len(failed) == 1 and failed[0][1] == "UNAVAILABLE"


# H. Batch remains completion-order, not registry-order.
def test_H_streaming_is_completion_order_not_registry_order():
    if _APPROVED_COUNT < 2:
        pytest.skip("needs at least 2 approved assets")
    slow_id = _APPROVED_IDS[0]
    fast_id = _APPROVED_IDS[-1]
    adapter = _mock_adapter()

    def timed(**kwargs):
        canonical_id = kwargs["key"].canonical_id
        if canonical_id == slow_id:
            time.sleep(0.08)
        return _fake_r_live_result(canonical_id)

    with patch("app.radar_rwa.r_live_service.RobinhoodAssetRegistryAdapter", return_value=adapter), \
         patch("app.radar_rwa.r_live_service.compose_r_live", side_effect=timed):
        rows = list(collect_r_live_batch(
            rpc_url="https://rpc.example.com/", workers=min(_APPROVED_COUNT, 4)
        ))
    order = [row[0] for row in rows]
    assert order.index(fast_id) < order.index(slow_id)


# I. Asset-level executor concurrency remains bounded.
def test_I_concurrency_never_exceeds_worker_bound():
    current = [0]
    maximum = [0]
    lock = threading.Lock()
    adapter = _mock_adapter()

    def track(**kwargs):
        with lock:
            current[0] += 1
            maximum[0] = max(maximum[0], current[0])
        time.sleep(0.01)
        with lock:
            current[0] -= 1
        return _fake_r_live_result(kwargs["key"].canonical_id)

    with patch("app.radar_rwa.r_live_service.RobinhoodAssetRegistryAdapter", return_value=adapter), \
         patch("app.radar_rwa.r_live_service.compose_r_live", side_effect=track):
        list(collect_r_live_batch(rpc_url="https://rpc.example.com/", workers=2))
    assert maximum[0] <= 2


def test_I_invalid_worker_count_raises():
    with pytest.raises(ValueError, match="BATCH_WORKERS_OUT_OF_RANGE"):
        list(collect_r_live_batch(rpc_url="https://rpc.example.com/", workers=0))
    with pytest.raises(ValueError, match="BATCH_WORKERS_OUT_OF_RANGE"):
        list(collect_r_live_batch(rpc_url="https://rpc.example.com/", workers=5))


# J. Canonical service itself still has no completed current-value cache.
def test_J_two_batch_calls_produce_independent_registry_fetches():
    calls = [0]
    adapter = _mock_adapter()

    def fetch():
        calls[0] += 1
        return _fake_registry()

    adapter.fetch_snapshot.side_effect = fetch
    with patch("app.radar_rwa.r_live_service.RobinhoodAssetRegistryAdapter", return_value=adapter), \
         patch("app.radar_rwa.r_live_service.compose_r_live",
               return_value=_fake_r_live_result(_APPROVED_IDS[0])):
        list(collect_r_live_batch(rpc_url="https://rpc.example.com/"))
        list(collect_r_live_batch(rpc_url="https://rpc.example.com/"))
    assert calls[0] == 2


# K. Batch arguments remain identical to the canonical single-asset contract.
def test_K_batch_compose_args_match_single_asset_contract():
    snapshot = _fake_registry([p.asset_key for p in APPROVED_BY_CANONICAL_ID.values()])
    adapter = _mock_adapter(snapshot)
    compose_calls: list[dict] = []

    def capture(**kwargs):
        compose_calls.append({
            "registry": kwargs.get("registry"),
            "key": kwargs.get("key"),
            "history": kwargs.get("history"),
        })
        return _fake_r_live_result(kwargs["key"].canonical_id)

    with patch("app.radar_rwa.r_live_service.RobinhoodAssetRegistryAdapter", return_value=adapter), \
         patch("app.radar_rwa.r_live_service.compose_r_live", side_effect=capture):
        list(collect_r_live_batch(rpc_url="https://rpc.example.com/"))
    assert len(compose_calls) == _APPROVED_COUNT
    assert all(item["registry"] is snapshot for item in compose_calls)
    assert all(item["key"].canonical_id in APPROVED_BY_CANONICAL_ID for item in compose_calls)
    assert all(item["history"] is None for item in compose_calls)


def test_format_r_live_result_unknown_canonical_id():
    state, data = format_r_live_result(
        "4663:0x0000000000000000000000000000000000000bad",
        _fake_r_live_result(_APPROVED_IDS[0]),
    )
    assert state == "UNAVAILABLE"
    assert data["reason"] == "ASSET_UID_INVALID"


def test_format_r_live_result_unavailable_state():
    canonical_id = _APPROVED_IDS[0]
    state, data = format_r_live_result(canonical_id, _fake_r_live_result(canonical_id))
    assert state == "UNAVAILABLE"
    assert data["exact_asset_key"]["canonical_id"] == canonical_id
    assert data["token_reference"]["price_usd_per_token"] is None
    assert data["robinhood_basis"]["price_usd_per_token"] is None
    assert data["b1_0_premium"]["value_bps"] is None


def test_current_workers_default_value():
    assert _CURRENT_WORKERS == 2


def _make_test_app():
    from fastapi import FastAPI
    from app.api.v1_1.r_live_public_router import router
    app = FastAPI()
    app.include_router(router)
    return app


def test_current_endpoint_rpc_not_configured(monkeypatch):
    monkeypatch.delenv("ROBINHOOD_RPC_URL", raising=False)
    from fastapi.testclient import TestClient
    response = TestClient(_make_test_app()).get("/radar/r-live/current")
    assert response.status_code == 200
    assert response.json()["state"] == "UNAVAILABLE"
    assert response.json()["data"]["reason"] == "RPC_NOT_CONFIGURED"
    assert response.headers["cache-control"] == "no-store"


def test_current_endpoint_streams_ndjson(monkeypatch):
    monkeypatch.setenv("ROBINHOOD_RPC_URL", "https://rpc.example.com/")
    adapter = _mock_adapter()

    def compose(**kwargs):
        return _fake_r_live_result(kwargs["key"].canonical_id)

    from fastapi.testclient import TestClient
    with patch("app.radar_rwa.r_live_service.RobinhoodAssetRegistryAdapter", return_value=adapter), \
         patch("app.radar_rwa.r_live_service.compose_r_live", side_effect=compose):
        response = TestClient(_make_test_app()).get("/radar/r-live/current")
    assert response.status_code == 200
    assert response.headers["cache-control"] == "no-store"
    import json
    rows = [json.loads(line) for line in response.text.splitlines() if line.strip()]
    assert len(rows) == _APPROVED_COUNT
    assert all(row["canonical_id"] in APPROVED_BY_CANONICAL_ID for row in rows)
    assert all("display_symbol" in row and "state" in row for row in rows)


def test_current_endpoint_no_cache_header(monkeypatch):
    monkeypatch.delenv("ROBINHOOD_RPC_URL", raising=False)
    from fastapi.testclient import TestClient
    response = TestClient(_make_test_app()).get("/radar/r-live/current")
    assert response.headers["cache-control"] == "no-store"


# L. Route set remains the PR #141 public families plus the instant-UX
# snapshot read family (read-only projection; never triggers acquisition).
def test_L_exactly_seven_route_families():
    from app.api.v1_1.r_live_public_router import router
    paths = {route.path for route in router.routes}
    assert paths == {
        "/radar/r-live/assets",
        "/radar/r-live/current",
        "/radar/r-live/snapshot",
        "/radar/r-live/history/ranges",
        "/radar/r-live/{uid}/history",
        "/radar/r-live/{uid}/history/ranges",
        "/radar/r-live/{uid}",
    }


# M. Exact UID range route remains present and fail-closed.
def test_M_uid_history_ranges_route_present():
    from fastapi.testclient import TestClient
    with patch("app.radar_rwa.r_live_service.read_r_live_ranges",
               side_effect=ValueError("R_LIVE_EXACT_ASSETKEY_NOT_APPROVED")):
        response = TestClient(_make_test_app()).get(
            "/radar/r-live/UNKNOWN_UID/history/ranges"
        )
    assert response.status_code == 200
    assert response.json()["state"] == "UNAVAILABLE"
    assert response.json()["data"]["reason"] == "ASSET_UID_INVALID"


def test_M_uid_history_ranges_returns_available_for_approved():
    canonical = {
        "range_1h": {"state": "AVAILABLE", "low_bps": "-5.0", "high_bps": "10.0",
                     "observation_count": 5},
        "range_24h": {"state": "AVAILABLE", "low_bps": "-20.0", "high_bps": "30.0",
                      "observation_count": 20},
        "last_available": None,
    }
    from fastapi.testclient import TestClient
    with patch("app.radar_rwa.r_live_service.read_r_live_ranges", return_value=canonical):
        response = TestClient(_make_test_app()).get(
            f"/radar/r-live/{_APPROVED_IDS[0]}/history/ranges"
        )
    assert response.json()["state"] == "AVAILABLE"
    assert response.json()["data"]["history_kind"] == "HISTORICAL"


# N. Bulk history range stays on canonical collected_at authority.
def test_N_bulk_ranges_delegates_to_canonical_read_r_live_ranges():
    calls: list[str] = []
    canonical = {
        "range_1h": {"state": "AVAILABLE", "low_bps": "0.0", "high_bps": "1.0",
                     "observation_count": 3},
        "range_24h": {"state": "AVAILABLE", "low_bps": "-1.0", "high_bps": "2.0",
                      "observation_count": 10},
        "last_available": None,
    }

    def read(canonical_id, **kwargs):
        calls.append(canonical_id)
        return canonical

    from fastapi.testclient import TestClient
    with patch("app.radar_rwa.r_live_service.read_r_live_ranges", side_effect=read):
        response = TestClient(_make_test_app()).get("/radar/r-live/history/ranges")
    assert set(calls) == set(_APPROVED_IDS)
    assert response.json()["state"] == "AVAILABLE"
    assert response.headers["cache-control"] == "no-store"


# O. Per-asset and bulk ranges call the same canonical service function.
def test_O_per_asset_and_bulk_ranges_use_same_function():
    canonical = {"range_1h": None, "range_24h": None, "last_available": None}
    from fastapi.testclient import TestClient
    with patch("app.radar_rwa.r_live_service.read_r_live_ranges", return_value=canonical) as one:
        TestClient(_make_test_app()).get(
            f"/radar/r-live/{_APPROVED_IDS[0]}/history/ranges"
        )
        assert one.call_count == 1
    with patch("app.radar_rwa.r_live_service.read_r_live_ranges", return_value=canonical) as bulk:
        TestClient(_make_test_app()).get("/radar/r-live/history/ranges")
        assert bulk.call_count == _APPROVED_COUNT


# P. Presentation exposes freshness fields without changing source clocks.
def test_P_format_r_live_result_includes_freshness():
    _, data = format_r_live_result(_APPROVED_IDS[0], _fake_r_live_result(_APPROVED_IDS[0]))
    assert "freshness" in data
    assert "market_activity_age_seconds" in data["freshness"]
    assert "quote_feed_age_seconds" in data["freshness"]


# Q. Market activity and oracle freshness remain independent clocks.
def test_Q_freshness_market_and_oracle_are_independent():
    from datetime import timedelta
    retrieved = datetime.now(timezone.utc)
    result = _format_freshness({
        "lastPoolActivityAt": (retrieved - timedelta(seconds=120)).isoformat(),
        "quoteUpdatedAt": (retrieved - timedelta(seconds=45)).isoformat(),
        "retrievedAt": retrieved.isoformat(),
    })
    assert result["market_activity_age_seconds"] == 120
    assert result["quote_feed_age_seconds"] == 45
    assert result["market_activity_age_seconds"] != result["quote_feed_age_seconds"]
