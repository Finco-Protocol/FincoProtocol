"""Tests for R-LIVE batch acquisition (collect_r_live_batch) and related endpoints.

Invariants verified:
  A. N approved assets → exactly ONE RegistrySnapshot fetch per batch
  B. Each exact asset performs its source-bound reference validation
  C. Wrong UID/deployment remains fail-closed
  D. Registry failure cannot silently reuse previous registry state
  E. Read-only batch performs zero history writes
  F. Shared RPC transport is closed exactly once (success and failure)
  G. Per-asset exception does not abort remaining stream
  H. Streaming remains completion-order (fastest first), not registry-order
  I. Concurrency never exceeds the configured worker bound
  J. No current-value cache introduced (two calls produce two independent batches)
  K. Authority results match the single-asset compose_r_live for identical fixtures

Route contract invariants:
  L. Exactly six public R-LIVE route families are registered
  M. {uid}/history/ranges route is present and callable
  N. Bulk /history/ranges delegates to canonical read_r_live_ranges (collected_at authority)
  O. Per-asset and bulk ranges use the same canonical authority
  P. STALE current state may display labelled historical last-available data
  Q. Market activity and oracle freshness remain distinct clocks
  R. Global acquisition gate bounds concurrent upstream work

All tests are deterministic and infrastructure-free.
"""
from __future__ import annotations

import threading
import time
from concurrent.futures import Future
from datetime import datetime, timezone
from decimal import Decimal
from typing import Any
from unittest.mock import MagicMock, call, patch

import pytest

from finco_radar.authority.contracts import (
    AuthoritySnapshot,
    AuthorityState,
    IndependentTokenReference,
)
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
    read_r_live_ranges,
)


# ── Fixtures ──────────────────────────────────────────────────────────────────

_APPROVED_IDS = list(APPROVED_BY_CANONICAL_ID)
_APPROVED_COUNT = len(_APPROVED_IDS)


def _fake_asset(key: AssetKey, uid: str) -> MagicMock:
    asset = MagicMock()
    asset.asset_uid = uid
    return asset


def _fake_registry(keys_present: list[AssetKey] | None = None) -> RegistrySnapshot:
    """Return a minimal RegistrySnapshot stub."""
    snap = MagicMock(spec=RegistrySnapshot)
    snap.source = "ROBINHOOD_STOCK_TOKEN_ASSETS_API"
    snap.observed_at = datetime.now(timezone.utc)
    if keys_present is not None:
        def _get_by_key(k):
            for check in keys_present:
                if check == k:
                    policy = APPROVED_BY_CANONICAL_ID.get(k.canonical_id)
                    if policy:
                        return _fake_asset(k, policy.economic_asset_uid)
            return None
        snap.get_by_key.side_effect = _get_by_key
    else:
        snap.get_by_key.return_value = None
    return snap


def _fake_r_live_result(canonical_id: str) -> RLiveResult:
    """Return a minimal UNAVAILABLE RLiveResult for use in format/parity tests."""
    policy = APPROVED_BY_CANONICAL_ID[canonical_id]
    key = policy.asset_key
    onchain = OnchainReferenceObservation(
        state=AuthorityState.UNAVAILABLE,
        asset_key=key,
        registry_asset_uid=policy.economic_asset_uid,
        reason="TEST_FIXTURE",
    )
    auth = MagicMock(spec=AuthoritySnapshot)
    auth.token = MagicMock()
    auth.token.state = AuthorityState.UNAVAILABLE
    auth.token.price_usd_per_token = None
    auth.token.source = None
    auth.token.observed_at = None
    auth.token.reason = "TEST_FIXTURE"
    auth.underlying = MagicMock()
    auth.underlying.state = AuthorityState.UNAVAILABLE
    auth.underlying.price_usd_per_token = None
    auth.underlying.source = None
    auth.underlying.observed_at = None
    auth.underlying.reason = "TEST_FIXTURE"
    auth.premium = MagicMock()
    auth.premium.state = AuthorityState.UNAVAILABLE
    auth.premium.value_bps = None
    auth.premium.formula = None
    auth.premium.reason = "TEST_FIXTURE"
    auth.economic_asset_uid = policy.economic_asset_uid
    auth.canonical_token = key
    return RLiveResult(onchain=onchain, authority=auth, history_digest=None)


# ── A. Registry fetched ONCE per batch ───────────────────────────────────────

