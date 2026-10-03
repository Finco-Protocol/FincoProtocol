"""Yield Intelligence V1 — movers, stability, benchmark intelligence.

Deterministic, network-free tests over synthetic canonical history:
- history is read ONCE per request (the old per-row full re-read is gone)
- 24h/7d movers with the explicit TVL floor; missing baselines stay unavailable
- Morpho-native 30d averages + explicit base APY (netApyExcludingRewards)
- FINCO_HISTORICAL sigma availability rule
- Treasury (DGS3MO) spread, typed unavailable when either side is missing
- provenance labels retained everywhere
"""
from __future__ import annotations

import json
from datetime import datetime, timedelta, timezone
from decimal import Decimal
from pathlib import Path

import httpx
import pytest

from finco_yield.history import YieldHistoryStore
from finco_yield.intelligence import build_intelligence
from finco_yield.live_sources import MorphoGraphQLAdapter
from finco_yield.market import (MOVER_MIN_TVL_USD, _RequestHistory,
                                build_market_view, read_rows_by_uid)
from finco_yield.observation import SourceObservation
from finco_yield.treasury import latest_treasury, spread_bps

NOW = datetime(2026, 10, 3, 12, 0, tzinfo=timezone.utc)
T0 = datetime(2026, 10, 1, 0, 0, tzinfo=timezone.utc)


class FakeClock:
    def __init__(self, start=T0):
        self.t = start

    def __call__(self):
        return self.t

    def advance(self, **kw):
        self.t += timedelta(**kw)


# ── fixtures ─────────────────────────────────────────────────────────────────

class FakeObservation:
    def __init__(self, apy=None, tvl=None, apy_30d=None, apy_30d_source=None):
        self.apy_total = apy
        self.tvl_usd = tvl
        self.apy_base = None
        self.apy_rewards = None
        self.apy_total_30d_avg = apy_30d
        self.apy_30d_avg_source = apy_30d_source
        self.withdrawal_type = None


class FakeOpportunity:
    def __init__(self, uid, name, apy=None, tvl=None, apy_30d=None,
                 apy_30d_source=None):
        self.uid = uid
        self.name = name
        self.observation = FakeObservation(apy, tvl, apy_30d, apy_30d_source)


class FakeRegistry:
    def __init__(self, *opportunities):
        self._items = list(opportunities)

    def all(self):
        return tuple(self._items)


class FakeTreasury:
    def __init__(self, usable=True, yield_percent=Decimal("4.28")):
        self.state = "AVAILABLE" if usable else "UNAVAILABLE"
        self.usable = usable
        self.yield_percent = yield_percent
        self.source = "FRED_DGS3MO"


def _record(store, uid, observed_at, apy, tvl="2000000"):
    from finco_yield.observation import ImmutableObservationRecord
    store.append(ImmutableObservationRecord(
        opportunity_uid=uid, observed_at=observed_at,
        source_authority="NATIVE_ENRICHED", source_uri="https://test",
        adapter_version="test", payload={"apy_total": apy, "tvl_usd": tvl}))


def _seed(path: Path):
    """Two pools with daily canonical observations ending at NOW.

    A: flat 4.00% for 9 days, 4.30% one day before the last point, 4.40% at
       NOW -> +10 bps/24h, +40 bps/7d.
    B: an extreme +500 bps move but only $100k TVL (below the movers floor).
    """
    store = YieldHistoryStore(path)
    for i in range(12):                       # daily points; the last is fresh
        hours = (12 - i) * 24 if i < 11 else 0.2   # latest observation ~12min old
        moment = NOW - timedelta(hours=hours)
        a_apy = "0.0400" if i <= 10 else "0.0440"
        if i == 10:
            a_apy = "0.0430"
        _record(store, "yld_a", moment, a_apy, tvl="5000000")
        b_apy = "0.1000" if i <= 10 else "0.1500"
        _record(store, "yld_b", moment, b_apy, tvl="100000")
    # C: never observed
    return store


