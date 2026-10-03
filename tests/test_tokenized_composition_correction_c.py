"""PR #177 Correction C — final Tokenized Markets composition authority."""

from datetime import timedelta

from finco_radar.venues.store import VenueMarketStore

from tests.test_tokenized_markets_composition import (
    NOW,
    ROBINHOOD_NVDA,
    _compose,
    _entry,
    _fresh_observation,
    _reference_rows,
    _registry,
    _tmp_store,
)


def _xstocks_entry():
    return _entry(
        platform="xstocks",
        representation_symbol="NVDAx",
        network="xstocks",
        chain_id=None,
        contract_address="0x" + "88" * 20,
        source="xstocks-official-api",
        source_ref="xstocks-api",
    )


class TestOverallStateCompleteness:
    def test_partial_representation_coverage_cannot_be_fresh(self):
        registry = _registry([_entry(), _xstocks_entry()])
        store = VenueMarketStore(_tmp_store())
        _fresh_observation(
            store,
            instrument_id=ROBINHOOD_NVDA,
            canonical="NVDA",
            price="196.00",
            observed_at=NOW - timedelta(seconds=30),
        )
        view = _compose(
            registry,
            store=store,
            reference_rows=_reference_rows(
                "NVDA",
                observed_at=(NOW - timedelta(seconds=30)).isoformat(),
            ),
        )
        robinhood = next(r for r in view.representations if r.venue_id == "robinhood-chain")
        xstocks = next(r for r in view.representations if r.venue_id == "xstocks")
        assert robinhood.has_market_data is True
        assert xstocks.has_market_data is False
        assert xstocks.freshness_state == "UNAVAILABLE"
        assert view.overall_state == "PARTIAL"

    def test_fully_available_representation_set_can_be_fresh(self):
        registry = _registry([_entry(), _xstocks_entry()])
        store = VenueMarketStore(_tmp_store())
        stamp = NOW - timedelta(seconds=30)
        _fresh_observation(
            store,
            instrument_id=ROBINHOOD_NVDA,
            canonical="NVDA",
            price="196.00",
            observed_at=stamp,
        )
        _fresh_observation(
            store,
            instrument_id="0x" + "88" * 20,
            canonical="NVDA",
            price="195.50",
            venue="xstocks",
            observed_at=stamp,
        )
        view = _compose(
            registry,
            store=store,
            reference_rows=_reference_rows("NVDA", observed_at=stamp.isoformat()),
        )
        assert len(view.representations) == 2
        assert all(r.has_market_data and r.freshness_state == "AVAILABLE"
                   for r in view.representations)
        assert view.overall_state == "FRESH"


class TestHyperliquidFinalAuthority:
    def _perp(self, **overrides):
        row = {
            "instrument_id": "NVDA-PERP",
            "price": "196.50",
            "funding_rate": "0.0001",
            "open_interest": "1234.5",
            "source_timestamp": (NOW - timedelta(seconds=30)).isoformat(),
            "source": "hyperliquid-adapter",
        }
        row.update(overrides)
        return row

    def test_halted_perp_is_inspectable_but_not_active_and_has_no_basis(self):
        registry = _registry([_entry()])
        view = _compose(
            registry,
            reference_rows=_reference_rows(
                "NVDA",
                observed_at=(NOW - timedelta(seconds=30)).isoformat(),
            ),
            perp_lookup=lambda symbol: self._perp(
                trading_halted=True,
                basis_bps="9999",
            ),
        )
        perp = next(r for r in view.representations if r.venue_id == "hyperliquid")
        assert perp.price == "196.50"
        assert perp.observation_status == "QUARANTINED"
        assert perp.has_market_data is False
        assert perp.basis_bps is None
        assert perp.basis_reason == "REPRESENTATION_QUARANTINED"
        assert perp not in view.priced_representations

    def test_provider_basis_is_ignored_and_finco_recomputes_basis(self):
        registry = _registry([_entry()])
        stamp = (NOW - timedelta(seconds=30)).isoformat()
        view = _compose(
            registry,
            reference_rows=_reference_rows("NVDA", price="195.00", observed_at=stamp),
            perp_lookup=lambda symbol: self._perp(
                source_timestamp=stamp,
                basis_bps="9999",
            ),
        )
        perp = next(r for r in view.representations if r.venue_id == "hyperliquid")
        assert perp.basis_bps == "77"
        assert perp.basis_bps != "9999"
        assert perp.basis_reason is None

    def test_missing_timestamp_still_blocks_basis_even_with_provider_basis(self):
        registry = _registry([_entry()])
        view = _compose(
            registry,
            reference_rows=_reference_rows("NVDA"),
            perp_lookup=lambda symbol: self._perp(
                source_timestamp=None,
                basis_bps="9999",
            ),
        )
        perp = next(r for r in view.representations if r.venue_id == "hyperliquid")
        assert perp.basis_bps is None
        assert perp.basis_reason == "EVIDENCE_TIMESTAMP_UNAVAILABLE"

    def test_stale_reference_still_blocks_finco_basis(self):
        registry = _registry([_entry()])
        stamp = (NOW - timedelta(seconds=30)).isoformat()
        view = _compose(
            registry,
            reference_rows=_reference_rows(
                "NVDA", state="STALE", price="195.00", observed_at=stamp
            ),
            perp_lookup=lambda symbol: self._perp(
                source_timestamp=stamp,
                basis_bps="9999",
            ),
        )
        perp = next(r for r in view.representations if r.venue_id == "hyperliquid")
        assert perp.basis_bps is None
        assert perp.basis_reason == "REFERENCE_STALE"