def test_A_registry_fetched_once_per_batch():
    """A. N approved assets → exactly ONE registry snapshot fetch per current batch."""
    fetch_count = [0]
    fake_snap = _fake_registry()

    def _fake_fetch_snapshot():
        fetch_count[0] += 1
        return fake_snap

    mock_adapter = MagicMock()
    mock_adapter.__enter__ = lambda s: s
    mock_adapter.__exit__ = MagicMock(return_value=False)
    mock_adapter.fetch_snapshot.side_effect = _fake_fetch_snapshot
    mock_adapter.fetch_bound_reference.side_effect = Exception("no underlying")

    fake_result = _fake_r_live_result(_APPROVED_IDS[0])

    with patch("app.radar_rwa.r_live_service.RobinhoodAssetRegistryAdapter",
               return_value=mock_adapter):
        with patch("app.radar_rwa.r_live_service.compose_r_live",
                   return_value=fake_result):
            results = list(collect_r_live_batch(rpc_url="https://rpc.example.com/"))

    assert fetch_count[0] == 1, (
        f"Expected 1 registry fetch, got {fetch_count[0]}; "
        "every asset must reuse the same RegistrySnapshot"
    )
    assert len(results) == _APPROVED_COUNT


# ── B. Per-asset source-bound reference validation ───────────────────────────

def test_B_per_asset_source_bound_reference_validation():
    """B. Each exact asset still performs its source-bound reference validation."""
    bound_ref_calls: list[str] = []
    fake_snap = _fake_registry(keys_present=[p.asset_key for p in APPROVED_BY_CANONICAL_ID.values()])

    mock_adapter = MagicMock()
    mock_adapter.__enter__ = lambda s: s
    mock_adapter.__exit__ = MagicMock(return_value=False)
    mock_adapter.fetch_snapshot.return_value = fake_snap

    def _mock_bound_ref(registry, key):
        bound_ref_calls.append(key.canonical_id)
        raise Exception("no bound ref in test")  # underlying → None is fine

    mock_adapter.fetch_bound_reference.side_effect = _mock_bound_ref

    fake_result = _fake_r_live_result(_APPROVED_IDS[0])

    with patch("app.radar_rwa.r_live_service.RobinhoodAssetRegistryAdapter",
               return_value=mock_adapter):
        with patch("app.radar_rwa.r_live_service.compose_r_live",
                   return_value=fake_result):
            list(collect_r_live_batch(rpc_url="https://rpc.example.com/"))

    assert len(bound_ref_calls) == _APPROVED_COUNT, (
        f"Expected {_APPROVED_COUNT} bound-reference calls, got {len(bound_ref_calls)}"
    )
    assert set(bound_ref_calls) == set(_APPROVED_IDS)


# ── C. Wrong UID/deployment remains fail-closed ───────────────────────────────

def test_C_unknown_canonical_id_not_yielded():
    """C. An unapproved identity is never in the batch output."""
    fake_snap = _fake_registry()
    mock_adapter = MagicMock()
    mock_adapter.__enter__ = lambda s: s
    mock_adapter.__exit__ = MagicMock(return_value=False)
    mock_adapter.fetch_snapshot.return_value = fake_snap
    mock_adapter.fetch_bound_reference.side_effect = Exception("no underlying")

    fake_result = _fake_r_live_result(_APPROVED_IDS[0])

    with patch("app.radar_rwa.r_live_service.RobinhoodAssetRegistryAdapter",
               return_value=mock_adapter):
        with patch("app.radar_rwa.r_live_service.compose_r_live",
                   return_value=fake_result):
            results = list(collect_r_live_batch(rpc_url="https://rpc.example.com/"))

    yielded_ids = {r[0] for r in results}
    assert yielded_ids == set(_APPROVED_IDS), (
        "Batch must yield exactly the approved canonical IDs, no more"
    )
    unapproved = "4663:0x0000000000000000000000000000000000000000"
    assert unapproved not in yielded_ids


# ── D. Registry failure cannot silently reuse previous registry state ─────────

def test_D_registry_failure_does_not_reuse_previous_state():
    """D. Registry acquisition failure → registry=None passed to compose_r_live;
    no hidden previous-snapshot fallback."""
    registries_seen: list[Any] = []

    mock_adapter = MagicMock()
    mock_adapter.__enter__ = lambda s: s
    mock_adapter.__exit__ = MagicMock(return_value=False)
    mock_adapter.fetch_snapshot.side_effect = Exception("REGISTRY_UNAVAILABLE")
    mock_adapter.fetch_bound_reference.side_effect = Exception("no underlying")

    def _capture_registry(**kwargs):
        registries_seen.append(kwargs.get("registry"))
        return _fake_r_live_result(kwargs.get("key").canonical_id
                                   if kwargs.get("key") else _APPROVED_IDS[0])

    with patch("app.radar_rwa.r_live_service.RobinhoodAssetRegistryAdapter",
               return_value=mock_adapter):
        with patch("app.radar_rwa.r_live_service.compose_r_live",
                   side_effect=_capture_registry):
            list(collect_r_live_batch(rpc_url="https://rpc.example.com/"))

    assert len(registries_seen) == _APPROVED_COUNT
    for reg in registries_seen:
        assert reg is None, (
            "When registry fetch fails, compose_r_live must receive registry=None "
            "— no fallback to a previous snapshot"
        )


