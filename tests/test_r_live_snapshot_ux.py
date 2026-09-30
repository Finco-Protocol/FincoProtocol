"""Instant R-LIVE + RWA UX consolidation — snapshot-first architecture tests.

Proves the master-stream invariants:

  - warm R-LIVE page/snapshot reads call ZERO live RPC (no batch, no
    coordinator, no per-asset acquisition);
  - cold start renders INITIALIZING immediately without blocking;
  - background refresh updates the snapshot atomically; a failed refresh
    preserves the prior valid snapshot; failure is isolated per asset;
  - freshness is re-evaluated AT READ TIME against the canonical policy;
    stale evidence becomes STALE — timestamps are never rewritten;
  - exact economic identity (canonical_id + economic_asset_uid) survives
    the snapshot round-trip byte-identically;
  - the RWA overview no longer duplicates the AAPL premium terminal;
  - BNB market-only rows remain market-only: no false Robinhood binding,
    no false premium, no ticker/name/fuzzy/LLM fallback;
  - snapshot reads are lightweight (< 500 ms server-side).
"""
from __future__ import annotations

import json
import time
from types import SimpleNamespace
from datetime import datetime, timedelta, timezone
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]


def _iso(dt: datetime) -> str:
    return dt.astimezone(timezone.utc).isoformat()


def _approved_ids(n: int | None = None) -> list[str]:
    """Deterministically pick canonical ids from THE one approved registry."""
    from finco_radar.authority.r_live_policy import APPROVED_BY_CANONICAL_ID
    ids = sorted(APPROVED_BY_CANONICAL_ID)
    return ids if n is None else ids[:n]


def _approved_count() -> int:
    from finco_radar.authority.r_live_policy import APPROVED_BY_CANONICAL_ID
    return len(APPROVED_BY_CANONICAL_ID)


def _fresh_row(canonical_id: str = "4663:0xapple", *, now=None) -> tuple[str, str, dict]:
    """An acquisition row exactly as the canonical batch yields it: all
    evidence timestamps inside their canonical freshness windows."""
    now = now or datetime.now(timezone.utc)
    data = {
        "exact_asset_key": {"canonical_id": canonical_id, "chain_id": 4663,
                            "contract_address": "0xapple"},
        "economic_asset_uid": f"equity:US:{canonical_id}",
        "token_reference": {"state": "AVAILABLE", "price_usd_per_token": "10.50",
                            "source": "Direct On-Chain", "observed_at": _iso(now - timedelta(seconds=5)),
                            "reason": None},
        "robinhood_basis": {"state": "AVAILABLE", "price_usd_per_token": "10.00",
                            "source": "NASDAQ", "observed_at": _iso(now - timedelta(seconds=8)),
                            "reason": None},
        "b1_0_premium": {"state": "AVAILABLE", "value_bps": "50.0",
                         "formula": "(token - basis) / basis", "reason": None},
        "observed_at": _iso(now - timedelta(seconds=5)),
        "freshness": {
            "market_activity_age_seconds": 10,
            "quote_feed_age_seconds": 60,
            "block_age_seconds": 5,
            "last_pool_activity_at": _iso(now - timedelta(seconds=10)),
            "quote_updated_at": _iso(now - timedelta(seconds=60)),
            "block_timestamp": _iso(now - timedelta(seconds=5)),
            "effective_evidence_at": _iso(now - timedelta(seconds=10)),
            "retrieved_at": _iso(now - timedelta(seconds=2)),
        },
    }
    return canonical_id, "AVAILABLE", data


@pytest.fixture()
def snapshot_db(tmp_path, monkeypatch):
    """Isolated snapshot store per test (durable file, never :memory:)."""
    path = tmp_path / "r_live_snapshots.db"
    monkeypatch.setenv("R_LIVE_SNAPSHOT_DB_PATH", str(path))
    return str(path)


@pytest.fixture()
def no_live_rpc(monkeypatch):
    """Any attempt to reach the live acquisition path in a read test fails loudly."""
    from app.radar_rwa import r_live_service, r_live_public_acquisition

    def forbidden(*a, **k):
        raise AssertionError("live RPC acquisition invoked on a snapshot read path")

    monkeypatch.setattr(r_live_service, "collect_r_live_batch", forbidden)
    monkeypatch.setattr(r_live_public_acquisition, "PUBLIC_RLIVE_ACQUISITION",
                        type("ForbiddenCoordinator", (), {"subscribe": staticmethod(forbidden)})())


# ── Warm snapshot reads never touch live RPC ─────────────────────────────────

