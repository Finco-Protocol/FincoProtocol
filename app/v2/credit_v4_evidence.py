"""Credit V4: read-only lender risk and date-exact committed Run comparison.

Consumes the Credit V3 projection (never calls a solver, DB, or persistence API).
A missing/invalid period is unavailable; a convergence flag never implies bankability.
"""
from __future__ import annotations

from datetime import date
import math
from typing import Any, Mapping, Sequence

VERSION = "RC7_CREDIT_DECISION_V4_READONLY"
METRICS = (
    ("base_cfads", "Base CFADS", "kEUR"),
    ("bank_cfads", "Lender-case CFADS", "kEUR"),
    ("debt_service", "Senior debt service", "kEUR"),
    ("dscr", "Reported DSCR", "x"),
    ("closing", "Senior closing balance", "kEUR"),
    ("dsra_balance", "Cash DSRA balance", "kEUR"),
    ("distribution", "Paid distributions", "kEUR"),
)
MAX_COLUMNS = 180
MAX_DETAIL = 90


def _finite(value: Any) -> float | None:
    if isinstance(value, bool) or not isinstance(value, (float, int)):
        return None
    val = float(value)
    return val if math.isfinite(val) else None


def _date(raw: Any) -> str | None:
    if not isinstance(raw, str) or len(raw) != 10:
        return None
    try:
        dt = date.fromisoformat(raw)
    except ValueError:
        return None
    return raw if dt.isoformat() == raw else None


def _as_mapping(data: Any) -> Mapping:
    return data if isinstance(data, Mapping) else {}


def _value(row: Any) -> float | None:
    return _finite(_as_mapping(row).get("v"))


def _fmt(value: float | None, unit: str) -> str:
    if value is None:
        return "UNAVAILABLE"
    return f"{value:,.2f}{'x' if unit == 'x' else ''}"


def _periods(view: Mapping) -> dict[str, Any]:
    timeline = _as_mapping(view.get("timeline"))
    if not timeline.get("available"):
        return {"valid": False, "by_date": {}, "reason": str(timeline.get("reason") or "NO_COMMITTED_DEBT_PERIODS"),
                "missing": ["DEBT_PERIOD_EVIDENCE_UNAVAILABLE"], "count": 0}
    columns = timeline.get("columns")
    rows = timeline.get("rows")
    if not isinstance(columns, (list, tuple)) or not isinstance(rows, (list, tuple)) or not columns or len(columns) > MAX_COLUMNS:
        return {"valid": False, "by_date": {}, "reason": "PERIOD_DIMENSION_INVALID_OR_UNBOUNDED", "missing": ["PERIOD_DIMENSION_INVALID"], "count": 0}
    dates: list[str] = []
    indexes: list[int] = []
    for col in columns:
        c = _as_mapping(col)
        d, i = _date(c.get("date")), c.get("index")
        if d is None or isinstance(i, bool) or not isinstance(i, int) or i < 1:
            return {"valid": False, "by_date": {}, "reason": "PERIOD_DATE_OR_INDEX_MISSING", "missing": ["PERIOD_DATE_OR_INDEX_MISSING"], "count": len(columns)}
        dates.append(d)
        indexes.append(i)
    if dates != sorted(set(dates)) or len(set(indexes)) != len(indexes) or indexes != sorted(indexes):
        return {"valid": False, "by_date": {}, "reason": "PERIOD_DATE_OR_INDEX_COLLISION", "missing": ["PERIOD_DATE_OR_INDEX_COLLISION"], "count": len(columns)}
    matrix = {}
    for row in rows:
        r = _as_mapping(row)
        key = r.get("key")
        if not isinstance(key, str) or key in matrix:
            return {"valid": False, "by_date": {}, "reason": "PERIOD_METRIC_ID_INVALID", "missing": ["PERIOD_METRIC_ID_INVALID"], "count": len(columns)}
        cells = r.get("cells")
        if not isinstance(cells, (tuple, list)) or len(cells) != len(columns):
            return {"valid": False, "by_date": {}, "reason": "PERIOD_VECTOR_SHAPE_MISMATCH", "missing": ["PERIOD_VECTOR_SHAPE_MISMATCH"], "count": len(columns)}
        matrix[key] = cells
    required = {"dscr", "debt_service", "base_cfads", "closing"}
    if not required.issubset(matrix):
        return {"valid": False, "by_date": {}, "reason": "REQUIRED_DEBT_METRIC_ABSENT", "missing": ["REQUIRED_DEBT_METRIC_ABSENT"], "count": len(columns)}
    by_date = {d: {key: _value(cell[idx]) for key, cell in matrix.items()}
               for idx, d in enumerate(dates)}
    missing = []
    for d, row in by_date.items():
        # Only service periods require coverage; zero or absent debt service is not proof of a serviced period.
        debt = row.get("debt_service")
        if debt is None or debt < 0:
            missing.append(f"{d}:DEBT_SERVICE_UNAVAILABLE_OR_INVALID")
        elif debt > 0 and (row.get("dscr") is None or row.get("base_cfads") is None or row.get("closing") is None):
            missing.append(f"{d}:COVERAGE_OR_BALANCE_UNAVAILABLE")
    return {"valid": True, "by_date": by_date, "reason": "", "missing": missing, "count": len(dates)}


