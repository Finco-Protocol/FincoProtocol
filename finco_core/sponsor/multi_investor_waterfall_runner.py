"""Phase 7D-3 — Multi-investor waterfall runner.

Runs the full multi-investor waterfall using Phase 7C waterfall runner as the
core engine. Produces per-investor preferred return results, aggregate
waterfall allocation result, and per-investor tier-annotated capital accounts.

Architecture (Institutional 8-and-20 Cascade)
──────────────────────────────────────────────
The waterfall uses the institutional 8-and-20 carry cascade:

  Tier 0: RETURN_OF_CAPITAL — proportional (LP×80%, GP×20%)
  Tier 1: GP_CATCH_UP — 100% to GP until threshold = (promote_rate/(1-promote_rate))×LP_accrued_pref
  Tier 2: PROMOTE — LP×80%, GP×20% of remainder
  Tier 3: RESIDUAL — LP×80%, GP×20% of any remaining

PREFERRED_RETURN is computed per-investor (Step 1) and included in per-investor
results — it is NOT in the aggregate cascade. The aggregate handles [ROC, GP_CATCH_UP,
PROMOTE, RESIDUAL].

GP catch-up formula:
  gp_catch_up_target = (promote_rate / (1-promote_rate)) × max(0, lp_cumulative_pref - lp_invested)

PreferredReturnAllocation provides lp_cumulative_pref_by_period for the GP catch-up
threshold computation.

Immutable. Deterministic. Pure function. No mutation of Phase 7C results.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

from finco_core.sponsor.investor_registry import (
    InvestorRole,
    InvestorEntry,
    InvestorRegistry,
)
from finco_core.sponsor.capital_stack import (
    CapitalStack,
    CapitalContributionEntry,
)
from finco_core.sponsor.sponsor_waterfall_tier import (
    TierType,
    CompoundingConvention,
    SponsorShare,
    SponsorWaterfallTier,
)
from finco_core.sponsor.preferred_return_calculator import (
    PreferredReturnCalculatorInputs,
    calculate_preferred_return,
)
from finco_core.sponsor.preferred_return_result import (
    PreferredReturnResult,
)
from finco_core.sponsor.waterfall_runner import (
    WaterfallRunnerInputs,
    run_waterfall,
)
from finco_core.sponsor.waterfall_allocation_result import (
    WaterfallAllocationResult,
    TierAllocationEntry,
    PeriodWaterfallResult,
)
from finco_core.sponsor.capital_account_tier_annotation import (
    TierAnnotatedSponsorCapitalAccount,
    from_waterfall_allocation_result,
)

__all__ = [
    "MultiInvestorWaterfallInputs",
    "PerInvestorPreferredReturnInputs",
    "PerInvestorWaterfallInputs",
    "PerInvestorWaterfallResult",
    "MultiInvestorWaterfallResult",
    "run_multi_investor_waterfall",
]


# ── Input Schemas ─────────────────────────────────────────────────────────────

@dataclass(frozen=True)
class PerInvestorPreferredReturnInputs:
    """Per-investor preferred return inputs for the multi-investor waterfall."""
    investor_id: str
    investor_entry: InvestorEntry
    contribution: CapitalContributionEntry
    hurdle_rate_pa: float
    compounding_convention: CompoundingConvention
    gp_promote_share: float

    def __post_init__(self):
        if not isinstance(self.investor_entry, InvestorEntry):
            raise TypeError("investor_entry must be InvestorEntry")
        if not isinstance(self.contribution, CapitalContributionEntry):
            raise TypeError("contribution must be CapitalContributionEntry")
        if not isinstance(self.compounding_convention, CompoundingConvention):
            raise TypeError(
                f"compounding_convention must be CompoundingConvention, "
                f"got {type(self.compounding_convention).__name__}"
            )
        for name, val in [
            ("hurdle_rate_pa", self.hurdle_rate_pa),
            ("gp_promote_share", self.gp_promote_share),
        ]:
            if not isinstance(val, (int, float)):
                raise TypeError(f"{name} must be float, got {type(val).__name__}")
            if val < 0.0:
                raise ValueError(f"{name} must be >= 0, got {val}")


@dataclass(frozen=True)
class PerInvestorWaterfallInputs:
    """Per-investor waterfall inputs for a single investor's tier set."""
    investor_id: str
    ownership_pct: float
    contribution: CapitalContributionEntry
    pref_result: PreferredReturnResult | None = None


