"""Tokenized Relative Value & Dislocation Persistence V1 tests (PR #183 Correction A)."""
from __future__ import annotations

from datetime import datetime, timedelta, timezone
from decimal import Decimal
from pathlib import Path

import pytest

from finco_radar.venues.intelligence import build_tokenized_intelligence
from finco_radar.venues.models import Deployment, RepresentationEntry
from finco_radar.venues.observations import (
    FreshnessState, MarketObservation, ObservationStatus,
)
from finco_radar.venues.registry import VenueRegistry, parse_underlying
from finco_radar.venues.relative_value import (
    DislocationStartState, DislocationState,
    compute_basis_distribution, compute_dislocation_persistence,
)
from finco_radar.venues.store import VenueMarketStore

NOW = datetime(2026, 10, 4, 12, 0, 0, tzinfo=timezone.utc)
NVDA_CONTRACT = "0xd0601ce157db5bdc3162bbac2a2c8af5320d9eec"
RECENT = NOW - timedelta(minutes=2)
DIST_START = NOW - timedelta(hours=4)


def _entry(**overrides) -> RepresentationEntry:
    base = dict(
        platform="robinhood", representation_symbol="NVDA",
        underlying_symbol="NVDA", underlying_isin="US67066G1040", isin=None,
        instrument_type="tokenized-equity", name="NVIDIA Token",
        network="robinhood-chain", chain_id=4663,
        contract_address=NVDA_CONTRACT,
        decimals=18, deployment_status="active", trading_halted=None,
        deployments=(), source="test", source_ref="test@rev")
    base.update(overrides)
    return RepresentationEntry(**base)


def _underlying():
    return parse_underlying({"canonical_symbol": "NVDA",
                             "underlying_name": "NVIDIA",
                             "sources": ["test"]})


def _registry(entries) -> VenueRegistry:
    return VenueRegistry({"NVDA": _underlying()}, list(entries), [])


def _tmp_store() -> VenueMarketStore:
    import tempfile
    return VenueMarketStore(Path(tempfile.mkdtemp()) / "venues.db")


def _observation(store, *, basis_bps: str, ts: datetime,
                 reference_price="195.00", instrument_id=NVDA_CONTRACT,
                 venue_id="robinhood-chain", instrument_type="tokenized-equity",
                 canonical="NVDA", freshness="AVAILABLE"):
    price = str((Decimal("195.00") * (1 + Decimal(basis_bps) / 10000))
                .quantize(Decimal("0.01")))
    observation = MarketObservation(
        ts=ts.isoformat(),
        collected_at=(ts + timedelta(seconds=5)).isoformat(),
        canonical_asset_id=canonical, venue_id=venue_id,
        instrument_id=instrument_id, instrument_type=instrument_type,
        price=price, reference_price=reference_price,
        source="persisted-evidence",
        freshness_state=FreshnessState(freshness),
        observation_status=ObservationStatus.OK,
        payload={"reference_state": "FRESH",
                 "reference_observed_at": ts.isoformat()},
    )
    store.append_observation(observation)


def _make_history(store, *, basis_series, instrument_id=NVDA_CONTRACT,
                  venue_id="robinhood-chain",
                  instrument_type="tokenized-equity", canonical="NVDA"):
    for bps, ts in basis_series:
        _observation(store, basis_bps=str(bps), ts=ts,
                     instrument_id=instrument_id, venue_id=venue_id,
                     instrument_type=instrument_type, canonical=canonical)


def _history_obj(store, *, instrument_id=NVDA_CONTRACT,
                 venue_id="robinhood-chain",
                 instrument_type="tokenized-equity"):
    registry = _registry([_entry()])
    intel = build_tokenized_intelligence(
        "NVDA", registry=registry, store=store, as_of=NOW, include_points=True)
    for h in intel.representations:
        if h.instrument_id == instrument_id and h.venue_id == venue_id:
            return h
    from finco_radar.venues.intelligence import RepresentationHistory
    return RepresentationHistory(
        venue_id=venue_id, instrument_id=instrument_id,
        representation_type=instrument_type, current_state="UNAVAILABLE",
        latest_price=None, latest_basis_bps=None, latest_basis_reason=None,
        basis_change_24h_bps=None, basis_change_7d_bps=None, points=())


