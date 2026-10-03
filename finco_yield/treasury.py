"""FINCO Yield Treasury benchmark — 3-month U.S. Treasury (DGS3MO).

Reuses the EXISTING FINCO FRED integration (``app.radar_economy.fred``) with
a Yield-local series definition; the radar Economy registry is untouched so
this stream stays isolated from parallel Radar work.

Missing Treasury evidence (no key, transport failure, stale series) is typed
UNAVAILABLE -- never zero and never a substituted value.  The spread to a
Yield observation exists ONLY when both sides are available and fresh.
"""
from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from decimal import Decimal, InvalidOperation
from typing import Any

from app.radar_economy.contracts import EconomySection, EconomyTransform
from app.radar_economy.fred import FredEconomyProvider
from app.radar_economy.registry import EconomySeriesDefinition

TREASURY_SERIES = EconomySeriesDefinition(
    key="yield_treasury_3mo",
    title="U.S. Treasury 3M (DGS3MO)",
    section=EconomySection.TREASURY_YIELDS,
    source_series_id="DGS3MO",
    publisher="Board of Governors of the Federal Reserve System (US)",
    transport="FRED",
    unit="percent",
    frequency="daily",
    transform=EconomyTransform.LEVEL,
    max_staleness_days=7,   # daily series; a week is the usable ceiling
)

TREASURY_SOURCE = "FRED_DGS3MO"


@dataclass(frozen=True)
class TreasuryObservation:
    """Typed latest 3M Treasury yield (percent) with explicit provenance."""

    state: str                    # AVAILABLE | STALE | UNAVAILABLE
    source: str                   # FRED_DGS3MO when any value exists
    yield_percent: Decimal | None
    period: str | None            # observation date (YYYY-MM-DD)
    retrieved_at: str | None
    reason: str | None = None

    @property
    def usable(self) -> bool:
        """Only a fresh (non-stale) observation may anchor a spread."""
        return self.state == "AVAILABLE" and self.yield_percent is not None


def latest_treasury(provider: FredEconomyProvider | None = None) -> TreasuryObservation:
    """Read the latest DGS3MO observation.  Failures stay typed/UNAVAILABLE."""
    provider = provider or FredEconomyProvider()
    try:
        observation = provider.read(TREASURY_SERIES)
    except Exception as exc:  # transport failure -> typed unavailable
        return TreasuryObservation("UNAVAILABLE", TREASURY_SOURCE, None, None, None,
                                   f"FRED_TRANSPORT_FAILED:{type(exc).__name__}")
    value = _decimal(observation.value)
    if observation.state.name == "FRESH" and value is not None:
        return TreasuryObservation(
            "AVAILABLE", TREASURY_SOURCE, value,
            observation.period.isoformat() if observation.period else None,
            observation.retrieved_at.isoformat() if observation.retrieved_at else None)
    if value is not None:
        return TreasuryObservation(
            "STALE", TREASURY_SOURCE, value,
            observation.period.isoformat() if observation.period else None,
            observation.retrieved_at.isoformat() if observation.retrieved_at else None,
            "TREASURY_SERIES_STALE")
    return TreasuryObservation(
        "UNAVAILABLE", TREASURY_SOURCE, None, None, None,
        observation.state.name if hasattr(observation.state, "name") else "UNAVAILABLE")


def spread_bps(apy_fraction: Decimal, treasury_percent: Decimal) -> Decimal | None:
    """Spread of a Yield APY (fraction, 0.04 == 4%) over the Treasury yield
    (percent, 4.28 == 4.28%), in basis points.  Pure arithmetic; callers own
    the availability/freshness gates."""
    try:
        apy_percent = Decimal(apy_fraction) * Decimal(100)
        return (apy_percent - Decimal(treasury_percent)) * Decimal(100)
    except (InvalidOperation, TypeError):
        return None


def _decimal(value: Any) -> Decimal | None:
    if value is None or isinstance(value, bool):
        return None
    try:
        number = Decimal(str(value))
    except InvalidOperation:
        return None
    return number if number.is_finite() else None
