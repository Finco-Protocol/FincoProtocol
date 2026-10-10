"""app.v2.output_workspace_projection — Statements & Debt output workspace over the persisted Last Run.

Read-only presentation.  Every number originates in the immutable Run evidence the workspace committed
(``RuntimeResult.financial_statements`` / ``debt_schedule`` / ``distribution_schedule`` / ``sponsor_schedule`` /
``runtime_summary.financing_evidence``).  Nothing here runs the engine, recomputes a statement line, creates or
modifies an input, or substitutes zero for an unavailable value: a value the Run did not persist is ``None`` and is
rendered as "not available".

Freshness against the Working Copy is the canonical ``RuntimeFreshness``.  CURRENT, STALE and NOT_RUN are shown as
such, and a STALE view always names the PRIOR Run it displays.  Run Integrity is a separate authority: a CURRENT Run can
carry an Integrity FAIL and both are shown, never merged.
"""
from __future__ import annotations

import math
from typing import Any, Mapping, Optional, Sequence

from app.v2.returns_projection import build_returns_projection
from app.workbook.runtime_projection import (
    FS_BS_ROW_DEFS,
    FS_PF_CF_ROW_DEFS,
    FS_PNL_ROW_DEFS,
    thaw_runtime_payload,
)

# Display-only tolerance for the persisted balance-check row (same ±1 kEUR the Financial Statements sheet uses)
# and for the cross-check of persisted facility service against the persisted PF waterfall.
BALANCE_TOLERANCE_KEUR = 1.0
FACILITY_SERVICE_TOLERANCE_KEUR = 0.01
# A non-zero closing balance below the 2-decimal display grain is labelled as such, never reported as repaid.
UNPAID_DISPLAY_FLOOR_KEUR = 0.005   # the 2-decimal display grain; used only to LABEL a residual, never to alter it

_MONTHS = ("Jan", "Feb", "Mar", "Apr", "May", "Jun", "Jul", "Aug", "Sep", "Oct", "Nov", "Dec")

STATEMENT_NOTES = {
    "pnl": "Income statement lines as persisted by the Run (kEUR per model period).",
    "balance_sheet": ("Balance sheet lines as persisted by the Run. Share capital is a placeholder in the persisted "
                      "statement (★)."),
    "cash_flow": ("Project finance cash waterfall as persisted by the Run. It is not an indirect-method cash flow "
                  "statement."),
}


def _num(value: Any) -> Optional[float]:
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        return None
    return float(value) if math.isfinite(value) else None


def period_label(date: Any) -> str:
    text = str(date or "")
    if len(text) >= 7 and text[4] == "-" and text[5:7].isdigit() and 1 <= int(text[5:7]) <= 12:
        return f"{_MONTHS[int(text[5:7]) - 1]} {text[:4]}"
    return text or "—"


def fmt_number(value: Optional[float], decimals: int = 2) -> str:
    return "—" if value is None else f"{value:,.{decimals}f}"


def _cell(value: Any, unit: str = "keur") -> dict[str, Any]:
    v = _num(value)
    return {"v": v, "text": fmt_number(v, 2), "unit": unit, "neg": v is not None and v < 0}


def _columns(periods: Sequence[Mapping[str, Any]], index_key: str) -> list[dict[str, Any]]:
    columns = []
    for position, period in enumerate(periods):
        raw = period.get(index_key)
        index = int(raw) if isinstance(raw, (int, float)) and not isinstance(raw, bool) else position
        columns.append({"index": index, "date": str(period.get("date") or ""),
                        "label": period_label(period.get("date")), "year0": index == 0})
    return columns


def _statement_table(table_id: str, title: str, note: str, row_defs: Sequence[tuple], periods: Optional[Sequence[Any]],
                     index_key: str, *, classification: str = "") -> dict[str, Any]:
    if not periods:
        return {"id": table_id, "title": title, "note": note, "available": False, "columns": [], "rows": [],
                "classification": classification}
    periods = [p for p in periods if isinstance(p, Mapping)]
    rows = [{"key": key, "label": label, "total": bool(total), "unit": "keur",
             "cells": [_cell(p.get(key)) for p in periods]} for key, label, total, _stock in row_defs]
    unavailable = [r["label"] for r in rows if all(c["v"] is None for c in r["cells"])]
    return {"id": table_id, "title": title, "note": note, "available": True, "columns": _columns(periods, index_key),
            "rows": rows, "classification": classification, "unavailable": unavailable}