@dataclass(frozen=True)
class MultiInvestorWaterfallInputs:
    """Complete multi-investor waterfall inputs.

    Attributes
    ----------
    capital_stack : CapitalStack
        Validated multi-investor capital stack.
    registry : InvestorRegistry
        Investor registry.
    hurdle_rate_pa : float
        Annual preferred return hurdle rate for all investors (decimal).
    compounding_convention : CompoundingConvention
        Compounding convention for preferred return accrual.
    gp_promote_share : float
        GP's promote/carry ownership percentage (decimal, e.g. 0.20 for 20%).
        Must be > 0.
    available_cash_by_period : tuple[float, ...]
        Available cash for distribution by period (kEUR).
    metadata : tuple[tuple[str, Any], ...]
        Frozen key-value metadata.
    """
    capital_stack: CapitalStack
    registry: InvestorRegistry
    hurdle_rate_pa: float
    compounding_convention: CompoundingConvention
    gp_promote_share: float
    available_cash_by_period: tuple[float, ...]
    metadata: tuple[tuple[str, Any], ...] = field(default_factory=tuple)

    def __post_init__(self):
        import math
        if not isinstance(self.capital_stack, CapitalStack):
            raise TypeError("capital_stack must be CapitalStack")
        if not isinstance(self.registry, InvestorRegistry):
            raise TypeError("registry must be InvestorRegistry")
        if not isinstance(self.compounding_convention, CompoundingConvention):
            raise TypeError(
                f"compounding_convention must be CompoundingConvention, "
                f"got {type(self.compounding_convention).__name__}"
            )
        for name, val in [
            ("hurdle_rate_pa", self.hurdle_rate_pa),
            ("gp_promote_share", self.gp_promote_share),
        ]:
            if not isinstance(val, (int, float)):
                raise TypeError(f"{name} must be float, got {type(val).__name__}")
            if math.isnan(val) or math.isinf(val):
                raise ValueError(f"{name} must be finite, got {val}")
            if val < 0.0:
                raise ValueError(f"{name} must be >= 0, got {val}")
        if not isinstance(self.available_cash_by_period, tuple):
            object.__setattr__(
                self, "available_cash_by_period",
                tuple(self.available_cash_by_period)
            )
        if len(self.available_cash_by_period) != self.capital_stack.num_periods:
            raise ValueError(
                f"available_cash_by_period has {len(self.available_cash_by_period)} periods, "
                f"expected {self.capital_stack.num_periods}"
            )
        if self.gp_promote_share <= 0.0:
            raise ValueError(f"gp_promote_share must be > 0, got {self.gp_promote_share}")


# ── Result Schemas ────────────────────────────────────────────────────────────

@dataclass(frozen=True)
class PerInvestorWaterfallResult:
    """Per-investor waterfall result for one investor.

    Contains:
    - pref_result: preferred return computed from this investor's invested capital
    - waterfall_result: aggregate ROC+PROMOTE+RESIDUAL allocations for this investor
      (per-investor PREF is in pref_result, not in waterfall_result)
    - capital_account: tier-annotated capital account
    """
    investor_id: str
    ownership_pct: float
    pref_result: PreferredReturnResult | None
    waterfall_result: WaterfallAllocationResult
    capital_account: TierAnnotatedSponsorCapitalAccount


