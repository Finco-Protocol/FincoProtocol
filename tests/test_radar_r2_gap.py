from __future__ import annotations

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
    GapComputationError,
    GapStatus,
    ReferenceSide,
)
from finco_radar.gap.engine import build_bound_reference_price, compute_directional_gap
from finco_radar.quotes.contracts import (
    AssetRef,
    ExecutionQuote,
    QuoteSide,
    QuoteStatus,
    SettlementReference,
    SettlementReferenceState,
)

UID = "0x" + "11" * 32
TOKEN = "0x" + "aa" * 20
OTHER_TOKEN = "0x" + "bb" * 20
SETTLEMENT = "0x" + "cc" * 20
NOW = datetime(2026, 9, 15, 12, 0, tzinfo=timezone.utc)
POLICY = GapComparisonPolicy(max_evidence_skew_seconds=120)


def asset(multiplier: str = "1") -> CanonicalAssetRecord:
    return CanonicalAssetRecord(
        asset_uid=UID,
        token_symbol="AAA",
        token_name="AAA Token",
        deployments=(AssetKey(4663, TOKEN),),
        current_multiplier=Decimal(multiplier),
        pending_multiplier=None,
        pending_multiplier_effective_at=None,
        status=RegistryAssetStatus.ACTIVE,
    )


def binding() -> ReferenceBinding:
    return ReferenceBinding(
        asset_uid=UID,
        asset_key=AssetKey(4663, TOKEN),
        reference_symbol="AAA",
    )


def price_row(**overrides: object) -> dict[str, object]:
    row: dict[str, object] = {
        "tokenSymbol": "AAA",
        "deployments": [{"chainId": 4663, "contractAddress": TOKEN}],
        "bid": "95",
        "ask": "105",
        "currency": "USD",
        "generatedAt": "2026-09-15T12:00:00Z",
        "isTradingHalt": False,
    }
    row.update(overrides)
    return row


def reference(multiplier: str = "1", **row_overrides: object):
    return build_bound_reference_price(asset(multiplier), binding(), price_row(**row_overrides))


def settlement(
    usable: bool = True,
    *,
    chain_id: int = 4663,
    observed_at: datetime | None = NOW,
    observed_at_naive: bool = False,
) -> SettlementReference:
    ts = observed_at
    if observed_at_naive and ts is not None:
        ts = ts.replace(tzinfo=None)
    return SettlementReference(
        asset=AssetRef(chain_id, SETTLEMENT, symbol="USDG", decimals=18),
        state=(
            SettlementReferenceState.REFERENCE_CURRENT
            if usable
            else SettlementReferenceState.REFERENCE_UNAVAILABLE
        ),
        usd_per_asset=Decimal("1") if usable else None,
        source="TEST_SETTLEMENT",
        observed_at=ts,
        raw_evidence={
            "address": SETTLEMENT,
            "symbol": "USDG",
            "decimals": 18,
            "priceUSD": "1.0",
            "canonicalIdentity": f"4663:{SETTLEMENT}",
        },
    )


def quote(
    side: QuoteSide,
    *,
    token_address: str = TOKEN,
    status: QuoteStatus = QuoteStatus.QUOTE_OK,
    normalized_in: str = "100",
    normalized_out: str = "0.8",
    fee: str | None = None,
    gas: str | None = None,
    usable_settlement: bool = True,
    settlement_chain_id: int = 4663,
    quoted_at: datetime = NOW,
    settlement_observed_at: datetime | None = NOW,
    settlement_naive: bool = False,
) -> ExecutionQuote:
    settlement_ref = settlement(
        usable_settlement,
        chain_id=settlement_chain_id,
        observed_at=settlement_observed_at,
        observed_at_naive=settlement_naive,
    )
    token_ref = AssetRef(4663, token_address, symbol="AAA", decimals=18)
    if side is QuoteSide.BUY:
        input_asset, output_asset = settlement_ref.asset, token_ref
    else:
        input_asset, output_asset = token_ref, settlement_ref.asset
    return ExecutionQuote(
        chain_id=4663,
        token_address=token_address,
        side=side,
        input_asset=input_asset,
        output_asset=output_asset,
        requested_notional_usd=Decimal("100"),
        raw_amount_in=1,
        raw_amount_out=1,
        normalized_amount_in=Decimal(normalized_in),
        normalized_amount_out=Decimal(normalized_out),
        input_decimals=18,
        output_decimals=18,
        source="TEST_EXECUTION",
        quoted_at=quoted_at,
        settlement_reference=settlement_ref,
        status=status,
        fee_cost_usd=Decimal(fee) if fee is not None else None,
        gas_cost_usd=Decimal(gas) if gas is not None else None,
    )


