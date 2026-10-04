"""Tokenized Markets composition tests (PR 3b).

Proves:
 1. canonical underlying → exact representations (registry authority);
 2. quarantined representation excluded from active composition;
 3. conflict representation excluded;
 4. missing market observation remains UNAVAILABLE, not zero;
 5. xStocks identity without verified price is NOT presented as live;
 6. basis exists only when exact compatible reference + representation
    price exist (otherwise None with typed reason);
 7. basis arithmetic is deterministic;
 8. Robinhood/R-Live identity stays exact (real seed);
 9. Hyperliquid mapping is consulted only by exact canonical symbol;
10. provenance/source is retained on every representation row;
11. history consumes only persisted store observations;
12. history rendering performs no provider acquisition;
13. no synthetic history;
14. no new provider (existing authorities only);
15. financial_engine/** and finco_core/** zero diff (TestFrozen).
"""
from __future__ import annotations

import subprocess
from datetime import datetime, timedelta, timezone
from decimal import Decimal
from pathlib import Path
from types import SimpleNamespace

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

REPO = Path(__file__).resolve().parents[1]

from finco_radar.venues.models import (
    Deployment,
    RegistryStatus,
    RepresentationEntry,
)
from finco_radar.venues.observations import (
    FreshnessState,
    MarketObservation,
    ObservationStatus,
)
from finco_radar.venues.registry import VenueRegistry, parse_underlying
from finco_radar.venues.store import VenueMarketStore

NOW = datetime(2026, 10, 2, 12, 0, 0, tzinfo=timezone.utc)
ROBINHOOD_NVDA = "0xd0601ce157db5bdc3162bbac2a2c8af5320d9eec"


def _entry(**overrides) -> RepresentationEntry:
    base = dict(
        platform="robinhood", representation_symbol="NVDA",
        underlying_symbol="NVDA", underlying_isin="US67066G1040", isin=None,
        instrument_type="tokenized-equity", name="NVIDIA • Robinhood Token",
        network="robinhood-chain", chain_id=4663, contract_address=ROBINHOOD_NVDA,
        decimals=18, deployment_status="active", trading_halted=None,
        deployments=(), source="rwaimport-registry",
        source_ref="dicethedev/rwaimport-registry@a52ab34#assets/robinhood-nvda")
    base.update(overrides)
    return RepresentationEntry(**base)


def _underlying(**overrides):
    base = dict(canonical_symbol="NVDA", underlying_isin="US67066G1040",
                underlying_name="NVIDIA", sources=("test",))
    base.update(overrides)
    return parse_underlying(base)


def _registry(entries, quarantines=None) -> VenueRegistry:
    underlyings = {
        "NVDA": _underlying(),
        "AAPL": parse_underlying({"canonical_symbol": "AAPL",
                                  "sources": ["test"]}),
    }
    return VenueRegistry(underlyings, list(entries), quarantines or [])


def _reference_rows(symbol: str, *, state="FRESH", price="195.00",
                    observed_at=None) -> list[dict]:
    return [{
        "uid": None, "symbol": symbol, "state": state,
        "price": price if state != "UNAVAILABLE" else None,
        "bid": None, "ask": None,
        "observed_at": observed_at or (NOW - timedelta(seconds=30)).isoformat(),
        "source": "bound-reference-authority",
    }]


def _fresh_observation(store: VenueMarketStore, *, instrument_id: str,
                       canonical: str, price: str, venue="robinhood-chain",
                       observed_at=None):
    stamp = observed_at or (NOW - timedelta(seconds=60))
    observation = MarketObservation(
        ts=stamp.isoformat(),
        collected_at=(stamp + timedelta(seconds=5)).isoformat(),
        canonical_asset_id=canonical,
        venue_id=venue,
        instrument_id=instrument_id,
        instrument_type="tokenized-equity",
        price=price,
        source="persisted-evidence",
        freshness_state=FreshnessState.AVAILABLE,
        observation_status=ObservationStatus.OK,
        payload={},
    )
    store.append_observation(observation)


def _tmp_store() -> str:
    import tempfile
    return str(Path(tempfile.mkdtemp()) / "venues.db")


def _compose(registry, *, reference_rows=None, store=None, perp_lookup=None,
             reference_reader=None):
    from app.radar_ui.tokenized_composition import compose_underlying
    if reference_reader is None:
        reference_reader = (lambda symbol: reference_rows or [])
    return compose_underlying(
        "NVDA", registry=registry, reference_reader=reference_reader,
        store=store, perp_lookup=perp_lookup, now=NOW)


