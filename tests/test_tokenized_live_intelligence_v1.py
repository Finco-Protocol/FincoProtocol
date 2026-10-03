"""FINCO Tokenized Live Intelligence V1 — end-to-end authority regressions.

Network-free. Provider behavior is injected. These tests prove the vertical:
reviewed exact identity -> bounded collector -> MarketObservation ->
append-only VenueMarketStore -> read-only history/intelligence -> UI.
"""
from __future__ import annotations

from datetime import datetime, timedelta, timezone
from decimal import Decimal
import io
from pathlib import Path
from types import SimpleNamespace

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from app.radar_rwa import tokenized_collect
from app.radar_ui.tokenized_composition import compose_underlying
from finco_radar.authority.r_live_policy import APPROVED_BY_CANONICAL_ID
from finco_radar.venues.health import (
    HEALTHY,
    LIVENESS_LIVE,
    LIVENESS_STALE,
    LIVENESS_STOPPED,
    TokenizedCollectorHealthStore,
    read_tokenized_collector_health,
)
from finco_radar.venues.intelligence import (
    build_tokenized_intelligence,
    effective_observation_state,
)
from finco_radar.venues.observations import (
    FreshnessState,
    MarketObservation,
    ObservationStatus,
)
from finco_radar.venues.registry import VenueRegistry
from finco_radar.venues.robinhood_live import (
    COMPARISON_UNIT,
    TokenizedLiveIdentityMismatch,
    market_observation_from_r_live,
)
from finco_radar.venues.store import VenueMarketStore
from tests.test_tokenized_markets_composition import (
    ROBINHOOD_NVDA,
    _entry,
    _registry,
)

NOW = datetime(2026, 10, 3, 12, 0, tzinfo=timezone.utc)


def _canonical_id(symbol: str) -> str:
    return next(
        canonical_id for canonical_id, policy in APPROVED_BY_CANONICAL_ID.items()
        if policy.symbol == symbol
    )


def _policy(symbol: str):
    return APPROVED_BY_CANONICAL_ID[_canonical_id(symbol)]


NVDA_ID = _canonical_id("NVDA")
AAPL_ID = _canonical_id("AAPL")


def _aapl_entry(**overrides):
    policy = _policy("AAPL")
    base = dict(
        platform="robinhood",
        representation_symbol="AAPL",
        underlying_symbol="AAPL",
        underlying_isin=None,
        isin=None,
        instrument_type="tokenized-equity",
        name="Apple • Robinhood Token",
        network="robinhood-chain",
        chain_id=policy.asset_key.chain_id,
        contract_address=policy.asset_key.contract_address,
        decimals=18,
        deployment_status="active",
        trading_halted=None,
        deployments=(),
        source="test",
        source_ref="test/aapl",
    )
    base.update(overrides)
    from finco_radar.venues.models import RepresentationEntry
    return RepresentationEntry(**base)


def _live_data(
    canonical_id: str,
    *,
    token_price: str = "102",
    reference_price: str = "100",
    stamp: datetime = NOW - timedelta(seconds=30),
):
    policy = APPROVED_BY_CANONICAL_ID[canonical_id]
    return {
        "exact_asset_key": {
            "canonical_id": canonical_id,
            "chain_id": policy.asset_key.chain_id,
            "contract_address": policy.asset_key.contract_address,
        },
        "economic_asset_uid": policy.economic_asset_uid,
        "token_reference": {
            "state": "AVAILABLE",
            "price_usd_per_token": token_price,
            "source": "UNISWAP_V3_TWAP_CHAINLINK_USDG_USD",
            "observed_at": stamp.isoformat(),
            "reason": None,
        },
        "robinhood_basis": {
            "state": "AVAILABLE",
            "price_usd_per_token": reference_price,
            "source": "ROBINHOOD_STOCK_TOKEN_REFERENCE",
            "observed_at": stamp.isoformat(),
            "reason": None,
        },
    }


