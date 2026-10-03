"""Yield Intelligence V1 Correction A — canonical currentness proofs.

- latest-value read returns the NEWEST canonical observation (APY and TVL
  independently), never the oldest
- REFERENCE_FIXTURE registry values never become market-current data
  (movers, counts, best/median, spreads)
- mover rankings are freshness-gated (stale evidence is not a current mover)
- Treasury spread requires BOTH sides current
- Treasury reads are TTL-cached (daily data must not fan out per page view)
- HISTORY entitlement denial renders the detail page without leaking
  intelligence
- Morpho native 30d values get full numeric validation and honest provenance
"""
from __future__ import annotations

import tempfile
from datetime import datetime, timedelta, timezone
from decimal import Decimal
from pathlib import Path

import httpx
import pytest

from finco_yield.history import YieldHistoryStore
from finco_yield.market import (_RequestHistory, _latest_values, _sorted_rows,
                                build_market_view)
from finco_yield.observation import ImmutableObservationRecord

NOW = datetime(2026, 10, 3, 12, 0, tzinfo=timezone.utc)


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
    store.append(ImmutableObservationRecord(
        opportunity_uid=uid, observed_at=observed_at,
        source_authority="NATIVE_ENRICHED", source_uri="https://test",
        adapter_version="test", payload={"apy_total": apy, "tvl_usd": tvl}))


# ── latest-value correctness ─────────────────────────────────────────────────

def _rows_for_bindings():
    return _sorted_rows([
        {"observed_at": "2026-10-01T00:00:00Z", "source_authority": "NATIVE_ENRICHED",
         "source_uri": "https://test", "adapter_version": "test",
         "payload": {"apy_total": "0.04", "tvl_usd": "1000000"}},
        {"observed_at": "2026-10-02T00:00:00Z", "source_authority": "NATIVE_ENRICHED",
         "source_uri": "https://test", "adapter_version": "test",
         "payload": {"apy_total": "0.06", "tvl_usd": "1100000"}},
    ])


def test_latest_values_returns_newest_apy_not_oldest():
    from finco_yield.market import _value_binding
    rows = _rows_for_bindings()
    now = datetime(2026, 10, 2, 0, 30, tzinfo=timezone.utc)   # both rows fresh
    apy = _value_binding(rows, "apy_total", now)
    tvl = _value_binding(rows, "tvl_usd", now)
    assert apy.value == Decimal("0.06"), "latest APY must be the NEWEST observation (6%), not the oldest (4%)"
    assert tvl.value == Decimal("1100000")
    assert apy.currentness == "CURRENT" and tvl.currentness == "CURRENT"
    assert apy.observed_at.isoformat() == "2026-10-02T00:00:00+00:00"


def test_latest_tvl_independent_of_newest_apy_gap():
    from finco_yield.market import _value_binding
    rows = _sorted_rows([
        {"observed_at": "2026-10-01T00:00:00Z", "source_authority": "NATIVE_ENRICHED",
         "source_uri": "https://test", "adapter_version": "test",
         "payload": {"apy_total": None, "tvl_usd": "900000"}},
        {"observed_at": "2026-10-02T00:00:00Z", "source_authority": "NATIVE_ENRICHED",
         "source_uri": "https://test", "adapter_version": "test",
         "payload": {"apy_total": "0.06", "tvl_usd": None}},
    ])
    now = datetime(2026, 10, 2, 0, 30, tzinfo=timezone.utc)
    apy = _value_binding(rows, "apy_total", now)
    tvl = _value_binding(rows, "tvl_usd", now)
    assert apy.value == Decimal("0.06")      # newest APY
    assert tvl.value == Decimal("900000")    # newest AVAILABLE TVL (independently)
    assert tvl.observed_at.isoformat() == "2026-10-01T00:00:00+00:00"


# ── fixture values are never market-current ──────────────────────────────────

def test_reference_fixture_never_becomes_market_current():
    fixture_registry = FakeRegistry(
        FakeOpportunity("yld_fixture", "Fixture Pool", apy=0.9900, tvl=999_000_000,
                        apy_30d=0.9))
    empty = YieldHistoryStore(Path(tempfile.mkdtemp()) / "empty.jsonl")
    view = build_market_view(_RequestHistory(empty.path), fixture_registry, as_of=NOW,
                             treasury=FakeTreasury(usable=True))
    assert view.pools_observed == 0
    assert view.pools_above_floor == 0
    assert view.movers["24h"] == [] and view.movers["7d"] == []
    assert view.best_apy is None and view.median_apy is None
    intel = view.pools["yld_fixture"]
    assert intel.latest_apy is None and intel.spread_bps is None


