"""Hybrid revenue schedule — delegates to domain/revenue/hybrid.py.

Usage:
    result = hybrid_revenue_schedule(inputs, engine)
    # period_revenues ulazi u ebitda_schedule za run_waterfall()
"""
from __future__ import annotations
from dataclasses import dataclass


@dataclass
class HybridRevenueResult:
    """Semi-annual hybrid revenue by period index."""
    period_revenues: dict[int, float]  # period_index → kEUR
    period_generation: dict[int, float]  # period_index → MWh
    annual_bess_revenue_keur: float
    annual_export_mwh: float
    annual_clipping_pct: float


def hybrid_revenue_schedule(
    inputs,  # ProjectInputs
    engine,  # PeriodEngine
    dispatch_result=None,  # deprecated — LP dispatch not implemented
) -> HybridRevenueResult:
    """Build semi-annual hybrid revenue schedule.

    Uses domain.revenue.hybrid.hybrid_period_revenue() for the computation.
    The dispatch_result parameter is deprecated — LP dispatch engine
    (core.engines) is not yet implemented.

    Revenue per period = (export_mwh × tariff/1000) + bess_arbitrage
    Split semi-annually proportionally by period.day_fraction.
    """
    if dispatch_result is not None:
        raise NotImplementedError(
            "LP dispatch engine (core.engines) is not yet implemented. "
            "Use domain.revenue.hybrid.hybrid_period_revenue() directly."
        )

    from domain.revenue.hybrid import HybridInputs, hybrid_period_revenue

    op_periods = [p for p in engine.periods() if p.is_operation]
    period_revenues: dict[int, float] = {}
    period_generation: dict[int, float] = {}

    # Build HybridInputs from project inputs
    hybrid_inputs = _build_hybrid_inputs(inputs)

    total_bess_rev = 0.0
    total_export_mwh = 0.0
    total_clipping = 0.0

    for period in op_periods:
        df = period.day_fraction

        period_result = hybrid_period_revenue(
            hybrid_inputs,
            generation_mwh=0.0,  # will be computed from technical inputs
            period_day_fraction=df,
            period_year_index=period.year_index,
        )

        period_revenues[period.index] = period_result.total_revenue_keur
        period_generation[period.index] = period_result.clipped_mwh + period_result.exported_mwh
        total_bess_rev += period_result.bess_discharge_revenue_keur + period_result.bess_charge_revenue_keur
        total_export_mwh += period_result.exported_mwh
        total_clipping += period_result.curtailment_mwh

    return HybridRevenueResult(
        period_revenues=period_revenues,
        period_generation=period_generation,
        annual_bess_revenue_keur=total_bess_rev,
        annual_export_mwh=total_export_mwh,
        annual_clipping_pct=total_clipping / sum(period_generation.values()) if period_generation else 0.0,
    )


def _build_hybrid_inputs(inputs) -> "HybridInputs":
    """Build HybridInputs from ProjectInputs."""
    from domain.revenue.hybrid import HybridInputs

    tech = inputs.technical
    rev = inputs.revenue

    return HybridInputs(
        solar_capacity_mw=getattr(tech, 'solar_capacity_mw', 0.0),
        wind_capacity_mw=getattr(tech, 'wind_capacity_mw', 0.0),
        grid_limit_mw=getattr(tech, 'grid_limit_mw', getattr(tech, 'capacity_mw', 9999.0)),
        solar_cf=getattr(tech, 'solar_cf', 0.0),
        wind_cf=getattr(tech, 'wind_cf', 0.0),
        ppa_base_tariff_eur_mwh=getattr(rev, 'ppa_base_tariff_eur_mwh', 0.0),
        ppa_escalation=getattr(rev, 'ppa_escalation', 0.0),
        hybrid_opex_keur=getattr(rev, 'hybrid_opex_keur', 0.0),
    )
