"""Focused, fully offline R3 executable liquidity tests.

Deterministic fixtures only: no network access anywhere in this module.
Test numbering follows the R3 specification's mandatory coverage list.
"""
from __future__ import annotations

from dataclasses import replace
from datetime import datetime, timedelta, timezone
from decimal import Decimal

import pytest

from finco_radar.assets.contracts import (
    AssetKey,
    CanonicalAssetRecord,
    ReferenceBinding,
    RegistryAssetStatus,
)
from finco_radar.gap.contracts import (
    GapComparisonPolicy,
    ReferenceSide,
)
from finco_radar.gap.engine import build_bound_reference_price, compute_directional_gap
from finco_radar.liquidity import engine as liquidity_engine
from finco_radar.liquidity.contracts import (
    BUY_DELTA_INTERPRETATION,
    SELL_DELTA_INTERPRETATION,
    CostTreatmentState,
    LiquidityComparisonPolicy,
    LiquidityComputationError,
    LiquidityStatus,
    ProviderCostEvidence,
    RouteSignature,
)
from finco_radar.liquidity.engine import (
    build_liquidity_snapshot,
    build_route_signature,
    executable_spread_evidence,
    normalize_provider_cost,
)
from finco_radar.quotes.contracts import (
    AssetRef,
    ExecutionQuote,
    QuoteEvidence,
    QuoteSide,
    QuoteStatus,
    RouteLeg,
    SettlementReference,
    SettlementReferenceState,
)
from finco_radar.quotes.normalization import quote_size_impact_bps

UID = "0x" + "11" * 32
OTHER_UID = "0x" + "22" * 32
TOKEN = "0x" + "aa" * 20
OTHER_TOKEN = "0x" + "bb" * 20
SETTLEMENT = "0x" + "cc" * 20
OTHER_SETTLEMENT = "0x" + "dd" * 20
CHAIN = 4663
NOW = datetime(2026, 9, 15, 12, 0, tzinfo=timezone.utc)
GIT_HEAD = "r3-test-git-head"

# R2 comparisons inside these tests use a generous 300s window so that the R3
# quote-pair policy (120s) is the boundary under test.
R2_POLICY = GapComparisonPolicy(max_evidence_skew_seconds=300)
POLICY = LiquidityComparisonPolicy(max_quote_pair_skew_seconds=120)

SMALL = Decimal("100")
LARGE = Decimal("1000")


def asset() -> CanonicalAssetRecord:
    return CanonicalAssetRecord(
        asset_uid=UID,
        token_symbol="AAA",
        token_name="AAA Token",
        deployments=(AssetKey(CHAIN, TOKEN),),
        current_multiplier=Decimal("1"),
        pending_multiplier=None,
        pending_multiplier_effective_at=None,
        status=RegistryAssetStatus.ACTIVE,
    )


def binding() -> ReferenceBinding:
    return ReferenceBinding(asset_uid=UID, asset_key=AssetKey(CHAIN, TOKEN), reference_symbol="AAA")


def price_row() -> dict[str, object]:
    return {
        "tokenSymbol": "AAA",
        "deployments": [{"chainId": CHAIN, "contractAddress": TOKEN}],
        "bid": "95",
        "ask": "105",
        "currency": "USD",
        "generatedAt": "2026-09-15T12:00:00Z",
        "isTradingHalt": False,
    }


def reference():
    return build_bound_reference_price(asset(), binding(), price_row())


def _settlement(
    *,
    address: str = SETTLEMENT,
    chain_id: int = CHAIN,
    usd: Decimal = Decimal("1"),
    observed_at: datetime = NOW,
) -> SettlementReference:
    return SettlementReference(
        asset=AssetRef(chain_id, address, symbol="USDG", decimals=18),
        state=SettlementReferenceState.REFERENCE_CURRENT,
        usd_per_asset=usd,
        source="TEST_SETTLEMENT",
        observed_at=observed_at,
        raw_evidence={},
    )


def mk_quote(
    side: QuoteSide,
    notional: Decimal,
    *,
    token_amount: str | None,
    settlement_amount: str | None,
    quoted_at: datetime = NOW,
    status: QuoteStatus = QuoteStatus.QUOTE_OK,
    fee: str | None = None,
    gas: str | None = None,
    route: tuple[RouteLeg, ...] | None = None,
    with_evidence: bool = True,
    token_address: str = TOKEN,
    chain_id: int = CHAIN,
    settlement_address: str = SETTLEMENT,
    settlement_chain_id: int = CHAIN,
    source: str = "TEST_EXECUTION",
) -> ExecutionQuote:
    settlement_ref = _settlement(address=settlement_address, chain_id=settlement_chain_id)
    token_ref = AssetRef(chain_id, token_address, symbol="AAA", decimals=18)
    if side is QuoteSide.BUY:
        input_asset, output_asset = settlement_ref.asset, token_ref
        normalized_in = Decimal(settlement_amount) if settlement_amount is not None else None
        normalized_out = Decimal(token_amount) if token_amount is not None else None
    else:
        input_asset, output_asset = token_ref, settlement_ref.asset
        normalized_in = Decimal(token_amount) if token_amount is not None else None
        normalized_out = Decimal(settlement_amount) if settlement_amount is not None else None
    if with_evidence:
        legs = route if route is not None else (
            (
                RouteLeg(
                    tool="lifi",
                    from_asset=(
                        settlement_address if side is QuoteSide.BUY else token_address
                    ),
                    to_asset=(
                        token_address if side is QuoteSide.BUY else settlement_address
                    ),
                ),
            )
        )
        evidence = QuoteEvidence(request_params={}, response_fields={}, route=legs)
    else:
        evidence = None
    return ExecutionQuote(
        chain_id=chain_id,
        token_address=token_address,
        side=side,
        input_asset=input_asset,
        output_asset=output_asset,
        requested_notional_usd=notional,
        raw_amount_in=1,
        raw_amount_out=1,
        normalized_amount_in=normalized_in,
        normalized_amount_out=normalized_out,
        input_decimals=18,
        output_decimals=18,
        source=source,
        quoted_at=quoted_at,
        settlement_reference=settlement_ref,
        status=status,
        fee_cost_usd=Decimal(fee) if fee is not None else None,
        gas_cost_usd=Decimal(gas) if gas is not None else None,
        evidence=evidence,
    )


