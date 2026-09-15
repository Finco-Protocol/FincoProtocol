"""Phase 7F-1 — App-layer sponsor waterfall runner.

Thin orchestration layer that wires existing Phase 7 domain runners into an
internal callable path. No UI redesign, no persistence wiring, no domain logic changes.

Pure function. Deterministic. No mutation of source inputs.
No domain → app imports. Domain imports are unidirectional: domain → domain only.

Architecture:
  SponsorRunConfig
      ↓
  [_build_investor_registry]  → InvestorRegistry
  [_build_capital_stack]      → CapitalStack
  [_build_waterfall_inputs]   → MultiInvestorWaterfallInputs
      ↓
  run_multi_investor_waterfall()  → MultiInvestorWaterfallResult
"""
from __future__ import annotations

from dataclasses import dataclass, field
import math
from typing import Any

__all__ = [
    "SponsorRunConfig",
    "run_sponsor_waterfall",
]


# ── SponsorRunConfig ──────────────────────────────────────────────────────────

@dataclass(frozen=True)
class SponsorRunConfig:
    """Minimal inputs for a sponsor waterfall run.

    All float fields must be finite and non-negative unless noted.
    ownership_percentages dict: investor_id → decimal (e.g. 0.80 for 80%).
    committed_capital_keur dict: investor_id → kEUR.

    The GP is identified by having role="GP". Exactly one GP is required.
    All other investors are treated as LP (or CO_INVESTOR if explicitly set).

    Parameters
    ----------
    ownership_percentages : dict[str, float]
        Mapping from investor_id to ownership decimal. Must sum to 1.0 (±1e-6).
    committed_capital_keur : dict[str, float]
        Mapping from investor_id to total committed capital in kEUR.
        GP's capital is typically the promote commitment (may be 0).
    hurdle_rate_pa : float
        Annual preferred return hurdle rate as decimal (e.g. 0.08 for 8%).
        Must be > 0.
    compounding_convention : str
        One of "SEMIANNUAL", "ANNUAL". Passed to CompoundingConvention enum.
    gp_promote_share : float
        GP's carry/promote ownership percentage as decimal (e.g. 0.20 for 20%).
        Must be > 0 and <= 1.0.
    available_cash_by_period : tuple[float, ...]
        Per-period cash available for distribution in kEUR.
        Each value must be >= 0 and finite.
    num_periods : int
        Number of semiannual periods. Must match len(available_cash_by_period).
    gp_investor_id : str
        Investor ID string for the GP (e.g. "GP-1"). Defaults to "GP-1".
    lp_investor_id : str
        Investor ID string for the LP (e.g. "LP-1"). Defaults to "LP-1".
    metadata : tuple[tuple[str, Any], ...]
        Optional frozen key-value metadata passed through to the result.
    contribution_timing : tuple[tuple[str, tuple[float, ...]], ...]
        Optional: per-period contribution fractions for each investor.
        Format: ((investor_id, (frac_period_0, frac_period_1, ...)), ...).
        Default: all capital committed at period 0 (cumulative stays flat thereafter).
        Fractions are ratio of total committed capital; must sum to 1.0 per investor across periods.
    """
    ownership_percentages: dict[str, float]
    committed_capital_keur: dict[str, float]
    hurdle_rate_pa: float
    compounding_convention: str
    gp_promote_share: float
    available_cash_by_period: tuple[float, ...]
    num_periods: int
    gp_investor_id: str = "GP-1"
    lp_investor_id: str = "LP-1"
    metadata: tuple[tuple[str, Any], ...] = ()
    contribution_timing: tuple[tuple[str, tuple[float, ...]], ...] = ()

    def __post_init__(self):
        # Validate ownership sums
        total_own = sum(self.ownership_percentages.values())
        eps = 1e-6
        if abs(total_own - 1.0) > eps:
            raise ValueError(
                f"ownership_percentages must sum to 1.0, got {total_own:.6f}"
            )
        # Validate all ownership values are finite and in [0,1]
        for inv_id, pct in self.ownership_percentages.items():
            if math.isnan(pct) or math.isinf(pct):
                raise ValueError(f"ownership_percentage for {inv_id!r} must be finite, got {pct}")
            if pct < 0.0 or pct > 1.0:
                raise ValueError(f"ownership_percentage for {inv_id!r} must be in [0,1], got {pct}")
        # Validate committed capitals
        for inv_id, cap in self.committed_capital_keur.items():
            if math.isnan(cap) or math.isinf(cap):
                raise ValueError(f"committed_capital_keur for {inv_id!r} must be finite, got {cap}")
            if cap < 0.0:
                raise ValueError(f"committed_capital_keur for {inv_id!r} must be >= 0, got {cap}")
        # Validate hurdle_rate
        if math.isnan(self.hurdle_rate_pa) or math.isinf(self.hurdle_rate_pa):
            raise ValueError(f"hurdle_rate_pa must be finite, got {self.hurdle_rate_pa}")
        if self.hurdle_rate_pa <= 0.0:
            raise ValueError(f"hurdle_rate_pa must be > 0, got {self.hurdle_rate_pa}")
        # Validate gp_promote_share
        if math.isnan(self.gp_promote_share) or math.isinf(self.gp_promote_share):
            raise ValueError(f"gp_promote_share must be finite, got {self.gp_promote_share}")
        if not (0.0 < self.gp_promote_share <= 1.0):
            raise ValueError(f"gp_promote_share must be in (0,1], got {self.gp_promote_share}")
        # Validate available_cash_by_period
        if not isinstance(self.available_cash_by_period, (list, tuple)):
            raise TypeError("available_cash_by_period must be tuple")
        object.__setattr__(
            self, "available_cash_by_period",
            tuple(self.available_cash_by_period)
        )
        if len(self.available_cash_by_period) != self.num_periods:
            raise ValueError(
                f"available_cash_by_period has {len(self.available_cash_by_period)} periods, "
                f"expected {self.num_periods}"
            )
        for i, val in enumerate(self.available_cash_by_period):
            if math.isnan(val) or math.isinf(val):
                raise ValueError(f"available_cash_by_period[{i}] must be finite, got {val}")
            if val < 0.0:
                raise ValueError(f"available_cash_by_period[{i}] must be >= 0, got {val}")
        # Validate num_periods
        if not isinstance(self.num_periods, int) or self.num_periods <= 0:
            raise ValueError(f"num_periods must be positive int, got {self.num_periods}")
        # Validate compounding_convention
        from domain.sponsor.sponsor_waterfall_tier import CompoundingConvention
        try:
            object.__setattr__(
                self, "compounding_convention",
                CompoundingConvention[self.compounding_convention]
            )
        except KeyError:
            valid = list(CompoundingConvention.__members__.keys())
            raise ValueError(
                f"compounding_convention must be one of {valid}, got {self.compounding_convention!r}"
            )
        # Validate gp_investor_id and lp_investor_id
        if not self.gp_investor_id or not self.gp_investor_id.strip():
            raise ValueError("gp_investor_id must be non-empty string")
        if not self.lp_investor_id or not self.lp_investor_id.strip():
            raise ValueError("lp_investor_id must be non-empty string")
        if self.gp_investor_id not in self.ownership_percentages:
            raise KeyError(f"GP investor_id {self.gp_investor_id!r} not in ownership_percentages")
        if self.lp_investor_id not in self.ownership_percentages:
            raise KeyError(f"LP investor_id {self.lp_investor_id!r} not in ownership_percentages")
        # Validate metadata
        if not isinstance(self.metadata, tuple):
            object.__setattr__(self, "metadata", tuple(self.metadata))
        # Normalize ownership_percentages dict to tuple of sorted items for determinism
        object.__setattr__(
            self, "ownership_percentages",
            dict(sorted(self.ownership_percentages.items()))
        )
        object.__setattr__(
            self, "committed_capital_keur",
            dict(sorted(self.committed_capital_keur.items()))
        )
        # Normalize contribution_timing
        if self.contribution_timing:
            object.__setattr__(
                self, "contribution_timing",
                tuple(
                    (inv_id, tuple(fracs))
                    for inv_id, fracs in sorted(self.contribution_timing)
                )
            )
            # Fractions are cumulative draw fractions: each value is the cumulative
            # fraction drawn by that period. The final value must be exactly 1.0
            # (full commitment drawn by end of last period).
            for inv_id, fracs in self.contribution_timing:
                if len(fracs) != self.num_periods:
                    raise ValueError(
                        f"contribution_timing for {inv_id!r} has {len(fracs)} periods, "
                        f"expected {self.num_periods}"
                    )
                # Validate fractions are non-decreasing (cumulative draw interpretation)
                for i in range(1, len(fracs)):
                    if fracs[i] < fracs[i - 1]:
                        raise ValueError(
                            f"contribution_timing fractions for {inv_id!r} must be "
                            f"non-decreasing (cumulative draw), got {fracs[i-1]:.2f} then "
                            f"{fracs[i]:.2f} at period {i}"
                        )
                # Validate each fraction is in [0, 1]
                for i, frac in enumerate(fracs):
                    if frac < 0.0 or frac > 1.0:
                        raise ValueError(
                            f"contribution_timing fraction for {inv_id!r} at period {i} "
                            f"must be in [0, 1], got {frac}"
                        )
                # Final cumulative fraction must be exactly 1.0 (full draw)
                if abs(fracs[-1] - 1.0) > 1e-6:
                    raise ValueError(
                        f"contribution_timing final fraction for {inv_id!r} must be 1.0 "
                        f"(full commitment drawn), got {fracs[-1]:.6f}"
                    )


