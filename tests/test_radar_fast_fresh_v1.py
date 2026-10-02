"""Radar Fast & Fresh V1 — focused regression tests.

Covers:
- local dashboard TTL caches (hit within TTL, expiry, single-flight,
  last-known-good on provider failure, UNAVAILABLE never cached)
- universe discovery TTL cache (hit within TTL, factory-override bypass)
- landing ranges batch read parity with the per-asset read
- R-Live browser read path stays network-free (snapshot polling causes zero
  upstream provider acquisition, for one client and for many clients)
- R-Live detail page contract: snapshot-first JS, no auto live acquisition,
  explicit Refresh now control
"""
from __future__ import annotations

import hashlib
import json
import sqlite3
import threading
import time
from datetime import datetime, timedelta, timezone

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from app.radar_ui import composition
from app.radar_ui import crypto_router as crypto_router_module
from app.radar_ui import derivatives_router as derivatives_router_module
from app.radar_ui import economy_router as economy_router_module
from app.radar_ui import rwa_router as rwa_router_module
from app.radar_ui import stablecoin_router as stablecoin_router_module

NOW = datetime(2026, 10, 2, 15, 0, tzinfo=timezone.utc)

DASHBOARD_MODULES = [
    crypto_router_module, derivatives_router_module,
    economy_router_module, stablecoin_router_module,
]


class CountingService:
    """Deterministic dashboard service stand-in; counts reads."""

    def __init__(self, payload=None, delay: float = 0.0):
        self.calls = 0
        self.payload = payload if payload is not None else {
            "state": "AVAILABLE", "sections": [], "retrieved_at": NOW.isoformat()}
        self._lock = threading.Lock()
        self.delay = delay

    def read_dashboard(self):
        with self._lock:
            self.calls += 1
        if self.delay:
            time.sleep(self.delay)
        return dict(self.payload)


# Minimal payloads matching each template's required top-level attributes —
# just enough for a deterministic 200 render; the tests assert cache
# behavior (call counts / body equality), never presentation details.
def _dashboard_payloads():
    generic = {"state": "AVAILABLE", "sections": [], "fresh_count": 0,
               "stale_count": 0, "unavailable_count": 0, "reason": None,
               "retrieved_at": NOW.isoformat()}
    return {
        "app.radar_ui.crypto_router": dict(generic),
        "app.radar_ui.economy_router": dict(generic),
        "app.radar_ui.stablecoin_router": {
            "state": "AVAILABLE", "summary_rows": [], "top_assets": [],
            "reason": None, "retrieved_at": NOW.isoformat()},
        "app.radar_ui.derivatives_router": {
            "state": "AVAILABLE", "asset_count": 0, "assets": [],
            "summary": {"combined_open_interest_usd_display": "—",
                        "combined_day_notional_volume_usd_display": "—",
                        "combined_oi_turnover_display": "—",
                        "funding_sign": "—"},
            "funding_history": {}, "funding_history_state": "UNAVAILABLE",
            "predicted_funding": {}, "predicted_funding_state": "UNAVAILABLE",
            "cross_venue_note": "", "freshness_note": "",
            "retrieved_at": NOW.isoformat()},
    }


DASHBOARD_PAYLOADS = _dashboard_payloads()


class FlipFailingService:
    """Succeeds on the first read, then raises — one service instance, so a
    cache reset on service injection cannot mask the failure semantics."""

    def __init__(self, payload):
        self.calls = 0
        self.payload = payload

    def read_dashboard(self):
        self.calls += 1
        if self.calls == 1:
            return dict(self.payload)
        raise RuntimeError("provider down")


class CountingPayloadService:
    """Serves a JSON payload through a counting provider read (for the RWA
    JSON snapshot endpoint, which returns the payload directly)."""

    def __init__(self, payload=None):
        self.calls = 0
        self.payload = payload if payload is not None else {
            "state": "AVAILABLE", "rows": [], "retrieved_at": NOW.isoformat()}

    def read_payload(self):
        self.calls += 1
        return dict(self.payload)


def _setter(module):
    names = [name for name in dir(module)
             if name.startswith("set_") and name.endswith("_service")]
    assert len(names) == 1, names
    return getattr(module, names[0])


def _route_path(module):
    paths = [route.path for route in module.router.routes
             if route.path.startswith("/radar")]
    return paths[0]


def _client_for(module) -> TestClient:
    app = FastAPI()
    app.include_router(module.router)
    return TestClient(app)


def _ttl_names(module):
    return [name for name in vars(module)
            if name.endswith("_TTL_SECONDS") and name.startswith("_")]


