"""WF-09 V2 - date-preserving monthly construction bridge (pure; no I/O; no engine change).

The committed Run takes its construction timing from ``ConstructionFinancingInput`` (``finco_core.inputs.construction_financing``):
a list of consecutive dated periods and, per CAPEX category, one payment-weight vector over those periods.  The generic policy
derives that input on the SEMESTER axis (``derive_construction_financing``).  The typed input itself is not semester specific:
``financial_engine.construction.adapter`` turns period dates into Senior interest fractions, so the same canonical Stage B2 /
allocator / IDC path runs unchanged on a MONTHLY construction timeline.

This module turns the semester input the Run already derives into the equivalent MONTHLY input and applies user monthly profiles:

  * every construction period is split at month-grid boundaries (``financial_close + k`` months, the PeriodEngine rule); a period
    boundary that is not a month boundary is UNSUPPORTED (typed refusal - the profile stays preview-only on that path);
  * a category without a profile keeps its existing cash dates: each semester weight moves to the LAST month of its period
    (the existing convention is "paid at the end of the construction period"), so cash dates are unchanged;
  * a category with profiled leaves gets the EXACT amount-weighted blend of its leaves (profiled leaves use their monthly weights,
    the remaining amount keeps the default timing).  The blend preserves the category total, and parents/children are never
    both counted because only leaf rows own a profile;
  * Senior / commitment / structuring / equity / SHL funding and IDC are NOT recomputed here: the unchanged canonical engine
    computes them from the monthly timeline.  Nothing is inferred from an already aggregated half-year amount.

Unsupported (refused, never approximated): per-period pricing vectors, an enabled VAT facility, SHL accrual tails, a financial
close whose semester boundaries are not month-grid boundaries, and leaf amounts that do not sum to the category amount.
"""
from __future__ import annotations

import dataclasses
from dataclasses import dataclass
from datetime import date, timedelta
from fractions import Fraction
from typing import Mapping, Sequence

from dateutil.relativedelta import relativedelta

from app.capex_profiles.contract import ProfileSpec, build_weights, reject_duplicates
from finco_core.inputs.construction_financing import (
    ConstructionCapexTimingInput, ConstructionFinancingInput, ConstructionPeriodSpec, ConstructionStructuringFeeInput,
)
from finco_core.inputs.senior_rate_schedule import SeniorRateMode

AMOUNT_TOLERANCE_KEUR = 1e-6


class BindingUnsupported(ValueError):
    """The monthly bridge cannot prove the financial effect for this input; the profile stays preview-only."""

    def __init__(self, code: str, detail: str = ""):
        self.code = code
        super().__init__(f"{code}: {detail}" if detail else code)


@dataclass(frozen=True)
class Leaf:
    """One leaf row (category base amount or active sub-line) that may own a monthly profile.  Amounts are kEUR."""
    item_key: str
    category_field: str                     # CapexStructure field / construction item code, e.g. "production_units"
    amount_keur: float
    spec: ProfileSpec | None = None         # None -> default (existing) timing


@dataclass(frozen=True)
class MonthGrid:
    starts: tuple[date, ...]                # month k starts here; len == construction months
    ends: tuple[date, ...]                  # inclusive last day of month k
    month_to_period: tuple[int, ...]        # index of the semester construction period containing month k
    period_last_month: tuple[int, ...]      # last month index of each semester period


@dataclass(frozen=True)
class BindingEvidence:
    months: int
    grid: MonthGrid
    profiled_leaves: tuple[str, ...]
    category_weights: Mapping[str, tuple[float, ...]]       # monthly blended weight per bound category
    default_weights: Mapping[str, tuple[float, ...]]        # the same categories with default (end-of-period) timing


@dataclass(frozen=True)
class BoundConstruction:
    construction: ConstructionFinancingInput
    evidence: BindingEvidence


def month_grid(construction: ConstructionFinancingInput, construction_months: int) -> MonthGrid:
    periods = construction.periods
    if not periods:
        raise BindingUnsupported("CAPEX_BINDING_NO_PERIODS")
    if isinstance(construction_months, bool) or not isinstance(construction_months, int) or construction_months < 1:
        raise BindingUnsupported("CAPEX_BINDING_DURATION_INVALID", repr(construction_months))
    fc = periods[0].start_date
    boundaries = [fc + relativedelta(months=k) for k in range(construction_months + 1)]
    if periods[-1].end_date + timedelta(days=1) != boundaries[-1]:
        raise BindingUnsupported("CAPEX_BINDING_AXIS_MISALIGNED",
                                 f"construction ends {periods[-1].end_date} but financial close + {construction_months} months is {boundaries[-1]}")
    starts = tuple(boundaries[:-1])
    ends = tuple(b - timedelta(days=1) for b in boundaries[1:])
    month_to_period: list[int] = []
    for start, end in zip(starts, ends):
        owner = next((i for i, p in enumerate(periods) if p.start_date <= start and end <= p.end_date), None)
        if owner is None:
            raise BindingUnsupported("CAPEX_BINDING_AXIS_MISALIGNED", f"month {start}..{end} crosses a construction period boundary")
        month_to_period.append(owner)
    last = tuple(max(k for k, o in enumerate(month_to_period) if o == p) for p in range(len(periods)))
    if len(set(month_to_period)) != len(periods):
        raise BindingUnsupported("CAPEX_BINDING_AXIS_MISALIGNED", "a construction period contains no month")
    return MonthGrid(starts, ends, tuple(month_to_period), last)


