"""Tokenized Markets foundation tests — registry, xStocks adapter,
observation store, isolated collector (PR 3a).

Registry: exact identity resolution, cross-source agreement collapse,
conflict exclusion, impostor quarantine, missing-stays-missing,
seed determinism, duplicate collapse.
xStocks: pagination, parse, halt, malformed/timeout/HTTP errors —
deterministic fixtures, no live API in CI.
Store: append-only semantics, digest dedupe, NULL missing, decimal
round-trip, clock separation, exact filters, deterministic windows.
Collector: fixture → observation → digest → store; typed failure with no
fabrication and no history rewrite.
"""
from __future__ import annotations

import json
from datetime import datetime, timedelta, timezone
from decimal import Decimal

import pytest

from finco_radar.venues.models import (
    CanonicalUnderlying,
    RegistryStatus,
    RepresentationEntry,
    canonical_underlying_symbol,
)
from finco_radar.venues.observations import (
    FreshnessState,
    MarketObservation,
    ObservationStatus,
)
from finco_radar.venues.registry import VenueRegistry
from finco_radar.venues.seed_loader import SeedError, load_registry_entries
from finco_radar.venues.store import VenueMarketStore

NOW = datetime(2026, 10, 2, 12, 0, 0, tzinfo=timezone.utc)


def _entry(**overrides) -> RepresentationEntry:
    base = dict(
        platform="robinhood", representation_symbol="NVDA",
        underlying_symbol="NVDA", underlying_isin="US67066G1040", isin=None,
        instrument_type="tokenized-equity", name="NVIDIA • Robinhood Token",
        network="robinhood-chain", chain_id=4663,
        contract_address="0xd0601ce157db5bdc3162bbac2a2c8af5320d9eec",
        decimals=18, deployment_status="active", trading_halted=None,
        deployments=(), source="test-source", source_ref="test@rev")
    base.update(overrides)
    return RepresentationEntry(**base)


def _underlying(**overrides) -> CanonicalUnderlying:
    base = dict(canonical_symbol="NVDA", underlying_isin="US67066G1040",
                underlying_name="NVIDIA", sources=("test-source",))
    base.update(overrides)
    return CanonicalUnderlying(**base)


def _registry(entries, underlyings=None, quarantines=None) -> VenueRegistry:
    if underlyings is None:
        underlyings = {"NVDA": _underlying()}
    return VenueRegistry(
        underlyings, list(entries), quarantines or [])


# ── Registry ──────────────────────────────────────────────────────────────────