def test_warm_snapshot_endpoint_does_not_call_live_rpc(snapshot_db, no_live_rpc):
    from app.radar_rwa.r_live_snapshot_store import RLiveSnapshotStore
    from app.radar_rwa.r_live_snapshot_view import build_snapshot_view

    now = datetime.now(timezone.utc)
    approved = _approved_ids(1)[0]
    with RLiveSnapshotStore(path=snapshot_db) as store:
        store.write_batch([_fresh_row(approved, now=now)], collected_at=now)
    view = build_snapshot_view(path=snapshot_db)
    assert view["state"] == "AVAILABLE"
    # FULL canonical universe, not just the stored rows
    assert len(view["rows"]) == _approved_count()
    row = next(r for r in view["rows"] if r["canonical_id"] == approved)
    assert row["state"] == "AVAILABLE"
    assert row["source"] == "LATEST_SNAPSHOT"
    missing = [r for r in view["rows"] if r["canonical_id"] != approved]
    assert all(r["state"] == "UNAVAILABLE"
               and r["reason"] == "SNAPSHOT_NOT_YET_COLLECTED"
               and r["data"] == {}
               for r in missing)


def test_warm_landing_page_does_not_call_live_rpc(snapshot_db, no_live_rpc):
    from app.radar_rwa.r_live_snapshot_store import RLiveSnapshotStore
    from fastapi import FastAPI
    from fastapi.testclient import TestClient
    from app.radar_ui.r_live_router import router

    now = datetime.now(timezone.utc)
    with RLiveSnapshotStore(path=snapshot_db) as store:
        store.write_batch(
            [_fresh_row(_approved_ids(1)[0], now=now)], collected_at=now)

    app = FastAPI()
    app.include_router(router)
    with TestClient(app) as client:
        started = time.perf_counter()
        response = client.get("/radar/r-live")
        elapsed_ms = (time.perf_counter() - started) * 1000
    assert response.status_code == 200
    assert "INITIALIZING" not in response.text  # warm: no cold banner
    # landing renders the FULL canonical approved universe
    assert response.text.count('data-canonical-id=') == _approved_count()
    assert elapsed_ms < 500, f"warm landing took {elapsed_ms:.0f} ms"


def test_snapshot_api_route_is_lightweight_and_never_acquires(
        snapshot_db, no_live_rpc):
    from app.radar_rwa.r_live_snapshot_store import RLiveSnapshotStore
    from fastapi import FastAPI
    from fastapi.testclient import TestClient
    from app.api.v1_1.r_live_public_router import router

    now = datetime.now(timezone.utc)
    with RLiveSnapshotStore(path=snapshot_db) as store:
        store.write_batch(
            [_fresh_row(cid, now=now) for cid in _approved_ids()], collected_at=now)

    app = FastAPI()
    app.include_router(router, prefix="/api/v1.1")
    with TestClient(app) as client:
        started = time.perf_counter()
        response = client.get("/api/v1.1/radar/r-live/snapshot")
        elapsed_ms = (time.perf_counter() - started) * 1000
    assert response.status_code == 200
    body = response.json()
    assert body["state"] == "AVAILABLE"
    assert len(body["data"]["rows"]) == _approved_count()
    assert all(r["state"] == "AVAILABLE" for r in body["data"]["rows"])
    assert body["data"]["read_duration_ms"] < 500
    assert elapsed_ms < 500, f"snapshot read took {elapsed_ms:.0f} ms"


# ── Cold start: immediate typed INITIALIZING, zero blocking ──────────────────

def test_cold_page_does_not_block_on_live_rpc(snapshot_db, no_live_rpc):
    from fastapi import FastAPI
    from fastapi.testclient import TestClient
    from app.radar_ui.r_live_router import router

    app = FastAPI()
    app.include_router(router)
    with TestClient(app) as client:
        started = time.perf_counter()
        response = client.get("/radar/r-live")
        elapsed_ms = (time.perf_counter() - started) * 1000
    assert response.status_code == 200
    assert 'data-testid="rlive-initializing"' in response.text
    assert "No current observation has been collected yet" in response.text
    assert elapsed_ms < 500, f"cold landing took {elapsed_ms:.0f} ms"


def test_cold_snapshot_endpoint_returns_typed_initializing(snapshot_db, no_live_rpc):
    from fastapi import FastAPI
    from fastapi.testclient import TestClient
    from app.api.v1_1.r_live_public_router import router

    app = FastAPI()
    app.include_router(router, prefix="/api/v1.1")
    with TestClient(app) as client:
        response = client.get("/api/v1.1/radar/r-live/snapshot")
    assert response.status_code == 200
    body = response.json()
    assert body["state"] == "INITIALIZING"
    assert body["data"]["reason"] == "NO_CURRENT_OBSERVATION_COLLECTED"
    assert len(body["data"]["rows"]) == _approved_count()
    assert all(r["state"] == "UNAVAILABLE"
               and r["reason"] == "SNAPSHOT_NOT_YET_COLLECTED"
               and r["data"] == {}
               for r in body["data"]["rows"])


# ── Atomic refresh + failure isolation + last-valid preservation ─────────────