def _refuse_unsupported(construction: ConstructionFinancingInput) -> None:
    if not construction.enabled:
        raise BindingUnsupported("CAPEX_BINDING_CONSTRUCTION_DISABLED")
    pricing = construction.senior_pricing
    if pricing is not None and (pricing.floating_base_rate_curve or pricing.explicit_all_in_schedule or pricing.explicit_period_fractions
                                or pricing.mode != SeniorRateMode.FLAT_ALL_IN):
        raise BindingUnsupported("CAPEX_BINDING_PERIOD_PRICING_UNSUPPORTED", "only a flat all-in Senior construction rate is bound")
    if construction.vat_facility is not None and construction.vat_facility.enabled:
        raise BindingUnsupported("CAPEX_BINDING_VAT_FACILITY_UNSUPPORTED")
    if construction.shl_accrual_tail_periods:
        raise BindingUnsupported("CAPEX_BINDING_SHL_TAIL_UNSUPPORTED")


def _spread_default(weights: Sequence[float], grid: MonthGrid) -> list[float]:
    """Existing convention: a semester weight is paid at the END of its construction period -> last month of that period."""
    out = [0.0] * len(grid.starts)
    for p, w in enumerate(weights):
        out[grid.period_last_month[p]] += float(w)
    return out


def expand_to_months(construction: ConstructionFinancingInput, grid: MonthGrid) -> tuple[ConstructionPeriodSpec, ...]:
    return tuple(dataclasses.replace(construction.periods[grid.month_to_period[k]], start_date=grid.starts[k], end_date=grid.ends[k])
                 for k in range(len(grid.starts)))


def bind(construction: ConstructionFinancingInput, *, construction_months: int, category_amounts_keur: Mapping[str, float],
         leaves: Sequence[Leaf] = ()) -> BoundConstruction:
    """Monthly construction input.  With no profiled leaf the result is the date-preserving monthly equivalent of the input
    (the 'monthly baseline' used to attribute financing effects to the profile rather than to the finer interest grid)."""
    _refuse_unsupported(construction)
    grid = month_grid(construction, construction_months)
    n = len(grid.starts)
    profiled = [leaf for leaf in leaves if leaf.spec is not None]
    reject_duplicates(leaf.spec for leaf in profiled)
    by_code: dict[str, list[Leaf]] = {}
    for leaf in leaves:
        by_code.setdefault(leaf.category_field, []).append(leaf)
    item_codes = {item.code for item in construction.capex_items}
    items_out: list[ConstructionCapexTimingInput] = []
    bound_weights: dict[str, tuple[float, ...]] = {}
    default_weights: dict[str, tuple[float, ...]] = {}
    for item in construction.capex_items:
        default = _spread_default(item.payment_weights, grid)
        category_leaves = by_code.get(item.code, [])
        weights = default
        if any(leaf.spec is not None for leaf in category_leaves):
            total = float(category_amounts_keur.get(item.code, 0.0))
            if abs(sum(leaf.amount_keur for leaf in category_leaves) - total) > max(AMOUNT_TOLERANCE_KEUR, 1e-9 * abs(total)):
                raise BindingUnsupported("CAPEX_BINDING_AMOUNT_MISMATCH",
                                         f"{item.code}: leaves sum to {sum(l.amount_keur for l in category_leaves)!r}, category is {total!r}")
            if total <= 0:
                raise BindingUnsupported("CAPEX_BINDING_ZERO_CATEGORY", item.code)
            acc = [Fraction(0)] * n
            plain = Fraction(total)
            for leaf in category_leaves:
                if leaf.spec is None:
                    continue
                a = Fraction(leaf.amount_keur)
                plain -= a
                for k, w in enumerate(build_weights(leaf.spec, n)):
                    acc[k] += a * w
            for k in range(n):
                acc[k] += plain * Fraction(default[k])
            weights = [float(x / Fraction(total)) for x in acc]
            bound_weights[item.code] = tuple(weights)
            default_weights[item.code] = tuple(default)
        items_out.append(dataclasses.replace(item, payment_weights=tuple(weights)))
    stray = sorted({leaf.category_field for leaf in profiled} - item_codes)
    if stray:
        raise BindingUnsupported("CAPEX_BINDING_CATEGORY_NOT_IN_CONSTRUCTION", ", ".join(stray))
    fee = construction.structuring_fee
    fee_out: ConstructionStructuringFeeInput | None = fee
    if fee is not None:
        fee_out = dataclasses.replace(fee, payment_weights=tuple(_spread_default(fee.payment_weights, grid)) if fee.payment_weights else ())
    bound = dataclasses.replace(construction, periods=expand_to_months(construction, grid), capex_items=tuple(items_out), structuring_fee=fee_out)
    evidence = BindingEvidence(n, grid, tuple(sorted(leaf.item_key for leaf in profiled)), bound_weights, default_weights)
    return BoundConstruction(bound, evidence)