@dataclass(frozen=True)
class MultiInvestorWaterfallResult:
    """Aggregate multi-investor waterfall result.

    Attributes
    ----------
    registry : InvestorRegistry
        Investor registry.
    per_investor_results : tuple[PerInvestorWaterfallResult, ...]
        Per-investor waterfall results (one per investor).
    aggregate_waterfall_result : WaterfallAllocationResult
        Aggregate waterfall allocation result (ROC + PROMOTE + RESIDUAL).
        Note: PREFERRED_RETURN tiers are NOT in this result
        (per-investor PREF is computed separately in Step 1).
    total_available_by_period_keur : tuple[float, ...]
        Echo of available cash by period.
    total_allocated_keur : float
        Total cash allocated via aggregate waterfall.
    gp_catch_up_threshold_keur : float
        GP catch-up threshold = total committed capital.
    audit_note : str
        Fixed audit note.
    metadata : tuple[tuple[str, Any], ...]
        Frozen key-value metadata.
    """
    registry: InvestorRegistry
    per_investor_results: tuple[PerInvestorWaterfallResult, ...]
    aggregate_waterfall_result: WaterfallAllocationResult
    total_available_by_period_keur: tuple[float, ...]
    total_allocated_keur: float
    gp_catch_up_threshold_keur: float
    audit_note: str = field(
        default="AUDIT-ONLY: multi-investor waterfall result — read-only governance artifact"
    )
    metadata: tuple[tuple[str, Any], ...] = field(default_factory=tuple)

    def __post_init__(self):
        if not isinstance(self.registry, InvestorRegistry):
            raise TypeError("registry must be InvestorRegistry")
        if not isinstance(self.per_investor_results, tuple):
            object.__setattr__(
                self, "per_investor_results",
                tuple(self.per_investor_results)
            )
        if not isinstance(self.aggregate_waterfall_result, WaterfallAllocationResult):
            raise TypeError("aggregate_waterfall_result must be WaterfallAllocationResult")

        expected_ids = {e.investor_id for e in self.registry.entries}
        actual_ids = {r.investor_id for r in self.per_investor_results}
        if actual_ids != expected_ids:
            missing = expected_ids - actual_ids
            extra = actual_ids - expected_ids
            raise ValueError(
                f"Per-investor results must cover all registry investors. "
                f"Missing: {missing}, Extra: {extra}"
            )
        if not isinstance(self.metadata, tuple):
            object.__setattr__(self, "metadata", tuple(self.metadata))


# ── Main Runner ─────────────────────────────────────────────────────────────