def _market_obs(
    *,
    venue: str,
    instrument: str,
    price: str,
    reference: str = "100",
    at: datetime,
    status: ObservationStatus = ObservationStatus.OK,
    comparison_unit: str = COMPARISON_UNIT,
    reference_at: datetime | None = None,
    canonical_asset_id: str = "NVDA",
):
    reference_at = reference_at or at
    return MarketObservation(
        ts=at.isoformat(),
        collected_at=(at + timedelta(seconds=5)).isoformat(),
        canonical_asset_id=canonical_asset_id,
        venue_id=venue,
        instrument_id=instrument,
        instrument_type="tokenized-equity",
        price=price,
        reference_price=reference,
        source="test-source",
        freshness_state=FreshnessState.AVAILABLE,
        observation_status=status,
        payload={
            "reference_state": "AVAILABLE",
            "reference_observed_at": reference_at.isoformat(),
            "reference_source": "test-reference",
            "comparison_unit": comparison_unit,
        },
    )


class TestExactRLiveBridge:
    def test_source_and_collection_clocks_remain_distinct(self):
        registry = _registry([_entry()])
        source_stamp = NOW - timedelta(seconds=40)
        observation = market_observation_from_r_live(
            canonical_id=NVDA_ID,
            state="AVAILABLE",
            data=_live_data(NVDA_ID, stamp=source_stamp),
            registry=registry,
            collected_at=NOW,
        )
        assert observation is not None
        assert observation.ts == source_stamp.isoformat()
        assert observation.collected_at == NOW.isoformat()
        assert observation.ts != observation.collected_at
        assert observation.canonical_asset_id == "NVDA"
        assert observation.instrument_id == ROBINHOOD_NVDA
        assert observation.payload["comparison_unit"] == COMPARISON_UNIT

    def test_contract_mapped_to_wrong_underlying_symbol_fails_closed(self):
        registry = _registry([_entry(underlying_symbol="AAPL")])
        with pytest.raises(
                TokenizedLiveIdentityMismatch,
                match="TOKENIZED_LIVE_UNDERLYING_POLICY_MISMATCH"):
            market_observation_from_r_live(
                canonical_id=NVDA_ID,
                state="AVAILABLE",
                data=_live_data(NVDA_ID),
                registry=registry,
                collected_at=NOW,
            )

    def test_economic_uid_mismatch_fails_closed(self):
        registry = _registry([_entry()])
        data = _live_data(NVDA_ID)
        data["economic_asset_uid"] = _policy("AAPL").economic_asset_uid
        with pytest.raises(TokenizedLiveIdentityMismatch):
            market_observation_from_r_live(
                canonical_id=NVDA_ID,
                state="AVAILABLE",
                data=data,
                registry=registry,
                collected_at=NOW,
            )

    def test_stale_or_unavailable_provider_state_is_not_invented_into_history(self):
        registry = _registry([_entry()])
        for state in ("STALE", "UNAVAILABLE"):
            assert market_observation_from_r_live(
                canonical_id=NVDA_ID,
                state=state,
                data={},
                registry=registry,
                collected_at=NOW,
            ) is None

    def test_halted_registry_evidence_is_quarantined_not_active(self):
        registry = _registry([_entry(trading_halted=True)])
        observation = market_observation_from_r_live(
            canonical_id=NVDA_ID,
            state="AVAILABLE",
            data=_live_data(NVDA_ID),
            registry=registry,
            collected_at=NOW,
        )
        assert observation is not None
        assert observation.price == "102"
        assert observation.observation_status is ObservationStatus.QUARANTINED