def std_quotes() -> list[ExecutionQuote]:
    """BUY $100/$1000 then SELL $100/$1000 with deterministic route economics."""
    return [
        mk_quote(QuoteSide.BUY, SMALL, token_amount="0.8", settlement_amount="100"),
        mk_quote(QuoteSide.BUY, LARGE, token_amount="7", settlement_amount="1000"),
        mk_quote(QuoteSide.SELL, SMALL, token_amount="0.8", settlement_amount="90"),
        mk_quote(QuoteSide.SELL, LARGE, token_amount="7", settlement_amount="880"),
    ]


def observations_for(quotes: list[ExecutionQuote]) -> list:
    return [compute_directional_gap(reference(), q, policy=R2_POLICY) for q in quotes]


STANDARD_OBSERVATIONS = observations_for(std_quotes())


def build(quotes: list[ExecutionQuote] | None = None, observations: list | None = None, **overrides):
    resolved = std_quotes() if quotes is None else quotes
    if observations is None:
        observations = observations_for(resolved)
    overrides.setdefault("produced_at", NOW)
    return build_liquidity_snapshot(
        asset=asset(),
        asset_key=AssetKey(CHAIN, TOKEN),
        quotes=resolved,
        gap_observations=observations,
        policy=POLICY,
        git_head=GIT_HEAD,
        **overrides,
    )


def expect_failure(
    quotes: list[ExecutionQuote] | None,
    observations: list | None,
    expected: LiquidityStatus,
) -> LiquidityComputationError:
    with pytest.raises(LiquidityComputationError) as excinfo:
        build(quotes=quotes, observations=observations)
    assert excinfo.value.status is expected
    return excinfo.value


def shifted(quotes: list[ExecutionQuote], index: int, seconds: int) -> list[ExecutionQuote]:
    moved = quotes[index].quoted_at + timedelta(seconds=seconds)
    moved_quote = replace(quotes[index], quoted_at=moved)
    return [*quotes[:index], moved_quote, *quotes[index + 1 :]]


def _walk_keys(value: object):
    if isinstance(value, dict):
        for key, item in value.items():
            yield key
            yield from _walk_keys(item)
    elif isinstance(value, list):
        for item in value:
            yield from _walk_keys(item)


def _walk_keys_excluding(value: object, skip: set[str]):
    if isinstance(value, dict):
        for key, item in value.items():
            yield key
            if key not in skip:
                yield from _walk_keys_excluding(item, skip)
    elif isinstance(value, list):
        for item in value:
            yield from _walk_keys_excluding(item, skip)


def _walk_values(value: object):
    if isinstance(value, dict):
        for item in value.values():
            yield from _walk_values(item)
    elif isinstance(value, list):
        for item in value:
            yield from _walk_values(item)
    else:
        yield value


# ---------------------------------------------------------------------------
# 1. Canonical identity
# ---------------------------------------------------------------------------

def test_01_exact_r1_canonical_identity_preserved() -> None:
    snap = build()
    assert snap.asset_uid == UID
    assert snap.canonical_key == AssetKey(CHAIN, TOKEN)
    assert snap.canonical_key.chain_id == CHAIN
    assert snap.canonical_key.contract_address == TOKEN
    assert snap.symbol == "AAA"


def test_02_ticker_cannot_substitute_for_address() -> None:
    quotes = std_quotes()
    same_ticker_wrong_address = replace(quotes[0], token_address=OTHER_TOKEN)
    broken = [same_ticker_wrong_address, *quotes[1:]]
    expect_failure(broken, STANDARD_OBSERVATIONS, LiquidityStatus.IDENTITY_MISMATCH)


# ---------------------------------------------------------------------------
# 3-6. Observation matrix
# ---------------------------------------------------------------------------

def test_03_exact_four_observation_matrix_required() -> None:
    snap = build()
    payload = snap.to_evidence_dict()
    assert len(payload["quoteMatrixEvidence"]) == 4
    assert len(snap.cost_evidence) == 4
    slots = {entry["slot"] for entry in payload["quoteMatrixEvidence"]}
    assert slots == {"BUY_100", "BUY_1000", "SELL_100", "SELL_1000"}
    assert payload["observationNotionals"] == {
        "smallNotionalUsd": "100",
        "largeNotionalUsd": "1000",
    }


def test_04_duplicate_matrix_row_rejected() -> None:
    quotes = std_quotes() + [
        mk_quote(QuoteSide.BUY, SMALL, token_amount="0.9", settlement_amount="100")
    ]
    expect_failure(quotes, STANDARD_OBSERVATIONS, LiquidityStatus.QUOTE_MATRIX_INCOMPLETE)


def test_05_missing_matrix_row_rejected() -> None:
    quotes = std_quotes()[:3]
    expect_failure(quotes, STANDARD_OBSERVATIONS[:3], LiquidityStatus.QUOTE_MATRIX_INCOMPLETE)


def test_06_non_quote_ok_quote_rejected() -> None:
    quotes = std_quotes()
    unavailable = replace(quotes[0], status=QuoteStatus.QUOTE_UNAVAILABLE)
    broken = [unavailable, *quotes[1:]]
    failure = expect_failure(
        broken, STANDARD_OBSERVATIONS, LiquidityStatus.QUOTE_UNAVAILABLE
    )
    assert "QUOTE_UNAVAILABLE" in str(failure)


def test_06b_insufficient_liquidity_status_maps_typed() -> None:
    quotes = std_quotes()
    thin = replace(quotes[0], status=QuoteStatus.INSUFFICIENT_LIQUIDITY)
    broken = [thin, *quotes[1:]]
    expect_failure(broken, STANDARD_OBSERVATIONS, LiquidityStatus.INSUFFICIENT_LIQUIDITY)


# ---------------------------------------------------------------------------
# 7-11. R0 size impact authority
# ---------------------------------------------------------------------------

def test_07_r0_buy_size_impact_uses_canonical_helper(monkeypatch: pytest.MonkeyPatch) -> None:
    calls: list[tuple[ExecutionQuote, ExecutionQuote]] = []

    def spy(small: ExecutionQuote, large: ExecutionQuote) -> Decimal:
        calls.append((small, large))
        return Decimal("777")

    monkeypatch.setattr(liquidity_engine, "quote_size_impact_bps", spy)
    snap = build()
    assert snap.buy.r0_size_impact_bps == Decimal("777")
    assert len(calls) == 2
    assert calls[0][0] is snap.buy.small_quote
    assert calls[0][1] is snap.buy.large_quote


