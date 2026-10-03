"""Correction A test additions for PR #177.

Appends exact-binding, basis-freshness, reference-reuse, per-underlying
history, unknown-underlying, landing batching and overall-state coverage.
"""
from __future__ import annotations

from datetime import datetime, timedelta, timezone
from decimal import Decimal
from types import SimpleNamespace

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from tests.test_tokenized_markets_composition import (
    NOW,
    ROBINHOOD_NVDA,
    TestComposition,
    TestTokenizedMarketsSurface,
    _compose,
    _entry,
    _fresh_observation,
    _reference_rows,
    _registry,
    _tmp_store,
)


def _underlying(**overrides):
    from finco_radar.venues.registry import parse_underlying
    base = dict(canonical_symbol="NVDA", underlying_isin="US67066G1040",
                underlying_name="NVIDIA", sources=("test",))
    base.update(overrides)
    return parse_underlying(base)


class TestExactStoreBinding:
    """Correction A #3/#4: store observations bind to the EXACT expected
    venue AND canonical underlying."""

    def test_exact_instrument_and_venue_resolves(self):
        registry = _registry([_entry()])
        store = VenueMarketStore(_tmp_store())
        _fresh_observation(store, instrument_id=ROBINHOOD_NVDA,
                           canonical="NVDA", price="196.00")
        view = _compose(registry, store=store, reference_rows=[])
        assert view.representations[0].price == "196.00"
        assert view.representations[0].venue_id == "robinhood-chain"

    def test_same_instrument_wrong_venue_does_not_resolve(self):
        registry = _registry([_entry()])
        store = VenueMarketStore(_tmp_store())
        # Observation stored under venue 'xstocks' — the registry row expects
        # venue 'robinhood-chain'.  Cross-venue evidence must not attach.
        _fresh_observation(store, instrument_id=ROBINHOOD_NVDA,
                           canonical="NVDA", price="999.00", venue="xstocks")
        view = _compose(registry, store=store, reference_rows=[])
        assert view.representations[0].price is None
        assert view.representations[0].freshness_state == "UNAVAILABLE"

    def test_correct_venue_wrong_canonical_underlying_does_not_resolve(self):
        registry = _registry([_entry()])
        store = VenueMarketStore(_tmp_store())
        # Right venue+instrument, but the observation claims AAPL.
        _fresh_observation(store, instrument_id=ROBINHOOD_NVDA,
                           canonical="AAPL", price="999.00")
        view = _compose(registry, store=store, reference_rows=[])
        assert view.representations[0].price is None
        assert view.representations[0].freshness_state == "UNAVAILABLE"

    def test_cross_venue_collision_resolves_only_own_venue(self):
        """Same instrument_id on venues A and B with different prices:
        composing venue A's representation resolves ONLY venue A's price."""
        registry = _registry([_entry()])
        store = VenueMarketStore(_tmp_store())
        _fresh_observation(store, instrument_id=ROBINHOOD_NVDA,
                           canonical="NVDA", price="196.00",
                           venue="robinhood-chain")
        _fresh_observation(store, instrument_id=ROBINHOOD_NVDA,
                           canonical="NVDA", price="420.00", venue="xstocks")
        view = _compose(registry, store=store, reference_rows=[])
        assert view.representations[0].price == "196.00"


