"""Reserve Coverage evidence (FIN-V2-R1): a READ-ONLY, additive projection of one completed clean run.

HARD RULES
- Nothing here changes a Run, Senior debt, funding or waterfall. The Senior debt service, the recorded
  Cash DSRA balance and the maturity / payoff facts are READ from the completed canonical result (payoff
  and maturity through the merged FIN-V2-C1-FIX-1a ``senior_debt_evidence`` authority). The only
  derived quantities are the calendar requirement (``financial_engine.dsra.forward_coverage``), and
  shortfall / excess differences against the RECORDED balance.
- It is NOT written into the Run payload by this change (that would alter committed payloads); a caller
  builds it on demand from a clean run. A committed Run has no such block and
  ``project_reserve_coverage_evidence`` states ``NOT_RECORDED``; history is never rebuilt.
- Unavailable data is a typed status, never zero. Both coverage conventions are reported side by side
  because the product has not ratified one (FORWARD_CALENDAR_COVERAGE_V1 never selects implicitly).
- This block describes a REQUIREMENT. It never claims that automatic Cash DSRA funding under the
  calendar policy is active: ``funding_activation`` states the gate.
"""
from __future__ import annotations

import math
from typing import Any, Mapping, Optional

from financial_engine.dsra.forward_coverage import (
    POLICY_VERSION,
    CoverageConvention,
    CoverageStatus,
    compute_forward_coverage,
)
from financial_engine.dsra.reserve_authority import (
    CALENDAR_V1_GATE,
    ReserveAuthorityError,
    classify_financing,
)

SCHEMA_VERSION = "RESERVE_COVERAGE_EVIDENCE_V1"
AUTHORITY = "CANONICAL_RUN_READ_ONLY_PROJECTION"
EVIDENCE_KEY = "reserve_coverage_evidence"

STATUS_RECORDED = "RECORDED"
STATUS_NOT_RECORDED = "NOT_RECORDED"
STATUS_NO_SENIOR = "NOT_APPLICABLE_NO_SENIOR"
STATUS_UNSUPPORTED_STRUCTURE = "UNSUPPORTED_FACILITY_STRUCTURE"
STATUS_UNAVAILABLE = "EVIDENCE_UNAVAILABLE"

BALANCE_NO_CASH_DSRA = "NO_CASH_DSRA_RECORDED"
BALANCE_RECORDED = "RECORDED"

_TOL = 1e-6


def _status(status: str, reason: str) -> dict:
    return {"schema_version": SCHEMA_VERSION, "status": status, "reason": reason}


def _f(v: Any) -> Optional[float]:
    try:
        x = float(v)
    except (TypeError, ValueError):
        return None
    return x if math.isfinite(x) else None


def _iso(d) -> Optional[str]:
    return d.isoformat() if d is not None else None


def _convention_block(result, balances: Mapping[int, Optional[float]], recorded_required: Mapping[int, float]) -> dict:
    rows = []
    for r in result.rows:
        bal = balances.get(r.test_period_index)
        req = r.required_keur
        shortfall = excess = None
        if req is not None and bal is not None:
            shortfall = max(req - bal, 0.0)
            excess = max(bal - req, 0.0)
            shortfall = 0.0 if shortfall < _TOL else shortfall
            excess = 0.0 if excess < _TOL else excess
        rows.append({
            "test_period_index": r.test_period_index, "test_date": _iso(r.test_date),
            "is_cod_test": r.is_cod_test, "window_end_date": _iso(r.window_end), "status": r.status.value,
            "required_reserve_keur": req,
            "covered_payments": [{"period_index": p.period_index, "due_date": _iso(p.due_date),
                                  "debt_service_keur": p.debt_service_keur, "covered_fraction": p.covered_fraction,
                                  "covered_keur": p.covered_keur} for p in r.payments],
            "recorded_cash_dsra_balance_keur": bal,
            "recorded_historical_target_keur": recorded_required.get(r.test_period_index),
            "reserve_shortfall_keur": shortfall, "excess_coverage_keur": excess,
        })
    return {
        "convention": result.convention.value, "peak_reserve_requirement_keur": result.peak_required_keur,
        "peak_test_date": _iso(result.peak_test_date), "peak_status": result.peak_status.value, "rows": rows,
    }