def _risk(view: Mapping, per: Mapping[str, Any]) -> dict[str, Any]:
    ident = _as_mapping(view.get("identity"))
    capacity = _as_mapping(view.get("capacity"))
    minimum = _value(capacity.get("min_dscr"))
    integrity = ident.get("integrity")
    low = [d for d, row in per["by_date"].items()
           if row.get("debt_service") is not None and row["debt_service"] > 0 and
           row.get("dscr") is not None and row["dscr"] < 1.0 - 1e-12]
    reasons = []
    if integrity != "PASS":
        reasons.append("RUN_INTEGRITY_NOT_PROVEN_PASS")
    if not per["valid"]:
        reasons.append(per["reason"])
    if per["missing"]:
        reasons.append("MISSING_OR_INVALID_PERIOD_EVIDENCE")
    if low or (minimum is not None and minimum < 1.0 - 1e-12):
        reasons.append("OBSERVED_DSCR_BELOW_ONE")
    if minimum is None:
        reasons.append("MIN_DSCR_UNAVAILABLE")
    status = "REVIEW_REQUIRED" if reasons else "OBSERVED_ONLY_NO_SHORTFALL_IDENTIFIED"
    return {
        "history_id": ident.get("history_id"), "scenario": ident.get("scenario"),
        "state": ident.get("state"), "integrity": integrity, "status": status,
        "reasons": reasons, "min_dscr": _fmt(minimum, "x"),
        "period_count": per["count"], "bad_period_dates": low[:12],
        "missing_count": len(per["missing"]), "missing_reasons": per["missing"][:12],
        "links": _as_mapping(view.get("links")),
        "disclosure": "Read-only observed screening, not an approval, covenant test, event of default or solver feasibility verdict."}


def build_credit_v4(views: Sequence[Mapping[str, Any]]) -> dict[str, Any]:
    """Date-aligned observational evidence over 1–3 already authorized committed Runs.

    All cross-Run deltas require identical, valid committed period-end dates.
    Different period axes are not aligned by index; missing data is never zero.
    """
    if not 1 <= len(views) <= 3:
        raise ValueError("CREDIT_V4_RUN_COUNT_INVALID")
    ids = [_as_mapping(v.get("identity")).get("history_id") for v in views]
    if any(not isinstance(i, str) or not i for i in ids) or len(set(ids)) != len(ids):
        raise ValueError("CREDIT_V4_RUN_ID_INVALID")
    parsed = [_periods(v) for v in views]
    risks = [_risk(v, p) for v, p in zip(views, parsed)]
    if len(parsed) == 1:
        comparison = {"available": False, "reason": "Select two or three committed Runs for date-exact comparison.", "rows": []}
    elif len({str(v.get("operating_frequency") or "6/6") for v in views}) > 1:
        # RC-7B: identical end dates on a 3-month and a 6-month axis measure
        # different intervals; an end-date-only join would compare unlike flows.
        comparison = {"available": False, "reason": "The selected Runs use different operating/debt frequencies; "
                      "date joins across different interval lengths are unavailable.", "rows": []}
    elif not all(p["valid"] for p in parsed):
        comparison = {"available": False, "reason": "At least one Run lacks valid period dates/identity; index-based matching is prohibited.", "rows": []}
    else:
        common = set(parsed[0]["by_date"])
        for p in parsed[1:]:
            common &= set(p["by_date"])
        if not common:
            comparison = {"available": False, "reason": "No identical committed period-end dates; comparisons across mismatched period axes are unavailable.", "rows": []}
        else:
            changed, missing, unchanged = [], [], 0
            for d in sorted(common):
                for key, label, unit in METRICS:
                    cells = [p["by_date"][d].get(key) for p in parsed]
                    values = [_fmt(c, unit) for c in cells]
                    delta = [None if cells[0] is None or x is None else x - cells[0] for x in cells[1:]]
                    state = "UNAVAILABLE" if any(c is None for c in cells) else (
                        "CHANGED" if any(abs(z) > 1e-12 for z in delta) else "UNCHANGED")
                    result = {"date": d, "metric": label, "key": key, "unit": unit,
                              "state": state, "values": values,
                              "deltas": [_fmt(x, unit) for x in delta],
                              "reason": "Metric missing from one or more committed Runs." if state == "UNAVAILABLE" else ""}
                    if state == "CHANGED":
                        changed.append(result)
                    elif state == "UNAVAILABLE":
                        missing.append(result)
                    else:
                        unchanged += 1
            # Exceptions / changes first, deterministic dates and metric ordering.
            all_rows = changed + missing
            comparison = {"available": True, "reason": "", "rows": all_rows[:MAX_DETAIL],
                          "changed": len(changed), "unavailable": len(missing), "unchanged": unchanged,
                          "truncated": len(all_rows) > MAX_DETAIL, "common_periods": len(common),
                          "excluded_dates": [len(p["by_date"]) - len(common) for p in parsed],
                          "basis": "Exact committed ISO period-end dates; signed differences against Run 1. "
                                   "CHANGED is not a materiality verdict or evidence of causation. "
                                   "No position-based join, missing-as-zero, contractual interpretation or recalculation."}
    return {"schema": VERSION, "run_risks": risks, "period_comparison": comparison,
            "unavailable": [
                {"metric": "PLCR", "reason": "No persisted PLCR or approved discount/cash-flow horizon basis."},
                {"metric": "Contractual covenant/default", "reason": "No source-proven contractual covenant dates, thresholds or EoD trigger."},
                {"metric": "DSRA/DSRF contractual coverage", "reason": "No approved coverage period/required funding or standby-facility terms persisted with every Run."},
                {"metric": "Cash sweep obligation", "reason": "No sourced contractual cash-sweep policy; observed sweep values alone do not prove covenant compliance."},
                {"metric": "Per-period revenue/sponsor returns", "reason": "This V4 date join uses only proven V3 credit timeline metrics. Revenue and sponsor-return period attribution require separately validated statement-row identity."},
            ]}


__all__ = ["VERSION", "METRICS", "build_credit_v4"]