class TestBasisFreshnessAuthority:
    """Correction A #5/#6: basis only from AVAILABLE source evidence with a
    source stamp; freshness authority overrides clock compatibility."""

    def _store_with(self, price="196.00", *, ts=None, freshness="AVAILABLE"):
        from finco_radar.venues.observations import (
            FreshnessState, MarketObservation, ObservationStatus)
        store = VenueMarketStore(_tmp_store())
        observation = MarketObservation(
            ts=ts,
            collected_at=(NOW - timedelta(seconds=30)).isoformat(),
            canonical_asset_id="NVDA",
            venue_id="robinhood-chain",
            instrument_id=ROBINHOOD_NVDA,
            instrument_type="tokenized-equity",
            price=price,
            source="persisted-evidence",
            freshness_state=FreshnessState(freshness),
            observation_status=ObservationStatus.OK,
            payload={},
        )
        store.append_observation(observation)
        return store

    def test_collected_at_never_substitutes_for_missing_source_timestamp(self):
        registry = _registry([_entry()])
        store = self._store_with(ts=None)  # valid FINCO collection time only
        view = _compose(registry, store=store,
                        reference_rows=_reference_rows("NVDA"))
        rep = view.representations[0]
        assert rep.price == "196.00"
        assert rep.source_timestamp is None
        assert rep.basis_bps is None
        assert rep.basis_reason == "EVIDENCE_TIMESTAMP_UNAVAILABLE"

    def test_representation_stale_blocks_basis_despite_fresh_reference(self):
        registry = _registry([_entry()])
        store = self._store_with(ts=(NOW - timedelta(seconds=30)).isoformat(),
                                 freshness="STALE")
        view = _compose(registry, store=store,
                        reference_rows=_reference_rows("NVDA"))
        rep = view.representations[0]
        assert rep.basis_bps is None
        assert rep.basis_reason == "REPRESENTATION_STALE"

    def test_reference_stale_blocks_basis_despite_fresh_representation(self):
        registry = _registry([_entry()])
        store = self._store_with(ts=(NOW - timedelta(seconds=30)).isoformat())
        view = _compose(registry, store=store, reference_rows=_reference_rows(
            "NVDA", state="STALE"))
        rep = view.representations[0]
        assert rep.basis_bps is None
        assert rep.basis_reason == "REFERENCE_STALE"

    def test_two_stale_agreeing_stamps_still_produce_no_basis(self):
        registry = _registry([_entry()])
        stale_stamp = (NOW - timedelta(minutes=10)).isoformat()
        store = self._store_with(ts=stale_stamp, freshness="STALE")
        view = _compose(registry, store=store, reference_rows=_reference_rows(
            "NVDA", state="STALE", observed_at=stale_stamp))
        rep = view.representations[0]
        assert rep.basis_bps is None
        assert rep.basis_reason == "REPRESENTATION_STALE"

    def test_valid_fresh_pair_with_compatible_stamps_produces_basis(self):
        registry = _registry([_entry()])
        stamp = (NOW - timedelta(seconds=30)).isoformat()
        store = self._store_with(ts=stamp)
        view = _compose(registry, store=store, reference_rows=_reference_rows(
            "NVDA", observed_at=stamp))
        rep = view.representations[0]
        assert rep.basis_bps == "51"


class TestReferenceReuse:
    """Correction A #7: one compose → at most one reference_reader call."""

    def test_reference_reader_called_once_per_compose(self):
        registry = _registry([_entry()])
        calls: list[str] = []

        def reader(symbol):
            calls.append(symbol)
            return _reference_rows(symbol)

        # With perp seam AND store — every consumer reuses the one read.
        store = VenueMarketStore(_tmp_store())
        _fresh_observation(store, instrument_id=ROBINHOOD_NVDA,
                           canonical="NVDA", price="196.00",
                           observed_at=NOW - timedelta(seconds=30))

        def perp_lookup(symbol):
            return {"instrument_id": "NVDA-PERP", "price": "196.50",
                    "source_timestamp": (NOW - timedelta(seconds=30)).isoformat()}

        view = _compose(registry, reference_rows=None, store=store,
                        perp_lookup=perp_lookup, reference_reader=reader)
        assert calls == ["NVDA"]
        perp = next(r for r in view.representations
                    if r.venue_id == "hyperliquid")
        assert perp.basis_bps is not None  # computed from the reused reference


class TestHistoryTruth:
    """Correction A #9/#10: per-underlying history availability."""

    def test_unrelated_asset_history_does_not_promote(self):
        registry = _registry([_entry(), _entry(
            representation_symbol="AAPL", underlying_symbol="AAPL",
            contract_address="0x" + "77" * 20, source="test")])
        registry._underlyings["AAPL"] = _underlying(canonical_symbol="AAPL")
        store = VenueMarketStore(_tmp_store())
        _fresh_observation(store, instrument_id=ROBINHOOD_NVDA,
                           canonical="NVDA", price="196.00")
        view = _compose(registry, store=store, reference_rows=[])
        assert view.history_available is True  # NVDA has history

        from app.radar_ui.tokenized_composition import compose_underlying
        aapl_view = compose_underlying(
            "AAPL", registry=registry,
            reference_reader=lambda symbol: [], store=store, now=NOW)
        assert aapl_view.history_available is False  # AAPL does not

    def test_no_store_means_no_history(self):
        registry = _registry([_entry()])
        view = _compose(registry, store=None, reference_rows=[])
        assert view.history_available is False


class TestUnknownUnderlying:
    """Correction A #11: unknown canonical underlying → 404, zero calls."""

    @pytest.fixture()
    def counting_client(self, tmp_path, monkeypatch):
        monkeypatch.setenv("FINCO_VENUE_DB_PATH", str(tmp_path / "venues.db"))
        from app.radar_ui.tokenized_router import router
        app = FastAPI()
        app.include_router(router)
        session = SimpleNamespace(user_id="user-1", username="qa",
                                  login_at=None, session_type="user")
        monkeypatch.setattr("app.auth.resolve_request_session",
                            lambda request: session)

        calls: list[str] = []

        class CountingService:
            def read(self, *, featured_symbols=()):
                calls.extend(featured_symbols)
                return [_reference_rows(s)[0] for s in featured_symbols]

        import app.radar_ui.router as router_module
        monkeypatch.setattr(router_module, "_market_read_service",
                            CountingService())
        return TestClient(app, raise_server_exceptions=False), calls

    def test_unknown_symbol_returns_404(self, counting_client):
        http_client, _calls = counting_client
        page = http_client.get("/radar/tokenized-markets/ZZZZ")
        assert page.status_code == 404
        assert 'data-testid="tmd-unknown"' in page.text

    def test_unknown_symbol_triggers_zero_reference_calls(self, counting_client):
        http_client, calls = counting_client
        http_client.get("/radar/tokenized-markets/ZZZZ")
        assert calls == []

    def test_known_symbol_still_resolves(self, counting_client):
        http_client, calls = counting_client
        page = http_client.get("/radar/tokenized-markets/NVDA")
        assert page.status_code == 200
        assert 'data-testid="tmd-representations"' in page.text


