from datetime import date, datetime, timezone

import pytest

from app.radar_economy.contracts import (
    EconomyObservation,
    EconomySection,
    EconomyState,
)
from app.radar_economy.fred import FredEconomyProvider
from app.radar_economy.registry import SERIES, get_series, series_for_section
from app.radar_economy.service import EconomyDashboardService


NOW = datetime(2026, 9, 24, 12, 0, tzinfo=timezone.utc)


def test_registry_keys_are_unique_and_every_navigation_section_is_populated():
    assert len({definition.key for definition in SERIES}) == len(SERIES)
    assert len({definition.source_series_id for definition in SERIES}) == len(SERIES)

    for section in EconomySection:
        assert series_for_section(section), section


def test_overview_is_curated_from_primary_sections_not_a_duplicate_authority():
    overview = series_for_section(EconomySection.OVERVIEW)
    assert {row.key for row in overview} == {
        "cpi_yoy",
        "treasury_2y",
        "treasury_10y",
        "breakeven_5y",
        "unemployment_rate",
        "sofr",
    }
    assert all(row.section is not EconomySection.OVERVIEW for row in overview)


def test_monthly_yoy_transform_is_computed_from_raw_levels():
    definition = get_series("cpi_yoy")
    rows = [
        (date(2025, 1, 1), 100.0),
        (date(2025, 2, 1), 100.0),
        (date(2025, 3, 1), 101.0),
        (date(2025, 4, 1), 102.0),
        (date(2025, 5, 1), 103.0),
        (date(2025, 6, 1), 104.0),
        (date(2025, 7, 1), 105.0),
        (date(2025, 8, 1), 106.0),
        (date(2025, 9, 1), 107.0),
        (date(2025, 10, 1), 108.0),
        (date(2025, 11, 1), 109.0),
        (date(2025, 12, 1), 110.0),
        (date(2026, 1, 1), 110.0),
        (date(2026, 2, 1), 112.0),
    ]

    value, previous, period = FredEconomyProvider._transform(definition, rows)

    assert value == pytest.approx(12.0)
    assert previous == pytest.approx(10.0)
    assert period == date(2026, 2, 1)


def test_period_change_and_curve_bps_are_derived_without_rounding_source_values():
    payrolls = get_series("nonfarm_payrolls_change")
    value, previous, _ = FredEconomyProvider._transform(
        payrolls,
        [
            (date(2026, 6, 1), 100.0),
            (date(2026, 7, 1), 110.0),
            (date(2026, 8, 1), 125.0),
        ],
    )
    assert value == 15.0
    assert previous == 10.0

    curve = get_series("treasury_2s10s")
    value, previous, _ = FredEconomyProvider._transform(
        curve,
        [(date(2026, 9, 22), 0.40), (date(2026, 9, 23), 0.51)],
    )
    assert value == pytest.approx(51.0)
    assert previous == pytest.approx(40.0)


def test_missing_fred_api_key_fails_closed_without_fabricating_values():
    provider = FredEconomyProvider(api_key="", now=lambda: NOW)
    observation = provider.read(get_series("treasury_10y"))

    assert observation.state is EconomyState.UNAVAILABLE
    assert observation.value is None
    assert observation.reason == "FRED_API_KEY_NOT_CONFIGURED"
    assert observation.source_series_id == "DGS10"


class _BoundFakeProvider:
    def read(self, definition):
        return EconomyObservation(
            key=definition.key,
            state=EconomyState.FRESH,
            value=1.0,
            previous=0.9,
            period=date(2026, 9, 23),
            retrieved_at=NOW,
            source_series_id=definition.source_series_id,
            publisher=definition.publisher,
            transport=definition.transport,
        )


class _WrongSourceProvider(_BoundFakeProvider):
    def read(self, definition):
        observation = super().read(definition)
        return EconomyObservation(
            key=observation.key,
            state=observation.state,
            value=observation.value,
            previous=observation.previous,
            period=observation.period,
            retrieved_at=observation.retrieved_at,
            source_series_id="WRONG_SERIES",
            publisher=observation.publisher,
            transport=observation.transport,
        )


def test_dashboard_keeps_source_binding_and_builds_all_sections():
    dashboard = EconomyDashboardService(provider=_BoundFakeProvider()).read_dashboard()

    assert dashboard["state"] == "FRESH"
    assert dashboard["metric_count"] == len(SERIES)
    assert len(dashboard["sections"]) == len(EconomySection)
    assert dashboard["sections"][0]["key"] == "overview"
    assert dashboard["sections"][0]["rows"][0]["source_series_id"]


def test_dashboard_fails_closed_when_provider_returns_wrong_source_identity():
    dashboard = EconomyDashboardService(provider=_WrongSourceProvider()).read_dashboard()

    assert dashboard["state"] == "UNAVAILABLE"
    assert dashboard["unavailable_count"] == len(SERIES)
    for section in dashboard["sections"]:
        for row in section["rows"]:
            assert row["state"] == "UNAVAILABLE"
            assert row["reason"] == "SOURCE_BINDING_MISMATCH"
