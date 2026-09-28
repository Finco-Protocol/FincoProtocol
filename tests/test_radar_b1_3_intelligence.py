"""B1.3 exact-identity intelligence over the unchanged B1.0 calculation."""
from __future__ import annotations

from dataclasses import replace
from datetime import datetime, timedelta, timezone
from decimal import Decimal

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from app.radar_rwa.bnb_history import BnbIntelligenceHistoryStore, make_history_point
from app.radar_rwa.bnb_intelligence import BnbAuthorityEvidence, compose_bnb_intelligence
from app.radar_rwa.bnb_service import BnbRwaDashboardService, serialize_bnb_snapshot
from app.radar_rwa.bnb_snapshot import compose_bnb_snapshot
from app.radar_ui import rwa_router
from finco_radar.assets.adapters.robinhood import RobinhoodAssetRegistryAdapter
from finco_radar.assets.contracts import AssetKey, CanonicalAssetRecord, RegistryAssetStatus
from finco_radar.assets.registry import RegistrySnapshot
from finco_radar.authority.contracts import AuthorityPolicy, AuthorityState, IndependentTokenReference
from finco_radar.authority.cross_chain import CrossChainIdentityBinding, resolve_cross_chain_identity, select_cross_chain_registry
from finco_radar.gap.engine import build_bound_reference_price
from finco_radar.quotes.contracts import (
    AssetRef, ExecutionQuote, QuoteEvidence, QuoteSide, QuoteStatus, RouteLeg,
    SettlementReference, SettlementReferenceState,
)

NOW = datetime(2026, 9, 28, 12, tzinfo=timezone.utc)
UID = "0x" + "11" * 32
OTHER_UID = "0x" + "22" * 32
RH = AssetKey(4663, "0x" + "aa" * 20)
BNB = AssetKey(56, "0x" + "bb" * 20)
OTHER_BNB = AssetKey(56, "0x" + "dd" * 20)
SETTLEMENT = AssetRef(56, "0x" + "cc" * 20, decimals=18)
POLICY = AuthorityPolicy(3600, 120, 60, 60, frozenset({"TEST_INDEPENDENT_ATTESTED_MARKET"}))


def registry(*, key=BNB, uid=UID):
    asset = CanonicalAssetRecord(uid, "AAA", "AAA equity token", (RH, key), Decimal("1"),
                                 None, None, RegistryAssetStatus.ACTIVE)
    return RegistrySnapshot(RobinhoodAssetRegistryAdapter.source_name, NOW, (asset,))


def binding(reg=None, *, key=BNB):
    reg = reg or registry()
    context = select_cross_chain_registry(lambda: reg, None, as_of=NOW, max_age_seconds=3600)
    return resolve_cross_chain_identity(context, key)


def underlying(reg=None, *, key=BNB, at=NOW):
    reg = reg or registry()
    owner = reg.require_by_key(key)
    row = {"tokenSymbol": owner.token_symbol,
           "deployments": [{"chainId": key.chain_id, "contractAddress": key.contract_address}],
           "bid": "99", "ask": "101", "currency": "USD", "generatedAt": at.isoformat(),
           "isTradingHalt": False}
    return build_bound_reference_price(owner, reg.reference_binding(key), row)


def token(*, key=BNB, uid=UID, price="105", source="TEST_INDEPENDENT_ATTESTED_MARKET", at=NOW):
    return IndependentTokenReference(uid, key, Decimal(price), source, at)


def quote(*, key=BNB, price="110", at=NOW, status=QuoteStatus.QUOTE_OK):
    token_leg = AssetRef(key.chain_id, key.contract_address, decimals=18)
    settlement = SettlementReference(SETTLEMENT, SettlementReferenceState.REFERENCE_CURRENT,
                                     Decimal("1"), "TEST_SETTLEMENT", at)
    return ExecutionQuote(
        chain_id=key.chain_id, token_address=key.contract_address, side=QuoteSide.BUY,
        input_asset=SETTLEMENT, output_asset=token_leg,
        requested_notional_usd=Decimal(price), raw_amount_in=int(Decimal(price)), raw_amount_out=1,
        normalized_amount_in=Decimal(price), normalized_amount_out=Decimal("1"),
        input_decimals=18, output_decimals=18, source="LIFI_EXECUTION", quoted_at=at,
        settlement_reference=settlement, status=status,
        fee_cost_usd=Decimal("1"), gas_cost_usd=Decimal("2"),
        evidence=QuoteEvidence({}, {}, (RouteLeg("DEX", SETTLEMENT.contract_address,
                                                 key.contract_address),)),
    )


