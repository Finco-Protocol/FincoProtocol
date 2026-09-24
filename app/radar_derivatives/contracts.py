"""Typed contracts for the Radar Crypto Derivatives surface."""
from __future__ import annotations

import math
from dataclasses import dataclass
from datetime import datetime
from enum import Enum


class DerivativesState(str, Enum):
    AVAILABLE = "AVAILABLE"
    UNAVAILABLE = "UNAVAILABLE"


def _required_text(value: str, name: str) -> str:
    if not isinstance(value, str) or not value.strip():
        raise ValueError(f"{name} must be a non-empty string")
    return value


def _finite(value: float, name: str) -> float:
    parsed = float(value)
    if not math.isfinite(parsed):
        raise ValueError(f"{name} must be finite")
    return parsed


def _aware(value: datetime, name: str) -> None:
    if value.tzinfo is None or value.utcoffset() is None:
        raise ValueError(f"{name} must be timezone-aware")


@dataclass(frozen=True)
class PerpAssetSnapshot:
    """One Hyperliquid perpetual context bound through the returned universe index."""

    symbol: str
    mark_price: float
    oracle_price: float
    prev_day_price: float
    mid_price: float | None
    impact_bid_price: float | None
    impact_ask_price: float | None
    funding_rate: float
    open_interest_base: float
    day_notional_volume_usd: float
    premium_rate: float | None
    max_leverage: int
    retrieved_at: datetime
    publisher: str
    transport: str
    source_endpoint: str
    source_id: str

    def __post_init__(self) -> None:
        for name in ("symbol", "publisher", "transport", "source_endpoint", "source_id"):
            _required_text(getattr(self, name), name)
        _aware(self.retrieved_at, "retrieved_at")
        for name in (
            "mark_price",
            "oracle_price",
            "prev_day_price",
            "funding_rate",
            "open_interest_base",
            "day_notional_volume_usd",
        ):
            _finite(getattr(self, name), name)
        for name in ("mid_price", "impact_bid_price", "impact_ask_price", "premium_rate"):
            value = getattr(self, name)
            if value is not None:
                _finite(value, name)
        if self.mark_price <= 0 or self.oracle_price <= 0 or self.prev_day_price <= 0:
            raise ValueError("mark_price, oracle_price and prev_day_price must be positive")
        if self.mid_price is not None and self.mid_price <= 0:
            raise ValueError("mid_price must be positive when present")
        if self.impact_bid_price is not None and self.impact_bid_price <= 0:
            raise ValueError("impact_bid_price must be positive when present")
        if self.impact_ask_price is not None and self.impact_ask_price <= 0:
            raise ValueError("impact_ask_price must be positive when present")
        if (
            self.impact_bid_price is not None
            and self.impact_ask_price is not None
            and self.impact_ask_price < self.impact_bid_price
        ):
            raise ValueError("impact ask cannot be below impact bid")
        if self.open_interest_base < 0 or self.day_notional_volume_usd < 0:
            raise ValueError("open interest and volume cannot be negative")
        if isinstance(self.max_leverage, bool) or self.max_leverage <= 0:
            raise ValueError("max_leverage must be a positive integer")


@dataclass(frozen=True)
class FundingRatePoint:
    symbol: str
    funding_rate: float
    premium_rate: float | None
    observed_at: datetime

    def __post_init__(self) -> None:
        _required_text(self.symbol, "symbol")
        _finite(self.funding_rate, "funding_rate")
        if self.premium_rate is not None:
            _finite(self.premium_rate, "premium_rate")
        _aware(self.observed_at, "observed_at")


@dataclass(frozen=True)
class PredictedFundingRate:
    symbol: str
    venue_code: str
    venue_name: str
    funding_rate: float
    next_funding_at: datetime

    def __post_init__(self) -> None:
        for name in ("symbol", "venue_code", "venue_name"):
            _required_text(getattr(self, name), name)
        _finite(self.funding_rate, "funding_rate")
        _aware(self.next_funding_at, "next_funding_at")


@dataclass(frozen=True)
class DerivativesSnapshot:
    state: DerivativesState
    assets: tuple[PerpAssetSnapshot, ...]
    retrieved_at: datetime
    publisher: str
    transport: str
    source_endpoint: str
    funding_history: tuple[FundingRatePoint, ...] = ()
    predicted_funding: tuple[PredictedFundingRate, ...] = ()
    funding_history_reason: str | None = None
    predicted_funding_reason: str | None = None
    reason: str | None = None

    def __post_init__(self) -> None:
        for name in ("publisher", "transport", "source_endpoint"):
            _required_text(getattr(self, name), name)
        _aware(self.retrieved_at, "retrieved_at")
        if self.state is DerivativesState.AVAILABLE and not self.assets:
            raise ValueError("AVAILABLE snapshot requires assets")
        if self.state is DerivativesState.UNAVAILABLE and self.assets:
            raise ValueError("UNAVAILABLE snapshot cannot carry assets")