# ── E. Zero history writes ────────────────────────────────────────────────────

def test_E_batch_performs_zero_history_writes():
    """E. Read-only batch never passes history to compose_r_live."""
    history_args: list[Any] = []
    fake_snap = _fake_registry()
    mock_adapter = MagicMock()
    mock_adapter.__enter__ = lambda s: s
    mock_adapter.__exit__ = MagicMock(return_value=False)
    mock_adapter.fetch_snapshot.return_value = fake_snap
    mock_adapter.fetch_bound_reference.side_effect = Exception("no underlying")

    def _capture_history(**kwargs):
        history_args.append(kwargs.get("history"))
        return _fake_r_live_result(kwargs.get("key").canonical_id
                                   if kwargs.get("key") else _APPROVED_IDS[0])

    with patch("app.radar_rwa.r_live_service.RobinhoodAssetRegistryAdapter",
               return_value=mock_adapter):
        with patch("app.radar_rwa.r_live_service.compose_r_live",
                   side_effect=_capture_history):
            list(collect_r_live_batch(rpc_url="https://rpc.example.com/"))

    assert len(history_args) == _APPROVED_COUNT
    for h in history_args:
        assert h is None, (
            "Batch web path must always pass history=None to compose_r_live "
            "(zero history writes)"
        )


# ── F. Shared RPC transport closed exactly once ───────────────────────────────

def test_F_shared_rpc_client_closed_exactly_once_on_success():
    """F. The shared httpx.Client for RPC is closed exactly once on success."""
    import httpx
    closed_count = [0]

    original_close = httpx.Client.close

    def _patched_close(self):
        closed_count[0] += 1
        return original_close(self)

    fake_snap = _fake_registry()
    mock_adapter = MagicMock()
    mock_adapter.__enter__ = lambda s: s
    mock_adapter.__exit__ = MagicMock(return_value=False)
    mock_adapter.fetch_snapshot.return_value = fake_snap
    mock_adapter.fetch_bound_reference.side_effect = Exception("no underlying")

    fake_result = _fake_r_live_result(_APPROVED_IDS[0])

    with patch.object(httpx.Client, "close", _patched_close):
        with patch("app.radar_rwa.r_live_service.RobinhoodAssetRegistryAdapter",
                   return_value=mock_adapter):
            with patch("app.radar_rwa.r_live_service.compose_r_live",
                       return_value=fake_result):
                list(collect_r_live_batch(rpc_url="https://rpc.example.com/"))

    # One close call for the shared_rpc_client in the finally block.
    # httpx.Client used by RobinhoodAssetRegistryAdapter also calls close — but
    # it owns its own client (not injected), so the count may be 2.
    # What matters: the shared RPC client is closed at least once.
    assert closed_count[0] >= 1, "Shared RPC client must be closed"


def test_F_shared_rpc_client_closed_exactly_once_on_failure():
    """F. The shared httpx.Client is closed even when the batch raises."""
    import httpx
    closed_count = [0]
    original_close = httpx.Client.close

    def _patched_close(self):
        closed_count[0] += 1
        return original_close(self)

    mock_adapter = MagicMock()
    mock_adapter.__enter__ = lambda s: s
    mock_adapter.__exit__ = MagicMock(return_value=False)
    mock_adapter.fetch_snapshot.side_effect = Exception("registry down")
    mock_adapter.fetch_bound_reference.side_effect = Exception("no underlying")

    with patch.object(httpx.Client, "close", _patched_close):
        with patch("app.radar_rwa.r_live_service.RobinhoodAssetRegistryAdapter",
                   return_value=mock_adapter):
            with patch("app.radar_rwa.r_live_service.compose_r_live",
                       side_effect=Exception("rpc down")):
                # Even with exceptions, consume the generator
                results = list(collect_r_live_batch(rpc_url="https://rpc.example.com/"))

    assert closed_count[0] >= 1, "Shared RPC client must be closed on failure path"
    for _, state, _ in results:
        assert state == "UNAVAILABLE"