class TestBasisDistribution:
    def _make(self, basis_values):
        store = _tmp_store()
        series = [(bps, DIST_START + timedelta(minutes=i * 15))
                  for i, bps in enumerate(basis_values)]
        _make_history(store, basis_series=series)
        history = _history_obj(store)
        return compute_basis_distribution(history, now=NOW), history

    def test_percentile_deterministic(self):
        d1, _ = self._make(list(range(20, 140, 10)))
        d2, _ = self._make(list(range(20, 140, 10)))
        assert d1.current_basis_percentile == d2.current_basis_percentile

    def test_minimum_low_percentile(self):
        """The minimum value in the series gets the lowest percentile."""
        d, _ = self._make(list(range(20, 140, 10)) + [5])
        assert d.current_basis_percentile is not None
        assert float(d.current_basis_percentile) < 15.0

    def test_maximum_high_percentile(self):
        values = list(range(10, 120, 10))
        d, _ = self._make(values)
        assert d.current_basis_percentile is not None
        assert float(d.current_basis_percentile) > 85.0

    def test_median_present(self):
        values = list(range(10, 130, 10))
        d, _ = self._make(values)
        assert d.historical_median_basis_bps is not None

    def test_ties_deterministic(self):
        values = [50] * 12
        d1, _ = self._make(values)
        d2, _ = self._make(values)
        assert d1.current_basis_percentile == d2.current_basis_percentile
        assert d1.current_basis_percentile == str(Decimal("50.0"))

    def test_negative_history_works(self):
        values = [-80, -60, -40, -20, 0, 20, 40, 60, 80, 100, 120, 140]
        d, _ = self._make(values)
        assert d.state == "AVAILABLE"

    def test_mixed_premium_discount(self):
        values = [-80, -40, -20, 0, 20, 40, 60, 80, 100, 120]
        d, _ = self._make(values)
        assert d.state == "AVAILABLE"
        assert d.historical_min_basis_bps is not None

    def test_insufficient_count_fails_closed(self):
        d, _ = self._make([50, 60, 70])
        assert d.state == "INSUFFICIENT_HISTORY"

    def test_insufficient_span_fails_closed(self):
        store = _tmp_store()
        series = [(50 + i * 10, NOW - timedelta(seconds=i * 10))
                  for i in range(10)]
        _make_history(store, basis_series=series)
        history = _history_obj(store)
        d = compute_basis_distribution(history, now=NOW)
        assert d.state == "INSUFFICIENT_HISTORY"

    def test_duplicates_do_not_overweight(self):
        store = _tmp_store()
        ts = NOW - timedelta(hours=1)
        for _ in range(3):
            _observation(store, basis_bps="50", ts=ts)
        for i in range(10):
            _observation(store, basis_bps=str(60 + i * 5),
                         ts=ts + timedelta(minutes=i * 10))
        history = _history_obj(store)
        d = compute_basis_distribution(history, now=NOW)
        assert d.usable_observation_count < 14

    def test_quartiles_present(self):
        d, _ = self._make(list(range(10, 130, 10)))
        assert d.historical_q25_basis_bps is not None
        assert d.historical_median_basis_bps is not None
        assert d.historical_q75_basis_bps is not None


