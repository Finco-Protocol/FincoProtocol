"""Typed contracts for FINCO Radar P2 tokenization-premium observations.

This module is read-only with respect to all R0–R12 authority surfaces.
It does not duplicate quote normalization, liquidity math, slippage math,
VWAP/effective-price calculation, freshness authority, corporate-action
authority, cross-market pair authority, or hash/lineage authority.

This is NOT a trading system.  Observations are never labelled as signals.

Economic semantic note (Section B / C of Correction A)
-------------------------------------------------------
``currentMultiplier`` (shares per token) is a UNIT CONVERSION, not a
source of tokenization premium.  The underlying-equivalent token basis is:

    underlying_token_basis = raw_underlying_mid × currentMultiplier

This is identical to R2's ``token_midpoint_usd_per_token``.  A comparison
of the R2 reference midpoint against ``raw_underlying_mid`` therefore
produces (multiplier - 1) × 10000 bps — a unit-conversion artefact, NOT
tokenization premium.

Tokenization premium requires an INDEPENDENT market price observation.
The independent authority in the current runtime is the DEX execution
quote: ``evidence["execution"]["effectivePrice"]``.  The midpoint of the
BUY and SELL DEX execution prices is the independent market observation.

Producible suppression states
------------------------------
Only states the engine can actually distinguish from available upstream
authority are declared here (Section F of Correction A).
"""
from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime
from decimal import Decimal
from enum import Enum
from typing import Any, Mapping


class TokenizationPremiumStatus(str, Enum):
    """Typed fail-closed status for each P2 tokenization-premium computation.

    Only states the engine can produce from available upstream authority.
    (Section F, Correction A: no phantom states.)
    """

    # Full chain: both BUY and SELL DEX execution available; execution mid
    # and tokenization premium vs underlying basis are computable.
    TOKENIZATION_PREMIUM_OK = "TOKENIZATION_PREMIUM_OK"

    # One DEX direction available; directional premium vs basis is available
    # but a cross-direction execution mid cannot be formed.
    EXECUTION_PREMIUM_PARTIAL = "EXECUTION_PREMIUM_PARTIAL"

    # No DEX execution data for either direction; underlying basis is shown
    # but no independent market comparison is possible.
    TOKEN_MARKET_REFERENCE_UNAVAILABLE = "TOKEN_MARKET_REFERENCE_UNAVAILABLE"

    # The reference evidence is absent, non-numeric, or internally
    # inconsistent.  Underlying basis cannot be computed.
    UNDERLYING_REFERENCE_INVALID = "UNDERLYING_REFERENCE_INVALID"

    # Reference authority reports a trading halt.  Premium observation is
    # suppressed per policy.
    TRADING_HALTED = "TRADING_HALTED"

    # Evidence timestamps exceed the caller-supplied coherence window.
    # The comparison involves evidence from more than one acquisition, so
    # cross-direction skew can be legitimately wider than within-direction R2.
    TIME_COHERENCE_VIOLATION = "TIME_COHERENCE_VIOLATION"

    # A DEX execution dict is present and reports available=True, but the
    # effectivePrice field is absent, non-numeric, or non-positive.
    TOKEN_EXECUTION_UNAVAILABLE = "TOKEN_EXECUTION_UNAVAILABLE"

    # The complement-direction snapshot does not match the primary snapshot
    # on asset identity (economicAssetUid / chainId / contractAddress /
    # notionalUsd).  The complement's execution evidence is not consumed.
    COMPLEMENT_IDENTITY_MISMATCH = "COMPLEMENT_IDENTITY_MISMATCH"

    # An unexpected error occurred at the compute_p2_view boundary.
    # This is a presentation-layer guard, NOT an economic status.
    PRESENTATION_BOUNDARY_ERROR = "PRESENTATION_BOUNDARY_ERROR"