# ── Dashboard TTL caches ──────────────────────────────────────────────────────

@pytest.mark.parametrize("module", DASHBOARD_MODULES)
def test_dashboard_repeated_requests_within_ttl_call_provider_once(module):
    service = CountingService(DASHBOARD_PAYLOADS[module.__name__])
    _setter(module)(service)
    ttl_name = _ttl_names(module)[0]
    original_ttl = getattr(module, ttl_name)
    setattr(module, ttl_name, 60.0)
    client = _client_for(module)
    path = _route_path(module)
    try:
        first = client.get(path)
        second = client.get(path)
        assert first.status_code == 200 and second.status_code == 200
        assert service.calls == 1, "second request within TTL must not re-call the provider"
    finally:
        setattr(module, ttl_name, original_ttl)


@pytest.mark.parametrize("module", DASHBOARD_MODULES)
def test_dashboard_cache_expiry_reacquires(module):
    service = CountingService(DASHBOARD_PAYLOADS[module.__name__])
    _setter(module)(service)
    ttl_name = _ttl_names(module)[0]
    original_ttl = getattr(module, ttl_name)
    setattr(module, ttl_name, 0.02)
    client = _client_for(module)
    path = _route_path(module)
    try:
        client.get(path)
        time.sleep(0.06)
        client.get(path)
        assert service.calls == 2, "expired TTL must reacquire"
    finally:
        setattr(module, ttl_name, original_ttl)


@pytest.mark.parametrize("module", DASHBOARD_MODULES)
def test_dashboard_provider_failure_serves_last_known_good(module):
    service = FlipFailingService(DASHBOARD_PAYLOADS[module.__name__])
    _setter(module)(service)
    ttl_name = _ttl_names(module)[0]
    grace_name = [name for name in vars(module)
                  if name.endswith("_STALE_GRACE_SECONDS") and name.startswith("_")][0]
    original_ttl = getattr(module, ttl_name)
    original_grace = getattr(module, grace_name)
    setattr(module, ttl_name, 0.02)
    setattr(module, grace_name, 60.0)
    client = _client_for(module)
    path = _route_path(module)
    try:
        first = client.get(path)  # provider success — primes the cache
        assert first.status_code == 200
        time.sleep(0.06)  # expire the TTL; provider now failing
        second = client.get(path)
        assert second.status_code == 200
        assert service.calls == 2
        assert second.text == first.text, (
            "provider failure must serve the preserved last-known-good payload")
    finally:
        setattr(module, ttl_name, original_ttl)
        setattr(module, grace_name, original_grace)


def test_dashboard_unavailable_payload_is_never_cached():
    module = crypto_router_module
    unavailable = CountingService(payload={"state": "UNAVAILABLE", "sections": [],
                                           "reason": "PROVIDER_DOWN"})
    original_ttl = module._DASHBOARD_TTL_SECONDS
    module._DASHBOARD_TTL_SECONDS = 60.0
    client = _client_for(module)
    try:
        module.set_crypto_service(unavailable)
        client.get("/radar/crypto")
        client.get("/radar/crypto")
        assert unavailable.calls == 2, "UNAVAILABLE payloads must not be cached"
    finally:
        module._DASHBOARD_TTL_SECONDS = original_ttl


def test_dashboard_identical_misses_single_flight():
    module = crypto_router_module
    service = CountingService(delay=0.2)
    module.set_crypto_service(service)
    module._DASHBOARD_TTL_SECONDS = 60.0
    try:
        results = []

        def hit():
            results.append(module._read_dashboard_cached())

        threads = [threading.Thread(target=hit) for _ in range(4)]
        for t in threads:
            t.start()
        for t in threads:
            t.join()
        assert len(results) == 4
        assert service.calls == 1, "concurrent identical misses must coalesce to one provider read"
    finally:
        module._DASHBOARD_TTL_SECONDS = 45.0


