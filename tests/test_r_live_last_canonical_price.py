"""R-LIVE last canonical price semantics — focused read-only acceptance."""
from __future__ import annotations

import sqlite3
from datetime import datetime, timedelta, timezone
from pathlib import Path

import pytest

from app.radar_rwa.bnb_history import BnbIntelligenceHistoryStore
from app.radar_rwa.r_live_snapshot_store import RLiveSnapshotStore
from app.radar_rwa.r_live_snapshot_view import (
    HISTORY_SOURCE,
    SNAPSHOT_SOURCE,
    build_snapshot_view,
)
from finco_radar.authority.r_live_policy import APPROVED_BY_CANONICAL_ID


NOW = datetime(2026, 10, 6, 16, 0, tzinfo=timezone.utc)


def _policy():
    return APPROVED_BY_CANONICAL_ID[sorted(APPROVED_BY_CANONICAL_ID)[0]]


def _history_point(*, age: timedelta, token: str = "101", basis: str = "100",
                   premium: str = "100", embedded_key: str | None = None) -> dict:
    policy = _policy()
    key = policy.asset_key.canonical_id
    uid = policy.economic_asset_uid
    source_at = NOW - age
    basis_at = source_at - timedelta(seconds=10)
    retrieved_at = source_at + timedelta(seconds=5)
    inner_key = embedded_key or key
    return {
        "economic_asset_uid": uid,
        "asset_key": key,
        "identity_source": "ROBINHOOD_ASSET_REGISTRY",
        "identity_observed_at": (source_at - timedelta(minutes=1)).isoformat(),
        "observed_at": source_at.isoformat(),
        "collected_at": retrieved_at.isoformat(),
        "state": "AVAILABLE",
        "robinhood_basis": {
            "price_usd_per_token": basis,
            "source": "ROBINHOOD_STOCK_TOKEN_BOUND_PRICE",
            "observed_at": basis_at.isoformat(),
        },
        "independent_token_reference": {
            "state": "AVAILABLE",
            "assetKey": inner_key,
            "assetUid": uid,
            "reason": None,
            "priceUsdPerToken": token,
            "observedAt": source_at.isoformat(),
            "evidence": {
                "assetKey": inner_key,
                "registryAssetUid": uid,
                "lastPoolActivityAt": source_at.isoformat(),
                "quoteUpdatedAt": (source_at - timedelta(minutes=1)).isoformat(),
                "blockTimestamp": source_at.isoformat(),
                "effectiveObservedAt": source_at.isoformat(),
                "retrievedAt": retrieved_at.isoformat(),
            },
        },
        "reference_premium_bps": premium,
        "premium_sources": [
            "ROBINHOOD_STOCK_TOKEN_BOUND_PRICE",
            "UNISWAP_V3_TWAP_CHAINLINK_USDG_USD",
        ],
        "premium_evidence_at": [basis_at.isoformat(), source_at.isoformat()],
        "execution_state": "UNAVAILABLE",
    }


def _snapshot_data(*, pool_age_seconds: int = 10, token: str | None = "202",
                   basis: str | None = "200", premium: str | None = "100") -> dict:
    policy = _policy()
    key = policy.asset_key
    observed = NOW - timedelta(seconds=5)
    return {
        "exact_asset_key": {
            "canonical_id": key.canonical_id,
            "chain_id": key.chain_id,
            "contract_address": key.contract_address,
        },
        "economic_asset_uid": policy.economic_asset_uid,
        "token_reference": {
            "state": "AVAILABLE" if token is not None else "UNAVAILABLE",
            "price_usd_per_token": token,
            "source": "UNISWAP_V3_TWAP_CHAINLINK_USDG_USD",
            "observed_at": observed.isoformat(),
            "reason": None,
        },
        "robinhood_basis": {
            "state": "AVAILABLE" if basis is not None else "UNAVAILABLE",
            "price_usd_per_token": basis,
            "source": "ROBINHOOD_STOCK_TOKEN_BOUND_PRICE",
            "observed_at": (NOW - timedelta(seconds=4)).isoformat(),
            "reason": None,
        },
        "b1_0_premium": {
            "state": "AVAILABLE" if premium is not None else "UNAVAILABLE",
            "value_bps": premium,
            "formula": "(token / basis - 1) * 10000",
            "reason": None,
        },
        "observed_at": observed.isoformat(),
        "freshness": {
            "market_activity_age_seconds": pool_age_seconds,
            "quote_feed_age_seconds": 5,
            "block_age_seconds": 5,
            "last_pool_activity_at": (
                NOW - timedelta(seconds=pool_age_seconds)).isoformat(),
            "quote_updated_at": (NOW - timedelta(seconds=5)).isoformat(),
            "block_timestamp": (NOW - timedelta(seconds=5)).isoformat(),
            "effective_evidence_at": observed.isoformat(),
            "retrieved_at": NOW.isoformat(),
        },
    }


