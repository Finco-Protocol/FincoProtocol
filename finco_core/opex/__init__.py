"""finco_core.opex — OPEX projection engine (V2-8).

Authoritative implementation. domain.opex.projections is a compatibility shim.

Public API:
    opex_item_amount_at_year
    opex_year
    opex_schedule_annual
    opex_per_mw_y1
    opex_per_mwh_y1
    opex_schedule_period
    opex_breakdown_year
    total_opex_over_horizon
    opex_growth_rate
"""
from finco_core.opex.projections import (
    opex_item_amount_at_year,
    opex_year,
    opex_schedule_annual,
    opex_per_mw_y1,
    opex_per_mwh_y1,
    opex_schedule_period,
    opex_breakdown_year,
    total_opex_over_horizon,
    opex_growth_rate,
)

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