class TestCollectorVertical:
    def test_exact_registry_intersection_bounds_universe(self):
        registry = _registry([_entry()])
        targets = tokenized_collect._target_ids(registry, max_assets=32)
        assert targets == (NVDA_ID,)
        with pytest.raises(tokenized_collect.TokenizedCollectorConfigError):
            tokenized_collect._target_ids(registry, max_assets=1)

    def test_collector_universe_rejects_contract_bound_to_wrong_underlying(self):
        registry = _registry([_entry(underlying_symbol="AAPL")])
        assert tokenized_collect._target_ids(registry, max_assets=32) == ()

    def test_available_row_persists_canonical_observation(self, tmp_path):
        registry = _registry([_entry()])
        store = VenueMarketStore(tmp_path / "market.db")
        calls = []

        def batch_provider(**kwargs):
            calls.append(kwargs)
            return [(NVDA_ID, "AVAILABLE", _live_data(NVDA_ID))]

        report, code = tokenized_collect.collect_once(
            rpc_url="https://rpc.example",
            as_of=NOW,
            registry=registry,
            store=store,
            batch_provider=batch_provider,
            acquire_one=lambda **kwargs: (_ for _ in ()).throw(
                AssertionError("retry must not run")),
        )
        assert code == 0 and report["state"] == "AVAILABLE"
        assert report["persisted"] == 1 and report["available"] == 1
        latest = store.get_latest_for_instrument(
            ROBINHOOD_NVDA, venue_id="robinhood-chain")
        assert latest is not None
        assert latest.price == "102" and latest.reference_price == "100"
        assert latest.ts == (NOW - timedelta(seconds=30)).isoformat()
        assert latest.collected_at == NOW.isoformat()
        assert calls and calls[0]["workers"] == 2

    def test_identical_source_evidence_dedupes_across_collection_times(self, tmp_path):
        registry = _registry([_entry()])
        store = VenueMarketStore(tmp_path / "market.db")
        data = _live_data(NVDA_ID)

        def batch_provider(**kwargs):
            return [(NVDA_ID, "AVAILABLE", data)]

        first, first_code = tokenized_collect.collect_once(
            rpc_url="https://rpc.example", as_of=NOW,
            registry=registry, store=store, batch_provider=batch_provider)
        second, second_code = tokenized_collect.collect_once(
            rpc_url="https://rpc.example", as_of=NOW + timedelta(minutes=5),
            registry=registry, store=store, batch_provider=batch_provider)
        assert first_code == second_code == 0
        assert first["persisted"] == 1 and second["persisted"] == 0
        assert second["duplicates"] == 1
        assert store.count() == 1

    def test_one_asset_failure_does_not_suppress_healthy_sibling(self, tmp_path):
        registry = _registry([_entry(), _aapl_entry()])
        store = VenueMarketStore(tmp_path / "market.db")

        def batch_provider(**kwargs):
            return [
                (NVDA_ID, "AVAILABLE", _live_data(NVDA_ID)),
                (AAPL_ID, "UNAVAILABLE", {"reason": "RPC_UNAVAILABLE"}),
            ]

        def failed_retry(**kwargs):
            raise RuntimeError("provider down")

        report, code = tokenized_collect.collect_once(
            rpc_url="https://rpc.example", as_of=NOW,
            registry=registry, store=store,
            batch_provider=batch_provider, acquire_one=failed_retry,
            retries=1, backoff_seconds=0, sleeper=lambda _: None)
        assert code == 3 and report["state"] == "PARTIAL"
        assert report["available"] == 1 and report["unavailable"] == 1
        assert store.get_latest_for_instrument(
            ROBINHOOD_NVDA, venue_id="robinhood-chain") is not None
        assert store.count() == 1

    def test_failed_refresh_never_erases_previous_history(self, tmp_path):
        registry = _registry([_entry()])
        store = VenueMarketStore(tmp_path / "market.db")

        tokenized_collect.collect_once(
            rpc_url="https://rpc.example", as_of=NOW,
            registry=registry, store=store,
            batch_provider=lambda **kwargs: [
                (NVDA_ID, "AVAILABLE", _live_data(NVDA_ID))])
        before = store.count()

        report, code = tokenized_collect.collect_once(
            rpc_url="https://rpc.example", as_of=NOW + timedelta(minutes=5),
            registry=registry, store=store,
            batch_provider=lambda **kwargs: [
                (NVDA_ID, "UNAVAILABLE", {"reason": "RPC_UNAVAILABLE"})],
            acquire_one=lambda **kwargs: (_ for _ in ()).throw(RuntimeError()),
            retries=0)
        assert code == 3 and report["unavailable"] == 1
        assert store.count() == before == 1
        assert store.get_latest_for_instrument(
            ROBINHOOD_NVDA, venue_id="robinhood-chain").price == "102"

    def test_retry_backoff_is_bounded(self, monkeypatch):
        sleeps = []
        calls = {"n": 0}

        class Result:
            pass

        def acquire(**kwargs):
            calls["n"] += 1
            if calls["n"] < 3:
                raise RuntimeError("down")
            return Result()

        monkeypatch.setattr(
            tokenized_collect, "format_r_live_result",
            lambda canonical_id, result: (
                "AVAILABLE", _live_data(canonical_id)))
        row = tokenized_collect._retry_one(
            NVDA_ID,
            rpc_url="https://rpc.example",
            as_of=NOW,
            retries=2,
            backoff_seconds=0.25,
            acquire_one=acquire,
            sleeper=sleeps.append,
        )
        assert row[1] == "AVAILABLE"
        assert calls["n"] == 3
        assert sleeps == [0.25, 0.5]

    def test_quarantine_is_persisted_but_not_counted_available(self, tmp_path):
        registry = _registry([_entry(trading_halted=True)])
        store = VenueMarketStore(tmp_path / "market.db")
        report, code = tokenized_collect.collect_once(
            rpc_url="https://rpc.example", as_of=NOW,
            registry=registry, store=store,
            batch_provider=lambda **kwargs: [
                (NVDA_ID, "AVAILABLE", _live_data(NVDA_ID))])
        assert code == 3
        assert report["available"] == 0 and report["quarantined"] == 1
        latest = store.get_latest_for_instrument(
            ROBINHOOD_NVDA, venue_id="robinhood-chain")
        assert latest.observation_status is ObservationStatus.QUARANTINED

    def test_cli_disabled_and_missing_rpc_never_expose_or_acquire(self):
        out = io.StringIO()
        assert tokenized_collect.main([], env={}, out=out) == 4
        assert '"state": "DISABLED"' in out.getvalue()

        out = io.StringIO()
        assert tokenized_collect.main(
            [], env={"FINCO_TOKENIZED_COLLECTOR_ENABLED": "1"}, out=out) == 4
        assert "RPC_NOT_CONFIGURED" in out.getvalue()
        assert "https://" not in out.getvalue()