def test_pools_observed_counts_canonical_evidence_only(tmp_path):
    store = YieldHistoryStore(tmp_path / "h.jsonl")
    _record(store, "yld_a", NOW - timedelta(hours=0.2), "0.0440", tvl="5000000")
    fixture_registry = FakeRegistry(
        FakeOpportunity("yld_a", "Pool A", apy=0.05, tvl=5_000_000),
        FakeOpportunity("yld_fixture", "Fixture Pool", apy=0.9900, tvl=999_000_000))
    view = build_market_view(_RequestHistory(store.path), fixture_registry, as_of=NOW)
    assert view.pools_observed == 1, "fixture APY must not count as observed market data"


def test_empty_configured_history_with_reference_registry_is_zero_observed(tmp_path):
    empty = YieldHistoryStore(tmp_path / "empty.jsonl")   # configured, 0 rows
    assert empty.read_all() == []
    registry = FakeRegistry(
        FakeOpportunity("yld_fixture", "Fixture Pool", apy=0.9900, tvl=999_000_000))
    view = build_market_view(_RequestHistory(empty.path), registry, as_of=NOW)
    assert view.pools_observed == 0
    assert view.movers["24h"] == []
    assert view.best_apy is None and view.median_apy is None


# ── freshness gating: movers and spreads ─────────────────────────────────────

def test_stale_latest_observation_excluded_from_movers_and_spread(tmp_path):
    store = YieldHistoryStore(tmp_path / "stale.jsonl")
    base = NOW - timedelta(days=3)
    for i in range(12):
        moment = base + timedelta(hours=i * 6)   # ends ~18h before NOW: STALE
        _record(store, "yld_stale", moment, "0.0400" if i < 11 else "0.0500")
    registry = FakeRegistry(FakeOpportunity("yld_stale", "Stale Pool",
                                            apy=0.05, tvl=5_000_000))
    view = build_market_view(_RequestHistory(store.path), registry, as_of=NOW,
                             treasury=FakeTreasury(usable=True))
    intel = view.pools["yld_stale"]
    assert intel.currentness == "STALE"
    assert intel.deltas["24h"] == Decimal("100.0")   # historically derivable
    assert all(m.uid != "yld_stale" for horizon in ("24h", "7d")
               for m in view.movers[horizon]), "stale evidence must not rank as a current mover"
    assert intel.spread_bps is None, "stale yield + fresh treasury -> spread unavailable"


def test_current_yield_with_stale_or_missing_treasury_has_no_spread(tmp_path):
    store = YieldHistoryStore(tmp_path / "h.jsonl")
    _record(store, "yld_a", NOW - timedelta(hours=0.2), "0.0440", tvl="5000000")
    registry = FakeRegistry(FakeOpportunity("yld_a", "Pool A", apy=0.0440, tvl=5_000_000))
    view_none = build_market_view(_RequestHistory(store.path), registry, as_of=NOW,
                                  treasury=None)
    assert view_none.pools["yld_a"].spread_bps is None
    stale = FakeTreasury(usable=False)
    stale.state = "STALE"
    view_stale = build_market_view(_RequestHistory(store.path), registry, as_of=NOW,
                                   treasury=stale)
    assert view_stale.pools["yld_a"].spread_bps is None


def test_current_yield_plus_current_treasury_yields_spread(tmp_path):
    store = YieldHistoryStore(tmp_path / "h.jsonl")
    _record(store, "yld_a", NOW - timedelta(hours=0.2), "0.0440", tvl="5000000")
    registry = FakeRegistry(FakeOpportunity("yld_a", "Pool A", apy=0.0440, tvl=5_000_000))
    view = build_market_view(_RequestHistory(store.path), registry, as_of=NOW,
                             treasury=FakeTreasury(usable=True,
                                                   yield_percent=Decimal("4.28")))
    a = view.pools["yld_a"]     # 4.40% vs 4.28% -> +12 bps
    assert a.spread_bps == Decimal("12.00")
    assert a.spread_source == "APY_VS_FRED_DGS3MO"


