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
LEGACY_DATE_AUTHORITY_VERSION = "LEGACY_CALENDAR/v0"
_ADMITTED_TECHNOLOGIES = frozenset({"solar", "wind"})


def _explicit_date_authority_version(inputs) -> str | None:
    info = getattr(inputs, "info", None)
    v = getattr(info, "date_authority_version", None) if info is not None else None
    if v is None:
        cal = getattr(inputs, "calendar", None)
        v = getattr(cal, "date_authority_version", None) if cal is not None else None
    return v


def _assert_admitted_technology_for_dated(inputs) -> None:
    tech = getattr(inputs, "technical", None)
    if tech is not None and (getattr(tech, "bess_enabled", False) or getattr(tech, "bess_native_config_json", "")):
        raise ValueError("DATE_AUTHORITY_TECHNOLOGY_UNSUPPORTED: BESS is not admitted to OD-TIME-01/v1")
    info = getattr(inputs, "info", None)
    if info is not None:
        code = str(getattr(info, "code", "") or "").lower()
        name = str(getattr(info, "name", "") or "").lower()
        if any(tok in code or tok in name for tok in ("data center", "data_center", "ev charging", "ev_charging")):
            raise ValueError(
                "DATE_AUTHORITY_TECHNOLOGY_UNSUPPORTED: Data Center / EV Charging require date-native driver adapters"
            )
    rev = getattr(inputs, "revenue", None)
    raw_cfg = getattr(rev, "multistream_config_json", "") or ""
    if raw_cfg:
        from domain.revenue.multistream_runtime import parse_config
        cfg = parse_config(raw_cfg)
        if cfg is not None and getattr(cfg, "technology", None) not in _ADMITTED_TECHNOLOGIES:
            raise ValueError(
                f"DATE_AUTHORITY_TECHNOLOGY_UNSUPPORTED: technology={getattr(cfg, 'technology', None)!r}"
            )


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
    version = _explicit_date_authority_version(inputs)
    if version is not None:
        if version == LEGACY_DATE_AUTHORITY_VERSION:
            return date_authority_active_for_config(
                getattr(getattr(inputs, "revenue", None), "multistream_config_json", "") or ""
            )
        if version != DATE_AUTHORITY_VERSION:
            raise ValueError(f"DATE_AUTHORITY_VERSION_UNSUPPORTED: {version!r}")
        _assert_admitted_technology_for_dated(inputs)
        return True
    return date_authority_active_for_config(getattr(getattr(inputs, "revenue", None), "multistream_config_json", "") or "")


def dated_life_end_exclusive(
    cod: date,
    horizon_years: int,
    raw_config_json="",
    *,
    date_authority_version: str | None = None,
) -> date | None:
    """Exclusive end of the contractual operating life for admitted projects, else None (legacy grid)."""
    if date_authority_version is not None:
        if date_authority_version == DATE_AUTHORITY_VERSION:
            return operating_horizon_interval(cod, int(horizon_years)).end_exclusive
        if date_authority_version != LEGACY_DATE_AUTHORITY_VERSION:
            raise ValueError(f"DATE_AUTHORITY_VERSION_UNSUPPORTED: {date_authority_version!r}")
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


