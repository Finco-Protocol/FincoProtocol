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


@dataclass(frozen=True)
class PerpAssetSnapshot:
    """One exchange-bound perpetual context.

    Hyperliquid's ``metaAndAssetCtxs`` response does not carry a source
    observation timestamp. ``retrieved_at`` therefore records FINCO retrieval
    time only and must not be presented as exchange observation freshness.
    """

    symbol: str
    mark_price: float
    oracle_price: float
    funding_rate: float
    open_interest_base: float
    day_notional_volume_usd: float
    premium_rate: float | None
    retrieved_at: datetime
    publisher: str
    transport: str
    source_endpoint: str
    source_id: str

    def __post_init__(self) -> None:
        for name in ("symbol", "publisher", "transport", "source_endpoint", "source_id"):
            _required_text(getattr(self, name), name)
        if self.retrieved_at.tzinfo is None or self.retrieved_at.utcoffset() is None:
            raise ValueError("retrieved_at must be timezone-aware")
        for name in (
            "mark_price", "oracle_price", "funding_rate",
            "open_interest_base", "day_notional_volume_usd",
        ):
            _finite(getattr(self, name), name)
        if self.premium_rate is not None:
            _finite(self.premium_rate, "premium_rate")
        if self.mark_price <= 0 or self.oracle_price <= 0:
            raise ValueError("mark_price and oracle_price must be positive")
        if self.open_interest_base < 0 or self.day_notional_volume_usd < 0:
            raise ValueError("open interest and volume cannot be negative")


@dataclass(frozen=True)
class DerivativesSnapshot:
    state: DerivativesState
    assets: tuple[PerpAssetSnapshot, ...]
    retrieved_at: datetime
    publisher: str
    transport: str
    source_endpoint: str
    reason: str | None = None

    def __post_init__(self) -> None:
        for name in ("publisher", "transport", "source_endpoint"):
            _required_text(getattr(self, name), name)
        if self.retrieved_at.tzinfo is None or self.retrieved_at.utcoffset() is None:
            raise ValueError("retrieved_at must be timezone-aware")
        if self.state is DerivativesState.AVAILABLE and not self.assets:
            raise ValueError("AVAILABLE snapshot requires assets")
        if self.state is DerivativesState.UNAVAILABLE and self.assets:
            raise ValueError("UNAVAILABLE snapshot cannot carry assets")