def evidence(*, reg=None, ref=None, independent=None, execution=None, policy=POLICY):
    reg = reg or registry()
    return BnbAuthorityEvidence(
        reg, ref if ref is not None else underlying(reg),
        independent, execution, policy,
    )


def compose(*, reg=None, bound=None, proof=None, at=NOW, key=BNB):
    reg = reg or registry()
    return compose_bnb_intelligence(key, bound if bound is not None else binding(reg, key=key),
                                    proof, as_of=at)


def test_a_m_full_valid_chain_and_exact_decomposition():
    result = compose(proof=evidence(independent=token(), execution=quote()))
    assert result["robinhood_basis"]["price_usd_per_token"] == "100"
    assert result["independent_token_reference"]["price_usd_per_token"] == "105"
    assert Decimal(result["reference_premium"]["value_bps"]) == 500
    assert result["execution"]["effective_price_usd_per_token"] == "110"
    assert Decimal(result["execution_gap"]["execution_impact_bps"]) == 500
    assert Decimal(result["execution_gap"]["effective_gap_bps"]) == 1000
    assert Decimal(result["execution_gap"]["effective_gap_bps"]) == (
        Decimal(result["reference_premium"]["value_bps"])
        + Decimal(result["execution_gap"]["execution_impact_bps"])
    )
    assert Decimal(result["execution_gap"]["effective_gap_bps"]) == (Decimal("110") / Decimal("100") - 1) * 10000
    assert result["execution_gap"]["fee_treatment"] == "EVIDENCE_ONLY_INCLUSION_UNRESOLVED"
    assert result["execution"]["fee_cost_usd"] == "1"
    assert result["execution"]["gas_cost_usd"] == "2"


def test_b_negative_premium_is_not_suppressed():
    result = compose(proof=evidence(independent=token(price="95")))
    assert Decimal(result["reference_premium"]["value_bps"]) == -500
    assert result["execution_gap"]["effective_gap_bps"] is None


def test_c_d_identity_unavailable_and_wrong_deployment_fail_closed():
    assert compose_bnb_intelligence(BNB, None, evidence(independent=token()), as_of=NOW)["reference_premium"]["value_bps"] is None
    wrong = binding(key=OTHER_BNB)
    result = compose_bnb_intelligence(BNB, wrong, evidence(independent=token()), as_of=NOW)
    assert result["reference_premium"]["state"] == "IDENTITY_UNAVAILABLE"
    assert result["execution_gap"]["effective_gap_bps"] is None
    mismatched_reg = registry(key=BNB, uid=OTHER_UID)
    result = compose(proof=evidence(reg=mismatched_reg, independent=token()))
    assert result["reason"] == "CANONICAL_REGISTRY_IDENTITY_MISMATCH"
    later_reg = replace(registry(), observed_at=NOW + timedelta(seconds=1))
    assert compose(proof=evidence(reg=later_reg, ref=underlying(later_reg),
                                  independent=token()))["reason"] == "CANONICAL_REGISTRY_IDENTITY_MISMATCH"


@pytest.mark.parametrize("source", ["COINGECKO", "LIFI_EXECUTION", "DEFILLAMA", "ROBINHOOD"])
def test_e_f_prohibited_token_references_never_produce_premium(source):
    policy = replace(POLICY, approved_token_reference_sources=frozenset({source}))
    result = compose(proof=evidence(independent=token(source=source), execution=quote(), policy=policy))
    assert result["independent_token_reference"]["state"] == "UNAVAILABLE"
    assert result["reference_premium"]["value_bps"] is None
    assert result["execution_gap"]["effective_gap_bps"] is None


def test_g_missing_independent_reference_never_uses_execution_price():
    result = compose(proof=evidence(execution=quote()))
    assert result["execution"]["state"] == "AVAILABLE"
    assert result["independent_token_reference"]["price_usd_per_token"] is None
    assert result["reference_premium"]["value_bps"] is None