def build_reserve_coverage_evidence(
    *, financing, capex, periods, senior_debt_service_by_index: Mapping[int, float], senior_axis,
    cash_dsra, senior_evidence: Mapping[str, Any], coverage_months: Optional[int] = None,
) -> dict:
    """Pure assembly from already-computed facts. Never raises for unavailable data (typed status)."""
    try:
        selection = classify_financing(financing, capex)
    except ReserveAuthorityError as exc:
        return _status(STATUS_UNAVAILABLE, exc.code)
    months = coverage_months if coverage_months is not None else (selection.coverage_months or getattr(financing, "dsra_months", None))
    if senior_evidence.get("status") not in (None, "RECORDED") and senior_evidence.get("repayment") is None:
        return _status(STATUS_NO_SENIOR if senior_evidence.get("status") == "NOT_APPLICABLE_NO_SENIOR"
                       else STATUS_UNAVAILABLE, f"Senior debt evidence: {senior_evidence.get('status')}")
    repayment = senior_evidence.get("repayment") or {}
    maturity_iso = repayment.get("contractual_maturity_date")
    if not axis_ok(senior_axis) or maturity_iso is None:
        return _status(STATUS_UNAVAILABLE, "contractual Senior maturity unavailable")
    from datetime import date as _date
    maturity = _date.fromisoformat(maturity_iso)
    if not isinstance(months, int) or isinstance(months, bool) or months <= 0:
        return {"schema_version": SCHEMA_VERSION, "status": STATUS_UNAVAILABLE,
                "reason": "RESERVE_COVERAGE_MONTHS_NOT_SELECTED",
                "selected_policy": selection.to_dict(), "funding_activation": CALENDAR_V1_GATE}

    ordered = sorted(periods, key=lambda p: p.period_index)
    axis = set(senior_axis)
    ds = [float(senior_debt_service_by_index[p.period_index]) if p.period_index in senior_debt_service_by_index
          else (0.0 if p.period_index not in axis else None) for p in ordered]
    balances: dict[int, Optional[float]] = {}
    recorded_required: dict[int, float] = {}
    balance_status = BALANCE_NO_CASH_DSRA
    if cash_dsra is not None and getattr(cash_dsra, "mode", "") == "CASH_DSRA":
        balance_status = BALANCE_RECORDED
        for pr in cash_dsra.period_results:
            balances[pr.period_index] = _f(pr.closing_balance_keur)
            recorded_required[pr.period_index] = _f(pr.required_balance_keur)
    # COD test date balance = opening of the first operating period (initial funding).
    if balance_status == BALANCE_RECORDED:
        first_op = next((pr for pr in cash_dsra.period_results if not pr.is_construction), None)
        cod_idx = max((p.period_index for p in ordered if p.is_construction), default=None)
        if first_op is not None and cod_idx is not None:
            balances[cod_idx] = _f(first_op.opening_balance_keur)

    conventions = {}
    for conv in (CoverageConvention.DUE_DATE_WINDOW, CoverageConvention.PRORATED_PERIOD):
        result = compute_forward_coverage(
            period_indices=[p.period_index for p in ordered], period_start_dates=[p.period_start for p in ordered],
            period_end_dates=[p.period_end for p in ordered], is_construction=[bool(p.is_construction) for p in ordered],
            senior_debt_service_keur=ds, coverage_months=months, convention=conv, senior_maturity_date=maturity)
        conventions[conv.value] = _convention_block(result, balances if balance_status == BALANCE_RECORDED else {}, recorded_required)

    return {
        "schema_version": SCHEMA_VERSION, "authority": AUTHORITY, "status": STATUS_RECORDED,
        "methodology": {"policy_version": POLICY_VERSION, "status": "REQUIREMENT_AND_PROJECTION_ONLY",
                        "convention_ratified": False, "kinds": ["forward", "peak_forward"]},
        "selected_policy": selection.to_dict(), "coverage_months": months,
        "future_senior_debt_service_basis": "FINAL_SENIOR_DEBT_SERVICE_SCHEDULE_DATE_AWARE",
        "contractual_senior_maturity_date": maturity_iso,
        "actual_senior_payoff_date": repayment.get("actual_payoff_date"),
        "senior_payoff_status": repayment.get("payoff_status"),
        "recorded_cash_dsra_status": balance_status,
        "conventions": conventions,
        "funding_activation": {"calendar_v1_automatic_funding": "UNAVAILABLE", "reason": CALENDAR_V1_GATE},
    }


def axis_ok(senior_axis) -> bool:
    return bool(senior_axis)


def build_from_clean_run(clean_run: Any, *, coverage_months: Optional[int] = None, project_type: Optional[str] = None) -> dict:
    """Adapter over a completed ``CleanProductionRun``. Reads only; failures become typed statuses."""
    try:
        from app.run_integrity.senior_debt_evidence import build_from_clean_run as senior_evidence
        fin = clean_run.g2c_result.financing_result
        from financial_engine.financing.junior_debt import JuniorFinancingResult
        from financial_engine.financing.multisenior import MultiSeniorFinancingResult
        if isinstance(fin, (MultiSeniorFinancingResult, JuniorFinancingResult)):
            return _status(STATUS_UNSUPPORTED_STRUCTURE, type(fin).__name__)
        model = fin.project_model_result
        if model.senior_debt is None or model.axis_contract is None:
            return _status(STATUS_NO_SENIOR, "no Senior debt schedule in the model result")
        sd = model.senior_debt
        by_index = dict(zip((int(i) for i in sd.period_indices), sd.senior_debt_service_keur))
        pi = clean_run.project_inputs
        return build_reserve_coverage_evidence(
            financing=pi.financing, capex=pi.capex, periods=model.periods,
            senior_debt_service_by_index=by_index, senior_axis=model.axis_contract.senior_axis,
            cash_dsra=_modal_cash_dsra(model), senior_evidence=senior_evidence(clean_run, project_type=project_type),
            coverage_months=coverage_months)
    except Exception as exc:  # evidence must never fail a Run; the typed status keeps the cause visible
        return _status(STATUS_UNAVAILABLE, f"{type(exc).__name__}")


def _modal_cash_dsra(model):
    schedules = getattr(model, "cash_dsra", None)
    if schedules is None:
        return None

    class _View:
        mode = str(getattr(schedules, "mode", "") or "")
        period_results = schedules.period_results
    mode = _View.mode.split(".")[-1].upper()
    _View.mode = mode
    return _View


def project_reserve_coverage_evidence(runtime_summary: Optional[Mapping[str, Any]]) -> dict:
    """Read-only projection for a COMMITTED Run: absent evidence is NOT_RECORDED, never rebuilt, never zero."""
    fe = (runtime_summary or {}).get("financing_evidence") if isinstance(runtime_summary, Mapping) else None
    block = fe.get(EVIDENCE_KEY) if isinstance(fe, Mapping) else None
    if isinstance(block, Mapping) and block.get("schema_version") == SCHEMA_VERSION:
        return dict(block)
    return _status(STATUS_NOT_RECORDED, "Run committed before Reserve Coverage evidence existed; not reconstructed")
