"""WF-04 — Debt Metrics projection of ONE committed Run (pure: no I/O, no engine, no writes, no calculation of a financial number).

Everything here is read from the Run's own persisted evidence: the digest-sealed Senior-debt period rows (full-precision DSCR, CFADS,
service), the dated debt / distribution schedules, the pro-forma cash waterfall, the runtime summary and the contractual DSCR terms that
were recorded in THAT Run's immutable identity.  A figure the Run did not persist stays unavailable with its reason; nothing is invented,
defaulted or averaged across arbitrary labels.  A changed Working Copy can never rewrite a historical Run's verdict.

Three independent conclusions are produced (see ``app.workbook.dscr_contract_terms``): operating coverage (< 1.00x), the contractual
covenant, and the model-evaluated Event-of-Default threshold condition.  None of them is a payment default, a bankability verdict or a
statement about profitability.
"""
from __future__ import annotations

import math
from typing import Any, Mapping, Optional, Sequence

from app.workbook import dscr_contract_terms as T

SCHEMA = "WF04_DEBT_METRICS_V1"
UNAVAILABLE = "UNAVAILABLE"
FREQUENCY_NAMES = {1: "ANNUAL", 2: "SEMIANNUAL", 4: "QUARTERLY", 12: "MONTHLY"}
BASIS_NOTE = ("Every value is persisted by this committed Run (period identity = the committed period index and date). DSCR statuses compare the "
              "sealed raw ratio with the terms recorded when this Run was committed; nothing is recalculated and no displayed rounding decides a status.")


def _num(value: Any) -> Optional[float]:
    if value is None or isinstance(value, bool) or not isinstance(value, (int, float)):
        return None
    f = float(value)
    return f if math.isfinite(f) else None


def _map(value: Any) -> Mapping:
    return value if isinstance(value, Mapping) else {}


def _rows(value: Any) -> list[Mapping]:
    return [r for r in value if isinstance(r, Mapping)] if isinstance(value, (list, tuple)) else []


def _cell(value: Any, display: Optional[str] = None, reason: str = "") -> dict[str, Any]:
    if value is None:
        return {"v": None, "d": UNAVAILABLE, "reason": reason or "Not persisted in this Run's evidence."}
    return {"v": value, "d": display if display is not None else str(value), "reason": ""}


def _x(value: Optional[float], refs: Sequence[float] = (1.0,), reason: str = "") -> dict[str, Any]:
    return _cell(None, reason=reason) if value is None else _cell(value, T.format_ratio(value, refs))


def _evidence_verified(evidence: Mapping[str, Any]) -> tuple[bool, str]:
    """The sealed evidence is the only source of the raw per-period ratios, so its digest must verify before a verdict is drawn from it."""
    from app.run_integrity.checks import check_evidence_digest
    from app.run_integrity.contracts import CheckStatus
    if not evidence:
        return False, "This Run persisted no Run Integrity evidence."
    check = check_evidence_digest(evidence)
    if check.status is CheckStatus.PASS:
        return True, ""
    return False, f"EVIDENCE_NOT_VERIFIED: {check.reason_code or check.status.value}. DSCR verdicts are not drawn from unverified evidence."


def _unavailable_evaluation(terms: T.RunTerms, reason: str) -> dict[str, Any]:
    def verdict(term: T.Term) -> dict[str, Any]:
        return {"status": UNAVAILABLE, "reason": reason, "threshold_x": term.value, "threshold_raw": term.raw, "breaching_periods": [],
                "worst": None, "headroom": None}
    return {"schema": T.SCHEMA, "basis": dict(T.TEST_BASIS), "terms_recorded": terms.recorded, "terms_reason": terms.reason,
            "achieved_min_dscr": {"available": False, "reason": reason, "min": None, "period": None},
            "bank_case_min_dscr": {"available": False, "min": None, "period": None},
            "coverage": {"status": UNAVAILABLE, "reason": reason, "periods": []},
            "eod": verdict(terms.eod), "covenant": verdict(terms.contractual)}