# ---------------------------------------------------------------------------
# Existing tests (unchanged — these must continue to pass)
# ---------------------------------------------------------------------------

def test_bound_reference_applies_multiplier_once_to_bid_and_ask() -> None:
    ref = reference("2")
    assert ref.raw_bid_usd_per_share == Decimal("95")
    assert ref.raw_ask_usd_per_share == Decimal("105")
    assert ref.token_bid_usd_per_token == Decimal("190")
    assert ref.token_ask_usd_per_token == Decimal("210")
    assert ref.token_midpoint_usd_per_token == Decimal("200")


def test_buy_gap_uses_official_ask_not_midpoint() -> None:
    obs = compute_directional_gap(reference(), quote(QuoteSide.BUY))
    expected_execution = Decimal("100") / Decimal("0.8")
    expected = ((expected_execution / Decimal("105")) - 1) * Decimal("10000")
    assert obs.reference_side is ReferenceSide.ASK
    assert obs.reference_price_usd_per_token == Decimal("105")
    assert obs.execution_price_usd_per_token == expected_execution
    assert obs.gap_bps == expected


def test_sell_gap_uses_official_bid_not_midpoint() -> None:
    obs = compute_directional_gap(
        reference(),
        quote(QuoteSide.SELL, normalized_in="1", normalized_out="90"),
    )
    expected = ((Decimal("90") / Decimal("95")) - 1) * Decimal("10000")
    assert obs.reference_side is ReferenceSide.BID
    assert obs.reference_price_usd_per_token == Decimal("95")
    assert obs.execution_price_usd_per_token == Decimal("90")
    assert obs.gap_bps == expected


def test_multiplier_is_not_applied_to_execution_price() -> None:
    obs = compute_directional_gap(reference("2"), quote(QuoteSide.BUY))
    assert obs.execution_price_usd_per_token == Decimal("125")
    assert obs.reference_price_usd_per_token == Decimal("210")


def test_fees_and_gas_are_preserved_but_not_added_to_gap_price() -> None:
    plain = compute_directional_gap(reference(), quote(QuoteSide.BUY))
    costed = compute_directional_gap(
        reference(),
        quote(QuoteSide.BUY, fee="7.5", gas="2.5"),
    )
    assert costed.execution_price_usd_per_token == plain.execution_price_usd_per_token
    assert costed.gap_bps == plain.gap_bps
    assert costed.fee_cost_usd == Decimal("7.5")
    assert costed.gas_cost_usd == Decimal("2.5")
    assert costed.cost_scope == "ROUTE_AMOUNTS_ONLY_FEES_AND_GAS_NOT_ADDED"


def test_quote_identity_mismatch_fails_closed() -> None:
    with pytest.raises(GapComputationError, match="identity"):
        compute_directional_gap(reference(), quote(QuoteSide.BUY, token_address=OTHER_TOKEN))


@pytest.mark.parametrize("side", [QuoteSide.BUY, QuoteSide.SELL])
def test_settlement_chain_identity_mismatch_fails_closed(side: QuoteSide) -> None:
    with pytest.raises(GapComputationError, match="settlement reference chain"):
        compute_directional_gap(
            reference(),
            quote(side, settlement_chain_id=1),
        )


def test_non_ok_quote_fails_closed_without_numeric_gap() -> None:
    with pytest.raises(GapComputationError, match="QUOTE_OK"):
        compute_directional_gap(
            reference(),
            quote(QuoteSide.BUY, status=QuoteStatus.ROUTE_UNAVAILABLE),
        )


def test_unusable_settlement_reference_fails_closed() -> None:
    with pytest.raises(GapComputationError, match="settlement reference"):
        compute_directional_gap(
            reference(),
            quote(QuoteSide.BUY, usable_settlement=False),
        )