def test_background_refresh_updates_snapshot_atomically(snapshot_db):
    from app.radar_rwa.r_live_snapshot_store import RLiveSnapshotStore

    now = datetime.now(timezone.utc)
    later = now + timedelta(seconds=45)
    with RLiveSnapshotStore(path=snapshot_db) as store:
        store.write_batch([_fresh_row("4663:0xa", now=now)], collected_at=now)
        store.write_batch([_fresh_row("4663:0xb", now=later),
                           _fresh_row("4663:0xc", now=later)], collected_at=later)
    from app.radar_rwa.r_live_snapshot_store import read_snapshots_readonly
    rows = {row["canonical_id"]: row for row in read_snapshots_readonly(path=snapshot_db)}
    assert set(rows) == {"4663:0xa", "4663:0xb", "4663:0xc"}
    assert rows["4663:0xb"]["collected_at"] == _iso(later)
    assert rows["4663:0xa"]["collected_at"] == _iso(now)


def test_failed_refresh_preserves_prior_snapshot(snapshot_db, monkeypatch):
    """A whole-batch failure must not destroy the last valid snapshot, and
    per-asset UNAVAILABLE rows are never written over valid evidence."""
    from app.radar_rwa.r_live_snapshot_store import RLiveSnapshotStore, read_snapshots_readonly
    from app.radar_rwa.r_live_warming import warm_snapshot_once

    now = datetime.now(timezone.utc)
    with RLiveSnapshotStore(path=snapshot_db) as store:
        store.write_batch([_fresh_row("4663:0xa", now=now)], collected_at=now)
    before = read_snapshots_readonly(path=snapshot_db)
    assert before and before[0]["canonical_id"] == "4663:0xa"

    # whole-batch failure
    from app.radar_rwa import r_live_service
    def failing_batch(*, rpc_url, **kwargs):
        raise RuntimeError("R_LIVE_BATCH_ACQUISITION_FAILED")
    monkeypatch.setattr(r_live_service, "collect_r_live_batch", failing_batch)
    summary = warm_snapshot_once("https://rpc.example", store_path=snapshot_db, now=now)
    assert summary["state"] == "SYSTEMIC_FAILURE"
    after = read_snapshots_readonly(path=snapshot_db)
    assert after == before  # last valid snapshot preserved byte-identically

    # per-asset failure: only the healthy asset is written
    def partial_batch(*, rpc_url, **kwargs):
        yield "4663:0xa", "UNAVAILABLE", {"reason": "RADAR_AUTHORITY_UNAVAILABLE"}
        yield "4663:0xb", "AVAILABLE", _fresh_row("4663:0xb", now=now)[2]
    monkeypatch.setattr(r_live_service, "collect_r_live_batch", partial_batch)
    summary = warm_snapshot_once("https://rpc.example", store_path=snapshot_db, now=now)
    assert summary["state"] == "OK" and summary["written"] == 1
    rows = {row["canonical_id"]: row for row in read_snapshots_readonly(path=snapshot_db)}
    assert "4663:0xa" in rows  # preserved despite this cycle's UNAVAILABLE
    assert "4663:0xb" in rows


def test_warming_records_collector_health_heartbeat(snapshot_db, monkeypatch):
    from app.radar_rwa import r_live_service
    from app.radar_rwa.collector_health import read_collector_health_readonly
    from app.radar_rwa.r_live_warming import warm_snapshot_once

    def batch(*, rpc_url, **kwargs):
        yield _fresh_row("4663:0xa")

    monkeypatch.setenv("RADAR_BNB_INTELLIGENCE_DB_PATH", snapshot_db)
    monkeypatch.setattr(r_live_service, "collect_r_live_batch", batch)
    summary = warm_snapshot_once("https://rpc.example", store_path=snapshot_db)
    assert summary["state"] == "OK"
    health = read_collector_health_readonly(path=snapshot_db)
    assert health.batch_outcome == "SUCCESS"
    assert health.liveness == "LIVE"
    assert health.available_count == 1


# ── Freshness recomputed at read; timestamps never rewritten ─────────────────

def test_stale_observation_becomes_stale_at_read_time(snapshot_db, no_live_rpc):
    from app.radar_rwa.r_live_snapshot_store import RLiveSnapshotStore
    from app.radar_rwa.r_live_snapshot_view import reevaluate_snapshot_row

    collected = datetime.now(timezone.utc) - timedelta(minutes=10)
    canonical_id, state, data = _fresh_row("4663:0xold", now=collected)
    with RLiveSnapshotStore(path=snapshot_db) as store:
        store.write_batch([(canonical_id, state, data)], collected_at=collected)
    stored = __import__("app.radar_rwa.r_live_snapshot_store", fromlist=[
        "read_snapshots_readonly"]).read_snapshots_readonly(path=snapshot_db)[0]
    view = reevaluate_snapshot_row(stored)
    assert view["state"] == "STALE"
    assert view["reason"] in ("SNAPSHOT_EVIDENCE_BLOCK_EXPIRED",
                              "SNAPSHOT_EVIDENCE_POOL_ACTIVITY_EXPIRED")
    # read-time ages computed from ORIGINAL evidence, not re-stamped values
    assert view["read_time_ages"]["block_age_seconds"] >= 600 - 5