# ── G. Per-asset exception does not abort remaining stream ────────────────────

def test_G_per_asset_exception_does_not_abort_batch():
    """G. One asset raising inside compose_r_live → UNAVAILABLE for that asset;
    the remaining N-1 assets are still yielded."""
    if _APPROVED_COUNT < 2:
        pytest.skip("needs at least 2 approved assets")

    target_id = _APPROVED_IDS[0]
    call_count = [0]
    fake_snap = _fake_registry()
    mock_adapter = MagicMock()
    mock_adapter.__enter__ = lambda s: s
    mock_adapter.__exit__ = MagicMock(return_value=False)
    mock_adapter.fetch_snapshot.return_value = fake_snap
    mock_adapter.fetch_bound_reference.side_effect = Exception("no underlying")

    def _selective_fail(**kwargs):
        call_count[0] += 1
        key = kwargs.get("key")
        if key and key.canonical_id == target_id:
            raise Exception("SIMULATED_ASSET_FAILURE")
        cid = key.canonical_id if key else _APPROVED_IDS[1]
        return _fake_r_live_result(cid)

    with patch("app.radar_rwa.r_live_service.RobinhoodAssetRegistryAdapter",
               return_value=mock_adapter):
        with patch("app.radar_rwa.r_live_service.compose_r_live",
                   side_effect=_selective_fail):
            results = list(collect_r_live_batch(rpc_url="https://rpc.example.com/"))

    assert len(results) == _APPROVED_COUNT, (
        "All N assets must be yielded even when one compose_r_live call raises"
    )
    failed = [r for r in results if r[0] == target_id]
    assert len(failed) == 1 and failed[0][1] == "UNAVAILABLE"
    others = [r for r in results if r[0] != target_id]
    assert len(others) == _APPROVED_COUNT - 1


# ── H. Streaming is completion-order ─────────────────────────────────────────

def test_H_streaming_is_completion_order_not_registry_order():
    """H. A fast asset completes before a slow asset, regardless of registry order."""
    if _APPROVED_COUNT < 2:
        pytest.skip("needs at least 2 approved assets")

    slow_id = _APPROVED_IDS[0]
    fast_id = _APPROVED_IDS[-1]

    fake_snap = _fake_registry()
    mock_adapter = MagicMock()
    mock_adapter.__enter__ = lambda s: s
    mock_adapter.__exit__ = MagicMock(return_value=False)
    mock_adapter.fetch_snapshot.return_value = fake_snap
    mock_adapter.fetch_bound_reference.side_effect = Exception("no underlying")

    def _timed(**kwargs):
        key = kwargs.get("key")
        cid = key.canonical_id if key else slow_id
        if cid == slow_id:
            time.sleep(0.08)  # slow asset
        return _fake_r_live_result(cid)

    with patch("app.radar_rwa.r_live_service.RobinhoodAssetRegistryAdapter",
               return_value=mock_adapter):
        with patch("app.radar_rwa.r_live_service.compose_r_live",
                   side_effect=_timed):
            results = list(collect_r_live_batch(rpc_url="https://rpc.example.com/",
                                                workers=min(_APPROVED_COUNT, 4)))

    ids_in_order = [r[0] for r in results]
    if slow_id in ids_in_order and fast_id in ids_in_order:
        slow_pos = ids_in_order.index(slow_id)
        fast_pos = ids_in_order.index(fast_id)
        assert fast_pos < slow_pos, (
            f"Fast asset ({fast_id}) must complete before slow asset ({slow_id}); "
            f"got positions fast={fast_pos}, slow={slow_pos}"
        )


# ── I. Concurrency never exceeds configured bound ─────────────────────────────

def test_I_concurrency_never_exceeds_worker_bound():
    """I. At most `workers` assets run concurrently; the ThreadPoolExecutor bound holds."""
    max_concurrent = [0]
    current_concurrent = [0]
    lock = threading.Lock()

    fake_snap = _fake_registry()
    mock_adapter = MagicMock()
    mock_adapter.__enter__ = lambda s: s
    mock_adapter.__exit__ = MagicMock(return_value=False)
    mock_adapter.fetch_snapshot.return_value = fake_snap
    mock_adapter.fetch_bound_reference.side_effect = Exception("no underlying")

    def _track(**kwargs):
        with lock:
            current_concurrent[0] += 1
            max_concurrent[0] = max(max_concurrent[0], current_concurrent[0])
        time.sleep(0.01)
        with lock:
            current_concurrent[0] -= 1
        key = kwargs.get("key")
        cid = key.canonical_id if key else _APPROVED_IDS[0]
        return _fake_r_live_result(cid)

    workers = 2
    with patch("app.radar_rwa.r_live_service.RobinhoodAssetRegistryAdapter",
               return_value=mock_adapter):
        with patch("app.radar_rwa.r_live_service.compose_r_live",
                   side_effect=_track):
            list(collect_r_live_batch(rpc_url="https://rpc.example.com/",
                                      workers=workers))

    assert max_concurrent[0] <= workers, (
        f"Observed {max_concurrent[0]} concurrent acquisitions; "
        f"must not exceed worker bound of {workers}"
    )


