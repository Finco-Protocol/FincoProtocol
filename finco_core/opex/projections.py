"""OPEX projections - per-year and per-period operational costs.

Each item has:
- Y1 amount in kEUR
- Annual escalation
- Step changes that become the new base from the step year onward

NOTE: This module contains PURE functions only.
Caching is handled in the app layer.

Authoritative location: finco_core.opex.projections (V2-8).
Legacy location: domain.opex.projections (compatibility shim).
"""
from typing import Sequence
from finco_core.inputs import OpexItem, ProjectInputs


def opex_item_amount_at_year(item: OpexItem, year_index: int) -> float:
    """Return one OPEX item amount for a given year.

    `OpexItem.amount_at_year()` historically treated `step_changes` as a one-year
    override only. Excel model step-change rows usually represent a new base
    amount from that year onward. This helper implements that sustained-step
    behavior without changing the frozen input schema.

    Note: percentage_of_opex items are NOT handled here — use opex_year() instead.
    """
    if year_index <= 0:
        return 0.0

    applicable_steps = sorted(
        ((step_year, amount) for step_year, amount in item.step_changes if step_year <= year_index),
        key=lambda pair: pair[0],
    )
    if applicable_steps:
        step_year, step_amount = applicable_steps[-1]
        years_after_step = year_index - step_year
        result = step_amount * (1 + item.annual_inflation) ** years_after_step
    else:
        result = item.y1_amount_keur * (1 + item.annual_inflation) ** (year_index - 1)

    return max(0.0, result)


def opex_year(
    items: Sequence[OpexItem],
    year_index: int,
) -> float:
    """Calculate total OPEX for a given year.

    Handles both fixed-amount and percentage-of-opex contingency items.
    For percentage_of_opex items: amount = pct * sum_of_fixed_items (excl. self).
    This avoids circular dependency by computing fixed items first.
    """
    if year_index <= 0:
        return 0.0

    # First pass: compute fixed amounts for all items
    fixed_amounts = {}
    percentage_items = []

    for item in items:
        if item.percentage_of_opex > 0:
            percentage_items.append(item)
        else:
            fixed_amounts[item.name] = opex_item_amount_at_year(item, year_index)

    # Compute percentage-based items using fixed amounts as base (no self-reference)
    for item in percentage_items:
        # Base = sum of all fixed items (excluding other percentage-based items and self)
        base = sum(fixed_amounts.values())
        fixed_amounts[item.name] = item.percentage_of_opex * base

    return sum(fixed_amounts.values())


def opex_schedule_annual(
    inputs: ProjectInputs,
    horizon_years: int = 30,
) -> dict[int, float]:
    """Generate annual OPEX schedule."""
    schedule = {}

    for year in range(1, horizon_years + 1):
        schedule[year] = opex_year(inputs.opex, year)

    return schedule


def opex_per_mw_y1(
    inputs: ProjectInputs,
) -> float:
    """Calculate OPEX per MW (Y1) in kEUR/MW."""
    opex_y1 = opex_year(inputs.opex, 1)
    return opex_y1 / inputs.technical.capacity_mw


def opex_per_mwh_y1(
    inputs: ProjectInputs,
) -> float:
    """Calculate OPEX per MWh (Y1) in EUR/MWh."""
    opex_y1 = opex_year(inputs.opex, 1)

    hours = inputs.technical.operating_hours_p50
    availability = inputs.technical.combined_availability
    generation_y1_mwh = inputs.technical.capacity_mw * hours * availability

    return (opex_y1 * 1000) / generation_y1_mwh


def opex_schedule_period(
    inputs: ProjectInputs,
    engine,
) -> dict[int, float]:
    """Generate period OPEX schedule using actual period day fractions.

    Dispatch:
    - If inputs.hierarchical_opex_capability is not None, route through the
      generic hierarchical engine (compute_periods checked public API).
    - Otherwise fall back to the legacy flat-item path.

    The capability field is the only dispatch signal.  Project name/code are
    never consulted.
    """
    if inputs.hierarchical_opex_capability is not None:
        return _opex_schedule_period_hierarchical(inputs, engine)
    return _opex_schedule_period_legacy(inputs, engine)


def _opex_schedule_period_legacy(
    inputs: ProjectInputs,
    engine,
) -> dict[int, float]:
    """Legacy flat-item OPEX period schedule."""
    schedule = {}
    annual_schedule = opex_schedule_annual(inputs, inputs.info.horizon_years)

    for period in engine.periods():
        if period.is_operation:
            annual_opex = annual_schedule.get(period.year_index, 0.0)
            schedule[period.index] = annual_opex * period.day_fraction
        else:
            schedule[period.index] = 0.0

    return schedule


def _opex_schedule_period_hierarchical(
    inputs: ProjectInputs,
    engine,
) -> dict[int, float]:
    """Hierarchical-engine OPEX period schedule.

    Uses compute_periods() (the checked public API) which validates all inputs
    and raises OpexInputValidationError on any ERROR-severity issue.
    """
    from finco_core.opex.hierarchical import compute_periods, OpexCalculationContext
    cap = inputs.hierarchical_opex_capability
    ctx = OpexCalculationContext(
        senior_debt_tenor_years=inputs.financing.senior_tenor_years,
        external_annual_series=cap.external_annual_series,
    )
    periods = list(engine.periods())
    period_results = compute_periods(cap.opex_model, ctx, iter(periods))
    hierarchical_by_idx = {r.period_index: r.total_keur for r in period_results}
    result: dict[int, float] = {}
    for period in periods:
        result[period.index] = hierarchical_by_idx.get(period.index, 0.0)
    return result


def opex_breakdown_year(
    inputs: ProjectInputs,
    year_index: int,
) -> dict[str, float]:
    """Get breakdown of OPEX by category for a given year.

    Handles both fixed-amount and percentage_of_opex items.
    """
    if year_index <= 0:
        return {item.name: 0.0 for item in inputs.opex}

    # First pass: compute fixed amounts
    fixed_amounts = {}
    percentage_items = []

    for item in inputs.opex:
        if item.percentage_of_opex > 0:
            percentage_items.append(item)
        else:
            fixed_amounts[item.name] = opex_item_amount_at_year(item, year_index)

    # Compute percentage-based items using fixed amounts as base
    for item in percentage_items:
        base = sum(fixed_amounts.values())
        fixed_amounts[item.name] = item.percentage_of_opex * base

    return fixed_amounts


def total_opex_over_horizon(
    inputs: ProjectInputs,
    horizon_years: int = 30,
    discount_rate: float = 0.0,
) -> float:
    """Calculate total (optionally discounted) OPEX over horizon."""
    total = 0.0
    for year in range(1, horizon_years + 1):
        amount = opex_year(inputs.opex, year)
        if discount_rate > 0:
            amount = amount / ((1 + discount_rate) ** year)
        total += amount
    return total


def opex_growth_rate(
    inputs: ProjectInputs,
    start_year: int = 1,
    end_year: int = 30,
) -> float:
    """Calculate average annual OPEX growth rate."""
    opex_start = opex_year(inputs.opex, start_year)
    opex_end = opex_year(inputs.opex, end_year)

    if opex_start <= 0:
        return 0.0

    years = end_year - start_year
    if years <= 0:
        return 0.0

    return (opex_end / opex_start) ** (1 / years) - 1


__all__ = [
    "opex_item_amount_at_year",
    "opex_year",
    "opex_schedule_annual",
    "opex_per_mw_y1",
    "opex_per_mwh_y1",
    "opex_schedule_period",
    "opex_breakdown_year",
    "total_opex_over_horizon",
    "opex_growth_rate",
]