def _balance_check(table: Mapping[str, Any]) -> dict[str, Any]:
    row = next((r for r in table.get("rows", ()) if r["key"] == "balance_check_keur"), None)
    values = [c["v"] for c in row["cells"] if c["v"] is not None] if row else []
    if not values:
        return {"state": "UNAVAILABLE", "label": "Balance check not persisted by this Run"}
    worst = max(abs(v) for v in values)
    ok = worst <= BALANCE_TOLERANCE_KEUR
    return {"state": "OK" if ok else "BREAK", "max_abs_keur": worst, "periods": len(values),
            "label": (f"Balance check within ±{BALANCE_TOLERANCE_KEUR:g} kEUR in all {len(values)} persisted periods "
                      f"(largest {worst:,.4f})" if ok else
                      f"Balance check outside ±{BALANCE_TOLERANCE_KEUR:g} kEUR (largest {worst:,.4f} kEUR)")}


def _by_index(periods: Optional[Sequence[Any]], index_key: str) -> dict[int, Mapping[str, Any]]:
    out: dict[int, Mapping[str, Any]] = {}
    for position, p in enumerate(periods or ()):
        if isinstance(p, Mapping):
            raw = p.get(index_key)
            out[int(raw) if isinstance(raw, (int, float)) and not isinstance(raw, bool) else position] = p
    return out


def _cfads_table(pf_periods: Optional[Sequence[Any]], debt_periods: Optional[Sequence[Any]]) -> dict[str, Any]:
    note = ("CFADS is the PF waterfall's cash available to Senior debt service (fcf_banks_keur). DSCR and DSRA balance "
            "come from the Run's debt schedule and are shown only where its period date matches.")
    if not pf_periods:
        return {"id": "cfads", "title": "CFADS", "note": note, "available": False, "columns": [], "rows": []}
    pf = [p for p in pf_periods if isinstance(p, Mapping)]
    debt = _by_index(debt_periods, "period")

    def debt_value(p: Mapping[str, Any], key: str):
        match = debt.get(int(p.get("period_index", -1))) if isinstance(p.get("period_index"), (int, float)) else None
        # Align only when the persisted dates agree — never by guess.
        return match.get(key) if match is not None and str(match.get("date")) == str(p.get("date")) else None

    def row(key, label, getter, unit="keur", total=False):
        return {"key": key, "label": label, "unit": unit, "total": total, "cells": [_cell(getter(p), unit) for p in pf]}

    rows = [
        row("ebitda_cash_keur", "EBITDA cash", lambda p: p.get("ebitda_cash_keur")),
        row("cash_tax_keur", "Cash tax", lambda p: p.get("cash_tax_keur")),
        row("cfads_keur", "CFADS to Senior", lambda p: p.get("fcf_banks_keur"), total=True),
        row("senior_service_keur", "Senior debt service", lambda p: p.get("senior_total_ds_keur")),
        row("dscr", "DSCR (x)", lambda p: debt_value(p, "dscr"), "x", True),
        row("dsra_balance_keur", "DSRA balance", lambda p: debt_value(p, "dsra_balance_keur")),
        row("dsra_funding_keur", "DSRA funding", lambda p: p.get("dsra_funding_keur")),
        row("dsra_release_keur", "DSRA release", lambda p: p.get("dsra_release_keur")),
    ]
    return {"id": "cfads", "title": "CFADS", "note": note, "available": True, "columns": _columns(pf, "period_index"),
            "rows": rows}


def _facility_label(position: int, instrument_id: str) -> str:
    return f"Facility {position + 1} · {instrument_id}" if instrument_id else f"Facility {position + 1}"


def _date_lookup(*period_lists: Optional[Sequence[Any]]) -> dict[int, str]:
    dates: dict[int, str] = {}
    for periods, key in zip(period_lists, ("period", "period_index", "period")):
        for index, p in _by_index(periods, key).items():
            if p.get("date"):
                dates.setdefault(index, str(p["date"]))
    return dates


def _facility_operating_table(facility: Mapping[str, Any], dates: Mapping[int, str]) -> dict[str, Any]:
    indices = [int(i) for i in facility.get("period_indices") or ()]
    cols = [{"index": i, "date": dates.get(i, ""), "label": period_label(dates.get(i)) if dates.get(i) else f"Period {i}",
             "year0": i == 0} for i in indices]
    spec = (("opening_keur", "Opening balance", False), ("interest_keur", "Interest", False),
            ("principal_keur", "Principal", False), ("debt_service_keur", "Debt service", True),
            ("closing_keur", "Closing balance", True))
    rows = []
    for key, label, total in spec:
        values = list(facility.get(key) or ())
        rows.append({"key": key, "label": label, "unit": "keur", "total": total,
                     "cells": [_cell(values[n] if n < len(values) else None) for n in range(len(indices))]})
    return {"columns": cols, "rows": rows, "available": bool(indices)}