class TokenizationPremiumError(ValueError):
    """Raised when tokenization premium cannot be computed without guessing.

    Always carries a typed status so callers can categorize the failure.
    """

    def __init__(
        self,
        message: str,
        status: TokenizationPremiumStatus = TokenizationPremiumStatus.UNDERLYING_REFERENCE_INVALID,
    ) -> None:
        super().__init__(message)
        self.status = status


@dataclass(frozen=True)
class TokenizationPremiumPolicy:
    """Explicit temporal coherence policy for one P2 observation.

    The caller supplies the policy; P2 never invents a hidden threshold.

    max_evidence_skew_seconds — maximum acceptable pairwise timestamp skew
    between the reference observedAt and any execution quotedAt.

    Because BUY and SELL execution evidence may come from separate
    acquisitions (the complement lookup), the acceptable skew for P2 is
    necessarily wider than R2's within-acquisition window (120 s).
    The application layer names this policy explicitly.
    """

    max_evidence_skew_seconds: int

    def __post_init__(self) -> None:
        if self.max_evidence_skew_seconds <= 0:
            raise ValueError("max_evidence_skew_seconds must be positive")


@dataclass(frozen=True)
class TokenizationPremiumObservation:
    """One tokenization-premium observation.  Not a trading signal.

    Economic chain (Correction A):

      underlying_token_basis  = underlying_share_mid × currentMultiplier
                              = R2 token_midpoint_usd_per_token

    Independent market authority = DEX execution effectivePrice.

    When both DEX directions are available:

      tokenization_premium_bps
        = ((execution_mid / underlying_token_basis) - 1) × 10000

      where execution_mid = (buy_exec_price + sell_exec_price) / 2

    Directional premiums (single-direction comparison vs basis):

      buy_execution_premium_bps
        = ((buy_exec_price / underlying_token_basis) - 1) × 10000

      sell_execution_premium_bps
        = ((sell_exec_price / underlying_token_basis) - 1) × 10000

    None of these are trading signals.
    """

    status: TokenizationPremiumStatus

    # Underlying equity reference (from R2 BoundReferencePrice, pass-through)
    underlying_raw_bid_usd_per_share: Decimal | None
    underlying_raw_ask_usd_per_share: Decimal | None
    underlying_raw_mid_usd_per_share: Decimal | None
    current_multiplier: Decimal | None

    # Underlying-equivalent token basis (= underlying_mid × multiplier = R2 token_mid)
    underlying_token_basis_usd_per_token: Decimal | None

    # Independent DEX execution prices (from R0 quote authority, pass-through)
    buy_execution_price_usd_per_token: Decimal | None
    sell_execution_price_usd_per_token: Decimal | None
    # Cross-direction execution mid (only when both directions available)
    execution_mid_price_usd_per_token: Decimal | None

    # Tokenization premium — requires independent DEX mid vs underlying basis
    tokenization_premium_bps: Decimal | None

    # Directional premiums: one direction vs underlying basis
    buy_execution_premium_bps: Decimal | None
    sell_execution_premium_bps: Decimal | None

    # Evidence timestamps for coherence audit
    reference_observed_at: datetime | None
    buy_quote_observed_at: datetime | None
    sell_quote_observed_at: datetime | None

    # Suppression reason when status is not OK
    suppression_reason: str | None = None

    # Raw evidence preserved for audit — never re-parsed for numeric use
    raw_evidence: Mapping[str, Any] = field(default_factory=dict)

    def is_ok(self) -> bool:
        return self.status is TokenizationPremiumStatus.TOKENIZATION_PREMIUM_OK

    def basis_available(self) -> bool:
        """True when the underlying token basis is computable."""
        return self.underlying_token_basis_usd_per_token is not None

    def independent_market_available(self) -> bool:
        """True when at least one independent DEX price is available."""
        return (
            self.buy_execution_price_usd_per_token is not None
            or self.sell_execution_price_usd_per_token is not None
        )