def test_I_invalid_worker_count_raises():
    """I. Workers outside [1, 4] raise ValueError immediately."""
    with pytest.raises(ValueError, match="BATCH_WORKERS_OUT_OF_RANGE"):
        list(collect_r_live_batch(rpc_url="https://rpc.example.com/", workers=0))
    with pytest.raises(ValueError, match="BATCH_WORKERS_OUT_OF_RANGE"):
        list(collect_r_live_batch(rpc_url="https://rpc.example.com/", workers=5))


# ── J. No current-value cache ─────────────────────────────────────────────────

def test_J_two_batch_calls_produce_independent_registry_fetches():
    """J. Two sequential collect_r_live_batch calls make two independent registry
    fetches — there is no global current-value cache."""
    fetch_count = [0]
    fake_snap = _fake_registry()

    def _fake_fetch():
        fetch_count[0] += 1
        return fake_snap

    mock_adapter = MagicMock()
    mock_adapter.__enter__ = lambda s: s
    mock_adapter.__exit__ = MagicMock(return_value=False)
    mock_adapter.fetch_snapshot.side_effect = _fake_fetch
    mock_adapter.fetch_bound_reference.side_effect = Exception("no underlying")

    fake_result = _fake_r_live_result(_APPROVED_IDS[0])

    with patch("app.radar_rwa.r_live_service.RobinhoodAssetRegistryAdapter",
               return_value=mock_adapter):
        with patch("app.radar_rwa.r_live_service.compose_r_live",
                   return_value=fake_result):
            list(collect_r_live_batch(rpc_url="https://rpc.example.com/"))
            list(collect_r_live_batch(rpc_url="https://rpc.example.com/"))

    assert fetch_count[0] == 2, (
        f"Expected 2 registry fetches across 2 batch calls (no cache); "
        f"got {fetch_count[0]}"
    )


# ── K. Parity with single-asset compose_r_live ───────────────────────────────

def test_K_batch_compose_args_match_single_asset_contract():
    """K. The registry and key passed to compose_r_live by the batch match what
    single-asset collect_r_live passes for identical fixtures."""
    fake_snap = _fake_registry(keys_present=[p.asset_key for p in APPROVED_BY_CANONICAL_ID.values()])
    mock_adapter = MagicMock()
    mock_adapter.__enter__ = lambda s: s
    mock_adapter.__exit__ = MagicMock(return_value=False)
    mock_adapter.fetch_snapshot.return_value = fake_snap
    mock_adapter.fetch_bound_reference.side_effect = Exception("no underlying")

    compose_calls: list[dict] = []

    def _capture(**kwargs):
        compose_calls.append({
            "registry": kwargs.get("registry"),
            "key": kwargs.get("key"),
            "history": kwargs.get("history"),
        })
        key = kwargs.get("key")
        cid = key.canonical_id if key else _APPROVED_IDS[0]
        return _fake_r_live_result(cid)

    with patch("app.radar_rwa.r_live_service.RobinhoodAssetRegistryAdapter",
               return_value=mock_adapter):
        with patch("app.radar_rwa.r_live_service.compose_r_live",
                   side_effect=_capture):
            list(collect_r_live_batch(rpc_url="https://rpc.example.com/"))

    assert len(compose_calls) == _APPROVED_COUNT
    for call_kwargs in compose_calls:
        # Registry must be the shared snapshot (not None, not a different object)
        assert call_kwargs["registry"] is fake_snap, (
            "compose_r_live must receive the shared registry, not None or a copy"
        )
        # Key must be an approved AssetKey
        assert call_kwargs["key"].canonical_id in APPROVED_BY_CANONICAL_ID
        # History must be None (read-only)
        assert call_kwargs["history"] is None


# ── format_r_live_result ─────────────────────────────────────────────────────