def _construction_table(facility: Mapping[str, Any], construction_periods: Sequence[Mapping[str, Any]]) -> dict[str, Any]:
    cols = [{"index": int(p.get("period_index", n + 1)), "date": str(p.get("period_end") or ""),
             "label": f"{period_label(p.get('period_start'))} – {period_label(p.get('period_end'))}", "year0": False}
            for n, p in enumerate(construction_periods)]
    spec = (("construction_draws_keur", "Draw"), ("construction_idc_keur", "Capitalised interest (IDC)"),
            ("upfront_fees_keur", "Upfront fee"), ("construction_commitment_fees_keur", "Commitment fee"))
    rows = []
    for key, label in spec:
        values = list(facility.get(key) or ())
        rows.append({"key": key, "label": label, "unit": "keur", "total": False,
                     "cells": [_cell(values[n] if n < len(values) else None) for n in range(len(cols))]})
    return {"columns": cols, "rows": rows, "available": bool(cols)}


def _last_value(values: Sequence[Any]) -> Optional[float]:
    for value in reversed(list(values or ())):
        number = _num(value)
        if number is not None:
            return number
    return None


REPAYMENT_LABELS = {
    "REPAID": "FULLY REPAID — the persisted closing balance is exactly zero",
    "OUTSTANDING": "UNPAID OBLIGATION — the persisted closing balance is outstanding",
    "OUTSTANDING_BELOW_DISPLAY": "OUTSTANDING BELOW DISPLAY PRECISION — the persisted closing balance is not zero",
    "NEGATIVE_BALANCE": "NEGATIVE PERSISTED BALANCE — not a liability; verify the Run evidence",
    "UNAVAILABLE": "REPAYMENT STATUS UNAVAILABLE — the Run did not persist the closing balance",
}


def _repayment(closing: Optional[float], basis: str) -> dict[str, Any]:
    """Repayment status of the PERSISTED closing balance.  Display rounding never decides it: the balance is shown
    as persisted and a non-zero balance is never reported as repaid because it rounds to 0.00."""
    if closing is None:
        status = "UNAVAILABLE"
    elif closing == 0.0:
        status = "REPAID"
    elif closing < 0.0:
        status = "NEGATIVE_BALANCE"
    elif closing >= UNPAID_DISPLAY_FLOOR_KEUR:
        status = "OUTSTANDING"
    else:
        status = "OUTSTANDING_BELOW_DISPLAY"
    return {"status": status, "label": REPAYMENT_LABELS[status], "balance": _cell(closing), "basis": basis,
            "exact_text": None if closing is None else f"{closing:.6g}",
            "problem": status in ("OUTSTANDING", "OUTSTANDING_BELOW_DISPLAY", "NEGATIVE_BALANCE", "UNAVAILABLE")}


def _canonical_senior_terminal(sponsor_schedule: Any) -> Optional[dict[str, Any]]:
    """The Run's own typed Senior terminal state (``terminal_financial_state.senior``), when persisted."""
    summary = sponsor_schedule.get("summary") if isinstance(sponsor_schedule, Mapping) else None
    tfs = summary.get("terminal_financial_state") if isinstance(summary, Mapping) else None
    senior = tfs.get("senior") if isinstance(tfs, Mapping) else None
    if not isinstance(senior, Mapping) or not senior.get("status"):
        return None
    index = senior.get("contractual_maturity_period_index")
    return {"status": str(senior["status"]), "maturity_index": int(index) if isinstance(index, (int, float)) and not isinstance(index, bool) else None,
            "maturity_date": senior.get("contractual_maturity_date"),
            "balance": _cell(senior.get("balance_at_contractual_maturity_keur"))}


