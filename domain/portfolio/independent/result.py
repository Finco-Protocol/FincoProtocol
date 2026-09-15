"""Phase 1 MVP + Phase 2 DSRF: Independent SPV portfolio result.

No pooled debt sculpting. No shared financing.

DSRF (Phase 2):
- enabled=False: zero impact on distributions, IRR, DSCR
- enabled=True: DSRF cash costs (commitment fee, interest, repayment) reduce
  distributable cash; IRR recalculation deferred.
"""
from __future__ import annotations

import math
from typing import TYPE_CHECKING, Any

from dataclasses import dataclass, field
from typing import Optional

from domain.waterfall.waterfall_engine import WaterfallResult


if TYPE_CHECKING:
    from domain.portfolio.independent.dsrf import DSRFPeriod, DSRFResult


@dataclass(frozen=True)
class SPVOutput:
    """Single SPV output — preserved from independent run."""
    project_code: str
    project_name: str
    # Per-SPV KPIs (IRR from waterfall; not recalculated in Phase 2 Step 3)
    project_irr: float          # unlevered project IRR (%) — from waterfall
    equity_irr: float           # levered equity IRR (%) — from waterfall
    total_revenue_keur: float
    total_ebitda_keur: float
    total_tax_keur: float
    total_senior_ds_keur: float
    # Distribution: original waterfall value OR adjusted (after DSRF cash costs)
    # When DSRF enabled: adjusted = max(0, waterfall_dist - DSRF_costs)
    # When DSRF disabled: same as waterfall distribution
    total_distribution_keur: float
    avg_dscr: float
    min_dscr: float
    # Full period result for audit (None when SPV failed in non-strict mode)
    waterfall_result: Optional[WaterfallResult]
    # Validation warnings from this SPV (if any)
    warnings: tuple[str, ...] = ()

    # Per-period distributions used by HoldCo to avoid double-counting DSRF costs.
    # When DSRF is enabled and aligned: holds DSRF-adjusted distributions per period.
    # When DSRF is disabled or unaligned: empty tuple (HoldCo falls back to
    # waterfall_result.periods[i].distribution_keur per period).
    adjusted_period_distributions_keur: tuple[float, ...] = field(default_factory=tuple)

    # DSRF facility fields (optional, default 0 / empty)
    dsrf_facility_limit_keur: float = 0.0
    dsrf_total_draw_keur: float = 0.0
    dsrf_total_repayment_keur: float = 0.0
    dsrf_commitment_fee_keur: float = 0.0
    dsrf_drawn_interest_keur: float = 0.0
    dsrf_debt_service_support_keur: float = 0.0
    dsrf_drawn_end_keur: float = 0.0
    dsrf_periods: tuple[Any, ...] = ()   # tuple[DSRFPeriod, ...] at runtime

    # DSRF cash impact on distributions
    # Reduction = commitment_fee + drawn_interest + repayment
    # When enabled=False: 0 (zero impact)
    dsrf_distribution_reduction_keur: float = 0.0


@dataclass(frozen=True)
class IndependentPortfolioResult:
    """Result of independent SPV portfolio aggregation. Phase 1 MVP + Phase 2 DSRF.

    Each SPV runs independently. Results are summed/min'd for portfolio KPIs.
    No portfolio-level debt sculpting. No shared financing.

    DSRF Phase 2 Step 3: When enabled=True, total_distribution_keur reflects
    adjusted distributions (waterfall_dist - DSRF_costs). IRR values are
    from the original waterfall and are NOT recalculated in this step.
    """
    portfolio_name: str
    # Per-SPV outputs (preserved)
    spv_outputs: tuple[SPVOutput, ...]

    # Sums across SPVs (adjusted distributions when DSRF enabled)
    total_revenue_keur: float
    total_ebitda_keur: float
    total_tax_keur: float
    total_senior_ds_keur: float
    total_distribution_keur: float  # sum of adjusted distributions

    # DSCR: min = conservative (lenders), avg = unweighted average
    min_dscr: float
    avg_dscr: float

    spv_project_irrs: tuple[float, ...]
    spv_equity_irrs: tuple[float, ...]

    # Unweighted averages — NOT true portfolio XIRR.
    # True portfolio IRR requires all cash-flows aligned and XIRR computed — deferred.
    simple_avg_project_irr: float = 0.0
    simple_avg_equity_irr: float = 0.0

    # DSRF enabled flag (Phase 2)
    dsrf_enabled: bool = False

    # Portfolio-level warnings (deduplicated)
    warnings: tuple[str, ...] = field(default_factory=tuple)

    # DSRF portfolio-level aggregates
    dsrf_facility_limit_keur: float = 0.0
    dsrf_total_draw_keur: float = 0.0
    dsrf_total_repayment_keur: float = 0.0
    dsrf_commitment_fee_keur: float = 0.0
    dsrf_drawn_interest_keur: float = 0.0
    dsrf_debt_service_support_keur: float = 0.0
    dsrf_drawn_end_keur: float = 0.0
    dsrf_periods: tuple[Any, ...] = ()

    # Total DSRF cash cost applied to distributions (sum across SPVs)
    # = commitment_fee + drawn_interest + repayment
    dsrf_distribution_reduction_keur: float = 0.0

    @property
    def num_spvs(self) -> int:
        return len(self.spv_outputs)

    def warning_summary(self) -> str:
        """Human-readable portfolio-level warning summary."""
        if not self.warnings:
            return "No warnings."
        lines = [f"Warnings ({len(self.warnings)}):"]
        for w in self.warnings:
            lines.append(f"  - {w}")
        return "\n".join(lines)