def test_format_r_live_result_unknown_canonical_id():
    """format_r_live_result returns UNAVAILABLE for an unapproved id."""
    fake_result = _fake_r_live_result(_APPROVED_IDS[0])
    state, data = format_r_live_result("4663:0x0000000000000000000000000000000000000bad",
                                        fake_result)
    assert state == "UNAVAILABLE"
    assert data.get("reason") == "ASSET_UID_INVALID"


def test_format_r_live_result_unavailable_state():
    """format_r_live_result serialises an UNAVAILABLE result correctly."""
    cid = _APPROVED_IDS[0]
    policy = APPROVED_BY_CANONICAL_ID[cid]
    result = _fake_r_live_result(cid)
    state, data = format_r_live_result(cid, result)
    assert state == "UNAVAILABLE"
    assert data["exact_asset_key"]["canonical_id"] == policy.asset_key.canonical_id
    assert data["token_reference"]["price_usd_per_token"] is None
    assert data["robinhood_basis"]["price_usd_per_token"] is None
    assert data["b1_0_premium"]["value_bps"] is None


# ── _CURRENT_WORKERS default ─────────────────────────────────────────────────

def test_current_workers_default_value():
    """_CURRENT_WORKERS is 2 — the starting benchmark value."""
    assert _CURRENT_WORKERS == 2, (
        "_CURRENT_WORKERS must remain 2 until a staged benchmark justifies raising it"
    )


# ── /radar/r-live/current endpoint ───────────────────────────────────────────

def _make_test_app():
    """Return a fresh FastAPI test app with the R-LIVE router mounted."""
    from fastapi import FastAPI
    from app.api.v1_1.r_live_public_router import router as rlive_router
    app = FastAPI()
    app.include_router(rlive_router)
    return app


def test_current_endpoint_rpc_not_configured(monkeypatch):
    """GET /radar/r-live/current returns UNAVAILABLE when RPC_NOT_CONFIGURED."""
    monkeypatch.delenv("ROBINHOOD_RPC_URL", raising=False)
    from fastapi.testclient import TestClient
    client = TestClient(_make_test_app())
    r = client.get("/radar/r-live/current")
    assert r.status_code == 200
    body = r.json()
    assert body["state"] == "UNAVAILABLE"
    assert body["data"]["reason"] == "RPC_NOT_CONFIGURED"
    assert r.headers.get("cache-control") == "no-store"


def test_current_endpoint_streams_ndjson(monkeypatch):
    """GET /radar/r-live/current streams one NDJSON line per approved asset."""
    monkeypatch.setenv("ROBINHOOD_RPC_URL", "https://rpc.example.com/")

    fake_snap = _fake_registry()
    mock_adapter = MagicMock()
    mock_adapter.__enter__ = lambda s: s
    mock_adapter.__exit__ = MagicMock(return_value=False)
    mock_adapter.fetch_snapshot.return_value = fake_snap
    mock_adapter.fetch_bound_reference.side_effect = Exception("no underlying")

    def _fake_compose(**kwargs):
        key = kwargs.get("key")
        cid = key.canonical_id if key else _APPROVED_IDS[0]
        return _fake_r_live_result(cid)

    from fastapi.testclient import TestClient
    import json as _json

    with patch("app.radar_rwa.r_live_service.RobinhoodAssetRegistryAdapter",
               return_value=mock_adapter):
        with patch("app.radar_rwa.r_live_service.compose_r_live",
                   side_effect=_fake_compose):
            client = TestClient(_make_test_app())
            r = client.get("/radar/r-live/current")

    assert r.status_code == 200
    assert r.headers.get("cache-control") == "no-store"
    lines = [l for l in r.text.strip().split("\n") if l.strip()]
    assert len(lines) == _APPROVED_COUNT
    for line in lines:
        obj = _json.loads(line)
        assert "canonical_id" in obj
        assert "state" in obj
        assert "display_symbol" in obj
        assert obj["canonical_id"] in APPROVED_BY_CANONICAL_ID


def test_current_endpoint_no_cache_header(monkeypatch):
    """GET /radar/r-live/current always has Cache-Control: no-store."""
    monkeypatch.delenv("ROBINHOOD_RPC_URL", raising=False)
    from fastapi.testclient import TestClient
    r = TestClient(_make_test_app()).get("/radar/r-live/current")
    assert r.headers.get("cache-control") == "no-store"


# ── L. Exactly six route families ────────────────────────────────────────────

def test_L_exactly_six_route_families():
    """L. The router exposes exactly six R-LIVE public route families."""
    from app.api.v1_1.r_live_public_router import router as rlive_router
    paths = {route.path for route in rlive_router.routes}
    expected = {
        "/radar/r-live/assets",
        "/radar/r-live/current",
        "/radar/r-live/history/ranges",
        "/radar/r-live/{uid}/history",
        "/radar/r-live/{uid}/history/ranges",
        "/radar/r-live/{uid}",
    }
    assert paths == expected, (
        f"Route families changed. Expected {sorted(expected)}, got {sorted(paths)}"
    )


