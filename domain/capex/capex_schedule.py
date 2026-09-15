"""CAPEX cash flow schedule - distributes CAPEX across construction periods.

Implements Blueprint S1-4 fix:
- v2 bug: All CAPEX deducted at Financial Close (period 0)
- v3 fix: CAPEX distributed across construction periods per spending_profile

Key insight:
- CAPEX is rarely paid all at once at Financial Close
- Large projects have 12-18 month construction periods
- CAPEX is spread across construction: Y0-H1, Y0-H2, Y1-H1, Y1-H2, etc.
- This affects equity IRR because capital is deployed earlier

Example for Generic Solar Reference (18-month construction):
  EPC Contract: 26,430 kEUR → paid over 18 months (spending_profile)
  Grid connection: 3,300 kEUR → often 100% at COD (Y1-H2)

v2 bug calculation:
  IRR base = -CAPEX at FC (26,430 + IDC + ... = ~60,000 kEUR)
  IRR would be LOWER because all money goes out at period 0

v3 fix:
  IRR base = -CAPEX per period (per spending_profile)
  IRR would be DIFFERENT because timing is different

For Generic Solar Reference, this shifts ~20,000 kEUR from period 0 to periods 1-4,
which changes the equity IRR by ~0.2-0.5 percentage points.
"""
from dataclasses import dataclass, field
from typing import Dict, Optional
from datetime import date


@dataclass(frozen=True)
class CapexCashFlowEntry:
    """Single CAPEX cash flow entry."""
    period_index: int
    period_date: date
    amount_keur: float  # Negative for outflow
    category: str        # "epc", "grid", "idc", "fees", etc.

    @property
    def is_outflow(self) -> bool:
        return self.amount_keur < 0


@dataclass(frozen=True)
class CapexCashFlowSchedule:
    """Full CAPEX cash flow schedule across construction period.

    Used for:
    1. Equity IRR calculation (CAPEX timing matters)
    2. DSRA funding (CAPEX inflows affect DSRA sizing)
    3. Cash balance tracking
    """
    entries: list[CapexCashFlowEntry] = field(default_factory=list)

    @property
    def total_outflow_keur(self) -> float:
        """Total CAPEX outflow (sum of negative entries)."""
        return sum(e.amount_keur for e in self.entries if e.is_outflow)

    @property
    def period_indexes(self) -> list[int]:
        """Unique period indexes with CAPEX."""
        return sorted(set(e.period_index for e in self.entries))

    def for_period(self, period_index: int) -> list[CapexCashFlowEntry]:
        """Get all entries for a specific period."""
        return [e for e in self.entries if e.period_index == period_index]

    def total_for_period(self, period_index: int) -> float:
        """Get total CAPEX for a period (sum of all entries)."""
        return sum(e.amount_keur for e in self.entries if e.period_index == period_index)


@dataclass(frozen=True)
class CapexItemWithProfile:
    """A CAPEX item with its spending profile across periods.

    This is the building block for the full CAPEX schedule.
    """
    name: str
    amount_keur: float
    spending_profile: Dict[int, float]  # period_index → fraction (0-1), sum = 1.0

    def amount_for_period(self, period_index: int) -> float:
        """Amount for a specific period."""
        fraction = self.spending_profile.get(period_index, 0.0)
        return self.amount_keur * fraction