def test_best_and_median_use_authority_safe_candidates(tmp_path):
    store = YieldHistoryStore(tmp_path / "h.jsonl")
    _record(store, "yld_hi", NOW - timedelta(hours=0.2), "0.0600", tvl="5000000")
    _record(store, "yld_lo", NOW - timedelta(hours=0.2), "0.0200", tvl="5000000")
    registry = FakeRegistry(
        FakeOpportunity("yld_hi", "High", apy=0.0600, tvl=5_000_000),
        FakeOpportunity("yld_lo", "Low", apy=0.0200, tvl=5_000_000),
        FakeOpportunity("yld_fixture", "Fixture", apy=0.9900, tvl=999_000_000))
    view = build_market_view(_RequestHistory(store.path), registry, as_of=NOW)
    assert view.best_apy["apy"] == Decimal("0.06")
    assert view.best_apy["uid"] == "yld_hi"
    assert view.median_apy == Decimal("0.0400")   # mean of the two real pools


# ── Morpho native 30d validation + provenance ────────────────────────────────

def _morpho_observation(state_overrides):
    from finco_yield.live_sources import MorphoGraphQLAdapter
    from finco_yield.schema import EvidenceConfidence

    target = type("T", (), {})()
    target.contract_address = "0x" + "a" * 40
    target.underlying_address = "0x" + "b" * 40
    target.share_token = "0x" + "c" * 40
    target.chain_id = 8453
    target.protocol = "morpho"
    target.product_type = "morpho_vault"
    target.underlying_symbol = "USDC"
    target.name = "V"
    target.source_uri = "https://test"
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
        timeout=1.0, clock=lambda: NOW)
    return adapter._observe(target)


def test_native_30d_values_reject_non_finite_and_out_of_policy():
    """validate() enforces the same numeric contract on the 30d fields as on
    apy_total/apy_base: finite, in-policy range; None stays UNAVAILABLE."""
    from decimal import InvalidOperation
    from finco_yield.observation import ObservationRejected, SourceObservation
    from finco_yield.schema import EvidenceConfidence

    def observation_with(total_30d, base_30d=None):
        return SourceObservation(
            provider="morpho_graphql", source_record_id="8453:0xabc",
            chain_id=8453, protocol="morpho", product_type="morpho_vault",
            contract_address="0x" + "a" * 40, underlying_address="0x" + "b" * 40,
            share_token="0x" + "c" * 40, underlying_symbol="USDC", name="V",
            fetched_at=NOW, observed_at=NOW, observed_at_policy="FETCHED_AT",
            source_uri="https://test", adapter="morpho-graphql",
            adapter_version="morpho-graphql-v1",
            source_type=EvidenceConfidence.NATIVE_ENRICHED,
            apy_total=Decimal("0.04"), apy_total_30d_avg=total_30d,
            apy_base_30d_avg=base_30d,
            apy_30d_avg_source="MORPHO_NATIVE" if total_30d is not None else None,
        )

    for bad in (float("nan"), float("inf"), Decimal("-5"), Decimal("500")):
        with pytest.raises((ObservationRejected, InvalidOperation, ValueError)):
            observation_with(total_30d=bad).validate()   # NaN/inf/out-of-policy
    with pytest.raises((ObservationRejected, InvalidOperation, ValueError)):
        observation_with(total_30d=Decimal("0.0395"), base_30d=float("nan")).validate()
    # valid values pass; missing stays UNAVAILABLE
    observation_with(total_30d=Decimal("0.0395"),
                     base_30d=Decimal("0.0310")).validate()
    observation_with(total_30d=None, base_30d=None).validate()

    # adapter-level: a non-numeric STRING from the provider is schema-rejected
    with pytest.raises(httpx.HTTPStatusError if False else Exception) as exc_info:
        _morpho_observation({"avgNetApy": "NaN", "avgNetApyExcludingRewards": 0.031,
                             "netApyExcludingRewards": 0.035})
    assert "SOURCE_SCHEMA_REJECTED" in str(exc_info.value) or         getattr(exc_info.value, "code", "") == "SOURCE_SCHEMA_REJECTED" or         type(exc_info.value).__name__ == "SourceProviderError"


def test_morpho_native_label_requires_total_30d_average():
    """Base-only 30d data must NOT label the total-APY 30d value MORPHO_NATIVE."""
    observation = _morpho_observation({
        "avgNetApy": None, "avgNetApyExcludingRewards": 0.031,
        "netApyExcludingRewards": 0.035,
    })
    assert observation.apy_base_30d_avg == Decimal("0.0310")
    assert observation.apy_total_30d_avg is None
    assert observation.apy_30d_avg_source is None