def test_08_r0_sell_size_impact_uses_canonical_helper(monkeypatch: pytest.MonkeyPatch) -> None:
    calls: list[tuple[ExecutionQuote, ExecutionQuote]] = []

    def spy(small: ExecutionQuote, large: ExecutionQuote) -> Decimal:
        calls.append((small, large))
        return Decimal("888")

    monkeypatch.setattr(liquidity_engine, "quote_size_impact_bps", spy)
    snap = build()
    assert snap.sell.r0_size_impact_bps == Decimal("888")
    assert len(calls) == 2
    assert calls[1][0] is snap.sell.small_quote
    assert calls[1][1] is snap.sell.large_quote


def test_09_buy_size_impact_formula() -> None:
    quotes = std_quotes()
    snap = build(quotes)
    # small rate 0.8/100 = 0.008; large rate 7/1000 = 0.007; exact 1250 bps.
    assert snap.buy.r0_size_impact_bps == Decimal("1250")
    assert snap.buy.r0_size_impact_bps == quote_size_impact_bps(quotes[0], quotes[1])


def test_10_sell_size_impact_formula() -> None:
    quotes = std_quotes()
    snap = build(quotes)
    assert snap.sell.r0_size_impact_bps == quote_size_impact_bps(quotes[2], quotes[3])
    # Larger SELL receives a better settlement-per-token rate: negative impact.
    assert snap.sell.r0_size_impact_bps < 0


def test_11_r0_size_metric_not_recomputed_from_r2_gap() -> None:
    snap = build()
    # The R2 directional GAP delta and the R0 size impact are different metrics
    # and must be allowed to differ numerically for the same evidence.
    assert snap.buy.directional_gap_delta_bps != snap.buy.r0_size_impact_bps
    assert snap.sell.directional_gap_delta_bps != snap.sell.r0_size_impact_bps
    payload = snap.to_evidence_dict()
    assert payload["sizeImpactEvidence"]["authority"].endswith("quote_size_impact_bps")


# ---------------------------------------------------------------------------
# 12-14. R2 directional GAP delta
# ---------------------------------------------------------------------------

def test_12_buy_r2_gap_delta_formula() -> None:
    snap = build()
    expected = (
        snap.buy.large_gap_observation.gap_bps - snap.buy.small_gap_observation.gap_bps
    )
    assert snap.buy.directional_gap_delta_bps == expected


def test_13_sell_r2_gap_delta_formula() -> None:
    snap = build()
    expected = (
        snap.sell.large_gap_observation.gap_bps - snap.sell.small_gap_observation.gap_bps
    )
    assert snap.sell.directional_gap_delta_bps == expected


def test_14_side_specific_interpretation_preserved() -> None:
    payload = build().to_evidence_dict()
    buy_interp = payload["gapEvidence"]["buyDeltaInterpretation"]
    sell_interp = payload["gapEvidence"]["sellDeltaInterpretation"]
    assert buy_interp == BUY_DELTA_INTERPRETATION
    assert sell_interp == SELL_DELTA_INTERPRETATION
    assert buy_interp.startswith("positive = larger BUY is worse")
    assert sell_interp.startswith("positive = larger SELL is better")
    assert buy_interp != sell_interp


# ---------------------------------------------------------------------------
# 15-19. Executable spread
# ---------------------------------------------------------------------------

def test_15_spread_at_100_formula() -> None:
    snap = build()
    p_buy = Decimal("100") * Decimal("1") / Decimal("0.8")
    p_sell = Decimal("90") * Decimal("1") / Decimal("0.8")
    p_mid = (p_buy + p_sell) / Decimal("2")
    expected = ((p_buy - p_sell) / p_mid) * Decimal("10000")
    spread = snap.spread_small
    assert spread.buy_execution_price_usd_per_token == p_buy == Decimal("125")
    assert spread.sell_execution_price_usd_per_token == p_sell == Decimal("112.5")
    assert spread.execution_mid_price_usd_per_token == p_mid
    assert spread.execution_spread_bps == expected


def test_16_spread_at_1000_formula() -> None:
    snap = build()
    p_buy = Decimal("1000") * Decimal("1") / Decimal("7")
    p_sell = Decimal("880") * Decimal("1") / Decimal("7")
    p_mid = (p_buy + p_sell) / Decimal("2")
    expected = ((p_buy - p_sell) / p_mid) * Decimal("10000")
    spread = snap.spread_large
    assert spread.buy_execution_price_usd_per_token == p_buy
    assert spread.sell_execution_price_usd_per_token == p_sell
    assert spread.execution_spread_bps == expected


def test_17_spread_delta_formula() -> None:
    snap = build()
    expected = snap.spread_large.execution_spread_bps - snap.spread_small.execution_spread_bps
    assert snap.spread_delta_bps == expected


def test_18_no_spread_if_one_side_missing() -> None:
    quotes = std_quotes()
    unavailable_sell = mk_quote(
        QuoteSide.SELL,
        SMALL,
        token_amount="0.8",
        settlement_amount="90",
        status=QuoteStatus.ROUTE_UNAVAILABLE,
    )
    assert executable_spread_evidence(None, quotes[2]) is None
    assert executable_spread_evidence(quotes[0], None) is None
    assert executable_spread_evidence(quotes[0], unavailable_sell) is None


def test_19_no_spread_if_economics_non_finite() -> None:
    quotes = std_quotes()
    broken_buy = mk_quote(QuoteSide.BUY, SMALL, token_amount=None, settlement_amount="100")
    with pytest.raises(LiquidityComputationError) as excinfo:
        executable_spread_evidence(broken_buy, quotes[2])
    assert excinfo.value.status is LiquidityStatus.NON_FINITE_ECONOMICS


# ---------------------------------------------------------------------------
# 20-23. Route stability
# ---------------------------------------------------------------------------

def _leg(tool: str, *, raw_in: str | None = None, raw_out: str | None = None) -> RouteLeg:
    return RouteLeg(
        tool=tool,
        from_asset=SETTLEMENT,
        to_asset=TOKEN,
        from_amount_raw=raw_in,
        to_amount_raw=raw_out,
    )


def test_20_deterministic_route_signature() -> None:
    routed = mk_quote(
        QuoteSide.BUY, SMALL, token_amount="0.8", settlement_amount="100",
        route=(_leg("lifi"),),
    )
    first = build_route_signature(routed)
    second = build_route_signature(routed)
    assert first == second
    assert first.canonical_form() == second.canonical_form()
    assert first.canonical_form() == f"lifi:{SETTLEMENT}>{TOKEN}"
    assert RouteSignature(legs=()).canonical_form() == "NO_ROUTE_EVIDENCE"


