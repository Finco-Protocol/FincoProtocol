"""Typed contracts for FINCO Radar R2 directional gap observations."""
from __future__ import annotations

from contextlib import contextmanager
from dataclasses import dataclass, field
from datetime import datetime
from decimal import Decimal
from enum import Enum
from typing import Any, Iterator, Mapping

from finco_radar.assets.contracts import (
    AssetKey,
    RegistryConflictError,
    RegistryLookupError,
    RegistrySourceError,
    normalize_asset_uid,
    normalize_symbol,
)
from finco_radar.quotes.contracts import QuoteSide


class GapStatus(str, Enum):
    """Typed fail-closed status for each gap computation attempt.

    C5: Materially different authority failures must not collapse to a generic BLOCKED.
    """

    GAP_OK = "GAP_OK"
    REFERENCE_BINDING_FAILED = "REFERENCE_BINDING_FAILED"
    REFERENCE_INVALID = "REFERENCE_INVALID"
    SETTLEMENT_REFERENCE_UNAVAILABLE = "SETTLEMENT_REFERENCE_UNAVAILABLE"
    QUOTE_UNAVAILABLE = "QUOTE_UNAVAILABLE"
    EVIDENCE_TIME_MISMATCH = "EVIDENCE_TIME_MISMATCH"
    NON_FINITE_ECONOMICS = "NON_FINITE_ECONOMICS"


class GapComputationError(ValueError):
    """Raised when a directional gap cannot be computed without guessing.

    Always carries a typed GapStatus so callers can categorize the failure
    without inspecting free-form message text.
    """

    def __init__(self, message: str, status: GapStatus = GapStatus.NON_FINITE_ECONOMICS) -> None:
        super().__init__(message)
        self.status = status


# D2: R1 normalization helpers raise their own exception family. Those types are not part
# of the R2 typed error contract, so without conversion a malformed symbol or UID escapes
# as a raw RegistrySourceError and bypasses GapStatus entirely. Every R2 boundary that
# calls into R1 validation must therefore convert them. R1 itself is never modified.
R1_VALIDATION_ERRORS = (RegistrySourceError, RegistryConflictError, RegistryLookupError)


@contextmanager
def r1_boundary(message: str, status: GapStatus) -> Iterator[None]:
    """Convert R1 validation/source exceptions into typed R2 gap errors.

    GapComputationError is not a member of R1_VALIDATION_ERRORS, so a typed error
    raised inside the block passes through unchanged rather than being relabelled.
    """
    try:
        yield
    except R1_VALIDATION_ERRORS as exc:
        raise GapComputationError(f"{message}: {exc}", status) from exc


class ReferenceSide(str, Enum):
    BID = "BID"
    ASK = "ASK"


@dataclass(frozen=True)
class GapComparisonPolicy:
    """Explicit temporal coherence policy for one R2 comparison.

    C1: R2 must not produce a numeric GAP from arbitrarily asynchronous evidence.
    The policy is caller-supplied — R2 never invents a hidden threshold.

    The comparison clock set must include at minimum:
      reference.generated_at, settlement_reference.observed_at, quote.quoted_at.
    If the maximum pairwise skew exceeds max_evidence_skew_seconds the comparison
    fails with EVIDENCE_TIME_MISMATCH.

    Once R4 exists it may authorize expected-static reference states under a richer
    policy; R2 itself must not guess that today.
    """

    max_evidence_skew_seconds: int

    def __post_init__(self) -> None:
        if self.max_evidence_skew_seconds <= 0:
            raise ValueError("max_evidence_skew_seconds must be positive")


def _positive_finite(value: Decimal, field_name: str) -> Decimal:
    if not value.is_finite() or value <= 0:
        raise GapComputationError(
            f"{field_name} must be positive and finite",
            GapStatus.NON_FINITE_ECONOMICS,
        )
    return value


@dataclass(frozen=True)
class BoundReferencePrice:
    """Official bid/ask bound to one exact canonical deployment.

    C7: The official /prices BID/ASK are raw underlying-equity prices in USD.
    currentMultiplier is the shares-per-token conversion authority from the
    official Robinhood asset registry.  The token-equivalent reference price is:
        raw_reference_price × currentMultiplier
    The multiplier is applied exactly once.  token_bid/ask/midpoint are the
    only correctly scaled values for on-chain token comparisons.
    """

    asset_uid: str
    asset_key: AssetKey
    symbol: str
    raw_bid_usd_per_share: Decimal
    raw_ask_usd_per_share: Decimal
    current_multiplier: Decimal
    currency: str
    generated_at: datetime
    is_trading_halt: bool
    source: str
    raw_evidence: Mapping[str, Any] = field(default_factory=dict)

    def __post_init__(self) -> None:
        # D2: malformed/broken binding identity must surface as a typed R2 failure.
        with r1_boundary(
            "bound reference identity is not valid R1 canonical identity",
            GapStatus.REFERENCE_BINDING_FAILED,
        ):
            object.__setattr__(self, "asset_uid", normalize_asset_uid(self.asset_uid))
            object.__setattr__(self, "symbol", normalize_symbol(self.symbol))
        object.__setattr__(self, "currency", self.currency.strip().upper())
        if self.currency != "USD":
            raise GapComputationError(
                "R2 requires a USD-denominated official reference",
                GapStatus.REFERENCE_INVALID,
            )
        _positive_finite(self.raw_bid_usd_per_share, "raw_bid_usd_per_share")
        _positive_finite(self.raw_ask_usd_per_share, "raw_ask_usd_per_share")
        _positive_finite(self.current_multiplier, "current_multiplier")
        if self.raw_ask_usd_per_share < self.raw_bid_usd_per_share:
            raise GapComputationError(
                "official reference ask must be greater than or equal to bid",
                GapStatus.REFERENCE_INVALID,
            )
        if self.generated_at.tzinfo is None:
            raise GapComputationError(
                "reference generated_at must be timezone-aware",
                GapStatus.EVIDENCE_TIME_MISMATCH,
            )
        if not self.source.strip():
            raise GapComputationError(
                "reference source must be non-empty",
                GapStatus.REFERENCE_INVALID,
            )

    @property
    def token_bid_usd_per_token(self) -> Decimal:
        return self.raw_bid_usd_per_share * self.current_multiplier

    @property
    def token_ask_usd_per_token(self) -> Decimal:
        return self.raw_ask_usd_per_share * self.current_multiplier

    @property
    def token_midpoint_usd_per_token(self) -> Decimal:
        return (self.token_bid_usd_per_token + self.token_ask_usd_per_token) / Decimal("2")

    @property
    def multiplier_formula(self) -> str:
        """C7: Human-readable transformation formula for audit purposes."""
        return (
            f"token_price = raw_equity_price × currentMultiplier; "
            f"BID: {self.raw_bid_usd_per_share} × {self.current_multiplier} = {self.token_bid_usd_per_token}; "
            f"ASK: {self.raw_ask_usd_per_share} × {self.current_multiplier} = {self.token_ask_usd_per_token}"
        )


