"""Runtime adapter for the offline OPEX line-item engine.

The adapter is deliberately narrow: it supports Generic Wind Reference only and does not import
or depend on the waterfall domain.
"""

from __future__ import annotations

from dataclasses import dataclass

from domain.opex.engine import compute_annual_opex
from domain.opex.result import OpexAnnualResult
from domain.opex.templates.generic_wind_reference import build_generic_wind_reference_opex_template


SUPPORTED_GENERIC_WIND_CODES = {"REF-WIND-B"}


@dataclass(frozen=True)
class RuntimeOpexAdapterResult:
    annual_result: OpexAnnualResult
    annual_schedule_keur: dict[int, float]
    period_schedule_keur: dict[int, float]


def build_runtime_opex_schedule(inputs, engine) -> RuntimeOpexAdapterResult:
    """Build annual and period OPEX schedules for a supported project."""

    project_code = getattr(getattr(inputs, "info", None), "code", "")
    if project_code not in SUPPORTED_GENERIC_WIND_CODES:
        raise ValueError(
            "OPEX line-item runtime engine is only supported for REF-WIND-B; "
            f"got project code {project_code!r}."
        )

    annual_result = compute_annual_opex(
        build_generic_wind_reference_opex_template(),
        years=inputs.info.horizon_years,
    )
    annual_schedule = {
        year_index: annual_result.total_for_year(year_index)
        for year_index in annual_result.years
    }
    period_schedule = {}
    for period in engine.periods():
        if period.is_operation:
            period_schedule[period.index] = annual_schedule.get(period.year_index, 0.0) * period.day_fraction
        else:
            period_schedule[period.index] = 0.0

    return RuntimeOpexAdapterResult(
        annual_result=annual_result,
        annual_schedule_keur=annual_schedule,
        period_schedule_keur=period_schedule,
    )


__all__ = ["RuntimeOpexAdapterResult", "build_runtime_opex_schedule"]