def test_21_unchanged_route_detected() -> None:
    same_route = (_leg("lifi"),)
    quotes = [
        mk_quote(QuoteSide.BUY, SMALL, token_amount="0.8", settlement_amount="100", route=same_route),
        mk_quote(QuoteSide.BUY, LARGE, token_amount="7", settlement_amount="1000", route=same_route),
        std_quotes()[2],
        std_quotes()[3],
    ]
    snap = build(quotes)
    assert snap.buy.route_changed is False
    assert (
        snap.buy.small_route_signature.canonical_form()
        == snap.buy.large_route_signature.canonical_form()
    )
    assert snap.to_evidence_dict()["routeEvidence"]["buy"]["buyRouteChanged"] is False


def test_22_changed_route_detected() -> None:
    quotes = [
        mk_quote(
            QuoteSide.BUY, SMALL, token_amount="0.8", settlement_amount="100",
            route=(_leg("lifi"),),
        ),
        mk_quote(
            QuoteSide.BUY, LARGE, token_amount="7", settlement_amount="1000",
            route=(_leg("uniswap_v3"),),
        ),
        std_quotes()[2],
        std_quotes()[3],
    ]
    snap = build(quotes)
    assert snap.buy.route_changed is True
    assert snap.to_evidence_dict()["routeEvidence"]["buy"]["buyRouteChanged"] is True


def test_23_route_change_does_not_alter_score_because_no_score_exists() -> None:
    plain = std_quotes()
    changed = [
        mk_quote(
            QuoteSide.BUY, SMALL, token_amount="0.8", settlement_amount="100",
            route=(_leg("lifi"),),
        ),
        mk_quote(
            QuoteSide.BUY, LARGE, token_amount="7", settlement_amount="1000",
            route=(_leg("uniswap_v3"),),
        ),
        plain[2],
        plain[3],
    ]
    snap_plain = build(plain)
    snap_changed = build(changed)
    # Identical economics: route change is evidence only, it moves no metric.
    assert snap_plain.spread_small == snap_changed.spread_small
    assert snap_plain.spread_large == snap_changed.spread_large
    assert snap_plain.spread_delta_bps == snap_changed.spread_delta_bps
    assert snap_plain.buy.r0_size_impact_bps == snap_changed.buy.r0_size_impact_bps
    for payload in (snap_plain.to_evidence_dict(), snap_changed.to_evidence_dict()):
        forbidden = ("score", "rank", "rating", "grade", "verdict", "opportunit")
        assert not any(word in key.lower() for key in _walk_keys(payload) for word in forbidden)


def test_23b_route_raw_amounts_never_determine_identity() -> None:
    first = build_route_signature(
        mk_quote(QuoteSide.BUY, SMALL, token_amount="0.8", settlement_amount="100",
                 route=(_leg("lifi", raw_in="100000000", raw_out="800000000"),))
    )
    second = build_route_signature(
        mk_quote(QuoteSide.BUY, SMALL, token_amount="0.8", settlement_amount="100",
                 route=(_leg("lifi", raw_in="999", raw_out="7"),))
    )
    assert first == second
    assert first.canonical_form() == second.canonical_form()


# ---------------------------------------------------------------------------
# 24-29. Provider cost evidence
# ---------------------------------------------------------------------------

def _cost_evidence_for(quotes: list[ExecutionQuote], index: int) -> ProviderCostEvidence:
    return build(quotes).cost_evidence[index]


def test_24_fee_usd_normalization() -> None:
    quotes = std_quotes()
    quotes[0] = replace(quotes[0], fee_cost_usd=Decimal("1"))
    evidence = _cost_evidence_for(quotes, 0)
    assert evidence.fee_bps_of_notional == Decimal("100")  # 1 USD on 100 USD
    payload = build(quotes).to_evidence_dict()
    assert Decimal(payload["costEvidence"][0]["feeBpsOfNotional"]) == Decimal("100")


def test_25_gas_usd_normalization() -> None:
    quotes = std_quotes()
    quotes[0] = replace(quotes[0], gas_cost_usd=Decimal("0.5"))
    evidence = _cost_evidence_for(quotes, 0)
    assert evidence.gas_bps_of_notional == Decimal("50")  # 0.5 USD on 100 USD


def test_26_combined_reported_cost_bps_normalization() -> None:
    quotes = std_quotes()
    quotes[0] = replace(quotes[0], fee_cost_usd=Decimal("1"), gas_cost_usd=Decimal("0.5"))
    evidence = _cost_evidence_for(quotes, 0)
    assert evidence.reported_cost_bps == Decimal("150")  # (1 + 0.5) on 100 USD
    payload = build(quotes).to_evidence_dict()
    assert Decimal(payload["costEvidence"][0]["reportedCostBps"]) == Decimal("150")


def test_27_missing_provider_costs_remain_explicit_none() -> None:
    snap = build()
    evidence = snap.cost_evidence[0]
    assert evidence.fee_cost_usd is None
    assert evidence.gas_cost_usd is None
    assert evidence.fee_bps_of_notional is None
    assert evidence.gas_bps_of_notional is None
    assert evidence.reported_cost_bps is None
    entry = snap.to_evidence_dict()["costEvidence"][0]
    assert entry["feeCostUsd"] is None
    assert entry["gasCostUsd"] is None
    assert entry["reportedCostBps"] is None


def test_28_cost_treatment_state_defaults_fail_safe() -> None:
    quotes = std_quotes()
    quotes[0] = replace(quotes[0], fee_cost_usd=Decimal("1"), gas_cost_usd=Decimal("0.5"))
    snap = build(quotes)
    for evidence in snap.cost_evidence:
        assert evidence.cost_treatment_state is CostTreatmentState.EVIDENCE_ONLY_INCLUSION_UNRESOLVED
    payload = snap.to_evidence_dict()
    assert all(
        entry["costTreatmentState"] == "EVIDENCE_ONLY_INCLUSION_UNRESOLVED"
        for entry in payload["costEvidence"]
    )


