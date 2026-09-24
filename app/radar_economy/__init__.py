"""FINCO Radar Economy — read-only macro/economic intelligence surface."""
from app.radar_economy.contracts import (
    EconomyObservation,
    EconomySection,
    EconomySeriesDefinition,
    EconomyState,
    EconomyTransform,
)
from app.radar_economy.registry import SERIES, get_series, series_for_section
from app.radar_economy.service import EconomyDashboardService

__all__ = [
    "EconomyDashboardService",
    "EconomyObservation",
    "EconomySection",
    "EconomySeriesDefinition",
    "EconomyState",
    "EconomyTransform",
    "SERIES",
    "get_series",
    "series_for_section",
]