class TestCollectorHealth:
    def test_readonly_health_does_not_create_database(self, tmp_path):
        path = tmp_path / "missing.db"
        value = read_tokenized_collector_health(path=str(path), now=NOW)
        assert value.health_state == "UNHEALTHY"
        assert not path.exists()

    def test_health_heartbeat_ages_at_read_time(self, tmp_path):
        path = tmp_path / "health.db"
        with TokenizedCollectorHealthStore(str(path)) as store:
            store.record_attempt(now=NOW)
            store.record_complete(
                attempted=1, available=1, stale=0, unavailable=0,
                quarantined=0, persisted=1, duplicates=0, now=NOW)
        live = read_tokenized_collector_health(
            path=str(path), now=NOW + timedelta(minutes=5))
        stale = read_tokenized_collector_health(
            path=str(path), now=NOW + timedelta(minutes=16))
        stopped = read_tokenized_collector_health(
            path=str(path), now=NOW + timedelta(hours=2))
        assert live.health_state == HEALTHY and live.liveness == LIVENESS_LIVE
        assert stale.liveness == LIVENESS_STALE
        assert stopped.liveness == LIVENESS_STOPPED
        assert stopped.health_state == "UNHEALTHY"


class TestHistoryIntelligence:
    def _registry_two_venues(self):
        xstocks = _entry(
            platform="xstocks",
            representation_symbol="NVDAx",
            network="xstocks",
            chain_id=None,
            contract_address="0x" + "88" * 20,
            source="xstocks-test",
            source_ref="xstocks-test",
        )
        return _registry([_entry(), xstocks])

    def test_exact_24h_7d_basis_changes_no_interpolation(self, tmp_path):
        registry = _registry([_entry()])
        store = VenueMarketStore(tmp_path / "market.db")
        latest_at = NOW - timedelta(minutes=5)
        store.append_observation(_market_obs(
            venue="robinhood-chain", instrument=ROBINHOOD_NVDA,
            price="99", at=latest_at - timedelta(days=8)))
        store.append_observation(_market_obs(
            venue="robinhood-chain", instrument=ROBINHOOD_NVDA,
            price="101", at=latest_at - timedelta(hours=25)))
        # This row is newer than the exact 24h cutoff and must NOT become
        # the baseline; no interpolation or nearest-point substitution.
        store.append_observation(_market_obs(
            venue="robinhood-chain", instrument=ROBINHOOD_NVDA,
            price="150", at=latest_at - timedelta(hours=23)))
        store.append_observation(_market_obs(
            venue="robinhood-chain", instrument=ROBINHOOD_NVDA,
            price="102", at=latest_at))

        intel = build_tokenized_intelligence(
            "NVDA", registry=registry, store=store, as_of=NOW)
        row = intel.representations[0]
        assert row.latest_basis_bps == "200"
        assert row.basis_change_24h_bps == "100"
        assert row.basis_change_7d_bps == "300"

    def test_cross_underlying_store_evidence_fails_closed(self, tmp_path):
        registry = _registry([_entry()])
        store = VenueMarketStore(tmp_path / "market.db")
        store.append_observation(_market_obs(
            venue="robinhood-chain", instrument=ROBINHOOD_NVDA,
            price="999", at=NOW - timedelta(minutes=5),
            canonical_asset_id="AAPL"))
        row = build_tokenized_intelligence(
            "NVDA", registry=registry, store=store,
            as_of=NOW).representations[0]
        assert row.current_state == "UNAVAILABLE"
        assert row.latest_price is None
        assert row.latest_basis_bps is None
        assert row.basis_change_24h_bps is None
        assert row.points == ()

    def test_missing_baseline_is_none_not_zero(self, tmp_path):
        registry = _registry([_entry()])
        store = VenueMarketStore(tmp_path / "market.db")
        store.append_observation(_market_obs(
            venue="robinhood-chain", instrument=ROBINHOOD_NVDA,
            price="102", at=NOW - timedelta(minutes=5)))
        row = build_tokenized_intelligence(
            "NVDA", registry=registry, store=store,
            as_of=NOW).representations[0]
        assert row.basis_change_24h_bps is None
        assert row.basis_change_7d_bps is None

    def test_read_time_aging_marks_old_market_stale(self):
        observation = _market_obs(
            venue="robinhood-chain", instrument=ROBINHOOD_NVDA,
            price="102", at=NOW - timedelta(minutes=20))
        assert effective_observation_state(
            observation, as_of=NOW, max_age_seconds=900) == "STALE"

    def test_missing_source_timestamp_does_not_promote_overall_to_stale(
            self, tmp_path):
        registry = _registry([_entry()])
        store = VenueMarketStore(tmp_path / "market.db")
        store.append_observation(MarketObservation(
            ts=None,
            collected_at=NOW.isoformat(),
            canonical_asset_id="NVDA",
            venue_id="robinhood-chain",
            instrument_id=ROBINHOOD_NVDA,
            instrument_type="tokenized-equity",
            price="102",
            reference_price="100",
            source="test",
            freshness_state=FreshnessState.AVAILABLE,
            observation_status=ObservationStatus.OK,
            payload={
                "reference_state": "AVAILABLE",
                "reference_observed_at": NOW.isoformat(),
                "comparison_unit": COMPARISON_UNIT,
            },
        ))
        view = compose_underlying(
            "NVDA",
            registry=registry,
            store=store,
            now=NOW,
            reference_reader=lambda symbol: [{
                "symbol": symbol,
                "state": "FRESH",
                "price": "100",
                "observed_at": NOW.isoformat(),
                "source": "test-reference",
            }],
        )
        assert view.representations[0].freshness_state == "UNAVAILABLE"
        assert view.representations[0].basis_bps is None
        assert view.overall_state == "UNAVAILABLE"

    def test_missing_source_timestamp_is_unavailable(self):
        observation = MarketObservation(
            ts=None,
            collected_at=NOW.isoformat(),
            canonical_asset_id="NVDA",
            venue_id="robinhood-chain",
            instrument_id=ROBINHOOD_NVDA,
            instrument_type="tokenized-equity",
            price="102",
            source="test",
            freshness_state=FreshnessState.AVAILABLE,
            observation_status=ObservationStatus.OK,
            payload={},
        )
        assert effective_observation_state(observation, as_of=NOW) == "UNAVAILABLE"

    def test_quarantined_history_has_no_basis(self, tmp_path):
        registry = _registry([_entry()])
        store = VenueMarketStore(tmp_path / "market.db")
        store.append_observation(_market_obs(
            venue="robinhood-chain", instrument=ROBINHOOD_NVDA,
            price="102", at=NOW - timedelta(minutes=5),
            status=ObservationStatus.QUARANTINED))
        row = build_tokenized_intelligence(
            "NVDA", registry=registry, store=store,
            as_of=NOW).representations[0]
        assert row.current_state == "QUARANTINED"
        assert row.latest_basis_bps is None
        assert row.latest_basis_reason == "REPRESENTATION_QUARANTINED"

    def test_cross_venue_requires_exact_comparable_current_evidence(self, tmp_path):
        registry = self._registry_two_venues()
        store = VenueMarketStore(tmp_path / "market.db")
        stamp = NOW - timedelta(minutes=5)
        store.append_observation(_market_obs(
            venue="robinhood-chain", instrument=ROBINHOOD_NVDA,
            price="102", at=stamp))
        store.append_observation(_market_obs(
            venue="xstocks", instrument="0x" + "88" * 20,
            price="103", at=stamp))
        intel = build_tokenized_intelligence(
            "NVDA", registry=registry, store=store, as_of=NOW)
        assert intel.cross_venue.state == "AVAILABLE"
        assert intel.cross_venue.divergence_bps == "98"
        assert {intel.cross_venue.low_venue, intel.cross_venue.high_venue} == {
            "robinhood-chain", "xstocks"}

    def test_cross_venue_unit_or_clock_mismatch_fails_closed(self, tmp_path):
        registry = self._registry_two_venues()
        store = VenueMarketStore(tmp_path / "market.db")
        stamp = NOW - timedelta(minutes=5)
        store.append_observation(_market_obs(
            venue="robinhood-chain", instrument=ROBINHOOD_NVDA,
            price="102", at=stamp))
        store.append_observation(_market_obs(
            venue="xstocks", instrument="0x" + "88" * 20,
            price="103", at=stamp, comparison_unit="DIFFERENT_UNIT"))
        intel = build_tokenized_intelligence(
            "NVDA", registry=registry, store=store, as_of=NOW)
        assert intel.cross_venue.state == "UNAVAILABLE"
        assert intel.cross_venue.reason == "COMPARISON_UNIT_MISMATCH"

        store2 = VenueMarketStore(tmp_path / "market2.db")
        store2.append_observation(_market_obs(
            venue="robinhood-chain", instrument=ROBINHOOD_NVDA,
            price="102", at=stamp))
        store2.append_observation(_market_obs(
            venue="xstocks", instrument="0x" + "88" * 20,
            price="103", at=stamp - timedelta(minutes=6)))
        intel2 = build_tokenized_intelligence(
            "NVDA", registry=registry, store=store2, as_of=NOW)
        assert intel2.cross_venue.state == "UNAVAILABLE"
        assert intel2.cross_venue.reason == "CROSS_VENUE_EVIDENCE_SKEW_EXCEEDED"

    def test_dislocation_detection_is_evidence_label_not_execution_claim(
            self, tmp_path, monkeypatch):
        monkeypatch.setenv("FINCO_TOKENIZED_DISLOCATION_THRESHOLD_BPS", "50")
        registry = _registry([_entry()])
        store = VenueMarketStore(tmp_path / "market.db")
        store.append_observation(_market_obs(
            venue="robinhood-chain", instrument=ROBINHOOD_NVDA,
            price="100.2", at=NOW - timedelta(hours=2)))
        store.append_observation(_market_obs(
            venue="robinhood-chain", instrument=ROBINHOOD_NVDA,
            price="102", at=NOW - timedelta(minutes=5)))
        intel = build_tokenized_intelligence(
            "NVDA", registry=registry, store=store, as_of=NOW)
        assert any(
            event.event_type == "REFERENCE_DIVERGENCE"
            and event.direction == "PREMIUM"
            and Decimal(event.value_bps) >= Decimal("50")
            for event in intel.events
        )


