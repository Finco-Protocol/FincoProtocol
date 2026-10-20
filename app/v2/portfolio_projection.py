"""Read-only portfolio observations over one immutable committed Run per project.

No portfolio return, covenant verdict, currency conversion or financial model
is calculated. Monetary subtotals are separated by recorded funding window.
"""
from __future__ import annotations

from collections import Counter, defaultdict
from dataclasses import dataclass
from datetime import date, datetime, timedelta
from decimal import Decimal, localcontext
from typing import Any
from urllib.parse import urlencode

from app.v2.decision_support_projection import run_metric_view
from app.v2.financing_sources_uses_projection import build_sources_uses_projection

MONEY = (
    ("capex", "Hard project CAPEX", "base_project_capex_keur"),
    ("uses", "Project uses", "total_uses_keur"),
    ("senior", "Senior financing", "senior_debt_keur"),
    ("equity", "Equity funding", "share_capital_and_other_equity_keur"),
    ("shl", "SHL funding", "shareholder_loan_cash_keur"),
    ("other", "Junior / other financing", "junior_or_other_keur"),
)
PERFORMANCE = (
    ("project_irr", "Project IRR", "pct"),
    ("equity_irr", "Pure Equity IRR", "pct"),
    ("total_sponsor_xirr", "Total Sponsor IRR", "pct"),
    ("min_dscr", "Min DSCR", "x"),
    ("avg_dscr", "Avg DSCR", "x"),
    ("min_llcr", "Min LLCR", "x"),
)
SORT_KEYS = {key for key, _, _ in MONEY + PERFORMANCE}
NA = "Unavailable"


@dataclass(frozen=True)
class ProjectEvidence:
    record: Any
    entry: Any = None
    freshness: str = "UNKNOWN"
    issue: str = ""


def _mapping(raw):
    return raw if isinstance(raw, dict) else {}


def _cell(value, kind="amount", source=""):
    # Shared Compare rejects strings, bools and non-finite financial numbers.
    import math
    try:
        valid = type(value) in (int, float) and math.isfinite(value)
    except OverflowError:
        valid = False
    value = value if valid else None
    display = NA if value is None else (
        f"{value * 100:.2f}%" if kind == "pct" else
        f"{value:.2f}x" if kind == "x" else f"{value:,.2f}")
    return {"value": value, "display": display, "source": source}


def _timestamp(raw):
    try:
        parsed = datetime.fromisoformat(raw.replace("Z", "+00:00"))
        return parsed.isoformat() if parsed.utcoffset() is not None else None
    except (AttributeError, TypeError, ValueError):
        return None


def _funding_window(finance):
    construction = _mapping(finance.get("construction_funding"))
    periods = construction.get("periods")
    if not isinstance(periods, (list, tuple)) or not periods:
        return None
    dates = []
    for period in periods:
        try:
            start = date.fromisoformat(period["period_start"])
            end = date.fromisoformat(period["period_end"])
            if start > end or (dates and (start < dates[-1][1] or start > dates[-1][1] + timedelta(days=1))):
                return None
            dates.append((start, end))
        except (KeyError, TypeError, ValueError):
            return None
    return dates[0][0].isoformat(), dates[-1][1].isoformat()


def _integrity(entry):
    if not entry.integrity_evidence:
        return NA
    try:
        from app.run_integrity import run_integrity_checks
        status = run_integrity_checks(entry.integrity_evidence).to_dict().get("overall")
        return status if status in ("PASS", "FAIL", "INCOMPLETE") else NA
    except Exception:
        return NA