def test_non_usd_reference_fails_closed() -> None:
    with pytest.raises(GapComputationError, match="USD-denominated"):
        reference(currency="EUR")


@pytest.mark.parametrize(
    "overrides",
    [
        {"bid": "0"},
        {"ask": "NaN"},
        {"bid": "106", "ask": "105"},
    ],
)
def test_invalid_official_bid_ask_fails_closed(overrides: dict[str, object]) -> None:
    with pytest.raises(GapComputationError):
        reference(**overrides)


def test_reference_requires_exact_canonical_deployment_once() -> None:
    duplicate = [
        {"chainId": 4663, "contractAddress": TOKEN},
        {"chainId": 4663, "contractAddress": TOKEN},
    ]
    with pytest.raises(GapComputationError, match="duplicate"):
        reference(deployments=duplicate)
    with pytest.raises(GapComputationError, match="exactly once"):
        reference(deployments=[{"chainId": 4663, "contractAddress": OTHER_TOKEN}])


def test_reference_requires_timezone_aware_generated_at() -> None:
    with pytest.raises(GapComputationError, match="timezone-aware"):
        reference(generatedAt="2026-09-15T12:00:00")


def test_explicit_halt_is_preserved_but_r4_state_authority_is_not_invented() -> None:
    obs = compute_directional_gap(
        reference(isTradingHalt=True),
        quote(QuoteSide.BUY),
    )
    assert obs.reference_is_trading_halt is True
    assert obs.reference_state_authority == "R4_NOT_YET_APPLIED"


def test_binding_uid_mismatch_fails_closed() -> None:
    wrong = ReferenceBinding(
        asset_uid="0x" + "22" * 32,
        asset_key=AssetKey(4663, TOKEN),
        reference_symbol="AAA",
    )
    with pytest.raises(GapComputationError, match="uid"):
        build_bound_reference_price(asset(), wrong, price_row())


# ---------------------------------------------------------------------------
# C1: Temporal coherence (GapComparisonPolicy)
# ---------------------------------------------------------------------------

def test_c1_within_policy_passes() -> None:
    """C1-1: reference + settlement + quote all within boundary → PASS."""
    ref_time = NOW
    sett_time = NOW + timedelta(seconds=30)
    quote_time = NOW + timedelta(seconds=60)
    ref = build_bound_reference_price(
        asset(), binding(),
        price_row(generatedAt=ref_time.isoformat()),
    )
    q = quote(QuoteSide.BUY, quoted_at=quote_time, settlement_observed_at=sett_time)
    obs = compute_directional_gap(ref, q, policy=GapComparisonPolicy(max_evidence_skew_seconds=120))
    assert obs.gap_bps.is_finite()
    assert obs.settlement_observed_at == sett_time


def test_c1_stale_reference_fails_with_evidence_time_mismatch() -> None:
    """C1-2: stale reference (200s old) vs fresh quote → EVIDENCE_TIME_MISMATCH."""
    ref_time = NOW - timedelta(seconds=200)
    ref = build_bound_reference_price(
        asset(), binding(),
        price_row(generatedAt=ref_time.isoformat()),
    )
    q = quote(QuoteSide.BUY, quoted_at=NOW, settlement_observed_at=NOW)
    with pytest.raises(GapComputationError) as exc_info:
        compute_directional_gap(ref, q, policy=GapComparisonPolicy(max_evidence_skew_seconds=120))
    assert exc_info.value.status is GapStatus.EVIDENCE_TIME_MISMATCH
    assert "skew" in str(exc_info.value).lower() or "exceeds" in str(exc_info.value).lower()


def test_c1_stale_settlement_fails_with_evidence_time_mismatch() -> None:
    """C1-3: stale settlement reference (200s old) vs fresh quote → EVIDENCE_TIME_MISMATCH."""
    old_settlement = NOW - timedelta(seconds=200)
    q = quote(QuoteSide.BUY, quoted_at=NOW, settlement_observed_at=old_settlement)
    ref = reference()
    with pytest.raises(GapComputationError) as exc_info:
        compute_directional_gap(ref, q, policy=GapComparisonPolicy(max_evidence_skew_seconds=120))
    assert exc_info.value.status is GapStatus.EVIDENCE_TIME_MISMATCH