def test_rwa_overview_and_bnb_payload_caches_are_independent():
    rwa_calls = CountingService()
    bnb_calls = CountingPayloadService()
    rwa_router_module.set_rwa_service(rwa_calls)
    rwa_router_module.set_bnb_service(bnb_calls)
    original_rwa_ttl = rwa_router_module._RWA_DASHBOARD_TTL_SECONDS
    original_bnb_ttl = rwa_router_module._BNB_PAYLOAD_TTL_SECONDS
    rwa_router_module._RWA_DASHBOARD_TTL_SECONDS = 60.0
    rwa_router_module._BNB_PAYLOAD_TTL_SECONDS = 60.0
    client = _client_for(rwa_router_module)
    try:
        client.get("/radar/crypto/rwa")
        client.get("/radar/crypto/rwa/bnb/snapshot")
        client.get("/radar/crypto/rwa")
        client.get("/radar/crypto/rwa/bnb/snapshot")
        assert rwa_calls.calls == 1 and bnb_calls.calls == 1
    finally:
        rwa_router_module._RWA_DASHBOARD_TTL_SECONDS = original_rwa_ttl
        rwa_router_module._BNB_PAYLOAD_TTL_SECONDS = original_bnb_ttl


# ── Universe discovery TTL cache ─────────────────────────────────────────────

class _FakeRegistry:
    def __init__(self, marker: str):
        self.marker = marker
        self.fetch_calls = 0

    def fetch_snapshot(self):
        self.fetch_calls += 1

        class _Deployment:
            chain_id = 4663
            contract_address = "0x" + "1" * 40

        class _Asset:
            asset_uid = f"rh-equity-{self.marker}"
            token_symbol = self.marker
            token_name = f"Fake {self.marker}"
            raw_evidence = {"tokenDecimals": 8}

            def deployment_for_chain(self, chain_id):
                return _Deployment()

        class _Snapshot:
            assets = [_Asset()]

        return _Snapshot()

    def close(self):
        pass


def test_universe_cache_default_path_reuses_one_registry_fetch(monkeypatch):
    composition.reset_universe_cache()
    registry = _FakeRegistry("AAA")
    monkeypatch.setattr(composition, "_registry_factory_override", None)
    monkeypatch.setattr(
        "finco_radar.assets.adapters.robinhood.RobinhoodAssetRegistryAdapter",
        lambda: registry)
    try:
        first = composition.fetch_robinhood_asset_universe()
        second = composition.fetch_robinhood_asset_universe()
        assert len(first) == len(second) == 1
        assert registry.fetch_calls == 1, "second default-path fetch within TTL must reuse the cache"
    finally:
        composition.reset_universe_cache()


def test_universe_cache_bypassed_when_factory_override_active(monkeypatch):
    composition.reset_universe_cache()
    default_registry = _FakeRegistry("AAA")
    monkeypatch.setattr(composition, "_registry_factory_override", None)
    monkeypatch.setattr(
        "finco_radar.assets.adapters.robinhood.RobinhoodAssetRegistryAdapter",
        lambda: default_registry)
    composition.fetch_robinhood_asset_universe()  # prime the cache
    override_registry = _FakeRegistry("BBB")
    monkeypatch.setattr(composition, "_registry_factory_override",
                        lambda: override_registry)
    try:
        universe = composition.fetch_robinhood_asset_universe()
        assert [a.token_symbol for a in universe] == ["BBB"]
        assert override_registry.fetch_calls == 1
    finally:
        composition.reset_universe_cache()


# ── Ranges batch parity ──────────────────────────────────────────────────────

def _history_db(tmp_path, points_by_pair):
    db_path = tmp_path / "b1_3_history.db"
    conn = sqlite3.connect(db_path)
    conn.execute(
        "CREATE TABLE bnb_intelligence_history (digest TEXT PRIMARY KEY, "
        "economic_asset_uid TEXT NOT NULL, asset_key TEXT NOT NULL, "
        "observed_at TEXT NOT NULL, payload TEXT NOT NULL)")
    for (uid, canonical_id), points in points_by_pair.items():
        for point in points:
            payload = json.dumps(point)
            digest = hashlib.sha256(payload.encode("utf-8")).hexdigest()
            conn.execute(
                "INSERT INTO bnb_intelligence_history VALUES (?, ?, ?, ?, ?)",
                (digest, uid, canonical_id, point.get("observed_at"), payload))
    conn.commit()
    conn.close()
    return db_path


def _point(collected_at: str, premium_bps: str, state: str = "AVAILABLE"):
    return {
        "economic_asset_uid": "uid-placeholder",
        "asset_key": "key-placeholder",
        "state": state,
        "collected_at": collected_at,
        "observed_at": collected_at,
        "reference_premium_bps": premium_bps,
        "robinhood_basis": {"price_usd_per_token": "100"},
        "independent_token_reference": {"priceUsdPerToken": "100.1"},
    }


def _prepare_points(points):
    fixed = {}
    for (uid, canonical_id), pts in points.items():
        for pt in pts:
            pt["economic_asset_uid"] = uid
            pt["asset_key"] = canonical_id
        fixed[(uid, canonical_id)] = pts
    return fixed