class TestRegistryIdentity:
    def test_exact_underlying_lookup(self):
        registry = _registry([_entry()])
        underlying = registry.get_underlying("nvda")
        assert underlying is not None
        assert underlying.canonical_symbol == "NVDA"
        assert underlying.underlying_isin == "US67066G1040"
        assert registry.get_underlying("nope") is None
        assert registry.get_underlying("") is None

    def test_exact_chain_contract_lookup(self):
        registry = _registry([_entry()])
        rows = registry.representation_by_contract(
            chain_id=4663, contract_address="0xD0601CE157Db5bdC3162BbaC2a2C8aF5320D9EEC")
        assert len(rows) == 1
        entry, status = rows[0]
        assert entry.underlying_symbol == "NVDA"
        assert status is RegistryStatus.ACTIVE

    def test_conflicting_sources_do_not_silently_resolve(self):
        registry = _registry([
            _entry(source="source-a", contract_address="0x" + "aa" * 20),
            _entry(source="source-b", contract_address="0x" + "bb" * 20),
        ])
        assert registry.resolve_exact_instrument(
            platform="robinhood", symbol="NVDA",
            network="robinhood-chain") is None
        statuses = {registry.status_for(e) for e in registry._entries}
        assert statuses == {RegistryStatus.CONFLICT}

    def test_agreeing_sources_collapse_to_one_instrument(self):
        registry = _registry([
            _entry(source="source-a"),
            _entry(source="source-b"),
        ])
        resolved = registry.resolve_exact_instrument(
            platform="robinhood", symbol="NVDA", network="robinhood-chain")
        assert resolved is not None
        assert resolved.status is RegistryStatus.ACTIVE

    def test_known_impostor_is_quarantined_and_cannot_resolve(self):
        impostor = _entry(source="impostor-source",
                          contract_address="0xdecf74e4aa6ff30b1612e65665aaf650bedecba3")
        quarantines = [{"chain_id": 4663,
                        "contract_address": impostor.contract_address,
                        "classification": "impostor"}]
        registry = _registry([_entry(), impostor], quarantines=quarantines)
        status = registry.status_for(impostor)
        assert status is RegistryStatus.QUARANTINED
        # Canonical resolution ignores the quarantined row entirely.
        resolved = registry.resolve_exact_instrument(
            platform="robinhood", symbol="NVDA", network="robinhood-chain")
        assert resolved is not None
        assert resolved.entry.contract_address != impostor.contract_address
        # Quarantined contract cannot produce an underlying.
        assert registry.underlying_for_contract(
            chain_id=4663,
            contract_address=impostor.contract_address) is None

    def test_missing_metadata_stays_missing(self):
        entry = _entry(underlying_symbol=None, underlying_isin=None,
                       isin=None, name=None, decimals=None)
        registry = _registry([entry], underlyings={})
        assert registry.underlying_for_contract(
            chain_id=4663,
            contract_address=entry.contract_address) is None
        assert entry.decimals is None
        assert registry.get_underlying("NVDA") is None

    def test_real_seed_loads_and_resolves_robinhood_nvda(self):
        registry = VenueRegistry.load()
        resolved = registry.resolve_exact_instrument(
            platform="robinhood", symbol="NVDA", network="robinhood-chain")
        assert resolved is not None
        assert resolved.entry.contract_address == (
            "0xd0601ce157db5bdc3162bbac2a2c8af5320d9eec")
        assert resolved.status is RegistryStatus.ACTIVE
        stats = registry.stats()
        assert stats["entries"] >= 2000
        assert stats["underlyings"] >= 1000

    def test_real_seed_impostor_contract_is_quarantined(self):
        registry = VenueRegistry.load()
        rows = registry.representation_by_contract(
            chain_id=4663, contract_address="0xdecf74e4aa6ff30b1612e65665aaf650bedecba3")
        # The known impostor contract is not a canonical row at all.
        assert all(status is not RegistryStatus.ACTIVE for _e, status in rows)
        assert registry.underlying_for_contract(
            chain_id=4663,
            contract_address="0xdecf74e4aa6ff30b1612e65665aaf650bedecba3") is None

    def test_real_seed_xstocks_mapping(self):
        registry = VenueRegistry.load()
        resolved = registry.resolve_exact_instrument(
            platform="xstocks", symbol="AAPLx")
        assert resolved is not None
        assert resolved.entry.underlying_symbol == "AAPL"
        assert resolved.entry.deployments, "xStocks asset carries deployments"
        networks = {d.network for d in resolved.entry.deployments}
        assert "ethereum" in networks

    def test_seed_is_deterministic_and_duplicate_free(self):
        first = load_registry_entries()
        second = load_registry_entries()
        assert first[1] == second[1]  # representation dataclasses compare exact
        keys = [(e.source, e.platform, e.identity_key) for e in first[1]]
        assert len(keys) == len(set(keys))


# ── xStocks adapter (deterministic fixtures) ──────────────────────────────────

class _FakeResponse:
    def __init__(self, payload, status=200):
        self._payload = payload
        self.status_code = status

    def raise_for_status(self):
        if self.status_code >= 400:
            import httpx
            raise httpx.HTTPStatusError(
                "http error", request=None, response=None)

    def json(self):
        if isinstance(self._payload, Exception):
            raise self._payload
        return self._payload


class _FakeClient:
    def __init__(self, pages, *, raise_on_get=None):
        self.pages = pages
        self.raise_on_get = raise_on_get
        self.calls = []

    def get(self, url, params=None):
        self.calls.append(params)
        if self.raise_on_get is not None:
            raise self.raise_on_get
        page = (params or {}).get("page", 0)
        return _FakeResponse(self.pages[min(page, len(self.pages) - 1)])

    def close(self):
        pass


def _page(nodes, has_next):
    return {"nodes": nodes, "page": {"currentPage": 0, "hasNextPage": has_next}}


_ASSET = {
    "symbol": "NVDAx", "name": "NVIDIA xStock", "isin": "CH123",
    "underlyingSymbol": "NVDA", "underlyingIsin": "US67066G1040",
    "isTradingHalted": True,
    "deployments": [
        {"address": "0x" + "11" * 20, "network": "Ethereum", "decimals": 18},
        {"network": "Solana"},  # no exact address: unusable, skipped
    ],
}