def test_29_unresolved_costs_are_not_added_to_execution_price() -> None:
    plain = std_quotes()
    priced = [
        replace(q, fee_cost_usd=Decimal("3"), gas_cost_usd=Decimal("2")) for q in std_quotes()
    ]
    snap_plain = build(plain)
    snap_priced = build(priced)
    # Execution prices and spreads are derived from route amounts only; the
    # presence of unresolved provider costs must not move them.
    assert snap_plain.spread_small == snap_priced.spread_small
    assert snap_plain.spread_large == snap_priced.spread_large
    assert snap_plain.spread_delta_bps == snap_priced.spread_delta_bps
    assert snap_plain.buy.r0_size_impact_bps == snap_priced.buy.r0_size_impact_bps


def test_29b_invalid_cost_evidence_fails_typed() -> None:
    with pytest.raises(LiquidityComputationError) as negative:
        ProviderCostEvidence(
            requested_notional_usd=SMALL, fee_cost_usd=Decimal("-1"), gas_cost_usd=None
        )
    assert negative.value.status is LiquidityStatus.COST_EVIDENCE_INVALID
    with pytest.raises(LiquidityComputationError) as non_finite:
        ProviderCostEvidence(
            requested_notional_usd=SMALL, fee_cost_usd=Decimal("NaN"), gas_cost_usd=None
        )
    assert non_finite.value.status is LiquidityStatus.COST_EVIDENCE_INVALID


def test_29c_reported_cost_requires_both_amounts() -> None:
    partial = normalize_provider_cost(replace(std_quotes()[0], fee_cost_usd=Decimal("1")))
    assert partial.fee_bps_of_notional == Decimal("100")
    assert partial.reported_cost_bps is None  # missing gas is never treated as zero


# ---------------------------------------------------------------------------
# 30-36. Temporal coherence
# ---------------------------------------------------------------------------

def test_30_buy_size_pair_skew_inside_boundary() -> None:
    quotes = shifted(std_quotes(), 0, 60)
    snap = build(quotes)
    skews = dict(snap.temporal.quote_pair_skews)
    assert skews["BUY_SIZE_PAIR"] == Decimal("60")
    assert snap.temporal.max_observed_pair_skew_seconds == Decimal("60")


def test_31_sell_size_pair_skew_inside_boundary() -> None:
    quotes = shifted(std_quotes(), 3, 30)
    snap = build(quotes)
    skews = dict(snap.temporal.quote_pair_skews)
    assert skews["SELL_SIZE_PAIR"] == Decimal("30")


def test_32_cross_side_100_skew_inside_boundary() -> None:
    quotes = shifted(std_quotes(), 2, 45)
    snap = build(quotes)
    skews = dict(snap.temporal.quote_pair_skews)
    assert skews["CROSS_SIDE_100"] == Decimal("45")


def test_33_cross_side_1000_skew_inside_boundary() -> None:
    quotes = shifted(std_quotes(), 3, 90)
    snap = build(quotes)
    skews = dict(snap.temporal.quote_pair_skews)
    assert skews["CROSS_SIDE_1000"] == Decimal("90")


def test_34_exact_temporal_boundary_passes() -> None:
    quotes = shifted(std_quotes(), 0, 120)
    snap = build(quotes)
    skews = dict(snap.temporal.quote_pair_skews)
    assert skews["BUY_SIZE_PAIR"] == Decimal("120")
    assert snap.temporal.policy.max_quote_pair_skew_seconds == 120


def test_35_over_boundary_fails_time_mismatch() -> None:
    quotes = shifted(std_quotes(), 0, 121)
    expect_failure(quotes, None, LiquidityStatus.EVIDENCE_TIME_MISMATCH)


def test_36_timezone_naive_timestamp_rejected() -> None:
    # Timezone-naive evidence timestamps are rejected fail-closed: the lineage
    # clock of the snapshot (produced_at) must be timezone-aware.
    with pytest.raises(LiquidityComputationError) as excinfo:
        build(produced_at=NOW.replace(tzinfo=None))
    assert excinfo.value.status is LiquidityStatus.EVIDENCE_TIME_MISMATCH


def test_36b_policy_is_mandatory_without_default() -> None:
    with pytest.raises(TypeError):
        LiquidityComparisonPolicy()  # type: ignore[call-arg]
    with pytest.raises(ValueError):
        LiquidityComparisonPolicy(max_quote_pair_skew_seconds=0)
    with pytest.raises(ValueError):
        LiquidityComparisonPolicy(max_quote_pair_skew_seconds=-5)


# ---------------------------------------------------------------------------
# 37-43. Identity and lineage validation
# ---------------------------------------------------------------------------

def test_37_token_chain_mismatch_fails() -> None:
    quotes = std_quotes()
    wrong_chain = mk_quote(
        QuoteSide.BUY, SMALL, token_amount="0.8", settlement_amount="100", chain_id=1
    )
    broken = [wrong_chain, *quotes[1:]]
    expect_failure(broken, STANDARD_OBSERVATIONS, LiquidityStatus.IDENTITY_MISMATCH)


def test_38_token_address_mismatch_fails() -> None:
    quotes = std_quotes()
    wrong_address = mk_quote(
        QuoteSide.BUY, SMALL, token_amount="0.8", settlement_amount="100",
        token_address=OTHER_TOKEN,
    )
    broken = [wrong_address, *quotes[1:]]
    expect_failure(broken, STANDARD_OBSERVATIONS, LiquidityStatus.IDENTITY_MISMATCH)


def test_39_settlement_chain_mismatch_fails() -> None:
    quotes = std_quotes()
    wrong_settlement = mk_quote(
        QuoteSide.BUY, SMALL, token_amount="0.8", settlement_amount="100",
        settlement_chain_id=1,
    )
    broken = [wrong_settlement, *quotes[1:]]
    expect_failure(broken, STANDARD_OBSERVATIONS, LiquidityStatus.IDENTITY_MISMATCH)


def test_40_settlement_address_mismatch_fails() -> None:
    quotes = std_quotes()
    wrong_settlement = mk_quote(
        QuoteSide.BUY, SMALL, token_amount="0.8", settlement_amount="100",
        settlement_address=OTHER_SETTLEMENT,
    )
    broken = [wrong_settlement, *quotes[1:]]
    expect_failure(broken, STANDARD_OBSERVATIONS, LiquidityStatus.IDENTITY_MISMATCH)


def test_41_r2_observation_asset_mismatch_fails() -> None:
    tampered = replace(STANDARD_OBSERVATIONS[0], asset_uid=OTHER_UID)
    observations = [tampered, *STANDARD_OBSERVATIONS[1:]]
    expect_failure(None, observations, LiquidityStatus.R2_LINEAGE_MISMATCH)