def test_unapproved_source_and_stale_identity_are_not_calculable():
    unapproved = compose(proof=evidence(independent=token(source="UNAPPROVED_EXCHANGE")))
    assert unapproved["reference_premium"]["value_bps"] is None
    stale_binding = CrossChainIdentityBinding(
        AuthorityState.STALE, BNB, None, (), None, None, "ROBINHOOD_REGISTRY_STALE",
    )
    stale = compose(bound=stale_binding, proof=evidence(independent=token(), execution=quote()))
    assert stale["reference_premium"]["state"] == "STALE"
    assert stale["execution_gap"]["effective_gap_bps"] is None


def test_h_i_j_stale_and_incoherent_evidence_fail_closed():
    stale_underlying = compose(proof=evidence(ref=underlying(at=NOW - timedelta(minutes=3)),
                                              independent=token()), at=NOW)
    assert stale_underlying["reference_premium"]["state"] == "STALE"
    stale_token = compose(proof=evidence(independent=token(at=NOW - timedelta(minutes=3))), at=NOW)
    assert stale_token["reference_premium"]["state"] == "STALE"
    mismatch = compose(proof=evidence(independent=token(at=NOW - timedelta(seconds=90))), at=NOW)
    assert mismatch["reference_premium"]["reason"] == "REFERENCE_TIME_MISMATCH"


def test_k_l_premium_without_execution_and_wrong_execution_deployment():
    no_execution = compose(proof=evidence(independent=token()))
    assert no_execution["reference_premium"]["state"] == "AVAILABLE"
    assert no_execution["execution_gap"]["state"] == "UNAVAILABLE"
    wrong = compose(proof=evidence(independent=token(), execution=quote(key=OTHER_BNB)))
    assert wrong["execution"]["state"] == "IDENTITY_UNAVAILABLE"
    assert wrong["execution_gap"]["effective_gap_bps"] is None


def test_stale_execution_and_execution_timestamp_mismatch_remain_separate():
    stale = compose(proof=evidence(independent=token(), execution=quote(status=QuoteStatus.STALE_QUOTE)))
    assert stale["reference_premium"]["state"] == "AVAILABLE"
    assert stale["execution_gap"]["state"] == "STALE"
    assert stale["execution_gap"]["effective_gap_bps"] is None
    longer_quote_policy = replace(POLICY, max_execution_age_seconds=120)
    mismatched = compose(proof=evidence(
        independent=token(), execution=quote(at=NOW - timedelta(seconds=90)),
        policy=longer_quote_policy,
    ))
    assert mismatched["execution"]["state"] == "AVAILABLE"
    assert mismatched["execution_gap"]["reason"] == "EXECUTION_TIME_MISMATCH"


def test_default_production_wiring_can_show_official_basis_but_not_invent_token_price(monkeypatch):
    reg = registry()

    class Identity:
        def selected_registry_snapshot(self):
            return reg

    class Adapter:
        def __enter__(self):
            return self

        def __exit__(self, *_):
            return None

        def fetch_bound_reference(self, selected, key):
            assert selected is reg and key == BNB
            return reg.reference_binding(BNB), {
                "tokenSymbol": "AAA", "deployments": [{"chainId": 56,
                    "contractAddress": BNB.contract_address}],
                "bid": "99", "ask": "101", "currency": "USD",
                "generatedAt": NOW.isoformat(), "isTradingHalt": False,
            }

    monkeypatch.setattr("app.radar_rwa.bnb_service.RobinhoodAssetRegistryAdapter", Adapter)
    service = BnbRwaDashboardService(identity_service=Identity(), now=lambda: NOW)
    result = compose(proof=service._default_evidence(BNB, binding(reg)))
    assert result["robinhood_basis"]["price_usd_per_token"] == "100"
    assert result["independent_token_reference"]["price_usd_per_token"] is None
    assert result["reference_premium"]["value_bps"] is None