def evaluate_run(entry: Any) -> tuple[T.RunTerms, list[dict[str, Any]], dict[str, Any], Optional[str]]:
    """(terms, test rows, evaluation, evidence_problem) of one committed Run.  ``evidence_problem`` is set when verdicts are withheld."""
    terms = T.read_run_terms(getattr(entry, "last_runtime_identity", None))
    evidence = _map(getattr(entry, "integrity_evidence", None))
    periods = [p for p in _rows(_map(evidence.get("senior_debt")).get("periods")) if isinstance(p.get("period_index"), int)]
    dates = {r["period"]: r["date"] for r in _rows(_map(getattr(entry, "debt_schedule", None)).get("periods"))
             if isinstance(r.get("period"), int) and isinstance(r.get("date"), str)}
    if not periods:
        reason = "No committed Senior-debt period evidence for this Run."
        return terms, [], _unavailable_evaluation(terms, reason), reason
    verified, why = _evidence_verified(evidence)
    if not verified:
        return terms, [], _unavailable_evaluation(terms, why), why
    rows = T.test_rows(periods, dates)
    return terms, rows, T.evaluate(terms, rows), None


# ── the covenant monitor ──────────────────────────────────────────────────────────────────────────────────────────────────────────────
def _status_row(*, row_id: str, label: str, role: str, description: str, basis: str, required: Optional[float], operator: str, actual: Optional[float],
                status: str, status_label: str, severity: str, reason: str = "", periods: Sequence[Mapping] = (), actual_reason: str = "",
                extra_refs: Sequence[float] = (), required_note: str = "") -> dict[str, Any]:
    refs = tuple(x for x in (required,) + tuple(extra_refs) if x is not None)
    head = T.headroom(actual, required)
    return {
        "id": row_id, "label": label, "role": role, "description": description, "basis": basis,
        "required": ({"v": required, "d": T.format_ratio(required, refs), "operator": operator, "note": required_note} if required is not None
                     else {"v": None, "d": UNAVAILABLE, "operator": operator, "note": required_note or reason}),
        "actual": _x(actual, refs, actual_reason),
        "headroom": ({"absolute": {"v": head["absolute_x"], "d": T.format_delta_x(head["absolute_x"])},
                      "relative": {"v": head["relative_pct"], "d": T.format_relative_pct(head["relative_pct"])},
                      "note": "negative = below the threshold; actual − required, and actual ÷ required − 1"} if head else None),
        "status": status, "status_label": status_label, "severity": severity, "reason": reason,
        "periods": [dict(p) for p in list(periods)[:12]], "periods_total": len(periods),
    }


