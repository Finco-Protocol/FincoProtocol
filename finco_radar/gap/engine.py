"""Fail-closed FINCO GAP computation over R0 quotes and R1 canonical identity."""
from __future__ import annotations

from datetime import datetime
from decimal import Decimal, InvalidOperation
from typing import Any, Mapping

from finco_radar.assets.contracts import (
    AssetKey,
    CanonicalAssetRecord,
    ReferenceBinding,
    normalize_symbol,
)
from finco_radar.quotes.contracts import AssetRef, ExecutionQuote, QuoteSide, QuoteStatus

from .contracts import (
    BoundReferencePrice,
    DirectionalGapObservation,
    GapComparisonPolicy,
    GapComputationError,
    GapStatus,
    ReferenceSide,
    r1_boundary,
)


def _decimal(value: Any, field_name: str) -> Decimal:
    try:
        parsed = Decimal(str(value))
    except (InvalidOperation, TypeError, ValueError) as exc:
        raise GapComputationError(
            f"{field_name} must be a decimal",
            GapStatus.REFERENCE_INVALID,
        ) from exc
    if not parsed.is_finite() or parsed <= 0:
        raise GapComputationError(
            f"{field_name} must be positive and finite",
            GapStatus.REFERENCE_INVALID,
        )
    return parsed


def _timestamp(value: Any) -> datetime:
    if not isinstance(value, str) or not value.strip():
        raise GapComputationError(
            "official reference generatedAt is required",
            GapStatus.REFERENCE_INVALID,
        )
    try:
        parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
    except ValueError as exc:
        raise GapComputationError(
            "official reference generatedAt must be ISO-8601",
            GapStatus.REFERENCE_INVALID,
        ) from exc
    if parsed.tzinfo is None:
        raise GapComputationError(
            "official reference generatedAt must be timezone-aware",
            GapStatus.EVIDENCE_TIME_MISMATCH,
        )
    return parsed


def build_bound_reference_price(
    asset: CanonicalAssetRecord,
    binding: ReferenceBinding,
    validated_price_row: Mapping[str, Any],
) -> BoundReferencePrice:
    """Convert one R1-bound official row into multiplier-adjusted token bid/ask authority."""
    if binding.asset_uid != asset.asset_uid:
        raise GapComputationError(
            "reference binding uid does not match canonical asset",
            GapStatus.REFERENCE_BINDING_FAILED,
        )
    if binding.asset_key not in asset.deployments:
        raise GapComputationError(
            "reference binding key is not owned by canonical asset",
            GapStatus.REFERENCE_BINDING_FAILED,
        )
    if binding.reference_symbol != asset.token_symbol:
        raise GapComputationError(
            "reference binding symbol does not match canonical asset metadata",
            GapStatus.REFERENCE_BINDING_FAILED,
        )

    # D2: a malformed tokenSymbol is malformed reference content, not a binding mismatch.
    with r1_boundary(
        "bound reference row tokenSymbol is malformed",
        GapStatus.REFERENCE_INVALID,
    ):
        row_symbol = normalize_symbol(
            str(validated_price_row.get("tokenSymbol") or ""),
            field_name="reference tokenSymbol",
        )
    if row_symbol != binding.reference_symbol:
        raise GapComputationError(
            "bound reference row symbol changed after R1 validation",
            GapStatus.REFERENCE_BINDING_FAILED,
        )

    deployments = validated_price_row.get("deployments")
    if not isinstance(deployments, list):
        raise GapComputationError(
            "bound reference row deployments must be a list",
            GapStatus.REFERENCE_BINDING_FAILED,
        )
    keys: list[AssetKey] = []
    for deployment in deployments:
        if not isinstance(deployment, Mapping):
            raise GapComputationError(
                "bound reference deployment must be an object",
                GapStatus.REFERENCE_BINDING_FAILED,
            )
        try:
            keys.append(
                AssetKey(
                    chain_id=int(deployment["chainId"]),
                    contract_address=str(deployment["contractAddress"]),
                )
            )
        except (KeyError, TypeError, ValueError) as exc:
            raise GapComputationError(
                "invalid deployment in bound reference row",
                GapStatus.REFERENCE_BINDING_FAILED,
            ) from exc
    if len(keys) != len(set(keys)):
        raise GapComputationError(
            "bound reference row contains duplicate deployment keys",
            GapStatus.REFERENCE_BINDING_FAILED,
        )
    if sum(1 for key in keys if key == binding.asset_key) != 1:
        raise GapComputationError(
            "bound reference row must contain the canonical key exactly once",
            GapStatus.REFERENCE_BINDING_FAILED,
        )

    halt = validated_price_row.get("isTradingHalt")
    if not isinstance(halt, bool):
        raise GapComputationError(
            "official reference isTradingHalt must be boolean",
            GapStatus.REFERENCE_INVALID,
        )

    return BoundReferencePrice(
        asset_uid=asset.asset_uid,
        asset_key=binding.asset_key,
        symbol=binding.reference_symbol,
        raw_bid_usd_per_share=_decimal(validated_price_row.get("bid"), "official bid"),
        raw_ask_usd_per_share=_decimal(validated_price_row.get("ask"), "official ask"),
        current_multiplier=asset.current_multiplier,
        currency=str(validated_price_row.get("currency") or ""),
        generated_at=_timestamp(validated_price_row.get("generatedAt")),
        is_trading_halt=halt,
        source="ROBINHOOD_STOCK_TOKEN_BOUND_PRICE",
        raw_evidence=dict(validated_price_row),
    )