class TestDislocationPersistence:
    def _make(self, series, **kwargs) -> DislocationPersistence:
        store = _tmp_store()
        _make_history(store, basis_series=series, **kwargs)
        history = _history_obj(store, **kwargs)
        return compute_dislocation_persistence(history, now=NOW, **kwargs)

    def test_first_above_threshold_is_prehistory(self):
        series = [(150, NOW - timedelta(minutes=3)),
                  (160, NOW - timedelta(minutes=1))]
        result = self._make(series)
        assert result.state == DislocationState.PREMIUM_DISLOCATION.value
        assert result.start_state == (DislocationStartState.
                                      PREHISTORY_UNAVAILABLE.value)
        assert result.started_at is None

    def test_proven_crossing_anchors_start(self):
        series = [(50, RECENT - timedelta(minutes=6)),
                  (150, RECENT - timedelta(minutes=3)),
                  (160, RECENT - timedelta(minutes=1))]
        result = self._make(series)
        assert result.state == DislocationState.PREMIUM_DISLOCATION.value
        assert result.start_state == DislocationStartState.PROVEN_CROSSING.value
        assert result.started_at is not None
        assert result.duration_seconds is not None

    def test_discount_crossing_works(self):
        series = [(-50, RECENT - timedelta(minutes=6)),
                  (-150, RECENT - timedelta(minutes=3)),
                  (-160, RECENT - timedelta(minutes=1))]
        result = self._make(series)
        assert result.state == DislocationState.DISCOUNT_DISLOCATION.value
        assert result.start_state == DislocationStartState.PROVEN_CROSSING.value

    def test_sign_reversal_starts_new_episode(self):
        start = RECENT - timedelta(minutes=12)
        series = [(150, start), (-150, start + timedelta(minutes=6))]
        result = self._make(series)
        assert result.state == DislocationState.DISCOUNT_DISLOCATION.value
        assert result.start_state == DislocationStartState.SIGN_REVERSAL.value
        assert result.started_at is not None

    def test_reverse_sign_reversal_also_new(self):
        start = RECENT - timedelta(minutes=12)
        series = [(-150, start), (150, start + timedelta(minutes=6))]
        result = self._make(series)
        assert result.state == DislocationState.PREMIUM_DISLOCATION.value
        assert result.start_state == DislocationStartState.SIGN_REVERSAL.value

    def test_missing_evidence_breaks_continuity(self):
        start = RECENT - timedelta(minutes=12)
        store = _tmp_store()
        _observation(store, basis_bps="150", ts=start)
        broken = MarketObservation(
            ts=(start + timedelta(minutes=5)).isoformat(),
            collected_at=(start + timedelta(minutes=5)).isoformat(),
            canonical_asset_id="NVDA", venue_id="robinhood-chain",
            instrument_id=NVDA_CONTRACT,
            instrument_type="tokenized-equity",
            price=None, reference_price=None,
            source="persisted-evidence",
            freshness_state=FreshnessState.UNAVAILABLE,
            observation_status=ObservationStatus.OK,
            payload={},
        )
        store.append_observation(broken)
        _observation(store, basis_bps="160", ts=start + timedelta(minutes=10))
        history = _history_obj(store)
        result = compute_dislocation_persistence(history, now=NOW)
        assert result.state == DislocationState.PREMIUM_DISLOCATION.value
        assert result.start_state == DislocationStartState.PROVEN_CROSSING.value
        assert result.started_at is not None
        assert result.duration_seconds is not None
        assert result.duration_seconds < 700

    def test_within_threshold_is_no_dislocation(self):
        series = [(50, RECENT - timedelta(minutes=6)),
                  (60, RECENT - timedelta(minutes=3))]
        result = self._make(series)
        assert result.state == DislocationState.WITHIN_THRESHOLD.value

    def test_no_data_is_unavailable(self):
        store = _tmp_store()
        history = _history_obj(store)
        result = compute_dislocation_persistence(history, now=NOW)
        assert result.state == DislocationState.UNAVAILABLE.value

    def test_stale_evidence_not_current_dislocation(self):
        stale_time = NOW - timedelta(hours=3)
        result = self._make([(150, stale_time),
                             (160, stale_time + timedelta(minutes=5))])
        assert result.state == DislocationState.STALE.value
        assert result.start_state == DislocationStartState.STALE.value

    def test_threshold_equality_positive(self):
        series = [(100, RECENT - timedelta(minutes=6)),
                  (100, RECENT - timedelta(minutes=3))]
        result = self._make(series)
        assert result.state == DislocationState.PREMIUM_DISLOCATION.value

    def test_threshold_equality_negative(self):
        series = [(-100, RECENT - timedelta(minutes=6)),
                  (-100, RECENT - timedelta(minutes=3))]
        result = self._make(series)
        assert result.state == DislocationState.DISCOUNT_DISLOCATION.value