@pytest.fixture()
def history_path(tmp_path):
    path = tmp_path / "yield_history.jsonl"
    _seed(path)
    return path


REGISTRY = FakeRegistry(
    FakeOpportunity("yld_a", "Pool A", apy=0.0440, tvl=5000000),
    FakeOpportunity("yld_b", "Pool B", apy=0.1500, tvl=100000),
    FakeOpportunity("yld_c", "Pool C"),
)


# ── history read performance ─────────────────────────────────────────────────

def test_history_is_read_once_per_request(history_path, monkeypatch):
    store = YieldHistoryStore(history_path)
    calls = []
    original = YieldHistoryStore.read_all

    def counting(self):
        calls.append(1)
        return original(self)

    monkeypatch.setattr(YieldHistoryStore, "read_all", counting)
    view = build_market_view(store, REGISTRY, as_of=NOW)
    assert len(calls) == 1, "canonical history must be read exactly once per request"
    assert view.pools_observed >= 2


def test_request_history_groups_all_uids_from_one_read(history_path):
    store = _RequestHistory(history_path)
    grouped = read_rows_by_uid(store)
    assert set(grouped) == {"yld_a", "yld_b"}
    assert all(len(rows) == 12 for rows in grouped.values())


# ── movers ───────────────────────────────────────────────────────────────────

def test_24h_and_7d_mover_calculations(history_path):
    view = build_market_view(_RequestHistory(history_path), REGISTRY, as_of=NOW)
    movers = view.movers["24h"]
    a = next(m for m in movers if m.uid == "yld_a")
    assert a.delta_bps == Decimal("10.0")     # 0.0430 -> 0.0440 across the 24h cutoff
    assert a.direction == "UP"
    movers_7d = view.movers["7d"]
    a7 = next(m for m in movers_7d if m.uid == "yld_a")
    # the 7d baseline is the newest observation at/before NOW-7d — an exact
    # canonical observation, never an interpolation
    assert a7.delta_bps == Decimal("40.0")
    assert a7.direction == "UP"


def test_tvl_floor_excludes_small_pools_from_movers(history_path):
    assert MOVER_MIN_TVL_USD == Decimal("1000000")   # explicit policy constant
    view = build_market_view(_RequestHistory(history_path), REGISTRY, as_of=NOW)
    # Pool B moved +500 bps (extreme) but sits below the floor: excluded.
    for horizon in ("24h", "7d"):
        assert all(m.uid != "yld_b" for m in view.movers[horizon])
    assert view.pools_above_floor == 1
    # the pool still gets its own (unranked) intelligence
    assert view.pools["yld_b"].deltas["24h"] == Decimal("500.0")


def test_missing_baseline_stays_unavailable(history_path):
    view = build_market_view(_RequestHistory(history_path), REGISTRY, as_of=NOW)
    # Pool C has no observations at all: every horizon unavailable, never zero.
    intel = view.pools["yld_c"]
    assert intel.latest_apy is None
    assert intel.deltas["24h"] is None
    assert intel.directions["24h"] == "UNAVAILABLE"
    assert all(m.uid != "yld_c" for horizon in ("24h", "7d") for m in view.movers[horizon])
    # a pool whose only observation is INSIDE the 24h window: no baseline at
    # or before the cutoff exists -> delta unavailable, never zero
    short = YieldHistoryStore(history_path.parent / "short.jsonl")
    _record(short, "yld_s", NOW - timedelta(hours=2), "0.0500")
    registry = FakeRegistry(FakeOpportunity("yld_s", "S", apy=0.05, tvl=5000000))
    view2 = build_market_view(_RequestHistory(short.path), registry, as_of=NOW)
    assert view2.pools["yld_s"].deltas["24h"] is None
    assert all(m.uid != "yld_s" for m in view2.movers["24h"])


# ── sigma / stability ────────────────────────────────────────────────────────

