"""Tokenized Markets foundation tests — PR #175 Correction A contracts.

CLOCKS: source ts authority (present → exact source time; absent → None),
collected_at distinct, naive stamps rejected.
DIGEST: evidence identity excludes collected_at — same evidence
re-collected → same digest → dedupe; changed evidence → new row.
COLLECTOR: identity-only discovery rows are NEVER market history; price
evidence comes from an injected provider over an exact bounded set;
unavailable is reported, never fabricated; halted stays typed; provider
failure never rewrites history.
REGISTRY: exact embedded-deployment identity (network/chain_id honored,
quarantined deployment never ACTIVE), ambiguous contract → None.
STORE: batch dedupe via PK (no full preload), INSERT OR IGNORE no-op,
latest-by-venue deterministic under ties.
SAFETY: scanner exemption is exact-path+exact-SHA (one-byte change fails).
"""
from __future__ import annotations

import hashlib
import json
from datetime import datetime, timedelta, timezone
from decimal import Decimal
from pathlib import Path
from types import SimpleNamespace

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

REPO = Path(__file__).resolve().parents[1]

from finco_radar.venues import collector as collector_module
from finco_radar.venues.collector import (
    PriceEvidence,
    PriceEvidenceUnavailable,
    collect_xstocks_prices,
)
from finco_radar.venues.models import (
    RegistryStatus,
    RepresentationEntry,
)
from finco_radar.venues.observations import (
    FreshnessState,
    MarketObservation,
    ObservationStatus,
)
from finco_radar.venues.registry import VenueRegistry
from finco_radar.venues.seed_loader import load_registry_entries
from finco_radar.venues.store import VenueMarketStore
from finco_radar.venues.xstocks import (
    XStocksAsset,
    XStocksUnavailable,
    fetch_assets,
)

NOW = datetime(2026, 10, 2, 12, 0, 0, tzinfo=timezone.utc)


# ── CLOCKS ────────────────────────────────────────────────────────────────────

class TestClockAuthority:
    def test_source_timestamp_present_is_exact_ts(self):
        evidence_stamp = datetime(2026, 10, 2, 11, 59, 30, tzinfo=timezone.utc)
        ts, collected = MarketObservation.clocks(evidence_stamp, NOW)
        assert ts == "2026-10-02T11:59:30+00:00"
        assert collected == NOW.isoformat()

    def test_source_timestamp_absent_gives_ts_none(self):
        ts, collected = MarketObservation.clocks(None, NOW)
        assert ts is None
        assert collected == NOW.isoformat()

    def test_observation_keeps_ts_none_and_collected_distinct(self):
        observation = _observation(ts=None, collected_at=NOW.isoformat())
        assert observation.ts is None
        assert observation.collected_at == NOW.isoformat()

    def test_naive_ts_rejected(self):
        with pytest.raises(ValueError):
            _observation(ts="2026-10-02T11:59:00")  # no tzinfo

    def test_naive_collected_at_rejected(self):
        with pytest.raises(ValueError):
            _observation(collected_at="2026-10-02T12:00:00")  # no tzinfo


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


# ── DIGEST ────────────────────────────────────────────────────────────────────

class TestDigestSemantics:
    def test_same_evidence_different_collected_at_same_digest(self):
        first = _observation(collected_at="2026-10-02T12:00:00+00:00")
        second = _observation(collected_at="2026-10-02T18:30:00+00:00")
        assert first.compute_digest() == second.compute_digest()

    def test_changed_source_timestamp_changes_digest(self):
        first = _observation(ts="2026-10-02T11:59:00+00:00")
        second = _observation(ts="2026-10-02T12:05:00+00:00")
        assert first.compute_digest() != second.compute_digest()

    def test_changed_price_changes_digest(self):
        first = _observation(price="195.25")
        second = _observation(price="196.00")
        assert first.compute_digest() != second.compute_digest()

    def test_digest_input_excludes_collected_at(self):
        assert "collected_at" not in _observation().digest_input()


# ── Registry (Correction A: embedded deployments + ambiguity) ─────────────────

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


