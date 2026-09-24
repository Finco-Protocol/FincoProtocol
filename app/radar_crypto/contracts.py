"""Typed contracts for FINCO Radar Crypto Overview.

Crypto market intelligence is isolated from the frozen Robinhood/R0-R12
identity and quote authority.  Every normalized observation keeps endpoint,
field identity, publisher, transport and source timestamp explicit.
"""
from __future__ import annotations

import math
from dataclasses import dataclass
from datetime import datetime
from enum import Enum


class CryptoSection(str, Enum):
    MARKET_OVERVIEW = "market-overview"
    MAJOR_ASSETS = "major-assets"


class CryptoState(str, Enum):
    FRESH = "FRESH"
    STALE = "STALE"
    UNAVAILABLE = "UNAVAILABLE"


def _required_text(value: str, name: str) -> str:
    if not isinstance(value, str) or not value.strip():
        raise ValueError(f"{name} must be a non-empty string")
    return value


def _aware(value: datetime, name: str) -> None:
    if value.tzinfo is None or value.utcoffset() is None:
        raise ValueError(f"{name} must be timezone-aware")


@dataclass(frozen=True)
class CryptoMetricDefinition:
    key: str
    title: str
    section: CryptoSection
    source_endpoint: str
    source_id: str
    publisher: str
    transport: str
    source_url: str
    unit: str
    max_staleness_seconds: int = 900

    def __post_init__(self) -> None:
        for name in (
            "key", "title", "source_endpoint", "source_id", "publisher",
            "transport", "source_url", "unit",
        ):
            _required_text(getattr(self, name), name)
        if isinstance(self.max_staleness_seconds, bool) or self.max_staleness_seconds <= 0:
            raise ValueError("max_staleness_seconds must be a positive integer")


@dataclass(frozen=True)
class CryptoObservation:
    key: str
    state: CryptoState
    value: float | None
    change_24h: float | None
    observed_at: datetime | None
    retrieved_at: datetime
    source_endpoint: str
    source_id: str
    publisher: str
    transport: str
    reason: str | None = None

    def __post_init__(self) -> None:
        for name in (
            "key", "source_endpoint", "source_id", "publisher", "transport",
        ):
            _required_text(getattr(self, name), name)
        _aware(self.retrieved_at, "retrieved_at")
        if self.observed_at is not None:
            _aware(self.observed_at, "observed_at")
        for name in ("value", "change_24h"):
            value = getattr(self, name)
            if value is not None and not math.isfinite(value):
                raise ValueError(f"{name} must be finite when present")
        if self.state is CryptoState.UNAVAILABLE:
            if self.value is not None or self.observed_at is not None:
                raise ValueError("UNAVAILABLE observations cannot carry value/timestamp")
        elif self.value is None or self.observed_at is None:
            raise ValueError("available observations require value and observed_at")
