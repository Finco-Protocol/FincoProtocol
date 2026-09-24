"""Typed contracts for FINCO Radar real-world-asset market intelligence."""
from __future__ import annotations

import math
from dataclasses import dataclass
from datetime import datetime
from enum import Enum


class RwaAssetType(str, Enum):
    STOCK = "stock"
    COMMODITY = "commodity"
    ETF = "etf"


class RwaAssetState(str, Enum):
    FRESH = "FRESH"
    STALE = "STALE"


class RwaSnapshotState(str, Enum):
    AVAILABLE = "AVAILABLE"
    UNAVAILABLE = "UNAVAILABLE"


def _required_text(value: str, name: str) -> str:
    if not isinstance(value, str) or not value.strip():
        raise ValueError(f"{name} must be a non-empty string")
    return value


def _finite_optional(value: float | None, name: str) -> None:
    if value is not None and not math.isfinite(value):
        raise ValueError(f"{name} must be finite when present")


@dataclass(frozen=True)
class RwaAssetMarket:
    id: str
    symbol: str
    name: str
    asset_type: RwaAssetType
    state: RwaAssetState
    current_price: float | None
    market_cap: float | None
    total_volume: float | None
    price_change_24h: float | None
    price_change_7d: float | None
    price_change_30d: float | None
    observed_at: datetime
    retrieved_at: datetime
    source_endpoint: str = "/rwas/markets"
    publisher: str = "CoinGecko"
    transport: str = "CoinGecko Demo API"

    def __post_init__(self) -> None:
        for name in ("id", "symbol", "name", "source_endpoint", "publisher", "transport"):
            _required_text(getattr(self, name), name)
        for name in (
            "current_price", "market_cap", "total_volume", "price_change_24h",
            "price_change_7d", "price_change_30d",
        ):
            _finite_optional(getattr(self, name), name)
        for name in ("observed_at", "retrieved_at"):
            value = getattr(self, name)
            if value.tzinfo is None or value.utcoffset() is None:
                raise ValueError(f"{name} must be timezone-aware")


@dataclass(frozen=True)
class RwaSnapshot:
    state: RwaSnapshotState
    retrieved_at: datetime
    total_count: int
    stock_count: int
    commodity_count: int
    etf_count: int
    leaders: tuple[RwaAssetMarket, ...]
    stock_leaders: tuple[RwaAssetMarket, ...]
    reason: str | None = None
    list_endpoint: str = "/rwas/list"
    markets_endpoint: str = "/rwas/markets"
    publisher: str = "CoinGecko"
    transport: str = "CoinGecko Demo API"

    def __post_init__(self) -> None:
        if self.retrieved_at.tzinfo is None or self.retrieved_at.utcoffset() is None:
            raise ValueError("retrieved_at must be timezone-aware")
        for name in ("total_count", "stock_count", "commodity_count", "etf_count"):
            value = getattr(self, name)
            if isinstance(value, bool) or value < 0:
                raise ValueError(f"{name} must be a non-negative integer")
        if self.state is RwaSnapshotState.UNAVAILABLE:
            if any((self.total_count, self.stock_count, self.commodity_count, self.etf_count)):
                raise ValueError("UNAVAILABLE snapshots cannot carry universe counts")
            if self.leaders or self.stock_leaders:
                raise ValueError("UNAVAILABLE snapshots cannot carry market rows")