def project_row(item: ProjectEvidence):
    record, entry = item.record, item.entry
    base = _mapping(record.baseline_snapshot)
    code = record.project_code
    row = {
        "code": code, "name": record.project_name,
        "technology": record.project_type or "Not set",
        "country": str(base.get("country_iso") or base.get("country") or "Not set"),
        "stage": record.project_stage or "Not set",
        "freshness": item.freshness, "integrity": NA, "issues": [],
        "history_id": None, "run_at": None, "engine": None, "workbook": None,
        "scenario": None, "snapshot": None, "hash": None, "cohort": None, "engine_state": "UNKNOWN",
        "aggregate_keys": (),
        "money": {key: _cell(None) for key, _, _ in MONEY},
        "metrics": {key: _cell(None, kind) for key, _, kind in PERFORMANCE},
        "gearing": _cell(None, "pct"),
        "project_url": "/v2/workbook?" + urlencode({"project": code}),
        "run_url": None, "credit_url": None,
    }
    if item.issue:
        row["issues"].append(item.issue)
    if entry is None:
        row["issues"].append("No readable committed Run" if item.issue else "No committed Run")
        return row
    if (entry.user_id != record.user_id or entry.project_id != record.project_id
            or entry.project_code != code or not entry.history_id
            or not entry.runtime_snapshot_id or not _timestamp(entry.ran_at)):
        row["freshness"] = "UNKNOWN"
        row["issues"].append("Run identity incomplete or inconsistent")
        return row
    row.update(history_id=entry.history_id, run_at=_timestamp(entry.ran_at),
               engine=entry.engine_version, workbook=entry.workbook_version,
               scenario=entry.active_scenario_name or "Scenario not recorded",
               snapshot=entry.runtime_snapshot_id, hash=entry.composite_hash)
    from app.workbook.runtime_authority import resolve_engine_currency
    row["engine_state"] = resolve_engine_currency(identity=entry.last_runtime_identity,
        replay_metadata=entry.replay_metadata, history_engine_version=entry.engine_version).state.value
    row["run_url"] = "/v2/workbook/run-history/detail?" + urlencode(
        {"project": code, "history_id": entry.history_id})
    if not record.is_protected:
        row["credit_url"] = "/v2/credit-decision?" + urlencode({"project": code, "run": entry.history_id})
    summary = _mapping(entry.runtime_summary)
    try:
        values = run_metric_view(summary, _mapping(_mapping(entry.sponsor_schedule).get("summary")),
                                _mapping(_mapping(entry.debt_schedule).get("summary")))
    except (ValueError, TypeError, OverflowError):
        values = {}
        row["issues"].append("Performance evidence invalid")
    for key, _, kind in PERFORMANCE:
        row["metrics"][key] = _cell(values.get(key), kind, "Committed Run / Compare metric catalog")
    # Requested gearing_cap_pct is deliberately NOT presented as actual leverage.
    row["gearing"] = _cell(summary.get("actual_gearing_pct"), "pct", "runtime_summary.actual_gearing_pct")
    row["integrity"] = _integrity(entry)
    finance = _mapping(summary.get("financing_evidence"))
    try:
        if not entry.composite_hash:
            raise ValueError("financing identity not recorded")
        view = build_sources_uses_projection(
            runtime_result=entry, run_kind="HISTORICAL_RUN",
            expected_snapshot_id=entry.runtime_snapshot_id,
            expected_composite_hash=entry.composite_hash,
            expected_scenario_id=entry.last_runtime_scenario_id)
        if not view["has_financing_evidence"]:
            raise ValueError("missing financing evidence")
        # FINANCING_F1_V1 + kEUR is the existing EUR authority, not the
        # editable project display-currency label. Conflicting metadata refuses.
        if finance.get("currency", "EUR") != "EUR" or summary.get("currency", "EUR") != "EUR":
            raise ValueError("unsupported or conflicting currency")
        su = finance["sources_uses"]
        for key, _, field in MONEY:
            row["money"][key] = _cell(su.get(field), source="financing_evidence.sources_uses." + field)
        window = _funding_window(finance)
        if window:
            row["cohort"] = ("EUR", "kEUR", *window)
            row["aggregate_keys"] = tuple(key for key, _, _ in MONEY)
            fc = _mapping(_mapping(finance.get("construction_funding")).get("non_construction_fc_use"))
            if fc.get("uses_keur") not in (None, 0):
                # F1 records these FC/COD amounts without a payment date. Do not
                # infer COD from the final construction period or Working Copy.
                row["aggregate_keys"] = ("capex",)
                row["issues"].append("Undated FC/COD funding; financing excluded from subtotals")
        else:
            row["issues"].append("Funding dates unavailable; excluded from subtotals")
    except (ValueError, TypeError, KeyError, OverflowError):
        row["issues"].append("Financing evidence unavailable or invalid")
    dscr = row["metrics"]["min_dscr"]["value"]
    if dscr is not None and dscr < 1:
        row["issues"].append("Observed DSCR below 1.00x; analyst review")
    if dscr is None or row["metrics"]["min_llcr"]["value"] is None:
        row["issues"].append("Credit evidence incomplete")
    if any(row["metrics"][key]["value"] is None for key in ("project_irr", "equity_irr", "total_sponsor_xirr")):
        row["issues"].append("Return evidence incomplete")
    if row["integrity"] != "PASS":
        row["issues"].append("Financial checks " + row["integrity"].lower())
    if row["freshness"] != "CURRENT":
        row["issues"].append({"STALE": "Inputs changed since this Run",
                              "HISTORICAL": "Latest committed Run is not the selected Last Run"}.get(
                                  row["freshness"], "Input freshness unverified"))
    if not entry.engine_version or not entry.workbook_version:
        row["issues"].append("Model version incomplete")
    if row["engine_state"] == "ENGINE_SUPERSEDED":
        row["issues"].append("Run uses a previous model engine version")
    return row


