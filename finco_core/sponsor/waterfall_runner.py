"""Phase 7C-3 — Waterfall allocation runner.

Deterministic waterfall allocation engine.
Pure function: no mutation, no side effects, no I/O.

Tiers (in order):
  1. RETURN_OF_CAPITAL  — repay invested capital
  2. PREFERRED_RETURN  — allocate unpaid preferred return balance
  3. GP_CATCH_UP       — 100% to GP until promote threshold reached
  4. PROMOTE           — proportional split by SponsorShare
  5. RESIDUAL          — residual split by SponsorShare

No forward-looking projections. No distribution allocation. No promote logic.
"""
from __future__ import annotations

from dataclasses import dataclass, field
import math
from typing import Any

from finco_core.sponsor.sponsor_waterfall_tier import (
    SponsorWaterfallTier,
    TierType,
    SponsorShare,
)
from finco_core.sponsor.preferred_return_result import (
    PreferredReturnResult,
)
from finco_core.sponsor.waterfall_allocation_result import (
    TierAllocationEntry,
    PeriodWaterfallResult,
    WaterfallAllocationResult,
)

__all__ = [
    "WaterfallRunnerInputs",
    "run_waterfall",
]


# ── Input type ────────────────────────────────────────────────────────────────

@dataclass(frozen=True)
class WaterfallRunnerInputs:
    """Inputs for waterfall allocation.

    Attributes
    ----------
    tiers : tuple[SponsorWaterfallTier, ...]
        Ordered waterfall tiers sorted by tier_index.
        Typically: [RETURN_OF_CAPITAL, PREFERRED_RETURN, GP_CATCH_UP, PROMOTE, RESIDUAL].
    available_cash_by_period : tuple[float, ...]
        Per-period cash available for waterfall allocation (kEUR).
        Must be non-negative. Length = num_periods.
    pref_result : PreferredReturnResult | None
        Preferred return accrual result from Phase 7C-2.
        Required if any PREFERRED_RETURN tier exists. None otherwise.
    cumulative_invested_by_period : tuple[float, ...]
        Cumulative invested capital by period (kEUR).
        Used for RETURN_OF_CAPITAL tier. Must be non-decreasing.
    num_periods : int
        Number of semiannual periods.

    Notes
    -----
    - Tiers must be sorted by tier_index (enforced in __post_init__)
    - No sponsor cashflow result mutation in this layer
    - No IRR recomputation inside the runner
    """
    tiers: tuple[SponsorWaterfallTier, ...]
    available_cash_by_period: tuple[float, ...]
    pref_result: PreferredReturnResult | None
    cumulative_invested_by_period: tuple[float, ...]
    num_periods: int
    # LP's cumulative preferred return distributions by period (kEUR).
    # Used for GP catch-up threshold: gp_target = promote_rate/(1-promote_rate) × max(0, lp_cum_pref - lp_invested)
    # Optional — required when a GP_CATCH_UP tier is present in multi-investor mode.
    lp_cumulative_pref_by_period: tuple[float, ...] = field(default_factory=tuple)
    # LP's invested capital (committed, kEUR). Used for catch-up threshold in multi-investor mode.
    # Optional — single-investor code falls back to cumulative_invested_by_period[-1].
    lp_invested_capital_keur: float = 0.0

    def __post_init__(self):
        if not isinstance(self.tiers, (list, tuple)):
            raise TypeError("tiers must be tuple")
        object.__setattr__(self, "tiers", tuple(sorted(self.tiers, key=lambda t: t.tier_index)))
        if len(self.tiers) == 0:
            raise ValueError("tiers cannot be empty")
        # Check for duplicate tier_indices
        indices = [t.tier_index for t in self.tiers]
        if len(indices) != len(set(indices)):
            raise ValueError(f"Duplicate tier_index in tiers: {indices}")
        if not isinstance(self.available_cash_by_period, (list, tuple)):
            raise TypeError("available_cash_by_period must be list or tuple")
        object.__setattr__(self, "available_cash_by_period", tuple(self.available_cash_by_period))
        if len(self.available_cash_by_period) != self.num_periods:
            raise ValueError(
                f"available_cash_by_period length ({len(self.available_cash_by_period)}) "
                f"must equal num_periods ({self.num_periods})"
            )
        for i, val in enumerate(self.available_cash_by_period):
            if not isinstance(val, (int, float)):
                raise TypeError(f"available_cash_by_period[{i}] must be float")
            if math.isnan(val) or math.isinf(val):
                raise ValueError(f"available_cash_by_period[{i}] must be finite, got {val}")
            if val < 0:
                raise ValueError(f"available_cash_by_period[{i}] must be >= 0, got {val}")
        if not isinstance(self.cumulative_invested_by_period, (list, tuple)):
            raise TypeError("cumulative_invested_by_period must be list or tuple")
        object.__setattr__(
            self,
            "cumulative_invested_by_period",
            tuple(self.cumulative_invested_by_period),
        )
        if len(self.cumulative_invested_by_period) != self.num_periods:
            raise ValueError(
                f"cumulative_invested_by_period length ({len(self.cumulative_invested_by_period)}) "
                f"must equal num_periods ({self.num_periods})"
            )
        for i, val in enumerate(self.cumulative_invested_by_period):
            if not isinstance(val, (int, float)):
                raise TypeError(f"cumulative_invested_by_period[{i}] must be float")
            if math.isnan(val) or math.isinf(val):
                raise ValueError(f"cumulative_invested_by_period[{i}] must be finite, got {val}")
            if val < 0:
                raise ValueError(f"cumulative_invested_by_period[{i}] must be >= 0, got {val}")
        if not isinstance(self.num_periods, int) or self.num_periods <= 0:
            raise ValueError(f"num_periods must be positive int, got {self.num_periods}")


