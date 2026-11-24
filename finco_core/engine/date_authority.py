"""OD-TIME-01 versioned date authority: ONE canonical bridge from the legacy period grid to dated economics.

Admission (explicit, data-derived, never a display flag): the dated grid/economics are active only for Solar/Wind projects that carry a
version-2 explicit contract book with at least one ABSOLUTE_ANNUAL physical contract (the R04 contract version).  Everything else
keeps the legacy semantics bit-for-bit (absent version == legacy).

The dated axis keeps every legacy row (identity, labels, construction, debt/tax timing) and only adds/truncates the FINAL operating row
so that the grid covers exactly ``[COD, COD + horizon_years)`` (end exclusive, Feb-29 clamp), with no gap and no overlap.
"""
from __future__ import annotations

from datetime import date, timedelta

from finco_core.engine.contractual_calendar import (
    ContractualInterval,
    contractual_generation_for_interval,
    convert_period_meta_to_half_open,
    operating_horizon_interval,
)

DATE_AUTHORITY_VERSION = "OD-TIME-01/v1"
_ADMITTED_TECHNOLOGIES = frozenset({"solar", "wind"})


def date_authority_active_for_config(raw_config_json) -> bool:
    """True only for admitted Solar/Wind contract books with an R04 ABSOLUTE_ANNUAL physical contract."""
    if not raw_config_json:
        return False
    from domain.revenue.multistream_runtime import parse_config

    config = parse_config(raw_config_json)
    if config is None or getattr(config, "technology", None) not in _ADMITTED_TECHNOLOGIES:
        return False
    return bool(getattr(config, "has_absolute_annual_quantity", False))


def date_authority_active(inputs) -> bool:
    return date_authority_active_for_config(getattr(getattr(inputs, "revenue", None), "multistream_config_json", "") or "")


def dated_life_end_exclusive(cod: date, horizon_years: int, raw_config_json) -> date | None:
    """Exclusive end of the contractual operating life for admitted projects, else None (legacy grid)."""
    if not date_authority_active_for_config(raw_config_json):
        return None
    return operating_horizon_interval(cod, int(horizon_years)).end_exclusive


def legacy_operating_intervals(engine, cod: date) -> dict[int, ContractualInterval]:
    """Explicit adapter-boundary conversion: legacy inclusive PeriodMeta labels -> contiguous half-open intervals."""
    out: dict[int, ContractualInterval] = {}
    prev_end = None
    for period in engine.periods():
        if not period.is_operation:
            continue
        out[period.index] = convert_period_meta_to_half_open(period, cod=cod, prev_end_date=prev_end)
        prev_end = period.end_date
    return out


def assert_grid_conserves_operating_life(inputs, engine) -> None:
    """Fail closed unless the grid covers exactly ``[COD, COD + N years)`` with no gap, overlap or phantom row."""
    cod = inputs.info.cod_date
    horizon = operating_horizon_interval(cod, int(inputs.info.horizon_years))
    intervals = list(legacy_operating_intervals(engine, cod).values())
    if not intervals:
        raise ValueError("DATE_AUTHORITY_GRID_LIFE_MISMATCH: the reporting grid has no operating period")
    cursor = cod
    for iv in intervals:
        if iv.start != cursor:
            raise ValueError(f"DATE_AUTHORITY_GRID_LIFE_MISMATCH: gap or overlap at {iv.start.isoformat()} (expected {cursor.isoformat()})")
        cursor = iv.end_exclusive
    if cursor != horizon.end_exclusive:
        raise ValueError(
            f"DATE_AUTHORITY_GRID_LIFE_MISMATCH: the reporting grid ends {cursor.isoformat()} (exclusive) but the contractual operating life "
            f"ends {horizon.end_exclusive.isoformat()}")


def dated_generation_schedule(inputs, engine, selected_hours: float) -> dict[int, float]:
    """Dated generation (MWh) per period index; the generator the P50 cap uses, ``selected_hours`` being the only case input."""
    cod = inputs.info.cod_date
    horizon = operating_horizon_interval(cod, int(inputs.info.horizon_years))
    tech = inputs.technical
    assert_grid_conserves_operating_life(inputs, engine)
    intervals = legacy_operating_intervals(engine, cod)
    schedule: dict[int, float] = {}
    for period in engine.periods():
        iv = intervals.get(period.index)
        if iv is None:
            schedule[period.index] = 0.0
            continue
        mwh, _ = contractual_generation_for_interval(
            iv, cod=cod, capacity_mw=float(tech.capacity_mw), annual_hours=float(selected_hours),
            combined_availability=float(tech.combined_availability), annual_degradation=float(tech.pv_degradation),
            horizon_end_exclusive=horizon.end_exclusive)
        schedule[period.index] = mwh
    return schedule


def dated_opex_schedule(inputs, engine, *, clock: str = "COD_ANNIVERSARY") -> dict[int, float]:
    """Dated OPEX (kEUR) per period index: exact day weights per calendar year, escalation on the explicit clock (default COD anniversary)."""
    from finco_core.engine.contractual_calendar import OpexInflationClock, contractual_opex_for_interval

    cod = inputs.info.cod_date
    horizon = operating_horizon_interval(cod, int(inputs.info.horizon_years))
    intervals = legacy_operating_intervals(engine, cod)
    clock_enum = OpexInflationClock(clock)
    out: dict[int, float] = {}
    for period in engine.periods():
        iv = intervals.get(period.index)
        out[period.index] = 0.0 if iv is None else contractual_opex_for_interval(
            iv, cod=cod, items=inputs.opex, clock=clock_enum, horizon_end_exclusive=horizon.end_exclusive)
    return out


def dated_depreciation_schedule(capex_items, engine, *, cod: date, senior_tenor_years: int) -> dict[int, float]:
    """Straight-line accounting depreciation over each asset's actual in-service life, mapped onto the dated axis rows."""
    from finco_core.engine.contractual_calendar import (
        ContractualReportingPeriod,
        contractual_depreciation_schedule,
        split_by_calendar_years,
    )

    intervals = legacy_operating_intervals(engine, cod)
    ordered = [p for p in engine.periods() if p.is_operation]
    rows = tuple(
        ContractualReportingPeriod(
            index=p.index, operating_period_index=p.operating_period_index, interval=intervals[p.index],
            is_first_stub=(i == 0), is_final_stub=(i == len(ordered) - 1),
            calendar_year_slices=split_by_calendar_years(intervals[p.index]))
        for i, p in enumerate(ordered))
    summary = contractual_depreciation_schedule(capex_items, cod=cod, reporting_periods=rows, senior_tenor_years=senior_tenor_years)
    out = {p.index: 0.0 for p in engine.periods()}
    out.update(summary.period_depreciation_keur)
    return out


def dated_generation_for_interval(inputs, interval: ContractualInterval, selected_hours: float) -> float:
    """Dated generation (MWh) over any sub-interval; identical generator to ``dated_generation_schedule`` (sums exactly across a partition)."""
    cod = inputs.info.cod_date
    tech = inputs.technical
    mwh, _ = contractual_generation_for_interval(
        interval, cod=cod, capacity_mw=float(tech.capacity_mw), annual_hours=float(selected_hours),
        combined_availability=float(tech.combined_availability), annual_degradation=float(tech.pv_degradation),
        horizon_end_exclusive=operating_horizon_interval(cod, int(inputs.info.horizon_years)).end_exclusive)
    return mwh