def _same_asset(key: AssetKey, *, chain_id: int, address: str) -> bool:
    try:
        return key == AssetKey(chain_id=chain_id, contract_address=address)
    except ValueError:
        return False


def _same_asset_ref(left: AssetRef, right: AssetRef) -> bool:
    """Compare asset identity by chain + contract only, never ticker metadata."""
    try:
        return AssetKey(left.chain_id, left.contract_address) == AssetKey(
            right.chain_id,
            right.contract_address,
        )
    except ValueError:
        return False


def _positive_amount(value: Decimal | None, field_name: str) -> Decimal:
    if value is None or not value.is_finite() or value <= 0:
        raise GapComputationError(
            f"{field_name} must be positive and finite",
            GapStatus.NON_FINITE_ECONOMICS,
        )
    return value


def _check_evidence_skew(
    reference_generated_at: datetime,
    settlement_observed_at: datetime | None,
    quote_quoted_at: datetime,
    policy: GapComparisonPolicy,
) -> Decimal:
    """Validate temporal coherence; return actual skew in seconds.

    C1: The comparison clock set must include reference.generated_at,
    settlement_reference.observed_at, and quote.quoted_at. If settlement_observed_at
    is absent or timezone-naive the check fails closed. The policy threshold is
    caller-supplied — R2 never invents a hidden threshold.
    """
    if settlement_observed_at is None:
        raise GapComputationError(
            "settlement_reference.observed_at is required for coherence policy check",
            GapStatus.EVIDENCE_TIME_MISMATCH,
        )
    if settlement_observed_at.tzinfo is None:
        raise GapComputationError(
            "settlement_reference.observed_at must be timezone-aware",
            GapStatus.EVIDENCE_TIME_MISMATCH,
        )
    if reference_generated_at.tzinfo is None:
        raise GapComputationError(
            "reference generated_at must be timezone-aware",
            GapStatus.EVIDENCE_TIME_MISMATCH,
        )
    if quote_quoted_at.tzinfo is None:
        raise GapComputationError(
            "quote quoted_at must be timezone-aware",
            GapStatus.EVIDENCE_TIME_MISMATCH,
        )
    timestamps = [reference_generated_at, settlement_observed_at, quote_quoted_at]
    earliest = min(timestamps)
    latest = max(timestamps)
    skew = Decimal(str((latest - earliest).total_seconds()))
    if skew > policy.max_evidence_skew_seconds:
        raise GapComputationError(
            f"evidence skew {float(skew):.1f}s exceeds policy {policy.max_evidence_skew_seconds}s",
            GapStatus.EVIDENCE_TIME_MISMATCH,
        )
    return skew