def _underlying(**overrides):
    from finco_radar.venues.registry import parse_underlying
    base = dict(canonical_symbol="NVDA", underlying_isin="US67066G1040",
                underlying_name="NVIDIA", sources=("test-source",))
    base.update(overrides)
    return parse_underlying(base)


def _registry(entries, underlyings=None, quarantines=None) -> VenueRegistry:
    if underlyings is None:
        underlyings = {"NVDA": _underlying()}
    return VenueRegistry(underlyings, list(entries), quarantines or [])


def _norm(value):
    return value.strip().upper() if value else None


class TestRegistryExactDeployments:
    def _xstocks_with_eth_deployment(self, contract="0x" + "22" * 20):
        from finco_radar.venues.models import Deployment
        return _entry(
            platform="xstocks", representation_symbol="NVDAx",
            underlying_symbol="NVDA", network=None, chain_id=None,
            contract_address=None, decimals=None, deployment_status=None,
            deployments=(Deployment(network="ethereum", chain_id=None,
                                    contract_address=contract, decimals=18),),
            source="xstocks")

    def test_embedded_exact_lookup_honors_network(self):
        registry = _registry([self._xstocks_with_eth_deployment()])
        contract = "0x" + "22" * 20
        rows = registry.representation_by_contract(
            network="ethereum", contract_address=contract)
        assert len(rows) == 1
        entry, status = rows[0]
        assert entry.representation_symbol == "NVDAx"
        assert status is RegistryStatus.ACTIVE
        assert registry.representation_by_contract(
            network="solana", contract_address=contract) == []

    def test_embedded_chain_id_request_never_matches_unknown_chain(self):
        registry = _registry([self._xstocks_with_eth_deployment()])
        contract = "0x" + "22" * 20
        # Deployment chain_id unknown (None): an explicit chain_id request
        # must never be satisfied by it.
        assert registry.representation_by_contract(
            chain_id=1, contract_address=contract) == []

    def test_embedded_quarantined_deployment_never_active(self):
        contract = "0x" + "33" * 20
        entry = self._xstocks_with_eth_deployment(contract=contract)
        quarantines = [{"network": "ethereum",
                        "contract_address": contract,
                        "classification": "impostor"}]
        registry = _registry([entry], quarantines=quarantines)
        rows = registry.representation_by_contract(
            network="ethereum", contract_address=contract)
        assert rows and rows[0][1] is RegistryStatus.QUARANTINED
        assert registry.underlying_for_contract(
            network="ethereum", contract_address=contract) is None

    def test_underlying_for_contract_ambiguity_never_first_row_wins(self):
        """Two ACTIVE rows resolving one exact contract to two DIFFERENT
        underlyings must return None (ambiguity), not the first row."""
        registry = _registry([
            _entry(source="source-a", underlying_symbol="NVDA"),
            _entry(source="source-b", underlying_symbol="TESLA"),
        ], underlyings={"NVDA": _underlying(),
                        "TESLA": _underlying(canonical_symbol="TESLA")})
        # Same exact contract via registry.index collision simulation:
        # inject a second ACTIVE row sharing the first one's contract.
        twin = _entry(source="source-b", underlying_symbol="TESLA")
        registry._entries.append(twin)
        registry._by_contract.setdefault(
            ("robinhood-chain", twin.contract_address), []).append(twin)
        assert registry.underlying_for_contract(
            network="robinhood-chain",
            contract_address=twin.contract_address) is None


