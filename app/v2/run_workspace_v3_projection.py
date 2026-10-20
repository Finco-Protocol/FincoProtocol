"""Institutional multi-Run comparison V3: presentation over committed evidence only.

The canonical Run History repository, Decision Support variance/lineage and
Credit V4 period identity remain the authorities. There are no engine calls,
persistence writes, or new financial calculations. Missing evidence is never 0.
"""
from __future__ import annotations

from datetime import date
import math
from typing import Any, Mapping, Sequence

from app.v2.decision_support_projection import (
    _METRICS, _fmt, _variance_fields, build_assumption_attribution,
    build_assumption_diff, build_assumption_limitations, run_metric_view,
)
from app.v2.output_metric_projection import KPI_CATALOG

MAX_RUNS = 3
MAX_PERIOD_ROWS = 90
UNAVAILABLE = "UNAVAILABLE"

# Additional catalog values are shown only when actually persisted; no
# reconstruction of CFADS, NPV, reserves or financing from other amounts.
_EXTRA = tuple(
    (key, label, "economics" if key == "total_cfads_keur" else
     "returns" if key == "equity_npv_keur" else "debt",
     "pct" if unit == "%" else "x" if unit == "x" else "keur")
    for key, label, unit, _format, _source in KPI_CATALOG
    if key in ("total_cfads_keur", "equity_npv_keur", "target_dscr")
    and key not in {m[0] for m in _METRICS}
)
CATALOG = tuple(_METRICS) + _EXTRA


def _finite(value: Any) -> float | None:
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        return None
    number = float(value)
    return number if math.isfinite(number) else None


def _mapping(value: Any) -> dict:
    return value if isinstance(value, dict) else {}


def _side_metrics(side: Mapping[str, Any]) -> dict[str, float | None]:
    result = run_metric_view(
        _mapping(side.get("runtime_summary")),
        _mapping(side.get("sponsor_schedule")).get("summary") or {},
        _mapping(side.get("debt_schedule")).get("summary") or {},
    )
    for key, _label, _section, _kind in _EXTRA:
        # Extra fields use only their documented persisted catalog source.
        source = next((m[4] for m in KPI_CATALOG if m[0] == key), "")
        raw = (_mapping(side.get("debt_schedule")).get("summary") or {}
               if source == "debt_schedule.summary" else
               _mapping(side.get("sponsor_schedule")).get("summary") or {}
               if source == "sponsor_schedule.summary" else
               _mapping(side.get("runtime_summary")))
        result[key] = _finite(raw.get(key)) if isinstance(raw, dict) else None
    return result


def build_kpi_sections(sides: Sequence[Mapping[str, Any]], reference: int,
                       changed_only: bool = False, unavailable_only: bool = False) -> list[dict]:
    """Existing signed variance arithmetic, applied to 2–3 persisted sides."""
    if len(sides) not in (2, 3) or reference not in range(len(sides)):
        raise ValueError("RUN_WORKSPACE_SELECTION_INVALID")
    metrics = [_side_metrics(side) for side in sides]
    sections: list[dict] = []
    names = {
        "returns": "Returns", "economics": "Project Economics",
        "debt": "Debt", "sponsor": "Sponsor", "tax": "Tax",
        "reserves": "Reserves / Cash",
    }
    for section, title in names.items():
        rows = []
        for key, label, category, kind in CATALOG:
            if section != category:
                continue
            values = [m.get(key) for m in metrics]
            unavailable = any(value is None for value in values)
            changed = any(
                value is not None and values[reference] is not None
                and value != values[reference]
                for i, value in enumerate(values) if i != reference
            )
            if changed_only and not changed:
                continue
            if unavailable_only and not unavailable:
                continue
            deltas = []
            for i, value in enumerate(values):
                if i == reference:
                    deltas.append("—")
                else:
                    signed, _pp, _percent, _direction = _variance_fields(
                        kind, values[reference], value)
                    deltas.append(signed)
            rows.append({
                "key": key, "label": label, "kind": kind,
                "values": [_fmt(kind, value) for value in values],
                "deltas": deltas, "changed": changed,
                "unavailable": unavailable, "source": "Committed Run",
            })
        if rows:
            sections.append({"key": section, "title": title, "rows": rows})
    return sections


def build_lineage(sides: Sequence[Mapping[str, Any]], reference: int) -> list[dict]:
    """Per-selected comparison; output movement is NEVER attributed to inputs."""
    base = sides[reference]
    result = []
    for i, selected in enumerate(sides):
        if i == reference:
            continue
        a = _mapping(base.get("last_runtime_identity"))
        b = _mapping(selected.get("last_runtime_identity"))
        rows = build_assumption_diff(
            a, b, _mapping(base.get("runtime_summary")),
            _mapping(selected.get("runtime_summary")))
        attribution = build_assumption_attribution(
            a, b, rows, hash_a=base.get("composite_hash"),
            hash_b=selected.get("composite_hash"))
        limits = ([] if attribution.status == "IDENTICAL" else
                  build_assumption_limitations(
                      a, b, _mapping(base.get("runtime_summary")),
                      _mapping(selected.get("runtime_summary"))))
        result.append({
            "index": i, "status": attribution.status,
            "message": attribution.message, "caveat": attribution.caveat,
            "rows": rows, "limitations": limits,
            "causality": "CAUSALITY UNAVAILABLE — committed input differences and result movement are observations only.",
        })
    return result


