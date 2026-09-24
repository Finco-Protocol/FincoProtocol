"""Read-only dashboard composition for Radar Economy."""
from __future__ import annotations

from concurrent.futures import ThreadPoolExecutor
from datetime import datetime, timezone
from typing import Callable

from app.radar_economy.contracts import EconomyObservation, EconomySection, EconomyState
from app.radar_economy.fred import FredEconomyProvider
from app.radar_economy.registry import SERIES, series_for_section, source_url


_SECTION_TITLES = {
    EconomySection.OVERVIEW: "Economy Overview",
    EconomySection.TREASURY_YIELDS: "Treasury Yields",
    EconomySection.INFLATION: "Inflation",
    EconomySection.INFLATION_EXPECTATIONS: "Inflation Expectations",
    EconomySection.LABOR_MARKET: "Labor Market",
    EconomySection.FUNDING_CONDITIONS: "Funding Conditions",
}


def _display(value: float | None, unit: str) -> str:
    if value is None:
        return "—"
    if unit == "percent":
        return f"{value:.2f}%"
    if unit == "basis_points":
        return f"{value:+.0f} bp"
    if unit == "thousand_persons":
        return f"{value:+,.0f}k"
    if unit == "persons":
        if abs(value) >= 1000:
            return f"{value / 1000:,.0f}k"
        return f"{value:,.0f}"
    if unit == "index":
        return f"{value:.2f}"
    return f"{value:,.2f}"


def _trend(value: float | None, previous: float | None) -> str:
    if value is None or previous is None:
        return "FLAT"
    if value > previous:
        return "UP"
    if value < previous:
        return "DOWN"
    return "FLAT"


def _row(definition, observation: EconomyObservation) -> dict:
    return {
        "key": definition.key,
        "title": definition.title,
        "state": observation.state.value,
        "value": observation.value,
        "value_display": _display(observation.value, definition.unit),
        "previous": observation.previous,
        "previous_display": _display(observation.previous, definition.unit),
        "trend": _trend(observation.value, observation.previous),
        "period": observation.period.isoformat() if observation.period else None,
        "retrieved_at": observation.retrieved_at.isoformat(),
        "frequency": definition.frequency,
        "unit": definition.unit,
        "source_series_id": definition.source_series_id,
        "publisher": definition.publisher,
        "transport": definition.transport,
        "source_url": source_url(definition),
        "reason": observation.reason,
    }


class EconomyDashboardService:
    def __init__(self, provider=None, *, max_workers: int = 6) -> None:
        self.provider = provider or FredEconomyProvider()
        self.max_workers = max_workers

    def _safe_read(self, definition) -> EconomyObservation:
        try:
            observation = self.provider.read(definition)
        except Exception as exc:  # injectable providers must not break the whole dashboard
            now = datetime.now(timezone.utc)
            return EconomyObservation(
                key=definition.key,
                state=EconomyState.UNAVAILABLE,
                value=None,
                previous=None,
                period=None,
                retrieved_at=now,
                source_series_id=definition.source_series_id,
                publisher=definition.publisher,
                transport=definition.transport,
                reason=f"PROVIDER_READ_FAILED:{type(exc).__name__}",
            )
        if (
            observation.key != definition.key
            or observation.source_series_id != definition.source_series_id
            or observation.publisher != definition.publisher
            or observation.transport != definition.transport
        ):
            now = datetime.now(timezone.utc)
            return EconomyObservation(
                key=definition.key,
                state=EconomyState.UNAVAILABLE,
                value=None,
                previous=None,
                period=None,
                retrieved_at=now,
                source_series_id=definition.source_series_id,
                publisher=definition.publisher,
                transport=definition.transport,
                reason="SOURCE_BINDING_MISMATCH",
            )
        return observation

    def read_dashboard(self) -> dict:
        with ThreadPoolExecutor(max_workers=self.max_workers) as pool:
            observations = tuple(pool.map(self._safe_read, SERIES))
        by_key = {observation.key: observation for observation in observations}

        sections = []
        for section in EconomySection:
            definitions = series_for_section(section)
            rows = [_row(definition, by_key[definition.key]) for definition in definitions]
            sections.append({
                "key": section.value,
                "title": _SECTION_TITLES[section],
                "rows": rows,
            })

        states = [observation.state for observation in observations]
        fresh = sum(state is EconomyState.FRESH for state in states)
        stale = sum(state is EconomyState.STALE for state in states)
        unavailable = sum(state is EconomyState.UNAVAILABLE for state in states)
        overall = (
            "STALE" if stale else
            "PARTIAL" if fresh and unavailable else
            "FRESH" if fresh else
            "UNAVAILABLE"
        )
        return {
            "state": overall,
            "metric_count": len(observations),
            "fresh_count": fresh,
            "stale_count": stale,
            "unavailable_count": unavailable,
            "sections": sections,
        }
