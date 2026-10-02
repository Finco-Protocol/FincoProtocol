"""Radar Terminal UX V1 — focused regression tests.

Covers:
- bounded display-only 24h series on the batch ranges seam (deterministic,
  digest-verified inputs, no interpolation, no synthetic points, capped)
- series absent by default (per-asset read path unchanged)
- chart/KPI template contracts for R-Live detail and landing
- chart rendering consumes only existing read-only endpoints — no provider
  acquisition from chart data
- workbook chart selector compatibility (legacy .v2-overview-chart intact)
"""
from __future__ import annotations

import hashlib
import json
import sqlite3
from datetime import datetime, timedelta, timezone

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

NOW = datetime(2026, 10, 3, 12, 0, tzinfo=timezone.utc)

REPO = None  # tests read repo files relative to CWD (pytest rootdir = repo root)


def _point(uid: str, canonical_id: str, collected_at: datetime, premium_bps: str,
           state: str = "AVAILABLE"):
    return {
        "economic_asset_uid": uid,
        "asset_key": canonical_id,
        "state": state,
        "collected_at": collected_at.isoformat(),
        "observed_at": collected_at.isoformat(),
        "reference_premium_bps": premium_bps,
        "robinhood_basis": {"price_usd_per_token": "100"},
        "independent_token_reference": {"priceUsdPerToken": "100.1"},
    }


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


def _pairs_and_points(count: int, premium_seq=None):
    from finco_radar.assets.contracts import AssetKey

    uid = "0x" + "a" * 64
    key = AssetKey(4663, "0x" + "b" * 40)
    pts = []
    for i in range(count):
        premium = premium_seq(i) if premium_seq else str(i % 7)
        pts.append(_point(uid, key.canonical_id,
                          NOW - timedelta(minutes=(count - i) * 5), premium))
    return (uid, key), pts


def test_series_is_deterministic_bounded_and_canonical(tmp_path, monkeypatch):
    """series_24h: bounded, deterministic, first/last canonical points kept,
    every point an unaltered canonical observation (no synthesis)."""
    from app.radar_rwa import bnb_history
    from finco_radar.assets.contracts import AssetKey

    monkeypatch.delenv("RADAR_BNB_INTELLIGENCE_DB_PATH", raising=False)
    (uid, key), pts = _pairs_and_points(120)
    db_path = _history_db(tmp_path, {(uid, key.canonical_id): pts})
    monkeypatch.setattr(bnb_history, "DEFAULT_DB_PATH", str(db_path))

    series_a = bnb_history.read_r_live_ranges_batch_readonly(
        [(uid, key)], as_of=NOW, include_series=True, max_series_points=48)
    series_b = bnb_history.read_r_live_ranges_batch_readonly(
        [(uid, key)], as_of=NOW, include_series=True, max_series_points=48)
    out = series_a[key.canonical_id]["series_24h"]
    assert len(out) == 48, "series must be capped at max_series_points"
    assert out == series_b[key.canonical_id]["series_24h"], "downsample must be deterministic"
    # first and last canonical points always preserved, unaltered
    assert out[0]["collected_at"] == pts[0]["collected_at"]
    assert out[0]["premium_bps"] == pts[0]["reference_premium_bps"]
    assert out[-1]["collected_at"] == pts[-1]["collected_at"]
    assert out[-1]["premium_bps"] == pts[-1]["reference_premium_bps"]
    # every series point IS a canonical point (selection, never invention)
    canonical = {(p["collected_at"], p["reference_premium_bps"]) for p in pts}
    for p in out:
        assert (p["collected_at"], p["premium_bps"]) in canonical
    # ascending by canonical timestamp
    stamps = [p["collected_at"] for p in out]
    assert stamps == sorted(stamps)


def test_series_small_history_rendered_directly_no_downsample(tmp_path, monkeypatch):
    from app.radar_rwa import bnb_history
    from finco_radar.assets.contracts import AssetKey

    monkeypatch.delenv("RADAR_BNB_INTELLIGENCE_DB_PATH", raising=False)
    (uid, key), pts = _pairs_and_points(20)
    db_path = _history_db(tmp_path, {(uid, key.canonical_id): pts})
    monkeypatch.setattr(bnb_history, "DEFAULT_DB_PATH", str(db_path))

    out = bnb_history.read_r_live_ranges_batch_readonly(
        [(uid, key)], as_of=NOW, include_series=True, max_series_points=48)
    series = out[key.canonical_id]["series_24h"]
    assert len(series) == 20, "series within budget renders directly (no downsample)"
    assert all(p["premium_bps"] == pts[i]["reference_premium_bps"]
               for i, p in enumerate(series))


