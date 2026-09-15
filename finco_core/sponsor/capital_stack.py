"""Phase 7D-2 — Capital stack schema.

Represents the multi-investor capital stack: per-investor contributions by
period, and aggregate capital stack totals.

Immutable. Deterministic. No waterfall allocation logic here — that lives in
the waterfall runner.

Design: capital_stack is a pure data schema. Waterfall allocation is handled
by the multi_investor_waterfall_runner.
"""
from __future__ import annotations

from dataclasses import dataclass, field
import math
from typing import Any

from finco_core.sponsor.investor_registry import (
    InvestorRole,
    InvestorEntry,
    InvestorRegistry,
)

__all__ = [
    "CapitalContributionEntry",
    "CapitalStack",
    "build_capital_stack",
]


# ── CapitalContributionEntry ─────────────────────────────────────────────────

@dataclass(frozen=True)
class CapitalContributionEntry:
    """Per-investor per-period capital contribution record.

    Attributes
    ----------
    investor_id : str
        Investor identifier matching an entry in InvestorRegistry.
    contributed_by_period_keur : tuple[float, ...]
        Cumulative contributed capital in kEUR at the end of each period.
        Must be non-decreasing and non-negative.
        Length must equal num_periods.
    """
    investor_id: str
    contributed_by_period_keur: tuple[float, ...]

    def __post_init__(self):
        if not isinstance(self.investor_id, str) or not self.investor_id.strip():
            raise ValueError("investor_id must be non-empty string")
        if not isinstance(self.contributed_by_period_keur, (list, tuple)):
            raise TypeError("contributed_by_period_keur must be tuple")
        object.__setattr__(
            self, "contributed_by_period_keur",
            tuple(self.contributed_by_period_keur)
        )
        if len(self.contributed_by_period_keur) == 0:
            raise ValueError("contributed_by_period_keur cannot be empty")
        for i, val in enumerate(self.contributed_by_period_keur):
            if not isinstance(val, (int, float)):
                raise TypeError(
                    f"contributed_by_period_keur[{i}] must be float, got {type(val).__name__}"
                )
            if math.isnan(val) or math.isinf(val):
                raise ValueError(
                    f"contributed_by_period_keur[{i}] must be finite, got {val}"
                )
            if val < 0.0:
                raise ValueError(
                    f"contributed_by_period_keur[{i}] must be >= 0, got {val}"
                )
        # Check non-decreasing
        for i in range(1, len(self.contributed_by_period_keur)):
            if self.contributed_by_period_keur[i] < self.contributed_by_period_keur[i - 1]:
                raise ValueError(
                    f"contributed_by_period_keur must be non-decreasing; "
                    f"period {i} delta is negative"
                )

    def contributed_at_period(self, period_index: int) -> float:
        """Cumulative contribution at end of period_index."""
        return self.contributed_by_period_keur[period_index]

    def contribution_delta(self, period_index: int) -> float:
        """Net new contribution in this period."""
        if period_index == 0:
            return self.contributed_by_period_keur[0]
        return (
            self.contributed_by_period_keur[period_index]
            - self.contributed_by_period_keur[period_index - 1]
        )


# ── CapitalStack ──────────────────────────────────────────────────────────────

