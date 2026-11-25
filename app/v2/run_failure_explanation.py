"""SC-10: a structured, plain-language explanation of a refused or failed Run.

Presentation only. It classifies the failure from the TYPED reason the engine/executor already produced (never from free text it invents), says what
it means, points to the input section most likely involved, and states the status of the previous committed Run. It does not change the decision:
a fail-closed refusal (for example ``F3_CONTRACTUAL_SERVICE_CASH_SHORTFALL``) stays a genuine refusal, no Run is recorded and nothing is retried.
"""
from __future__ import annotations

from typing import Any, Optional

KIND_LABELS = {
    "FAIL_CLOSED_REFUSAL": "Model refusal (fail-closed): the inputs, not the system, stopped this Run",
    "INPUT_NOT_RUNNABLE": "Inputs could not be assembled into a runnable model",
    "EXECUTION_ERROR": "Calculation did not complete (nothing was computed)",
    "UNCLASSIFIED": "Unclassified failure",
}

_DEBT = ("Senior debt · capital stack", "tab-debt")
_SETUP = ("Project setup · horizon and construction timing", "tab-project-setup")
_REVENUE = ("Revenue · PPA contracts", "tab-revenue")
_INVESTOR = ("Investor · shareholder-loan terms", "tab-investor")
_RECENT = ("Inputs you changed most recently", "tab-project-setup")

