"""B1.2 exact cross-chain identity: no market-provider identity inference."""
from __future__ import annotations

from dataclasses import replace
from datetime import datetime, timedelta, timezone
from decimal import Decimal

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from app.radar_rwa.bnb_identity import BnbCrossChainIdentityService
from app.radar_rwa.bnb_service import BnbRwaDashboardService, serialize_bnb_snapshot
from app.radar_rwa.bnb_snapshot import compose_bnb_snapshot
from app.radar_ui import rwa_router
from finco_radar.assets.adapters.robinhood import RobinhoodAssetRegistryAdapter
from finco_radar.assets.contracts import (
    AssetKey, CanonicalAssetRecord, RegistryAssetStatus,
    RegistryConflictError, RegistrySourceError,
)
from finco_radar.assets.registry import RegistrySnapshot
from finco_radar.authority.contracts import AuthorityState
from finco_radar.authority.cross_chain import (
    resolve_cross_chain_identity, select_cross_chain_registry,
)

NOW = datetime(2026, 9, 28, 12, tzinfo=timezone.utc)
UID = "0x" + "11" * 32
OTHER_UID = "0x" + "22" * 32
RH = AssetKey(4663, "0x" + "aa" * 20)
BNB = AssetKey(56, "0x" + "bb" * 20)
OTHER_BNB = AssetKey(56, "0x" + "cc" * 20)
WRONG_CHAIN = AssetKey(1, BNB.contract_address)


def _asset(uid=UID, deployments=(RH, BNB), symbol="ABC", name="Example equity token"):
    return CanonicalAssetRecord(
        uid, symbol, name, tuple(deployments), Decimal("1"), None, None,
        RegistryAssetStatus.ACTIVE,
    )


def _registry(*assets, observed_at=NOW, source=RobinhoodAssetRegistryAdapter.source_name):
    return RegistrySnapshot(source, observed_at, tuple(assets or (_asset(),)))


def _context(live=None, retained=None, *, as_of=NOW, failure=None):
    if failure is not None:
        def fetch():
            raise failure
    else:
        def fetch():
            return live
    return select_cross_chain_registry(
        fetch, retained, as_of=as_of, max_age_seconds=3600,
    )


def _bnb_market_snapshot(*, contract=BNB.contract_address, provider_id="coingecko-abc"):
    return compose_bnb_snapshot(
        platforms=[{"id": "binance-smart-chain", "chain_identifier": 56}],
        coins=[{"id": provider_id, "symbol": "abc", "name": "Example equity token",
                "platforms": {"binance-smart-chain": contract}}],
        markets=[{"id": provider_id, "symbol": "abc", "name": "Example equity token",
                  "last_updated": NOW.isoformat(), "current_price": 1,
                  "market_cap": 100, "total_volume": 10,
                  "price_change_percentage_24h": 0,
                  "circulating_supply": None, "total_supply": None}],
        retrieved_at=NOW,
    )


def test_a_exact_canonical_bnb_binding_is_available_only_for_owned_uid():
    result = resolve_cross_chain_identity(
        _context(live=_registry()), BNB, expected_economic_asset_uid=UID,
    )
    assert result.state is AuthorityState.AVAILABLE
    assert result.economic_asset_uid == UID
    assert result.external_asset_key == BNB
    assert result.canonical_deployments == (RH, BNB)
    assert result.authority_source == "ROBINHOOD_STOCK_TOKEN_ASSETS_API:LIVE"
    assert result.observed_at == NOW


def test_b_wrong_contract_c_wrong_chain_and_k_missing_deployment_fail_closed():
    context = _context(live=_registry())
    assert resolve_cross_chain_identity(context, OTHER_BNB, expected_economic_asset_uid=UID).state is AuthorityState.IDENTITY_UNAVAILABLE
    assert resolve_cross_chain_identity(context, WRONG_CHAIN, expected_economic_asset_uid=UID).state is AuthorityState.IDENTITY_UNAVAILABLE
    assert resolve_cross_chain_identity(context, None, expected_economic_asset_uid=UID).state is AuthorityState.IDENTITY_UNAVAILABLE
    assert resolve_cross_chain_identity(
        _context(live=_registry(_asset(deployments=(RH,)))), BNB,
        expected_economic_asset_uid=UID,
    ).state is AuthorityState.IDENTITY_UNAVAILABLE