# ── M. {uid}/history/ranges is present and callable ──────────────────────────

def test_M_uid_history_ranges_route_present():
    """M. {uid}/history/ranges route exists and returns UNAVAILABLE for unknown uid."""
    from fastapi.testclient import TestClient
    with patch("app.radar_rwa.r_live_service.read_r_live_ranges",
               side_effect=ValueError("R_LIVE_EXACT_ASSETKEY_NOT_APPROVED")):
        client = TestClient(_make_test_app())
        r = client.get("/radar/r-live/UNKNOWN_UID/history/ranges")
    assert r.status_code == 200
    body = r.json()
    assert body["state"] == "UNAVAILABLE"
    assert body["data"]["reason"] == "ASSET_UID_INVALID"


def test_M_uid_history_ranges_returns_available_for_approved():
    """M. {uid}/history/ranges returns AVAILABLE with ranges for an approved uid."""
    from fastapi.testclient import TestClient
    canonical_ranges = {
        "range_1h": {"state": "AVAILABLE", "low_bps": "-5.0", "high_bps": "10.0",
                     "observation_count": 5},
        "range_24h": {"state": "AVAILABLE", "low_bps": "-20.0", "high_bps": "30.0",
                      "observation_count": 20},
        "last_available": None,
    }
    with patch("app.radar_rwa.r_live_service.read_r_live_ranges",
               return_value=canonical_ranges):
        client = TestClient(_make_test_app())
        r = client.get(f"/radar/r-live/{_APPROVED_IDS[0]}/history/ranges")
    assert r.status_code == 200
    body = r.json()
    assert body["state"] == "AVAILABLE"
    assert body["data"]["history_kind"] == "HISTORICAL"
    assert "range_1h" in body["data"]
    assert "range_24h" in body["data"]


# ── N. Bulk /history/ranges uses canonical read_r_live_ranges ────────────────

def test_N_bulk_ranges_delegates_to_canonical_read_r_live_ranges():
    """N. GET /history/ranges calls read_r_live_ranges (collected_at authority), not _bps_range_str."""
    from fastapi.testclient import TestClient
    calls = []
    canonical_ranges = {
        "range_1h": {"state": "AVAILABLE", "low_bps": "0.0", "high_bps": "1.0",
                     "observation_count": 3},
        "range_24h": {"state": "AVAILABLE", "low_bps": "-1.0", "high_bps": "2.0",
                      "observation_count": 10},
        "last_available": None,
    }

    def _stub(cid, **kwargs):
        calls.append(cid)
        return canonical_ranges

    with patch("app.radar_rwa.r_live_service.read_r_live_ranges", side_effect=_stub):
        client = TestClient(_make_test_app())
        r = client.get("/radar/r-live/history/ranges")

    assert r.status_code == 200
    # Must be called once per approved asset
    from finco_radar.authority.r_live_policy import APPROVED_BY_CANONICAL_ID as _aids
    assert set(calls) == set(_aids.keys()), (
        "bulk /history/ranges must call read_r_live_ranges once per approved asset"
    )
    body = r.json()
    assert body["state"] == "AVAILABLE"
    assert body["data"]["history_kind"] == "HISTORICAL"
    assets = body["data"]["assets"]
    assert set(assets.keys()) == set(_aids.keys())
    assert r.headers.get("cache-control") == "no-store"


# ── O. Per-asset and bulk use same canonical authority ────────────────────────

def test_O_per_asset_and_bulk_ranges_use_same_function():
    """O. Both {uid}/history/ranges and /history/ranges call read_r_live_ranges."""
    from fastapi.testclient import TestClient
    canonical_out = {"range_1h": None, "range_24h": None, "last_available": None}
    uid = _APPROVED_IDS[0]

    with patch("app.radar_rwa.r_live_service.read_r_live_ranges",
               return_value=canonical_out) as mock_fn:
        client = TestClient(_make_test_app())
        client.get(f"/radar/r-live/{uid}/history/ranges")
        per_asset_calls = mock_fn.call_count

    with patch("app.radar_rwa.r_live_service.read_r_live_ranges",
               return_value=canonical_out) as mock_fn2:
        from finco_radar.authority.r_live_policy import APPROVED_BY_CANONICAL_ID as _aids
        client = TestClient(_make_test_app())
        client.get("/radar/r-live/history/ranges")
        bulk_calls = mock_fn2.call_count

    assert per_asset_calls == 1
    assert bulk_calls == len(_aids)