def test_batch_ranges_match_per_asset_read(tmp_path, monkeypatch):
    from app.radar_rwa.bnb_history import (
        read_r_live_range_summary_readonly, read_r_live_ranges_batch_readonly)
    from finco_radar.assets.contracts import AssetKey

    monkeypatch.delenv("RADAR_BNB_INTELLIGENCE_DB_PATH", raising=False)
    uid_a = "0x00000000000000000000000000000000aaaaaaaaaaaaaaaaaaaaaaaaaaaaaaa1"
    uid_b = "0x00000000000000000000000000000000bbbbbbbbbbbbbbbbbbbbbbbbbbbbbbb2"
    key_a, key_b = AssetKey(4663, "0x" + "a" * 40), AssetKey(4663, "0x" + "b" * 40)
    points = _prepare_points({
        (uid_a, key_a.canonical_id): [
            _point((NOW - timedelta(minutes=5)).isoformat(), "10.5"),
            _point((NOW - timedelta(minutes=90)).isoformat(), "-3.25"),
            _point((NOW - timedelta(hours=30)).isoformat(), "99"),  # outside window
            _point((NOW - timedelta(minutes=10)).isoformat(), "1.0", state="STALE"),
        ],
        (uid_b, key_b.canonical_id): [
            _point((NOW - timedelta(minutes=2)).isoformat(), "-7.75"),
        ],
    })
    db_path = _history_db(tmp_path, points)
    monkeypatch.setattr("app.radar_rwa.bnb_history.DEFAULT_DB_PATH", str(db_path))

    batch = read_r_live_ranges_batch_readonly(
        [(uid_a, key_a), (uid_b, key_b)], as_of=NOW)
    single_a = read_r_live_range_summary_readonly(uid_a, key_a, as_of=NOW)
    single_b = read_r_live_range_summary_readonly(uid_b, key_b, as_of=NOW)
    assert batch[key_a.canonical_id] == single_a
    assert batch[key_b.canonical_id] == single_b
    # Window math actually filtered: 30h-old point excluded, STALE point
    # excluded from ranges; last_available is the newest AVAILABLE point.
    assert single_a["range_24h"]["observation_count"] == 2
    assert single_a["range_1h"]["observation_count"] == 1
    assert single_a["last_available"]["premium_bps"] == "10.5"
    assert single_b["range_24h"]["observation_count"] == 1


def test_batch_ranges_single_store_open(tmp_path, monkeypatch):
    from app.radar_rwa import bnb_history
    from finco_radar.assets.contracts import AssetKey

    monkeypatch.delenv("RADAR_BNB_INTELLIGENCE_DB_PATH", raising=False)
    pairs = []
    points = {}
    for i in range(4):
        uid = "0x" + f"{i:064x}"[-64:]
        key = AssetKey(4663, "0x" + f"{i:040x}")
        pts = [_point((NOW - timedelta(minutes=m)).isoformat(), "2.5")
               for m in (5, 90, 700)]
        for pt in pts:
            pt["economic_asset_uid"] = uid
            pt["asset_key"] = key.canonical_id
        points[(uid, key.canonical_id)] = pts
        pairs.append((uid, key))
    db_path = _history_db(tmp_path, points)
    monkeypatch.setattr(bnb_history, "DEFAULT_DB_PATH", str(db_path))

    opens = []
    real_connect = sqlite3.connect

    def counting_connect(*args, **kwargs):
        opens.append(args)
        return real_connect(*args, **kwargs)

    monkeypatch.setattr(bnb_history.sqlite3, "connect", counting_connect)
    result = bnb_history.read_r_live_ranges_batch_readonly(pairs, as_of=NOW)
    assert len(result) == 4
    ro_opens = [a for a in opens if "mode=ro" in str(a[0])]
    assert len(ro_opens) == 1, f"batch read must open the store once, saw {len(ro_opens)}"