def _debt_section(summary: Mapping[str, Any], debt_schedule: Optional[Mapping[str, Any]],
                  pf_periods: Optional[Sequence[Any]], pnl_periods: Optional[Sequence[Any]],
                  sponsor_schedule: Any = None) -> dict[str, Any]:
    canonical = _canonical_senior_terminal(sponsor_schedule)
    evidence = summary.get("financing_evidence") if isinstance(summary, Mapping) else None
    evidence = evidence if isinstance(evidence, Mapping) else {}
    debt_periods = (debt_schedule or {}).get("periods") if isinstance(debt_schedule, Mapping) else None
    dates = _date_lookup(pnl_periods, pf_periods, debt_periods)
    schedules = evidence.get("facility_schedules")
    if isinstance(schedules, list) and schedules:
        construction = (evidence.get("construction_funding") or {}).get("periods") or []
        facilities = []
        for position, f in enumerate(s for s in schedules if isinstance(s, Mapping)):
            maturity_index = f.get("maturity_period_index")
            maturity_index = int(maturity_index) if isinstance(maturity_index, (int, float)) else None
            operating = _facility_operating_table(f, dates)
            indices = [int(i) for i in f.get("period_indices") or ()]
            closings = list(f.get("closing_keur") or ())
            at_maturity = (_num(closings[indices.index(maturity_index)])
                           if maturity_index in indices and indices.index(maturity_index) < len(closings) else None)
            repayment = _repayment(at_maturity, f"closing balance at this facility's maturity period {maturity_index}"
                                   if maturity_index is not None else "maturity period not persisted")
            facilities.append({
                "id": str(f.get("instrument_id") or ""), "label": _facility_label(position, str(f.get("instrument_id") or "")),
                "commitment": _cell(f.get("commitment_keur")),
                "maturity_index": maturity_index, "maturity_date": dates.get(maturity_index) if maturity_index is not None else None,
                "repayment": repayment,
                "construction": _construction_table(f, construction), "operating": operating, "fees_supported": True,
            })
        check = _facility_service_check(schedules, pf_periods)
        return {"mode": "F3_TWO_SENIOR", "authority": str(evidence.get("facility_authority") or ""), "facilities": facilities,
                "service_check": check, "canonical_terminal": canonical,
                "note": "Facility schedules are the Run's own F3 evidence; the aggregate Senior lines are the PF waterfall's."}
    periods = [p for p in (debt_periods or ()) if isinstance(p, Mapping)]
    if not periods:
        return {"mode": "UNAVAILABLE", "facilities": [], "service_check": {"state": "UNAVAILABLE"}, "canonical_terminal": canonical,
                "note": "This Run persisted no debt schedule."}
    cols = _columns(periods, "period")
    spec = (("opening", "Opening balance", None, False), ("interest", "Interest", "senior_interest_keur", False),
            ("principal", "Principal", "senior_principal_keur", False), ("service", "Debt service", "senior_ds_keur", True),
            ("closing", "Closing balance", "senior_balance_keur", True), ("dscr", "DSCR (x)", "dscr", False))
    rows = []
    for key, label, source, total in spec:
        unit = "x" if key == "dscr" else "keur"
        rows.append({"key": key, "label": label, "unit": unit, "total": total, "not_exposed": source is None,
                     "cells": [_cell(p.get(source) if source else None, unit) for p in periods]})
    at_maturity = None
    basis = "closing balance in the last persisted period"
    if canonical and canonical["maturity_index"] is not None:
        row = next((p for p in periods if p.get("period") == canonical["maturity_index"]), None)
        if row is not None and _num(row.get("senior_balance_keur")) is not None:
            at_maturity, basis = _num(row["senior_balance_keur"]), f"closing balance at the canonical maturity period {canonical['maturity_index']}"
    if at_maturity is None:
        at_maturity = _last_value([p.get("senior_balance_keur") for p in periods])
    repayment = _repayment(at_maturity, basis)
    return {"mode": "AGGREGATE_SENIOR", "facilities": [{
        "id": "senior", "label": "Senior debt (aggregate)", "commitment": _cell(None), "maturity_index": canonical["maturity_index"] if canonical else None,
        "maturity_date": canonical["maturity_date"] if canonical else None, "repayment": repayment,
        "construction": {"available": False, "columns": [], "rows": []}, "fees_supported": False,
        "operating": {"columns": cols, "rows": rows, "available": True}}],
        "service_check": {"state": "NOT_APPLICABLE"}, "canonical_terminal": canonical,
        "note": ("This Run carries a single aggregate Senior schedule; per-facility interest, principal, balances, fees "
                 "and maturities are not persisted for it and are shown as not available.")}