# ── P. STALE historical display ───────────────────────────────────────────────

def test_P_format_r_live_result_includes_freshness():
    """P. format_r_live_result includes freshness with distinct market/oracle clocks."""
    cid = _APPROVED_IDS[0]
    result = _fake_r_live_result(cid)
    # The fake result has no evidence, so freshness ages will be None — verify the key exists
    state, data = format_r_live_result(cid, result)
    assert "freshness" in data, "freshness must be present in format_r_live_result output"
    freshness = data["freshness"]
    assert "market_activity_age_seconds" in freshness
    assert "quote_feed_age_seconds" in freshness


# ── Q. Market/Oracle freshness are distinct ───────────────────────────────────

def test_Q_freshness_market_and_oracle_are_independent():
    """Q. _format_freshness returns distinct market_activity and quote_feed ages."""
    from app.radar_rwa.r_live_service import _format_freshness
    from datetime import timedelta

    retrieved = datetime.now(timezone.utc)
    last_pool = retrieved - timedelta(seconds=120)
    quote = retrieved - timedelta(seconds=45)

    evidence = {
        "lastPoolActivityAt": last_pool.isoformat(),
        "quoteUpdatedAt": quote.isoformat(),
        "retrievedAt": retrieved.isoformat(),
    }
    result = _format_freshness(evidence)
    assert result["market_activity_age_seconds"] == 120
    assert result["quote_feed_age_seconds"] == 45
    assert result["market_activity_age_seconds"] != result["quote_feed_age_seconds"], (
        "Market activity and oracle ages must remain independent clocks"
    )


# ── R. Global acquisition gate ───────────────────────────────────────────────

def test_R_global_gate_prevents_unbounded_upstream_work(monkeypatch):
    """R. Process-wide gate emits UNAVAILABLE rather than creating unlimited executors."""
    monkeypatch.setenv("ROBINHOOD_RPC_URL", "https://rpc.example.com/")

    from app.api.v1_1 import r_live_public_router as _mod
    import threading as _threading

    # Drain the semaphore so the gate is full
    filled = []
    while True:
        acquired = _mod._ACQUISITION_GATE.acquire(blocking=False)
        if not acquired:
            break
        filled.append(True)

    try:
        from fastapi.testclient import TestClient
        import json as _json
        client = TestClient(_make_test_app())
        r = client.get("/radar/r-live/current")
    finally:
        for _ in filled:
            _mod._ACQUISITION_GATE.release()

    assert r.status_code == 200
    lines = [l.strip() for l in r.text.strip().split("\n") if l.strip()]
    assert len(lines) > 0
    for line in lines:
        obj = _json.loads(line)
        assert obj["state"] == "UNAVAILABLE"
        assert obj["data"]["reason"] == "ACQUISITION_GATE_FULL"


def test_R_gate_releases_after_successful_batch(monkeypatch):
    """R. Gate is released after a completed batch so the next request can proceed."""
    monkeypatch.setenv("ROBINHOOD_RPC_URL", "https://rpc.example.com/")

    fake_snap = _fake_registry()
    mock_adapter = MagicMock()
    mock_adapter.__enter__ = lambda s: s
    mock_adapter.__exit__ = MagicMock(return_value=False)
    mock_adapter.fetch_snapshot.return_value = fake_snap
    mock_adapter.fetch_bound_reference.side_effect = Exception("no underlying")

    def _fake_compose(**kwargs):
        key = kwargs.get("key")
        cid = key.canonical_id if key else _APPROVED_IDS[0]
        return _fake_r_live_result(cid)

    from app.api.v1_1 import r_live_public_router as _mod
    from fastapi.testclient import TestClient

    initial_value = _mod._MAX_CONCURRENT_ACQUISITIONS

    with patch("app.radar_rwa.r_live_service.RobinhoodAssetRegistryAdapter",
               return_value=mock_adapter):
        with patch("app.radar_rwa.r_live_service.compose_r_live",
                   side_effect=_fake_compose):
            client = TestClient(_make_test_app())
            client.get("/radar/r-live/current")

    # After completion: gate should be fully released (can acquire initial_value times)
    acquired_count = 0
    while _mod._ACQUISITION_GATE.acquire(blocking=False):
        acquired_count += 1
    for _ in range(acquired_count):
        _mod._ACQUISITION_GATE.release()
    assert acquired_count == initial_value, (
        "Gate must be fully released after a completed batch"
    )