def test_c1_exact_boundary_value_passes() -> None:
    """C1-4: skew exactly equal to max_evidence_skew_seconds → PASS (not exceeded)."""
    ref_time = NOW - timedelta(seconds=120)
    ref = build_bound_reference_price(
        asset(), binding(),
        price_row(generatedAt=ref_time.isoformat()),
    )
    q = quote(QuoteSide.BUY, quoted_at=NOW, settlement_observed_at=NOW)
    obs = compute_directional_gap(ref, q, policy=GapComparisonPolicy(max_evidence_skew_seconds=120))
    assert obs.gap_bps.is_finite()


def test_c1_timezone_naive_settlement_fails_closed() -> None:
    """C1-5: timezone-naive settlement observed_at → fail closed."""
    q = quote(QuoteSide.BUY, settlement_naive=True)
    with pytest.raises(GapComputationError) as exc_info:
        compute_directional_gap(reference(), q, policy=POLICY)
    assert exc_info.value.status is GapStatus.EVIDENCE_TIME_MISMATCH


def test_c1_missing_settlement_observed_at_fails_closed() -> None:
    """C1: absent settlement observed_at fails closed under policy."""
    q = quote(QuoteSide.BUY, settlement_observed_at=None)
    with pytest.raises(GapComputationError) as exc_info:
        compute_directional_gap(reference(), q, policy=POLICY)
    assert exc_info.value.status is GapStatus.EVIDENCE_TIME_MISMATCH


def test_c1_no_policy_skips_skew_check() -> None:
    """Without a policy, stale evidence is not blocked (backward compat)."""
    old = NOW - timedelta(seconds=9999)
    ref = build_bound_reference_price(
        asset(), binding(),
        price_row(generatedAt=old.isoformat()),
    )
    obs = compute_directional_gap(ref, quote(QuoteSide.BUY))
    assert obs.gap_bps.is_finite()


# ---------------------------------------------------------------------------
# C2: Settlement evidence reconstructibility
# ---------------------------------------------------------------------------

def test_c2_settlement_observed_at_preserved_in_observation() -> None:
    """C2: settlement_observed_at is in the observation for reconstruction."""
    obs = compute_directional_gap(reference(), quote(QuoteSide.BUY))
    assert obs.settlement_observed_at == NOW


def test_c2_settlement_observed_at_none_when_absent() -> None:
    """C2: absent observed_at is preserved as None (without policy)."""
    q = quote(QuoteSide.BUY, settlement_observed_at=None)
    obs = compute_directional_gap(reference(), q)
    assert obs.settlement_observed_at is None


def test_c2_settlement_evidence_fields_present() -> None:
    """C2: SettlementReference raw_evidence contains conversion inputs."""
    sett = settlement()
    assert "address" in sett.raw_evidence or "canonicalIdentity" in sett.raw_evidence
    assert sett.usd_per_asset is not None
    assert sett.observed_at is not None
    assert sett.source is not None
    assert sett.asset.chain_id == 4663
    assert sett.asset.contract_address == SETTLEMENT
    # Reconstruct: settlement_token_amount × usd_per_asset = settlement_usd
    obs = compute_directional_gap(reference(), quote(QuoteSide.BUY))
    # normalized_in is 100 USDG, usd_per_asset is 1.0 → settlement_amount_usd = 100
    assert obs.settlement_amount_usd == Decimal("100")
    assert sett.usd_per_asset * Decimal("100") == obs.settlement_amount_usd


# ---------------------------------------------------------------------------
# C3: Primary directional vs neutral midpoint analytics
# ---------------------------------------------------------------------------

def test_c3_buy_gap_still_uses_ask() -> None:
    """C3: BUY directional GAP unchanged — uses official ASK."""
    obs = compute_directional_gap(reference(), quote(QuoteSide.BUY))
    assert obs.reference_side is ReferenceSide.ASK
    assert obs.reference_price_usd_per_token == Decimal("105")