def test_n_o_p_history_is_exact_identity_not_symbol_and_missing_is_null(tmp_path):
    store = BnbIntelligenceHistoryStore(str(tmp_path / "history.db"))
    first = compose(proof=evidence(independent=token(), execution=quote()))
    point = make_history_point(binding(), first, NOW.isoformat())
    assert point is not None
    store.put(point)
    store.put(point)  # same canonical evidence is idempotent
    assert len(store.read(UID, BNB)) == 1
    assert store.read(UID, OTHER_BNB) == []
    assert store.read(OTHER_UID, BNB) == []
    second_reg = registry(key=OTHER_BNB)
    second = compose(reg=second_reg, key=OTHER_BNB,
                     proof=evidence(reg=second_reg, ref=underlying(second_reg, key=OTHER_BNB),
                                    independent=token(key=OTHER_BNB)))
    second_point = make_history_point(binding(second_reg, key=OTHER_BNB), second, NOW.isoformat())
    assert second_point is not None and second_point["total_execution_gap_bps"] is None
    store.put(second_point)
    assert len(store.read(UID, BNB)) == len(store.read(UID, OTHER_BNB)) == 1
    assert first["reference_premium"]["value_bps"] is not None
    unavailable = compose(proof=None)
    assert unavailable["reference_premium"]["value_bps"] is None
    assert make_history_point(binding(), unavailable, NOW.isoformat()) is None
    store.close()
    reopened = BnbIntelligenceHistoryStore(str(tmp_path / "history.db"))
    assert len(reopened.read(UID, BNB)) == len(reopened.read(UID, OTHER_BNB)) == 1
    reopened.close()


def test_q_api_ui_available_and_unavailable_fixtures(tmp_path):
    market = compose_bnb_snapshot(
        platforms=[{"id": "binance-smart-chain", "chain_identifier": 56}],
        coins=[{"id": "coin-a", "symbol": "aaa", "name": "Asset A",
                "platforms": {"binance-smart-chain": BNB.contract_address}}],
        markets=[{"id": "coin-a", "symbol": "aaa", "name": "Asset A",
                  "last_updated": NOW.isoformat(), "current_price": 1, "market_cap": 100,
                  "total_volume": 10, "price_change_percentage_24h": 0,
                  "circulating_supply": None, "total_supply": None}],
        retrieved_at=NOW,
    )

    class Provider:
        def read_snapshot(self):
            return market

    class Identity:
        def resolve_snapshot(self, _):
            return {BNB: binding()}

    store = BnbIntelligenceHistoryStore(str(tmp_path / "history.db"))
    service = BnbRwaDashboardService(Provider(), Identity(),
                                     evidence_resolver=lambda _key, _binding: evidence(independent=token(), execution=quote()),
                                     history_store=store, now=lambda: NOW)
    payload = service.read_payload()
    row = payload["observations"][0]
    assert Decimal(row["intelligence"]["reference_premium"]["value_bps"]) == 500
    assert row["price_usd"] == "1"  # CoinGecko observation never becomes the numerator (105).
    assert row["intelligence"]["independent_token_reference"]["price_usd_per_token"] == "105"
    assert len(row["intelligence_history"]) == 1
    previous = rwa_router._bnb_service
    rwa_router.set_bnb_service(service)
    try:
        app = FastAPI()
        app.include_router(rwa_router.router)
        client = TestClient(app)
        page = client.get("/radar/crypto/rwa/bnb")
        assert page.status_code == 200
        assert "Reference premium" in page.text and "500" in page.text
        assert "Execution gap" in page.text and "1000" in page.text
        api = client.get("/radar/crypto/rwa/bnb/snapshot").json()
        assert Decimal(api["observations"][0]["intelligence"]["execution_gap"]["effective_gap_bps"]) == 1000
        history = client.get("/radar/crypto/rwa/bnb/history", params={
            "economic_asset_uid": UID, "contract_address": BNB.contract_address,
        }).json()
        assert len(history["points"]) == 1
        assert client.get("/radar/crypto/rwa/bnb/history", params={
            "economic_asset_uid": OTHER_UID, "contract_address": BNB.contract_address,
        }).json()["points"] == []
    finally:
        rwa_router.set_bnb_service(previous)
        store.close()
    unavailable = serialize_bnb_snapshot(market)["observations"][0]["intelligence"]
    assert unavailable["reference_premium"]["value_bps"] is None
    assert unavailable["execution_gap"]["effective_gap_bps"] is None
