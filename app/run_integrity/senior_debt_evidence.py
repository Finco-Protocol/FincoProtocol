"""Senior Debt transparency evidence (FIN-V2-C1-FIX-1a): contractual maturity vs actual payoff, the
binding sizing constraint and the DSCR bases, as a READ-ONLY projection of one completed clean run.

HARD RULES
- Nothing here calculates a financial result. Every amount, balance, capacity, CFADS and DSCR is read
  from the already-computed canonical ``ProjectModelResult`` and copied at full precision. The only
  derived quantities are period/date lookups, counts, differences of recorded periods, a min/avg of
  recorded DSCR values and boolean consistency checks. No solver, sizing, repayment, DSRA, IDC or
  gearing arithmetic is performed or changed.
- A Run records this block under ``financing_evidence.senior_debt_evidence`` so it inherits the Run's
  ``run_binding`` (snapshot id, composite hash, scenario). Runs committed before this block existed
  carry no such key; ``project_senior_debt_evidence`` then states ``NOT_RECORDED`` and never rebuilds it.
- Failures to describe a structure are typed statuses, never zero and never an exception that could fail
  a Run.

Definitions (all period indices are MODEL period indices of the Senior axis)
- contractual repayment start / maturity: first / last index of the policy-derived Senior axis.
- actual payoff: the period in which the Senior balance is extinguished = the last period with an opening
  balance above ``tolerance_keur`` provided its closing balance is within tolerance. Date = that period's end.
- active (zero-amortisation) rows: repayment-window rows with debt service above tolerance and principal
  within tolerance. In a DSCR-sculpted schedule these are the rows where the non-negative-amortisation
  limit is active, i.e. where the DSCR debt-service budget covers interest only.
- RAMP_UP_INTEREST_COVERAGE: active rows exist, all precede the window's peak bank CFADS, and the first later
  row with principal has higher bank CFADS than the last active row (interest cover binds while CFADS is
  still rising). Purely observational; no threshold is invented.
"""
from __future__ import annotations

import math
from typing import Any, Mapping, Sequence

SCHEMA_VERSION = "SENIOR_DEBT_EVIDENCE_V1"
AUTHORITY = "CANONICAL_SENIOR_DEBT_RESULT_READ_ONLY_PROJECTION"
EVIDENCE_KEY = "senior_debt_evidence"

# Same absolute tolerance the Senior adapter hands to the solver (convergence_tolerance_keur).
DEFAULT_TOLERANCE_KEUR = 1e-4

STATUS_RECORDED = "RECORDED"
STATUS_NOT_RECORDED = "NOT_RECORDED"
STATUS_NO_SENIOR = "NOT_APPLICABLE_NO_SENIOR"
STATUS_UNSUPPORTED_STRUCTURE = "UNSUPPORTED_FACILITY_STRUCTURE"
STATUS_UNAVAILABLE = "EVIDENCE_UNAVAILABLE"

PAYOFF_AT_MATURITY = "EXTINGUISHED_AT_CONTRACTUAL_MATURITY"
PAYOFF_BEFORE_MATURITY = "EXTINGUISHED_BEFORE_CONTRACTUAL_MATURITY"
PAYOFF_NOT_EXTINGUISHED = "NOT_EXTINGUISHED_AT_CONTRACTUAL_MATURITY"

NATURE_GEARING = "GEARING_CAP"
NATURE_RAMP_UP = "RAMP_UP_INTEREST_COVERAGE"
NATURE_ZERO_AMORT = "ZERO_AMORTISATION_ROW_BINDS"
NATURE_FULL_TENOR = "FULL_TENOR_DSCR_BUDGET"
NATURE_UNCLASSIFIED = "UNCLASSIFIED_DSCR_LIMIT"



def _f(value: Any) -> float | None:
    if value is None or isinstance(value, bool):
        return None
    try:
        out = float(value)
    except (TypeError, ValueError):
        return None
    return out if math.isfinite(out) else None


def _iso(value: Any) -> str | None:
    return value.isoformat() if hasattr(value, "isoformat") else None


def _status(status: str, reason: str) -> dict:
    return {"schema_version": SCHEMA_VERSION, "authority": AUTHORITY, "status": status, "reason": reason}