def test_fresh_snapshot_remains_available_at_read(snapshot_db, no_live_rpc):
    from app.radar_rwa.r_live_snapshot_store import RLiveSnapshotStore
    from app.radar_rwa.r_live_snapshot_view import reevaluate_snapshot_row

    collected = datetime.now(timezone.utc) - timedelta(seconds=5)
    canonical_id, state, data = _fresh_row("4663:0xfresh", now=collected)
    with RLiveSnapshotStore(path=snapshot_db) as store:
        store.write_batch([(canonical_id, state, data)], collected_at=collected)
    stored = __import__("app.radar_rwa.r_live_snapshot_store", fromlist=[
        "read_snapshots_readonly"]).read_snapshots_readonly(path=snapshot_db)[0]
    view = reevaluate_snapshot_row(stored)
    assert view["state"] == "AVAILABLE"


def test_timestamps_are_never_rewritten(snapshot_db, no_live_rpc):
    """Every evidence timestamp survives the store + read round-trip
    byte-identically; the collector clock stays in its own column."""
    from app.radar_rwa.r_live_snapshot_store import RLiveSnapshotStore, read_snapshots_readonly

    collected = datetime.now(timezone.utc) - timedelta(seconds=30)
    canonical_id, state, data = _fresh_row("4663:0xts", now=collected)
    evidence_before = json.dumps(data["freshness"], sort_keys=True)
    observed_before = data["observed_at"]
    with RLiveSnapshotStore(path=snapshot_db) as store:
        store.write_batch([(canonical_id, state, data)], collected_at=collected)
    stored = read_snapshots_readonly(path=snapshot_db)[0]
    evidence_after = json.dumps(stored["payload"]["data"]["freshness"], sort_keys=True)
    assert evidence_after == evidence_before
    assert stored["payload"]["data"]["observed_at"] == observed_before
    assert stored["collected_at"] == _iso(collected)
    # a much later read does NOT refresh the stored evidence
    later = datetime.now(timezone.utc) + timedelta(hours=1)
    from app.radar_rwa.r_live_snapshot_view import reevaluate_snapshot_row
    view = reevaluate_snapshot_row(stored, now=later)
    assert view["data"]["freshness"] == data["freshness"]
    assert view["data"]["observed_at"] == observed_before


def test_exact_economic_identity_unchanged_through_snapshot(snapshot_db, no_live_rpc):
    from app.radar_rwa.r_live_snapshot_store import RLiveSnapshotStore, read_snapshots_readonly

    collected = datetime.now(timezone.utc)
    canonical_id, state, data = _fresh_row("4663:0xident", now=collected)
    with RLiveSnapshotStore(path=snapshot_db) as store:
        store.write_batch([(canonical_id, state, data)], collected_at=collected)
    stored = read_snapshots_readonly(path=snapshot_db)[0]
    assert stored["canonical_id"] == "4663:0xident"
    assert stored["payload"]["data"]["economic_asset_uid"] == "equity:US:4663:0xident"
    assert stored["payload"]["data"]["exact_asset_key"] == {
        "canonical_id": "4663:0xident", "chain_id": 4663, "contract_address": "0xapple"}


def test_read_path_does_not_rewind_timestamps_to_look_current(snapshot_db, no_live_rpc):
    """An aged-out observation can NEVER be presented as AVAILABLE by
    refreshing timestamps — the view fails closed to STALE/UNAVAILABLE."""
    from app.radar_rwa.r_live_snapshot_store import RLiveSnapshotStore, read_snapshots_readonly
    from app.radar_rwa.r_live_snapshot_view import reevaluate_snapshot_row

    collected = datetime.now(timezone.utc) - timedelta(hours=2)
    canonical_id, state, data = _fresh_row("4663:0xancient", now=collected)
    with RLiveSnapshotStore(path=snapshot_db) as store:
        store.write_batch([(canonical_id, state, data)], collected_at=collected)
    stored = read_snapshots_readonly(path=snapshot_db)[0]
    for hours_later in (1, 6, 24):
        view = reevaluate_snapshot_row(
            stored, now=datetime.now(timezone.utc) + timedelta(hours=hours_later))
        assert view["state"] in ("STALE", "UNAVAILABLE")
        assert view["state"] != "AVAILABLE"


# ── Warming loop: no overlapping refreshes; single holder lease ──────────────

