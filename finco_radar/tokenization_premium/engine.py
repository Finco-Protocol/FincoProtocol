"""P2 tokenization-premium engine.

Computes the tokenization-premium observation from frozen R2/R0 evidence
dicts produced by the composition layer.  Zero duplication of existing
quote normalization, liquidity math, slippage, VWAP, freshness authority,
corporate-action authority, or hash/lineage authority.

This is NOT a trading system.  No BUY/SELL/OPPORTUNITY/ARBITRAGE labels.

Economic semantic note (Correction A):
  currentMultiplier is a UNIT CONVERSION (shares per token), not premium.
  underlying_token_basis = raw_underlying_mid × currentMultiplier
  This equals R2's token_midpoint_usd_per_token — comparing them yields zero.
  Real tokenization premium requires an INDEPENDENT DEX execution price.
"""
from __future__ import annotations

from datetime import datetime
from decimal import Decimal, InvalidOperation
from typing import Any, Mapping

from finco_radar.tokenization_premium.contracts import (
    TokenizationPremiumObservation,
    TokenizationPremiumPolicy,
    TokenizationPremiumStatus,
)


def _parse_decimal(value: Any, field_name: str) -> Decimal:
    """Parse a string/numeric value to Decimal; raise ValueError on failure."""
    if value is None:
        raise ValueError(f"{field_name} is None")
    try:
        d = Decimal(str(value))
    except InvalidOperation as exc:
        raise ValueError(f"{field_name} is not a valid decimal: {value!r}") from exc
    if not d.is_finite():
        raise ValueError(f"{field_name} is not finite: {value!r}")
    return d


def _parse_positive_decimal(value: Any, field_name: str) -> Decimal:
    d = _parse_decimal(value, field_name)
    if d <= 0:
        raise ValueError(f"{field_name} must be positive, got {d}")
    return d


def _parse_iso_dt(value: Any, field_name: str) -> datetime:
    if value is None:
        raise ValueError(f"{field_name} is None")
    try:
        dt = datetime.fromisoformat(str(value))
    except ValueError as exc:
        raise ValueError(f"{field_name} is not valid ISO datetime: {value!r}") from exc
    if dt.tzinfo is None:
        raise ValueError(f"{field_name} must be timezone-aware")
    return dt


def _suppressed(
    status: TokenizationPremiumStatus,
    reason: str,
    ref: dict | None = None,
    buy_exec: dict | None = None,
    sell_exec: dict | None = None,
) -> TokenizationPremiumObservation:
    """Build a suppressed (non-OK) observation."""
    raw: dict[str, Any] = {}
    if ref is not None:
        raw["reference"] = ref
    if buy_exec is not None:
        raw["buyExecution"] = buy_exec
    if sell_exec is not None:
        raw["sellExecution"] = sell_exec
    return TokenizationPremiumObservation(
        status=status,
        underlying_raw_bid_usd_per_share=None,
        underlying_raw_ask_usd_per_share=None,
        underlying_raw_mid_usd_per_share=None,
        current_multiplier=None,
        underlying_token_basis_usd_per_token=None,
        buy_execution_price_usd_per_token=None,
        sell_execution_price_usd_per_token=None,
        execution_mid_price_usd_per_token=None,
        tokenization_premium_bps=None,
        buy_execution_premium_bps=None,
        sell_execution_premium_bps=None,
        reference_observed_at=None,
        buy_quote_observed_at=None,
        sell_quote_observed_at=None,
        suppression_reason=reason,
        raw_evidence=raw,
    )


