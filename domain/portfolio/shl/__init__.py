"""Phase 4A SHL (Subordinated HoldCo Loan) domain — data model, engine, and Phase 4C integration.

No sculpting. No capitalization. No circular funding.
Phase 4C integration layer bridges SHL engine output to portfolio/HoldCo flow.
"""
from __future__ import annotations

from domain.portfolio.shl.inputs import (
    SHLFacility,
    SHLPortfolioInputs,
)
from domain.portfolio.shl.result import (
    SHLPeriodResult,
    SHLFacilityResult,
    SHLPortfolioResult,
)
from domain.portfolio.shl.runner import (
    run_shl_facility,
    run_shl_portfolio,
)
from domain.portfolio.shl.integration import (
    build_shl_period_lookup,
    group_shl_facilities_by_borrower,
    inject_shl_into_waterfall_periods,
    enrich_portfolio_result_with_shl,
)

__all__ = [
    # Inputs
    "SHLFacility",
    "SHLPortfolioInputs",
    # Results
    "SHLPeriodResult",
    "SHLFacilityResult",
    "SHLPortfolioResult",
    # Engine
    "run_shl_facility",
    "run_shl_portfolio",
    # Phase 4C integration
    "build_shl_period_lookup",
    "group_shl_facilities_by_borrower",
    "inject_shl_into_waterfall_periods",
    "enrich_portfolio_result_with_shl",
]
