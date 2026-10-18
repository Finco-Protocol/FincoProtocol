"""Read-only CAPEX item catalogue and construction timeline for the planner.

Reuses the existing authorities and writes nothing:
  * amounts: the workspace input set (category scalar inputs) and the active ``capex_sub_lines`` rows - exactly the rows the
    existing folding adds into the canonical category amounts;
  * timeline: the existing ``PeriodEngine`` fed with the project's own financial-close / construction / COD inputs, using the
    same construction-period convention as ``derive_construction_financing`` (period end exclusive);
  * C.13 contingency, C.17/C.18, IDC, bank/commitment fees, VAT costs and reserves are DERIVED or financing items and are not
    spending-profile eligible.
"""
from __future__ import annotations

from dataclasses import dataclass
from datetime import date, timedelta
from typing import Any, Optional

from app.persistence.capex_sub_lines import (
    ALLOWED_PARENT_CATEGORIES, CAPEX_CATEGORY_TO_FIELD, REJECTED_PARENT_CATEGORIES, get_active_sub_lines_for_project,
)
from app.workbook.registry import WORKBOOK
from app.workbook.specs import FieldKind

KIND_CATEGORY_BASE = "CATEGORY_BASE"
KIND_SUB_LINE = "SUB_LINE"


@dataclass(frozen=True)
class CapexItemView:
    item_key: str
    kind: str                       # CATEGORY_BASE | SUB_LINE
    label: str
    category_code: str
    amount_keur: float
    eligible: bool = True


@dataclass(frozen=True)
class Timeline:
    available: bool
    reason: str
    months: int
    month_start: tuple[date, ...] = ()
    month_to_period: tuple[int, ...] = ()
    period_starts: tuple[date, ...] = ()
    period_ends: tuple[date, ...] = ()          # inclusive last day, as in the construction financing input
    source: str = ""


def _field_to_category() -> dict[str, str]:
    out: dict[str, str] = {}
    for code, field in CAPEX_CATEGORY_TO_FIELD.items():
        out.setdefault(field, code)
    return out


def catalogue(pis, project_id: str) -> tuple[tuple[CapexItemView, ...], tuple[CapexItemView, ...]]:
    """(eligible items, excluded derived/financing items).  Parent roll-ups are never items, so nothing is counted twice."""
    cat_of = _field_to_category()
    eligible: list[CapexItemView] = []
    excluded: list[CapexItemView] = []
    for spec in WORKBOOK.all_fields():
        if not spec.field_id.startswith("capex."):
            continue
        suffix = spec.field_id.rsplit(".", 1)[-1]
        field_name = "ops_prep" if suffix == "ops_preparation" else suffix
        if spec.kind != FieldKind.INPUT or not spec.editable:
            if spec.field_id != "capex.summary.total":
                value = pis.get(spec.field_id)
                excluded.append(CapexItemView(spec.field_id, "DERIVED", spec.label, cat_of.get(field_name, ""),
                                              float(value) if isinstance(value, (int, float)) else 0.0, False))
            continue
        value = pis.get(spec.field_id)
        try:
            amount = float(value) if value is not None else 0.0
        except (TypeError, ValueError):
            amount = 0.0
        if amount > 0:
            eligible.append(CapexItemView(spec.field_id, KIND_CATEGORY_BASE, spec.label, cat_of.get(field_name, ""), amount))
    for sub in get_active_sub_lines_for_project(project_id):
        if sub.parent_category_code in REJECTED_PARENT_CATEGORIES or sub.parent_category_code not in ALLOWED_PARENT_CATEGORIES:
            excluded.append(CapexItemView(sub.business_code, "DERIVED", sub.label, sub.parent_category_code, sub.amount_keur, False))
        elif CAPEX_CATEGORY_TO_FIELD.get(sub.parent_category_code) == "contingencies":
            excluded.append(CapexItemView(sub.business_code, "DERIVED", sub.label, sub.parent_category_code, sub.amount_keur, False))
        elif sub.amount_keur > 0:
            eligible.append(CapexItemView(sub.business_code, KIND_SUB_LINE, sub.label, sub.parent_category_code, float(sub.amount_keur)))
    return tuple(eligible), tuple(excluded)


def _add_months(d: date, months: int) -> date:
    y, m = divmod(d.month - 1 + months, 12)
    year, month = d.year + y, m + 1
    day = min(d.day, [31, 29 if year % 4 == 0 and (year % 100 or year % 400 == 0) else 28, 31, 30, 31, 30, 31, 31, 30, 31, 30, 31][month - 1])
    return date(year, month, day)


def build_timeline(snapshot: dict[str, Any], months: int) -> Timeline:
    """Month dates and the existing construction-period index of each month.  Degrades to 'unavailable' rather than inventing dates."""
    try:
        from app.input_adapter import build_projectinputs_from_snapshot
        from finco_core.engine.period_engine import PeriodEngine, PeriodFrequency as EnginePeriodFrequency
        from finco_core.inputs import PeriodFrequency as InputPeriodFrequency
        pi = build_projectinputs_from_snapshot(snapshot)
        info = pi.info
        if info.period_frequency != InputPeriodFrequency.SEMESTRIAL:
            return Timeline(False, "UNSUPPORTED_PERIOD_FREQUENCY", months)      # same boundary as the construction financing derivation
        engine = PeriodEngine(
            financial_close=info.financial_close, construction_months=info.construction_months, horizon_years=info.horizon_years,
            ppa_years=pi.revenue.ppa_term_years, frequency=EnginePeriodFrequency.SEMESTRIAL, cod_date=info.cod_date,
            period_axis_convention=getattr(info.period_axis_convention, "value", info.period_axis_convention))
        construction = [p for p in engine.periods() if p.is_construction]
        if not construction:
            return Timeline(False, "NO_CONSTRUCTION_PERIODS", months)
        starts = tuple(p.start_date for p in construction)
        ends = tuple(p.end_date - timedelta(days=1) for p in construction)
        month_start = tuple(_add_months(info.financial_close, k) for k in range(months))
        mapping = []
        for ms in month_start:
            idx = 0
            for i, (s, e) in enumerate(zip(starts, ends)):
                if s <= ms <= e:
                    idx = i
                    break
            else:
                idx = len(starts) - 1 if ms > ends[-1] else 0
            mapping.append(idx)
        return Timeline(True, "", months, month_start, tuple(mapping), starts, ends, "PeriodEngine (project financial close / construction / COD inputs)")
    except Exception as exc:                                    # noqa: BLE001 - any timeline failure must degrade, never guess
        return Timeline(False, f"TIMELINE_UNAVAILABLE:{type(exc).__name__}", months)

