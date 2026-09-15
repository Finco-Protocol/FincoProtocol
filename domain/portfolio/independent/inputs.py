"""Phase 1 MVP + Phase 2 DSRF: Independent SPV portfolio aggregation.

Architecture:
- Each SPV runs through the existing single-asset engine independently
- Results are preserved per-SPV and aggregated into summary metrics
- NO shared financing, NO pooled debt sculpting, NO cross-default enforcement

DSRF (Phase 2):
- Optional revolving debt service reserve facility, default disabled
- enabled=False has zero impact on distributions, IRR, or DSCR
- enabled=True attaches DSRF facility schedule per SPV and aggregates
  portfolio totals; distribution/IRR financial impact is deferred to next step

This module is NOT the pooled-financing portfolio path (see domain/portfolio/waterfall.py).
"""
from __future__ import annotations

from dataclasses import dataclass
from typing import Optional

# Re-export the canonical DSRFConfig from the pure engine module.
from domain.portfolio.independent.dsrf import (
    DSRFConfig as _CanonicalDSRFConfig,
)

# Re-export for backward-compatible import from this module
DSRFConfig = _CanonicalDSRFConfig


@dataclass(frozen=True)
class IndependentPortfolioInputs:
    """Independent SPV portfolio — Phase 1 MVP + Phase 2 DSRF.

    Each SPV runs independently through the existing calibrated single-asset engine.
    Results are aggregated into summary metrics.

    NO shared financing. NO pooled debt sculpting. NO cross-default.

    DSRF (Phase 2): dsrf parameter accepts DSRFConfig(enabled=True) to compute
    the revolving facility schedule; distribution impact is deferred.
    """
    # All projects must have unique codes (enforced at ProjectInputs level)
    projects: tuple["ProjectInputs", ...]  # forward reference, resolved at runtime
    portfolio_name: str = "Portfolio"

    # DSRF: optional, default None (disabled)
    # Pass DSRFConfig(enabled=True, sizing_months=6, ...) to activate
    dsrf: Optional[DSRFConfig] = None

    def __post_init__(self):
        if len(self.projects) < 1:
            raise ValueError("Portfolio must contain at least 1 project")
        codes = [p.info.code for p in self.projects]
        if len(set(codes)) != len(codes):
            raise ValueError(f"Project codes must be unique, got: {codes}")


__all__ = [
    "DSRFConfig",
    "IndependentPortfolioInputs",
]


# Kept for backward compatibility with any code that imports PHASE1_LIMITATIONS
PHASE1_LIMITATIONS: str = (
    "Phase 1 MVP: Independent SPV portfolio, no pooled debt sculpting. "
    "DSRF (Phase 2) is optional, default disabled."
)