class TestBrowserBoundary:
    def test_tokenized_detail_uses_persisted_evidence_not_market_provider(
            self, tmp_path, monkeypatch):
        db_path = tmp_path / "venues.db"
        store = VenueMarketStore(db_path)
        now = datetime.now(timezone.utc)
        store.append_observation(_market_obs(
            venue="robinhood-chain", instrument=ROBINHOOD_NVDA,
            price="102", at=now - timedelta(seconds=30),
            reference_at=now - timedelta(seconds=30)))
        monkeypatch.setenv("FINCO_VENUE_DB_PATH", str(db_path))

        class ExplodingMarketService:
            def read(self, **kwargs):
                raise AssertionError("browser must not acquire provider evidence")

        import app.radar_ui.router as radar_router
        monkeypatch.setattr(
            radar_router, "_market_read_service", ExplodingMarketService())

        from app.radar_ui.tokenized_router import router
        app = FastAPI()
        app.include_router(router)
        session = SimpleNamespace(
            user_id="user-1", username="qa", login_at=None, session_type="user")
        monkeypatch.setattr(
            "app.auth.resolve_request_session", lambda request: session)

        page = TestClient(app, raise_server_exceptions=True).get(
            "/radar/tokenized-markets/NVDA")
        assert page.status_code == 200
        assert 'data-testid="tmd-history-table"' in page.text
        assert 'data-testid="tmd-basis-history-chart"' in page.text
        assert "never triggers market acquisition" in page.text

    def test_router_has_no_market_acquisition_import(self):
        source = Path("app/radar_ui/tokenized_router.py").read_text(encoding="utf-8")
        for forbidden in (
            "_market_read_service",
            "RobinhoodAssetRegistryAdapter",
            "collect_r_live",
            "tokenized_collect",
        ):
            assert forbidden not in source