class TestLandingBatchedReference:
    """Correction A #12/#13: N landing rows use ONE batched reference read."""

    def test_landing_batches_reference_reads(self, tmp_path, monkeypatch):
        from finco_radar.venues.registry import parse_underlying
        entries = []
        underlyings = {}
        for ticker in ("AAPL", "NVDA", "MSFT"):
            entries.append(_entry(
                representation_symbol=ticker, underlying_symbol=ticker,
                contract_address="0x" + ticker.encode().hex().ljust(40, "0"),
                source="test"))
            underlyings[ticker] = parse_underlying({
                "canonical_symbol": ticker, "sources": ["test"]})
        from finco_radar.venues.registry import VenueRegistry
        registry = VenueRegistry(underlyings, entries, [])

        monkeypatch.setenv("FINCO_VENUE_DB_PATH", str(tmp_path / "venues.db"))
        monkeypatch.setenv("RADAR_FEATURED_EQUITY_SYMBOLS", "AAPL,NVDA,MSFT")
        from app.radar_ui.tokenized_router import router
        app = FastAPI()
        app.include_router(router)
        session = SimpleNamespace(user_id="user-1", username="qa",
                                  login_at=None, session_type="user")
        monkeypatch.setattr("app.auth.resolve_request_session",
                            lambda request: session)

        board_reads: list[tuple] = []

        class CountingService:
            def read(self, *, featured_symbols=()):
                board_reads.append(tuple(featured_symbols))
                return [_reference_rows(t)[0] for t in featured_symbols]

        import app.radar_ui.router as router_module
        monkeypatch.setattr(router_module, "_market_read_service",
                            CountingService())

        client = TestClient(app, raise_server_exceptions=False)
        page = client.get("/radar/tokenized-markets")
        assert page.status_code == 200
        # 3 composed featured rows → exactly ONE batched board read.
        # ONE batched read covering all three featured symbols
        assert len(board_reads) == 1
        assert sorted(board_reads[0]) == ["AAPL", "MSFT", "NVDA"]


class TestOverallState:
    """Correction A #15: conservative product-state semantics."""

    def test_priced_available_with_unavailable_reference_is_not_fresh(self):
        registry = _registry([_entry()])
        store = VenueMarketStore(_tmp_store())
        _fresh_observation(store, instrument_id=ROBINHOOD_NVDA,
                           canonical="NVDA", price="196.00")
        view = _compose(registry, store=store, reference_rows=[
            {"state": "UNAVAILABLE", "price": None, "observed_at": None,
             "source": None, "symbol": "NVDA"}])
        assert view.overall_state in ("PARTIAL", "STALE")
        assert view.overall_state != "FRESH"

    def test_priced_available_with_fresh_reference_is_fresh(self):
        registry = _registry([_entry()])
        store = VenueMarketStore(_tmp_store())
        _fresh_observation(store, instrument_id=ROBINHOOD_NVDA,
                           canonical="NVDA", price="196.00",
                           observed_at=NOW - timedelta(seconds=30))
        view = _compose(registry, store=store, reference_rows=_reference_rows(
            "NVDA", observed_at=(NOW - timedelta(seconds=30)).isoformat()))
        assert view.overall_state == "FRESH"

    def test_identity_only_is_unavailable(self):
        registry = _registry([_entry()])
        view = _compose(registry, store=VenueMarketStore(_tmp_store()),
                        reference_rows=[])
        assert view.overall_state == "UNAVAILABLE"


class TestHyperliquidScopeTruth:
    def test_no_fuzzy_mapping_in_composition(self):
        import app.radar_ui.tokenized_composition as comp
        source = open(comp.__file__, encoding="utf-8").read()
        assert "fuzzy" not in source.lower() or "no fuzzy" in source.lower()
        # The perp seam is consulted only with the exact requested symbol.
        registry = _registry([_entry()])
        calls: list[str] = []

        def perp_lookup(symbol):
            calls.append(symbol)
            return None

        _compose(registry, reference_rows=_reference_rows("NVDA"),
                 perp_lookup=perp_lookup)
        assert calls == ["NVDA"]


from finco_radar.venues.store import VenueMarketStore  # noqa: E402