def test_series_excludes_non_available_points(tmp_path, monkeypatch):
    from app.radar_rwa import bnb_history
    from finco_radar.assets.contracts import AssetKey

    monkeypatch.delenv("RADAR_BNB_INTELLIGENCE_DB_PATH", raising=False)
    (uid, key), pts = _pairs_and_points(10)
    pts[4]["state"] = "STALE"
    db_path = _history_db(tmp_path, {(uid, key.canonical_id): pts})
    monkeypatch.setattr(bnb_history, "DEFAULT_DB_PATH", str(db_path))

    out = bnb_history.read_r_live_ranges_batch_readonly(
        [(uid, key)], as_of=NOW, include_series=True)
    series = out[key.canonical_id]["series_24h"]
    assert len(series) == 9
    assert all(p["collected_at"] != pts[4]["collected_at"] for p in series)


def test_series_absent_by_default_parity_preserved(tmp_path, monkeypatch):
    """Default batch output keeps its exact pre-series shape (parity with the
    per-asset read); series only appears with include_series=True."""
    from app.radar_rwa import bnb_history
    from app.radar_rwa.bnb_history import (
        read_r_live_range_summary_readonly, read_r_live_ranges_batch_readonly)
    from finco_radar.assets.contracts import AssetKey

    monkeypatch.delenv("RADAR_BNB_INTELLIGENCE_DB_PATH", raising=False)
    (uid, key), pts = _pairs_and_points(10)
    db_path = _history_db(tmp_path, {(uid, key.canonical_id): pts})
    monkeypatch.setattr(bnb_history, "DEFAULT_DB_PATH", str(db_path))

    default_out = read_r_live_ranges_batch_readonly([(uid, key)], as_of=NOW)
    single = read_r_live_range_summary_readonly(uid, key, as_of=NOW)
    assert "series_24h" not in default_out[key.canonical_id]
    assert default_out[key.canonical_id] == single

    with_series = read_r_live_ranges_batch_readonly(
        [(uid, key)], as_of=NOW, include_series=True)
    assert with_series[key.canonical_id]["series_24h"]
    # ranges themselves identical with series on/off
    for field in ("range_1h", "range_24h", "last_available"):
        assert with_series[key.canonical_id][field] == default_out[key.canonical_id][field]


def test_series_empty_on_window_cap(tmp_path, monkeypatch):
    from app.radar_rwa import bnb_history
    from finco_radar.assets.contracts import AssetKey

    monkeypatch.delenv("RADAR_BNB_INTELLIGENCE_DB_PATH", raising=False)
    (uid, key), pts = _pairs_and_points(10)
    db_path = _history_db(tmp_path, {(uid, key.canonical_id): pts})
    monkeypatch.setattr(bnb_history, "DEFAULT_DB_PATH", str(db_path))
    # Force the cap path: a window larger than the cap reports cap-exceeded.
    monkeypatch.setattr(bnb_history, "MAX_RLIVE_RANGE_POINTS", 5)
    out = bnb_history.read_r_live_ranges_batch_readonly(
        [(uid, key)], as_of=NOW, include_series=True)
    summary = out[key.canonical_id]
    assert summary.get("reason") == "HISTORY_WINDOW_CAP_EXCEEDED"
    assert summary["series_24h"] == []


def test_public_ranges_endpoint_serves_bounded_series(tmp_path, monkeypatch):
    """The landing ranges endpoint is the ONE request that feeds all chart
    cells — read-only, bounded, no provider acquisition."""
    from app.api.v1_1.r_live_public_router import router
    from app.radar_rwa import bnb_history
    from finco_radar.authority.r_live_policy import APPROVED_RLIVE_ASSETS
    from finco_radar.assets.contracts import AssetKey

    monkeypatch.delenv("RADAR_BNB_INTELLIGENCE_DB_PATH", raising=False)
    pairs = []
    points_by_pair = {}
    for i, policy in enumerate(APPROVED_RLIVE_ASSETS.values()):
        uid, key = policy.economic_asset_uid, policy.asset_key
        pts = [_point(uid, key.canonical_id,
                      NOW - timedelta(minutes=(10 - j) * 5), str(j + 1))
               for j in range(10)]
        points_by_pair[(uid, key.canonical_id)] = pts
        pairs.append((uid, key))
    db_path = _history_db(tmp_path, points_by_pair)
    monkeypatch.setattr(bnb_history, "DEFAULT_DB_PATH", str(db_path))

    app = FastAPI()
    app.include_router(router, prefix="/api/v1.1")
    client = TestClient(app)
    response = client.get("/api/v1.1/radar/r-live/history/ranges")
    assert response.status_code == 200
    assert response.headers["cache-control"] == "no-store"
    assets = response.json()["data"]["assets"]
    for policy in APPROVED_RLIVE_ASSETS.values():
        cid = policy.asset_key.canonical_id
        assert "series_24h" in assets[cid]
        assert len(assets[cid]["series_24h"]) <= 48