# (token, kind, (section label, tab id), explanation, recovery). Order matters: first match wins.
_RULES = (
    ("DUAL_BALANCING_COST_BASIS_FORBIDDEN", "FAIL_CLOSED_REFUSAL", _REVENUE,
     "Both percentage merchant balancing (% of spot sales) and per-MWh balancing cost are nonzero. The model refuses competing dual balancing deductions rather than double-counting or silently dropping one.",
     "Set either Merchant Balancing (%) or Balancing Cost (EUR/MWh) explicitly to 0 in Revenue -> Balancing & CO2, then Run again."),
    ("UNKNOWN_YIELD_SCENARIO", "INPUT_NOT_RUNNABLE", _SETUP,
     "The selected yield scenario is unrecognized; only documented P50 or P90-10y scenarios are admitted.",
     "Set Yield Scenario to a valid P50 or P90-10y value in Project Setup -> Technical and Run again."),
    ("UNSUPPORTED_CURRENCY_EUR_ONLY", "INPUT_NOT_RUNNABLE", _SETUP,
     "The Working Copy specifies a non-EUR currency label. All FINCO financial calculations operate strictly in EUR with no FX conversion contract.",
     "Reset Currency to EUR in Project Setup -> Identity to execute a EUR Run, or keep historical snapshots read-only."),
    ("R04_PHYSICAL_SHORTFALL_NO_SETTLEMENT_CONTRACT", "FAIL_CLOSED_REFUSAL", _REVENUE,
     "The physical PPA commitments fit the P50 envelope, but exceed available generation in the selected bank/debt-sizing case without an approved shortfall settlement contract.",
     "Reduce the declared physical PPA annual quantities or adjust contract dates to fit bank-case generation, review the lender-case policy in Bankability where supported, or supply an approved settlement contract when supported."),
    ("R04_GLOBAL_P50_CAP_EXCEEDED", "FAIL_CLOSED_REFUSAL", _REVENUE,
     "The sum of physical PPA commitments exceeds the canonical P50 generation envelope.",
     "Reduce the declared annual physical PPA quantities or adjust contract dates so total commitments fit within P50."),
    ("SHL_MATURITY_NOT_ON_PERIOD_GRID_FAILS_CLOSED", "FAIL_CLOSED_REFUSAL", _SETUP,
     "The shareholder loan matures after the last period the model covers, so there is no period on which it could be repaid.",
     "Lengthen the project horizon so the model covers the shareholder-loan maturity, or review the shareholder-loan terms. The model never moves the maturity for you."),
    ("SHL_MATURITY_RESIDUAL_FAILS_CLOSED", "FAIL_CLOSED_REFUSAL", _INVESTOR,
     "These inputs leave part of the shareholder loan unpaid at its maturity.",
     "Increase share capital / equity funding or lower senior gearing, adjust shareholder-loan repayment/maturity terms, or review revenue, OPEX, and CAPEX, then Run again."),
    ("F3_CONTRACTUAL_SERVICE_CASH_SHORTFALL", "FAIL_CLOSED_REFUSAL", _DEBT,
     "Project cash cannot pay the contractual Senior debt service, including principal due at maturity. The model does not invent a repayment or refinancing.",
     "Review the facility terms (commitment, rate, grace, maturity) or the revenue and cost inputs that fund debt service."),
    ("F3_PERIOD_OVERFUNDING", "FAIL_CLOSED_REFUSAL", _DEBT,
     "A dated facility draw is larger than construction Uses in that period.", "Adjust the draw dates or amounts."),
    ("F3_AGGREGATE_GEARING_CAP_EXCEEDED", "FAIL_CLOSED_REFUSAL", _DEBT,
     "The explicit facility commitments exceed the project gearing cap. No automatic resizing is applied.", "Reduce the commitments or review the gearing cap."),
    ("F3_MATURITY_NOT_ON_OPERATING_BOUNDARY", "FAIL_CLOSED_REFUSAL", _DEBT,
     "A facility maturity does not fall on an operating period end.", "Choose a maturity date that matches an operating period end."),
    ("F3_DRAW_OUTSIDE_CONSTRUCTION", "FAIL_CLOSED_REFUSAL", _DEBT, "A facility draw falls outside the construction period.", "Move the draw into construction."),
    ("F3_GRACE_EXCEEDS_MATURITY", "FAIL_CLOSED_REFUSAL", _DEBT, "No principal-eligible period remains before maturity.", "Shorten the grace period or extend the maturity."),
    # RC-7B matched 3/3 candidate (release-closed): typed refusals, never "unclassified".
    ("QUARTERLY_ADMISSION_CLOSED", "FAIL_CLOSED_REFUSAL", _SETUP,
     "This Working Copy selects the matched 3/3 (quarterly) operating and debt frequency. It is a release-closed candidate pending "
     "independent financial review and owner decisions, so no Run is produced.",
     "Reset the operating/debt frequency to the released 6/6 default to Run the model."),
    ("QUARTERLY_RESERVE_POLICY_PENDING_D09", "FAIL_CLOSED_REFUSAL", _DEBT,
     "The quarterly candidate has no approved reserve (DSRA/DSRF) policy; a reserve is refused rather than treated as zero.",
     "Remove the reserve configuration or use the released 6/6 frequency."),
    ("QUARTERLY_FINANCING_STRUCTURE_MISMATCH", "FAIL_CLOSED_REFUSAL", _DEBT,
     "The saved 3/3 selection recorded a shareholder-loan / DSRA structure that this Working Copy no longer carries. "
     "A shareholder loan or DSRA is never removed silently, so no Run is produced.",
     "Review financing independently of frequency selection, or use the released 6/6 frequency."),
    ("QUARTERLY_SHL_UNSUPPORTED", "FAIL_CLOSED_REFUSAL", _DEBT,
     "The quarterly candidate requires existing equity-only sponsor funding with zero shareholder loans; financing is never discarded.",
     "Remove the shareholder-loan configuration or use the released 6/6 frequency."),
    ("QUARTERLY_INTRAPERIOD_PPA_EXPIRY_UNSUPPORTED", "FAIL_CLOSED_REFUSAL", _SETUP,
     "The PPA ends inside a quarter. The quarterly candidate never splits a quarter between PPA and merchant sales.",
     "Choose a COD on a quarter end, or use the released 6/6 frequency."),
    ("QUARTERLY_COD_ROLL_WINDOW_PENDING_D01", "FAIL_CLOSED_REFUSAL", _SETUP,
     "COD falls in the window where the released six-month model moves the operating start; the quarterly stub rule is not yet decided.",
     "Move COD at least seven days away from 30 June / 31 December, or use the released 6/6 frequency."),
    ("QUARTERLY_", "FAIL_CLOSED_REFUSAL", _SETUP,
     "These inputs are outside the scope of the quarterly (3/3) candidate, which refuses them rather than approximating.",
     "Use the released 6/6 frequency, or bring the inputs inside the documented 3/3 scope."),
    ("PR8_PROJECT_TYPE_NOT_CLASSIFIED", "INPUT_NOT_RUNNABLE", _SETUP,
     "The saved inputs could not be assembled into a runnable model.",
     "Review project setup (horizon, construction timing) and the senior debt tenor, then Run again."),
)


def _evidence(exc: BaseException) -> str:
    return " ".join(str(part) for part in (getattr(exc, "reason_code", ""), getattr(exc, "detail", ""), exc) if part)


def _prior_run(ws: Any) -> str:
    if ws is None or not getattr(ws, "last_runtime_snapshot_id", None):
        return "No committed Run exists for this Working Copy yet."
    state = "STALE (inputs changed since it was computed)" if getattr(ws, "dirty", True) else "CURRENT"
    at = str(getattr(ws, "last_runtime_at", "") or "")[:16].replace("T", " ")
    return f"Your last committed Run{(' from ' + at + ' UTC') if at else ''} is unchanged and remains {state}. This failed attempt created no Run History entry."


def _number(pis: Any, field_id: str) -> Optional[float]:
    try:
        return float(pis.get(field_id))
    except (TypeError, ValueError, AttributeError):
        return None