@dataclass(frozen=True)
class CapitalStack:
    """Immutable multi-investor capital stack.

    Attributes
    ----------
    registry : InvestorRegistry
        The investor registry for this stack.
    contributions : tuple[CapitalContributionEntry, ...]
        Per-investor contribution records. One entry per investor in registry.
    num_periods : int
        Number of periods.
    total_contributed_by_period_keur : tuple[float, ...]
        Aggregate cumulative contributions across all investors per period.
        Length = num_periods.
    total_committed_keur : float
        Sum of all committed capital across all investors.
    audit_note : str
        Fixed audit note.
    metadata : tuple[tuple[str, Any], ...]
        Frozen key-value metadata.
    """
    registry: InvestorRegistry
    contributions: tuple[CapitalContributionEntry, ...]
    num_periods: int
    total_contributed_by_period_keur: tuple[float, ...]
    total_committed_keur: float
    audit_note: str = field(
        default="AUDIT-ONLY: capital stack — read-only governance artifact"
    )
    metadata: tuple[tuple[str, Any], ...] = field(default_factory=tuple)

    def __post_init__(self):
        if not isinstance(self.registry, InvestorRegistry):
            raise TypeError("registry must be InvestorRegistry")
        if not isinstance(self.contributions, (list, tuple)):
            raise TypeError("contributions must be tuple")
        object.__setattr__(self, "contributions", tuple(self.contributions))
        if len(self.contributions) == 0:
            raise ValueError("contributions cannot be empty")

        # Verify one contribution per investor
        investor_ids_in_registry = {e.investor_id for e in self.registry.entries}
        investor_ids_in_contrib = {c.investor_id for c in self.contributions}
        if investor_ids_in_contrib != investor_ids_in_registry:
            missing = investor_ids_in_registry - investor_ids_in_contrib
            extra = investor_ids_in_contrib - investor_ids_in_registry
            raise ValueError(
                f"Contribution investor_ids must match registry. "
                f"Missing: {missing}, Extra: {extra}"
            )

        # Check num_periods consistency
        for c in self.contributions:
            if len(c.contributed_by_period_keur) != self.num_periods:
                raise ValueError(
                    f"Investor {c.investor_id} has {len(c.contributed_by_period_keur)} "
                    f"periods, expected {self.num_periods}"
                )

        # Validate total_contributed_by_period length
        if not isinstance(self.total_contributed_by_period_keur, tuple):
            object.__setattr__(
                self, "total_contributed_by_period_keur",
                tuple(self.total_contributed_by_period_keur)
            )
        if len(self.total_contributed_by_period_keur) != self.num_periods:
            raise ValueError(
                f"total_contributed_by_period_keur has {len(self.total_contributed_by_period_keur)} "
                f"entries, expected {self.num_periods}"
            )

        # Reconcile totals
        eps = 1e-6
        total_computed = sum(c.contributed_by_period_keur[-1] for c in self.contributions)
        if abs(total_computed - self.total_committed_keur) > eps:
            raise ValueError(
                f"total_committed_keur ({self.total_committed_keur}) does not reconcile "
                f"with contributions sum ({total_computed:.6f})"
            )

        # Reconcile aggregate by period
        for p in range(self.num_periods):
            period_sum = sum(c.contributed_by_period_keur[p] for c in self.contributions)
            if abs(period_sum - self.total_contributed_by_period_keur[p]) > eps:
                raise ValueError(
                    f"Period {p} total_contributed ({self.total_contributed_by_period_keur[p]}) "
                    f"does not reconcile with contributions sum ({period_sum:.6f})"
                )

        if not isinstance(self.metadata, tuple):
            object.__setattr__(self, "metadata", tuple(self.metadata))

    def contribution_for(self, investor_id: str) -> CapitalContributionEntry:
        """Return the contribution entry for a given investor_id."""
        for c in self.contributions:
            if c.investor_id == investor_id:
                return c
        raise KeyError(f"Investor not found: {investor_id!r}")

    def __len__(self) -> int:
        return len(self.contributions)

    def __iter__(self):
        return iter(self.contributions)


# ── Capital Stack Builder ────────────────────────────────────────────────────

def build_capital_stack(
    registry: InvestorRegistry,
    contributions_by_investor: dict[str, tuple[float, ...]],
    metadata: tuple[tuple[str, Any], ...] = (),
) -> CapitalStack:
    """Build a validated CapitalStack from a registry and per-investor contributions.

    Pure function. Deterministic.

    Parameters
    ----------
    registry : InvestorRegistry
        Validated investor registry.
    contributions_by_investor : dict[str, tuple[float, ...]]
        Mapping from investor_id to cumulative contributed_by_period_keur tuple.
    metadata : tuple[tuple[str, Any], ...]
        Optional metadata.

    Returns
    -------
    CapitalStack
        Validated frozen capital stack.

    Raises
    ------
    ValueError : if ownership sums != 1.0, investor IDs don't match, etc.
    """
    if not isinstance(registry, InvestorRegistry):
        raise TypeError("registry must be InvestorRegistry")

    # Determine num_periods from first contribution
    if not contributions_by_investor:
        raise ValueError("contributions_by_investor cannot be empty")
    num_periods = len(next(iter(contributions_by_investor.values())))

    # Validate all contributions have the same number of periods before building
    for inv_id, contrib in contributions_by_investor.items():
        if len(contrib) != num_periods:
            raise ValueError(
                f"Investor {inv_id} has {len(contrib)} periods, expected {num_periods}"
            )

    # Build contribution entries
    contrib_entries: list[CapitalContributionEntry] = []
    for inv in registry.entries:
        if inv.investor_id not in contributions_by_investor:
            raise KeyError(f"No contribution data for investor: {inv.investor_id!r}")
        contrib_entries.append(
            CapitalContributionEntry(
                investor_id=inv.investor_id,
                contributed_by_period_keur=contributions_by_investor[inv.investor_id],
            )
        )

    # Compute aggregate total by period
    total_by_period = tuple(
        sum(c.contributed_by_period_keur[p] for c in contrib_entries)
        for p in range(num_periods)
    )

    total_committed = sum(c.contributed_by_period_keur[-1] for c in contrib_entries)

    return CapitalStack(
        registry=registry,
        contributions=tuple(contrib_entries),
        num_periods=num_periods,
        total_contributed_by_period_keur=total_by_period,
        total_committed_keur=total_committed,
        metadata=metadata,
    )
