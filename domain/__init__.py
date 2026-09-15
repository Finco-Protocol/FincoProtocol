"""Domain layer - pure business logic (no Streamlit/pandas dependencies).

This package contains immutable dataclasses representing project finance inputs.
All calculation functions are pure and testable.

Sub-modules:
- analytics: Monte Carlo, LCOE, BESS
- capex: spending profiles, IDC calculation
- financing: debt scheduling, sculpting, covenants
- opex: operational expenditure projections
- returns: XIRR, XNPV calculations
- revenue: generation, tariff calculations
- tax: corporate tax, ATAD, loss carryforward
- waterfall: cash flow waterfall with distribution
"""
from domain.inputs import (
    ProjectInputs,
    ProjectInfo,
    CapexItem,
    CapexStructure,
    OpexItem,
    TechnicalParams,
    RevenueParams,
    FinancingParams,
    TaxParams,
)
from domain.period_engine import PeriodEngine, PeriodMeta

__all__ = [
    # Core inputs
    "ProjectInputs",
    "ProjectInfo",
    "CapexItem",
    "CapexStructure",
    "OpexItem",
    "TechnicalParams",
    "RevenueParams",
    "FinancingParams",
    "TaxParams",
    # Period engine
    "PeriodEngine",
    "PeriodMeta",
]