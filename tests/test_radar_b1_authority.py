"""B1.0 authority, identity, freshness, and decomposition regression ring."""
from dataclasses import replace
from datetime import datetime, timedelta, timezone
from decimal import Decimal

import pytest

from finco_radar.assets.adapters.robinhood import RobinhoodAssetRegistryAdapter
from finco_radar.assets.contracts import AssetKey, CanonicalAssetRecord, RegistryAssetStatus, RegistryConflictError
from finco_radar.assets.registry import RegistrySnapshot
from finco_radar.authority.contracts import AuthorityPolicy, AuthorityState, IndependentTokenReference
from finco_radar.authority.engine import build_authority_snapshot, select_robinhood_registry
from finco_radar.gap.engine import build_bound_reference_price
from finco_radar.liquidity.engine import execution_midpoint_usd_per_token
from finco_radar.quotes.contracts import (
    AssetRef, ExecutionQuote, QuoteEvidence, QuoteSide, QuoteStatus, RouteLeg,
    SettlementReference, SettlementReferenceState,
)
from finco_radar.tokenization_premium.contracts import TokenizationPremiumPolicy
from finco_radar.tokenization_premium.engine import compute_tokenization_premium

T0 = datetime(2026, 9, 27, 12, tzinfo=timezone.utc)
UID = "0x" + "11" * 32
OTHER_UID = "0x" + "22" * 32
KEY = AssetKey(4663, "0x" + "aa" * 20)
OTHER_KEY = AssetKey(56, "0x" + "bb" * 20)
SETTLEMENT = AssetRef(4663, "0x" + "cc" * 20, decimals=18)
POLICY = AuthorityPolicy(3600, 120, 60, 60,
                         frozenset({"TEST_ATTESTED_TOKEN_MARKET"}))


def asset(uid=UID, key=KEY, symbol="AAA"):
    return CanonicalAssetRecord(uid, symbol, "AAA equity token", (key,), Decimal("1"),
                                None, None, RegistryAssetStatus.ACTIVE)


def registry(*assets, source=RobinhoodAssetRegistryAdapter.source_name):
    return RegistrySnapshot(source, T0, tuple(assets or (asset(),)))


def underlying(reg=None, key=KEY):
    reg = reg or registry()
    owner = reg.require_by_key(key)
    binding = reg.reference_binding(key)
    row = {"tokenSymbol": owner.token_symbol,
           "deployments": [{"chainId": key.chain_id, "contractAddress": key.contract_address}],
           "bid": "99", "ask": "101", "currency": "USD",
           "generatedAt": T0.isoformat(), "isTradingHalt": False}
    return build_bound_reference_price(owner, binding, row)


def token_ref(**overrides):
    fields = dict(registry_asset_uid=UID, asset_key=KEY,
                  price_usd_per_token=Decimal("105"), source="TEST_ATTESTED_TOKEN_MARKET",
                  observed_at=T0)
    fields.update(overrides)
    return IndependentTokenReference(**fields)


def quote(**overrides):
    token = AssetRef(KEY.chain_id, KEY.contract_address, decimals=18)
    settlement = SettlementReference(SETTLEMENT, SettlementReferenceState.REFERENCE_CURRENT,
                                     Decimal("1"), "TEST_SETTLEMENT", T0)
    fields = dict(chain_id=KEY.chain_id, token_address=KEY.contract_address,
                  side=QuoteSide.BUY, input_asset=SETTLEMENT, output_asset=token,
                  requested_notional_usd=Decimal("110"), raw_amount_in=110,
                  raw_amount_out=1, normalized_amount_in=Decimal("110"),
                  normalized_amount_out=Decimal("1"), input_decimals=18,
                  output_decimals=18, source="TEST_EXECUTION", quoted_at=T0,
                  settlement_reference=settlement, status=QuoteStatus.QUOTE_OK,
                  fee_cost_usd=Decimal("1"), gas_cost_usd=Decimal("2"),
                  evidence=QuoteEvidence({}, {}, (RouteLeg("DEX", SETTLEMENT.contract_address,
                                                        KEY.contract_address),)))
    fields.update(overrides)
    return ExecutionQuote(**fields)


def build(reg=None, ref=None, token=None, execution=None, key=KEY, at=T0):
    return build_authority_snapshot(
        registry=reg if reg is not None else registry(), key=key,
        underlying_reference=ref if ref is not None else underlying(),
        token_reference=token, execution_quote=execution, as_of=at, policy=POLICY)