def run_multi_investor_waterfall(
    inputs: MultiInvestorWaterfallInputs,
) -> MultiInvestorWaterfallResult:
    """Run the full multi-investor waterfall.

    Pure function. Deterministic. No mutation of inputs.

    Parameters
    ----------
    inputs : MultiInvestorWaterfallInputs
        Validated multi-investor waterfall inputs.

    Returns
    -------
    MultiInvestorWaterfallResult
        Frozen result with aggregate waterfall and per-investor breakdowns.
    """
    registry = inputs.registry
    capital_stack = inputs.capital_stack
    num_periods = capital_stack.num_periods
    investor_ids_sorted = sorted(inv.investor_id for inv in registry.entries)

    # ── Step 1: Compute per-investor preferred return results ────────────
    # Each investor's preferred return is computed from their own
    # invested capital. These are independent calculations.
    pref_results_by_investor: dict[str, PreferredReturnResult] = {}
    for inv in registry.entries:
        contrib = capital_stack.contribution_for(inv.investor_id)
        pref_tier = SponsorWaterfallTier(
            tier_index=0,
            tier_type=TierType.PREFERRED_RETURN,
            sponsor_shares=(SponsorShare(
                sponsor_code=inv.investor_id,
                allocation_percentage=1.0,
            ),),
            hurdle_rate_pa=inputs.hurdle_rate_pa,
            compounding_convention=inputs.compounding_convention,
            description=f"pref_{inv.investor_id}",
        )
        pref_inputs = PreferredReturnCalculatorInputs(
            tier=pref_tier,
            cumulative_invested_by_period=contrib.contributed_by_period_keur,
            distributions_by_period=tuple(0.0 for _ in range(num_periods)),
            num_periods=num_periods,
        )
        pref_results_by_investor[inv.investor_id] = calculate_preferred_return(pref_inputs)

    # ── Step 2: Build and run aggregate waterfall ─────────────────────────
    # Institutional 8-and-20 cascade (4 tiers, no PREF in aggregate):
    #   [RETURN_OF_CAPITAL, GP_CATCH_UP, PROMOTE, RESIDUAL]
    #
    # ROC:  proportional shares (ownership-based, e.g. LP=80%, GP=20%)
    # Catch-up:  100% to GP until GP has (promote_rate/(1-promote_rate)) × max(0, LP_cum_pref − LP_invested)
    # PROMOTE:  LP×(1−gp_promote_share), GP×gp_promote_share (carry split, e.g. 80/20)
    # RESIDUAL: same as PROMOTE (final residue split)
    proportional_shares = tuple(
        SponsorShare(sponsor_code=e.investor_id, allocation_percentage=e.ownership_percentage)
        for e in sorted(registry.entries, key=lambda x: x.investor_id)
    )

    # GP investor ID — the catch-up tier is 100% to GP (not proportional)
    gp_investor_ids = [e.investor_id for e in registry.entries if e.investor_id != "LP-1"]
    gp_investor_id = gp_investor_ids[0] if gp_investor_ids else "GP-1"

    # Promote shares: explicit carry split vs ownership split.
    # GP gets gp_promote_share; remaining (1 − gp_promote_share) is split among all
    # non-GP investors proportional to their ownership.
    non_gp_total_ownership = sum(
        e.ownership_percentage
        for e in sorted(registry.entries, key=lambda x: x.investor_id)
        if e.investor_id != gp_investor_id
    )
    non_gp_residual = 1.0 - inputs.gp_promote_share
    promote_shares = tuple(
        SponsorShare(
            sponsor_code=e.investor_id,
            allocation_percentage=(
                inputs.gp_promote_share
                if e.investor_id == gp_investor_id
                else e.ownership_percentage / non_gp_total_ownership * non_gp_residual
            ),
        )
        for e in sorted(registry.entries, key=lambda x: x.investor_id)
    )

    aggregate_tiers = (
        SponsorWaterfallTier(
            tier_index=0,
            tier_type=TierType.RETURN_OF_CAPITAL,
            sponsor_shares=proportional_shares,
            description="roc_all",
        ),
        SponsorWaterfallTier(
            tier_index=1,
            tier_type=TierType.GP_CATCH_UP,
            sponsor_shares=(SponsorShare(sponsor_code=gp_investor_id, allocation_percentage=1.0),),
            description="gp_catch_up",
        ),
        SponsorWaterfallTier(
            tier_index=2,
            tier_type=TierType.PROMOTE,
            sponsor_shares=promote_shares,
            description="promote",
        ),
        SponsorWaterfallTier(
            tier_index=3,
            tier_type=TierType.RESIDUAL,
            sponsor_shares=promote_shares,
            description="residual",
        ),
    )

    # Build PreferredReturnAllocation from per-investor results (for GP catch-up threshold only)
    from finco_core.sponsor.preferred_return_allocation import PreferredReturnAllocation
    per_investor_pref_results = tuple(
        (inv_id, pref_results_by_investor[inv_id])
        for inv_id in investor_ids_sorted
    )
    lp_entry = registry.investor_for("LP-1")
    lp_invested = lp_entry.committed_capital_keur if lp_entry else 0.0
    pref_allocation = PreferredReturnAllocation(
        per_investor_results=per_investor_pref_results,
        lp_investor_id="LP-1",
        lp_invested_capital_keur=lp_invested,
    )

    # LP cumulative preferred return by period (for GP catch-up threshold)
    lp_cumulative_pref_by_period = pref_allocation.lp_cumulative_pref_by_period()

    aggregate_inputs = WaterfallRunnerInputs(
        tiers=aggregate_tiers,
        available_cash_by_period=inputs.available_cash_by_period,
        pref_result=None,  # PREF not in aggregate cascade; per-investor results in Step 1
        cumulative_invested_by_period=capital_stack.total_contributed_by_period_keur,
        num_periods=num_periods,
        lp_cumulative_pref_by_period=lp_cumulative_pref_by_period,
    )
    agg_result = run_waterfall(aggregate_inputs)

    # ── Step 3: Build per-investor results and capital accounts ──────────
    per_investor_results: list[PerInvestorWaterfallResult] = []

    for inv_id in investor_ids_sorted:
        inv = registry.investor_for(inv_id)
        pref_result = pref_results_by_investor[inv_id]

        # Build per-investor waterfall entries using backwards cash-conservation decomposition.
        #
        # Ownership-scaled available / remaining fields are NOT safe when carry_split ≠ ownership
        # (PROMOTE tier allocates by carry split, not ownership). A forward pass would compute
        # inv_available - inv_allocated ≠ inv_remaining, violating conservation and producing
        # negative remaining balances for the LP investor in the PROMOTE tier.
        #
        # Canonical fix: reconstruct per-investor tier path backwards from the terminal remainder:
        #   terminal_inv_remaining = ownership_pct × p_result.total_remaining_cash_keur
        #   for each tier in REVERSE: inv_available = inv_allocated + running_remaining
        #   then reverse tier list back to canonical order.
        inv_period_results: list[PeriodWaterfallResult] = []
        running_cumulative = 0.0
        for p_result in agg_result.period_results:
            # Anchor: terminal remaining is always ownership-scaled (no tier consumes it)
            terminal_inv_remaining = inv.ownership_percentage * p_result.total_remaining_cash_keur
            running_remaining = terminal_inv_remaining

            # Backwards pass: reconstruct available_before from allocated + remaining_after
            reversed_tier_entries: list[TierAllocationEntry] = []
            for entry in reversed(p_result.tier_entries):
                inv_amt = entry.allocation_for(inv_id)
                inv_remaining_after = running_remaining
                inv_available_before = inv_amt + inv_remaining_after
                reversed_tier_entries.append(
                    TierAllocationEntry(
                        tier_index=entry.tier_index,
                        tier_type=entry.tier_type,
                        available_cash_before_tier_keur=inv_available_before,
                        allocated_amount_keur=inv_amt,
                        allocated_per_sponsor_keur=((inv_id, inv_amt),),
                        remaining_cash_after_tier_keur=inv_remaining_after,
                    )
                )
                running_remaining = inv_available_before

            # Restore canonical (ascending) tier order
            inv_tier_entries = list(reversed(reversed_tier_entries))

            inv_total_alloc = sum(e.allocated_amount_keur for e in inv_tier_entries)
            running_cumulative += inv_total_alloc
            # Period available is the first tier's available_before (top of the stack for this investor)
            inv_available_period = inv_tier_entries[0].available_cash_before_tier_keur if inv_tier_entries else 0.0

            inv_period_results.append(
                PeriodWaterfallResult(
                    period_index=p_result.period_index,
                    available_cash_keur=inv_available_period,
                    tier_entries=tuple(inv_tier_entries),
                    total_allocated_keur=inv_total_alloc,
                    total_remaining_cash_keur=terminal_inv_remaining,
                    cumulative_distributions_by_sponsor_keur=((inv_id, running_cumulative),),
                )
            )

        inv_total_alloc = sum(p.total_allocated_keur for p in inv_period_results)
        inv_waterfall_result = WaterfallAllocationResult(
            investor_id=inv_id,
            period_results=tuple(inv_period_results),
            total_allocated_keur=inv_total_alloc,
            total_distributions_by_sponsor_keur=((inv_id, inv_total_alloc),),
        )

        # Capital account from aggregate result
        inv_cap = from_waterfall_allocation_result(agg_result, inv_id)

        per_investor_results.append(
            PerInvestorWaterfallResult(
                investor_id=inv_id,
                ownership_pct=inv.ownership_percentage,
                pref_result=pref_result,
                waterfall_result=inv_waterfall_result,
                capital_account=inv_cap,
            )
        )

    total_allocated = sum(r.waterfall_result.total_allocated_keur for r in per_investor_results)

    return MultiInvestorWaterfallResult(
        registry=registry,
        per_investor_results=tuple(per_investor_results),
        aggregate_waterfall_result=agg_result,
        total_available_by_period_keur=inputs.available_cash_by_period,
        total_allocated_keur=total_allocated,
        gp_catch_up_threshold_keur=capital_stack.total_committed_keur,
        metadata=inputs.metadata,
    )