def test_no_overlapping_batch_refreshes(snapshot_db, monkeypatch):
    import threading
    from app.radar_rwa import r_live_service
    from app.radar_rwa.r_live_warming import RLiveSnapshotWarmer

    entered = threading.Event()
    release_event = threading.Event()
    batch_entries = []

    def slow_batch(*, rpc_url, **kwargs):
        batch_entries.append(1)
        entered.set()
        release_event.wait(timeout=5)
        yield _fresh_row("4663:0xslow")

    monkeypatch.setattr(r_live_service, "collect_r_live_batch", slow_batch)
    warmer = RLiveSnapshotWarmer(store_path=snapshot_db, interval_seconds=15)

    summaries = []

    def first_cycle():
        summaries.append(warmer.run_cycle(rpc_url="https://rpc.example"))

    worker = threading.Thread(target=first_cycle, daemon=True)
    worker.start()
    assert entered.wait(timeout=5), "first warming cycle never entered the batch"
    # while the first batch is in flight, a second cycle must be REFUSED
    assert warmer.run_cycle(rpc_url="https://rpc.example") is None
    release_event.set()
    worker.join(timeout=5)
    assert summaries and summaries[0]["state"] == "OK"
    assert len(batch_entries) == 1  # the refused cycle never started a batch


def test_lease_admits_exactly_one_holder(snapshot_db):
    from app.radar_rwa.r_live_warming import _SnapshotLease

    lease_a = _SnapshotLease(snapshot_db)
    lease_b = _SnapshotLease(snapshot_db)
    try:
        assert lease_a.acquire_or_renew(ttl_seconds=300) is True
        assert lease_b.acquire_or_renew(ttl_seconds=300) is False  # single holder
        lease_a.release()
        assert lease_b.acquire_or_renew(ttl_seconds=300) is True  # free after release
        lease_b.release()
    finally:
        lease_a.close()
        lease_b.close()


# ── G: RWA overview no longer duplicates the AAPL premium terminal ───────────

def test_rwa_overview_has_no_duplicate_aapl_premium_panel(client_for_rwa):
    html = client_for_rwa("/radar/crypto/rwa")
    assert "AAPL live premium" not in html
    assert 'id="r-live-aapl"' not in html
    assert "Premium history" not in html
    # replaced by one small informational link card to the canonical terminal
    assert "Robinhood tokenized equities" in html
    assert 'href="/radar/r-live"' in html
    assert "View R-LIVE" in html
    # the duplicate live-acquisition wiring is gone from this page
    assert "/static/radar/r_live.js" not in html


@pytest.fixture()
def client_for_rwa(monkeypatch, tmp_path):
    from fastapi import FastAPI
    from fastapi.testclient import TestClient
    from app.radar_ui import rwa_router

    monkeypatch.setenv("RADAR_BNB_INTELLIGENCE_DB_PATH", str(tmp_path / "bnb.db"))

    class _FailingDashboard:
        state = "UNAVAILABLE"

        def read_dashboard(self):
            raise RuntimeError("provider unavailable in test")

    rwa_router.set_rwa_service(_FailingDashboard())
    app = FastAPI()
    app.include_router(rwa_router.router)
    with TestClient(app) as test_client:
        def get(path):
            return test_client.get(path).text
        yield get
    rwa_router.set_rwa_service(rwa_router.RwaDashboardService())


# ── H/I: BNB market-only rows stay market-only; capability chips ─────────────

def _bnb_observation(provider_id, *, with_deployment=False):
    """A minimal typed BnbRwaMarketObservation stand-in with the fields _row needs."""
    from types import SimpleNamespace
    from decimal import Decimal
    from finco_radar.authority.contracts import AuthorityState
    return SimpleNamespace(
        provider_id=provider_id, symbol=provider_id.upper()[:5], name=f"Token {provider_id}",
        asset_key=None if not with_deployment else __import__(
            "finco_radar.assets.contracts", fromlist=["AssetKey"]).AssetKey(
            56, "0x" + provider_id.encode().hex()[:40].ljust(40, "0")),
        deployment_reason=None if with_deployment else "BNB_DEPLOYMENT_UNAVAILABLE",
        state=AuthorityState.AVAILABLE,
        observed_at=datetime.now(timezone.utc),
        price_usd=Decimal("1.23"), market_cap_usd=Decimal("1000"),
        volume_24h_usd=Decimal("10"), price_change_24h_pct=None,
        circulating_supply=None, total_supply=None,
        unavailable_fields=[], source="CoinGecko", provider_asset_id=provider_id,
        market_endpoint="coins/markets", deployment_endpoint="coins/list",
        classification="tokenized-product", market_scope="asset-level",
    )


def test_bnb_market_only_row_remains_market_only(monkeypatch):
    """A market observation with a BNB deployment but NO source-proven
    Robinhood binding must not gain identity, premium, or execution."""
    from app.radar_rwa.bnb_service import _row

    observation = _bnb_observation("tok1", with_deployment=True)
    row = _row(observation, identities={}, intelligence={}, history={})
    caps = row["capabilities"]
    assert caps["market_data"] == "AVAILABLE"
    assert caps["bnb_deployment"] == "AVAILABLE"
    assert caps["rh_identity"] == "UNBOUND"
    assert caps["reference_premium"] == "NOT_SUPPORTED"
    assert caps["execution"] == "NOT_SUPPORTED"
    assert row["intelligence"]["reference_premium"]["state"] != "AVAILABLE"
    assert row["canonical_identity"]["economic_asset_uid"] is None