def _covenant_table(ev: Mapping[str, Any], rows: Sequence[Mapping[str, Any]], summary: Mapping[str, Any], lockup: Mapping[str, Any]) -> list[dict[str, Any]]:
    achieved = _num(_map(ev["achieved_min_dscr"]).get("min"))
    worst_period = _map(ev["achieved_min_dscr"]).get("period")
    table: list[dict[str, Any]] = []

    eod = ev["eod"]
    eod_sev = {"TRIGGERED": "CRITICAL", T.EOD_NOT_TRIGGERED: "OK"}.get(eod["status"], "NEUTRAL")
    eod_label = {"TRIGGERED": "EVENT_OF_DEFAULT: TRIGGERED", T.EOD_NOT_TRIGGERED: "NOT TRIGGERED UNDER THIS FLOOR",
                 T.NOT_CONFIGURED: "NOT CONFIGURED", T.UNAVAILABLE: "UNAVAILABLE", T.NOT_APPLICABLE: "NOT APPLICABLE"}[eod["status"]]
    table.append(_status_row(
        row_id="EOD_FLOOR", label="Minimum DSCR — EoD threshold", role="INPUT",
        description="Model-evaluated Event-of-Default threshold on the entered credit terms. Not a legally declared default.",
        basis="Strict comparison (actual < threshold) of each period's raw base-case DSCR; equal is not a trigger.",
        required=eod.get("threshold_x"), operator="≥", actual=achieved, status=eod["status"], status_label=eod_label, severity=eod_sev,
        reason=eod.get("reason", ""), periods=eod.get("breaching_periods") or ([worst_period] if worst_period and eod["status"] == T.EOD_NOT_TRIGGERED else []),
        actual_reason=_map(ev["achieved_min_dscr"]).get("reason", "")))

    cov = ev["covenant"]
    cov_sev = {"BREACHED": "CRITICAL", T.COV_COMPLIANT: "OK"}.get(cov["status"], "NEUTRAL")
    cov_label = {"BREACHED": "BREACHED", T.COV_COMPLIANT: "COMPLIANT", T.NOT_CONFIGURED: "NOT CONFIGURED",
                 T.UNAVAILABLE: "UNAVAILABLE", T.NOT_APPLICABLE: "NOT APPLICABLE"}[cov["status"]]
    table.append(_status_row(
        row_id="CONTRACTUAL_DSCR", label="Contractual DSCR — covenant", role="INPUT",
        description="The contractual DSCR requirement. A breach does not by itself mean unpaid debt service or an Event of Default.",
        basis="Same documented basis and test periods as the EoD threshold; a separately stored value that never inherits the sizing target.",
        required=cov.get("threshold_x"), operator="≥", actual=achieved, status=cov["status"], status_label=cov_label, severity=cov_sev,
        reason=cov.get("reason", ""), periods=cov.get("breaching_periods") or [], actual_reason=_map(ev["achieved_min_dscr"]).get("reason", "")))

    coverage = ev["coverage"]
    cv_label = {T.COVERAGE_DEFICIENCY: "CFADS DEFICIENCY", T.COVERAGE_NO_DEFICIENCY: "NO DEFICIENCY FOUND", T.UNAVAILABLE: "UNAVAILABLE",
                T.NOT_APPLICABLE: "NOT APPLICABLE"}[coverage["status"]]
    table.append(_status_row(
        row_id="COVERAGE_1X", label="Debt-service coverage — 1.00x", role="RESULT",
        description="CFADS against scheduled Senior debt service. Independent of both configured terms; a deficiency is not by itself a payment default.",
        basis="Base-case CFADS ÷ scheduled Senior debt service per period, raw ratio.",
        required=1.0, operator="≥", actual=achieved, status=coverage["status"], status_label=cv_label,
        severity="CRITICAL" if coverage["status"] == T.COVERAGE_DEFICIENCY else ("OK" if coverage["status"] == T.COVERAGE_NO_DEFICIENCY else "NEUTRAL"),
        reason=coverage.get("reason", ""), periods=coverage.get("periods") or [], actual_reason=_map(ev["achieved_min_dscr"]).get("reason", "")))

    # Lock-up: an existing, independent control. The Run persists the per-period flag, not the threshold value.
    count = lockup.get("active_count")
    if lockup.get("available"):
        active = bool(count)
        table.append(_status_row(
            row_id="LOCKUP", label="Lock-up DSCR", role="EXISTING_CONTROL",
            description="Distribution lock-up observed in the committed distribution schedule. A lock-up restricts distributions; it is not a default.",
            basis="Per-period lock-up flag persisted by the Run. The threshold value itself is not persisted with a Run.",
            required=None, operator="≥", actual=None, status="ACTIVE" if active else "INACTIVE",
            status_label=(f"ACTIVE · {count} period(s)" if active else "INACTIVE"), severity="WARNING" if active else "OK",
            reason="Threshold value not recorded with this Run; status is read from the persisted per-period flags.",
            required_note="threshold not recorded with this Run"))
    else:
        table.append(_status_row(
            row_id="LOCKUP", label="Lock-up DSCR", role="EXISTING_CONTROL",
            description="Distribution lock-up observed in the committed distribution schedule.", basis="Per-period lock-up flag.",
            required=None, operator="≥", actual=None, status=UNAVAILABLE, status_label="UNAVAILABLE", severity="NEUTRAL",
            reason=str(lockup.get("reason") or "The Run persisted no lock-up flags."), required_note="not recorded"))

    # Sizing target: a debt-sizing assumption on the BANK-case basis — never a covenant, never compared with the base-case ratio.
    tight = None
    for r in rows:
        if r["applicable"] and r["bank_dscr"] is not None and r["sizing_target_dscr"]:
            ratio = r["bank_dscr"] / r["sizing_target_dscr"]
            if tight is None or ratio < tight[0]:
                tight = (ratio, r)
    if tight is not None:
        row = tight[1]
        meets = row["bank_dscr"] >= row["sizing_target_dscr"]
        table.append(_status_row(
            row_id="SIZING_TARGET", label="Sizing target DSCR", role="SIZING_ASSUMPTION",
            description="Sizing assumption — NOT a contractual covenant. It sized the Senior debt on the lender (bank) case.",
            basis="Tightest period of bank-case CFADS ÷ scheduled service against that period's sizing target (lender basis; base-case ratios are not compared with it).",
            required=row["sizing_target_dscr"], operator="≥", actual=row["bank_dscr"], status="AT_OR_ABOVE_TARGET" if meets else "BELOW_TARGET",
            status_label="AT OR ABOVE TARGET" if meets else "BELOW TARGET", severity="OK" if meets else "WARNING",
            periods=[{"period_index": row["period_index"], "date": row["date"], "dscr": row["bank_dscr"]}]))
    else:
        table.append(_status_row(
            row_id="SIZING_TARGET", label="Sizing target DSCR", role="SIZING_ASSUMPTION",
            description="Sizing assumption — NOT a contractual covenant.", basis="Bank-case basis.", required=None, operator="≥", actual=None,
            status=UNAVAILABLE, status_label="UNAVAILABLE", severity="NEUTRAL", reason="The Run persisted no bank-case ratio or sizing target.",
            required_note="not persisted"))

    # LLCR: an aggregate minimum may be persisted; no LLCR covenant term exists, and no per-period series.
    llcr = _num(summary.get("min_llcr"))
    table.append(_status_row(
        row_id="LLCR", label="LLCR", role="OBSERVATION",
        description="Loan-life coverage. Shown only when the Run persisted it; no LLCR covenant term is recorded with a Run.",
        basis="Persisted aggregate minimum LLCR (runtime summary).", required=None, operator="≥", actual=llcr, status="OBSERVED" if llcr is not None else UNAVAILABLE,
        status_label="OBSERVED — no covenant term recorded" if llcr is not None else "UNAVAILABLE",
        severity="NEUTRAL", reason="" if llcr is not None else "LLCR is not persisted by this Run.", actual_reason="LLCR is not persisted by this Run.",
        required_note="no LLCR covenant term is recorded with a Run"))
    return table