def _facility_service_check(schedules: Sequence[Any], pf_periods: Optional[Sequence[Any]]) -> dict[str, Any]:
    """Cross-check persisted facility service against the persisted PF waterfall (display only)."""
    pf = _by_index(pf_periods, "period_index")
    totals: dict[int, float] = {}
    for f in schedules:
        if not isinstance(f, Mapping):
            continue
        for index, service in zip(f.get("period_indices") or (), f.get("debt_service_keur") or ()):
            number = _num(service)
            if number is not None:
                totals[int(index)] = totals.get(int(index), 0.0) + number
    diffs = []
    for index, total in totals.items():
        reported = _num((pf.get(index) or {}).get("senior_total_ds_keur"))
        if reported is not None:
            diffs.append(abs(total - reported))
    if not diffs:
        return {"state": "UNAVAILABLE", "label": "Facility service could not be matched to the PF waterfall"}
    worst = max(diffs)
    ok = worst <= FACILITY_SERVICE_TOLERANCE_KEUR
    return {"state": "OK" if ok else "BREAK", "max_abs_keur": worst, "periods": len(diffs),
            "label": (f"Facility debt service equals the PF waterfall's Senior service in {len(diffs)} periods "
                      f"(largest difference {worst:,.4f} kEUR)" if ok else
                      f"Facility debt service differs from the PF waterfall (largest {worst:,.4f} kEUR)")}


def _returns_section(rr: Any, ws: Any, is_stale: bool) -> dict[str, Any]:
    projection = build_returns_projection(rr, ws, runtime_is_stale=is_stale)
    metrics = [{"label": m.label, "display": m.display, "available": m.value is not None, "source": m.source}
               for m in projection.metrics]

    def period_table(table_id: str, title: str, rows: Sequence[Mapping[str, Any]], spec: Sequence[tuple]) -> dict[str, Any]:
        if not rows:
            return {"id": table_id, "title": title, "available": False, "columns": [], "rows": []}
        cols = [{"index": int(r["period"]) if isinstance(r.get("period"), (int, float)) else n, "date": str(r.get("date") or ""),
                 "label": period_label(r.get("date")), "year0": False} for n, r in enumerate(rows)]
        return {"id": table_id, "title": title, "available": True, "columns": cols,
                "rows": [{"key": key, "label": label, "unit": "keur", "total": total,
                          "cells": [_cell(r.get(key)) for r in rows]} for key, label, total in spec]}

    distributions = period_table("distributions", "Distribution waterfall", projection.distribution_rows, (
        ("cf_after_reserves_keur", "Cash flow after reserves", False), ("distribution_keur", "Distribution", True),
        ("dsra_balance_keur", "DSRA balance", False)))
    sponsor = period_table("sponsor", "Sponsor cash flows", projection.sponsor_rows, (
        ("share_capital_contribution_keur", "Share capital contribution", False),
        ("share_premium_contribution_keur", "Share premium contribution", False),
        ("additional_equity_contribution_keur", "Additional equity contribution", False),
        ("shl_principal_receipt_keur", "SHL principal receipt", False),
        ("shl_cash_interest_receipt_keur", "SHL cash interest receipt", False),
        ("legal_equity_distribution_keur", "Legal equity distribution", True)))
    return {"available": projection.has_runtime, "metrics": metrics, "distributions": distributions, "sponsor": sponsor,
            "sponsor_source": projection.sponsor_source, "distribution_source": projection.distribution_source}


def _integrity(report: Optional[Mapping[str, Any]]) -> dict[str, Any]:
    if not isinstance(report, Mapping) or not report.get("checks"):
        return {"status": "UNAVAILABLE", "label": "Run Integrity not available", "counts": {}, "failures": []}
    overall = str(report.get("overall") or "")
    status = overall if overall in ("PASS", "FAIL", "INCOMPLETE") else "UNAVAILABLE"
    failures = [{"id": c.get("check_id"), "title": c.get("title"), "reason": c.get("reason_code")}
                for c in report.get("checks", ()) if c.get("status") == "FAIL"]
    return {"status": status, "label": f"Run Integrity {status}", "counts": dict(report.get("counts") or {}),
            "failures": failures}


UNAVAILABLE_LABEL = "UNAVAILABLE"


def _identity(rr: Any, ws: Any, scenario_label: Optional[str]) -> dict[str, Any]:
    """Committed Run identity.  The scenario label is proven by the authorized request layer
    (``resolve_last_run_scenario``); a label that could not be proven is UNAVAILABLE — never Base Case, never the
    active Working Copy scenario, never a name read from the Run's own identity blob."""
    identity = getattr(ws, "last_runtime_identity", None)
    identity = identity if isinstance(identity, Mapping) else {}
    label = scenario_label.strip() if isinstance(scenario_label, str) and scenario_label.strip() else None
    ran_at = (getattr(rr, "ran_at", "") or "")
    return {"snapshot_id": getattr(rr, "snapshot_id", "") or "", "ran_at": ran_at[:19].replace("T", " "),
            "composite_hash": getattr(ws, "last_runtime_composite_hash", "") or "",
            "scenario": label or UNAVAILABLE_LABEL, "scenario_proven": label is not None,
            "engine_version": str(identity.get("engine_version") or "")}