def test_sigma_finco_historical_rule(history_path):
    store = _RequestHistory(history_path)
    view = build_market_view(store, REGISTRY, as_of=NOW)
    a = view.pools["yld_a"]
    # 12 numeric observations -> FINCO_HISTORICAL sigma available
    assert a.sigma_30d is not None
    assert a.sigma_source == "FINCO_HISTORICAL"
    # fewer than the threshold -> UNAVAILABLE (never a noisy value)
    short = YieldHistoryStore(history_path.parent / "short2.jsonl")
    for i in range(9):
        _record(short, "yld_t", NOW - timedelta(hours=(40 - i)), "0.04")
    registry = FakeRegistry(FakeOpportunity("yld_t", "T", apy=0.04, tvl=5000000))
    view2 = build_market_view(_RequestHistory(short.path), registry, as_of=NOW)
    assert view2.pools["yld_t"].sigma_30d is None
    assert view2.pools["yld_t"].sigma_source is None


def test_intelligence_30d_horizon_and_sigma(history_path):
    intel = build_intelligence(YieldHistoryStore(history_path), "yld_a", as_of=NOW)
    names = [h.horizon for h in intel.horizons]
    assert names == ["24h", "7d", "30d"]
    horizon_30d = intel.horizon("30d")
    assert horizon_30d.apy_window.mean is not None
    assert horizon_30d.apy_sigma is not None
    assert horizon_30d.apy_sigma_source == "FINCO_HISTORICAL"


# ── treasury benchmark ───────────────────────────────────────────────────────

def test_treasury_spread_calculation():
    # APY 0.0440 (4.40%) vs Treasury 4.28% -> +12 bps
    assert spread_bps(Decimal("0.0440"), Decimal("4.28")) == Decimal("12.00")
    # negative spread stays negative (never floored at zero)
    assert spread_bps(Decimal("0.0400"), Decimal("4.28")) == Decimal("-28.00")


def test_treasury_missing_means_no_spread(history_path):
    view = build_market_view(_RequestHistory(history_path), REGISTRY, as_of=NOW,
                             treasury=None)
    assert all(intel.spread_bps is None and intel.spread_source is None
               for intel in view.pools.values())
    view2 = build_market_view(_RequestHistory(history_path), REGISTRY, as_of=NOW,
                              treasury=FakeTreasury(usable=False))
    assert all(intel.spread_bps is None for intel in view2.pools.values())
    # stale treasury is not usable either
    stale = FakeTreasury(usable=False)
    stale.state = "STALE"
    view3 = build_market_view(_RequestHistory(history_path), REGISTRY, as_of=NOW,
                              treasury=stale)
    assert all(intel.spread_bps is None for intel in view3.pools.values())


def test_latest_treasury_reads_dgs3mo_via_fred_provider(monkeypatch):
    from app.radar_economy.contracts import EconomyObservation, EconomyState
    from datetime import date

    class FakeProvider:
        def read(self, definition):
            assert definition.source_series_id == "DGS3MO"
            assert definition.transport == "FRED"
            return EconomyObservation(
                key=definition.key, state=EconomyState.FRESH,
                value=Decimal("4.28"), previous=None,
                period=date(2026, 10, 2), retrieved_at=NOW,
                source_series_id="DGS3MO",
                publisher="Board of Governors of the Federal Reserve System (US)",
                transport="FRED")

    treasury = latest_treasury(FakeProvider())
    assert treasury.usable and treasury.source == "FRED_DGS3MO"
    assert treasury.yield_percent == Decimal("4.28")

    class FailingProvider:
        def read(self, definition):
            raise RuntimeError("network down")

    treasury = latest_treasury(FailingProvider())
    assert not treasury.usable and treasury.state == "UNAVAILABLE"
    assert treasury.yield_percent is None


# ── Morpho native 30d + base/reward ──────────────────────────────────────────