# ── series, reserves, schedule ────────────────────────────────────────────────────────────────────────────────────────────────────────
def _frequency(op_rows: Sequence[Mapping]) -> tuple[str, Optional[int]]:
    ppy = max((r["period_in_year"] for r in op_rows if isinstance(r.get("period_in_year"), int)), default=None)
    return FREQUENCY_NAMES.get(ppy, "UNKNOWN"), ppy


def _label(row_date: Optional[str], year: Any, in_year: Any, ppy: Optional[int]) -> str:
    if isinstance(year, int) and isinstance(in_year, int) and ppy == 2:
        return f"{year} H{in_year}"
    if isinstance(year, int) and isinstance(in_year, int) and ppy == 4:
        return f"{year} Q{in_year}"
    return row_date or (str(year) if year is not None else "—")


def _series(entry: Any, rows: Sequence[Mapping[str, Any]], terms: T.RunTerms) -> tuple[list[dict[str, Any]], str, Optional[int]]:
    debt = {r["period"]: r for r in _rows(_map(getattr(entry, "debt_schedule", None)).get("periods")) if isinstance(r.get("period"), int)}
    dist = {r["period"]: r for r in _rows(_map(getattr(entry, "distribution_schedule", None)).get("periods")) if isinstance(r.get("period"), int)}
    cash = {r["period_index"]: r for r in _rows(_map(_map(getattr(entry, "financial_statements", None)).get("pf_cash_waterfall")).get("periods"))
            if isinstance(r.get("period_index"), int)}
    ev = {r["period_index"]: r for r in rows}
    evidence_rows = {p["period_index"]: p for p in _rows(_map(_map(getattr(entry, "integrity_evidence", None)).get("senior_debt")).get("periods"))
                     if isinstance(p.get("period_index"), int)}
    indexes = sorted(set(ev) | {i for i, r in debt.items() if r.get("is_operation")})
    frequency, ppy = _frequency([r for r in debt.values() if r.get("is_operation")])
    eod_x, cov_x = terms.eod.value if terms.recorded else None, terms.contractual.value if terms.recorded else None
    out: list[dict[str, Any]] = []
    for i in indexes:
        r = ev.get(i, {})
        d, s, c = debt.get(i, {}), dist.get(i, {}), cash.get(i, {})
        e = evidence_rows.get(i, {})
        dscr = r.get("dscr")
        flag = s.get("lockup_active")
        out.append({
            "period_index": i, "date": d.get("date") or s.get("date") or r.get("date"), "year": d.get("year_index"),
            "period_in_year": d.get("period_in_year"), "label": _label(d.get("date"), d.get("year_index"), d.get("period_in_year"), ppy),
            "has_debt_service": bool(r.get("applicable")),
            "dscr": dscr, "bank_dscr": r.get("bank_dscr"), "sizing_target_dscr": r.get("sizing_target_dscr"),
            "base_cfads_keur": r.get("base_cfads_keur"), "bank_cfads_keur": r.get("bank_cfads_keur"),
            "debt_service_keur": r.get("debt_service_keur"), "principal_keur": r.get("principal_keur"), "interest_keur": r.get("interest_keur"),
            "senior_opening_keur": _num(e.get("opening")), "senior_closing_keur": _num(e.get("closing")),
            "shortfall_keur": r.get("shortfall_keur"),
            "below_one": None if dscr is None else dscr < 1.0,
            "eod_breach": None if (dscr is None or eod_x is None) else dscr < eod_x,
            "covenant_breach": None if (dscr is None or cov_x is None) else dscr < cov_x,
            "lockup_active": flag if isinstance(flag, bool) else None,
            "dsra_balance_keur": _num(d.get("dsra_balance_keur")), "dsra_contribution_keur": _num(d.get("dsra_contribution_keur")),
            "dsra_funding_keur": _num(c.get("dsra_funding_keur")), "dsra_release_keur": _num(c.get("dsra_release_keur")),
            "distribution_keur": _num(s.get("distribution_keur")), "cash_sweep_keur": _num(s.get("cash_sweep_keur")),
            "senior_balance_keur": _num(d.get("senior_balance_keur")),
        })
    return out, frequency, ppy