def build_capex_cashflow_schedule(
    capex_items: list["CapexItemWithProfile"],
    periods: list,
    construction_start_period: int = 0,
) -> CapexCashFlowSchedule:
    """Build full CAPEX cash flow schedule from spending profiles.

    Args:
        capex_items: List of CAPEX items with spending profiles
        periods: List of period objects (from period_engine)
        construction_start_period: Starting period for construction (usually 0)

    Returns:
        CapexCashFlowSchedule with all CAPEX outflows distributed per profile

    Example:
        # Generic Solar Reference EPC contract (26,430 kEUR over 18 months)
        epc = CapexItemWithProfile(
            name="epc_contract",
            amount_keur=26_430.0,
            spending_profile={
                0: 0.0,   # Y0-H1: not started yet
                1: 0.15,  # Y0-H2: 15%
                2: 0.20,  # Y1-H1: 20%
                3: 0.20,  # Y1-H2: 20%
                4: 0.15,  # Y2-H1: 15%
                ...
            }
        )
    """
    entries = []

    for item in capex_items:
        for period_index, fraction in item.spending_profile.items():
            if fraction <= 0:
                continue

            # Find the period object for this index
            period = next((p for p in periods if p.index == period_index), None)
            if period is None:
                continue

            amount = item.amount_keur * fraction
            entry = CapexCashFlowEntry(
                period_index=period_index,
                period_date=period.start_date,
                amount_keur=-amount,  # Negative for outflow
                category=item.name,
            )
            entries.append(entry)

    # Sort by period index
    entries.sort(key=lambda e: e.period_index)
    return CapexCashFlowSchedule(entries=entries)


def capex_cashflow_for_irr(
    schedule: CapexCashFlowSchedule,
    exclude_period_0: bool = True,
) -> list[tuple[int, float]]:
    """Get CAPEX cash flows formatted for XIRR calculation.

    Args:
        schedule: CapexCashFlowSchedule from build_capex_cashflow_schedule
        exclude_period_0: If True, exclude period 0 (FC date) for IRR base

    Returns:
        List of (period_index, outflow_keur) for IRR calculation
    """
    cfs = []
    for entry in schedule.entries:
        if exclude_period_0 and entry.period_index == 0:
            continue
        cfs.append((entry.period_index, entry.amount_keur))
    return cfs


def aggregate_capex_by_period(
    schedule: CapexCashFlowSchedule,
) -> Dict[int, float]:
    """Aggregate total CAPEX outflow per period.

    Returns:
        Dict mapping period_index → total outflow for that period
    """
    result = {}
    for entry in schedule.entries:
        if entry.period_index not in result:
            result[entry.period_index] = 0.0
        result[entry.period_index] += entry.amount_keur
    return result


def total_sculpt_capex(
    capex_items: list["CapexItemWithProfile"],
) -> float:
    """Calculate total CAPEX (for sculpting base).

    This is the sum of all CAPEX items, used as the base for
    debt sizing (gearing calculation).

    Note: This is the TOTAL, not the present value. For debt sizing,
    we use the nominal total (no discounting).
    """
    return sum(item.amount_keur for item in capex_items)


def default_spending_profile(
    total_periods: int,
    construction_periods: int,
    profile_type: str = "linear",
) -> Dict[int, float]:
    """Generate a default spending profile.

    Args:
        total_periods: Total construction periods
        construction_periods: Number of periods with spending
        profile_type: "linear" (default), "front_loaded", "back_loaded"

    Returns:
        Dict mapping period_index → fraction

    Example:
        profile = default_spending_profile(total_periods=8, construction_periods=4)
        # Returns: {0: 0.25, 1: 0.25, 2: 0.25, 3: 0.25} (linear over 4 periods)
    """
    if construction_periods <= 0:
        return {0: 1.0}

    fractions = []
    if profile_type == "linear":
        fraction = 1.0 / construction_periods
        fractions = [fraction] * construction_periods
    elif profile_type == "front_loaded":
        # More spending early: 40%, 30%, 20%, 10%
        weights = [4, 3, 2, 1][:construction_periods]
        total = sum(weights)
        fractions = [w / total for w in weights]
    elif profile_type == "back_loaded":
        # Less spending early: 10%, 20%, 30%, 40%
        weights = [1, 2, 3, 4][:construction_periods]
        total = sum(weights)
        fractions = [w / total for w in weights]

    result = {}
    for i, frac in enumerate(fractions):
        result[i] = frac

    return result


__all__ = [
    "CapexCashFlowEntry",
    "CapexCashFlowSchedule",
    "CapexItemWithProfile",
    "build_capex_cashflow_schedule",
    "capex_cashflow_for_irr",
    "aggregate_capex_by_period",
    "total_sculpt_capex",
    "default_spending_profile",
]