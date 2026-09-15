"""finco_core.engine.axis_contract — Immutable canonical axis contract.

PR-F1 Correction F: CanonicalAxisContract encapsulates the three independently-
derived canonical period-index sets used throughout the engine.  It is constructed
BEFORE any solver output is accepted and is NEVER derived from solver/result
schedule indices.

Axis definitions
----------------
full_axis      : every model period index (construction + operating), in order.
operating_axis : operating-only period indices (is_operation=True), in order.
senior_axis    : debt-active operating subset derived from SeniorDebtPolicy bounds
                 (repayment_start_period_index .. maturity_period_index inclusive).
                 Empty tuple when no Senior policy is active.

Construction contract
---------------------
Construct once, early, from the typed canonical periods tuple and the typed
SeniorDebtPolicy (or None).  Pass the resulting contract to all downstream
consumers that need an axis expectation.  Never re-derive from a solver result.

Non-serialized
--------------
CanonicalAxisContract is a runtime-only object.  It must NOT be serialized,
used as a cache key, or exposed as a user input.
"""
from __future__ import annotations

from dataclasses import dataclass
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from typing import Any


@dataclass(frozen=True)
class CanonicalAxisContract:
    """Immutable canonical axis contract for one engine run.

    Error-code precedence (TASK F4 — documented here as the authoritative reference):
      1. AXIS_PERIOD_DUPLICATE  — duplicate raw indices in supplied vector (checked first)
      2. AXIS_LENGTH_MISMATCH   — lengths differ and both missing and extra exist
      3. AXIS_PERIOD_MISSING    — expected index absent from supplied (includes shifted range)
      4. AXIS_PERIOD_EXTRA      — supplied index not in expected (same set size)
      5. AXIS_PERIOD_SHIFTED    — identical sets, identical length, different order

    Note: a "shifted range" (e.g., supply {2,3,4} vs expected {1,2,3}) produces
    AXIS_PERIOD_MISSING because the sets differ (missing={1}, extra={4}).
    AXIS_PERIOD_SHIFTED only fires when len matches AND sets match but order differs.
    """

    full_axis: tuple[int, ...]
    """All model period indices, construction + operating, 0-based, in order."""

    operating_axis: tuple[int, ...]
    """Operating-only period indices (is_operation=True), in order."""

    senior_axis: tuple[int, ...]
    """Debt-active operating subset [repayment_start .. maturity] from policy.
    Empty tuple when no Senior debt policy is active."""

    @classmethod
    def from_periods_and_policy(
        cls,
        periods: tuple,
        senior_policy: "Any | None",
    ) -> "CanonicalAxisContract":
        """Construct the contract from canonical model periods and an optional policy.

        Parameters
        ----------
        periods:
            Canonical immutable model periods tuple (OperatingPeriodResult or PeriodMeta).
            Each element must expose `period_index` (or `index` for PeriodMeta) and
            `is_operation`.
        senior_policy:
            A SeniorDebtPolicy instance with `repayment_start_period_index` and
            `maturity_period_index`, or None when no Senior debt is active.

        Returns
        -------
        CanonicalAxisContract
            Frozen contract.  senior_axis is () when senior_policy is None.
        """
        # Support both OperatingPeriodResult (period_index) and PeriodMeta (index).
        def _idx(p: "Any") -> int:
            if hasattr(p, "period_index"):
                return p.period_index
            return p.index

        def _is_op(p: "Any") -> bool:
            return bool(getattr(p, "is_operation", False))

        full_axis = tuple(_idx(p) for p in periods)
        operating_axis = tuple(_idx(p) for p in periods if _is_op(p))

        if senior_policy is not None:
            debt_start = senior_policy.repayment_start_period_index
            debt_end = senior_policy.maturity_period_index
            senior_axis = tuple(
                i for i in operating_axis
                if debt_start <= i <= debt_end
            )
        else:
            senior_axis = ()

        return cls(
            full_axis=full_axis,
            operating_axis=operating_axis,
            senior_axis=senior_axis,
        )
