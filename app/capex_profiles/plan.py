"""Planner projection: validated per-item profiles -> monthly uses, cumulative/remaining, period equivalents.

Pure over (items, specs, timeline).  Rows are validated independently so one invalid row never hides the others, but an invalid
row is reported with its amount as UNALLOCATED and is excluded from every total (nothing is normalised or guessed).
"""
from __future__ import annotations

from dataclasses import dataclass, field
from decimal import Decimal
from typing import Mapping, Sequence

from app.capex_profiles.contract import ProfileError, ProfileResult, ProfileSpec, aggregate_by_group, allocate
from app.capex_profiles.projection import CapexItemView, Timeline

PREVIEW_NOTICE = ("PREVIEW ONLY - hypothetical allocation. Nothing is saved and no Run was started; the committed Run, its "
                  "construction funding, IDC and Sources & Uses are unchanged.")


@dataclass(frozen=True)
class RowOutcome:
    item: CapexItemView
    spec: ProfileSpec | None
    result: ProfileResult | None
    error_code: str | None
    error_detail: str | None
    unallocated_keur: Decimal
    period_equivalent_keur: tuple[Decimal, ...] = ()


@dataclass(frozen=True)
class PlanView:
    months: int
    timeline: Timeline
    rows: tuple[RowOutcome, ...]
    monthly_total_keur: tuple[Decimal, ...]
    monthly_cumulative_keur: tuple[Decimal, ...]
    monthly_remaining_keur: tuple[Decimal, ...]
    planned_total_keur: Decimal
    profiled_total_keur: Decimal
    unallocated_total_keur: Decimal
    period_equivalent_total_keur: tuple[Decimal, ...] = ()
    global_errors: tuple[str, ...] = ()
    notice: str = PREVIEW_NOTICE
    canonical: bool = False             # this view is never a canonical financial input


def build_plan(items: Sequence[CapexItemView], specs: Sequence[ProfileSpec], months: int, timeline: Timeline,
               *, excluded_keys: frozenset[str] = frozenset(), inactive_keys: frozenset[str] = frozenset()) -> PlanView:
    by_key = {i.item_key: i for i in items}
    global_errors: list[str] = []
    seen: set[str] = set()
    outcomes: list[RowOutcome] = []
    groups = (max(timeline.month_to_period) + 1) if timeline.available and timeline.month_to_period else 0
    group_map = timeline.month_to_period if timeline.available and len(timeline.month_to_period) == months else ()
    for spec in specs:
        if spec.item_key in seen:
            global_errors.append(f"CAPEX_PROFILE_DUPLICATE_ITEM: {spec.item_key}")
            continue
        seen.add(spec.item_key)
        item = by_key.get(spec.item_key)
        if item is None:
            code = ("CAPEX_PROFILE_ITEM_NOT_ELIGIBLE" if spec.item_key in excluded_keys else
                    "CAPEX_PROFILE_ITEM_INACTIVE" if spec.item_key in inactive_keys else "CAPEX_PROFILE_UNKNOWN_ITEM")
            global_errors.append(f"{code}: {spec.item_key}")
            continue
        try:
            result = allocate(spec, item.amount_keur, months)
            eq = aggregate_by_group(result, group_map, groups) if group_map else ()
            outcomes.append(RowOutcome(item, spec, result, None, None, Decimal(0), eq))
        except ProfileError as exc:
            amount = Decimal(str(item.amount_keur))
            outcomes.append(RowOutcome(item, spec, None, exc.code, str(exc), amount))
    for item in items:                                   # items without any submitted spec are simply unprofiled (not an error)
        if item.item_key not in seen:
            outcomes.append(RowOutcome(item, None, None, None, None, Decimal(0)))
    monthly = [Decimal(0)] * months
    period_total = [Decimal(0)] * groups if group_map else []
    for row in outcomes:
        if row.result is not None:
            for m in row.result.months:
                monthly[m.month - 1] += m.amount_keur
            for g, v in enumerate(row.period_equivalent_keur):
                period_total[g] += v
    profiled = sum((r.result.total_keur for r in outcomes if r.result is not None), Decimal(0))
    planned = sum((Decimal(str(i.amount_keur)) for i in items), Decimal(0))
    cumulative, remaining, running = [], [], Decimal(0)
    for v in monthly:
        running += v
        cumulative.append(running)
        remaining.append(profiled - running)
    return PlanView(months, timeline, tuple(outcomes), tuple(monthly), tuple(cumulative), tuple(remaining), planned, profiled,
                    sum((r.unallocated_keur for r in outcomes), Decimal(0)), tuple(period_total), tuple(global_errors))