class TestComposition:
    def test_canonical_underlying_resolves_exact_representations(self):
        registry = _registry([_entry()])
        resolved = registry.representations_for_underlying("NVDA")
        assert len(resolved) == 1
        assert resolved[0].entry.contract_address == ROBINHOOD_NVDA
        assert resolved[0].entry.underlying_symbol == "NVDA"

    def test_quarantined_representation_excluded_from_composition(self):
        registry = _registry([_entry()], quarantines=[
            {"chain_id": 4663, "contract_address": ROBINHOOD_NVDA,
             "classification": "impostor"}])
        assert registry.representations_for_underlying("NVDA") == []

    def test_conflict_representation_excluded_from_composition(self):
        registry = _registry([
            _entry(source="source-a"),
            _entry(source="source-b", contract_address="0x" + "bb" * 20),
        ])
        assert registry.resolve_exact_instrument(
            platform="robinhood", symbol="NVDA",
            network="robinhood-chain") is None
        assert all(registry.status_for(e) is RegistryStatus.CONFLICT
                   for e in registry._entries)

    def test_missing_observation_is_unavailable_not_zero(self):
        registry = _registry([_entry()])
        view = _compose(registry, reference_rows=[])
        assert len(view.representations) == 1
        rep = view.representations[0]
        assert rep.price is None
        assert rep.freshness_state == "UNAVAILABLE"
        assert rep.basis_bps is None
        assert rep.basis_reason == "REPRESENTATION_PRICE_UNAVAILABLE"
        assert not rep.has_market_data

    def test_xstocks_identity_without_price_not_presented_live(self):
        xstocks = _entry(
            platform="xstocks", representation_symbol="NVDAx",
            network=None, chain_id=None, contract_address=None, decimals=None,
            deployment_status=None,
            deployments=(Deployment(network="ethereum", chain_id=None,
                                    contract_address="0x" + "22" * 20,
                                    decimals=18),),
            source="xstocks-official-api", source_ref="xstocks-api")
        registry = _registry([_entry(), xstocks])
        view = _compose(registry, reference_rows=_reference_rows("NVDA"))
        xstocks_view = next(r for r in view.representations
                            if r.venue_id == "xstocks")
        assert xstocks_view.price is None
        assert xstocks_view.freshness_state == "UNAVAILABLE"
        assert "unavailable" in xstocks_view.basis_reason.lower()
        assert xstocks_view.provenance == "xstocks-api"

    def test_basis_only_when_exact_compatible_reference_and_price(self):
        registry = _registry([_entry()])
        store = VenueMarketStore(_tmp_store())
        _fresh_observation(store, instrument_id=ROBINHOOD_NVDA,
                           canonical="NVDA", price="196.00")
        view = _compose(registry, store=store, reference_rows=_reference_rows(
            "NVDA", price="195.00",
            observed_at=(NOW - timedelta(seconds=60)).isoformat()))
        rep = view.representations[0]
        assert rep.price == "196.00"
        assert rep.basis_bps is not None
        view = _compose(registry, store=store, reference_rows=[])
        assert view.representations[0].basis_bps is None
        assert view.representations[0].basis_reason == "REFERENCE_UNAVAILABLE"

    def test_basis_arithmetic_deterministic(self):
        from app.radar_ui.tokenized_composition import compute_basis_bps
        assert compute_basis_bps("196.00", "195.00") == Decimal(51)
        assert compute_basis_bps("195.00", "196.00") == Decimal(-51)
        assert compute_basis_bps("195.00", "195.00") == Decimal(0)

    def test_basis_skew_policy_blocks_stale_pairs(self):
        registry = _registry([_entry()])
        store = VenueMarketStore(_tmp_store())
        _fresh_observation(store, instrument_id=ROBINHOOD_NVDA,
                           canonical="NVDA", price="196.00",
                           observed_at=NOW - timedelta(minutes=10))
        view = _compose(registry, store=store, reference_rows=_reference_rows("NVDA"))
        rep = view.representations[0]
        assert rep.basis_bps is None
        assert rep.basis_reason == "EVIDENCE_SKEW_EXCEEDS_POLICY"

    def test_robinhood_identity_remains_exact_real_seed(self):
        registry = VenueRegistry.load()
        resolved = registry.resolve_exact_instrument(
            platform="robinhood", symbol="NVDA", network="robinhood-chain")
        assert resolved is not None
        assert resolved.entry.contract_address == ROBINHOOD_NVDA

    def test_hyperliquid_seam_is_exact_only(self):
        registry = _registry([_entry()])
        calls: list[str] = []

        def perp_lookup(symbol: str):
            calls.append(symbol)
            if symbol != "NVDA":
                return None
            return {"instrument_id": "NVDA-PERP", "price": "196.50",
                    "funding_rate": "0.0001", "open_interest": "1234.5",
                    "source_timestamp": (NOW - timedelta(seconds=20)).isoformat(),
                    "source": "hyperliquid-adapter"}

        view = _compose(registry, reference_rows=_reference_rows("NVDA"),
                        perp_lookup=perp_lookup)
        assert calls == ["NVDA"]
        perp = next(r for r in view.representations if r.venue_id == "hyperliquid")
        assert perp.instrument_id == "NVDA-PERP"
        assert perp.price == "196.50"
        assert perp.basis_bps is not None
        assert perp.funding_rate == "0.0001" and perp.open_interest == "1234.5"

    def test_provenance_retained_on_every_representation(self):
        registry = _registry([_entry()])
        view = _compose(registry, reference_rows=[])
        assert all(r.provenance for r in view.representations)

    def test_history_comes_only_from_persisted_store(self):
        registry = _registry([_entry()])
        store = VenueMarketStore(_tmp_store())
        _fresh_observation(store, instrument_id=ROBINHOOD_NVDA,
                           canonical="NVDA", price="196.00")
        view = _compose(registry, store=store, reference_rows=[])
        assert view.representations[0].price == "196.00"
        assert view.representations[0].source == "persisted-evidence"
        assert view.history_available

    def test_history_rendering_performs_no_provider_acquisition(self):
        registry = _registry([_entry()])
        calls: list[str] = []

        def reader(symbol):
            calls.append(symbol)
            return []

        store = VenueMarketStore(_tmp_store())
        _fresh_observation(store, instrument_id=ROBINHOOD_NVDA,
                           canonical="NVDA", price="196.00")
        view = _compose(registry, store=store, reference_rows=None,
                        reference_reader=reader)
        assert calls == ["NVDA"]
        assert view.representations[0].price == "196.00"

    def test_no_synthetic_history(self):
        store = VenueMarketStore(_tmp_store())
        registry = _registry([_entry()])
        view = _compose(registry, store=store, reference_rows=[])
        assert view.history_available is False
        assert store.count() == 0
        assert all(r.price is None for r in view.representations)

    def test_no_new_provider_registered(self):
        import app.radar_ui.tokenized_composition as comp
        source = open(comp.__file__, encoding="utf-8").read()
        for forbidden in ("requests.", "ccxt", "alpaca", "polygon.io",
                          "coingecko.com/api", "new_provider"):
            assert forbidden not in source, forbidden


