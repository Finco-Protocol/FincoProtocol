"""Model state - pre-computed schedules shared across all UI pages.

This module provides cached computation of expensive model outputs
(revenue, generation, OPEX) that are used by multiple UI pages.

NOTE: Called from app/cache.py (cached wrapper). No Streamlit imports here.
"""
from dataclasses import dataclass
from typing import Optional

from domain.inputs import ProjectInputs, PeriodFrequency
from domain.period_engine import PeriodEngine


@dataclass(frozen=True)
class ModelState:
    """Pre-computed schedules shared across all UI pages."""
    revenue: dict[int, float]
    generation: dict[int, float]
    opex_annual: dict[int, float]
    periods: list
    op_periods: list
    depreciation_schedule: list[float]


def build_model_state(inputs: ProjectInputs, engine: PeriodEngine) -> ModelState:
    """Build model state with all precomputed schedules.

    NOTE: Cached by app/cache.py (not decorated here). Call via cached wrapper.
    Call it once per inputs/engine change.

    Args:
        inputs: ProjectInputs instance
        engine: PeriodEngine instance

    Returns:
        ModelState with all precomputed schedules
    """
    # Revenue schedule
    from domain.revenue.generation import full_revenue_schedule
    revenue = full_revenue_schedule(inputs, engine)

    # Generation schedule
    from domain.revenue.generation import full_generation_schedule
    generation = full_generation_schedule(inputs, engine)

    # OPEX annual
    from domain.opex.projections import opex_schedule_annual
    opex_annual = opex_schedule_annual(inputs, inputs.info.horizon_years)

    # Depreciation schedule (30-year straight-line for solar)
    dep_per_year = inputs.capex.total_capex / inputs.info.horizon_years
    depreciation_schedule = [dep_per_year] * inputs.info.horizon_years

    # Get periods
    periods = list(engine.periods())
    op_periods = [p for p in periods if p.is_operation]

    return ModelState(
        revenue=revenue,
        generation=generation,
        opex_annual=opex_annual,
        periods=periods,
        op_periods=op_periods,
        depreciation_schedule=depreciation_schedule,
    )