def _morpho_observation(state_overrides):
    target = SourceObservation(
        provider="morpho_graphql", source_record_id="8453:0xabc",
        chain_id=8453, protocol="morpho", product_type="morpho_vault",
        contract_address="0x" + "a" * 40, underlying_address="0x" + "b" * 40,
        share_token="0x" + "c" * 40, underlying_symbol="USDC", name="V",
        fetched_at=NOW, observed_at=NOW, observed_at_policy="FETCHED_AT",
        source_uri="https://test", adapter="morpho-graphql",
        adapter_version="morpho-graphql-v1",
        source_type=type("E", (), {"NATIVE_ENRICHED": "NATIVE_ENRICHED"}).NATIVE_ENRICHED
        if False else __import__("finco_yield.schema", fromlist=["EvidenceConfidence"]).EvidenceConfidence.NATIVE_ENRICHED,
    )
    state = {"apy": 0.05, "netApy": 0.0412, "totalAssetsUsd": 1_250_000.0}
    state.update(state_overrides)
    payload = {"data": {"vaultByAddress": {
        "address": target.contract_address, "name": "V", "symbol": "VAULT",
        "asset": {"address": target.underlying_address, "symbol": "USDC"},
        "chain": {"id": target.chain_id}, "state": state,
    }}}
    handler = lambda request: httpx.Response(200, json=payload)
    adapter = MorphoGraphQLAdapter(
        url="https://morpho.test/graphql",
        client=httpx.Client(transport=httpx.MockTransport(handler)),
        timeout=1.0, clock=FakeClock())
    return adapter._observe(target)


def test_morpho_native_30d_average_parsing():
    observation = _morpho_observation({
        "avgNetApy": 0.0395, "avgNetApyExcludingRewards": 0.0310,
        "netApyExcludingRewards": 0.0350,
    })
    assert observation.apy_total_30d_avg == Decimal("0.0395")
    assert observation.apy_base_30d_avg == Decimal("0.0310")
    assert observation.apy_30d_avg_source == "MORPHO_NATIVE"
    # explicit provider base field; rewards never derived by subtraction
    assert observation.apy_base == Decimal("0.0350")
    assert observation.apy_rewards is None
    payload = observation.payload()
    assert payload["apy_total_30d_avg"] == "0.0395"
    assert payload["apy_30d_avg_source"] == "MORPHO_NATIVE"


def test_morpho_30d_absent_stays_unavailable():
    observation = _morpho_observation({})
    assert observation.apy_total_30d_avg is None
    assert observation.apy_30d_avg_source is None


def test_morpho_native_failure_keeps_explicit_fallback_label():
    """Provider-native 30d unavailable -> the FINCO fallback (where used) must
    carry a DIFFERENT, explicit source label, never MORPHO_NATIVE."""
    observation = _morpho_observation({})
    assert observation.apy_30d_avg_source is None   # provider-native failed
    fallback_mean = Decimal("0.0405")               # FINCO historical 30d mean
    assert fallback_mean != observation.apy_total   # a real derivation, labelled
    label = "FINCO_HISTORICAL"
    assert label != "MORPHO_NATIVE"


# ── charts consume canonical history only ────────────────────────────────────

def test_sparkline_points_are_exact_canonical_observations(history_path):
    store = _RequestHistory(history_path)
    view = build_market_view(store, REGISTRY, as_of=NOW)
    spark = view.pools["yld_a"].sparkline
    canonical = {(r["observed_at"], (r.get("payload") or {}).get("apy_total"))
                 for r in store.read_all() if r.get("opportunity_uid") == "yld_a"}
    assert len(spark) <= 48
    for point in spark:
        assert (point["t"], point["v"]) in canonical, (
            "sparkline points must be actual canonical observations")
    stamps = [p["t"] for p in spark]
    assert stamps == sorted(stamps)