def _sum(values):
    # Exact decimal sum of recorded numeric representations; order independent.
    with localcontext() as context:
        context.prec = 400
        return sum((Decimal(str(value)) for value in values), Decimal(0))


def _composition(rows, key):
    counts = Counter(row[key] for row in rows)
    return [{"label": label, "count": count,
             "share": count / len(rows) if rows else 0} for label, count in sorted(counts.items())]


def build_portfolio(items, *, technology="", country="", project="", stage="", review="", sort="",
                    minimum="", maximum=""):
    all_rows = sorted((project_row(item) for item in items), key=lambda row: (row["name"].casefold(), row["code"]))
    rows = [row for row in all_rows if (not technology or row["technology"] == technology)
            and (not country or row["country"] == country) and (not project or row["code"] == project)
            and (not stage or row["stage"] == stage)
            and (not review or (review == "review" and row["issues"])
                 or (review == "stale" and row["freshness"] == "STALE")
                 or (review == "no_run" and not row["history_id"])
                 or (review == "credit_missing" and any(row["metrics"][k]["value"] is None for k in ("min_dscr", "min_llcr")))
                 or (review == "low_dscr" and row["metrics"]["min_dscr"]["value"] is not None
                     and row["metrics"]["min_dscr"]["value"] < 1))]
    if sort in SORT_KEYS:
        def value(row):
            return (row["money"] if sort in row["money"] else row["metrics"])[sort]["value"]
        if minimum or maximum:
            low = Decimal(minimum) if minimum else None
            high = Decimal(maximum) if maximum else None
            def within(row):
                raw = value(row)
                if raw is None:
                    return False
                number = Decimal(str(raw))
                if sort.endswith("irr"):
                    number *= 100
                return (low is None or number >= low) and (high is None or number <= high)
            rows = [row for row in rows if within(row)]
        rows.sort(key=lambda row: (value(row) is None, -(value(row) or 0)))
    groups = defaultdict(list)
    for row in rows:
        if row["cohort"]:
            groups[row["cohort"]].append(row)
    cohorts = []
    for cohort, members in sorted(groups.items()):
        totals = {}
        for key, label, _ in MONEY:
            values = [r["money"][key]["value"] for r in members
                      if key in r["aggregate_keys"] and r["money"][key]["value"] is not None]
            total = _sum(values) if values else None
            totals[key] = {"label": label, "value": str(total) if total is not None else None,
                           "display": f"{total:,.2f}" if total is not None else NA,
                           "coverage": len(values), "projects": len(members)}
        concentration = {}
        for dimension in ("technology", "country"):
            concentration[dimension] = []
            for label in sorted({r[dimension] for r in members}):
                selected = [r for r in members if r[dimension] == label]
                group = {"label": label}
                for key in ("capex", "senior"):
                    values = [r["money"][key]["value"] for r in selected if key in r["aggregate_keys"]]
                    group[key] = f"{_sum(values):,.2f}" if values else NA
                concentration[dimension].append(group)
        cohorts.append({"currency": cohort[0], "unit": cohort[1], "start": cohort[2], "end": cohort[3],
                        "count": len(members), "totals": totals, "concentration": concentration})
    return {"rows": rows, "total": len(rows), "all_count": len(all_rows),
            "with_run": sum(bool(r["history_id"]) for r in rows),
            "review_count": sum(bool(r["issues"]) for r in rows),
            "stale_count": sum(r["freshness"] == "STALE" for r in rows),
            "excluded_count": sum(len(r["aggregate_keys"]) != len(MONEY) for r in rows),
            "cohorts": cohorts, "technology_counts": _composition(rows, "technology"),
            "country_counts": _composition(rows, "country"),
            "options": {key: sorted({r[key] for r in all_rows}) for key in ("technology", "country", "stage")},
            "project_options": [{"code": r["code"], "name": r["name"]} for r in all_rows],
            "filters": dict(technology=technology, country=country, project=project, stage=stage, review=review,
                            sort=sort, minimum=minimum, maximum=maximum),
            "money_columns": MONEY, "performance_columns": PERFORMANCE}
