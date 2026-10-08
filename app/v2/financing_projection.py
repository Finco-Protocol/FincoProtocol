"""Read-only bankability presentation. Never reconstruct financing economics."""
from __future__ import annotations

import math
from collections.abc import Mapping
from dataclasses import dataclass
from typing import Any

from app.workbook.runtime_projection import thaw_runtime_payload


UNAVAILABLE = "Not available"


def number(value: Any) -> float | None:
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        return None
    return float(value) if math.isfinite(value) else None


def label(value: Any) -> str:
    raw = getattr(value, "value", value)
    names = {
        "SHARE_CAPITAL_THEN_SHL": "Share capital, then shareholder loan",
        "EQUITY_ONLY": "Equity only (no shareholder loan)",
        "BULLET": "Bullet at maturity",
        "CASH_SWEEP": "Cash sweep",
        "PARTIAL_PAY_SWEEP": "Cash sweep",
        "ACT_365_FIXED": "Actual / 365 fixed",
        "ACT_365": "Actual / 365",
        "ACT_360": "Actual / 360",
        "THIRTY_360": "30 / 360",
        "PERIOD_AXIS_ACTUAL_YEAR": "Actual period days / calendar-year days",
        "NONE": "No reserve support",
        "CASH_DSRA": "Cash-funded debt service reserve",
        "DSRF": "Debt service reserve facility",
        "FORWARD_DEBT_SERVICE_MONTHS": "Forward debt service coverage",
        "PEAK_FORWARD_DEBT_SERVICE_MONTHS": "Peak forward debt service coverage",
        "FIXED_AMOUNT": "Fixed reserve requirement",
    }
    return names.get(str(raw).upper(), str(raw).replace("_", " ").lower().capitalize()) if raw is not None else UNAVAILABLE


@dataclass(frozen=True)
class FinanceMetric:
    label: str
    value: float | None
    display: str
    source: str
    reason: str = ""


def metric(title: str, value: Any, unit: str, source: str, reason: str = "") -> FinanceMetric:
    raw = number(value)
    if raw is None:
        return FinanceMetric(title, None, UNAVAILABLE, source, reason or "Not exposed in the persisted Last Run.")
    display = f"{raw * 100:.2f}%" if unit == "%" else f"{raw:,.2f}{'x' if unit == 'x' else ' ' + unit}"
    return FinanceMetric(title, raw, display, source)


def senior_editor_fields(fields: list[dict], pi: Any) -> list[dict]:
    """Project the typed flat rate into registry percent units, without a magnitude guess."""
    from app.input_adapter import senior_rate_authority, senior_dscr_authority

    rows = [dict(f) for f in fields]
    if pi is None:
        return rows
    rate_mode, rate, _ = senior_rate_authority(pi)
    dscr_mode, dscr, _ = senior_dscr_authority(pi)
    for row in rows:
        if row["field_id"] == "debt.senior.gearing_pct":
            row["label"] = "Requested gearing cap"
        if row["field_id"] == "debt.senior.interest_rate_pct":
            if rate_mode == "FLAT" and number(rate) is not None:
                row["value"] = f"{rate * 100:.2f}"
                row["display_value"] = f"{rate * 100:.2f}%"
            elif rate_mode == "CALIBRATED":
                row["display_value"] = "Period-specific calibrated rates"
            row["help_text"] = "Enter a percentage: 5.50 means 5.50% all-in. Saved through the existing typed rate authority."
        elif row["field_id"] == "debt.senior.target_dscr":
            if dscr_mode != "CALIBRATED" and number(dscr) is not None:
                row["value"] = dscr
                row["display_value"] = f"{dscr:.2f}x"
            elif dscr_mode == "CALIBRATED":
                row["display_value"] = "Period-specific calibrated DSCR targets"
    return rows