@dataclass(frozen=True)
class DirectionalGapObservation:
    """One size-specific quote/reference observation; not a trading signal.

    Primary metrics (C3):
      BUY  directional GAP = P_buy  vs multiplier-adjusted ASK
      SELL directional GAP = P_sell vs multiplier-adjusted BID

    Neutral analytics (C3 — secondary, clearly labeled):
      gap_to_mid_bps uses P_ref_mid = (token_bid + token_ask) / 2

    None of these are trading signals.  Quote spread is not realized slippage.
    R3 owns generalized liquidity/all-in-cost scoring.
    """

    asset_uid: str
    asset_key: AssetKey
    side: QuoteSide
    requested_notional_usd: Decimal
    token_amount: Decimal
    settlement_amount_usd: Decimal
    execution_price_usd_per_token: Decimal
    reference_side: ReferenceSide
    reference_price_usd_per_token: Decimal
    gap_bps: Decimal
    gap_to_mid_bps: Decimal  # C3: neutral midpoint comparison
    quote_source: str
    quoted_at: datetime
    reference_generated_at: datetime
    settlement_observed_at: datetime | None  # C1/C2: coherence and reconstruction evidence
    reference_is_trading_halt: bool
    fee_cost_usd: Decimal | None
    gas_cost_usd: Decimal | None
    cost_scope: str = "ROUTE_AMOUNTS_ONLY_FEES_AND_GAS_NOT_ADDED"
    reference_state_authority: str = "R4_NOT_YET_APPLIED"

    def __post_init__(self) -> None:
        # D2: malformed/broken binding identity must surface as a typed R2 failure.
        with r1_boundary(
            "observation asset_uid is not valid R1 canonical identity",
            GapStatus.REFERENCE_BINDING_FAILED,
        ):
            object.__setattr__(self, "asset_uid", normalize_asset_uid(self.asset_uid))
        _positive_finite(self.requested_notional_usd, "requested_notional_usd")
        _positive_finite(self.token_amount, "token_amount")
        _positive_finite(self.settlement_amount_usd, "settlement_amount_usd")
        _positive_finite(self.execution_price_usd_per_token, "execution_price_usd_per_token")
        _positive_finite(self.reference_price_usd_per_token, "reference_price_usd_per_token")
        if not self.gap_bps.is_finite():
            raise GapComputationError(
                "gap_bps must be finite",
                GapStatus.NON_FINITE_ECONOMICS,
            )
        if not self.gap_to_mid_bps.is_finite():
            raise GapComputationError(
                "gap_to_mid_bps must be finite",
                GapStatus.NON_FINITE_ECONOMICS,
            )
        if self.quoted_at.tzinfo is None or self.reference_generated_at.tzinfo is None:
            raise GapComputationError(
                "quote and reference timestamps must be timezone-aware",
                GapStatus.EVIDENCE_TIME_MISMATCH,
            )
        if self.settlement_observed_at is not None and self.settlement_observed_at.tzinfo is None:
            raise GapComputationError(
                "settlement_observed_at must be timezone-aware when present",
                GapStatus.EVIDENCE_TIME_MISMATCH,
            )
        for name, value in (("fee_cost_usd", self.fee_cost_usd), ("gas_cost_usd", self.gas_cost_usd)):
            if value is not None and (not value.is_finite() or value < 0):
                raise GapComputationError(
                    f"{name} must be non-negative and finite when present",
                    GapStatus.NON_FINITE_ECONOMICS,
                )
        if self.side is QuoteSide.BUY and self.reference_side is not ReferenceSide.ASK:
            raise GapComputationError(
                "BUY gap must compare against official ASK",
                GapStatus.REFERENCE_INVALID,
            )
        if self.side is QuoteSide.SELL and self.reference_side is not ReferenceSide.BID:
            raise GapComputationError(
                "SELL gap must compare against official BID",
                GapStatus.REFERENCE_INVALID,
            )