# ── Allocation helpers ────────────────────────────────────────────────────────

def _allocate_by_shares(
    total: float,
    shares: tuple[SponsorShare, ...],
) -> tuple[tuple[str, float], ...]:
    """Allocate `total` amount proportionally by SponsorShare percentages."""
    if total <= 0.0:
        return tuple((s.sponsor_code, 0.0) for s in shares)
    result = []
    for share in shares:
        amt = total * share.allocation_percentage
        result.append((share.sponsor_code, amt))
    return tuple(result)


def _min(a: float, b: float) -> float:
    return a if a < b else b


# ── Per-tier allocation ────────────────────────────────────────────────────────

def _allocate_return_of_capital(
    tier: SponsorWaterfallTier,
    available: float,
    cumulative_invested: float,
    already_repaid: float,
) -> tuple[float, tuple[tuple[str, float], ...]]:
    """Allocate RETURN_OF_CAPITAL tier.

    Repay invested capital: remaining ROC balance = cumulative_invested - already_repaid.
    Allocate min(available, remaining_roc_balance) to sponsors by share.
    """
    remaining_roc = max(0.0, cumulative_invested - already_repaid)
    allocate_amount = _min(available, remaining_roc)
    per_sponsor = _allocate_by_shares(allocate_amount, tier.sponsor_shares)
    return allocate_amount, per_sponsor


def _allocate_preferred_return(
    tier: SponsorWaterfallTier,
    available: float,
    pref_result: PreferredReturnResult,
    period_index: int,
) -> tuple[float, tuple[tuple[str, float], ...]]:
    """Allocate PREFERRED_RETURN tier.

    Use unpaid_pref_balance_keur from pref_result for this period.
    Allocate min(available, unpaid_pref_balance) to sponsors by share.
    """
    entry = pref_result.entry_for(period_index)
    if entry is None:
        unpaid = 0.0
    else:
        unpaid = max(0.0, entry.unpaid_pref_balance_keur)
    allocate_amount = _min(available, unpaid)
    per_sponsor = _allocate_by_shares(allocate_amount, tier.sponsor_shares)
    return allocate_amount, per_sponsor