def explain_run_failure(exc: Optional[BaseException], *, message: str, ws: Any = None, pis: Any = None,
                        kind: Optional[str] = None) -> dict:
    """Return the explanation dict rendered under the failure banner. ``kind`` forces EXECUTION_ERROR for executor timeouts/failures."""
    evidence = _evidence(exc) if exc is not None else ""
    out = {
        "classification": "UNCLASSIFIED_ENGINE_FAILURE", "kind": "UNCLASSIFIED", "kind_label": KIND_LABELS["UNCLASSIFIED"], "message": message,
        "explanation": "The model stopped before producing a result.", "section": _RECENT[0], "tab": _RECENT[1],
        "recovery": "Review the inputs you changed most recently and Run again. If the same failure repeats, share the classification code with support.",
        "prior_run": _prior_run(ws), "no_run_recorded": True,
    }
    if kind == "EXECUTION_ERROR":
        out.update(classification="MODEL_EXECUTION_FAILED", kind="EXECUTION_ERROR", kind_label=KIND_LABELS["EXECUTION_ERROR"],
                   explanation="The calculation did not complete, so no result exists to judge your inputs by.",
                   recovery="Retry the Run. If it fails again, contact support with this classification.", section="", tab="")
        return out
    for token, rule_kind, (section, tab), explanation, recovery in _RULES:
        if token in evidence:
            out.update(classification="QUARTERLY_SCOPE_REFUSAL" if token == "QUARTERLY_" else token, kind=rule_kind,
                       kind_label=KIND_LABELS[rule_kind], explanation=explanation, section=section, tab=tab, recovery=recovery)
            break
    else:
        if "FAIL_CLOSED" in evidence:
            out.update(classification="ENGINE_FAIL_CLOSED", kind="FAIL_CLOSED_REFUSAL", kind_label=KIND_LABELS["FAIL_CLOSED_REFUSAL"],
                       explanation="The model's integrity checks refused to produce a result for the current inputs.")
    _refine(out, pis, evidence=evidence)
    return out


def _refine(out: dict, pis: Any, *, evidence: str = "") -> None:
    """Add input-specific facts read from the saved inputs or typed evidence (no calculation)."""
    if out["classification"] == "SHL_MATURITY_RESIDUAL_FAILS_CLOSED":
        import re as _re
        m_bal = _re.search(r"closing balance\s+([0-9]+(?:\.[0-9]+)?)\s*kEUR", evidence)
        m_per = _re.search(r"period_index=(\d+)", evidence)
        if m_bal or m_per:
            bal_txt = f" Unpaid closing balance: {m_bal.group(1)} kEUR" if m_bal else ""
            per_txt = f" at maturity period {m_per.group(1)}" if m_per else ""
            out["explanation"] += f"{bal_txt}{per_txt}."
    elif out["classification"] == "R04_PHYSICAL_SHORTFALL_NO_SETTLEMENT_CONTRACT":
        import re as _re
        m = _re.search(
            r"in period\s+(\d{4}-\d{2}-\d{2}\.\.\d{4}-\d{2}-\d{2}):\s*contracted\s+([0-9.]+)\s*MWh\s+exceeds\s+available generation\s+([0-9.]+)\s*MWh\s*\(shortfall\s+([0-9.]+)\s*MWh\)",
            evidence,
        )
        if m:
            out["explanation"] += (
                f" Period {m.group(1)}: contracted {m.group(2)} MWh vs available {m.group(3)} MWh "
                f"(shortfall {m.group(4)} MWh)."
            )
    elif pis is not None and out["classification"] == "SHL_MATURITY_NOT_ON_PERIOD_GRID_FAILS_CLOSED":
        from app.v2.horizon_readiness import shl_horizon_notice
        notice = shl_horizon_notice(pis)
        if notice and notice.get("min_horizon_years"):
            out["explanation"] += (f" With a {notice['horizon_years']}-year horizon the model ends at period {notice['last_period']}; the shareholder loan "
                                   f"matures in period {notice['maturity_period']}. A horizon of at least {notice['min_horizon_years']} years covers it.")
    elif pis is not None and out["classification"] == "PR8_PROJECT_TYPE_NOT_CLASSIFIED":
        horizon, tenor = _number(pis, "project_setup.technical.horizon_years"), _number(pis, "debt.senior.tenor_years")
        if horizon is not None and tenor is not None and horizon <= tenor:
            out["explanation"] = (f"The project horizon ({horizon:g} years) is not longer than the senior debt tenor ({tenor:g} years), "
                                  "so the shareholder-loan repayment window is empty and the inputs cannot form a runnable model.")
            out["recovery"] = "Lengthen the project horizon or shorten the senior debt tenor, then Run again."