def dated_scalar_revenue_for_period(
    inputs,
    interval: ContractualInterval,
    selected_hours: float,
) -> tuple[dict[str, float], set[int]]:
    """Evaluate legacy/scalar PPA + merchant revenue on an OD-TIME-01 half-open interval.

    Uses ``contractual_ppa_and_merchant_for_interval`` for exact subperiod splitting at
    Jan 1, COD anniversaries, PPA expiry, and contract-anniversary escalation dates.
    Also returns any calendar years with positive merchant generation that precede
    ``market_price_calendar_start_year`` so the caller fails closed consistently.
    """
    from finco_core.engine.contractual_calendar import (
        add_calendar_years,
        contractual_ppa_and_merchant_for_interval,
        operating_year_index,
    )
    from financial_engine.ppa_indexation import PpaIndexationStartPolicy

    cod = inputs.info.cod_date
    horizon = operating_horizon_interval(cod, int(inputs.info.horizon_years))
    rev = inputs.revenue
    tech = inputs.technical

    ppa_years = int(round(float(rev.ppa_term_years)))
    contract_start = cod
    contract_end_exclusive = add_calendar_years(cod, ppa_years) if ppa_years > 0 else cod

    policy = rev.ppa_indexation_start_policy or PpaIndexationStartPolicy.AFTER_FIRST_FULL_OPERATING_YEAR

    # Build exact calendar-year merchant price lookup for every calendar year touched by interval.
    market_price_by_year: dict[int, float] = {}
    cal_prices = rev.market_prices_by_calendar_year_eur_mwh
    cal_start = rev.market_price_calendar_start_year
    for yr in range(interval.start.year, interval.end_exclusive.year + 1):
        op_yr = operating_year_index(cod, max(cod, date(yr, 1, 1)))
        market_price_by_year[yr] = float(
            rev.market_price_for_period(period_end_year=yr, operating_year=op_yr)
        )

    totals, slices = contractual_ppa_and_merchant_for_interval(
        interval,
        cod=cod,
        capacity_mw=float(tech.capacity_mw),
        annual_hours=float(selected_hours),
        combined_availability=float(tech.combined_availability),
        annual_degradation=float(tech.pv_degradation),
        ppa_base_tariff_eur_mwh=float(rev.ppa_base_tariff),
        ppa_index=float(rev.ppa_index),
        ppa_share=float(rev.ppa_production_share),
        ppa_policy=policy,
        contract_start=contract_start,
        contract_end_exclusive=contract_end_exclusive,
        market_price_by_year=market_price_by_year,
        ppa_indexation_start_date=rev.ppa_indexation_start_date,
        horizon_end_exclusive=horizon.end_exclusive,
    )

    missing_merchant_years: set[int] = set()
    if cal_prices and cal_start is not None:
        for sl in slices:
            sl_year = sl.interval.start.year
            if sl.merchant_mwh > 0.0 and sl_year < cal_start:
                missing_merchant_years.add(sl_year)

    # When only a relative operating-year merchant curve is present (no calendar-year table),
    # price each COD-anniversary-split slice at its exact contractual operating year.
    if not cal_prices:
        merch_rev = 0.0
        merch_prices = set()
        for sl in slices:
            if sl.merchant_mwh > 0.0:
                op_yr = operating_year_index(cod, sl.interval.start)
                mp = float(rev.market_price_for_period(period_end_year=sl.interval.start.year, operating_year=op_yr))
                merch_rev += sl.merchant_mwh * mp / 1000.0
                merch_prices.add(mp)
        totals["merchant_revenue_keur"] = merch_rev
        totals["energy_revenue_keur"] = totals["ppa_revenue_keur"] + merch_rev
    else:
        merch_prices = {market_price_by_year[sl.interval.start.year] for sl in slices if sl.merchant_mwh > 0.0}

    ppa_tariffs = {sl.ppa_tariff_eur_mwh for sl in slices if sl.ppa_mwh > 0.0}
    totals["ppa_tariff_eur_mwh"] = (
        next(iter(ppa_tariffs))
        if len(ppa_tariffs) == 1
        else (totals["ppa_revenue_keur"] * 1000.0 / totals["ppa_mwh"] if totals["ppa_mwh"] > 0 else 0.0)
    )
    totals["market_price_eur_mwh"] = (
        next(iter(merch_prices))
        if len(merch_prices) == 1
        else (totals["merchant_revenue_keur"] * 1000.0 / totals["merchant_mwh"] if totals["merchant_mwh"] > 0 else 0.0)
    )
    totals["is_ppa_active"] = totals["ppa_mwh"] > 0.0
    return totals, missing_merchant_years