def _by_index(indices: Sequence[int], values: Sequence[Any]) -> dict[int, Any]:
    if len(indices) != len(values):
        raise ValueError("period vector length mismatch")
    out: dict[int, Any] = {}
    for i, v in zip(indices, values):
        if i in out:
            raise ValueError(f"duplicate period index {i}")
        out[int(i)] = v
    return out


def build_senior_debt_evidence(
    *,
    periods: Sequence[Any],
    senior_debt: Any,
    senior_axis: Sequence[int],
    bank_period_indices: Sequence[int],
    bank_cfads_keur: Sequence[float],
    bank_sizing_dscr: Sequence[float | None],
    base_period_indices: Sequence[int],
    base_cfads_keur: Sequence[float],
    target_dscr: float | None,
    gearing_ratio: float | None,
    gearing_basis_keur: float | None,
    debt_sizing_mode: str | None,
    sizing_yield_scenario: str | None,
    contractual_maturity_period_index: int | None = None,
    project_type: str | None = None,
    standalone_dscr_capacity_keur: float | None = None,
    project_gearing_capacity_keur: float | None = None,
    tolerance_keur: float = DEFAULT_TOLERANCE_KEUR,
) -> dict:
    """Return the JSON-native evidence block. Never raises for an unsupported/empty structure."""
    axis = tuple(int(i) for i in senior_axis)
    if not axis:
        return _status(STATUS_NO_SENIOR, "empty Senior axis")
    sd_idx = tuple(int(i) for i in senior_debt.period_indices)
    if sd_idx != axis:
        return _status(STATUS_UNAVAILABLE, "Senior schedule axis differs from the policy-derived Senior axis")
    tol = float(tolerance_keur)
    size = _f(senior_debt.debt_size_keur)
    if size is None or size <= tol:
        return _status(STATUS_NO_SENIOR, "sized Senior debt is zero")

    per = {int(p.period_index): p for p in periods}
    if any(i not in per for i in axis):
        return _status(STATUS_UNAVAILABLE, "Senior axis not contained in the model period axis")

    opening = _by_index(sd_idx, senior_debt.senior_debt_opening_keur)
    interest = _by_index(sd_idx, senior_debt.senior_interest_keur)
    principal = _by_index(sd_idx, senior_debt.senior_principal_keur)
    service = _by_index(sd_idx, senior_debt.senior_debt_service_keur)
    closing = _by_index(sd_idx, senior_debt.senior_debt_closing_keur)
    base_dscr = _by_index(sd_idx, senior_debt.base_dscr)
    bank_cf = _by_index(bank_period_indices, bank_cfads_keur)
    bank_dscr = _by_index(bank_period_indices, bank_sizing_dscr)
    base_cf = _by_index(base_period_indices, base_cfads_keur)

    start_idx, maturity_idx = axis[0], axis[-1]
    if contractual_maturity_period_index is not None and int(contractual_maturity_period_index) != maturity_idx:
        return _status(STATUS_UNAVAILABLE, "contractual maturity of the terminal state differs from the Senior axis")

    # ── repayment / payoff ──────────────────────────────────────────────────────────────────────
    funded = [i for i in axis if (_f(opening[i]) or 0.0) > tol]
    payoff_idx = funded[-1] if funded else None
    if payoff_idx is not None and (_f(closing[payoff_idx]) or 0.0) > tol:
        payoff_idx = None
        payoff_status = PAYOFF_NOT_EXTINGUISHED
    elif payoff_idx is None:
        return _status(STATUS_NO_SENIOR, "no period with an opening Senior balance")
    elif payoff_idx == maturity_idx:
        payoff_status = PAYOFF_AT_MATURITY
    else:
        payoff_status = PAYOFF_BEFORE_MATURITY
    first_principal_idx = next((i for i in axis if (_f(principal[i]) or 0.0) > tol), None)
    maturity_end = per[maturity_idx].period_end
    payoff_end = per[payoff_idx].period_end if payoff_idx is not None else None

    repayment = {
        "index_axis": "MODEL_PERIOD_INDEX",
        "contractual_repayment_start_period_index": start_idx,
        "contractual_repayment_start_date": _iso(per[start_idx].period_start),
        "contractual_maturity_period_index": maturity_idx,
        "contractual_maturity_date": _iso(maturity_end),
        "first_principal_period_index": first_principal_idx,
        "first_principal_date": _iso(per[first_principal_idx].period_end) if first_principal_idx is not None else None,
        "actual_payoff_period_index": payoff_idx,
        "actual_payoff_date": _iso(payoff_end),
        "payoff_status": payoff_status,
        "periods_maturity_minus_payoff": (maturity_idx - payoff_idx) if payoff_idx is not None else None,
        "days_maturity_minus_payoff": (maturity_end - payoff_end).days if payoff_end is not None else None,
        "tolerance_keur": tol,
    }

    # ── sizing constraint ───────────────────────────────────────────────────────────────────────
    diag = dict(senior_debt.diagnostics or {})
    engine_label = senior_debt.binding_constraint or diag.get("binding_constraint")
    dscr_cap = _f(diag.get("dscr_debt_capacity_keur"))
    gear_cap = _f(diag.get("gearing_debt_capacity_keur"))
    from_caps = None
    if dscr_cap is not None and gear_cap is not None:
        from_caps = "BOTH" if abs(dscr_cap - gear_cap) <= tol else ("DSCR" if dscr_cap < gear_cap else "GEARING")
    binding_cap = {"DSCR": dscr_cap, "GEARING": gear_cap, "BOTH": dscr_cap}.get(engine_label)
    window = [i for i in axis]
    active = [i for i in window
              if (_f(service[i]) or 0.0) > tol and (_f(principal[i]) or 0.0) <= tol]

    def row(i: int) -> dict:
        return {
            "period_index": i, "period_end_date": _iso(per[i].period_end),
            "opening_balance_keur": _f(opening[i]), "interest_keur": _f(interest[i]),
            "principal_keur": _f(principal[i]), "debt_service_keur": _f(service[i]),
            "bank_cfads_keur": _f(bank_cf.get(i)), "bank_sizing_dscr": _f(bank_dscr.get(i)),
        }

    limiting_rows: list[dict] = []
    context: dict | None = None
    if engine_label in ("DSCR", "BOTH"):
        limiting_rows = [row(i) for i in active]
        cf_win = {i: _f(bank_cf.get(i)) for i in window}
        peak_idx = max((i for i in window if cf_win[i] is not None), key=lambda i: cf_win[i], default=None)
        positive_after = None
        if active:
            positive_after = next((i for i in window if i > active[-1] and (_f(principal[i]) or 0.0) > tol), None)
        ramp = bool(
            active and peak_idx is not None and positive_after is not None
            and active[-1] < peak_idx
            and cf_win[positive_after] is not None and cf_win[active[-1]] is not None
            and cf_win[positive_after] > cf_win[active[-1]]
        )
        if active:
            nature = NATURE_RAMP_UP if ramp else NATURE_ZERO_AMORT
        elif payoff_status == PAYOFF_AT_MATURITY:
            nature = NATURE_FULL_TENOR
        else:
            nature = NATURE_UNCLASSIFIED
        if active and peak_idx is not None and cf_win[peak_idx]:
            context = {
                "limiting_bank_cfads_keur": cf_win[active[0]],
                "window_peak_bank_cfads_keur": cf_win[peak_idx],
                "window_peak_period_index": peak_idx,
                "limiting_to_peak_cfads_ratio": (cf_win[active[0]] / cf_win[peak_idx]) if cf_win[active[0]] is not None else None,
                "first_amortising_period_after_limit": positive_after,
            }
    else:
        nature = NATURE_GEARING

    if payoff_status == PAYOFF_AT_MATURITY:
        explanation = "FULL_TENOR_REPAYMENT"
    elif payoff_status == PAYOFF_NOT_EXTINGUISHED:
        explanation = "BALANCE_OUTSTANDING_AT_MATURITY"
    elif engine_label == "GEARING" and dscr_cap is not None and gear_cap is not None and dscr_cap > gear_cap:
        explanation = "GEARING_CAP_BELOW_DSCR_CAPACITY_SCULPTED_BUDGET_RETIRES_DEBT_EARLY"
    elif engine_label in ("DSCR", "BOTH") and active:
        explanation = "ZERO_AMORTISATION_ROWS_LIMIT_CAPACITY_LATER_DSCR_BUDGET_RETIRES_DEBT_EARLY"
    else:
        explanation = "UNCLASSIFIED_EARLY_PAYOFF"

    sizing = {
        "debt_sizing_mode": debt_sizing_mode,
        "debt_size_keur": size,
        "binding_constraint": engine_label,
        "binding_constraint_source": "SENIOR_DEBT_RESULT.binding_constraint / SolverDiagnostics",
        # Two DSCR capacities exist by design and are never merged: the funded-pass solver diagnostic is the
        # value the final loan is the minimum of (financing/project.py: expected_final_senior); the standalone
        # DSCR-only capacity pass is what financing_evidence.bankability reports.
        "dscr_debt_capacity_keur": dscr_cap,
        "dscr_debt_capacity_basis": "SOLVER_DIAGNOSTICS_FUNDED_PASS (used in the sizing minimum)",
        "dscr_debt_capacity_standalone_pass_keur": _f(standalone_dscr_capacity_keur),
        "dscr_debt_capacity_standalone_basis": "PROJECT_FINANCING_RESULT DSCR-only capacity pass (as in financing_evidence.bankability)",
        "dscr_capacity_pass_difference_keur": (
            abs(dscr_cap - _f(standalone_dscr_capacity_keur))
            if dscr_cap is not None and _f(standalone_dscr_capacity_keur) is not None else None),
        "gearing_debt_capacity_keur": gear_cap,
        "gearing_debt_capacity_basis": "SOLVER_DIAGNOSTICS (eligible project cost x maximum gearing)",
        "gearing_capacity_project_result_keur": _f(project_gearing_capacity_keur),
        "capacity_difference_keur": (abs(dscr_cap - gear_cap) if dscr_cap is not None and gear_cap is not None else None),
        "binding_from_capacities": from_caps,
        "binding_label_consistent": (from_caps == engine_label) if from_caps is not None else None,
        "debt_equals_binding_capacity": (abs(size - binding_cap) <= max(tol, 1e-6 * size)) if binding_cap is not None else None,
        "gearing_ratio": _f(gearing_ratio),
        "gearing_basis_keur": _f(gearing_basis_keur),
        "limiting_nature": nature,
        "limiting_rows": limiting_rows,
        "limiting_context": context,
        "payoff_explanation": explanation,
        "solver_termination_reason": diag.get("termination_reason"),
        "solver_converged": diag.get("converged"),
    }

    # ── DSCR bases ─────────────────────────────────────────────────────────────────────────────
    def stats(series: dict[int, Any]) -> tuple[float | None, int | None, float | None, int]:
        vals = [(i, _f(series.get(i))) for i in window if _f(series.get(i)) is not None]
        if not vals:
            return None, None, None, 0
        mi, mv = min(vals, key=lambda t: (t[1], t[0]))
        return mv, mi, sum(v for _, v in vals) / len(vals), len(vals)

    s_min, s_idx, s_avg, s_n = stats(bank_dscr)
    r_min, r_idx, r_avg, r_n = stats(base_dscr)
    diff = [abs((_f(bank_cf.get(i)) or 0.0) - (_f(base_cf.get(i)) or 0.0)) for i in window]
    max_diff = max(diff) if diff else None
    dscr = {
        "sizing": {
            "basis": "BANK_SIZING_CASE_CFADS",
            "target_dscr": _f(target_dscr),
            "production_yield_scenario_requested": sizing_yield_scenario,
            "cfads_series": "debt_sizing.bank_cfads_keur",
            "definition": "bank_cfads / senior_debt_service per period",
            "min_realised_dscr": s_min, "min_realised_period_index": s_idx,
            "avg_realised_dscr": s_avg, "periods_counted": s_n,
        },
        "reported": {
            "basis": "BASE_CASE_CFADS",
            "production_basis": "technical.operating_hours_p50 (base-case production)",
            "cfads_series": "tax_and_cfads.cfads_keur",
            "definition": "base_cfads / senior_debt_service per period",
            "min_dscr": r_min, "min_period_index": r_idx, "avg_dscr": r_avg, "periods_counted": r_n,
        },
        "bank_case_distinct_from_base_case": bool(max_diff is not None and max_diff > tol),
        "max_abs_bank_minus_base_cfads_keur": max_diff,
    }

    # ── future LLCR loan-life inputs (no ratio computed here) ───────────────────────────────────
    llcr_inputs = {
        "loan_life_end_candidates": {
            "contractual_maturity_period_index": maturity_idx,
            "contractual_maturity_date": repayment["contractual_maturity_date"],
            "actual_payoff_period_index": payoff_idx,
            "actual_payoff_date": repayment["actual_payoff_date"],
        },
        "llcr_ratio": None,
        "llcr_status": "NOT_COMPUTED_BY_THIS_EVIDENCE",
        "note": "Loan life for LLCR is an Owner-defined convention; both candidates are recorded.",
    }

    return {
        "schema_version": SCHEMA_VERSION, "authority": AUTHORITY, "status": STATUS_RECORDED,
        "units": "kEUR", "project_type": project_type,
        "repayment": repayment, "sizing": sizing, "dscr": dscr, "llcr_inputs": llcr_inputs,
    }


