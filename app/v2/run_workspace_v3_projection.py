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
                "unit": "%" if kind == "pct" else "x" if kind == "x" else "kEUR",
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


# Whitelist of existing Statements V2 committed model-period rows. No
# total/reaggregation logic is present. Stock variables remain point-in-time.
_STATEMENT_LINES = (
    ("pnl", "revenues_keur", "P&L · Revenue"),
    ("pnl", "operating_expenses_keur", "P&L · OPEX"),
    ("pnl", "depreciation_keur", "P&L · Depreciation"),
    ("pnl", "ebit_keur", "P&L · EBIT"),
    ("pnl", "net_income_keur", "P&L · Net income"),
    ("cash_flow", "revenue_cash_keur", "Cash Flow · Revenue received"),
    ("cash_flow", "opex_cash_keur", "Cash Flow · OPEX paid"),
    ("cash_flow", "ebitda_cash_keur", "Cash Flow · EBITDA cash"),
    ("cash_flow", "fcf_banks_keur", "Cash Flow · CFADS to Senior"),
    ("cash_flow", "cash_tax_keur", "Cash Flow · Cash tax"),
    ("cash_flow", "net_dividends_keur", "Cash Flow · Net dividends"),
    ("balance_sheet", "senior_balance_keur", "Balance Sheet · Senior balance"),
    ("balance_sheet", "dsra_balance_keur", "Balance Sheet · DSRA balance"),
    ("balance_sheet", "cash_keur", "Balance Sheet · Cash"),
    ("balance_sheet", "balance_check_keur", "Balance Sheet · Balance check"),
)


def _statement_rows(side: Mapping[str, Any]) -> dict[str, dict[str, float | None]]:
    """Read existing Statements V2 model-period cells; never aggregate years.

    The adapter uses only this Run's own immutable payloads. A column without
    a valid committed date, a duplicate date or a malformed cell is excluded.
    The caller separately proves the exact economic interval via Credit V4.
    """
    from types import SimpleNamespace
    from app.v2.statement_presentation import statements_from_run
    from app.v2.historical_statements import _run_result_view

    entry = side.get("entry")
    if entry is not None:
        source = _run_result_view(entry)
    else:
        source = SimpleNamespace(
            debt_schedule=_mapping(side.get("debt_schedule")),
            tax_schedule=_mapping(side.get("tax_schedule")),
            financial_statements=_mapping(side.get("financial_statements")),
            runtime_summary=_mapping(side.get("runtime_summary")),
            sponsor_schedule=_mapping(side.get("sponsor_schedule")),
            distribution_schedule=_mapping(side.get("distribution_schedule")),
            snapshot_id=side.get("snapshot_id"),
            ran_at=side.get("ran_at"), origin=side.get("origin"),
        )
    try:
        tables = statements_from_run(source, False)
    except Exception:
        # Missing/legacy or malformed statement evidence: no synthesized rows.
        return {}
    out: dict[str, dict[str, float | None]] = {}
    permitted = {(t, k) for t, k, _label in _STATEMENT_LINES}
    for table in tables:
        table_id = table.get("id")
        columns = table.get("columns")
        if table_id not in ("pnl", "cash_flow", "balance_sheet") or not isinstance(columns, list):
            continue
        dates = []
        for col in columns:
            end = col.get("date") if isinstance(col, dict) else None
            try:
                valid = isinstance(end, str) and len(end) == 10 and date.fromisoformat(end).isoformat() == end
            except ValueError:
                valid = False
            dates.append(end if valid else None)
        duplicates = {d for d in dates if d is not None and dates.count(d) > 1}
        for row in table.get("rows") or ():
            key = row.get("key")
            cells = row.get("cells")
            if (table_id, key) not in permitted or not isinstance(cells, list) or len(cells) != len(columns):
                continue
            for idx, end in enumerate(dates):
                if end is None or end in duplicates:
                    continue
                raw = cells[idx].get("v") if isinstance(cells[idx], dict) else None
                out.setdefault(end, {})[f"statement:{table_id}:{key}"] = _finite(raw)
    return out


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
    statements = [_statement_rows(s) for s in sides]
    frequencies = {_frequency(s) for s in sides}
    if len(frequencies) != 1 or "UNKNOWN" in frequencies:
        return {"available": False, "reason": "PERIOD_FREQUENCY_MISMATCH_OR_UNAVAILABLE",
                "rows": [], "excluded": [], "count": 0}
    if any(not source["valid"] for source in sources):
        return {"available": False, "reason": "PERIOD_EVIDENCE_UNAVAILABLE",
                "rows": [], "excluded": [], "count": 0}
    all_dates = set().union(*(set(source["by_date"]) for source in sources))
    dates = set(sources[reference]["by_date"])
    for source in sources:
        dates &= set(source["by_date"])
    unmatched = sorted(all_dates - dates)
    rows, excluded = [], [
        {"date": end, "reason": "PERIOD_NOT_PERSISTED_IN_EVERY_RUN"}
        for end in unmatched
    ]
    matched_intervals = 0
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
        matched_intervals += 1
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
                "unit": "x" if unit == "x" else "kEUR",
            })
        # The statement adapter returns committed cells on their own dated
        # columns. They join ONLY at this independently validated Credit V4
        # interval; they are never joined by their list position.
        for table_id, key, label in _STATEMENT_LINES:
            full_key = f"statement:{table_id}:{key}"
            values = [table.get(end, {}).get(full_key) for table in statements]
            if not any(v is not None for v in values):
                continue
            missing = any(v is None for v in values)
            moved = any(v is not None and values[reference] is not None
                        and v != values[reference]
                        for i, v in enumerate(values) if i != reference)
            if (changed_only and not moved) or (unavailable_only and not missing):
                continue
            rows.append({
                "start": starts[0], "end": end, "key": full_key, "label": label,
                "values": [UNAVAILABLE if v is None else f"{v:,.2f}" for v in values],
                "deltas": ["—" if i == reference or v is None or values[reference] is None
                           else f"{v - values[reference]:+,.2f}"
                           for i, v in enumerate(values)],
                "unavailable": missing, "changed": moved, "unit": "kEUR",
            })
    if not dates:
        reason = "PERIOD_END_DATES_DO_NOT_MATCH"
    elif not matched_intervals:
        reason = "PERIOD_INTERVALS_NOT_COMPARABLE"
    else:
        reason = ""
    return {
        "available": matched_intervals > 0,
        "reason": reason, "rows": rows[offset:offset + MAX_PERIOD_ROWS],
        "count": len(rows), "next_offset": offset + MAX_PERIOD_ROWS
        if offset + MAX_PERIOD_ROWS < len(rows) else None,
        "excluded": excluded[:20], "excluded_count": len(excluded),
        "unmatched_count": len(unmatched),
        "basis": "Credit V4 committed period intervals. Δ = Selected − Reference; no aggregation or causal attribution.",
    }