@pytest.fixture()
def stores(tmp_path: Path, monkeypatch):
    history = tmp_path / "r_live_history.db"
    snapshot = tmp_path / "r_live_snapshot.db"
    monkeypatch.setenv("RADAR_BNB_INTELLIGENCE_DB_PATH", str(history))
    monkeypatch.setenv("R_LIVE_SNAPSHOT_DB_PATH", str(snapshot))
    return history, snapshot


def _put_history(path: Path, point: dict) -> None:
    store = BnbIntelligenceHistoryStore(str(path), allowed_chain_id=4663)
    try:
        store.put(point)
    finally:
        store.close()


def _row(view: dict) -> dict:
    canonical_id = _policy().asset_key.canonical_id
    return next(row for row in view["rows"] if row["canonical_id"] == canonical_id)


def _history_count(path: Path) -> int:
    with sqlite3.connect(path) as conn:
        return conn.execute("SELECT COUNT(*) FROM bnb_intelligence_history").fetchone()[0]


def test_fresh_current_snapshot_wins_over_older_history(stores):
    history, snapshot = stores
    _put_history(history, _history_point(age=timedelta(minutes=20)))
    policy = _policy()
    with RLiveSnapshotStore(path=str(snapshot)) as store:
        store.write_batch([
            (policy.asset_key.canonical_id, "AVAILABLE", _snapshot_data())
        ], collected_at=NOW)

    row = _row(build_snapshot_view(path=str(snapshot), now=NOW))
    assert row["state"] == "AVAILABLE"
    assert row["source"] == SNAPSHOT_SOURCE
    assert row["data"]["token_reference"]["price_usd_per_token"] == "202"
    assert row["data"]["robinhood_basis"]["price_usd_per_token"] == "200"


@pytest.mark.parametrize("age", [timedelta(minutes=20), timedelta(hours=4)])
def test_aged_last_canonical_price_remains_visible_with_original_clocks(
        stores, age):
    history, snapshot = stores
    point = _history_point(age=age)
    _put_history(history, point)
    before_count = _history_count(history)
    before_mtime = history.stat().st_mtime_ns

    row = _row(build_snapshot_view(path=str(snapshot), now=NOW))

    assert row["state"] == "AVAILABLE"
    assert row["source"] == HISTORY_SOURCE
    assert row["data"]["token_reference"]["price_usd_per_token"] == "101"
    assert row["data"]["robinhood_basis"]["price_usd_per_token"] == "100"
    assert row["data"]["b1_0_premium"]["value_bps"] == "100"
    assert row["data"]["observed_at"] == point["observed_at"]
    assert row["data"]["token_reference"]["observed_at"] == (
        point["independent_token_reference"]["observedAt"])
    assert row["data"]["robinhood_basis"]["observed_at"] == (
        point["robinhood_basis"]["observed_at"])
    assert row["read_time_ages"]["market_activity_age_seconds"] == int(age.total_seconds())
    assert row["read_time_ages"]["quote_feed_age_seconds"] == int(age.total_seconds()) + 60
    assert row["snapshot"]["evidence_digest"] is not None

    assert _history_count(history) == before_count
    assert history.stat().st_mtime_ns == before_mtime