# ── Internal builders ─────────────────────────────────────────────────────────

def _build_investor_registry(config: SponsorRunConfig) -> Any:
    """Build InvestorRegistry from SponsorRunConfig.

    Deterministic. No mutation of config.
    """
    from domain.sponsor.investor_registry import (
        InvestorRole,
        InvestorEntry,
        InvestorRegistry,
    )

    entries_list = []
    for inv_id in sorted(config.ownership_percentages.keys()):
        pct = config.ownership_percentages[inv_id]
        if inv_id == config.gp_investor_id:
            role = InvestorRole("GP")
        else:
            role = InvestorRole("LP")
        cap = config.committed_capital_keur.get(inv_id, 0.0)
        entries_list.append(
            InvestorEntry(
                investor_id=inv_id,
                role=role,
                ownership_percentage=pct,
                committed_capital_keur=cap,
            )
        )

    entries_tuple = tuple(entries_list)
    return InvestorRegistry(
        entries=entries_tuple,
        total_ownership_pct=sum(e.ownership_percentage for e in entries_tuple),
        total_committed_keur=sum(e.committed_capital_keur for e in entries_tuple),
    )


def _build_contributions(
    config: SponsorRunConfig,
    registry: Any,
) -> dict[str, tuple[float, ...]]:
    """Build per-investor contribution timeline from SponsorRunConfig.

    Default: capital committed at period 0 and held (cumulative constant, non-decreasing).
    Custom contribution_timing overrides default with phased draw-down fractions.

    Returns dict: investor_id → cumulative contributed_by_period_keur tuple.
    Deterministic. No mutation.
    """
    from domain.sponsor.capital_stack import CapitalContributionEntry

    num_periods = config.num_periods

    # Default: full amount committed at period 0, cumulative stays flat thereafter
    def default_timeline(investor_id: str) -> tuple[float, ...]:
        cap = config.committed_capital_keur.get(investor_id, 0.0)
        if cap == 0.0:
            return tuple(0.0 for _ in range(num_periods))
        # Cumulative: full amount at period 0, same amount in all subsequent periods
        return tuple(float(cap) for _ in range(num_periods))

    # Use custom timing if provided
    if config.contribution_timing:
        timing_dict = dict(config.contribution_timing)
        result = {}
        for inv_id in sorted(config.ownership_percentages.keys()):
            fracs = timing_dict.get(inv_id)
            if fracs is None:
                result[inv_id] = default_timeline(inv_id)
            else:
                cap = config.committed_capital_keur.get(inv_id, 0.0)
                # Fractions are already cumulative draw fractions.
                # (0.50, 1.00, 1.00) means 50% drawn by period 0, 100% by period 1.
                result[inv_id] = tuple(cap * frac for frac in fracs)
        return result
    else:
        return {inv_id: default_timeline(inv_id) for inv_id in config.ownership_percentages}