def unsupported_structure_evidence(structure: str) -> dict:
    """Two-Senior / junior structures keep their own facility evidence; no aggregate is invented here."""
    return _status(STATUS_UNSUPPORTED_STRUCTURE, f"{structure}: per-facility evidence lives in facility_schedules")


def build_from_clean_run(clean_run: Any, *, project_type: str | None = None) -> dict:
    """Adapter over a completed ``CleanProductionRun``. Reads only; swallows nothing silently:
    any failure becomes a typed ``EVIDENCE_UNAVAILABLE`` block carrying the exception class."""
    try:
        fin = clean_run.g2c_result.financing_result
        from financial_engine.financing.junior_debt import JuniorFinancingResult
        from financial_engine.financing.multisenior import MultiSeniorFinancingResult
        if isinstance(fin, MultiSeniorFinancingResult):
            return unsupported_structure_evidence("F3_TWO_SENIOR")
        if isinstance(fin, JuniorFinancingResult):
            return unsupported_structure_evidence("JUNIOR_DEBT")
        model = fin.project_model_result
        if model.senior_debt is None or model.axis_contract is None:
            return _status(STATUS_NO_SENIOR, "no Senior debt schedule in the model result")
        terminal = clean_run.g2c_result.return_summary.terminal.senior
        case = getattr(clean_run.project_inputs.financing, "debt_sizing_case", None)
        scenario = getattr(getattr(case, "production_yield_scenario", None), "value", None)
        mode = getattr(getattr(clean_run.project_inputs.financing, "debt_sizing_mode", None), "value", None)
        return build_senior_debt_evidence(
            periods=model.periods, senior_debt=model.senior_debt,
            senior_axis=model.axis_contract.senior_axis,
            bank_period_indices=model.debt_sizing.period_indices,
            bank_cfads_keur=model.debt_sizing.bank_cfads_keur,
            bank_sizing_dscr=model.debt_sizing.bank_sizing_dscr,
            base_period_indices=model.tax_and_cfads.period_indices,
            base_cfads_keur=model.tax_and_cfads.cfads_keur,
            target_dscr=getattr(clean_run.project_inputs.financing, "target_dscr", None),
            gearing_ratio=getattr(fin, "gearing_ratio", None),
            gearing_basis_keur=getattr(fin, "gearing_basis_keur", None),
            debt_sizing_mode=mode, sizing_yield_scenario=scenario,
            contractual_maturity_period_index=terminal.contractual_maturity_period_index,
            project_type=project_type,
            standalone_dscr_capacity_keur=getattr(fin, "dscr_debt_capacity_keur", None),
            project_gearing_capacity_keur=getattr(fin, "gearing_debt_capacity_keur", None),
        )
    except Exception as exc:  # evidence must never fail a Run; the typed status keeps the cause visible
        return _status(STATUS_UNAVAILABLE, f"{type(exc).__name__}")


def project_senior_debt_evidence(runtime_summary: Mapping[str, Any] | None) -> dict:
    """Read-only projection for a COMMITTED Run. Missing evidence is NOT_RECORDED (never rebuilt, never zero)."""
    fe = (runtime_summary or {}).get("financing_evidence") if isinstance(runtime_summary, Mapping) else None
    block = fe.get(EVIDENCE_KEY) if isinstance(fe, Mapping) else None
    if isinstance(block, Mapping) and block.get("schema_version") == SCHEMA_VERSION:
        return dict(block)
    return _status(STATUS_NOT_RECORDED, "Run committed before Senior debt evidence was recorded; not reconstructed")