def _lockup(series: Sequence[Mapping[str, Any]]) -> dict[str, Any]:
    flagged = [p for p in series if p["lockup_active"] is not None]
    if not flagged:
        return {"available": False, "reason": "The Run persisted no per-period lock-up flags.", "active_count": None, "periods": []}
    return {"available": True, "reason": "", "active_count": sum(1 for p in flagged if p["lockup_active"]),
            "periods": [{"period_index": p["period_index"], "label": p["label"], "date": p["date"], "active": p["lockup_active"]} for p in flagged],
            "note": "Per-period flags persisted by the distribution schedule; the lock-up threshold value is not persisted with a Run."}


def _reserves(entry: Any, series: Sequence[Mapping[str, Any]], lockup: Mapping[str, Any]) -> dict[str, Any]:
    su = _map(_map(_map(getattr(entry, "integrity_evidence", None)).get("sources_uses")).get("summary"))
    initial = _num(su.get("initial_dsra_funding_keur"))
    balances = [p["dsra_balance_keur"] for p in series if p["dsra_balance_keur"] is not None]
    present = any(b > 0 for b in balances)
    if not balances:
        dsra: dict[str, Any] = {"available": False, "reason": "The Run persisted no DSRA balance series.", "present": False}
    else:
        dsra = {"available": True, "present": present, "initial_funding_keur": initial,
                "reason": "" if present else ("No cash DSRA balance in this Run" + (" (initial cash DSRA funding is 0)." if initial == 0 else ".")),
                "peak_balance_keur": max(balances), "required": {"available": False,
                        "reason": "The required DSRA amount is not persisted with a Run (it is derived by the engine); only the balance and its movements are."}}
    return {"dsra": dsra,
            "dsrf": {"available": False, "reason": "A standby reserve facility (DSRF) commitment and its drawings are not persisted with a Run. A cash DSRA balance is not a DSRF commitment."},
            "lockup": dict(lockup)}