# ── Treasury TTL cache ───────────────────────────────────────────────────────

def test_treasury_ttl_caches_upstream_reads(monkeypatch):
    from datetime import date
    from finco_yield import treasury as treasury_mod
    from app.radar_economy.contracts import EconomyObservation, EconomyState

    treasury_mod.reset_treasury_cache()
    calls = []

    class FakeProvider:
        def read(self, definition):
            calls.append(definition.source_series_id)
            return EconomyObservation(
                key=definition.key, state=EconomyState.FRESH,
                value=Decimal("4.28"), previous=None, period=date(2026, 10, 2),
                retrieved_at=NOW, source_series_id="DGS3MO",
                publisher="FRB", transport="FRED")

    monkeypatch.setattr(treasury_mod, "FredEconomyProvider", FakeProvider)
    first = treasury_mod.latest_treasury()
    second = treasury_mod.latest_treasury()
    assert first.usable and second.usable
    assert calls == ["DGS3MO"], "second read within TTL must not re-hit FRED"
    treasury_mod.reset_treasury_cache()


def test_treasury_unavailable_is_negatively_cached_and_typed(monkeypatch):
    from finco_yield import treasury as treasury_mod
    treasury_mod.reset_treasury_cache()
    calls = []

    class FailingProvider:
        def read(self, definition):
            calls.append(1)
            raise RuntimeError("network down")

    monkeypatch.setattr(treasury_mod, "FredEconomyProvider", FailingProvider)
    first = treasury_mod.latest_treasury()
    second = treasury_mod.latest_treasury()
    assert calls == [1], "typed-unavailable reads are negatively cached"
    assert not first.usable and not second.usable
    assert first.state == "UNAVAILABLE" and second.state == "UNAVAILABLE"
    assert first.yield_percent is None
    treasury_mod.reset_treasury_cache()


def test_no_defillama_integration_anywhere():
    import pathlib
    for path in pathlib.Path("finco_yield").rglob("*.py"):
        text = path.read_text(encoding="utf-8").lower()
        assert "defillama" not in text, f"{path} must not integrate DeFiLlama"


# ── entitlement + route contracts ────────────────────────────────────────────

def test_history_entitlement_denied_detail_renders_without_leak(monkeypatch, tmp_path):
    """HISTORY entitlement denied -> detail renders 200 with no intelligence
    and no exception (the _intel name used to be unbound on this path)."""
    from fastapi import FastAPI
    from fastapi.testclient import TestClient
    from finco_yield import access as access_mod
    from finco_yield.web import router

    store = YieldHistoryStore(tmp_path / "h.jsonl")
    _record(store, "yld_a", NOW - timedelta(hours=0.2), "0.0440")
    monkeypatch.setenv("FINCO_YIELD_ENABLED", "1")
    monkeypatch.setenv("FINCO_YIELD_HISTORY_PATH", str(store.path))
    monkeypatch.setenv("FINCO_TOKEN_GATING_ENABLED", "1")

    from app.protocol.entitlement_evaluator import Decision, ResourceAccessDecision

    async def fake(resource_key, wallet):
        return ResourceAccessDecision(
            resource_key=resource_key, decision=Decision.DENY,
            reason_code="BALANCE_BELOW_THRESHOLD", access_mode="FINCO_HOLDER",
            wallet_address=wallet, chain_id=None, token_address=None,
            entitlement_state=None, observed_balance=None, minimum_balance=None,
            observed_at=None)

    monkeypatch.setattr(access_mod, "evaluate_resource_access", fake)
    app = FastAPI()
    app.include_router(router)
    client = TestClient(app)
    from finco_yield.registry import load_bundled_registry
    uid = load_bundled_registry().all()[0].uid
    response = client.get(f"/yield/{uid}")
    assert response.status_code == 200
    assert "ACCESS_RESTRICTED" in response.text
    assert "intel-latest-observed" not in response.text  # no intelligence leak


def test_explore_route_treasury_read_is_offloaded(monkeypatch):
    """The Explore route must not call the (cached) Treasury reader inline on
    the event loop — it goes through run_in_threadpool."""
    web_src = open("finco_yield/web.py", encoding="utf-8").read()
    assert "await run_in_threadpool(latest_treasury)" in web_src
    assert "from fastapi.concurrency import run_in_threadpool" in web_src