class TestDeploymentContract:
    def test_systemd_is_job_driven_bounded_and_not_web(self):
        base = Path("deploy/tokenized_market_collector_v1")
        service = (base / "finco-tokenized-market-collector.service").read_text()
        timer = (base / "finco-tokenized-market-collector.timer").read_text()
        env = (base / "tokenized-market-collector.env.example").read_text()
        assert "python -m app.radar_rwa.tokenized_collect" in service
        assert "flock -n -E 75" in service
        assert "SuccessExitStatus=3" in service
        assert "[Install]" not in service
        assert "OnCalendar=*-*-* *:00/5:00" in timer
        assert "FINCO_TOKENIZED_COLLECTOR_ENABLED=0" in env
        assert "FINCO_TOKENIZED_COLLECTOR_MAX_ASSETS=32" in env

    @pytest.mark.parametrize("namespace", ["financial_engine", "finco_core"])
    def test_frozen_namespaces_zero_diff(self, namespace):
        import subprocess
        root = Path(__file__).resolve().parents[1]
        out = subprocess.run(
            ["git", "diff", "--name-only", "origin/main..HEAD", "--", namespace],
            cwd=root, capture_output=True, text=True)
        if out.returncode != 0:
            pytest.skip("git unavailable")
        assert out.stdout.strip() == "", out.stdout
