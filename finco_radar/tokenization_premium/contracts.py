"""Typed contracts for FINCO Radar P2 tokenization-premium observations.

This module is read-only with respect to all R0–R12 authority surfaces.
It does not duplicate quote normalization, liquidity math, slippage math,
VWAP/effective-price calculation, freshness authority, corporate-action
authority, cross-market pair authority, or hash/lineage authority.

This is NOT a trading system.  Observations are never labelled as signals.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime
from decimal import Decimal
from enum import Enum
from typing import Any, Mapping


class TokenizationPremiumStatus(str, Enum):
    """Typed fail-closed status for each tokenization-premium computation.

    Section T suppression matrix — 12 states.
    Materially different failure modes must not collapse to a single BLOCKED.
    """

    # Full chain available — reference premium AND execution-adjusted premiums.
    TOKENIZATION_PREMIUM_OK = "TOKENIZATION_PREMIUM_OK"
    # Reference premium available; execution evidence unavailable for this run.
    REFERENCE_PREMIUM_OK_EXECUTION_UNAVAILABLE = (
        "REFERENCE_PREMIUM_OK_EXECUTION_UNAVAILABLE"
    )
    # The underlying reference fields are absent or non-numeric.
    UNDERLYING_REFERENCE_INVALID = "UNDERLYING_REFERENCE_INVALID"
    # The underlying reference timestamp indicates staleness beyond policy.
    UNDERLYING_REFERENCE_STALE = "UNDERLYING_REFERENCE_STALE"
    # DEX execution evidence is absent or non-numeric.
    TOKEN_EXECUTION_UNAVAILABLE = "TOKEN_EXECUTION_UNAVAILABLE"
    # A corporate action is unresolved; premium comparison is unreliable.
    CORPORATE_ACTION_UNMIRRORED = "CORPORATE_ACTION_UNMIRRORED"
    # Asset is halted; premium observation is suppressed per policy.
    TRADING_HALTED = "TRADING_HALTED"
    # Reference is not USD-denominated; cross-currency premium is ambiguous.
    CURRENCY_MISMATCH = "CURRENCY_MISMATCH"
    # Multiplier transition is unresolved; scaled reference mid is ambiguous.
    MULTIPLIER_TRANSITION_UNRESOLVED = "MULTIPLIER_TRANSITION_UNRESOLVED"
    # Evidence timestamps are too far apart to compare coherently.
    TIME_COHERENCE_VIOLATION = "TIME_COHERENCE_VIOLATION"
    # Asset identity binding is missing or broken.
    IDENTITY_BINDING_MISSING = "IDENTITY_BINDING_MISSING"
    # Execution quote is outside the freshness window of the reference.
    EXECUTION_QUOTE_STALE = "EXECUTION_QUOTE_STALE"


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
    max_evidence_skew_seconds applies to the pairwise skew between the
    reference timestamp and each execution quote timestamp.
    """

    max_evidence_skew_seconds: int

    def __post_init__(self) -> None:
        if self.max_evidence_skew_seconds <= 0:
            raise ValueError("max_evidence_skew_seconds must be positive")


@dataclass(frozen=True)
class TokenizationPremiumObservation:
    """One tokenization-premium observation.  Not a trading signal.

    Chain (Section Q):
      UNDERLYING → TOKENIZED MARKET → TOKENIZATION PREMIUM → EXECUTION AT SELECTED SIZE

    Reference premium (Section Q):
      reference_premium_bps = ((token_reference_mid / underlying_raw_mid) - 1) × 10000

    Execution-adjusted premium (Section R):
      buy_execution_premium_bps  = ((buy_exec_price  / underlying_raw_mid) - 1) × 10000
      sell_execution_premium_bps = ((sell_exec_price / underlying_raw_mid) - 1) × 10000

    Execution gap (Section R):
      buy_execution_gap_bps  = buy_execution_premium_bps  - reference_premium_bps
      sell_execution_gap_bps = sell_execution_premium_bps - reference_premium_bps

    None of these are trading signals.
    """

    status: TokenizationPremiumStatus

    # Underlying equity reference values (raw, pre-multiplier).
    underlying_raw_bid_usd_per_share: Decimal | None
    underlying_raw_ask_usd_per_share: Decimal | None
    underlying_raw_mid_usd_per_share: Decimal | None

    # Token reference values (multiplier-adjusted).
    token_reference_bid_usd_per_token: Decimal | None
    token_reference_ask_usd_per_token: Decimal | None
    token_reference_mid_usd_per_token: Decimal | None
    current_multiplier: Decimal | None

    # Reference premium — how much the token's official reference exceeds underlying.
    reference_premium_bps: Decimal | None

    # Execution-adjusted premiums (None when execution is unavailable).
    buy_execution_price_usd_per_token: Decimal | None
    sell_execution_price_usd_per_token: Decimal | None
    buy_execution_premium_bps: Decimal | None
    sell_execution_premium_bps: Decimal | None

    # Execution gaps relative to reference premium.
    buy_execution_gap_bps: Decimal | None
    sell_execution_gap_bps: Decimal | None

    # Timestamps used in evidence coherence check.
    reference_observed_at: datetime | None
    buy_quote_observed_at: datetime | None
    sell_quote_observed_at: datetime | None

    # Suppression reason when status is not TOKENIZATION_PREMIUM_OK.
    suppression_reason: str | None = None

    # Raw evidence preserved for audit — never re-parsed for numeric use.
    raw_evidence: Mapping[str, Any] = field(default_factory=dict)

    def is_ok(self) -> bool:
        return self.status is TokenizationPremiumStatus.TOKENIZATION_PREMIUM_OK

    def reference_premium_available(self) -> bool:
        return self.status in (
            TokenizationPremiumStatus.TOKENIZATION_PREMIUM_OK,
            TokenizationPremiumStatus.REFERENCE_PREMIUM_OK_EXECUTION_UNAVAILABLE,
        )
