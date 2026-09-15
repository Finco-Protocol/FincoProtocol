from __future__ import annotations

from datetime import datetime, timezone
from decimal import Decimal

import pytest

from finco_radar.assets.contracts import (
    AssetKey,
    CanonicalAssetRecord,
    ReferenceBinding,
    RegistryAssetStatus,
)
from finco_radar.gap.contracts import GapComputationError, ReferenceSide
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


def settlement(usable: bool = True, *, chain_id: int = 4663) -> SettlementReference:
    return SettlementReference(
        asset=AssetRef(chain_id, SETTLEMENT, symbol="USDG", decimals=18),
        state=(
            SettlementReferenceState.REFERENCE_CURRENT
            if usable
            else SettlementReferenceState.REFERENCE_UNAVAILABLE
        ),
        usd_per_asset=Decimal("1") if usable else None,
        source="TEST_SETTLEMENT",
        observed_at=NOW,
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
) -> ExecutionQuote:
    settlement_ref = settlement(usable_settlement, chain_id=settlement_chain_id)
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
        quoted_at=NOW,
        settlement_reference=settlement_ref,
        status=status,
        fee_cost_usd=Decimal(fee) if fee is not None else None,
        gas_cost_usd=Decimal(gas) if gas is not None else None,
    )


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