def test_bnb_missing_robinhood_identity_does_not_gain_premium(monkeypatch):
    from app.radar_rwa.bnb_service import _row
    observation = _bnb_observation("tok2", with_deployment=False)
    row = _row(observation, identities={}, intelligence={}, history={})
    caps = row["capabilities"]
    assert caps["bnb_deployment"] == "UNAVAILABLE"
    assert caps["rh_identity"] == "UNBOUND"
    assert caps["reference_premium"] == "NOT_SUPPORTED"
    assert caps["execution"] == "NOT_SUPPORTED"


def test_bnb_bound_row_with_evidence_gains_premium_capability():
    from types import SimpleNamespace
    from decimal import Decimal
    from finco_radar.assets.contracts import AssetKey
    from finco_radar.authority.contracts import AuthorityState
    from app.radar_rwa.bnb_service import _row

    key = AssetKey(56, "0x" + "ab" * 20)
    binding = SimpleNamespace(
        state=AuthorityState.AVAILABLE, economic_asset_uid="equity:US:TEST",
        canonical_deployments=[SimpleNamespace(chain_id=56, contract_address=key.contract_address,
                                               canonical_id=key.canonical_id)],
        authority_source="canonical-registry", observed_at=datetime.now(timezone.utc),
        reason=None)
    intelligence = {
        "robinhood_basis": {"state": "AVAILABLE", "price_usd_per_token": "10",
                            "source": "registry", "observed_at": None, "reason": None},
        "independent_token_reference": {"state": "AVAILABLE", "price_usd_per_token": "10.1",
                                        "source": "onchain", "observed_at": None, "reason": None},
        "reference_premium": {"state": "AVAILABLE", "value_bps": "100.0",
                              "formula": "f", "reason": None, "observed_at": []},
        "execution": {"effective_price_usd_per_token": None, "provider": None,
                      "requested_notional_usd": None, "route": None,
                      "fee_cost_usd": None, "gas_cost_usd": None,
                      "observed_at": None, "reason": None},
        "execution_gap": {"state": "UNAVAILABLE", "effective_gap_bps": None,
                          "execution_impact_bps": None, "reason": "ROUTE_UNAVAILABLE"},
    }
    observation = SimpleNamespace(
        provider_id="bound1", symbol="TEST", name="Bound Token", asset_key=key,
        deployment_reason=None, state=AuthorityState.AVAILABLE,
        observed_at=datetime.now(timezone.utc), price_usd=Decimal("10"),
        market_cap_usd=Decimal("5000"), volume_24h_usd=Decimal("5"),
        price_change_24h_pct=None, circulating_supply=None, total_supply=None,
        unavailable_fields=[], source="CoinGecko", provider_asset_id="bound1",
        market_endpoint="coins/markets", deployment_endpoint="coins/list",
        classification="tokenized-product", market_scope="asset-level",
    )
    row = _row(observation, identities={key: binding}, intelligence={key: intelligence},
               history={})
    caps = row["capabilities"]
    assert caps["rh_identity"] == "BOUND"
    assert caps["reference_premium"] == "AVAILABLE"
    # execution route evidence missing → capability is UNAVAILABLE, never AVAILABLE
    assert caps["execution"] == "UNAVAILABLE"


def test_bnb_capability_chips_render_without_dominant_unavailable_rows(client_for_rwa_bnb):
    html = client_for_rwa_bnb("/radar/crypto/rwa/bnb")
    assert 'data-testid="bnb-capabilities"' in html
    assert "cap-chip" in html
    assert "RH IDENTITY" in html and "UNBOUND" in html
    assert "ALL OBSERVED" in html and "BOUND" in html and "ACTIONABLE" in html
    # detailed authority reasons remain accessible in expansion details
    assert "Authority detail" in html


def test_bnb_filters_are_presentation_only_with_exact_definitions():
    js = (ROOT / "static/radar/rwa_bnb_filters.js").read_text(encoding="utf-8")
    assert "data-cap-bound" in js and "data-cap-actionable" in js
    assert "no fetch" in js.lower()
    template = (ROOT / "app/templates/radar/rwa_bnb.html").read_text(encoding="utf-8")
    assert "exact source-proven" in template
    assert "execution capability actually exists" in template
    assert 'data-filter="actionable"' in template and 'data-filter="bound"' in template


# ── No identity inference anywhere in the presentation layer ────────────────

def test_no_ticker_or_fuzzy_identity_fallback_in_presentation_layer():
    """The BNB presentation layer must not gain any symbol/name/fuzzy/LLM
    matching that could fabricate an identity binding.  The check targets
    real inference constructs (imported matchers, similarity helpers,
    LLM/API clients) rather than documentation words."""
    bnb_source = (ROOT / "app/radar_rwa/bnb_service.py").read_text(encoding="utf-8")
    banned_imports = ("difflib", "SequenceMatcher", "rapidfuzz", "thefuzz",
                      "fuzzywuzzy", "openai", "anthropic", "levenshtein")
    lowered = bnb_source.lower()
    for token in banned_imports:
        assert token.lower() not in lowered, token
    assert "startswith" not in bnb_source  # no prefix/ticker matching either
    template = (ROOT / "app/templates/radar/rwa_bnb.html").read_text(encoding="utf-8")
    assert "No ticker or provider-ID mapping is inferred" in template