def compute_tokenization_premium(
    *,
    reference_evidence: Mapping[str, Any],
    buy_exec_evidence: Mapping[str, Any] | None,
    sell_exec_evidence: Mapping[str, Any] | None,
    policy: TokenizationPremiumPolicy,
    complement_identity_verified: bool = True,
) -> TokenizationPremiumObservation:
    """Compute one tokenization-premium observation from frozen evidence dicts.

    reference_evidence  — the "reference" section from the composition layer;
                          must include: rawBid, rawAsk, currentMultiplier,
                          observedAt, available, isTradingHalt.
    buy_exec_evidence   — the "execution" section from a BUY acquisition, or None.
    sell_exec_evidence  — the "execution" section from a SELL acquisition, or None.
    policy              — caller-supplied coherence policy; never invented here.
    complement_identity_verified — False when the complement snapshot was rejected
                          by the router's identity check (asset/notional mismatch);
                          in that case the complement's execution evidence is
                          not consumed and status reflects partial or unavailable.

    Returns a TokenizationPremiumObservation.  This is NOT a trading signal.
    """
    ref = dict(reference_evidence) if reference_evidence else {}
    buy_exec = dict(buy_exec_evidence) if buy_exec_evidence else None
    sell_exec = dict(sell_exec_evidence) if sell_exec_evidence else None

    # --- complement identity guard --------------------------------------------
    # When the complement snapshot failed identity verification, treat it as
    # absent so its execution price is never mixed with a different asset.
    if not complement_identity_verified:
        return _suppressed(
            TokenizationPremiumStatus.COMPLEMENT_IDENTITY_MISMATCH,
            "COMPLEMENT_IDENTITY_NOT_VERIFIED",
            ref=ref, buy_exec=buy_exec, sell_exec=sell_exec,
        )

    # --- reference section availability ----------------------------------------
    if not ref.get("available"):
        reason = ref.get("unavailableReason") or ref.get("reason") or "REFERENCE_UNAVAILABLE"
        return _suppressed(
            TokenizationPremiumStatus.UNDERLYING_REFERENCE_INVALID,
            reason,
            ref=ref,
        )

    # --- trading halt -----------------------------------------------------------
    if ref.get("isTradingHalt"):
        return _suppressed(
            TokenizationPremiumStatus.TRADING_HALTED,
            "TRADING_HALT",
            ref=ref, buy_exec=buy_exec, sell_exec=sell_exec,
        )

    # --- parse underlying raw prices and multiplier ----------------------------
    try:
        raw_bid = _parse_positive_decimal(ref.get("rawBid"), "rawBid")
        raw_ask = _parse_positive_decimal(ref.get("rawAsk"), "rawAsk")
        current_multiplier = _parse_positive_decimal(
            ref.get("currentMultiplier"), "currentMultiplier"
        )
    except ValueError as exc:
        return _suppressed(
            TokenizationPremiumStatus.UNDERLYING_REFERENCE_INVALID,
            f"UNDERLYING_FIELDS_MISSING_OR_INVALID: {exc}",
            ref=ref,
        )

    if raw_ask < raw_bid:
        return _suppressed(
            TokenizationPremiumStatus.UNDERLYING_REFERENCE_INVALID,
            "UNDERLYING_ASK_LESS_THAN_BID",
            ref=ref,
        )

    # --- parse reference timestamp ---------------------------------------------
    try:
        ref_observed_at = _parse_iso_dt(ref.get("observedAt"), "reference.observedAt")
    except ValueError as exc:
        return _suppressed(
            TokenizationPremiumStatus.UNDERLYING_REFERENCE_INVALID,
            f"REFERENCE_TIMESTAMP_INVALID: {exc}",
            ref=ref,
        )

    # --- compute underlying token basis ----------------------------------------
    # underlying_token_basis = underlying_share_mid × currentMultiplier
    # This equals R2's token_midpoint_usd_per_token: it is a unit conversion,
    # NOT tokenization premium.  Real premium requires an independent DEX price.
    underlying_mid = (raw_bid + raw_ask) / Decimal("2")
    underlying_token_basis = underlying_mid * current_multiplier

    # --- check execution availability ------------------------------------------
    buy_available = (
        buy_exec is not None
        and buy_exec.get("available") is True
        and buy_exec.get("effectivePrice") is not None
    )
    sell_available = (
        sell_exec is not None
        and sell_exec.get("available") is True
        and sell_exec.get("effectivePrice") is not None
    )

    if not buy_available and not sell_available:
        # No independent market authority; can show basis but no premium.
        return TokenizationPremiumObservation(
            status=TokenizationPremiumStatus.TOKEN_MARKET_REFERENCE_UNAVAILABLE,
            underlying_raw_bid_usd_per_share=raw_bid,
            underlying_raw_ask_usd_per_share=raw_ask,
            underlying_raw_mid_usd_per_share=underlying_mid,
            current_multiplier=current_multiplier,
            underlying_token_basis_usd_per_token=underlying_token_basis,
            buy_execution_price_usd_per_token=None,
            sell_execution_price_usd_per_token=None,
            execution_mid_price_usd_per_token=None,
            tokenization_premium_bps=None,
            buy_execution_premium_bps=None,
            sell_execution_premium_bps=None,
            reference_observed_at=ref_observed_at,
            buy_quote_observed_at=None,
            sell_quote_observed_at=None,
            suppression_reason="NO_INDEPENDENT_DEX_EXECUTION_AVAILABLE",
            raw_evidence={"reference": ref, "buyExecution": buy_exec, "sellExecution": sell_exec},
        )

    # --- parse execution prices and timestamps --------------------------------
    buy_price: Decimal | None = None
    buy_quoted_at: datetime | None = None
    sell_price: Decimal | None = None
    sell_quoted_at: datetime | None = None

    if buy_available:
        try:
            buy_price = _parse_positive_decimal(
                buy_exec.get("effectivePrice"), "buy.effectivePrice"  # type: ignore[union-attr]
            )
            buy_quoted_at = _parse_iso_dt(
                buy_exec.get("quotedAt"), "buy.quotedAt"  # type: ignore[union-attr]
            )
        except ValueError as exc:
            return _suppressed(
                TokenizationPremiumStatus.TOKEN_EXECUTION_UNAVAILABLE,
                f"BUY_EXECUTION_FIELDS_INVALID: {exc}",
                ref=ref, buy_exec=buy_exec, sell_exec=sell_exec,
            )

    if sell_available:
        try:
            sell_price = _parse_positive_decimal(
                sell_exec.get("effectivePrice"), "sell.effectivePrice"  # type: ignore[union-attr]
            )
            sell_quoted_at = _parse_iso_dt(
                sell_exec.get("quotedAt"), "sell.quotedAt"  # type: ignore[union-attr]
            )
        except ValueError as exc:
            return _suppressed(
                TokenizationPremiumStatus.TOKEN_EXECUTION_UNAVAILABLE,
                f"SELL_EXECUTION_FIELDS_INVALID: {exc}",
                ref=ref, buy_exec=buy_exec, sell_exec=sell_exec,
            )

    # --- temporal coherence check ---------------------------------------------
    timestamps: list[datetime] = [ref_observed_at]
    if buy_quoted_at is not None:
        timestamps.append(buy_quoted_at)
    if sell_quoted_at is not None:
        timestamps.append(sell_quoted_at)

    if len(timestamps) >= 2:
        earliest = min(timestamps)
        latest = max(timestamps)
        skew_seconds = (latest - earliest).total_seconds()
        if skew_seconds > policy.max_evidence_skew_seconds:
            return _suppressed(
                TokenizationPremiumStatus.TIME_COHERENCE_VIOLATION,
                f"EVIDENCE_SKEW_{skew_seconds:.0f}s_EXCEEDS_{policy.max_evidence_skew_seconds}s",
                ref=ref, buy_exec=buy_exec, sell_exec=sell_exec,
            )

    # --- compute tokenization premiums vs underlying basis --------------------
    # tokenization_premium_bps = ((execution_mid / underlying_token_basis) - 1) × 10000
    # When execution_mid = underlying_token_basis (unit-conversion only), result = 0 bps.
    buy_exec_premium: Decimal | None = None
    sell_exec_premium: Decimal | None = None
    execution_mid: Decimal | None = None
    tokenization_premium_bps: Decimal | None = None

    if buy_price is not None:
        buy_exec_premium = (
            (buy_price / underlying_token_basis) - Decimal("1")
        ) * Decimal("10000")

    if sell_price is not None:
        sell_exec_premium = (
            (sell_price / underlying_token_basis) - Decimal("1")
        ) * Decimal("10000")

    if buy_price is not None and sell_price is not None:
        execution_mid = (buy_price + sell_price) / Decimal("2")
        tokenization_premium_bps = (
            (execution_mid / underlying_token_basis) - Decimal("1")
        ) * Decimal("10000")

    # --- determine final status ------------------------------------------------
    if buy_price is not None and sell_price is not None:
        status = TokenizationPremiumStatus.TOKENIZATION_PREMIUM_OK
    else:
        # One direction available — directional premium vs basis is computable,
        # but an execution mid cannot be formed.
        status = TokenizationPremiumStatus.EXECUTION_PREMIUM_PARTIAL

    return TokenizationPremiumObservation(
        status=status,
        underlying_raw_bid_usd_per_share=raw_bid,
        underlying_raw_ask_usd_per_share=raw_ask,
        underlying_raw_mid_usd_per_share=underlying_mid,
        current_multiplier=current_multiplier,
        underlying_token_basis_usd_per_token=underlying_token_basis,
        buy_execution_price_usd_per_token=buy_price,
        sell_execution_price_usd_per_token=sell_price,
        execution_mid_price_usd_per_token=execution_mid,
        tokenization_premium_bps=tokenization_premium_bps,
        buy_execution_premium_bps=buy_exec_premium,
        sell_execution_premium_bps=sell_exec_premium,
        reference_observed_at=ref_observed_at,
        buy_quote_observed_at=buy_quoted_at,
        sell_quote_observed_at=sell_quoted_at,
        suppression_reason=None,
        raw_evidence={"reference": ref, "buyExecution": buy_exec, "sellExecution": sell_exec},
    )