def build_output_workspace(*, runtime_result: Any, workspace: Any, freshness: Any,
                           last_run_scenario: Optional[str],
                           integrity_report: Optional[Mapping[str, Any]] = None) -> dict[str, Any]:
    """Compact, template-ready projection of the Statements & Debt workspace."""
    state = getattr(getattr(freshness, "state", None), "value", None)
    state = state if state in ("CURRENT", "STALE") else "NOT_RUN"
    if runtime_result is None or state == "NOT_RUN":
        return {"state": "NOT_RUN", "identity": None, "integrity": _integrity(None), "reconciliation": None,
                "statements": [], "cfads": None, "debt": None, "returns": None}
    fs = thaw_runtime_payload(getattr(runtime_result, "financial_statements", None) or {}) or {}
    summary = thaw_runtime_payload(getattr(runtime_result, "runtime_summary", None) or {}) or {}
    debt_schedule = thaw_runtime_payload(getattr(runtime_result, "debt_schedule", None) or {}) or {}
    pnl_periods = (fs.get("pnl") or {}).get("periods")
    bs_periods = (fs.get("balance_sheet") or {}).get("periods")
    pf_periods = (fs.get("pf_cash_waterfall") or {}).get("periods")
    statements = [
        _statement_table("pnl", "Profit & Loss", STATEMENT_NOTES["pnl"], FS_PNL_ROW_DEFS, pnl_periods, "period"),
        _statement_table("balance_sheet", "Balance Sheet", STATEMENT_NOTES["balance_sheet"], FS_BS_ROW_DEFS,
                         bs_periods, "period_index"),
        _statement_table("cash_flow", "Cash Flow (PF waterfall)", STATEMENT_NOTES["cash_flow"], FS_PF_CF_ROW_DEFS,
                         pf_periods, "period_index"),
    ]
    balance = _balance_check(statements[1]) if statements[1]["available"] else {
        "state": "UNAVAILABLE", "label": "Balance sheet not persisted by this Run"}
    sponsor_schedule = thaw_runtime_payload(getattr(runtime_result, "sponsor_schedule", None) or {}) or {}
    debt = _debt_section(summary, debt_schedule, pf_periods, pnl_periods, sponsor_schedule)
    service = debt.get("service_check", {"state": "NOT_APPLICABLE"})
    checks = [balance] + ([service] if service.get("state") != "NOT_APPLICABLE" else [])
    if any(c["state"] == "BREAK" for c in checks):
        overall = "BREAK"
    elif any(c["state"] == "UNAVAILABLE" for c in checks):
        overall = "UNVERIFIED"
    else:
        overall = "RECONCILED"
    identity = _identity(runtime_result, workspace, last_run_scenario)
    return {
        "state": state, "identity": identity, "integrity": _integrity(integrity_report),
        "reconciliation": {"overall": overall, "checks": [{"name": n, **c} for n, c in
                           zip(["Balance sheet check", "Facility service vs PF waterfall"], checks)]},
        "statements": statements, "cfads": _cfads_table(pf_periods, debt_schedule.get("periods")),
        "debt": debt, "returns": _returns_section(runtime_result, workspace, state == "STALE"),
        "banner": (f"STALE — showing the PRIOR Last Run ({identity['ran_at']} · snapshot {identity['snapshot_id'][:22]} · "
                   f"{identity['scenario']}). The Working Copy changed after it; these values are not the current inputs."
                   if state == "STALE" else ""),
    }


def build_output_workspace_safe(**kwargs: Any) -> dict[str, Any]:
    try:
        return build_output_workspace(**kwargs)
    except Exception:  # noqa: BLE001 - presentation adapter fails closed, never fabricates
        return {"state": "UNAVAILABLE", "identity": None, "integrity": _integrity(None), "reconciliation": None,
                "statements": [], "cfads": None, "debt": None, "returns": None,
                "message": "The persisted Run evidence could not be projected; nothing is estimated."}


__all__ = ["build_output_workspace", "build_output_workspace_safe", "fmt_number", "period_label"]