def aggregate_independent_results(
    portfolio_name: str,
    spv_outputs: tuple[SPVOutput, ...],
    dsrf_enabled: bool = False,
    dsrf_result: Optional[Any] = None,
) -> IndependentPortfolioResult:
    """Aggregate per-SPV outputs into portfolio summary.

    Sums: revenue, EBITDA, tax, senior debt service, adjusted distributions.
    Min DSCR = conservative min across SPVs.
    Avg DSCR = unweighted average of per-SPV avg DSCRs.
    Unweighted averages — NOT true portfolio IRR.

    DSRF Phase 2 Step 3: When enabled=True, each SPVOutput.total_distribution_keur
    already contains the DSRF-adjusted distribution (original - DSRF_costs).
    Portfolio total_distribution_keur is the sum of those adjusted values.
    IRR values are from the original waterfall and are NOT recalculated.
    """
    total_rev = sum(s.total_revenue_keur for s in spv_outputs)
    total_ebitda = sum(s.total_ebitda_keur for s in spv_outputs)
    total_tax = sum(s.total_tax_keur for s in spv_outputs)
    total_senior_ds = sum(s.total_senior_ds_keur for s in spv_outputs)
    # total_distribution_keur: sum of adjusted (DSRF-enabled) or original (DSRF-disabled) SPV dists
    total_dist = sum(s.total_distribution_keur for s in spv_outputs)

    min_dscr = min((s.min_dscr for s in spv_outputs if s.min_dscr > 0), default=0.0)
    avg_dscr_vals = [s.avg_dscr for s in spv_outputs if s.avg_dscr > 0]
    avg_dscr = sum(avg_dscr_vals) / len(avg_dscr_vals) if avg_dscr_vals else 0.0

    # All finite IRRs included — 0, positive, and negative — no silent filtering
    project_irrs = [
        s.project_irr
        for s in spv_outputs
        if math.isfinite(s.project_irr)
    ]
    equity_irrs = [
        s.equity_irr
        for s in spv_outputs
        if math.isfinite(s.equity_irr)
    ]

    avg_proj_irr = sum(project_irrs) / len(project_irrs) if project_irrs else 0.0
    avg_eq_irr = sum(equity_irrs) / len(equity_irrs) if equity_irrs else 0.0

    # Deduplicate portfolio-level warnings
    all_warnings: list[str] = []
    for s in spv_outputs:
        for w in s.warnings:
            if w not in all_warnings:
                all_warnings.append(w)

    # DSRF aggregates from dsrf_result (from _aggregate_dsrf_results)
    if dsrf_result is not None:
        dsrf_facility = getattr(dsrf_result, "facility_limit_keur", 0.0)
        dsrf_draw = getattr(dsrf_result, "total_draw_keur", 0.0)
        dsrf_repay = getattr(dsrf_result, "total_repayment_keur", 0.0)
        dsrf_commit = getattr(dsrf_result, "total_commitment_fee_keur", 0.0)
        dsrf_interest = getattr(dsrf_result, "total_drawn_interest_keur", 0.0)
        dsrf_support = getattr(dsrf_result, "total_debt_service_support_keur", 0.0)
        dsrf_drawn_end = getattr(dsrf_result, "drawn_end_keur", 0.0)
        dsrf_periods_out = getattr(dsrf_result, "periods", ())
        dsrf_reduction = dsrf_commit + dsrf_interest + dsrf_repay
    else:
        dsrf_facility = 0.0
        dsrf_draw = 0.0
        dsrf_repay = 0.0
        dsrf_commit = 0.0
        dsrf_interest = 0.0
        dsrf_support = 0.0
        dsrf_drawn_end = 0.0
        dsrf_periods_out = ()
        dsrf_reduction = 0.0

    return IndependentPortfolioResult(
        portfolio_name=portfolio_name,
        spv_outputs=spv_outputs,
        total_revenue_keur=total_rev,
        total_ebitda_keur=total_ebitda,
        total_tax_keur=total_tax,
        total_senior_ds_keur=total_senior_ds,
        total_distribution_keur=total_dist,
        min_dscr=min_dscr,
        avg_dscr=avg_dscr,
        spv_project_irrs=tuple(project_irrs),
        spv_equity_irrs=tuple(equity_irrs),
        simple_avg_project_irr=avg_proj_irr,
        simple_avg_equity_irr=avg_eq_irr,
        dsrf_enabled=dsrf_enabled,
        warnings=tuple(all_warnings),
        dsrf_facility_limit_keur=dsrf_facility,
        dsrf_total_draw_keur=dsrf_draw,
        dsrf_total_repayment_keur=dsrf_repay,
        dsrf_commitment_fee_keur=dsrf_commit,
        dsrf_drawn_interest_keur=dsrf_interest,
        dsrf_debt_service_support_keur=dsrf_support,
        dsrf_drawn_end_keur=dsrf_drawn_end,
        dsrf_periods=tuple(dsrf_periods_out),
        dsrf_distribution_reduction_keur=dsrf_reduction,
    )


__all__ = [
    "SPVOutput",
    "IndependentPortfolioResult",
    "aggregate_independent_results",
]