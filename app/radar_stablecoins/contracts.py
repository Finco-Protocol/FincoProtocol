"""Typed contracts for the Radar Stablecoin liquidity slice."""
from __future__ import annotations

import math
from dataclasses import dataclass
from datetime import datetime
from enum import Enum


class StablecoinState(str, Enum):
    AVAILABLE = "AVAILABLE"
    UNAVAILABLE = "UNAVAILABLE"


def _required(value: str, name: str) -> None:
    if not isinstance(value, str) or not value.strip():
        raise ValueError(f"{name} must be non-empty")


def _finite_optional(value: float | None, name: str) -> None:
    if value is not None and not math.isfinite(value):
        raise ValueError(f"{name} must be finite")


@dataclass(frozen=True)
class StablecoinAssetRecord:
    asset_id: str
    name: str
    symbol: str
    peg_type: str
    current: float
    previous_day: float | None
    previous_week: float | None
    previous_month: float | None
    price: float | None

    def __post_init__(self) -> None:
        for name in ("asset_id", "name", "symbol", "peg_type"):
            _required(getattr(self, name), name)
        for name in ("current", "previous_day", "previous_week", "previous_month", "price"):
            value = getattr(self, name)
            _finite_optional(value, name)
            if value is not None and value < 0:
                raise ValueError(f"{name} cannot be negative")


@dataclass(frozen=True)
class StablecoinSnapshot:
    state: StablecoinState
    retrieved_at: datetime
    assets: tuple[StablecoinAssetRecord, ...]
    publisher: str
    transport: str
    source_endpoint: str
    reason: str | None = None

    def __post_init__(self) -> None:
        for name in ("publisher", "transport", "source_endpoint"):
            _required(getattr(self, name), name)
        if self.retrieved_at.tzinfo is None or self.retrieved_at.utcoffset() is None:
            raise ValueError("retrieved_at must be timezone-aware")
        if self.state is StablecoinState.UNAVAILABLE and self.assets:
            raise ValueError("UNAVAILABLE snapshot cannot contain assets")
        if self.state is StablecoinState.AVAILABLE and not self.assets:
            raise ValueError("AVAILABLE snapshot requires at least one asset")