def test_42_r2_side_mismatch_fails() -> None:
    # A SELL-labelled observation cannot occupy the BUY $100 slot: the matrix
    # detects the duplicate SELL row and fails closed as lineage mismatch.
    tampered = replace(
        STANDARD_OBSERVATIONS[0],
        side=QuoteSide.SELL,
        reference_side=ReferenceSide.BID,
        reference_price_usd_per_token=Decimal("95"),
    )
    observations = [tampered, *STANDARD_OBSERVATIONS[1:]]
    expect_failure(None, observations, LiquidityStatus.R2_LINEAGE_MISMATCH)


def test_43_r2_notional_mismatch_fails() -> None:
    tampered = replace(STANDARD_OBSERVATIONS[0], requested_notional_usd=Decimal("500"))
    observations = [tampered, *STANDARD_OBSERVATIONS[1:]]
    expect_failure(None, observations, LiquidityStatus.R2_LINEAGE_MISMATCH)


def test_43b_r2_quoted_at_lineage_mismatch_fails() -> None:
    tampered = replace(STANDARD_OBSERVATIONS[0], quoted_at=NOW + timedelta(seconds=5))
    observations = [tampered, *STANDARD_OBSERVATIONS[1:]]
    expect_failure(None, observations, LiquidityStatus.R2_LINEAGE_MISMATCH)


def test_43c_r2_execution_price_lineage_mismatch_fails() -> None:
    tampered = replace(
        STANDARD_OBSERVATIONS[0], execution_price_usd_per_token=Decimal("123.456")
    )
    observations = [tampered, *STANDARD_OBSERVATIONS[1:]]
    expect_failure(None, observations, LiquidityStatus.R2_LINEAGE_MISMATCH)


# ---------------------------------------------------------------------------
# 44-45. Fail-closed economics and typed statuses
# ---------------------------------------------------------------------------

def test_44_non_finite_economics_fail_closed() -> None:
    quotes = std_quotes()
    broken = [mk_quote(QuoteSide.BUY, SMALL, token_amount=None, settlement_amount="100"),
              *quotes[1:]]
    expect_failure(broken, STANDARD_OBSERVATIONS, LiquidityStatus.NON_FINITE_ECONOMICS)


def test_45_typed_failure_status_preserved() -> None:
    cases = [
        (std_quotes()[:3], STANDARD_OBSERVATIONS[:3], LiquidityStatus.QUOTE_MATRIX_INCOMPLETE),
        (
            [replace(std_quotes()[0], token_address=OTHER_TOKEN), *std_quotes()[1:]],
            STANDARD_OBSERVATIONS,
            LiquidityStatus.IDENTITY_MISMATCH,
        ),
        (shifted(std_quotes(), 0, 121), None, LiquidityStatus.EVIDENCE_TIME_MISMATCH),
    ]
    for quotes, observations, expected in cases:
        failure = expect_failure(quotes, observations, expected)
        assert isinstance(failure.status.value, str)
        assert failure.status is expected


# ---------------------------------------------------------------------------
# 46-49. Serialization structure and boundary declarations
# ---------------------------------------------------------------------------

def test_46_git_evidence_serialization_structure() -> None:
    snap = build()
    payload = snap.to_evidence_dict()
    assert payload["lineage"]["gitHead"] == GIT_HEAD
    parsed = datetime.fromisoformat(payload["lineage"]["producedAt"])
    assert parsed.tzinfo is not None and parsed == NOW
    assert payload["lineage"]["quoteSource"] == "TEST_EXECUTION"
    for entry in payload["quoteMatrixEvidence"]:
        assert "routeLegs" in entry
        assert entry["settlementEvidence"]["contractAddress"] == SETTLEMENT
        assert entry["settlementEvidence"]["usdPerAsset"] == "1"
    assert payload["temporalEvidence"]["policy"]["maxQuotePairSkewSeconds"] == 120
    assert set(payload["temporalEvidence"]["quoteTimestamps"]) == {
        "BUY_100", "BUY_1000", "SELL_100", "SELL_1000"
    }
    assert len(payload["temporalEvidence"]["observedPairSkews"]) == 4


def test_47_no_liquidity_ranking_field() -> None:
    payload = build().to_evidence_dict()
    forbidden = ("score", "rank", "rating", "grade", "verdict", "opportunit")
    assert not any(
        word in key.lower() for key in _walk_keys(payload) for word in forbidden
    )


def test_48_no_trading_signal_field() -> None:
    payload = build().to_evidence_dict()
    forbidden = ("signal", "recommend", "opportunit", "trade_signal")
    assert not any(
        word in key.lower()
        for key in _walk_keys_excluding(payload, skip={"boundaries"})
        for word in forbidden
    )
    for value in _walk_values(payload):
        assert value not in {"HIGH LIQUIDITY", "LOW LIQUIDITY", "GOOD", "BAD", "ARBITRAGE"}


def test_49_r4_not_yet_applied_preserved() -> None:
    snap = build()
    payload = snap.to_evidence_dict()
    assert payload["boundaries"]["referenceStateAuthority"] == "R4_NOT_YET_APPLIED"
    assert payload["boundaries"]["signalAuthority"] == "R5_NOT_YET_APPLIED"
    assert payload["boundaries"]["terminalAuthority"] == "R6_NOT_YET_APPLIED"
    assert snap.lineage.reference_state_authority == "R4_NOT_YET_APPLIED"
    assert snap.lineage.signal_authority == "R5_NOT_YET_APPLIED"
    assert snap.lineage.terminal_authority == "R6_NOT_YET_APPLIED"


# ---------------------------------------------------------------------------
# 50. R0/R1/R2 source behavior unchanged (regression canaries)
# ---------------------------------------------------------------------------

def test_50_r0_r1_r2_source_behavior_unchanged() -> None:
    quotes = std_quotes()
    # R0: canonical size-impact formula unchanged.
    assert quote_size_impact_bps(quotes[0], quotes[1]) == Decimal("1250")
    # R2: directional GAP formula and side binding unchanged.
    obs = STANDARD_OBSERVATIONS[0]
    expected_gap = ((Decimal("125") / Decimal("105")) - Decimal("1")) * Decimal("10000")
    assert obs.reference_side is ReferenceSide.ASK
    assert obs.gap_bps == expected_gap
    # R1: canonical identity normalization unchanged; ticker never part of the key.
    mixed_case = "0x" + TOKEN[2:].upper()
    assert AssetKey(CHAIN, mixed_case).canonical_id == f"{CHAIN}:{TOKEN}"