# ── HTTP surface ──────────────────────────────────────────────────────────────

class TestTokenizedMarketsSurface:
    @pytest.fixture()
    def client(self, tmp_path, monkeypatch):
        monkeypatch.setenv("FINCO_VENUE_DB_PATH", str(tmp_path / "venues.db"))
        from app.radar_ui.tokenized_router import router
        app = FastAPI()
        app.include_router(router)
        session = SimpleNamespace(user_id="user-1", username="qa",
                                  login_at=None, session_type="user")
        monkeypatch.setattr("app.auth.resolve_request_session",
                            lambda request: session)
        return TestClient(app, raise_server_exceptions=False)

    def test_landing_renders_with_empty_history(self, client):
        page = client.get("/radar/tokenized-markets")
        assert page.status_code == 200
        assert 'data-testid="tokenized-markets-table"' in page.text
        assert "economic underlying" in page.text  # lede (capitalized in copy)
        assert 'data-testid="tm-history-note"' in page.text

    def test_landing_primary_list_excludes_identity_only_rows_and_catalog_keeps_them(self, client):
        # Product-reality contract: an identity with no persisted market evidence is NOT a primary
        # public row; it stays reachable through the research identity catalog and detail deep link.
        page = client.get("/radar/tokenized-markets")
        assert 'data-testid="tm-row-NVDA"' not in page.text
        assert 'data-testid="tm-empty"' in page.text
        catalog = client.get("/radar/tokenized-markets?view=catalog")
        assert 'href="/radar/tokenized-markets/NVDA"' in catalog.text
        assert 'data-testid="tm-catalog-row-NVDA"' in catalog.text
        assert client.get("/radar/tokenized-markets/NVDA").status_code == 200

    def test_detail_shows_representations_and_truth_states(self, client):
        page = client.get("/radar/tokenized-markets/NVDA")
        assert page.status_code == 200
        assert 'data-testid="tmd-reference"' in page.text
        assert 'data-testid="tmd-representations"' in page.text
        assert ROBINHOOD_NVDA in page.text
        assert "identity available · market unavailable" in page.text
        assert 'data-testid="tmd-history-none"' in page.text
        assert "No canonical FINCO history collected yet" in page.text


# ── Frozen namespaces ─────────────────────────────────────────────────────────

class TestFrozen:
    @pytest.mark.parametrize("namespace", ["financial_engine", "finco_core"])
    def test_zero_diff(self, namespace):
        out = subprocess.run(
            ["git", "diff", "--name-only", "origin/main..HEAD", "--", namespace],
            cwd=REPO, capture_output=True, text=True)
        if out.returncode != 0:
            pytest.skip("git unavailable")
        assert out.stdout.strip() == "", out.stdout