def compute_directional_gap(
    reference: BoundReferencePrice,
    quote: ExecutionQuote,
    *,
    policy: GapComparisonPolicy | None = None,
) -> DirectionalGapObservation:
    """Compute signed on-chain execution price vs the economically matching reference side.

    Positive gap means the on-chain quote-implied token price is above the official
    reference side. Negative means it is below. BUY therefore uses ASK while SELL
    uses BID. Separately reported gas/fee USD amounts are evidence only in R2 and
    are not added to the amount-derived execution price.

    C1: When a GapComparisonPolicy is provided, the evidence timestamps are
    validated for temporal coherence. If max skew exceeds the policy the
    computation fails with EVIDENCE_TIME_MISMATCH. Without a policy the skew
    check is skipped — the live proof always passes one.
    """
    if quote.status is not QuoteStatus.QUOTE_OK:
        raise GapComputationError(
            f"gap requires QUOTE_OK, got {quote.status.value}",
            GapStatus.QUOTE_UNAVAILABLE,
        )
    if not _same_asset(
        reference.asset_key,
        chain_id=quote.chain_id,
        address=quote.token_address,
    ):
        raise GapComputationError(
            "execution quote token identity does not match canonical reference key",
            GapStatus.REFERENCE_BINDING_FAILED,
        )
    if not quote.settlement_reference.usable or quote.settlement_reference.usd_per_asset is None:
        raise GapComputationError(
            "execution quote settlement reference is not usable",
            GapStatus.SETTLEMENT_REFERENCE_UNAVAILABLE,
        )
    if quote.settlement_reference.asset.chain_id != quote.chain_id:
        raise GapComputationError(
            "settlement reference chain does not match execution quote chain",
            GapStatus.SETTLEMENT_REFERENCE_UNAVAILABLE,
        )
    settlement_usd_per_asset = _positive_amount(
        quote.settlement_reference.usd_per_asset,
        "settlement usd_per_asset",
    )

    settlement_observed_at = quote.settlement_reference.observed_at

    # C1: temporal coherence check (when policy provided).
    actual_skew: Decimal | None = None
    if policy is not None:
        actual_skew = _check_evidence_skew(
            reference_generated_at=reference.generated_at,
            settlement_observed_at=settlement_observed_at,
            quote_quoted_at=quote.quoted_at,
            policy=policy,
        )

    if quote.side is QuoteSide.BUY:
        if not _same_asset(
            reference.asset_key,
            chain_id=quote.output_asset.chain_id,
            address=quote.output_asset.contract_address,
        ):
            raise GapComputationError(
                "BUY quote output is not the canonical token",
                GapStatus.REFERENCE_BINDING_FAILED,
            )
        if not _same_asset_ref(quote.input_asset, quote.settlement_reference.asset):
            raise GapComputationError(
                "BUY quote input is not the canonical settlement asset",
                GapStatus.SETTLEMENT_REFERENCE_UNAVAILABLE,
            )
        settlement_amount = _positive_amount(quote.normalized_amount_in, "BUY settlement input")
        token_amount = _positive_amount(quote.normalized_amount_out, "BUY token output")
        settlement_amount_usd = settlement_amount * settlement_usd_per_asset
        execution_price = settlement_amount_usd / token_amount
        reference_side = ReferenceSide.ASK
        reference_price = reference.token_ask_usd_per_token
    elif quote.side is QuoteSide.SELL:
        if not _same_asset(
            reference.asset_key,
            chain_id=quote.input_asset.chain_id,
            address=quote.input_asset.contract_address,
        ):
            raise GapComputationError(
                "SELL quote input is not the canonical token",
                GapStatus.REFERENCE_BINDING_FAILED,
            )
        if not _same_asset_ref(quote.output_asset, quote.settlement_reference.asset):
            raise GapComputationError(
                "SELL quote output is not the canonical settlement asset",
                GapStatus.SETTLEMENT_REFERENCE_UNAVAILABLE,
            )
        token_amount = _positive_amount(quote.normalized_amount_in, "SELL token input")
        settlement_amount = _positive_amount(quote.normalized_amount_out, "SELL settlement output")
        settlement_amount_usd = settlement_amount * settlement_usd_per_asset
        execution_price = settlement_amount_usd / token_amount
        reference_side = ReferenceSide.BID
        reference_price = reference.token_bid_usd_per_token
    else:
        raise GapComputationError(
            "unsupported quote side",
            GapStatus.QUOTE_UNAVAILABLE,
        )

    if not execution_price.is_finite() or execution_price <= 0:
        raise GapComputationError(
            "execution price must be positive and finite",
            GapStatus.NON_FINITE_ECONOMICS,
        )
    gap_bps = ((execution_price / reference_price) - Decimal("1")) * Decimal("10000")
    if not gap_bps.is_finite():
        raise GapComputationError(
            "computed gap is not finite",
            GapStatus.NON_FINITE_ECONOMICS,
        )

    # C3: neutral midpoint comparison (secondary analytic, not the primary directional metric).
    ref_mid = reference.token_midpoint_usd_per_token
    try:
        gap_to_mid_bps = ((execution_price / ref_mid) - Decimal("1")) * Decimal("10000")
    except (InvalidOperation, ZeroDivisionError) as exc:
        raise GapComputationError(
            "gap_to_mid computation failed",
            GapStatus.NON_FINITE_ECONOMICS,
        ) from exc
    if not gap_to_mid_bps.is_finite():
        raise GapComputationError(
            "gap_to_mid_bps is not finite",
            GapStatus.NON_FINITE_ECONOMICS,
        )

    return DirectionalGapObservation(
        asset_uid=reference.asset_uid,
        asset_key=reference.asset_key,
        side=quote.side,
        requested_notional_usd=quote.requested_notional_usd,
        token_amount=token_amount,
        settlement_amount_usd=settlement_amount_usd,
        execution_price_usd_per_token=execution_price,
        reference_side=reference_side,
        reference_price_usd_per_token=reference_price,
        gap_bps=gap_bps,
        gap_to_mid_bps=gap_to_mid_bps,
        quote_source=quote.source,
        quoted_at=quote.quoted_at,
        reference_generated_at=reference.generated_at,
        settlement_observed_at=settlement_observed_at,
        reference_is_trading_halt=reference.is_trading_halt,
        fee_cost_usd=quote.fee_cost_usd,
        gas_cost_usd=quote.gas_cost_usd,
    )