_SCHEDULE = (
    ("debt", "Senior debt", (
        ("senior_opening_keur", "Senior debt — opening", "kEUR"), ("principal_keur", "Principal", "kEUR"), ("interest_keur", "Interest", "kEUR"),
        ("debt_service_keur", "Scheduled debt service", "kEUR"), ("senior_closing_keur", "Senior debt — closing", "kEUR"))),
    ("coverage", "Coverage", (
        ("base_cfads_keur", "Base-case CFADS", "kEUR"), ("bank_cfads_keur", "Bank-case CFADS", "kEUR"), ("dscr", "DSCR (base case)", "x"),
        ("bank_dscr", "DSCR (bank case)", "x"), ("shortfall_keur", "Period shortfall (service − base CFADS; negative = surplus)", "kEUR"))),
    ("terms", "Thresholds and tests", (
        ("sizing_target_dscr", "Sizing target DSCR (assumption)", "x"), ("below_one", "DSCR below 1.00x", "flag"),
        ("covenant_breach", "Below Contractual DSCR", "flag"), ("eod_breach", "Below Minimum DSCR (EoD threshold)", "flag"),
        ("lockup_active", "Distribution lock-up", "flag"))),
    ("reserves", "Reserves and distributions", (
        ("dsra_balance_keur", "DSRA balance", "kEUR"), ("dsra_funding_keur", "DSRA funding", "kEUR"), ("dsra_release_keur", "DSRA release", "kEUR"),
        ("distribution_keur", "Distributions", "kEUR"), ("cash_sweep_keur", "Cash sweep", "kEUR"))),
)


def _schedule(series: Sequence[Mapping[str, Any]], terms: T.RunTerms) -> list[dict[str, Any]]:
    groups = []
    for group_id, label, definitions in _SCHEDULE:
        items = []
        for key, row_label, unit in definitions:
            values = [p.get(key) for p in series]
            available = any(v is not None for v in values)
            reason = "" if available else "Not persisted by this Run."
            if key == "eod_breach" and not (terms.recorded and terms.eod.status == T.CONFIGURED):
                reason = "No Minimum DSCR (EoD threshold) is recorded with this Run."
                values, available = [None for _ in series], False
            if key == "covenant_breach" and not (terms.recorded and terms.contractual.status == T.CONFIGURED):
                reason = "No Contractual DSCR is recorded with this Run."
                values, available = [None for _ in series], False
            items.append({"key": key, "label": row_label, "unit": unit, "values": values, "available": available, "reason": reason})
        groups.append({"id": group_id, "label": label, "rows": items})
    return groups


def _kpis(ev: Mapping[str, Any], rows: Sequence[Mapping[str, Any]], summary: Mapping[str, Any], entry: Any) -> dict[str, Any]:
    achieved = _map(ev["achieved_min_dscr"])
    applicable = [r["dscr"] for r in rows if r["applicable"] and r["dscr"] is not None]
    avg = _num(summary.get("avg_dscr"))
    recomputed = math.fsum(applicable) / len(applicable) if applicable else None
    gearing = _num(summary.get("actual_gearing_pct"))
    terminal = _map(_map(_map(getattr(entry, "sponsor_schedule", None)).get("summary")).get("terminal_financial_state")).get("senior")
    senior = _map(terminal)
    llcr = _num(summary.get("min_llcr"))
    plcr = _num(summary.get("plcr"))
    return {
        "achieved_min_dscr": {"label": "Achieved Min DSCR", "available": bool(achieved.get("available")), "value": achieved.get("min"),
                              "display": _x(achieved.get("min"), (1.0,), achieved.get("reason", ""))["d"], "period": achieved.get("period"),
                              "basis": "Result: the measured minimum of this Run's applicable per-period base-case DSCR (not an input).",
                              "reason": achieved.get("reason", "")},
        "average_dscr": {"label": "Average DSCR", "available": avg is not None, "value": avg, "display": _x(avg)["d"],
                         "basis": ("Persisted Run summary. Equals the mean of the applicable per-period DSCR." if (avg is not None and recomputed is not None and abs(avg - recomputed) <= 1e-9)
                                   else "Persisted Run summary; its averaging convention was not independently reproduced from the period rows."),
                         "reproduced_from_periods": bool(avg is not None and recomputed is not None and abs(avg - recomputed) <= 1e-9),
                         "reason": "" if avg is not None else "Not persisted by this Run."},
        "llcr": {"label": "LLCR", "available": llcr is not None, "value": llcr, "display": _x(llcr)["d"], "basis": "Persisted aggregate minimum LLCR; no per-period LLCR series is persisted.",
                 "reason": "" if llcr is not None else "LLCR is not persisted by this Run."},
        "plcr": {"label": "PLCR", "available": plcr is not None, "value": plcr, "display": _x(plcr)["d"], "basis": "Persisted PLCR.",
                 "reason": "" if plcr is not None else "PLCR is not persisted by this Run."},
        "gearing": {"label": "Actual funded gearing", "available": gearing is not None, "value": gearing,
                    "display": f"{gearing * 100:.2f}%" if gearing is not None else UNAVAILABLE,
                    "basis": "Persisted actual gearing (Senior ÷ Total Project Uses).", "reason": "" if gearing is not None else "Not persisted by this Run."},
        "debt_maturity": {"label": "Senior contractual maturity", "available": isinstance(senior.get("contractual_maturity_date"), str),
                          "value": senior.get("contractual_maturity_date"), "display": senior.get("contractual_maturity_date") or UNAVAILABLE,
                          "status": senior.get("status"), "basis": "Persisted terminal Senior state.", "reason": "" if senior else "Not persisted by this Run."},
    }