def _allocate_gp_catch_up(
    tier: SponsorWaterfallTier,
    available: float,
    promote_threshold_keur: float,
    gp_already_received_keur: float,
) -> tuple[float, tuple[tuple[str, float], ...]]:
    """Allocate GP_CATCH_UP tier.

    GP receives 100% of available cash until gp_already_received >= promote_threshold.
    After threshold, allocation = 0.
    """
    remaining_to_threshold = max(0.0, promote_threshold_keur - gp_already_received_keur)
    if remaining_to_threshold <= 0.0:
        return 0.0, tuple((s.sponsor_code, 0.0) for s in tier.sponsor_shares)
    allocate_amount = _min(available, remaining_to_threshold)
    per_sponsor = _allocate_by_shares(allocate_amount, tier.sponsor_shares)
    return allocate_amount, per_sponsor


def _allocate_promote(
    tier: SponsorWaterfallTier,
    available: float,
) -> tuple[float, tuple[tuple[str, float], ...]]:
    """Allocate PROMOTE tier.

    Proportional split by SponsorShare percentages.
    """
    allocate_amount = available  # all remaining cash goes to promote
    per_sponsor = _allocate_by_shares(allocate_amount, tier.sponsor_shares)
    return allocate_amount, per_sponsor


def _allocate_residual(
    tier: SponsorWaterfallTier,
    available: float,
) -> tuple[float, tuple[tuple[str, float], ...]]:
    """Allocate RESIDUAL tier.

    Proportional split by SponsorShare percentages.
    """
    allocate_amount = available
    per_sponsor = _allocate_by_shares(allocate_amount, tier.sponsor_shares)
    return allocate_amount, per_sponsor


# ── Main runner ───────────────────────────────────────────────────────────────

