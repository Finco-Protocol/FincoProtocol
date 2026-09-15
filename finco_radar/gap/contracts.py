"""Typed contracts for FINCO Radar R2 directional gap observations."""
from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime
from decimal import Decimal
from enum import Enum
from typing import Any, Mapping

from finco_radar.assets.contracts import AssetKey, normalize_asset_uid, normalize_symbol
from finco_radar.quotes.contracts import QuoteSide


class GapComputationError(ValueError):
    """Raised when a directional gap cannot be computed without guessing."""


class ReferenceSide(str, Enum):
    BID = "BID"
    ASK = "ASK"


def _positive_finite(value: Decimal, field_name: str) -> Decimal:
    if not value.is_finite() or value <= 0:
        raise GapComputationError(f"{field_name} must be positive and finite")
    return value


@dataclass(frozen=True)
class BoundReferencePrice:
    """Official bid/ask bound to one exact canonical deployment."""

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
        object.__setattr__(self, "asset_uid", normalize_asset_uid(self.asset_uid))
        object.__setattr__(self, "symbol", normalize_symbol(self.symbol))
        object.__setattr__(self, "currency", self.currency.strip().upper())
        if self.currency != "USD":
            raise GapComputationError("R2 requires a USD-denominated official reference")
        _positive_finite(self.raw_bid_usd_per_share, "raw_bid_usd_per_share")
        _positive_finite(self.raw_ask_usd_per_share, "raw_ask_usd_per_share")
        _positive_finite(self.current_multiplier, "current_multiplier")
        if self.raw_ask_usd_per_share < self.raw_bid_usd_per_share:
            raise GapComputationError("official reference ask must be greater than or equal to bid")
        if self.generated_at.tzinfo is None:
            raise GapComputationError("reference generated_at must be timezone-aware")
        if not self.source.strip():
            raise GapComputationError("reference source must be non-empty")

    @property
    def token_bid_usd_per_token(self) -> Decimal:
        return self.raw_bid_usd_per_share * self.current_multiplier

    @property
    def token_ask_usd_per_token(self) -> Decimal:
        return self.raw_ask_usd_per_share * self.current_multiplier

    @property
    def token_midpoint_usd_per_token(self) -> Decimal:
        return (self.token_bid_usd_per_token + self.token_ask_usd_per_token) / Decimal("2")


@dataclass(frozen=True)
class DirectionalGapObservation:
    """One size-specific quote/reference observation; not a trading signal."""

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
    quote_source: str
    quoted_at: datetime
    reference_generated_at: datetime
    reference_is_trading_halt: bool
    fee_cost_usd: Decimal | None
    gas_cost_usd: Decimal | None
    cost_scope: str = "ROUTE_AMOUNTS_ONLY_FEES_AND_GAS_NOT_ADDED"
    reference_state_authority: str = "R4_NOT_YET_APPLIED"

    def __post_init__(self) -> None:
        object.__setattr__(self, "asset_uid", normalize_asset_uid(self.asset_uid))
        _positive_finite(self.requested_notional_usd, "requested_notional_usd")
        _positive_finite(self.token_amount, "token_amount")
        _positive_finite(self.settlement_amount_usd, "settlement_amount_usd")
        _positive_finite(self.execution_price_usd_per_token, "execution_price_usd_per_token")
        _positive_finite(self.reference_price_usd_per_token, "reference_price_usd_per_token")
        if not self.gap_bps.is_finite():
            raise GapComputationError("gap_bps must be finite")
        if self.quoted_at.tzinfo is None or self.reference_generated_at.tzinfo is None:
            raise GapComputationError("quote and reference timestamps must be timezone-aware")
        for name, value in (("fee_cost_usd", self.fee_cost_usd), ("gas_cost_usd", self.gas_cost_usd)):
            if value is not None and (not value.is_finite() or value < 0):
                raise GapComputationError(f"{name} must be non-negative and finite when present")
        if self.side is QuoteSide.BUY and self.reference_side is not ReferenceSide.ASK:
            raise GapComputationError("BUY gap must compare against official ASK")
        if self.side is QuoteSide.SELL and self.reference_side is not ReferenceSide.BID:
            raise GapComputationError("SELL gap must compare against official BID")