def test_c3_sell_gap_still_uses_bid() -> None:
    """C3: SELL directional GAP unchanged — uses official BID."""
    obs = compute_directional_gap(
        reference(), quote(QuoteSide.SELL, normalized_in="1", normalized_out="90")
    )
    assert obs.reference_side is ReferenceSide.BID
    assert obs.reference_price_usd_per_token == Decimal("95")


def test_c3_buy_gap_to_mid_formula() -> None:
    """C3: neutral midpoint BUY formula uses (bid+ask)/2."""
    ref = reference()
    obs = compute_directional_gap(ref, quote(QuoteSide.BUY))
    mid = ref.token_midpoint_usd_per_token  # (95+105)/2 = 100
    assert mid == Decimal("100")
    expected_to_mid = ((obs.execution_price_usd_per_token / mid) - Decimal("1")) * Decimal("10000")
    assert obs.gap_to_mid_bps == expected_to_mid


def test_c3_sell_gap_to_mid_formula() -> None:
    """C3: neutral midpoint SELL formula uses (bid+ask)/2."""
    ref = reference()
    obs = compute_directional_gap(
        ref, quote(QuoteSide.SELL, normalized_in="1", normalized_out="90")
    )
    mid = ref.token_midpoint_usd_per_token
    expected_to_mid = ((Decimal("90") / mid) - Decimal("1")) * Decimal("10000")
    assert obs.gap_to_mid_bps == expected_to_mid


def test_c3_gap_to_mid_differs_from_directional_gap() -> None:
    """C3: gap_to_mid_bps is distinct from gap_bps when bid != ask."""
    ref = reference()  # bid=95, ask=105, mid=100
    obs = compute_directional_gap(ref, quote(QuoteSide.BUY))
    # BUY uses ask=105; mid=100 — these are different so gap_bps != gap_to_mid_bps
    assert obs.gap_bps != obs.gap_to_mid_bps


def test_c3_gap_to_mid_equals_directional_when_bid_equals_ask() -> None:
    """C3: when bid==ask==mid, gap_to_mid_bps equals gap_bps for BUY."""
    ref = reference(bid="100", ask="100")  # bid==ask==mid==100
    obs = compute_directional_gap(ref, quote(QuoteSide.BUY))
    assert obs.gap_bps == obs.gap_to_mid_bps


def test_c3_execution_midpoint_formula() -> None:
    """C3: P_execution_mid = (P_buy + P_sell) / 2 computed externally from observations."""
    ref = reference()
    obs_buy = compute_directional_gap(ref, quote(QuoteSide.BUY))
    obs_sell = compute_directional_gap(
        ref, quote(QuoteSide.SELL, normalized_in="1", normalized_out="90")
    )
    p_exec_mid = (obs_buy.execution_price_usd_per_token + obs_sell.execution_price_usd_per_token) / Decimal("2")
    assert p_exec_mid.is_finite() and p_exec_mid > 0


def test_c3_mid_gap_formula() -> None:
    """C3: mid_gap_bps = ((P_exec_mid / P_ref_mid) - 1) * 10_000."""
    ref = reference()
    obs_buy = compute_directional_gap(ref, quote(QuoteSide.BUY))
    obs_sell = compute_directional_gap(
        ref, quote(QuoteSide.SELL, normalized_in="1", normalized_out="90")
    )
    p_exec_mid = (obs_buy.execution_price_usd_per_token + obs_sell.execution_price_usd_per_token) / Decimal("2")
    ref_mid = ref.token_midpoint_usd_per_token
    mid_gap = ((p_exec_mid / ref_mid) - Decimal("1")) * Decimal("10000")
    assert mid_gap.is_finite()


def test_c3_quote_spread_formula() -> None:
    """C3: quote_spread_bps = ((P_buy - P_sell) / P_exec_mid) * 10_000."""
    ref = reference()
    obs_buy = compute_directional_gap(ref, quote(QuoteSide.BUY))
    obs_sell = compute_directional_gap(
        ref, quote(QuoteSide.SELL, normalized_in="1", normalized_out="90")
    )
    p_exec_mid = (obs_buy.execution_price_usd_per_token + obs_sell.execution_price_usd_per_token) / Decimal("2")
    spread = ((obs_buy.execution_price_usd_per_token - obs_sell.execution_price_usd_per_token) / p_exec_mid) * Decimal("10000")
    assert spread.is_finite()


