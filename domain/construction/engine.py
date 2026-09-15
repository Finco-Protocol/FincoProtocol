"""Offline construction funding schedule engine."""

from __future__ import annotations

from dataclasses import replace

from domain.construction.capex_schedule import build_monthly_uses, validate_monthly_uses_total
from domain.construction.config import ConstructionConfig
from domain.construction.funding_allocation import allocate_source_waterfall
from domain.construction.idc_calculator import (
    compute_full_source_elapsed_compound_idc,
    compute_senior_monthly_cumulative_idc,
)
from domain.construction.result import ConstructionMonthlyEntry, ConstructionScheduleResult


def compute_construction_schedule(config: ConstructionConfig) -> ConstructionScheduleResult:
    """Compute an offline construction funding bridge without runtime side effects."""

    monthly_uses = build_monthly_uses(config)
    uses_delta = validate_monthly_uses_total(
        monthly_uses,
        config.total_uses_keur,
        tolerance_keur=0.05,
    )
    entries = allocate_source_waterfall(monthly_uses, config.funding_caps, tolerance_keur=0.05)

    senior_idc_values = compute_senior_monthly_cumulative_idc(
        entries,
        senior_interest_rate=config.senior_interest_rate,
        monthly_interest_period_fractions=config.senior_interest_period_fractions,
        monthly_base_rates=config.senior_base_rates,
    )
    entries_with_idc: list[ConstructionMonthlyEntry] = []
    cumulative_senior_idc = 0.0
    for entry, senior_idc in zip(entries, senior_idc_values):
        cumulative_senior_idc += senior_idc
        entries_with_idc.append(
            replace(
                entry,
                senior_idc_keur=senior_idc,
                cumulative_senior_idc_keur=cumulative_senior_idc,
            )
        )

    total_shl_draw = sum(entry.shl_draw_keur for entry in entries_with_idc)
    shl_investment_date = config.shl_investment_date or config.construction_start_date
    total_shl_idc = compute_full_source_elapsed_compound_idc(
        source_draw_keur=total_shl_draw,
        annual_rate=config.shl_interest_rate,
        investment_date=shl_investment_date,
        cod_date=config.cod_date,
        day_count_denominator=config.shl_day_count_denominator,
    )
    total_senior_idc = sum(senior_idc_values)
    total_senior_draw = sum(entry.senior_draw_keur for entry in entries_with_idc)

    opening_shl = total_shl_draw + total_shl_idc if config.shl_idc_capitalized else total_shl_draw
    opening_senior = (
        total_senior_draw + total_senior_idc if config.senior_idc_capitalized else total_senior_draw
    )
    total_funding = sum(
        entry.equity_draw_keur + entry.shl_draw_keur + entry.junior_draw_keur + entry.senior_draw_keur
        for entry in entries_with_idc
    )

    return ConstructionScheduleResult(
        project_code=config.project_code,
        monthly_entries=tuple(entries_with_idc),
        total_uses_keur=sum(monthly_uses),
        total_equity_draw_keur=sum(entry.equity_draw_keur for entry in entries_with_idc),
        total_shl_draw_keur=total_shl_draw,
        total_junior_draw_keur=sum(entry.junior_draw_keur for entry in entries_with_idc),
        total_senior_draw_keur=total_senior_draw,
        total_shl_idc_keur=total_shl_idc,
        total_senior_idc_keur=total_senior_idc,
        opening_shl_balance_keur=opening_shl,
        opening_senior_balance_keur=opening_senior,
        uses_funding_delta_keur=total_funding - sum(monthly_uses) + uses_delta,
        senior_idc_delta_to_target_keur=(
            total_senior_idc - config.senior_idc_target_keur
            if config.senior_idc_target_keur is not None
            else None
        ),
    )


__all__ = ["compute_construction_schedule"]