class TestXStocksAdapter:
    def test_pagination_and_parse(self):
        import httpx
        client = _FakeClient([
            _page([_ASSET], True),
            _page([{ "symbol": "TSLAx", "underlyingSymbol": "TSLA",
                     "deployments": []}], False),
        ])
        assets, pages = __import__(
            "finco_radar.venues.xstocks", fromlist=["fetch_assets"]
        ).fetch_assets(client=client)
        assert pages == 2
        assert [a.symbol for a in assets] == ["NVDAx", "TSLAx"]
        assert assets[0].underlying_symbol == "NVDA"
        assert assets[0].underlying_isin == "US67066G1040"
        assert assets[0].is_trading_halted is True
        assert len(assets[0].deployments) == 1  # addressless row skipped
        assert assets[0].deployments[0].decimals == 18

    def test_malformed_payload_is_typed(self):
        from finco_radar.venues.xstocks import XStocksParseError, fetch_assets
        client = _FakeClient([{"unexpected": 1}])
        with pytest.raises(XStocksParseError):
            fetch_assets(client=client)

    def test_http_error_is_typed_unavailable(self):
        import httpx
        from finco_radar.venues.xstocks import XStocksUnavailable, fetch_assets
        client = _FakeClient([], raise_on_get=httpx.ConnectTimeout("down"))
        with pytest.raises(XStocksUnavailable):
            fetch_assets(client=client)

    def test_timeout_is_typed_unavailable(self):
        import httpx
        from finco_radar.venues.xstocks import XStocksUnavailable, fetch_assets
        client = _FakeClient([], raise_on_get=httpx.ReadTimeout("slow"))
        with pytest.raises(XStocksUnavailable):
            fetch_assets(client=client)


# ── Observation store ─────────────────────────────────────────────────────────

def _observation(**overrides) -> MarketObservation:
    base = dict(
        ts="2026-10-02T11:59:00+00:00",
        collected_at="2026-10-02T12:00:00+00:00",
        canonical_asset_id="NVDA",
        venue_id="robinhood-chain",
        instrument_id="0xd0601ce157db5bdc3162bbac2a2c8af5320d9eec",
        instrument_type="tokenized-equity",
        price="195.25",
        source="test",
        freshness_state=FreshnessState.AVAILABLE,
        observation_status=ObservationStatus.OK,
        payload={"note": "unit"},
    )
    base.update(overrides)
    return MarketObservation(**base)


class TestObservationStore:
    @pytest.fixture()
    def store(self, tmp_path):
        return VenueMarketStore(tmp_path / "venues.db")

    def test_append_dedupes_by_digest_and_immutability(self, store):
        digest_a, created_a = store.append_observation(_observation())
        assert created_a is True
        digest_b, created_b = store.append_observation(_observation())
        assert digest_a == digest_b and created_b is False
        assert store.count() == 1
        # changed evidence → new row (later source timestamp)
        store.append_observation(_observation(
            price="196.00", ts="2026-10-02T12:01:00+00:00"))
        assert store.count() == 2
        latest = store.get_latest_for_instrument(
            "0xd0601ce157db5bdc3162bbac2a2c8af5320d9eec")
        assert latest.price == "196.00"
        # old row untouched
        rows = store.get_window_for_instrument(
            "0xd0601ce157db5bdc3162bbac2a2c8af5320d9eec",
            since=NOW - timedelta(days=1))
        assert [r.price for r in rows] == ["195.25", "196.00"]

    def test_missing_numerics_stay_null_and_decimals_round_trip(
            self, store):
        store.append_observation(_observation(
            price="0.0000012345", reference_price=None, basis_bps=None,
            volume_24h=None, open_interest=None, funding_rate=None))
        latest = store.get_latest_for_instrument(
            "0xd0601ce157db5bdc3162bbac2a2c8af5320d9eec")
        assert latest.price == "0.0000012345"
        assert Decimal(latest.price) == Decimal("0.0000012345")
        assert latest.reference_price is None
        assert latest.volume_24h is None

    def test_clocks_stay_distinct(self, store):
        store.append_observation(_observation())
        latest = store.get_latest_for_instrument(
            "0xd0601ce157db5bdc3162bbac2a2c8af5320d9eec")
        assert latest.ts == "2026-10-02T11:59:00+00:00"
        assert latest.collected_at == "2026-10-02T12:00:00+00:00"

    def test_latest_and_windows_and_filters(self, store):
        early = _observation(
            ts="2026-10-01T10:00:00+00:00", price="190.00")
        late = _observation(
            ts="2026-10-02T10:00:00+00:00", price="195.00",
            canonical_asset_id="nvda", venue_id="robinhood-chain",
            instrument_id="0xd0601ce157db5bdc3162bbac2a2c8af5320d9eec")
        store.append_observation(early)
        store.append_observation(late)
        latest = store.get_latest_for_underlying("nvda")
        assert latest.price == "195.00"
        window = store.get_window_for_underlying(
            "NVDA", since=NOW - timedelta(days=2), until=NOW)
        assert len(window) == 2
        assert [w.price for w in window] == ["190.00", "195.00"]
        # venue filter is exact
        empty = store.get_window_for_underlying(
            "NVDA", since=NOW - timedelta(days=1), venue_id="xstocks")
        assert empty == []
        by_venue = store.list_latest_by_venue("robinhood-chain")
        assert len(by_venue) == 1

    def test_quarantined_observation_stays_explicit(self, store):
        store.append_observation(_observation(
            observation_status=ObservationStatus.QUARANTINED, price=None,
            freshness_state=FreshnessState.UNAVAILABLE))
        latest = store.get_latest_for_instrument(
            "0xd0601ce157db5bdc3162bbac2a2c8af5320d9eec")
        assert latest.observation_status is ObservationStatus.QUARANTINED
        assert latest.price is None
        assert latest.freshness_state is FreshnessState.UNAVAILABLE

    def test_non_finite_price_rejected(self, store):
        with pytest.raises(ValueError):
            _observation(price="NaN")
        with pytest.raises(ValueError):
            _observation(price=195.25)  # floats never persist