def test_d_symbol_name_and_e_coingecko_id_do_not_create_identity():
    snapshot = _bnb_market_snapshot(provider_id="robinhood-ABC")
    assert snapshot.observations[0].symbol == "ABC"
    context = _context(live=_registry(_asset(deployments=(RH,))))
    result = resolve_cross_chain_identity(context, snapshot.observations[0].asset_key)
    assert result.state is AuthorityState.IDENTITY_UNAVAILABLE
    assert result.economic_asset_uid is None
    assert result.reason == "CANONICAL_BNB_DEPLOYMENT_ABSENT"


def test_f_valid_live_registry_precedes_convenient_retained_match():
    live = _registry(_asset(deployments=(RH,)))
    retained = _registry(_asset(deployments=(RH, BNB)))
    context = _context(live=live, retained=retained)
    assert context.selected is live and context.origin == "LIVE"
    result = resolve_cross_chain_identity(context, BNB, expected_economic_asset_uid=UID)
    assert result.state is not AuthorityState.AVAILABLE
    assert result.economic_asset_uid is None


def test_g_valid_retained_snapshot_is_used_only_on_live_outage():
    retained = _registry()
    context = _context(retained=retained, failure=ConnectionError("offline"))
    assert context.selected is retained and context.origin == "RETAINED"
    result = resolve_cross_chain_identity(context, BNB, expected_economic_asset_uid=UID)
    assert result.state is AuthorityState.AVAILABLE
    assert result.authority_source == "ROBINHOOD_STOCK_TOKEN_ASSETS_API:RETAINED"


def test_live_freshness_clock_is_sampled_after_registry_fetch():
    live = _registry(observed_at=NOW + timedelta(seconds=2))
    observed_order = []

    def fetch():
        observed_order.append("fetch")
        return live

    def clock():
        observed_order.append("clock")
        return NOW + timedelta(seconds=3)

    context = select_cross_chain_registry(fetch, None, as_of=clock, max_age_seconds=3600)
    assert observed_order == ["fetch", "clock"]
    assert resolve_cross_chain_identity(context, BNB).state is AuthorityState.AVAILABLE


def test_h_stale_retained_snapshot_cannot_authorize_current_identity():
    retained = _registry(observed_at=NOW - timedelta(seconds=3601))
    context = _context(retained=retained, failure=ConnectionError("offline"))
    result = resolve_cross_chain_identity(context, BNB)
    assert result.state is AuthorityState.STALE
    assert result.economic_asset_uid is None


def test_i_duplicate_deployment_and_live_retained_disagreement_fail_closed():
    with pytest.raises(RegistryConflictError):
        _registry(_asset(), _asset(OTHER_UID, deployments=(OTHER_BNB, BNB)))
    with pytest.raises(RegistryConflictError):
        _asset(deployments=(RH, BNB, OTHER_BNB))
    live = _registry(_asset())
    retained = _registry(_asset(OTHER_UID, deployments=(AssetKey(4663, "0x" + "dd" * 20), BNB)))
    result = resolve_cross_chain_identity(_context(live=live, retained=retained), BNB)
    assert result.state is AuthorityState.UNAVAILABLE
    assert result.reason == "LIVE_RETAINED_IDENTITY_CONFLICT"
    assert result.economic_asset_uid is None


def test_j_multiple_valid_chain_deployments_remain_separate_exact_keys():
    another = AssetKey(1, "0x" + "ee" * 20)
    asset = _asset(deployments=(RH, BNB, another))
    result = resolve_cross_chain_identity(_context(live=_registry(asset)), BNB)
    assert result.state is AuthorityState.AVAILABLE
    assert result.canonical_deployments == (RH, BNB, another)
    assert resolve_cross_chain_identity(_context(live=_registry(asset)), OTHER_BNB).state is AuthorityState.IDENTITY_UNAVAILABLE