class TestRegistryRealSeed:
    def test_real_seed_loads_and_resolves_robinhood_nvda(self):
        registry = VenueRegistry.load()
        resolved = registry.resolve_exact_instrument(
            platform="robinhood", symbol="NVDA", network="robinhood-chain")
        assert resolved is not None
        assert resolved.entry.contract_address == (
            "0xd0601ce157db5bdc3162bbac2a2c8af5320d9eec")
        assert resolved.status is RegistryStatus.ACTIVE

    def test_real_seed_impostor_contract_is_quarantined(self):
        registry = VenueRegistry.load()
        contract = "0xdecf74e4aa6ff30b1612e65665aaf650bedecba3"
        rows = registry.representation_by_contract(chain_id=4663,
                                                   contract_address=contract)
        assert all(status is not RegistryStatus.ACTIVE for _e, status in rows)
        assert registry.underlying_for_contract(chain_id=4663,
                                                contract_address=contract) is None

    def test_real_seed_xstocks_mapping(self):
        registry = VenueRegistry.load()
        resolved = registry.resolve_exact_instrument(
            platform="xstocks", symbol="AAPLx")
        assert resolved is not None
        assert resolved.entry.underlying_symbol == "AAPL"
        underlying = registry.underlying_for_contract(
            network="ethereum",
            contract_address=resolved.entry.deployments[0].contract_address)
        assert underlying.canonical_symbol == "AAPL"

    def test_seed_is_deterministic_and_duplicate_free(self):
        first = load_registry_entries()
        second = load_registry_entries()
        assert first[1] == second[1]
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
            raise httpx.HTTPStatusError("http error", request=None, response=None)

    def json(self):
        return self._payload


class _FakeClient:
    def __init__(self, pages, *, raise_on_get=None):
        self.pages = pages
        self.raise_on_get = raise_on_get

    def get(self, url, params=None):
        if self.raise_on_get is not None:
            raise self.raise_on_get
        page = (params or {}).get("page", 0)
        return _FakeResponse(self.pages[min(page, len(self.pages) - 1)])

    def close(self):
        pass


def _page(nodes, has_next):
    return {"nodes": nodes, "page": {"currentPage": 0, "hasNextPage": has_next}}


class TestXStocksAdapter:
    def test_pagination_parse_and_halt(self):
        asset_node = {
            "symbol": "NVDAx", "name": "NVIDIA xStock", "isin": "CH123",
            "underlyingSymbol": "NVDA", "underlyingIsin": "US67066G1040",
            "isTradingHalted": True,
            "deployments": [
                {"address": "0x" + "11" * 20, "network": "Ethereum",
                 "decimals": 18},
                {"network": "Solana"},  # no exact address: skipped
            ],
        }
        client = _FakeClient([_page([asset_node], True),
                              _page([{"symbol": "TSLAx",
                                      "underlyingSymbol": "TSLA",
                                      "deployments": []}], False)])
        assets, pages = fetch_assets(client=client)
        assert pages == 2
        assert [a.symbol for a in assets] == ["NVDAx", "TSLAx"]
        assert assets[0].underlying_symbol == "NVDA"
        assert assets[0].underlying_isin == "US67066G1040"
        assert assets[0].is_trading_halted is True
        assert len(assets[0].deployments) == 1

    def test_malformed_payload_is_typed(self):
        from finco_radar.venues.xstocks import XStocksParseError
        with pytest.raises(XStocksParseError):
            fetch_assets(client=_FakeClient([{"unexpected": 1}]))

    def test_http_error_is_typed_unavailable(self):
        import httpx
        from finco_radar.venues.xstocks import XStocksUnavailable
        with pytest.raises(XStocksUnavailable):
            fetch_assets(client=_FakeClient(
                [], raise_on_get=httpx.ConnectTimeout("down")))

    def test_timeout_is_typed_unavailable(self):
        import httpx
        from finco_radar.venues.xstocks import XStocksUnavailable
        with pytest.raises(XStocksUnavailable):
            fetch_assets(client=_FakeClient(
                [], raise_on_get=httpx.ReadTimeout("slow")))


# ── Observation store ─────────────────────────────────────────────────────────

