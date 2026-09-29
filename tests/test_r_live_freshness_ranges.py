"""Read-only collection-clock ranges and distinct R-LIVE freshness evidence."""
from __future__ import annotations

from datetime import datetime, timedelta, timezone
from pathlib import Path

from app.api.v1_1.institutional import _r_live_freshness
from app.radar_rwa.bnb_history import (BnbIntelligenceHistoryStore,
                                      read_r_live_range_summary_readonly)
from finco_radar.authority.r_live_policy import AAPL_KEY, AAPL_UID


NOW = datetime(2026, 9, 29, 12, 0, tzinfo=timezone.utc)
EVIDENCE_AT = NOW - timedelta(hours=23)


def point(collected_at: datetime | None, value: str, source_id: int) -> dict:
    evidence = {"sourceEvent": source_id}
    if collected_at is not None:
        evidence["retrievedAt"] = collected_at.isoformat()
    return {
        "economic_asset_uid": AAPL_UID,
        "asset_key": AAPL_KEY.canonical_id,
        "observed_at": EVIDENCE_AT.isoformat(),
        "collected_at": collected_at.isoformat() if collected_at else None,
        "state": "AVAILABLE",
        "robinhood_basis": {"price_usd_per_token": "100"},
        "independent_token_reference": {
            "priceUsdPerToken": "101", "evidence": evidence,
        },
        "reference_premium_bps": value,
    }


def ledger(path: Path, points: list[dict]) -> None:
    store = BnbIntelligenceHistoryStore(str(path), allowed_chain_id=4663)
    try:
        for item in points:
            store.put(item)
    finally:
        store.close()


def test_freshness_separates_market_oracle_and_effective_evidence():
    evidence = {
        "retrievedAt": NOW.isoformat(),
        "lastPoolActivityAt": (NOW - timedelta(seconds=30)).isoformat(),
        "quoteUpdatedAt": EVIDENCE_AT.isoformat(),
        "blockTimestamp": (NOW - timedelta(seconds=5)).isoformat(),
        "effectiveObservedAt": EVIDENCE_AT.isoformat(),
    }
    result = _r_live_freshness(evidence)
    assert result["market_activity_age_seconds"] == 30
    assert result["quote_feed_age_seconds"] == 23 * 3600
    assert result["block_age_seconds"] == 5
    assert result["effective_evidence_at"] == EVIDENCE_AT.isoformat()
    assert result["retrieved_at"] == NOW.isoformat()
    assert _r_live_freshness({})["market_activity_age_seconds"] is None


def test_one_point_and_legacy_without_collection_time_never_fill_range(tmp_path):
    db = tmp_path / "history.db"
    ledger(db, [point(NOW - timedelta(minutes=5), "10", 1),
                point(None, "99", 2)])
    before = db.stat().st_mtime_ns
    summary = read_r_live_range_summary_readonly(AAPL_UID, AAPL_KEY, as_of=NOW, path=str(db))
    assert summary["range_1h"] == {"state": "UNAVAILABLE", "low_bps": None,
                                    "high_bps": None, "observation_count": 1}
    assert summary["range_24h"]["observation_count"] == 1
    assert summary["last_available"] is not None
    assert db.stat().st_mtime_ns == before  # Reader did not mutate the ledger.


def test_two_collections_five_minutes_apart_share_old_source_time(tmp_path):
    db = tmp_path / "history.db"
    ledger(db, [point(NOW - timedelta(minutes=5), "10", 1), point(NOW, "20", 2)])
    summary = read_r_live_range_summary_readonly(AAPL_UID, AAPL_KEY, as_of=NOW, path=str(db))
    for window in ("range_1h", "range_24h"):
        assert summary[window] == {"state": "AVAILABLE", "low_bps": "10",
                                   "high_bps": "20", "observation_count": 2}
    assert summary["last_available"]["effective_evidence_at"] == EVIDENCE_AT.isoformat()
    assert summary["last_available"]["collected_at"] == NOW.isoformat()


def test_24h_range_reads_more_than_old_100_point_browser_limit(tmp_path):
    db = tmp_path / "history.db"
    points = [point(NOW - timedelta(minutes=5 * i), str(i), i)
              for i in range(150)]
    ledger(db, points)
    summary = read_r_live_range_summary_readonly(AAPL_UID, AAPL_KEY, as_of=NOW, path=str(db))
    assert summary["range_24h"] == {"state": "AVAILABLE", "low_bps": "0",
                                     "high_bps": "149", "observation_count": 150}
    assert summary["range_1h"]["observation_count"] == 13


def test_readonly_summary_does_not_create_missing_database(tmp_path):
    db = tmp_path / "absent.db"
    result = read_r_live_range_summary_readonly(AAPL_UID, AAPL_KEY, as_of=NOW, path=str(db))
    assert not db.exists()
    assert result["range_1h"]["state"] == "UNAVAILABLE"
    assert result["last_available"] is None