class TestDislocationMonitor:
    def test_monitor_end_to_end_with_real_history(self):
        from finco_radar.venues.relative_value import build_dislocation_monitor
        registry = _registry([_entry()])
        store = _tmp_store()
        series = []
        for i in range(12):
            bps = 50 + i * 10
            ts = NOW - timedelta(hours=3) + timedelta(minutes=i * 15)
            series.append((bps, ts))
        _make_history(store, basis_series=series)
        rows = build_dislocation_monitor(
            registry=registry, store=store, now=NOW, symbols=["NVDA"])
        assert len(rows) >= 1
        row = rows[0]
        assert row.current_basis_bps is not None
        assert row.current_basis_percentile is not None
        assert row.historical_median_basis_bps is not None
        assert row.current_dislocation_duration_seconds is not None
        assert row.observed_at is not None

    def test_monitor_ordering_deterministic(self):
        from finco_radar.venues.relative_value import build_dislocation_monitor
        tsla = parse_underlying({"canonical_symbol": "TSLA",
                                 "sources": ["test"]})
        aapl = parse_underlying({"canonical_symbol": "AAPL",
                                 "sources": ["test"]})
        ts = RECENT - timedelta(minutes=5)
        tsla_entry = RepresentationEntry(
            platform="robinhood", representation_symbol="TSLA",
            underlying_symbol="TSLA", underlying_isin=None, isin=None,
            instrument_type="tokenized-equity", name="Tesla Token",
            network="robinhood-chain", chain_id=4663,
            contract_address="0x" + "aa" * 20, decimals=18,
            deployment_status="active", trading_halted=None,
            deployments=(), source="test", source_ref="test@rev")
        aapl_entry = RepresentationEntry(
            platform="robinhood", representation_symbol="AAPL",
            underlying_symbol="AAPL", underlying_isin=None, isin=None,
            instrument_type="tokenized-equity", name="Apple Token",
            network="robinhood-chain", chain_id=4663,
            contract_address="0x" + "bb" * 20, decimals=18,
            deployment_status="active", trading_halted=None,
            deployments=(), source="test", source_ref="test@rev")
        registry = VenueRegistry(
            {"NVDA": _underlying(), "TSLA": tsla, "AAPL": aapl},
            [_entry(), tsla_entry, aapl_entry], [])
        store = _tmp_store()
        _observation(store, basis_bps="150", ts=ts)
        _observation(store, basis_bps="50", ts=ts,
                     instrument_id="0x" + "aa" * 20, canonical="TSLA")
        _observation(store, basis_bps="120", ts=ts,
                     instrument_id="0x" + "bb" * 20, canonical="AAPL")
        rows = build_dislocation_monitor(
            registry=registry, store=store, now=NOW)
        assert rows[0].canonical_asset_id == "NVDA"
        assert rows[1].canonical_asset_id == "AAPL"
        assert rows[2].canonical_asset_id == "TSLA"


class TestNoDuplication:
    def test_no_new_basis_arithmetic(self):
        source = open("finco_radar/venues/relative_value.py",
                      encoding="utf-8").read()
        assert "def basis_for_evidence" not in source
        assert "def _basis_from_observation" not in source

    def test_threshold_reused(self):
        source = open("finco_radar/venues/relative_value.py",
                      encoding="utf-8").read()
        assert "dislocation_threshold_bps" in source

    def test_intelligence_reused(self):
        source = open("finco_radar/venues/relative_value.py",
                      encoding="utf-8").read()
        assert "build_tokenized_intelligence" in source

    def test_no_opportunity_vocabulary(self):
        source = open("finco_radar/venues/relative_value.py",
                      encoding="utf-8").read()
        for banned in ("Best trades", "Arbitrage opportunities",
                       "Top returns", "opportunity_score"):
            assert banned not in source, banned

    def test_no_prediction_vocabulary(self):
        source = open("finco_radar/venues/relative_value.py",
                      encoding="utf-8").read()
        for banned in ("PERSISTENCE_PROBABILITY", "LIKELY_TO_PERSIST",
                       "MEAN_REVERSION_PROBABILITY", "PRICE_TARGET"):
            assert banned not in source, banned

    def test_no_execution_signing_custody(self):
        source = open("finco_radar/venues/relative_value.py",
                      encoding="utf-8").read()
        for forbidden in ("sign_transaction", "private_key", "broadcast",
                          "execute_trade", "custody"):
            assert forbidden not in source.lower(), forbidden