# ---------------------------------------------------------------------------
# Additional determinism coverage
# ---------------------------------------------------------------------------

def test_51_snapshot_build_is_deterministic() -> None:
    assert build().to_evidence_dict() == build().to_evidence_dict()


def test_52_cost_evidence_order_matches_required_matrix() -> None:
    payload = build().to_evidence_dict()
    order = [(entry["side"], entry["requestedNotionalUsd"]) for entry in payload["costEvidence"]]
    assert order == [("BUY", "100"), ("BUY", "1000"), ("SELL", "100"), ("SELL", "1000")]


def test_53_spread_semantics_language_present() -> None:
    payload = build().to_evidence_dict()
    assert "not realized slippage" in payload["spreadEvidence"]["semantics"]
    assert "not an order-book bid/ask spread" in payload["spreadEvidence"]["semantics"]
    assert "evidence only" in payload["routeEvidence"]["semantics"]
    assert "never be added" in payload["costSemantics"] or "never added" in payload["costSemantics"]


# ---------------------------------------------------------------------------
# Correction A1 — route evidence is mandatory (missing evidence is UNKNOWN)
# ---------------------------------------------------------------------------

def test_a1_01_missing_quote_evidence_rejected() -> None:
    quotes = std_quotes()
    blind = mk_quote(
        QuoteSide.BUY, SMALL, token_amount="0.8", settlement_amount="100",
        with_evidence=False,
    )
    broken = [blind, *quotes[1:]]
    failure = expect_failure(broken, None, LiquidityStatus.ROUTE_EVIDENCE_UNAVAILABLE)
    assert "UNKNOWN" in str(failure)


def test_a1_02_empty_route_rejected() -> None:
    quotes = std_quotes()
    empty = mk_quote(
        QuoteSide.BUY, SMALL, token_amount="0.8", settlement_amount="100", route=(),
    )
    broken = [empty, *quotes[1:]]
    expect_failure(broken, None, LiquidityStatus.ROUTE_EVIDENCE_UNAVAILABLE)


def test_a1_03_missing_route_cannot_serialize_route_changed_false() -> None:
    # A missing-route build produces no snapshot at all, so no artifact can
    # ever serialize routeChanged=false derived from missing evidence.
    blind_quotes = [
        mk_quote(QuoteSide.BUY, SMALL, token_amount="0.8", settlement_amount="100",
                 with_evidence=False),
        mk_quote(QuoteSide.BUY, LARGE, token_amount="7", settlement_amount="1000",
                 with_evidence=False),
        mk_quote(QuoteSide.SELL, SMALL, token_amount="0.8", settlement_amount="90",
                 with_evidence=False),
        mk_quote(QuoteSide.SELL, LARGE, token_amount="7", settlement_amount="880",
                 with_evidence=False),
    ]
    for index, blind in enumerate(blind_quotes):
        matrix = list(std_quotes())
        matrix[index] = blind
        with pytest.raises(LiquidityComputationError) as excinfo:
            build(matrix)
        assert excinfo.value.status is LiquidityStatus.ROUTE_EVIDENCE_UNAVAILABLE


def test_a1_04_leg_without_identity_information_rejected() -> None:
    quotes = std_quotes()
    anonymous = mk_quote(
        QuoteSide.BUY, SMALL, token_amount="0.8", settlement_amount="100",
        route=(RouteLeg(tool="  ", from_asset=SETTLEMENT, to_asset=TOKEN),),
    )
    broken = [anonymous, *quotes[1:]]
    expect_failure(broken, None, LiquidityStatus.ROUTE_EVIDENCE_UNAVAILABLE)


def test_a1_05_successful_snapshot_never_serializes_no_route_evidence() -> None:
    payload = build().to_evidence_dict()
    for side in ("buy", "sell"):
        block = payload["routeEvidence"][side]
        for field in ("smallRouteSignature", "largeRouteSignature"):
            signature = block[field]
            assert isinstance(signature, str) and signature
            assert signature != "NO_ROUTE_EVIDENCE"
        assert isinstance(block[f"{side}RouteChanged"], bool)


# ---------------------------------------------------------------------------
# Correction A2 — canonical route identity
# ---------------------------------------------------------------------------

def test_a2_01_mixed_case_evm_addresses_normalize_to_same_signature() -> None:
    quotes = std_quotes()
    checksummed = mk_quote(
        QuoteSide.BUY, SMALL, token_amount="0.8", settlement_amount="100",
        route=(
            RouteLeg(
                tool="lifi",
                from_asset="0x" + SETTLEMENT[2:].upper(),
                to_asset="0x" + TOKEN[2:].upper(),
            ),
        ),
    )
    broken = [checksummed, *quotes[1:]]
    snap = build(broken)
    assert snap.buy.route_changed is False
    expected = f"lifi:{SETTLEMENT}>{TOKEN}"
    assert snap.buy.small_route_signature.canonical_form() == expected
    assert snap.buy.large_route_signature.canonical_form() == expected


def test_a2_02_whitespace_evm_addresses_normalize_correctly() -> None:
    quotes = std_quotes()
    padded = mk_quote(
        QuoteSide.BUY, SMALL, token_amount="0.8", settlement_amount="100",
        route=(
            RouteLeg(tool="lifi", from_asset=f"  {SETTLEMENT} ", to_asset=f"\t{TOKEN}\n"),
        ),
    )
    broken = [padded, *quotes[1:]]
    snap = build(broken)
    assert snap.buy.route_changed is False
    assert snap.buy.small_route_signature.canonical_form() == f"lifi:{SETTLEMENT}>{TOKEN}"


def test_a2_03_tool_case_and_whitespace_normalize_to_same_signature() -> None:
    quotes = std_quotes()
    fancy_tool = mk_quote(
        QuoteSide.BUY, SMALL, token_amount="0.8", settlement_amount="100",
        route=(RouteLeg(tool="  LiFi  ", from_asset=SETTLEMENT, to_asset=TOKEN),),
    )
    broken = [fancy_tool, *quotes[1:]]
    snap = build(broken)
    assert snap.buy.route_changed is False
    assert snap.buy.small_route_signature.canonical_form() == f"lifi:{SETTLEMENT}>{TOKEN}"