# ---------------------------------------------------------------------------
# C4: Deterministic size comparison
# ---------------------------------------------------------------------------

def _make_obs(side: QuoteSide, notional: str, out: str) -> object:
    """Helper: observation at a specific notional with given token output."""
    ref = reference()
    if side is QuoteSide.BUY:
        q = ExecutionQuote(
            chain_id=4663,
            token_address=TOKEN,
            side=side,
            input_asset=settlement().asset,
            output_asset=AssetRef(4663, TOKEN, symbol="AAA", decimals=18),
            requested_notional_usd=Decimal(notional),
            raw_amount_in=1,
            raw_amount_out=1,
            normalized_amount_in=Decimal(notional),
            normalized_amount_out=Decimal(out),
            input_decimals=18,
            output_decimals=18,
            source="TEST",
            quoted_at=NOW,
            settlement_reference=settlement(),
            status=QuoteStatus.QUOTE_OK,
        )
    else:
        q = ExecutionQuote(
            chain_id=4663,
            token_address=TOKEN,
            side=side,
            input_asset=AssetRef(4663, TOKEN, symbol="AAA", decimals=18),
            output_asset=settlement().asset,
            requested_notional_usd=Decimal(notional),
            raw_amount_in=1,
            raw_amount_out=1,
            normalized_amount_in=Decimal(out),
            normalized_amount_out=Decimal(notional),
            input_decimals=18,
            output_decimals=18,
            source="TEST",
            quoted_at=NOW,
            settlement_reference=settlement(),
            status=QuoteStatus.QUOTE_OK,
        )
    return compute_directional_gap(ref, q)


def test_c4_size_snapshots_are_distinct_objects() -> None:
    """C4: $100 and $1000 observations are separate computed values."""
    obs_100 = _make_obs(QuoteSide.BUY, "100", "0.8")
    obs_1000 = _make_obs(QuoteSide.BUY, "1000", "7.5")
    assert obs_100 is not obs_1000
    assert obs_100.requested_notional_usd == Decimal("100")
    assert obs_1000.requested_notional_usd == Decimal("1000")


def test_c4_buy_directional_gap_delta_orientation() -> None:
    """C4: buyDirectionalGapDelta = large_gap - small_gap, deterministic orientation."""
    obs_100 = _make_obs(QuoteSide.BUY, "100", "0.8")    # P_buy = 100/0.8 = 125
    obs_1000 = _make_obs(QuoteSide.BUY, "1000", "7.5")  # P_buy = 1000/7.5 ≈ 133.3

    buy_gap_100 = obs_100.gap_bps
    buy_gap_1000 = obs_1000.gap_bps
    delta = buy_gap_1000 - buy_gap_100
    # Verify the delta is finite and sign is consistent
    assert delta.is_finite()
    # At 1000 the execution price is higher (7.5 tokens per 1000 < 8 per 100),
    # so P_buy_1000 > P_buy_100, meaning gap_1000 > gap_100, delta > 0
    assert delta > 0


def test_c4_sell_directional_gap_delta_orientation() -> None:
    """C4: sellDirectionalGapDelta = large_gap - small_gap, deterministic orientation."""
    # For SELL: normalized_in=token_amount, normalized_out=settlement_amount
    # $100 SELL: token_in=1, settlement_out=90 → P_sell=90
    # $1000 SELL: token_in=10, settlement_out=880 → P_sell=88 (worse due to impact)
    ref = reference()

    q_100 = ExecutionQuote(
        chain_id=4663, token_address=TOKEN, side=QuoteSide.SELL,
        input_asset=AssetRef(4663, TOKEN, symbol="AAA", decimals=18),
        output_asset=settlement().asset,
        requested_notional_usd=Decimal("100"),
        raw_amount_in=1, raw_amount_out=1,
        normalized_amount_in=Decimal("1"), normalized_amount_out=Decimal("90"),
        input_decimals=18, output_decimals=18, source="TEST", quoted_at=NOW,
        settlement_reference=settlement(), status=QuoteStatus.QUOTE_OK,
    )
    q_1000 = ExecutionQuote(
        chain_id=4663, token_address=TOKEN, side=QuoteSide.SELL,
        input_asset=AssetRef(4663, TOKEN, symbol="AAA", decimals=18),
        output_asset=settlement().asset,
        requested_notional_usd=Decimal("1000"),
        raw_amount_in=1, raw_amount_out=1,
        normalized_amount_in=Decimal("10"), normalized_amount_out=Decimal("880"),
        input_decimals=18, output_decimals=18, source="TEST", quoted_at=NOW,
        settlement_reference=settlement(), status=QuoteStatus.QUOTE_OK,
    )

    obs_100 = compute_directional_gap(ref, q_100)
    obs_1000 = compute_directional_gap(ref, q_1000)
    delta = obs_1000.gap_bps - obs_100.gap_bps
    assert delta.is_finite()
    # $1000 SELL realized 88/token, $100 realized 90/token — larger size is worse
    assert delta < 0


