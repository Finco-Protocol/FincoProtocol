"""Typed contracts for FINCO Radar economy data.

Economy data is a separate read-only market-intelligence surface.  It does not
reuse or redefine the frozen R0-R12 token identity / quote authority contracts.
Each observation keeps its source series and publisher explicit so the UI can
show provenance instead of presenting an unattributed number.
"""
from __future__ import annotations

import math
from dataclasses import dataclass
from datetime import date, datetime
from enum import Enum


class EconomySection(str, Enum):
    OVERVIEW = "overview"
    TREASURY_YIELDS = "treasury-yields"
    INFLATION = "inflation"
    INFLATION_EXPECTATIONS = "inflation-expectations"
    LABOR_MARKET = "labor-market"
    FUNDING_CONDITIONS = "funding-conditions"


class EconomyTransform(str, Enum):
    LEVEL = "LEVEL"
    YOY_PERCENT_CHANGE = "YOY_PERCENT_CHANGE"
    PERIOD_CHANGE = "PERIOD_CHANGE"
    LEVEL_PERCENT_TO_BPS = "LEVEL_PERCENT_TO_BPS"


class EconomyState(str, Enum):
    FRESH = "FRESH"
    STALE = "STALE"
    UNAVAILABLE = "UNAVAILABLE"


def _required_text(value: str, name: str) -> str:
    if not isinstance(value, str) or not value.strip():
        raise ValueError(f"{name} must be a non-empty string")
    return value


@dataclass(frozen=True)
class EconomySeriesDefinition:
    """One canonical Radar metric definition.

    ``transport`` names how FINCO retrieves the series. ``publisher`` names
    the institution identified by the source metadata.  Keeping these separate
    prevents a transport such as FRED from silently becoming the economic-data
    authority for series originally published by BLS, the Fed, or NY Fed.
    """

    key: str
    title: str
    section: EconomySection
    source_series_id: str
    publisher: str
    transport: str
    unit: str
    frequency: str
    transform: EconomyTransform = EconomyTransform.LEVEL
    overview: bool = False
    max_staleness_days: int = 62

    def __post_init__(self) -> None:
        for name in (
            "key", "title", "source_series_id", "publisher", "transport",
            "unit", "frequency",
        ):
            _required_text(getattr(self, name), name)
        if self.section is EconomySection.OVERVIEW:
            raise ValueError(
                "OVERVIEW is a curated cross-section view, not a primary series section"
            )
        if isinstance(self.max_staleness_days, bool) or self.max_staleness_days <= 0:
            raise ValueError("max_staleness_days must be a positive integer")


@dataclass(frozen=True)
class EconomyObservation:
    """Normalized observation used by Radar Economy UI/API surfaces."""

    key: str
    state: EconomyState
    value: float | None
    previous: float | None
    period: date | None
    retrieved_at: datetime
    source_series_id: str
    publisher: str
    transport: str
    reason: str | None = None

    def __post_init__(self) -> None:
        for name in ("key", "source_series_id", "publisher", "transport"):
            _required_text(getattr(self, name), name)
        if self.retrieved_at.tzinfo is None or self.retrieved_at.utcoffset() is None:
            raise ValueError("retrieved_at must be timezone-aware")
        for name in ("value", "previous"):
            value = getattr(self, name)
            if value is not None and not math.isfinite(value):
                raise ValueError(f"{name} must be finite when present")
        if self.state is EconomyState.UNAVAILABLE and self.value is not None:
            raise ValueError("UNAVAILABLE observations cannot carry a value")
        if self.state is not EconomyState.UNAVAILABLE:
            if self.value is None or self.period is None:
                raise ValueError("available observations require value and period")