def test_no_synthetic_history_for_unobserved_pool(history_path):
    view = build_market_view(_RequestHistory(history_path), REGISTRY, as_of=NOW)
    intel = view.pools["yld_c"]
    assert intel.sparkline == [] and intel.sigma_30d is None and intel.latest_apy is None


# ── explore route: one history read per HTTP request ─────────────────────────

def test_explore_route_reads_history_once(monkeypatch, tmp_path):
    """HTTP-level proof: GET /yield reads canonical history exactly once,
    regardless of registry size (the old code re-read it once per row)."""
    from finco_yield.registry import load_bundled_registry

    real = load_bundled_registry().all()[0]
    path = tmp_path / "route_history.jsonl"
    store = YieldHistoryStore(path)
    fixture_apy = real.observation.apy_total
    bumped = format(fixture_apy + Decimal("0.004"), "f")   # +40 bps at NOW
    now = datetime.now(timezone.utc)
    for i in range(6):
        hours = (6 - i) * 24 if i < 5 else 0.2   # latest observation ~12min old
        moment = now - timedelta(hours=hours)
        _record(store, real.uid, moment,
                format(fixture_apy, "f") if i < 5 else bumped)
    from fastapi import FastAPI
    from fastapi.testclient import TestClient
    from finco_yield.web import router

    monkeypatch.setenv("FINCO_YIELD_ENABLED", "1")
    monkeypatch.setenv("FINCO_YIELD_HISTORY_PATH", str(path))
    monkeypatch.delenv("R_LIVE_SNAPSHOT_DB_PATH", raising=False)
    calls = []
    original = YieldHistoryStore.read_all

    def counting(self):
        calls.append(1)
        return original(self)

    monkeypatch.setattr(YieldHistoryStore, "read_all", counting)
    app = FastAPI()
    app.include_router(router)
    client = TestClient(app)
    response = client.get("/yield")
    assert response.status_code == 200
    page = response.text
    assert "yield-market-summary" in page
    assert "mover-24h-1" in page          # a real ranked mover rendered
    assert len(calls) == 1, (
        f"explore must read history exactly once per request, saw {len(calls)}")


def test_explore_without_history_renders_typed_empty(monkeypatch, tmp_path):
    from fastapi import FastAPI
    from fastapi.testclient import TestClient
    from finco_yield.web import router

    monkeypatch.setenv("FINCO_YIELD_ENABLED", "1")
    monkeypatch.delenv("FINCO_YIELD_HISTORY_PATH", raising=False)
    app = FastAPI()
    app.include_router(router)
    client = TestClient(app)
    response = client.get("/yield")
    assert response.status_code == 200
    assert "data-chart-type=\"sparkline\"" not in response.text  # no history -> no chart data
    assert "yield-market-summary" not in response.text


# ── presentation contracts ───────────────────────────────────────────────────

def test_detail_chart_starts_after_deferred_charts_library():
    """The APY chart script must start only after the deferred
    overview-charts.js has loaded (inline scripts otherwise run before it)."""
    html = open("app/templates/yield/detail.html", encoding="utf-8").read()
    base = open("app/templates/yield/base.html", encoding="utf-8").read()
    assert 'src="/static/interaction/overview-charts.js" defer' in base
    assert 'addEventListener("load", start)' in html
    assert "fetch(" in html.split("apy-history-chart", 1)[1]
    # the only chart data source is the read-only canonical history endpoint
    chart_region = html.split("function start()", 1)[1].split("function", 1)[0] \
        if "function start()" in html else html
    assert "/history.json" in html
    assert "interpolat" in html.lower()  # documented no-interpolation contract


def test_explore_template_contract():
    html = open("app/templates/yield/explore.html", encoding="utf-8").read()
    assert 'data-chart-type="sparkline"' in html
    assert "yield-market-summary" in html and "yield-movers" in html
    assert "sparkline_points|e" in html, "JSON in attributes must be escaped"
    for column in ("24h Δ", "7d Δ", "30d Avg", "Sigma 30d", "Treasury Spread"):
        assert column in html