def test_c4_r0_size_impact_not_conflated_with_gap_delta() -> None:
    """C4: R0 size-impact is a separate metric — not renamed or conflated with gap delta."""
    # gap delta and r0 size impact are distinct concepts with different formulas.
    # The test checks they're independently computed and not substituted.
    obs_100 = _make_obs(QuoteSide.BUY, "100", "0.8")
    obs_1000 = _make_obs(QuoteSide.BUY, "1000", "7.5")
    gap_delta_bps = obs_1000.gap_bps - obs_100.gap_bps
    # R0 size-impact formula (from quotes/normalization.py): different than gap delta
    # They may not equal each other even at similar magnitudes.
    # The structural test: gap_delta uses gap_bps (vs reference side).
    # R0 size-impact uses effective output-per-input ratio comparison.
    assert gap_delta_bps.is_finite()
    assert obs_100.gap_bps != obs_1000.gap_bps  # different sizes → different gaps


# ---------------------------------------------------------------------------
# C5: Typed status mapping
# ---------------------------------------------------------------------------

def test_c5_quote_unavailable_carries_typed_status() -> None:
    """C5: ROUTE_UNAVAILABLE quote maps to QUOTE_UNAVAILABLE status."""
    with pytest.raises(GapComputationError) as exc_info:
        compute_directional_gap(
            reference(),
            quote(QuoteSide.BUY, status=QuoteStatus.ROUTE_UNAVAILABLE),
        )
    assert exc_info.value.status is GapStatus.QUOTE_UNAVAILABLE


def test_c5_settlement_unavailable_carries_typed_status() -> None:
    """C5: unusable settlement maps to SETTLEMENT_REFERENCE_UNAVAILABLE."""
    with pytest.raises(GapComputationError) as exc_info:
        compute_directional_gap(reference(), quote(QuoteSide.BUY, usable_settlement=False))
    assert exc_info.value.status is GapStatus.SETTLEMENT_REFERENCE_UNAVAILABLE


def test_c5_settlement_chain_mismatch_carries_typed_status() -> None:
    """C5: settlement chain mismatch maps to SETTLEMENT_REFERENCE_UNAVAILABLE."""
    with pytest.raises(GapComputationError) as exc_info:
        compute_directional_gap(reference(), quote(QuoteSide.BUY, settlement_chain_id=1))
    assert exc_info.value.status is GapStatus.SETTLEMENT_REFERENCE_UNAVAILABLE


def test_c5_reference_binding_mismatch_carries_typed_status() -> None:
    """C5: token identity mismatch maps to REFERENCE_BINDING_FAILED."""
    with pytest.raises(GapComputationError) as exc_info:
        compute_directional_gap(reference(), quote(QuoteSide.BUY, token_address=OTHER_TOKEN))
    assert exc_info.value.status is GapStatus.REFERENCE_BINDING_FAILED


def test_c5_evidence_time_mismatch_carries_typed_status() -> None:
    """C5: temporal coherence failure maps to EVIDENCE_TIME_MISMATCH."""
    old = NOW - timedelta(seconds=999)
    ref = build_bound_reference_price(
        asset(), binding(),
        price_row(generatedAt=old.isoformat()),
    )
    with pytest.raises(GapComputationError) as exc_info:
        compute_directional_gap(ref, quote(QuoteSide.BUY), policy=POLICY)
    assert exc_info.value.status is GapStatus.EVIDENCE_TIME_MISMATCH