class TestObservationStore:
    @pytest.fixture()
    def store(self, tmp_path):
        return VenueMarketStore(tmp_path / "venues.db")

    def test_append_dedupes_by_digest_and_immutability(self, store):
        digest_a, created_a = store.append_observation(_observation())
        assert created_a is True
        _digest, created_b = store.append_observation(_observation())
        assert created_b is False
        assert store.count() == 1
        store.append_observation(_observation(
            price="196.00", ts="2026-10-02T12:01:00+00:00"))
        assert store.count() == 2
        latest = store.get_latest_for_instrument(
            "0xd0601ce157db5bdc3162bbac2a2c8af5320d9eec")
        assert latest.price == "196.00"
        rows = store.get_window_for_instrument(
            "0xd0601ce157db5bdc3162bbac2a2c8af5320d9eec",
            since=NOW - timedelta(days=1))
        assert [r.price for r in rows] == ["195.25", "196.00"]

    def test_same_evidence_recollected_does_not_append_clock_change_only(
            self, store):
        """Correction A digest invariant: only the collector clock changed →
        same evidence identity → dedupe, no new row."""
        store.append_observation(_observation(collected_at=NOW.isoformat()))
        later = NOW + timedelta(hours=5)
        store.append_observation(_observation(collected_at=later.isoformat()))
        assert store.count() == 1

    def test_missing_numerics_stay_null_and_decimals_round_trip(self, store):
        store.append_observation(_observation(
            price="0.0000012345", reference_price=None, basis_bps=None,
            volume_24h=None, open_interest=None, funding_rate=None))
        latest = store.get_latest_for_instrument(
            "0xd0601ce157db5bdc3162bbac2a2c8af5320d9eec")
        assert latest.price == "0.0000012345"
        assert Decimal(latest.price) == Decimal("0.0000012345")
        assert latest.reference_price is None

    def test_clocks_stay_distinct(self, store):
        store.append_observation(_observation())
        latest = store.get_latest_for_instrument(
            "0xd0601ce157db5bdc3162bbac2a2c8af5320d9eec")
        assert latest.ts == "2026-10-02T11:59:00+00:00"
        assert latest.collected_at == "2026-10-02T12:00:00+00:00"

    def test_source_time_window_excludes_missing_ts(self, store):
        store.append_observation(_observation(ts=None))
        rows = store.get_window_for_instrument(
            "0xd0601ce157db5bdc3162bbac2a2c8af5320d9eec",
            since=NOW - timedelta(days=1))
        assert rows == []  # collected_at never pretends to be evidence time
        latest = store.get_latest_for_instrument(
            "0xd0601ce157db5bdc3162bbac2a2c8af5320d9eec")
        assert latest is not None and latest.ts is None

    def test_latest_and_windows_and_filters(self, store):
        early = _observation(ts="2026-10-01T10:00:00+00:00", price="190.00")
        late = _observation(ts="2026-10-02T10:00:00+00:00", price="195.00")
        store.append_observation(early)
        store.append_observation(late)
        latest = store.get_latest_for_underlying("nvda")
        assert latest.price == "195.00"
        window = store.get_window_for_underlying(
            "NVDA", since=NOW - timedelta(days=2), until=NOW)
        assert [w.price for w in window] == ["190.00", "195.00"]
        assert store.get_window_for_underlying(
            "NVDA", since=NOW - timedelta(days=2), venue_id="xstocks") == []
        assert len(store.list_latest_by_venue("robinhood-chain")) == 1

    def test_quarantined_observation_stays_explicit(self, store):
        store.append_observation(_observation(
            observation_status=ObservationStatus.QUARANTINED, price=None,
            freshness_state=FreshnessState.UNAVAILABLE))
        latest = store.get_latest_for_instrument(
            "0xd0601ce157db5bdc3162bbac2a2c8af5320d9eec")
        assert latest.observation_status is ObservationStatus.QUARANTINED
        assert latest.price is None

    def test_non_finite_and_float_prices_rejected(self, store):
        with pytest.raises(ValueError):
            _observation(price="NaN")
        with pytest.raises(ValueError):
            _observation(price="Infinity")
        with pytest.raises(ValueError):
            _observation(price=195.25)  # floats never persist

    def test_batch_dedupe_no_duplicate_rows(self, store):
        first = [_observation(ts=f"2026-10-0{d}T10:00:00+00:00")
                 for d in range(1, 4)]
        created = store.append_many_batched(first)
        assert all(was for _digest, was in created)
        duplicate = store.append_many_batched(first)
        assert all(not was for _digest, was in duplicate)
        assert store.count() == 3

    def test_latest_by_venue_deterministic_under_ties(self, store):
        tie_a = _observation(collected_at="2026-10-02T12:00:00+00:00",
                             price="100.00")
        tie_b = _observation(collected_at="2026-10-02T12:00:00+00:00",
                             price="200.00")
        created = store.append_many_batched([tie_a, tie_b])
        assert sum(1 for _d, was in created if was) == 2  # distinct evidence
        latest_rows = store.list_latest_by_venue("robinhood-chain")
        assert len(latest_rows) == 1  # exactly one deterministic winner