def build_financing_evidence(rr: Any) -> dict:
    runtime = thaw_runtime_payload(getattr(rr, "runtime_summary", None) or {})
    debt = thaw_runtime_payload(getattr(rr, "debt_schedule", None) or {})
    summary = debt.get("summary") or {}
    statements = thaw_runtime_payload(getattr(rr, "financial_statements", None) or {})
    cash = (statements.get("pf_cash_waterfall") or {}).get("periods") or []
    # Preserve the source period/date and sign. No invented annual aggregation,
    # alignment to a second schedule, or substitution of Bank CFADS.
    cash_rows = tuple({
        "period": p.get("period_index", p.get("period")), "date": p.get("date"),
        "cfads": metric("CFADS to Senior", p.get("fcf_banks_keur"), "kEUR", "RuntimeResult.financial_statements.pf_cash_waterfall.periods.fcf_banks_keur"),
        "service": metric("Senior debt service cash", p.get("senior_total_ds_keur"), "kEUR", "RuntimeResult.financial_statements.pf_cash_waterfall.periods.senior_total_ds_keur"),
        "funding": metric("DSRA funding cash", p.get("dsra_funding_keur"), "kEUR", "RuntimeResult.financial_statements.pf_cash_waterfall.periods.dsra_funding_keur"),
        "release": metric("DSRA release cash", p.get("dsra_release_keur"), "kEUR", "RuntimeResult.financial_statements.pf_cash_waterfall.periods.dsra_release_keur"),
    } for p in cash if isinstance(p, Mapping) and (
        "fcf_banks_keur" in p or "senior_total_ds_keur" in p))
    return {
        "metrics": (
            metric("Actual sized Senior debt", runtime.get("senior_debt_keur"), "kEUR", "RuntimeResult.runtime_summary.senior_debt_keur"),
            metric("Actual gearing (Last Run)", runtime.get("actual_gearing_pct"), "%", "RuntimeResult.runtime_summary.actual_gearing_pct", "Last Run gearing on Total Project Uses is not persisted; current Working CAPEX is not substituted."),
            metric("Gearing cap (Last Run)", runtime.get("gearing_cap_pct"), "%", "RuntimeResult.runtime_summary.gearing_cap_pct"),
            metric("Target DSCR (Last Run)", summary.get("target_dscr"), "x", "RuntimeResult.debt_schedule.summary.target_dscr"),
            metric("Minimum DSCR", summary.get("actual_min_dscr"), "x", "RuntimeResult.debt_schedule.summary.actual_min_dscr"),
            metric("Average DSCR", summary.get("actual_avg_dscr"), "x", "RuntimeResult.debt_schedule.summary.actual_avg_dscr"),
            metric("Minimum LLCR", summary.get("min_llcr"), "x", "RuntimeResult.debt_schedule.summary.min_llcr", summary.get("llcr_unavailable_reason") or "No LLCR value or typed unavailability reason is exposed in this persisted debt summary."),
        ),
        "cash_rows": cash_rows,
        "sizing_status": UNAVAILABLE,
        "sizing_reason": "Binding constraints and the sizing/sculpting verdict are not persisted in this presentation contract. Review financial integrity separately.",
    }


def build_sponsor_view(fin: Any, rr: Any) -> dict:
    runtime = thaw_runtime_payload(getattr(rr, "runtime_summary", None) or {})
    sponsor = thaw_runtime_payload(getattr(rr, "sponsor_schedule", None) or {})
    summary = sponsor.get("summary") or {}

    def value(name):
        return getattr(fin, name, None) if fin is not None else None

    def amount(title, name):
        return metric(title, value(name), "kEUR", "Working ProjectInputs.financing." + name)

    return {
        "mode": label(value("sponsor_funding_mode")),
        "equity": (amount("Share capital", "share_capital_keur"), amount("Share premium", "share_premium_keur"), amount("Other equity before SHL", "other_equity_funding_before_shl_keur")),
        "other": (amount("Junior / other project funding", "junior_or_other_project_funding_keur"),),
        "shl": (
            metric("SHL interest rate", value("shl_rate"), "%", "Working ProjectInputs.financing.shl_rate"),
        ),
        "repayment": label(value("clean_shl_repayment_method")),
        "day_count": label(value("shl_day_count_convention")),
        "eligibility": value("shl_principal_eligibility_start_period"),
        "maturity": value("shl_maturity_period_index"),
        "returns": (
            metric("Pure Equity IRR", runtime.get("equity_irr"), "%", "RuntimeResult.runtime_summary.equity_irr"),
            metric("Total Sponsor IRR", summary.get("total_sponsor_xirr"), "%", "RuntimeResult.sponsor_schedule.summary.total_sponsor_xirr"),
            metric("Pure Equity MOIC", summary.get("pure_equity_moic"), "x", "RuntimeResult.sponsor_schedule.summary.pure_equity_moic"),
            metric("Total Sponsor MOIC", summary.get("total_sponsor_moic"), "x", "RuntimeResult.sponsor_schedule.summary.total_sponsor_moic"),
        ),
    }


def build_reserve_view(fin: Any) -> dict:
    return {
        "support": label(getattr(fin, "dsra_support_mode", None)),
        "target": label(getattr(fin, "dsra_target_policy", None) or "FIXED_AMOUNT") if fin else UNAVAILABLE,
        "months": getattr(fin, "dsra_months", None),
        "requirement": metric("Configured reserve requirement", getattr(fin, "debt_service_reserve_requirement_keur", None), "kEUR", "Working ProjectInputs.financing.debt_service_reserve_requirement_keur"),
        "facility": metric("Reserve facility commitment", getattr(fin, "dsrf_commitment_keur", None), "kEUR", "Working ProjectInputs.financing.dsrf_commitment_keur"),
    }


def integrity_view(evidence: Mapping, input_state: str) -> dict:
    """Format the existing institutional integrity report; never invent a verdict."""
    checks = tuple(evidence.get("checks") or ())
    overall = evidence.get("overall")
    status = {"PASS": "PASS", "FAIL": "FAIL", "INCOMPLETE": "WARN"}.get(overall, "UNAVAILABLE")
    if not checks:
        status = "UNAVAILABLE"
    failures = tuple(c for c in checks if c.get("status") == "FAIL")
    missing = tuple(c for c in checks if c.get("status") == "UNAVAILABLE")
    return {"inputs": input_state, "status": status, "counts": evidence.get("counts") or {},
            "checks": checks, "reasons": failures or missing,
            "prior": input_state == "STALE"}