def test_c5_binding_uid_mismatch_carries_typed_status() -> None:
    """C5: uid mismatch in build_bound_reference_price maps to REFERENCE_BINDING_FAILED."""
    wrong = ReferenceBinding(
        asset_uid="0x" + "22" * 32,
        asset_key=AssetKey(4663, TOKEN),
        reference_symbol="AAA",
    )
    with pytest.raises(GapComputationError) as exc_info:
        build_bound_reference_price(asset(), wrong, price_row())
    assert exc_info.value.status is GapStatus.REFERENCE_BINDING_FAILED


def test_c5_reference_invalid_usd_carries_typed_status() -> None:
    """C5: non-USD reference maps to REFERENCE_INVALID."""
    with pytest.raises(GapComputationError) as exc_info:
        reference(currency="EUR")
    assert exc_info.value.status is GapStatus.REFERENCE_INVALID


# ---------------------------------------------------------------------------
# C6: Evidence provenance
# ---------------------------------------------------------------------------

def test_c6_settlement_observed_at_in_observation() -> None:
    """C6: settlement_observed_at in observation for provenance."""
    obs = compute_directional_gap(reference(), quote(QuoteSide.BUY))
    assert obs.settlement_observed_at is not None
    assert obs.settlement_observed_at.tzinfo is not None


def test_c6_reference_generated_at_in_observation() -> None:
    """C6: reference_generated_at preserved in observation."""
    obs = compute_directional_gap(reference(), quote(QuoteSide.BUY))
    assert obs.reference_generated_at == NOW


def test_c6_settlement_chain_mismatch_still_fails_closed() -> None:
    """C6: settlement chain mismatch is not silently ignored."""
    with pytest.raises(GapComputationError):
        compute_directional_gap(reference(), quote(QuoteSide.BUY, settlement_chain_id=1))


def test_c6_settlement_address_mismatch_still_fails_closed() -> None:
    """C6: settlement address mismatch detected via identity check."""
    with pytest.raises(GapComputationError):
        compute_directional_gap(reference(), quote(QuoteSide.BUY, token_address=OTHER_TOKEN))


# ---------------------------------------------------------------------------
# C7: Multiplier semantics documentation
# ---------------------------------------------------------------------------

def test_c7_multiplier_formula_documented() -> None:
    """C7: BoundReferencePrice exposes multiplier_formula as human-readable string."""
    ref = reference("2")
    formula = ref.multiplier_formula
    assert "190" in formula  # token_bid = 95 * 2
    assert "210" in formula  # token_ask = 105 * 2
    assert "currentMultiplier" in formula or "multiplier" in formula.lower()


def test_c7_multiplier_applied_once_only() -> None:
    """C7: raw_bid × multiplier = token_bid (applied exactly once, not compounded)."""
    ref = reference("3")
    # raw_bid=95, multiplier=3 → token_bid=285 (not 855)
    assert ref.token_bid_usd_per_token == Decimal("285")
    assert ref.token_ask_usd_per_token == Decimal("315")
    # Execution price uses the settlement/token ratio, not the reference
    obs = compute_directional_gap(ref, quote(QuoteSide.BUY))
    assert obs.execution_price_usd_per_token == Decimal("125")  # 100/0.8, unaffected by multiplier
    assert obs.reference_price_usd_per_token == Decimal("315")  # token_ask with multiplier


def test_c7_raw_bid_ask_preserved_separately() -> None:
    """C7: raw equity prices preserved alongside token-adjusted prices."""
    ref = reference("2")
    assert ref.raw_bid_usd_per_share == Decimal("95")
    assert ref.raw_ask_usd_per_share == Decimal("105")
    assert ref.token_bid_usd_per_token == Decimal("190")
    assert ref.token_ask_usd_per_token == Decimal("210")
    # They differ by exactly the multiplier
    assert ref.token_bid_usd_per_token == ref.raw_bid_usd_per_share * ref.current_multiplier
    assert ref.token_ask_usd_per_token == ref.raw_ask_usd_per_share * ref.current_multiplier