@pytest.fixture()
def client_for_rwa_bnb(monkeypatch, tmp_path):
    from fastapi import FastAPI
    from fastapi.testclient import TestClient
    from app.radar_ui import rwa_router
    from app.radar_rwa import bnb_service

    monkeypatch.setenv("RADAR_BNB_INTELLIGENCE_DB_PATH", str(tmp_path / "bnb.db"))

    class _StaticBnb:
        def read_payload(self):
            from app.radar_rwa.bnb_service import serialize_bnb_snapshot
            from finco_radar.authority.contracts import AuthorityState
            snapshot = SimpleNamespace(
                chain_id=56, state=AuthorityState.AVAILABLE,
                retrieved_at=datetime.now(timezone.utc),
                category_id="tokenized-products", source="CoinGecko",
                source_endpoints=[], market_scope="asset-level",
                observations=[_bnb_observation("mkt1", with_deployment=False)],
                deployment_available_count=0, deployment_unavailable_count=1,
                current_count=1, stale_count=0, observed_market_cap_usd=None,
                observed_volume_24h_usd=None, market_cap_contributors=0,
                volume_contributors=0, rwa_tvl_reason="NO_RWA_TVL_AUTHORITY",
                degraded_reasons=[], reason=None)
            return serialize_bnb_snapshot(snapshot)

    rwa_router.set_bnb_service(_StaticBnb())
    app = FastAPI()
    app.include_router(rwa_router.router)
    with TestClient(app) as test_client:
        def get(path):
            return test_client.get(path).text
        yield get
    rwa_router.set_bnb_service(rwa_router.BnbRwaDashboardService())


# ── Correction A: stable lease holder + renewal semantics ────────────────────

def test_lease_same_instance_renews_foreign_blocked_expired_takeover(snapshot_db):
    """A. acquire → renew (same instance, pre-expiry) → foreign denied →
    renew again → foreign still denied → release → foreign acquires."""
    from app.radar_rwa.r_live_warming import _SnapshotLease

    lease_a = _SnapshotLease(snapshot_db)
    lease_b = _SnapshotLease(snapshot_db)
    t0 = datetime.now(timezone.utc)
    try:
        assert lease_a.acquire_or_renew(ttl_seconds=300, now=t0) is True
        # SAME instance renews before expiry — never self-rejects
        assert lease_a.acquire_or_renew(
            ttl_seconds=300, now=t0 + timedelta(seconds=60)) is True
        # foreign holder is denied while A remains valid/renewed
        assert lease_b.acquire_or_renew(
            ttl_seconds=300, now=t0 + timedelta(seconds=90)) is False
        # A renews again
        assert lease_a.acquire_or_renew(
            ttl_seconds=300, now=t0 + timedelta(seconds=120)) is True
        assert lease_b.acquire_or_renew(
            ttl_seconds=300, now=t0 + timedelta(seconds=150)) is False
        # release deletes ONLY A's lease; B can then acquire
        lease_a.release()
        assert lease_b.acquire_or_renew(
            ttl_seconds=300, now=t0 + timedelta(seconds=180)) is True
        lease_b.release()
    finally:
        lease_a.close()
        lease_b.close()


def test_lease_expired_foreign_lease_taken_over(snapshot_db):
    """B. A stops renewing → after its TTL expires B can acquire."""
    from app.radar_rwa.r_live_warming import _SnapshotLease

    lease_a = _SnapshotLease(snapshot_db)
    lease_b = _SnapshotLease(snapshot_db)
    t0 = datetime.now(timezone.utc)
    try:
        assert lease_a.acquire_or_renew(ttl_seconds=60, now=t0) is True
        # still valid: denied
        assert lease_b.acquire_or_renew(
            ttl_seconds=60, now=t0 + timedelta(seconds=59)) is False
        # TTL expired: takeover allowed
        assert lease_b.acquire_or_renew(
            ttl_seconds=60, now=t0 + timedelta(seconds=61)) is True
        lease_b.release()
    finally:
        lease_a.close()
        lease_b.close()


def test_lease_holder_id_is_stable_per_instance(snapshot_db):
    from app.radar_rwa.r_live_warming import _SnapshotLease

    lease = _SnapshotLease(snapshot_db)
    try:
        first = lease._holder
        lease.acquire_or_renew(ttl_seconds=300)
        assert lease._holder == first  # stable across calls
        assert first  # non-empty, contains a random discriminator (not PID alone)
    finally:
        lease.release()
        lease.close()


