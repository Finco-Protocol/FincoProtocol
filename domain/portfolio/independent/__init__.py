"""Phase 1 MVP: Independent SPV Portfolio Aggregation.

Architecture:
- Each SPV runs through existing single-asset waterfall engine independently
- Per-SPV results are preserved in SPVOutput
- Aggregate summary: sum/min/avg across SPVs
- NO pooled debt sculpting, NO shared financing

Pooled financing (domain/portfolio/waterfall.py) is experimental / Phase 2+.
"""
from domain.portfolio.independent.inputs import (
    DSRFConfig,
    IndependentPortfolioInputs,
    PHASE1_LIMITATIONS,
)
from domain.portfolio.independent.result import (
    SPVOutput,
    IndependentPortfolioResult,
    aggregate_independent_results,
)
from domain.portfolio.independent.runner import (
    run_independent_portfolio,
    SPVWaterfallError,
)

__all__ = [
    # Inputs
    "DSRFConfig",
    "IndependentPortfolioInputs",
    "PHASE1_LIMITATIONS",
    # Results
    "SPVOutput",
    "IndependentPortfolioResult",
    "aggregate_independent_results",
    # Runner
    "run_independent_portfolio",
    "SPVWaterfallError",
]