# ── Template / JS contracts ──────────────────────────────────────────────────

def _detail_html():
    return open("app/templates/radar/r_live_detail.html", encoding="utf-8").read()


def _landing_html():
    return open("app/templates/radar/r_live_landing.html", encoding="utf-8").read()


def _landing_js():
    return open("static/radar/r_live_table.js", encoding="utf-8").read()


def _charts_js():
    return open("static/interaction/overview-charts.js", encoding="utf-8").read()


def test_detail_template_has_kpi_strip_and_charts():
    html = _detail_html()
    assert "detail-kpi-strip" in html
    for kpi in ("kpi-premium", "kpi-basis", "kpi-token", "kpi-range", "kpi-freshness"):
        assert kpi in html
    assert 'data-chart-type="line"' in html
    assert "chart-premium-skeleton" in html and "chart-prices-skeleton" in html
    assert "fo-power-skeleton" in html, "detail loading must reuse the existing skeleton primitive"
    assert "overview-charts.js" in html
    assert "Insufficient canonical history" in html, "typed insufficient-history state required"
    assert "history?limit=100" in html, "detail uses the existing bounded history read"


def test_detail_charts_use_canonical_history_only():
    js = _detail_html()
    # the chart builder consumes the same history fetch as the table
    assert "build_charts(points)" in js and "build_history_table(points)" in js
    assert "Gaps stay gaps" in js or "gaps are missing evidence" in js or "gaps stay gaps" in js.lower()
    # no new data source: charts come from HIST_URL only
    assert js.count("fetch(HIST_URL)") == 1 and js.count("fetch(SNAPSHOT_URL)") == 1
    assert "fo-charts:refresh" not in js, "async pages render via window.FoCharts, not re-scan"


def test_landing_visuals_are_read_only_and_bounded():
    html = _landing_html()
    js = _landing_js()
    assert 'data-chart-type="sparkline"' in html
    assert 'data-chart-type="range-bar"' in html
    assert "fo-power-skeleton" in html
    # still exactly two read-only endpoints on the landing (snapshot + ranges)
    assert js.count("fetch(") == 2
    assert "/api/v1.1/radar/r-live/snapshot" in js
    assert "/api/v1.1/radar/r-live/history/ranges" in js
    # visuals come from the ranges payload only
    assert "series_24h" in js and "range_24h" in js
    assert "FoCharts" in js
    # skeleton never shimmers forever: failure path clears it
    assert "fo-power-skeleton" in js


def test_chart_primitives_are_genuine_and_zero_dependency():
    js = _charts_js()
    assert "renderSparkline" in js and "renderLine" in js and "renderRangeBar" in js
    assert "window.FoCharts" in js
    # gaps stay gaps — runsOf splits at null values, no interpolation
    assert "runsOf" in js
    # legacy workbook selector still handled
    assert "v2-overview-chart" in js
    for forbidden in ("chart.js", "Chart.js", "plotly", "d3.v", "require(", "import "):
        assert forbidden not in js, forbidden


def test_rlive_detail_chart_path_never_acquires(monkeypatch):
    """Detail page surfaces are read-only: with acquisition instrumented to
    fail loudly, the snapshot/history reads used by the charts still serve."""
    from app.api.v1_1 import r_live_public_router as rlive_module
    from app.radar_rwa import bnb_history

    def _forbidden_acquire(*args, **kwargs):
        raise AssertionError("chart data path must never acquire live")

    monkeypatch.setattr(
        "app.radar_rwa.r_live_public_acquisition.acquire_single_current",
        _forbidden_acquire)
    monkeypatch.delenv("RADAR_BNB_INTELLIGENCE_DB_PATH", raising=False)
    monkeypatch.setattr(bnb_history, "DEFAULT_DB_PATH", "nonexistent-path.db")
    app = FastAPI()
    app.include_router(rlive_module.router, prefix="/api/v1.1")
    client = TestClient(app)
    from finco_radar.authority.r_live_policy import APPROVED_BY_CANONICAL_ID
    uid = next(iter(APPROVED_BY_CANONICAL_ID))
    history = client.get(f"/api/v1.1/radar/r-live/{uid}/history")
    assert history.status_code == 200  # typed empty history, zero acquisition
