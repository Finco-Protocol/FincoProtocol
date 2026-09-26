"""Presentation-only view model for the P2 tokenization-premium panel.

Formats values already produced by the frozen P2 engine.
Never calculates prices, never derives gaps, never infers availability.
"""
from __future__ import annotations

from decimal import Decimal, InvalidOperation, ROUND_HALF_UP
from typing import Any, Mapping

from finco_radar.tokenization_premium.contracts import (
    TokenizationPremiumObservation,
    TokenizationPremiumPolicy,
    TokenizationPremiumStatus,
)
from finco_radar.tokenization_premium.engine import compute_tokenization_premium

_DISCLAIMER = (
    "OBSERVATION ONLY — not a trading signal, not a recommendation. "
    "Gap values reflect quote vs. reference at the time of the snapshot only."
)


def _fmt_usd(value: Decimal | None) -> str | None:
    if value is None:
        return None
    try:
        rounded = value.quantize(Decimal("0.0001"), rounding=ROUND_HALF_UP)
        return f"${rounded:,.4f}"
    except (InvalidOperation, ValueError):
        return str(value)


def _fmt_bps(value: Decimal | None) -> str | None:
    if value is None:
        return None
    try:
        rounded = value.quantize(Decimal("0.01"), rounding=ROUND_HALF_UP)
        sign = "+" if rounded > 0 else ""
        return f"{sign}{rounded:,.2f} bps"
    except (InvalidOperation, ValueError):
        return str(value)


def _fmt_multiplier(value: Decimal | None) -> str | None:
    if value is None:
        return None
    try:
        return str(value.normalize())
    except (InvalidOperation, ValueError):
        return str(value)


def build_tokenization_premium_view(
    obs: TokenizationPremiumObservation,
) -> dict[str, Any]:
    """Build the token-market panel view from one frozen P2 observation."""
    ok = obs.is_ok()
    ref_ok = obs.reference_premium_available()

    return {
        "available": ok or ref_ok,
        "status": obs.status.value,
        "disclaimer": _DISCLAIMER,
        # Underlying equity reference
        "underlying": {
            "rawBid": _fmt_usd(obs.underlying_raw_bid_usd_per_share),
            "rawAsk": _fmt_usd(obs.underlying_raw_ask_usd_per_share),
            "rawMid": _fmt_usd(obs.underlying_raw_mid_usd_per_share),
        } if ref_ok else None,
        # Token reference (multiplier-adjusted)
        "tokenReference": {
            "bid": _fmt_usd(obs.token_reference_bid_usd_per_token),
            "ask": _fmt_usd(obs.token_reference_ask_usd_per_token),
            "mid": _fmt_usd(obs.token_reference_mid_usd_per_token),
            "multiplier": _fmt_multiplier(obs.current_multiplier),
        } if ref_ok else None,
        # Reference premium
        "referencePremiumBps": _fmt_bps(obs.reference_premium_bps) if ref_ok else None,
        "referencePremiumRaw": str(obs.reference_premium_bps) if ref_ok and obs.reference_premium_bps is not None else None,
        # Execution-adjusted premiums and gaps
        "execution": {
            "buyPrice": _fmt_usd(obs.buy_execution_price_usd_per_token),
            "sellPrice": _fmt_usd(obs.sell_execution_price_usd_per_token),
            "buyPremiumBps": _fmt_bps(obs.buy_execution_premium_bps),
            "sellPremiumBps": _fmt_bps(obs.sell_execution_premium_bps),
            "buyGapBps": _fmt_bps(obs.buy_execution_gap_bps),
            "sellGapBps": _fmt_bps(obs.sell_execution_gap_bps),
        } if ok else None,
        # Timestamps
        "timestamps": {
            "referenceObservedAt": obs.reference_observed_at.isoformat() if obs.reference_observed_at else None,
            "buyQuoteObservedAt": obs.buy_quote_observed_at.isoformat() if obs.buy_quote_observed_at else None,
            "sellQuoteObservedAt": obs.sell_quote_observed_at.isoformat() if obs.sell_quote_observed_at else None,
        },
        # Suppression reason when not OK
        "suppressionReason": obs.suppression_reason,
    }


def compute_p2_view(
    *,
    reference_evidence: Mapping[str, Any],
    buy_exec_evidence: Mapping[str, Any] | None,
    sell_exec_evidence: Mapping[str, Any] | None,
    max_evidence_skew_seconds: int = 300,
) -> dict[str, Any]:
    """Entry point for router.py: compute P2 and return a view dict.

    Keeps all finco_radar imports out of router.py (test_ui_20 contract).
    Never raises — returns a suppressed view dict on any error.
    """
    try:
        policy = TokenizationPremiumPolicy(
            max_evidence_skew_seconds=max_evidence_skew_seconds)
        obs = compute_tokenization_premium(
            reference_evidence=reference_evidence,
            buy_exec_evidence=buy_exec_evidence,
            sell_exec_evidence=sell_exec_evidence,
            policy=policy,
        )
        return build_tokenization_premium_view(obs)
    except Exception:  # noqa: BLE001
        return {
            "available": False,
            "status": "P2_COMPUTE_ERROR",
            "suppressionReason": "INTERNAL_ERROR",
            "disclaimer": _DISCLAIMER,
        }