def test_valid_binding_and_transparent_gap_without_double_counting_fees():
    result = build(token=token_ref(), execution=quote())
    assert result.economic_asset_uid == UID
    assert result.underlying.price_usd_per_token == Decimal("100")
    assert result.token.price_usd_per_token == Decimal("105")
    assert result.premium.state is AuthorityState.AVAILABLE
    assert result.premium.value_bps == Decimal("500")
    assert result.premium.numerator_usd_per_token == Decimal("105")
    assert result.premium.denominator_usd_per_token == Decimal("100")
    assert result.premium.sources == ("ROBINHOOD_STOCK_TOKEN_BOUND_PRICE", "TEST_ATTESTED_TOKEN_MARKET")
    assert result.execution.requested_notional_usd == Decimal("110")
    assert result.execution.effective_price_usd_per_token == Decimal("110")
    assert result.execution.route == (("dex", SETTLEMENT.contract_address, KEY.contract_address),)
    assert result.execution_gap.reference_premium_bps == Decimal("500")
    assert result.execution_gap.execution_impact_bps == Decimal("500")
    assert result.execution_gap.effective_gap_bps == Decimal("1000")
    assert result.execution_gap.fee_treatment == "EVIDENCE_ONLY_INCLUSION_UNRESOLVED"
    assert result.execution.fee_cost_usd == 1 and result.execution.gas_cost_usd == 2


def test_missing_independent_token_reference_does_not_turn_quote_into_reference():
    result = build(execution=quote())
    assert result.underlying.state is AuthorityState.AVAILABLE
    assert result.token.state is AuthorityState.UNAVAILABLE
    assert result.execution.state is AuthorityState.AVAILABLE
    assert result.premium.value_bps is None and result.execution_gap.effective_gap_bps is None


def test_discount_sign_and_no_execution_are_independent():
    result = build(token=token_ref(price_usd_per_token=Decimal("95")))
    assert result.premium.value_bps == Decimal("-500")
    assert result.execution.state is AuthorityState.UNAVAILABLE
    assert result.execution_gap.effective_gap_bps is None


@pytest.mark.parametrize("bad_ref", [
    lambda: token_ref(registry_asset_uid=OTHER_UID),
    lambda: token_ref(asset_key=OTHER_KEY),
])
def test_wrong_uid_or_deployment_fails_closed(bad_ref):
    result = build(token=bad_ref(), execution=quote())
    assert result.token.state is AuthorityState.IDENTITY_UNAVAILABLE
    assert result.premium.state is AuthorityState.IDENTITY_UNAVAILABLE
    assert result.premium.value_bps is None


def test_symbol_only_and_unbound_bnb_deployment_are_not_identity():
    result = build(key=OTHER_KEY, token=token_ref(asset_key=OTHER_KEY))
    assert result.economic_asset_uid is None
    assert result.token.state is AuthorityState.IDENTITY_UNAVAILABLE
    assert result.execution.state is AuthorityState.IDENTITY_UNAVAILABLE


def test_explicit_second_deployment_of_same_registry_uid_can_bind():
    multi = replace(asset(), deployments=(KEY, OTHER_KEY))
    reg = registry(multi)
    result = build(reg=reg, key=OTHER_KEY, ref=underlying(reg, OTHER_KEY),
                   token=token_ref(asset_key=OTHER_KEY))
    assert result.economic_asset_uid == UID
    assert result.token.state is AuthorityState.AVAILABLE


def test_wrong_bound_reference_uid_and_missing_reference_are_unavailable():
    wrong = replace(underlying(), asset_uid=OTHER_UID)
    result = build(ref=wrong, token=token_ref())
    assert result.underlying.state is AuthorityState.UNAVAILABLE
    assert result.premium.value_bps is None
    missing = build_authority_snapshot(registry=registry(), key=KEY,
        underlying_reference=None, token_reference=token_ref(),
        execution_quote=None, as_of=T0, policy=POLICY)
    assert missing.underlying.state is AuthorityState.UNAVAILABLE
    assert missing.premium.value_bps is None


def test_wrong_quote_deployment_fails_closed_without_rebinding_by_symbol():
    wrong = quote(token_address=OTHER_KEY.contract_address)
    result = build(token=token_ref(), execution=wrong)
    assert result.execution.state is AuthorityState.IDENTITY_UNAVAILABLE
    assert result.premium.value_bps == Decimal("500")
    assert result.execution_gap.effective_gap_bps is None


def test_non_robinhood_registry_and_conflicting_snapshot_fail_closed():
    result = build(reg=registry(source="COINGECKO"), token=token_ref())
    assert result.premium.state is AuthorityState.IDENTITY_UNAVAILABLE
    with pytest.raises(RegistryConflictError):
        registry(asset(), asset(OTHER_UID, KEY, "BBB"))


def test_robinhood_live_identity_precedes_valid_retained_snapshot():
    live = registry(asset(UID, KEY))
    retained = registry(asset(OTHER_UID, KEY))
    chosen = select_robinhood_registry(lambda: live, retained, as_of=T0,
                                       max_age_seconds=60)
    assert chosen is live
    assert chosen.require_by_key(KEY).asset_uid == UID