def _frequency(side: Mapping[str, Any]) -> str:
    """Use a *committed* frequency; do not infer one from the Working Copy."""
    summary = _mapping(side.get("runtime_summary"))
    identity = _mapping(side.get("last_runtime_identity"))
    for container in (summary, identity):
        value = container.get("operating_frequency")
        if value in ("3/3", "6/6"):
            return value
        calendar = container.get("operating_calendar_policy")
        if isinstance(calendar, dict):
            freq = calendar.get("operating_months")
            if freq in (3, 6):
                return "3/3" if freq == 3 else "6/6"
    # Released default: absence of any quarterly selection means 6/6.
    # A present but unknown policy must not silently fall back.
    if any("operating_frequency" in obj or "operating_calendar_policy" in obj
           for obj in (summary, identity)):
        return "UNKNOWN"
    return "6/6"


def _period_evidence(side: Mapping[str, Any]) -> dict:
    from types import SimpleNamespace
    from app.v2.credit_decision_projection import RunInput, _timeline
    from app.v2.credit_v4_evidence import _periods

    entry = side.get("entry")
    if entry is None:
        # A legacy Last Run with no ledger entry is NOT a fabricated historical
        # row. Its own persisted schedules are the only permissible inputs.
        entry = SimpleNamespace(
            integrity_evidence=_mapping(side.get("integrity_evidence")),
            debt_schedule=_mapping(side.get("debt_schedule")),
            distribution_schedule=_mapping(side.get("distribution_schedule")),
            sponsor_schedule=_mapping(side.get("sponsor_schedule")),
        )
    return _periods(_timeline(RunInput(entry=entry)))


def build_period_grid(sides: Sequence[Mapping[str, Any]], reference: int,
                      changed_only: bool = False, unavailable_only: bool = False,
                      offset: int = 0) -> dict:
    """Use Credit V4's validated committed start/end interval evidence.

    The grid never joins by index, annualises a flow, sums a stock or ratio,
    or compares 3/3 with 6/6. Source keys are the Credit V4 timeline keys.
    """
    from app.v2.credit_v4_evidence import METRICS
    if offset < 0 or offset > 10000:
        raise ValueError("RUN_WORKSPACE_OFFSET_INVALID")
    sources = [_period_evidence(s) for s in sides]
    frequencies = {_frequency(s) for s in sides}
    if len(frequencies) != 1 or "UNKNOWN" in frequencies:
        return {"available": False, "reason": "PERIOD_FREQUENCY_MISMATCH_OR_UNAVAILABLE",
                "rows": [], "excluded": [], "count": 0}
    if any(not source["valid"] for source in sources):
        return {"available": False, "reason": "PERIOD_EVIDENCE_UNAVAILABLE",
                "rows": [], "excluded": [], "count": 0}
    dates = set(sources[reference]["by_date"])
    for source in sources:
        dates &= set(source["by_date"])
    rows, excluded = [], []
    for end in sorted(dates):
        starts = [source["starts"].get(end) for source in sources]
        if any(start is None for start in starts):
            excluded.append({"date": end, "reason": "PERIOD_START_NOT_COMMITTED"})
            continue
        if len(set(starts)) != 1:
            excluded.append({"date": end, "reason": "PERIOD_INTERVAL_DIFFERS"})
            continue
        if starts[0] >= end:
            excluded.append({"date": end, "reason": "PERIOD_INTERVAL_INVALID"})
            continue
        for key, label, unit in METRICS:
            values = [source["by_date"][end].get(key) for source in sources]
            unavailable = any(v is None for v in values)
            changed = any(
                v is not None and values[reference] is not None
                and v != values[reference]
                for i, v in enumerate(values) if i != reference
            )
            if changed_only and not changed:
                continue
            if unavailable_only and not unavailable:
                continue
            def render(value):
                return UNAVAILABLE if value is None else (
                    f"{value:,.2f}x" if unit == "x" else f"{value:,.2f}")
            delta = [
                "—" if i == reference or values[reference] is None or v is None
                else (f"{(v-values[reference]):+.2f}x" if unit == "x"
                      else f"{(v-values[reference]):+,.2f}")
                for i, v in enumerate(values)
            ]
            rows.append({
                "start": starts[0], "end": end, "key": key, "label": label,
                "values": [render(v) for v in values], "deltas": delta,
                "unavailable": unavailable, "changed": changed,
            })
    if not dates:
        reason = "PERIOD_END_DATES_DO_NOT_MATCH"
    elif not rows and excluded:
        reason = "PERIOD_INTERVALS_NOT_COMPARABLE"
    else:
        reason = ""
    return {
        "available": bool(dates) and (bool(rows) or not excluded),
        "reason": reason, "rows": rows[offset:offset + MAX_PERIOD_ROWS],
        "count": len(rows), "next_offset": offset + MAX_PERIOD_ROWS
        if offset + MAX_PERIOD_ROWS < len(rows) else None,
        "excluded": excluded[:20], "excluded_count": len(excluded),
        "basis": "Credit V4 committed period intervals. Δ = Selected − Reference; no aggregation or causal attribution.",
    }