def test_60s_warming_schedule_with_180s_ttl_keeps_60s_cadence(snapshot_db):
    """C. deterministic clock: a 60-second warming cycle with a 180-second
    lease TTL renews its own lease every cycle — the effective collection
    cadence stays 60 s (never degraded to the TTL)."""
    from app.radar_rwa.r_live_warming import _SnapshotLease

    lease = _SnapshotLease(snapshot_db)
    t0 = datetime.now(timezone.utc)
    try:
        acquired_at = []
        for tick in range(0, 6):  # 6 cycles at 60 s spacing
            now = t0 + timedelta(seconds=60 * tick)
            allowed = lease.acquire_or_renew(ttl_seconds=180, now=now)
            assert allowed is True, f"cycle {tick} was self-rejected"
            acquired_at.append(60 * tick)
        assert acquired_at == [0, 60, 120, 180, 240, 300]  # full 60 s cadence
        lease.release()
    finally:
        lease.close()


# ── Correction A: full canonical approved universe presentation ──────────────

def test_partial_snapshot_still_presents_full_approved_universe(
        snapshot_db, no_live_rpc):
    """Regression 1: canonical universe = all approved assets; only some
    stored → API returns the FULL universe and missing assets are typed
    UNAVAILABLE / SNAPSHOT_NOT_YET_COLLECTED (never omitted, never zero)."""
    from app.radar_rwa.r_live_snapshot_store import RLiveSnapshotStore
    from fastapi import FastAPI
    from fastapi.testclient import TestClient
    from app.api.v1_1.r_live_public_router import router

    ids = _approved_ids()
    stored, missing = ids[:9], ids[9:]
    now = datetime.now(timezone.utc)
    with RLiveSnapshotStore(path=snapshot_db) as store:
        store.write_batch([_fresh_row(cid, now=now) for cid in stored],
                          collected_at=now)

    app = FastAPI()
    app.include_router(router, prefix="/api/v1.1")
    with TestClient(app) as client:
        response = client.get("/api/v1.1/radar/r-live/snapshot")
    body = response.json()
    assert body["state"] == "AVAILABLE"  # partial is a real projection
    rows = {r["canonical_id"]: r for r in body["data"]["rows"]}
    assert len(rows) == _approved_count()  # FULL universe in the API
    for cid in stored:
        assert rows[cid]["state"] == "AVAILABLE"
        assert rows[cid]["data"]["b1_0_premium"]["value_bps"] is not None
    for cid in missing:
        assert rows[cid]["state"] == "UNAVAILABLE"
        assert rows[cid]["reason"] == "SNAPSHOT_NOT_YET_COLLECTED"
        assert rows[cid]["data"] == {}  # no fabricated numeric fields


def test_partial_snapshot_landing_renders_full_approved_universe(
        snapshot_db, no_live_rpc):
    """Regression 1 (landing): the page always renders the canonical
    approved rows — snapshot evidence is a LEFT JOIN, never the universe."""
    from app.radar_rwa.r_live_snapshot_store import RLiveSnapshotStore
    from fastapi import FastAPI
    from fastapi.testclient import TestClient
    from app.radar_ui.r_live_router import router

    ids = _approved_ids()
    now = datetime.now(timezone.utc)
    with RLiveSnapshotStore(path=snapshot_db) as store:
        store.write_batch([_fresh_row(cid, now=now) for cid in ids[:9]],
                          collected_at=now)
    app = FastAPI()
    app.include_router(router)
    with TestClient(app) as client:
        html = client.get("/radar/r-live").text
    assert html.count('data-canonical-id=') == _approved_count()
    for cid in ids[9:]:
        assert cid in html  # missing-evidence assets remain in the DOM
    assert "INITIALIZING" not in html  # partial is warm: no cold banner


def test_never_observed_asset_visible_without_fabricated_numbers(snapshot_db):
    """Regression 3: an asset that never had a successful observation stays
    visible and typed — no prices, no premium, no zeros."""
    from app.radar_rwa.r_live_snapshot_view import build_snapshot_view
    view = build_snapshot_view(path=snapshot_db)
    assert view["state"] == "INITIALIZING"
    for row in view["rows"]:
        assert row["state"] == "UNAVAILABLE"
        assert row["reason"] == "SNAPSHOT_NOT_YET_COLLECTED"
        assert row["data"] == {}
        assert "b1_0_premium" not in row["data"]
        assert "token_reference" not in row["data"]


def test_view_never_serves_evidence_for_unapproved_ids(snapshot_db):
    """No second registry: stored rows outside the approved universe are
    never presented."""
    from app.radar_rwa.r_live_snapshot_store import RLiveSnapshotStore
    from app.radar_rwa.r_live_snapshot_view import build_snapshot_view

    now = datetime.now(timezone.utc)
    with RLiveSnapshotStore(path=snapshot_db) as store:
        store.write_batch([_fresh_row("4663:0xnotapproved", now=now)],
                          collected_at=now)
    view = build_snapshot_view(path=snapshot_db)
    assert all(r["canonical_id"] in _approved_ids() for r in view["rows"])