def test_batch_ranges_digest_failure_isolated_per_pair(tmp_path, monkeypatch):
    from app.radar_rwa import bnb_history
    from finco_radar.assets.contracts import AssetKey

    monkeypatch.delenv("RADAR_BNB_INTELLIGENCE_DB_PATH", raising=False)
    uid_a = "0x00000000000000000000000000000000aaaaaaaaaaaaaaaaaaaaaaaaaaaaaaa1"
    uid_b = "0x00000000000000000000000000000000bbbbbbbbbbbbbbbbbbbbbbbbbbbbbbb2"
    key_a, key_b = AssetKey(4663, "0x" + "a" * 40), AssetKey(4663, "0x" + "b" * 40)
    points = _prepare_points({
        (uid_a, key_a.canonical_id): [
            _point((NOW - timedelta(minutes=6)).isoformat(), "2.0")],
        (uid_b, key_b.canonical_id): [
            _point((NOW - timedelta(minutes=5)).isoformat(), "1.0")],
    })
    db_path = _history_db(tmp_path, points)
    conn = sqlite3.connect(db_path)
    conn.execute("UPDATE bnb_intelligence_history SET digest = 'deadbeef' "
                 "WHERE economic_asset_uid = ?", (uid_a,))
    conn.commit()
    conn.close()
    monkeypatch.setattr(bnb_history, "DEFAULT_DB_PATH", str(db_path))

    result = bnb_history.read_r_live_ranges_batch_readonly(
        [(uid_a, key_a), (uid_b, key_b)], as_of=NOW)
    assert result[key_a.canonical_id] == {"reason": "HISTORY_UNAVAILABLE"}
    assert result[key_b.canonical_id]["range_24h"]["observation_count"] == 1


# ── R-Live browser read path: zero upstream provider fan-out ─────────────────

def test_rlive_snapshot_read_path_is_network_free_for_many_clients(monkeypatch):
    """1 client and N clients polling the snapshot endpoint must cause ZERO
    upstream provider acquisition calls; the background warmer is the only
    acquisition path."""
    from app.api.v1_1 import r_live_public_router as rlive_module
    from finco_radar.authority.r_live_policy import APPROVED_BY_CANONICAL_ID

    acquisition_calls = []

    def _forbidden_acquire(*args, **kwargs):
        acquisition_calls.append((args, kwargs))
        raise AssertionError("snapshot read path must never acquire live")

    def _fake_view(*args, **kwargs):
        return {
            "state": "AVAILABLE",
            "rows": [
                {"canonical_id": canonical_id, "display_symbol": "X",
                 "state": "AVAILABLE", "data": {}, "reason": None,
                 "source": "LATEST_SNAPSHOT", "snapshot": {},
                 "snapshot_age_seconds": 1, "read_time_ages": {}}
                for canonical_id in APPROVED_BY_CANONICAL_ID
            ],
            "counts": {}, "read_duration_ms": 0, "detail": "test",
        }

    monkeypatch.setattr("app.radar_rwa.r_live_snapshot_view.build_snapshot_view",
                        _fake_view)
    monkeypatch.setattr(
        "app.radar_rwa.r_live_public_acquisition.acquire_single_current",
        _forbidden_acquire)
    app = FastAPI()
    app.include_router(rlive_module.router)
    client = TestClient(app)
    for _ in range(3):  # multiple sequential "clients"
        response = client.get("/radar/r-live/snapshot")
        assert response.status_code == 200
        body = response.json()
        assert body["state"] == "AVAILABLE"
        assert len(body["data"]["rows"]) == len(APPROVED_BY_CANONICAL_ID)
    assert acquisition_calls == [], "snapshot polling must not trigger provider acquisition"


def test_rlive_landing_page_uses_snapshot_endpoint_only():
    """Landing page contract: the data endpoint is the network-free snapshot;
    polling is continuous, state-independent, and never targets a live
    acquisition URL."""
    js = open("static/radar/r_live_table.js", encoding="utf-8").read()
    assert "/api/v1.1/radar/r-live/snapshot" in js
    assert "setInterval" in js, "continuous polling must exist"
    assert "/radar/r-live/current" not in js, "landing must never poll the live acquisition stream"
    assert "clearInterval" not in js, "polling must never be stopped once the snapshot is warm"
    assert "document.hidden" in js, "polling skips only while the page is not visible"


def test_rlive_detail_page_is_snapshot_first_with_explicit_refresh():
    """Detail page contract: first render reads the canonical snapshot; the
    only live acquisition URL is bound to the explicit Refresh now control."""
    html = open("app/templates/radar/r_live_detail.html", encoding="utf-8").read()
    assert "/api/v1.1/radar/r-live/snapshot" in html
    assert "detail-refresh-now" in html
    assert "INITIALIZING" in html
    live_fetches = [line for line in html.splitlines() if "fetch(LIVE_URL" in line]
    assert len(live_fetches) == 1, "live acquisition must have exactly one call site"
    initial_fetch_region = html.split("function refresh_snapshot", 1)[1][:300]
    assert "SNAPSHOT_URL" in initial_fetch_region, "initial fetch must target the snapshot URL"
