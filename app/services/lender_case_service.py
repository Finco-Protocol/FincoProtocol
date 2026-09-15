"""V4-4: Lender Case & Covenant Analytics service.

Pure computation — no persistence side effects, no engine changes.
Reuses canonical WaterfallResult period data for covenant analytics.
Reuses _apply_shock from sensitivity_service for lender case adjustments.
"""
from __future__ import annotations

from dataclasses import replace
from typing import Any, Optional

from app.services.reporting_kpi_sources import build_canonical_report_kpis


# ─── Lender adjustment registry ──────────────────────────────────────────────

LENDER_ADJUSTMENTS: dict[str, tuple[str, str, float]] = {
    # key: (label, unit, default_value)
    "yield_p90": ("Yield (P90 10yr)", "hours", 0.0),         # absolute hours override
    "yield_haircut": ("Yield Haircut", "%", 0.0),             # % reduction on P50
    "ppa_haircut": ("PPA Price Haircut", "%", 0.0),
    "merchant_haircut": ("Merchant Price Haircut", "%", 0.0),
    "capex_contingency": ("CAPEX Contingency", "%", 0.0),
    "opex_contingency": ("OPEX Contingency", "%", 0.0),
    "interest_stress": ("Interest Rate Stress", "bps", 0.0),
    "inflation_stress": ("Inflation Stress", "%", 0.0),
    "availability_stress": ("Availability Stress", "%", 0.0),
}

# Covenant thresholds (standard project-finance defaults)
DSCR_LOCKUP = 1.10
DSCR_DISTRIBUTION = 1.15
DSCR_EVENT_OF_DEFAULT = 1.05
DSCR_CASH_SWEEP = 1.20


def apply_lender_adjustments(proj: Any, adjustments: dict[str, float]) -> Any:
    """Apply lender case adjustments to ProjectInputs.

    adjustments: dict mapping LENDER_ADJUSTMENTS keys to values.
    Returns a new ProjectInputs with adjustments applied (frozen, no side effects).
    """
    from app.services.sensitivity_service import _apply_shock

    result = proj

    # P90 yield override (absolute hours)
    if adjustments.get("yield_p90", 0.0) > 0:
        p90 = adjustments["yield_p90"]
        result = replace(
            result,
            technical=replace(result.technical, operating_hours_p50=p90),
        )

    # Yield haircut (applied on top of P90 or P50)
    if adjustments.get("yield_haircut", 0.0) != 0.0:
        result = _apply_shock(result, "yield", -abs(adjustments["yield_haircut"]))

    # PPA price haircut
    if adjustments.get("ppa_haircut", 0.0) != 0.0:
        result = _apply_shock(result, "ppa_price", -abs(adjustments["ppa_haircut"]))

    # Merchant price haircut
    if adjustments.get("merchant_haircut", 0.0) != 0.0:
        result = _apply_shock(result, "merchant_price", -abs(adjustments["merchant_haircut"]))

    # CAPEX contingency (upward only)
    if adjustments.get("capex_contingency", 0.0) != 0.0:
        result = _apply_shock(result, "capex", abs(adjustments["capex_contingency"]))

    # OPEX contingency (upward only)
    if adjustments.get("opex_contingency", 0.0) != 0.0:
        result = _apply_shock(result, "opex", abs(adjustments["opex_contingency"]))

    # Interest rate stress (basis points)
    if adjustments.get("interest_stress", 0.0) != 0.0:
        result = _apply_shock(result, "interest_rate", adjustments["interest_stress"])

    # Inflation stress on opex inflation rates
    if adjustments.get("inflation_stress", 0.0) != 0.0:
        stress = adjustments["inflation_stress"] / 100.0
        new_opex = tuple(
            replace(o, annual_inflation=min(1.0, max(0.0, o.annual_inflation + stress)))
            for o in result.opex
        )
        result = replace(result, opex=new_opex)

    # Availability stress (downward only)
    if adjustments.get("availability_stress", 0.0) != 0.0:
        result = _apply_shock(result, "availability", -abs(adjustments["availability_stress"]))

    return result


def run_lender_case(
    proj: Any,
    adjustments: dict[str, float],
) -> dict[str, Any]:
    """Run engine under lender adjustments and return KPIs + period data.

    Returns a dict with:
      - kpis: top-level KPIs
      - periods: list of per-period covenant analytics dicts
      - adjustment_summary: human-readable list of applied adjustments
    """
    from app.services.production_waterfall_seam import execute_production_waterfall

    shocked_proj = apply_lender_adjustments(proj, adjustments)
    # PR-8 correction pass: lender-case shocks execute through the ONE
    # shared production authority seam — clean G2C for clean-ready projects,
    # explicitly classified legacy for blocked projects. No legacy Base run
    # alongside clean data.
    execution = execute_production_waterfall(shocked_proj)
    result = execution.result

    kpis = build_canonical_report_kpis(result)

    periods = build_covenant_periods(result)

    adjustment_summary = _build_adjustment_summary(adjustments)

    return {
        "kpis": kpis,
        "periods": periods,
        "adjustment_summary": adjustment_summary,
        "project_inputs": shocked_proj,
    }