def run_waterfall(inputs: WaterfallRunnerInputs) -> WaterfallAllocationResult:
    """Run deterministic waterfall allocation across all periods.

    Pure function. No mutation of inputs. Deterministic.

    Parameters
    ----------
    inputs : WaterfallRunnerInputs
        Tiers, cash availability, and preferred return results.

    Returns
    -------
    WaterfallAllocationResult
        Frozen result with per-period per-tier allocation snapshots.

    Cash conservation
    -----------------
    For every period: available_cash = sum(tier_allocations) + remaining_cash
    This is enforced in PeriodWaterfallResult.__post_init__.

    Tier ordering
    ------------
    Tiers are processed in tier_index order (0 → 1 → 2 → ...).
    Unallocated cash from each tier rolls to the next tier.
    """
    tier_by_index = {t.tier_index: t for t in inputs.tiers}
    sorted_tier_indices = sorted(tier_by_index.keys())

    # Cumulative tracking across periods
    cumulative_repaid_roc = {s.sponsor_code: 0.0 for t in inputs.tiers for s in t.sponsor_shares}
    cumulative_gp_received = {s.sponsor_code: 0.0 for t in inputs.tiers for s in t.sponsor_shares}
    cumulative_distributions = {s.sponsor_code: 0.0 for t in inputs.tiers for s in t.sponsor_shares}

    period_results: list[PeriodWaterfallResult] = []

    for p in range(inputs.num_periods):
        available = inputs.available_cash_by_period[p]
        cumulative_invested = inputs.cumulative_invested_by_period[p]

        tier_entries: list[TierAllocationEntry] = []
        remaining = available

        for tier_idx in sorted_tier_indices:
            tier = tier_by_index[tier_idx]

            if tier.tier_type == TierType.RETURN_OF_CAPITAL:
                total_repaid = sum(cumulative_repaid_roc[s] for s in cumulative_repaid_roc)
                alloc, per_sp = _allocate_return_of_capital(
                    tier, remaining, cumulative_invested, total_repaid
                )
                # Update cumulative repaid tracking
                for code, amt in per_sp:
                    cumulative_repaid_roc[code] += amt

            elif tier.tier_type == TierType.PREFERRED_RETURN:
                if inputs.pref_result is None:
                    alloc, per_sp = 0.0, tuple((s.sponsor_code, 0.0) for s in tier.sponsor_shares)
                else:
                    alloc, per_sp = _allocate_preferred_return(
                        tier, remaining, inputs.pref_result, p
                    )

            elif tier.tier_type == TierType.GP_CATCH_UP:
                # promote_threshold: (promote_rate / (1-promote_rate)) × max(0, lp_cum_pref - lp_invested)
                # This is the institutional 8-and-20 carry formula:
                #   GP catches up to (promote_rate/(1-promote_rate)) × LP's preferred return above LP invested capital.
                # lp_cumulative_pref_by_period comes from PreferredReturnAllocation.lp_catch_up_trigger_by_period().
                # Single-investor mode (empty lp_cumulative_pref_by_period): falls back to total invested capital.
                lp_cum_pref_by_period = inputs.lp_cumulative_pref_by_period
                if lp_cum_pref_by_period and p < len(lp_cum_pref_by_period):
                    lp_cum_pref = lp_cum_pref_by_period[p]
                    lp_invested = inputs.lp_invested_capital_keur if inputs.lp_invested_capital_keur else (inputs.cumulative_invested_by_period[-1] if inputs.cumulative_invested_by_period else 0.0)
                    lp_catch_up_trigger = max(0.0, lp_cum_pref - lp_invested)
                    # Extract promote_rate from tier sponsor_shares (GP's allocation % in the CATCH_UP tier)
                    promote_rate = 0.20  # default for 8-and-20
                    for s in tier.sponsor_shares:
                        if s.allocation_percentage > 0 and s.allocation_percentage < 1.0:
                            promote_rate = s.allocation_percentage
                            break
                    # GP's catch-up target: promote_rate/(1-promote_rate) × trigger
                    promote_threshold = (promote_rate / (1.0 - promote_rate)) * lp_catch_up_trigger
                else:
                    # Single-investor fallback: use total invested capital
                    promote_threshold = inputs.cumulative_invested_by_period[-1] if inputs.cumulative_invested_by_period else 0.0
                total_gp_received = sum(cumulative_gp_received.values())
                alloc, per_sp = _allocate_gp_catch_up(
                    tier, remaining, promote_threshold, total_gp_received
                )
                for code, amt in per_sp:
                    cumulative_gp_received[code] += amt

            elif tier.tier_type == TierType.PROMOTE:
                alloc, per_sp = _allocate_promote(tier, remaining)

            elif tier.tier_type == TierType.RESIDUAL:
                alloc, per_sp = _allocate_residual(tier, remaining)

            else:
                alloc = 0.0
                per_sp = tuple((s.sponsor_code, 0.0) for s in tier.sponsor_shares)

            remaining_after = remaining - alloc
            entry = TierAllocationEntry(
                tier_index=tier_idx,
                tier_type=tier.tier_type,
                available_cash_before_tier_keur=remaining,
                allocated_amount_keur=alloc,
                allocated_per_sponsor_keur=per_sp,
                remaining_cash_after_tier_keur=remaining_after,
            )
            tier_entries.append(entry)
            remaining = remaining_after
            # Update cumulative distribution tracker for this period's allocations
            for code, amt in per_sp:
                cumulative_distributions[code] += amt

        total_allocated = sum(e.allocated_amount_keur for e in tier_entries)

        period_result = PeriodWaterfallResult(
            period_index=p,
            available_cash_keur=available,
            tier_entries=tuple(tier_entries),
            total_allocated_keur=total_allocated,
            total_remaining_cash_keur=remaining,
            cumulative_distributions_by_sponsor_keur=tuple(
                sorted(cumulative_distributions.items())
            ),
        )
        period_results.append(period_result)

    return WaterfallAllocationResult(
        investor_id="WATERFALL",
        period_results=tuple(period_results),
        total_allocated_keur=sum(p.total_allocated_keur for p in period_results),
        total_distributions_by_sponsor_keur=tuple(
            sorted(
                {
                    code: sum(
                        e.allocation_for(code)
                        for p in period_results
                        for e in p.tier_entries
                    )
                    for code in {
                        s.sponsor_code
                        for t in inputs.tiers
                        for s in t.sponsor_shares
                    }
                }.items()
            )
        ),
    )