# ── entry point ──────────────────────────────────────────────────────────────────────────────────────────────────────────────────────
def build_debt_metrics(entry: Any, *, integrity: Optional[Mapping[str, Any]] = None, state: str = "HISTORICAL") -> dict[str, Any]:
    """The Debt Metrics view-model of one committed Run.  Pure over the Run's own persisted evidence."""
    terms, rows, evaluation, problem = evaluate_run(entry)
    summary = _map(getattr(entry, "runtime_summary", None))
    series, frequency, ppy = _series(entry, rows, terms) if rows else ([], "UNKNOWN", None)
    lockup = _lockup(series)
    available = bool(rows)
    return {
        "schema": SCHEMA, "available": available,
        "reason": "" if available else (problem or "No committed Senior-debt period evidence for this Run."),
        "run_state": state, "basis_note": BASIS_NOTE,
        "contract_terms": {
            "recorded": terms.recorded, "reason": terms.reason,
            "eod_minimum_dscr": {"status": terms.eod.status, "value": terms.eod.value, "raw": terms.eod.raw, "label": "Minimum DSCR (EoD threshold)"},
            "contractual_dscr": {"status": terms.contractual.status, "value": terms.contractual.value, "raw": terms.contractual.raw, "label": "Contractual DSCR (covenant)"},
            "test_basis": dict(T.TEST_BASIS),
            "note": "The two inputs are recorded with each Run when it is committed; editing them later never changes a historical Run.",
        },
        "evaluation": evaluation,
        "covenant_table": _covenant_table(evaluation, rows, summary, lockup) if available else [],
        "kpis": _kpis(evaluation, rows, summary, entry),
        "axis": {"frequency": frequency, "periods_per_year": ppy, "period_count": len(series),
                 "note": "Periods are shown on the Run's own committed calendar; no aggregation or averaging across periods is applied."},
        "periods": series,
        "series": {
            "llcr": {"available": False, "reason": "LLCR is persisted only as an aggregate minimum; this Run has no per-period LLCR series."},
            "thresholds": {"coverage_x": 1.0, "eod_x": terms.eod.value if (terms.recorded and terms.eod.status == T.CONFIGURED) else None,
                           "contractual_x": terms.contractual.value if (terms.recorded and terms.contractual.status == T.CONFIGURED) else None,
                           "sizing_target_note": "The sizing target varies by period and is plotted from each period's persisted value."},
        },
        "reserves": _reserves(entry, series, lockup) if available else None,
        "schedule": _schedule(series, terms) if available else [],
        "integrity": {"status": (integrity or {}).get("status", UNAVAILABLE), "failures": list((integrity or {}).get("failures") or [])},
    }