def build_covenant_periods(result: Any) -> list[dict[str, Any]]:
    """Extract per-period covenant analytics from WaterfallResult."""
    rows = []
    for p in result.periods:
        if not p.is_operation:
            continue
        dscr = getattr(p, "dscr", None)
        llcr = getattr(p, "llcr", None)
        plcr = getattr(p, "plcr", None)
        lockup = getattr(p, "lockup_active", False)
        dist = getattr(p, "distribution_keur", 0.0)
        sweep = getattr(p, "cash_sweep_keur", 0.0)

        # Traffic light
        if dscr is None:
            rag = "na"
        elif dscr < DSCR_EVENT_OF_DEFAULT:
            rag = "breach"
        elif dscr < DSCR_LOCKUP:
            rag = "warning"
        elif dscr < DSCR_DISTRIBUTION:
            rag = "caution"
        else:
            rag = "ok"

        rows.append({
            "period": p.period,
            "year_index": getattr(p, "year_index", None),
            "date": str(p.date) if p.date else "",
            "dscr": dscr,
            "llcr": llcr,
            "plcr": plcr,
            "lockup": lockup,
            "distribution_keur": dist,
            "cash_sweep_keur": sweep,
            "senior_balance_keur": getattr(p, "senior_balance_keur", 0.0),
            "ebitda_keur": getattr(p, "ebitda_keur", 0.0),
            "senior_ds_keur": getattr(p, "senior_ds_keur", 0.0),
            "rag": rag,
        })
    return rows


def build_credit_summary(
    proj: Any,
    kpis: dict[str, Any],
    lender_kpis: Optional[dict[str, Any]] = None,
) -> dict[str, Any]:
    """Assemble one-page credit summary from project inputs and KPIs."""
    from finco_core.inputs._models import CapexItem
    from dataclasses import fields

    fin = proj.financing
    tech = proj.technical
    info = proj.info
    rev = proj.revenue
    tax = proj.tax

    # Total equity = CAPEX - senior debt
    senior_debt = kpis.get("total_senior_ds_keur")  # proxy; actual sizing from run
    # Use gearing to estimate
    gearing = getattr(fin, "gearing_ratio", None) or 0.0
    total_capex = proj.capex.total_capex
    debt_keur = total_capex * gearing
    equity_keur = total_capex * (1.0 - gearing)

    # Payback: first period where cum_distributions >= equity_invest (approximate)
    payback_years = None

    return {
        "project_name": info.name,
        "company": info.company,
        "country": info.country_iso,
        "technology": "Wind" if "wind" in info.name.lower() else "Solar",
        "capacity_mw": tech.capacity_mw,
        "cod_date": str(info.cod_date),
        "horizon_years": info.horizon_years,
        "ppa_tariff": rev.ppa_base_tariff,
        "ppa_term_years": rev.ppa_term_years,
        "total_capex_keur": total_capex,
        "debt_keur": debt_keur,
        "equity_keur": equity_keur,
        "gearing_pct": gearing * 100.0,
        "corporate_tax_rate_pct": tax.corporate_rate * 100.0,
        "senior_tenor_years": getattr(fin, "senior_tenor_years", None),
        # KPIs from base run
        "project_irr": kpis.get("project_irr"),
        "equity_irr": kpis.get("equity_irr"),
        "equity_npv": kpis.get("equity_npv"),
        "avg_dscr": kpis.get("actual_avg_dscr"),
        "min_dscr": kpis.get("min_dscr"),
        "min_llcr": kpis.get("min_llcr"),
        "total_distribution_keur": kpis.get("total_distribution_keur"),
        "total_tax_keur": kpis.get("total_tax_keur"),
        # Lender case KPIs (if provided)
        "lender_project_irr": lender_kpis.get("project_irr") if lender_kpis else None,
        "lender_equity_irr": lender_kpis.get("equity_irr") if lender_kpis else None,
        "lender_avg_dscr": lender_kpis.get("actual_avg_dscr") if lender_kpis else None,
        "lender_min_dscr": lender_kpis.get("min_dscr") if lender_kpis else None,
        "lender_min_llcr": lender_kpis.get("min_llcr") if lender_kpis else None,
    }


def _build_adjustment_summary(adjustments: dict[str, float]) -> list[dict[str, Any]]:
    rows = []
    for key, value in adjustments.items():
        if value == 0.0:
            continue
        meta = LENDER_ADJUSTMENTS.get(key, (key, "", 0.0))
        label, unit = meta[0], meta[1]
        if unit == "%":
            display = f"{value:+.1f}%"
        elif unit == "bps":
            display = f"{value:+.0f} bps"
        elif unit == "hours":
            display = f"{value:.0f} hrs"
        else:
            display = str(value)
        rows.append({"key": key, "label": label, "value": value, "display": display})
    return rows