def test_failed_live_read_uses_only_valid_unconflicted_retained_snapshot():
    retained = registry()
    def failed_live():
        raise ConnectionError("offline")
    assert select_robinhood_registry(failed_live, retained, as_of=T0,
                                     max_age_seconds=60) is retained
    assert select_robinhood_registry(failed_live, registry(source="COINGECKO"),
                                     as_of=T0, max_age_seconds=60) is None
    assert select_robinhood_registry(failed_live, retained,
                                     as_of=T0 + timedelta(seconds=61),
                                     max_age_seconds=60) is None


@pytest.mark.parametrize("source", ["CoinGecko RWA", "DeFiLlama /chains", "LI.FI execution", "Robinhood reference"])
def test_market_aggregators_and_execution_are_not_token_reference_authority(source):
    result = build(token=token_ref(source=source))
    assert result.token.state is AuthorityState.UNAVAILABLE
    assert result.premium.value_bps is None


def test_token_reference_requires_explicit_source_approval():
    result = build_authority_snapshot(registry=registry(), key=KEY,
        underlying_reference=underlying(), token_reference=token_ref(),
        execution_quote=None, as_of=T0,
        policy=replace(POLICY, approved_token_reference_sources=frozenset()))
    assert result.token.state is AuthorityState.UNAVAILABLE
    assert result.premium.value_bps is None


def test_reference_staleness_preserved_and_premium_suppressed():
    result = build(token=token_ref(), at=T0 + timedelta(seconds=121))
    assert result.underlying.state is AuthorityState.STALE
    assert result.underlying.price_usd_per_token == Decimal("100")
    assert result.premium.state is AuthorityState.STALE
    assert result.premium.value_bps is None


def test_token_reference_staleness_preserves_observation():
    stale = token_ref(observed_at=T0 - timedelta(seconds=121))
    result = build(token=stale)
    assert result.token.state is AuthorityState.STALE
    assert result.token.price_usd_per_token == Decimal("105")
    assert result.premium.state is AuthorityState.STALE


def test_identity_mismatch_takes_precedence_over_stale_price():
    result = build(token=token_ref(registry_asset_uid=OTHER_UID),
                   at=T0 + timedelta(seconds=121))
    assert result.premium.state is AuthorityState.IDENTITY_UNAVAILABLE
    assert result.execution_gap.state is AuthorityState.IDENTITY_UNAVAILABLE


def test_provider_marked_stale_quote_keeps_time_and_reason():
    result = build(token=token_ref(), execution=quote(status=QuoteStatus.STALE_QUOTE))
    assert result.execution.state is AuthorityState.STALE
    assert result.execution.observed_at == T0
    assert result.execution_gap.state is AuthorityState.STALE


def test_stale_quote_preserved_but_not_live_execution_gap():
    result = build(token=token_ref(), execution=quote(), at=T0 + timedelta(seconds=61))
    assert result.execution.state is AuthorityState.STALE
    assert result.execution.effective_price_usd_per_token == Decimal("110")
    assert result.execution_gap.state is AuthorityState.STALE
    assert result.execution_gap.effective_gap_bps is None


def test_missing_route_suppresses_execution_without_suppressing_reference_premium():
    result = build(token=token_ref(), execution=quote(evidence=None))
    assert result.premium.value_bps == Decimal("500")
    assert result.execution.state is AuthorityState.UNAVAILABLE
    assert result.execution_gap.effective_gap_bps is None


def test_time_mismatch_blocks_premium_and_execution_gap():
    later = T0 + timedelta(seconds=61)
    result = build(token=token_ref(observed_at=later), at=later)
    assert result.premium.reason == "REFERENCE_TIME_MISMATCH"
    assert result.execution_gap.effective_gap_bps is None


def test_legacy_p2_output_and_r3_midpoint_economic_equivalence():
    reference = {"available": True, "price": "100", "rawBid": "99", "rawAsk": "101",
                 "currentMultiplier": "1", "observedAt": T0.isoformat(), "isTradingHalt": False}
    buy = {"available": True, "effectivePrice": "102", "quotedAt": T0.isoformat()}
    sell = {"available": True, "effectivePrice": "100", "quotedAt": T0.isoformat()}
    result = compute_tokenization_premium(reference_evidence=reference,
        buy_exec_evidence=buy, sell_exec_evidence=sell,
        policy=TokenizationPremiumPolicy(max_evidence_skew_seconds=60))
    assert result.execution_mid_price_usd_per_token == execution_midpoint_usd_per_token(Decimal("102"), Decimal("100"))
    assert result.tokenization_premium_bps == Decimal("100")
    assert result.buy_execution_premium_bps == Decimal("200")
    assert result.sell_execution_premium_bps == Decimal("0")