def test_no_history_and_no_fresh_price_is_unavailable(stores):
    _history, snapshot = stores
    policy = _policy()
    with RLiveSnapshotStore(path=str(snapshot)) as store:
        store.write_batch([
            (policy.asset_key.canonical_id, "STALE",
             _snapshot_data(pool_age_seconds=1200, token=None, premium=None))
        ], collected_at=NOW)

    row = _row(build_snapshot_view(path=str(snapshot), now=NOW))
    assert row["state"] == "UNAVAILABLE"
    assert row["data"] == {}


def test_invalid_embedded_identity_is_never_surfaced(stores):
    history, snapshot = stores
    _put_history(history, _history_point(
        age=timedelta(minutes=20), embedded_key="4663:0xdeadbeef"))

    row = _row(build_snapshot_view(path=str(snapshot), now=NOW))
    assert row["state"] == "UNAVAILABLE"
    assert row["data"] == {}


def test_stale_acquisition_cannot_refresh_old_basis_or_invent_premium(stores):
    history, snapshot = stores
    historical = _history_point(
        age=timedelta(minutes=20), token="101", basis="100", premium="100")
    _put_history(history, historical)

    policy = _policy()
    # Separate newer acquisition has a fresh-looking basis but no admitted
    # token observation. The product fallback must ignore the whole snapshot
    # and surface one complete older B1.3 observation instead.
    current = _snapshot_data(
        pool_age_seconds=1200, token=None, basis="999", premium=None)
    with RLiveSnapshotStore(path=str(snapshot)) as store:
        store.write_batch([
            (policy.asset_key.canonical_id, "STALE", current)
        ], collected_at=NOW)

    row = _row(build_snapshot_view(path=str(snapshot), now=NOW))
    assert row["source"] == HISTORY_SOURCE
    assert row["data"]["token_reference"]["price_usd_per_token"] == "101"
    assert row["data"]["robinhood_basis"]["price_usd_per_token"] == "100"
    assert row["data"]["robinhood_basis"]["price_usd_per_token"] != "999"
    assert row["data"]["b1_0_premium"]["value_bps"] == "100"
    assert row["data"]["freshness"]["last_pool_activity_at"] == (
        historical["independent_token_reference"]["evidence"]["lastPoolActivityAt"])


def test_fallback_read_creates_no_history_snapshot_or_checkpoint_writes(
        stores, monkeypatch):
    history, snapshot = stores
    _put_history(history, _history_point(age=timedelta(minutes=20)))
    before_count = _history_count(history)

    def forbidden(*_args, **_kwargs):
        raise AssertionError("read-time fallback attempted a write")

    monkeypatch.setattr(BnbIntelligenceHistoryStore, "put", forbidden)
    monkeypatch.setattr(BnbIntelligenceHistoryStore, "put_r_live", forbidden)
    monkeypatch.setattr(RLiveSnapshotStore, "write_batch", forbidden)

    row = _row(build_snapshot_view(path=str(snapshot), now=NOW))
    assert row["state"] == "AVAILABLE"
    assert _history_count(history) == before_count
    assert not snapshot.exists()


def test_detail_uses_live_product_status_without_claiming_old_price_is_fresh():
    template = (
        Path(__file__).resolve().parents[1]
        / "app/templates/radar/r_live_detail.html"
    ).read_text(encoding="utf-8")
    assert 'badge.textContent = live ? "LIVE" : "UNAVAILABLE"' in template
    assert 'presentation_source !== "CANONICAL_B1_3_HISTORY"' in template
    assert 'populate(row.state, row.data, row.read_time_ages, row.source)' in template
    assert 'populate(state, (env && env.data) || {}, null, "LIVE_ACQUISITION")' in template
    assert 'if (state === "AVAILABLE")' in template
    assert "Keeping the latest canonical on-chain price." in template
    assert "return refresh_snapshot();" in template