# ── Collector (price seam; identity rows are not market history) ──────────────

class TestCollector:
    @pytest.fixture()
    def store(self, tmp_path):
        return VenueMarketStore(tmp_path / "venues.db")

    @staticmethod
    def _deps(monkeypatch, store, prices, underlyings, halts=None):
        monkeypatch.setattr(collector_module, "fetch_assets",
                            lambda **kwargs: ([], 1))
        under = dict(underlyings)
        price_map = dict(prices)
        halt_map = dict(halts or {})
        return (
            lambda symbol: under.get(symbol),
            lambda symbol: price_map.get(symbol)
            or (_ for _ in ()).throw(PriceEvidenceUnavailable(symbol)),
            (lambda symbol: halt_map.get(symbol)) if halt_map else None,
        )

    def test_identity_only_universe_is_never_market_history(
            self, store, monkeypatch):
        """The assets endpoint refresh returns the typed universe and writes
        NOTHING into market_observations (Correction A #5)."""
        asset = XStocksAsset(
            symbol="NVDAx", name="NVIDIA xStock", isin="CH123",
            underlying_symbol="NVDA", underlying_isin="US67066G1040",
            is_trading_halted=False, deployments=())
        monkeypatch.setattr(collector_module, "fetch_assets",
                            lambda **kwargs: ([asset], 1))
        universe, pages = collector_module.collect_xstocks_universe_identity()
        assert pages == 1 and universe[0].symbol == "NVDAx"
        assert store.count() == 0

    def test_price_evidence_produces_observation_with_exact_underlying(
            self, store, monkeypatch):
        prices = {"NVDAx": PriceEvidence(
            symbol="NVDAx", price="195.25",
            source_timestamp=datetime(2026, 10, 2, 11, 59, tzinfo=timezone.utc))}
        fetch, price_fetcher, halt = self._deps(
            monkeypatch, store, prices, underlyings={"NVDAx": "NVDA"})
        report = collect_xstocks_prices(
            store=store, symbols=["NVDAx"], price_fetcher=price_fetcher,
            underlying_lookup=fetch, halt_lookup=halt, collected_at=NOW)
        assert (report.requested, report.priced, report.persisted) == (1, 1, 1)
        latest = store.get_latest_for_underlying("NVDA")
        assert latest.price == "195.25"
        assert latest.ts == "2026-10-02T11:59:00+00:00"  # provider stamp

    def test_price_without_provider_stamp_has_ts_none(self, store, monkeypatch):
        prices = {"AAPLx": PriceEvidence(
            symbol="AAPLx", price="250.10", source_timestamp=None)}
        fetch, price_fetcher, halt = self._deps(
            monkeypatch, store, prices, underlyings={"AAPLx": "AAPL"})
        collect_xstocks_prices(store=store, symbols=["AAPLx"],
                               price_fetcher=price_fetcher,
                               underlying_lookup=fetch, halt_lookup=halt,
                               collected_at=NOW)
        latest = store.get_latest_for_underlying("AAPL")
        assert latest.ts is None
        assert latest.collected_at == NOW.isoformat()

    def test_unavailable_price_is_skipped_never_fabricated(
            self, store, monkeypatch):
        fetch, price_fetcher, halt = self._deps(
            monkeypatch, store, {}, underlyings={"NVDAx": "NVDA"})
        report = collect_xstocks_prices(
            store=store, symbols=["NVDAx"], price_fetcher=price_fetcher,
            underlying_lookup=fetch, halt_lookup=halt, collected_at=NOW)
        assert report.skipped_unavailable == 1
        assert store.count() == 0

    def test_unresolvable_underlying_is_skipped_never_guessed(
            self, store, monkeypatch):
        prices = {"MYSTERYx": PriceEvidence(
            symbol="MYSTERYx", price="1.00", source_timestamp=None)}
        fetch, price_fetcher, halt = self._deps(
            monkeypatch, store, prices, underlyings={})
        report = collect_xstocks_prices(
            store=store, symbols=["MYSTERYx"], price_fetcher=price_fetcher,
            underlying_lookup=fetch, halt_lookup=halt, collected_at=NOW)
        assert report.skipped_unavailable == 1
        assert store.count() == 0

    def test_halted_instrument_stays_typed(self, store, monkeypatch):
        prices = {"HALTx": PriceEvidence(
            symbol="HALTx", price="10.00", source_timestamp=None)}
        fetch, price_fetcher, halt = self._deps(
            monkeypatch, store, prices, underlyings={"HALTx": "HALT"},
            halts={"HALTx": True})
        report = collect_xstocks_prices(
            store=store, symbols=["HALTx"], price_fetcher=price_fetcher,
            underlying_lookup=fetch, halt_lookup=halt, collected_at=NOW)
        assert report.halted_quarantined == 1
        latest = store.get_latest_for_underlying("HALT")
        assert latest.observation_status is ObservationStatus.QUARANTINED
        assert latest.price == "10.00"  # priced evidence is real, not fake

    def test_provider_failure_never_rewrites_prior_history(
            self, store, monkeypatch):
        prices = {"NVDAx": PriceEvidence(
            symbol="NVDAx", price="195.25", source_timestamp=None)}
        fetch, price_fetcher, halt = self._deps(
            monkeypatch, store, prices, underlyings={"NVDAx": "NVDA"})
        collect_xstocks_prices(store=store, symbols=["NVDAx"],
                               price_fetcher=price_fetcher,
                               underlying_lookup=fetch, halt_lookup=halt,
                               collected_at=NOW)
        before = store.count()

        def failing_fetcher(symbol):
            raise PriceEvidenceUnavailable("down")

        report = collect_xstocks_prices(
            store=store, symbols=["NVDAx"], price_fetcher=failing_fetcher,
            underlying_lookup=fetch, halt_lookup=halt,
            collected_at=NOW + timedelta(hours=1))
        assert report.skipped_unavailable == 1
        assert store.count() == before

    def test_recollected_identical_evidence_dedupes(self, store, monkeypatch):
        prices = {"NVDAx": PriceEvidence(
            symbol="NVDAx", price="195.25",
            source_timestamp=datetime(2026, 10, 2, 11, 59, tzinfo=timezone.utc))}
        fetch, price_fetcher, halt = self._deps(
            monkeypatch, store, prices, underlyings={"NVDAx": "NVDA"})
        first = collect_xstocks_prices(
            store=store, symbols=["NVDAx"], price_fetcher=price_fetcher,
            underlying_lookup=fetch, halt_lookup=halt, collected_at=NOW)
        second = collect_xstocks_prices(
            store=store, symbols=["NVDAx"], price_fetcher=price_fetcher,
            underlying_lookup=fetch, halt_lookup=halt,
            collected_at=NOW + timedelta(hours=2))
        assert first.persisted == 1 and second.persisted == 0
        assert second.duplicates == 1
        assert store.count() == 1


# ── Safety scanner exemption (exact path + exact SHA) ─────────────────────────

class TestSafetyScanExemption:
    SEED_PATH = "finco_radar/venues/data/venue_registry_seed.json"

    def _expected_sha(self):
        from tools.public_safety_scan import _SEED_SECRET_EXEMPT
        return _SEED_SECRET_EXEMPT[self.SEED_PATH]

    def test_exemption_matches_exact_path_and_hash(self):
        from tools.public_safety_scan import _seed_secret_exempt
        data = (REPO / self.SEED_PATH).read_bytes()
        assert _seed_secret_exempt(self.SEED_PATH, data) is True

    def test_one_byte_change_breaks_exemption(self):
        from tools.public_safety_scan import _seed_secret_exempt
        data = (REPO / self.SEED_PATH).read_bytes()
        tampered = data + b" "
        assert _seed_secret_exempt(self.SEED_PATH, tampered) is False
        assert _seed_secret_exempt("some/other/path", data) is False

    def test_expected_digest_matches_committed_file(self):
        assert (hashlib.sha256(
            (REPO / self.SEED_PATH).read_bytes()).hexdigest()
            == self._expected_sha())
