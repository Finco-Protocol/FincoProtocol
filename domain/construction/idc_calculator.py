"""Construction IDC calculation helpers."""

from __future__ import annotations

from datetime import date

from domain.construction.result import ConstructionMonthlyEntry


def compute_full_source_elapsed_compound_idc(
    *,
    source_draw_keur: float,
    annual_rate: float,
    investment_date: date,
    cod_date: date,
    day_count_denominator: float = 365.0,
) -> float:
    """Compute IDC on the full source amount over elapsed construction years."""

    if source_draw_keur < 0:
        raise ValueError("source_draw_keur cannot be negative")
    if annual_rate < 0:
        raise ValueError("annual_rate cannot be negative")
    if cod_date < investment_date:
        raise ValueError("cod_date cannot be before investment_date")
    if day_count_denominator <= 0:
        raise ValueError("day_count_denominator must be positive")

    elapsed_years = (cod_date - investment_date).days / day_count_denominator
    return source_draw_keur * ((1.0 + annual_rate) ** elapsed_years - 1.0)


def compute_senior_monthly_cumulative_idc(
    monthly_entries: tuple[ConstructionMonthlyEntry, ...],
    *,
    senior_interest_rate: float,
    monthly_interest_period_fractions: tuple[float, ...],
    monthly_base_rates: tuple[float, ...] = (),
) -> tuple[float, ...]:
    """Compute senior IDC from prior cumulative senior draw balances."""

    if senior_interest_rate < 0:
        raise ValueError("senior_interest_rate cannot be negative")
    if len(monthly_interest_period_fractions) != len(monthly_entries):
        raise ValueError("monthly_interest_period_fractions length must match entries")
    if monthly_base_rates and len(monthly_base_rates) != len(monthly_entries):
        raise ValueError("monthly_base_rates length must match entries")

    idc_values: list[float] = []
    previous_cumulative_senior = 0.0
    for pos, entry in enumerate(monthly_entries):
        period_fraction = monthly_interest_period_fractions[pos]
        if period_fraction < 0:
            raise ValueError("monthly interest period fractions cannot be negative")
        base_rate = monthly_base_rates[pos] if monthly_base_rates else 0.0
        if base_rate < 0:
            raise ValueError("monthly base rates cannot be negative")
        idc_values.append((senior_interest_rate + base_rate) * previous_cumulative_senior * period_fraction)
        previous_cumulative_senior = entry.cumulative_senior_keur
    return tuple(idc_values)


__all__ = [
    "compute_full_source_elapsed_compound_idc",
    "compute_senior_monthly_cumulative_idc",
]
