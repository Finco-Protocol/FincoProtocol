"""Presentation-only view model for the P2 tokenization-premium panel.

Formats values already produced by the frozen P2 engine.
Never calculates prices, never derives gaps, never infers availability.
"""
from __future__ import annotations

from decimal import Decimal, InvalidOperation, ROUND_HALF_UP
from typing import Any, Mapping

from finco_radar.tokenization_premium.contracts import (
    ComplementIdentityStatus,
    TokenizationPremiumObservation,
    TokenizationPremiumPolicy,
    TokenizationPremiumStatus,
)
from finco_radar.tokenization_premium.engine import compute_tokenization_premium

# Re-export ComplementIdentityStatus so router.py can import it from this module
# without importing finco_radar directly (test_ui_20 boundary contract).
__all__ = [
    "ComplementIdentityStatus",
    "compute_p2_view",
    "build_tokenization_premium_view",
]

_DISCLAIMER = (
    "OBSERVATION ONLY — not a trading signal, not a recommendation. "
    "Premium values reflect DEX execution vs. underlying-equivalent basis "
    "at the time of the snapshot only."
)

# P2 cross-direction coherence window.
# BUY and SELL execution evidence may come from separate acquisitions
# (complement lookup), so the acceptable skew is wider than R2's
# within-acquisition 120 s bound.
_P2_CROSS_DIRECTION_SKEW_SECONDS = 300


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
    basis_ok = obs.basis_available()
    market_ok = obs.independent_market_available()

    return {
        "available": ok or basis_ok,
        "status": obs.status.value,
        "disclaimer": _DISCLAIMER,
        # Underlying equity reference (unit conversion only; not premium)
        "underlying": {
            "rawBid": _fmt_usd(obs.underlying_raw_bid_usd_per_share),
            "rawAsk": _fmt_usd(obs.underlying_raw_ask_usd_per_share),
            "rawMid": _fmt_usd(obs.underlying_raw_mid_usd_per_share),
            "multiplier": _fmt_multiplier(obs.current_multiplier),
            "tokenBasis": _fmt_usd(obs.underlying_token_basis_usd_per_token),
        } if basis_ok else None,
        # Independent DEX execution prices — labeled by direction always
        "execution": {
            "buyExecutionPrice": _fmt_usd(obs.buy_execution_price_usd_per_token),
            "sellExecutionPrice": _fmt_usd(obs.sell_execution_price_usd_per_token),
            "executionMidPrice": _fmt_usd(obs.execution_mid_price_usd_per_token),
        } if market_ok else None,
        # Tokenization premium: execution mid vs underlying basis (both directions required)
        "tokenizationPremiumBps": _fmt_bps(obs.tokenization_premium_bps) if ok else None,
        "tokenizationPremiumRaw": (
            str(obs.tokenization_premium_bps)
            if ok and obs.tokenization_premium_bps is not None
            else None
        ),
        # Directional premiums: each direction vs underlying basis
        # Labeled by direction (BUY/SELL), not by primary/complement position
        "directionalPremiums": {
            "buyExecutionPremiumBps": _fmt_bps(obs.buy_execution_premium_bps),
            "sellExecutionPremiumBps": _fmt_bps(obs.sell_execution_premium_bps),
        } if market_ok else None,
        # Timestamps
        "timestamps": {
            "referenceObservedAt": (
                obs.reference_observed_at.isoformat() if obs.reference_observed_at else None
            ),
            "buyQuoteObservedAt": (
                obs.buy_quote_observed_at.isoformat() if obs.buy_quote_observed_at else None
            ),
            "sellQuoteObservedAt": (
                obs.sell_quote_observed_at.isoformat() if obs.sell_quote_observed_at else None
            ),
        },
        # Suppression reason when not fully OK
        "suppressionReason": obs.suppression_reason,
    }


def compute_p2_view(
    *,
    reference_evidence: Mapping[str, Any],
    buy_exec_evidence: Mapping[str, Any] | None,
    sell_exec_evidence: Mapping[str, Any] | None,
    complement_identity_status: ComplementIdentityStatus = ComplementIdentityStatus.MATCHED,
    max_evidence_skew_seconds: int = _P2_CROSS_DIRECTION_SKEW_SECONDS,
) -> dict[str, Any]:
    """Entry point for router.py: compute P2 and return a view dict.

    Keeps all finco_radar imports out of router.py (test_ui_20 contract).
    Never raises — returns a suppressed view dict on any error.

    complement_identity_status must be one of ComplementIdentityStatus:
      MATCHED  — complement snapshot verified, evidence consumed.
      ABSENT   — no complement snapshot yet; partial observation is normal.
      MISMATCH — complement snapshot found but identity failed; fails closed.
    """
    try:
        policy = TokenizationPremiumPolicy(
            max_evidence_skew_seconds=max_evidence_skew_seconds)
        obs = compute_tokenization_premium(
            reference_evidence=reference_evidence,
            buy_exec_evidence=buy_exec_evidence,
            sell_exec_evidence=sell_exec_evidence,
            policy=policy,
            complement_identity_status=complement_identity_status,
        )
        return build_tokenization_premium_view(obs)
    except Exception:  # noqa: BLE001
        return {
            "available": False,
            "status": TokenizationPremiumStatus.PRESENTATION_BOUNDARY_ERROR.value,
            "suppressionReason": "INTERNAL_ERROR",
            "disclaimer": _DISCLAIMER,
        }