def _build_capital_stack(
    config: SponsorRunConfig,
    registry: Any,
) -> Any:
    """Build CapitalStack from SponsorRunConfig.

    Deterministic. No mutation of inputs.
    """
    from domain.sponsor.capital_stack import build_capital_stack

    contributions = _build_contributions(config, registry)
    return build_capital_stack(
        registry=registry,
        contributions_by_investor=contributions,
        metadata=config.metadata,
    )


def _build_waterfall_inputs(
    config: SponsorRunConfig,
    capital_stack: Any,
    registry: Any,
) -> Any:
    """Build MultiInvestorWaterfallInputs from SponsorRunConfig.

    Deterministic. No mutation of inputs.
    """
    from domain.sponsor.multi_investor_waterfall_runner import (
        MultiInvestorWaterfallInputs,
    )

    return MultiInvestorWaterfallInputs(
        capital_stack=capital_stack,
        registry=registry,
        hurdle_rate_pa=config.hurdle_rate_pa,
        compounding_convention=config.compounding_convention,
        gp_promote_share=config.gp_promote_share,
        available_cash_by_period=config.available_cash_by_period,
        metadata=config.metadata,
    )


# ── Main runner ───────────────────────────────────────────────────────────────

def run_sponsor_waterfall(
    config: SponsorRunConfig,
) -> Any:
    """Run the sponsor waterfall for a validated config.

    Pure function. Deterministic. No mutation of config or any inputs.

    This is a thin app-layer orchestrator: it builds domain objects from config
    and delegates to the domain runner. No domain logic lives here.

    Parameters
    ----------
    config : SponsorRunConfig
        Validated sponsor run configuration.

    Returns
    -------
    MultiInvestorWaterfallResult
        Frozen result with aggregate waterfall and per-investor breakdowns.

    Raises
    ------
    TypeError, ValueError : on invalid inputs (propagated from domain constructors).
    """
    registry = _build_investor_registry(config)
    capital_stack = _build_capital_stack(config, registry)
    inputs = _build_waterfall_inputs(config, capital_stack, registry)

    from domain.sponsor.multi_investor_waterfall_runner import (
        run_multi_investor_waterfall,
    )

    return run_multi_investor_waterfall(inputs)