def test_wrong_uid_or_unapproved_provenance_never_binds():
    result = resolve_cross_chain_identity(
        _context(live=_registry()), BNB, expected_economic_asset_uid=OTHER_UID,
    )
    assert result.state is AuthorityState.UNAVAILABLE
    assert result.reason == "DEPLOYMENT_OWNED_BY_DIFFERENT_UID"
    fake = _registry(source="COINGECKO")
    assert resolve_cross_chain_identity(_context(live=fake), BNB).state is AuthorityState.IDENTITY_UNAVAILABLE
    with pytest.raises(RegistrySourceError):
        AssetKey(56, "not-an-address")


def test_live_conflict_does_not_fall_back_and_in_app_retention_is_exact():
    retained = _registry()
    conflict = _context(retained=retained, failure=RegistryConflictError("collision"))
    assert resolve_cross_chain_identity(conflict, BNB).state is AuthorityState.UNAVAILABLE
    calls = 0

    def fetch():
        nonlocal calls
        calls += 1
        if calls == 1:
            return retained
        raise ConnectionError("offline")

    service = BnbCrossChainIdentityService(fetch_live=fetch)
    snapshot = _bnb_market_snapshot()
    assert service.resolve_snapshot(snapshot, as_of=NOW)[BNB].state is AuthorityState.AVAILABLE
    assert service.resolve_snapshot(snapshot, as_of=NOW)[BNB].authority_source.endswith(":RETAINED")
    assert calls == 2


def test_malformed_live_timestamp_is_not_replaced_with_retained_identity():
    malformed_live = _registry(observed_at="not-a-timestamp")
    result = resolve_cross_chain_identity(
        _context(live=malformed_live, retained=_registry()), BNB,
    )
    assert result.state is AuthorityState.UNAVAILABLE
    assert result.reason == "LIVE_ROBINHOOD_REGISTRY_TIMESTAMP_INVALID"


def test_l_api_and_ui_show_available_and_unavailable_without_overwriting_deployment():
    snapshot = _bnb_market_snapshot()
    binding = resolve_cross_chain_identity(_context(live=_registry()), BNB)
    payload = serialize_bnb_snapshot(snapshot, {BNB: binding})
    row = payload["observations"][0]
    assert row["asset_key"]["canonical_id"] == BNB.canonical_id
    assert row["canonical_identity"]["state"] == "AVAILABLE"
    assert row["canonical_identity"]["economic_asset_uid"] == UID
    assert row["canonical_identity"]["authority_source"].endswith(":LIVE")
    assert row["market_scope"] == "COINGECKO_COIN_GLOBAL_NOT_BNB_SPECIFIC"
    assert payload["rwa_tvl_usd"] is None

    class Provider:
        def read_snapshot(self):
            return snapshot

    class IdentityService:
        def resolve_snapshot(self, _snapshot):
            return {BNB: binding}

    service = BnbRwaDashboardService(Provider(), IdentityService())
    previous = rwa_router._bnb_service
    rwa_router.set_bnb_service(service)
    try:
        app = FastAPI()
        app.include_router(rwa_router.router)
        client = TestClient(app)
        page = client.get("/radar/crypto/rwa/bnb")
        assert page.status_code == 200
        assert UID in page.text
        assert "ROBINHOOD_STOCK_TOKEN_ASSETS_API:LIVE" in page.text
        assert BNB.canonical_id in page.text
        assert client.get("/radar/crypto/rwa/bnb/snapshot").json()["observations"][0]["canonical_identity"]["state"] == "AVAILABLE"
    finally:
        rwa_router.set_bnb_service(previous)

    unavailable = serialize_bnb_snapshot(snapshot)
    assert unavailable["observations"][0]["canonical_identity"]["state"] == "IDENTITY_UNAVAILABLE"
    assert unavailable["observations"][0]["canonical_identity"]["economic_asset_uid"] is None
