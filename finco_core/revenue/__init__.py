"""finco_core.revenue — Revenue engine extraction (V2-7).

Authoritative implementation. domain.revenue.generation is a compatibility shim.

Public API:
    period_generation
    annual_generation_mwh
    period_revenue
    full_generation_schedule
    full_revenue_schedule
    revenue_decomposition_schedule
"""
from finco_core.revenue.generation import (
    period_generation,
    annual_generation_mwh,
    period_revenue,
    full_generation_schedule,
    full_revenue_schedule,
    revenue_decomposition_schedule,
)

__all__ = [
    "period_generation",
    "annual_generation_mwh",
    "period_revenue",
    "full_generation_schedule",
    "full_revenue_schedule",
    "revenue_decomposition_schedule",
]