# ── Collector ─────────────────────────────────────────────────────────────────

class TestCollector:
    def test_fixture_to_observation_to_store(self, tmp_path, monkeypatch):
        from finco_radar.venues import collector as collector_module
        from finco_radar.venues.collector import collect_xstocks_once
        from finco_radar.venues.xstocks import XStocksAsset

        asset = XStocksAsset(
            symbol="NVDAx", name="NVIDIA xStock", isin="CH123",
            underlying_symbol="NVDA", underlying_isin="US67066G1040",
            is_trading_halted=False,
            deployments=((__import__(
                "finco_radar.venues.xstocks",
                fromlist=["XStocksDeployment"]).XStocksDeployment(
                network="ethereum", contract_address="0x" + "22" * 20,
                decimals=18)),))

        class StubAdapter:
            def fetch(self):
                return [asset], 1

        monkeypatch.setattr(collector_module, "fetch_assets",
                            lambda **kwargs: ([asset], 1))
        store = VenueMarketStore(tmp_path / "venues.db")
        report = collect_xstocks_once(store=store, collected_at=NOW)
        assert report.observations == 1 and report.persisted == 1
        latest = store.get_latest_for_underlying("NVDA")
        assert latest.canonical_asset_id == "NVDA"
        assert latest.instrument_id == "NVDAx"
        assert latest.digest is not None
        # deterministic digest: same evidence → same digest
        store2 = VenueMarketStore(tmp_path / "venues2.db")
        report2 = collect_xstocks_once(store=store2, collected_at=NOW)
        latest2 = store2.get_latest_for_underlying("NVDA")
        assert latest.digest == latest2.digest
        assert report2.duplicates == 0

    def test_provider_failure_never_fabricates_or_rewrites(
            self, tmp_path, monkeypatch):
        from finco_radar.venues import collector as collector_module
        from finco_radar.venues.collector import collect_xstocks_once
        from finco_radar.venues.xstocks import XStocksUnavailable

        monkeypatch.setattr(
            collector_module, "fetch_assets",
            lambda **kwargs: (_ for _ in ()).throw(
                XStocksUnavailable("api down")))
        store = VenueMarketStore(tmp_path / "venues.db")
        with pytest.raises(XStocksUnavailable):
            collect_xstocks_once(store=store, collected_at=NOW)
        assert store.count() == 0

    def test_asset_without_underlying_is_skipped_never_guessed(self, tmp_path, monkeypatch):
        from finco_radar.venues import collector as collector_module
        from finco_radar.venues.collector import collect_xstocks_once
        from finco_radar.venues.xstocks import XStocksAsset

        asset = XStocksAsset(
            symbol="MYSTERYx", name=None, isin=None, underlying_symbol=None,
            underlying_isin=None, is_trading_halted=None, deployments=())
        monkeypatch.setattr(collector_module, "fetch_assets",
                            lambda **kwargs: ([asset], 1))
        store = VenueMarketStore(tmp_path / "venues.db")
        report = collect_xstocks_once(store=store, collected_at=NOW)
        assert report.observations == 0 and store.count() == 0

    def test_halted_asset_is_explicitly_quarantined_not_priced(
            self, tmp_path, monkeypatch):
        from finco_radar.venues import collector as collector_module
        from finco_radar.venues.collector import collect_xstocks_once
        from finco_radar.venues.xstocks import XStocksAsset

        asset = XStocksAsset(
            symbol="HALTx", name=None, isin=None, underlying_symbol="HALT",
            underlying_isin=None, is_trading_halted=True, deployments=())
        monkeypatch.setattr(collector_module, "fetch_assets",
                            lambda **kwargs: ([asset], 1))
        store = VenueMarketStore(tmp_path / "venues.db")
        collect_xstocks_once(store=store, collected_at=NOW)
        latest = store.get_latest_for_underlying("HALT")
        assert latest.observation_status is ObservationStatus.QUARANTINED
