"""Canonical series registry for Radar Economy v1.

FRED is the initial transport because it exposes stable series identifiers and
source metadata.  ``publisher`` remains the originating/source institution so
transport and authority are never conflated.
"""
from __future__ import annotations

from app.radar_economy.contracts import (
    EconomySection,
    EconomySeriesDefinition,
    EconomyTransform,
)

_FRED = "FRED"
_BLS = "U.S. Bureau of Labor Statistics"
_FRB = "Board of Governors of the Federal Reserve System (US)"
_STL_FED = "Federal Reserve Bank of St. Louis"
_NY_FED = "Federal Reserve Bank of New York"
_CHICAGO_FED = "Federal Reserve Bank of Chicago"


SERIES: tuple[EconomySeriesDefinition, ...] = (
    # Inflation
    EconomySeriesDefinition(
        key="cpi_yoy",
        title="CPI YoY",
        section=EconomySection.INFLATION,
        source_series_id="CPIAUCSL",
        publisher=_BLS,
        transport=_FRED,
        unit="percent",
        frequency="monthly",
        transform=EconomyTransform.YOY_PERCENT_CHANGE,
        overview=True,
        max_staleness_days=62,
    ),
    EconomySeriesDefinition(
        key="core_cpi_yoy",
        title="Core CPI YoY",
        section=EconomySection.INFLATION,
        source_series_id="CPILFESL",
        publisher=_BLS,
        transport=_FRED,
        unit="percent",
        frequency="monthly",
        transform=EconomyTransform.YOY_PERCENT_CHANGE,
        max_staleness_days=62,
    ),

    # Treasury curve
    EconomySeriesDefinition(
        key="treasury_2y",
        title="U.S. Treasury 2Y",
        section=EconomySection.TREASURY_YIELDS,
        source_series_id="DGS2",
        publisher=_FRB,
        transport=_FRED,
        unit="percent",
        frequency="daily",
        overview=True,
        max_staleness_days=7,
    ),
    EconomySeriesDefinition(
        key="treasury_10y",
        title="U.S. Treasury 10Y",
        section=EconomySection.TREASURY_YIELDS,
        source_series_id="DGS10",
        publisher=_FRB,
        transport=_FRED,
        unit="percent",
        frequency="daily",
        overview=True,
        max_staleness_days=7,
    ),
    EconomySeriesDefinition(
        key="treasury_30y",
        title="U.S. Treasury 30Y",
        section=EconomySection.TREASURY_YIELDS,
        source_series_id="DGS30",
        publisher=_FRB,
        transport=_FRED,
        unit="percent",
        frequency="daily",
        max_staleness_days=7,
    ),
    EconomySeriesDefinition(
        key="treasury_2s10s",
        title="2s10s Curve",
        section=EconomySection.TREASURY_YIELDS,
        source_series_id="T10Y2Y",
        publisher=_STL_FED,
        transport=_FRED,
        unit="basis_points",
        frequency="daily",
        transform=EconomyTransform.LEVEL_PERCENT_TO_BPS,
        max_staleness_days=7,
    ),

    # Inflation expectations
    EconomySeriesDefinition(
        key="breakeven_5y",
        title="5Y Breakeven Inflation",
        section=EconomySection.INFLATION_EXPECTATIONS,
        source_series_id="T5YIE",
        publisher=_STL_FED,
        transport=_FRED,
        unit="percent",
        frequency="daily",
        overview=True,
        max_staleness_days=7,
    ),
    EconomySeriesDefinition(
        key="breakeven_10y",
        title="10Y Breakeven Inflation",
        section=EconomySection.INFLATION_EXPECTATIONS,
        source_series_id="T10YIE",
        publisher=_STL_FED,
        transport=_FRED,
        unit="percent",
        frequency="daily",
        max_staleness_days=7,
    ),
    EconomySeriesDefinition(
        key="inflation_5y5y",
        title="5Y5Y Inflation Expectation",
        section=EconomySection.INFLATION_EXPECTATIONS,
        source_series_id="T5YIFR",
        publisher=_STL_FED,
        transport=_FRED,
        unit="percent",
        frequency="daily",
        max_staleness_days=7,
    ),

    # Labor market
    EconomySeriesDefinition(
        key="unemployment_rate",
        title="Unemployment Rate",
        section=EconomySection.LABOR_MARKET,
        source_series_id="UNRATE",
        publisher=_BLS,
        transport=_FRED,
        unit="percent",
        frequency="monthly",
        overview=True,
        max_staleness_days=62,
    ),
    EconomySeriesDefinition(
        key="nonfarm_payrolls_change",
        title="Nonfarm Payrolls",
        section=EconomySection.LABOR_MARKET,
        source_series_id="PAYEMS",
        publisher=_BLS,
        transport=_FRED,
        unit="thousand_persons",
        frequency="monthly",
        transform=EconomyTransform.PERIOD_CHANGE,
        max_staleness_days=62,
    ),
    EconomySeriesDefinition(
        key="initial_jobless_claims",
        title="Initial Jobless Claims",
        section=EconomySection.LABOR_MARKET,
        source_series_id="ICSA",
        publisher=_BLS,
        transport=_FRED,
        unit="persons",
        frequency="weekly",
        max_staleness_days=14,
    ),

    # Funding conditions
    EconomySeriesDefinition(
        key="fed_funds_effective",
        title="Effective Fed Funds Rate",
        section=EconomySection.FUNDING_CONDITIONS,
        source_series_id="DFF",
        publisher=_FRB,
        transport=_FRED,
        unit="percent",
        frequency="daily",
        max_staleness_days=7,
    ),
    EconomySeriesDefinition(
        key="sofr",
        title="SOFR",
        section=EconomySection.FUNDING_CONDITIONS,
        source_series_id="SOFR",
        publisher=_NY_FED,
        transport=_FRED,
        unit="percent",
        frequency="daily",
        overview=True,
        max_staleness_days=7,
    ),
    EconomySeriesDefinition(
        key="nfci",
        title="Chicago Fed NFCI",
        section=EconomySection.FUNDING_CONDITIONS,
        source_series_id="NFCI",
        publisher=_CHICAGO_FED,
        transport=_FRED,
        unit="index",
        frequency="weekly",
        max_staleness_days=14,
    ),
)

_BY_KEY = {definition.key: definition for definition in SERIES}

if len(_BY_KEY) != len(SERIES):  # fail fast during import; registry keys are authority material
    raise RuntimeError("Radar Economy registry contains duplicate metric keys")


def get_series(key: str) -> EconomySeriesDefinition:
    try:
        return _BY_KEY[key]
    except KeyError as exc:
        raise KeyError(f"Unknown Radar Economy series: {key!r}") from exc


def series_for_section(section: EconomySection) -> tuple[EconomySeriesDefinition, ...]:
    if section is EconomySection.OVERVIEW:
        return tuple(definition for definition in SERIES if definition.overview)
    return tuple(definition for definition in SERIES if definition.section is section)


def source_url(definition: EconomySeriesDefinition) -> str:
    return f"https://fred.stlouisfed.org/series/{definition.source_series_id}"