def test_a2_04_actually_different_address_changes_route() -> None:
    quotes = std_quotes()
    different = mk_quote(
        QuoteSide.BUY, LARGE, token_amount="7", settlement_amount="1000",
        route=(RouteLeg(tool="lifi", from_asset=SETTLEMENT, to_asset=OTHER_TOKEN),),
    )
    broken = [quotes[0], different, *quotes[2:]]
    snap = build(broken)
    assert snap.buy.route_changed is True


def test_a2_05_reordered_legs_change_route() -> None:
    forward = (
        RouteLeg(tool="lifi", from_asset=SETTLEMENT, to_asset=TOKEN),
        RouteLeg(tool="usdg_pool", from_asset=TOKEN, to_asset=TOKEN),
    )
    backward = (forward[1], forward[0])
    quotes = [
        mk_quote(QuoteSide.BUY, SMALL, token_amount="0.8", settlement_amount="100",
                 route=forward),
        mk_quote(QuoteSide.BUY, LARGE, token_amount="7", settlement_amount="1000",
                 route=backward),
        std_quotes()[2],
        std_quotes()[3],
    ]
    snap = build(quotes)
    assert snap.buy.route_changed is True
    assert (
        snap.buy.small_route_signature.canonical_form()
        != snap.buy.large_route_signature.canonical_form()
    )


def test_a2_06_raw_amounts_alone_do_not_change_route() -> None:
    quotes = [
        mk_quote(
            QuoteSide.SELL, SMALL, token_amount="0.8", settlement_amount="90",
            route=(RouteLeg(tool="lifi", from_asset=TOKEN, to_asset=SETTLEMENT,
                            from_amount_raw="800000", to_amount_raw="90000000"),),
        ),
        mk_quote(
            QuoteSide.SELL, LARGE, token_amount="7", settlement_amount="880",
            route=(RouteLeg(tool="lifi", from_asset=TOKEN, to_asset=SETTLEMENT,
                            from_amount_raw="7", to_amount_raw="61"),),
        ),
        std_quotes()[0],
        std_quotes()[1],
    ]
    snap = build(quotes)
    assert snap.sell.route_changed is False
    assert snap.sell.small_route_signature == snap.sell.large_route_signature


# ---------------------------------------------------------------------------
# Correction A3 — exact R2 observation ↔ R0 quote amount lineage
# ---------------------------------------------------------------------------

def test_a3_01_mismatched_r2_token_amount_rejected() -> None:
    tampered = replace(STANDARD_OBSERVATIONS[0], token_amount=Decimal("1.6"))
    observations = [tampered, *STANDARD_OBSERVATIONS[1:]]
    expect_failure(None, observations, LiquidityStatus.R2_LINEAGE_MISMATCH)


def test_a3_02_mismatched_r2_settlement_usd_amount_rejected() -> None:
    tampered = replace(STANDARD_OBSERVATIONS[0], settlement_amount_usd=Decimal("200"))
    observations = [tampered, *STANDARD_OBSERVATIONS[1:]]
    expect_failure(None, observations, LiquidityStatus.R2_LINEAGE_MISMATCH)


def test_a3_03_rescaled_fake_observation_with_same_price_rejected() -> None:
    # Adversarial: same asset/side/notional/quoted_at/source/execution price,
    # but token amount ×2 and settlement USD ×2. The execution price is
    # unchanged, so the price-lineage check alone cannot catch it; exact amount
    # lineage must.
    original = STANDARD_OBSERVATIONS[0]
    tampered = replace(
        original,
        token_amount=original.token_amount * Decimal("2"),
        settlement_amount_usd=original.settlement_amount_usd * Decimal("2"),
    )
    assert tampered.execution_price_usd_per_token == original.execution_price_usd_per_token
    observations = [tampered, *STANDARD_OBSERVATIONS[1:]]
    expect_failure(None, observations, LiquidityStatus.R2_LINEAGE_MISMATCH)


def test_a3_04_exact_quote_derived_observation_still_passes() -> None:
    quotes = std_quotes()
    snap = build(quotes, observations_for(quotes))
    buy_obs = snap.buy.small_gap_observation
    sell_obs = snap.sell.small_gap_observation
    assert buy_obs.token_amount == quotes[0].normalized_amount_out == Decimal("0.8")
    assert buy_obs.settlement_amount_usd == (
        quotes[0].normalized_amount_in * quotes[0].settlement_reference.usd_per_asset
    )
    assert sell_obs.token_amount == quotes[2].normalized_amount_in == Decimal("0.8")
    assert sell_obs.settlement_amount_usd == (
        quotes[2].normalized_amount_out * quotes[2].settlement_reference.usd_per_asset
    )


def test_a3_05_fee_lineage_mismatch_rejected() -> None:
    tampered = replace(STANDARD_OBSERVATIONS[0], fee_cost_usd=Decimal("9"))
    observations = [tampered, *STANDARD_OBSERVATIONS[1:]]
    expect_failure(None, observations, LiquidityStatus.R2_LINEAGE_MISMATCH)
    # A quote with fees against an observation without them also mismatches.
    fabricated = replace(STANDARD_OBSERVATIONS[0], fee_cost_usd=None)
    quote_with_fee = replace(std_quotes()[0], fee_cost_usd=Decimal("1"))
    broken_quotes = [quote_with_fee, *std_quotes()[1:]]
    expect_failure(
        broken_quotes,
        [fabricated, *STANDARD_OBSERVATIONS[1:]],
        LiquidityStatus.R2_LINEAGE_MISMATCH,
    )


def test_a3_06_gas_lineage_mismatch_rejected() -> None:
    tampered = replace(STANDARD_OBSERVATIONS[0], gas_cost_usd=Decimal("7"))
    observations = [tampered, *STANDARD_OBSERVATIONS[1:]]
    expect_failure(None, observations, LiquidityStatus.R2_LINEAGE_MISMATCH)


def test_a3_07_fee_gas_present_and_matching_remain_lineage_only() -> None:
    quotes = std_quotes()
    quotes[0] = replace(quotes[0], fee_cost_usd=Decimal("1"), gas_cost_usd=Decimal("0.5"))
    snap = build(quotes, observations_for(quotes))
    assert snap.buy.small_gap_observation.fee_cost_usd == Decimal("1")
    assert snap.buy.small_gap_observation.gas_cost_usd == Decimal("0.5")
    # Costs remain evidence only: execution prices and spreads are unchanged.
    assert snap.spread_small.buy_execution_price_usd_per_token == Decimal("125")
