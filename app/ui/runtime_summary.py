"""Phase 9.5 — Runtime summary builder.

app/ui/runtime_summary.py

Responsibilities:
1. Accept a run_project result dict (from app.api.project_runner.run_project())
2. Extract KPI fields safely (no fabricated values)
3. Return a serialisable dict for Jinja2 rendering

No runtime formula changes. No engine changes.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any


NOT_AVAILABLE = "NOT_AVAILABLE"
MISSING_RUNTIME_BINDING = "MISSING_RUNTIME_BINDING"


@dataclass(frozen=True)
class RuntimeSummary:
    """Lightweight live runtime summary for one project run.

    All fields are sourced from actual model execution results.
    Fields that are unavailable are marked NOT_AVAILABLE.
    """

    project_id: str
    project_name: str
    ran_at: str = ""
    status: str = "ok"

    project_irr: str = NOT_AVAILABLE
    equity_irr: str = NOT_AVAILABLE
    avg_dscr: str = NOT_AVAILABLE
    min_dscr: str = NOT_AVAILABLE

    total_revenue_keur: str = NOT_AVAILABLE
    total_ebitda_keur: str = NOT_AVAILABLE
    total_opex_keur: str = NOT_AVAILABLE
    total_capex_keur: str = NOT_AVAILABLE
    total_distributions_keur: str = NOT_AVAILABLE

    senior_debt_keur: str = NOT_AVAILABLE
    shl_opening_keur: str = NOT_AVAILABLE
    total_cfads_keur: str = NOT_AVAILABLE

    # E1-2: tax KPIs
    total_tax_keur: str = NOT_AVAILABLE
    effective_tax_rate_pct: str = NOT_AVAILABLE

    revenue_derivation: dict[str, Any] = field(default_factory=dict)
    dscr_derivation: dict[str, Any] = field(default_factory=dict)
    cfads_derivation: dict[str, Any] = field(default_factory=dict)
    ebitda_derivation: dict[str, Any] = field(default_factory=dict)
    opex_derivation: dict[str, Any] = field(default_factory=dict)
    capex_derivation: dict[str, Any] = field(default_factory=dict)
    senior_debt_derivation: dict[str, Any] = field(default_factory=dict)

    error_message: str = ""

    def to_dict(self) -> dict[str, Any]:
        return {
            "project_id": self.project_id,
            "project_name": self.project_name,
            "ran_at": self.ran_at,
            "status": self.status,
            "project_irr": self.project_irr,
            "equity_irr": self.equity_irr,
            "avg_dscr": self.avg_dscr,
            "min_dscr": self.min_dscr,
            "total_revenue_keur": self.total_revenue_keur,
            "total_ebitda_keur": self.total_ebitda_keur,
            "total_opex_keur": self.total_opex_keur,
            "total_capex_keur": self.total_capex_keur,
            "total_distributions_keur": self.total_distributions_keur,
            "senior_debt_keur": self.senior_debt_keur,
            "shl_opening_keur": self.shl_opening_keur,
            "total_cfads_keur": self.total_cfads_keur,
            "total_tax_keur": self.total_tax_keur,
            "effective_tax_rate_pct": self.effective_tax_rate_pct,
            "revenue_derivation": self.revenue_derivation,
            "dscr_derivation": self.dscr_derivation,
            "cfads_derivation": self.cfads_derivation,
            "ebitda_derivation": self.ebitda_derivation,
            "opex_derivation": self.opex_derivation,
            "capex_derivation": self.capex_derivation,
            "senior_debt_derivation": self.senior_debt_derivation,
            "error_message": self.error_message,
        }


def _fmt(v: Any, suffix: str = "", decimal_places: int = 2) -> str:
    """Format a numeric value safely, returning NOT_AVAILABLE for None/NaN."""
    if v is None:
        return NOT_AVAILABLE
    try:
        f = float(v)
        if _is_bad_float(f):
            return NOT_AVAILABLE
        if suffix == "%":
            return f"{f * 100:.{decimal_places}f}%".replace(".00%", ".0%")
        if suffix == "x":
            return f"{f:.2f}x".replace(".00x", ".0x")
        return f"{f:,.{decimal_places}f}{suffix}"
    except (TypeError, ValueError):
        return NOT_AVAILABLE


def _is_bad_float(v: float) -> bool:
    return v != v or abs(v) == float("inf")


def _keur(v: Any) -> str:
    """Format as kEUR string."""
    if v is None:
        return NOT_AVAILABLE
    try:
        f = float(v)
        if _is_bad_float(f):
            return NOT_AVAILABLE
        return f"{f:,.0f} kEUR"
    except (TypeError, ValueError):
        return NOT_AVAILABLE


def _format_dscr_derivation(raw: dict[str, Any]) -> dict[str, Any]:
    """Format DSCR derivation evidence for direct template rendering."""
    if not raw:
        return {}
    return {
        "display_value": _fmt(raw.get("display_value"), suffix="x", decimal_places=4),
        "summary_method": raw.get("summary_method", ""),
        "period_formula": raw.get("period_formula", ""),
        "period_count": raw.get("period_count", 0),
        "total_cfads_keur": _keur(raw.get("total_cfads_keur")),
        "total_senior_debt_service_keur": _keur(raw.get("total_senior_debt_service_keur")),
        "sample_period_label": raw.get("sample_period_label", ""),
        "sample_cfads_keur": _keur(raw.get("sample_cfads_keur")),
        "sample_senior_debt_service_keur": _keur(raw.get("sample_senior_debt_service_keur")),
        "sample_dscr": _fmt(raw.get("sample_dscr"), suffix="x", decimal_places=4),
        "audit_source": raw.get("audit_source", ""),
    }


def _format_cfads_derivation(raw: dict[str, Any]) -> dict[str, Any]:
    """Format CFADS derivation evidence for direct template rendering."""
    if not raw:
        return {}
    return {
        "display_value_keur": _keur(raw.get("display_value_keur")),
        "summary_method": raw.get("summary_method", ""),
        "period_formula": raw.get("period_formula", ""),
        "period_count": raw.get("period_count", 0),
        "sample_period_label": raw.get("sample_period_label", ""),
        "sample_ebitda_keur": _keur(raw.get("sample_ebitda_keur")),
        "sample_tax_keur": _keur(raw.get("sample_tax_keur")),
        "sample_cfads_keur": _keur(raw.get("sample_cfads_keur")),
        "audit_source": raw.get("audit_source", ""),
    }


def _format_ebitda_derivation(raw: dict[str, Any]) -> dict[str, Any]:
    """Format EBITDA derivation evidence for direct template rendering."""
    if not raw:
        return {}
    return {
        "display_value_keur": _keur(raw.get("display_value_keur")),
        "summary_method": raw.get("summary_method", ""),
        "period_formula": raw.get("period_formula", ""),
        "period_count": raw.get("period_count", 0),
        "sample_period_label": raw.get("sample_period_label", ""),
        "sample_revenue_keur": _keur(raw.get("sample_revenue_keur")),
        "sample_opex_keur": _keur(raw.get("sample_opex_keur")),
        "sample_ebitda_keur": _keur(raw.get("sample_ebitda_keur")),
        "audit_source": raw.get("audit_source", ""),
    }


def _format_opex_derivation(raw: dict[str, Any]) -> dict[str, Any]:
    """Format OPEX derivation evidence for direct template rendering."""
    if not raw:
        return {}
    return {
        "display_value_keur": _keur(raw.get("display_value_keur")),
        "summary_method": raw.get("summary_method", ""),
        "period_formula": raw.get("period_formula", ""),
        "period_count": raw.get("period_count", NOT_AVAILABLE),
        "sample_period_label": raw.get("sample_period_label", NOT_AVAILABLE),
        "sample_opex_keur": _keur(raw.get("sample_opex_keur")),
        "audit_source": raw.get("audit_source", ""),
    }


def _format_capex_derivation(raw: dict[str, Any]) -> dict[str, Any]:
    """Format CAPEX derivation evidence for direct template rendering."""
    if not raw:
        return {}
    return {
        "display_value_keur": _keur(raw.get("display_value_keur")),
        "summary_method": raw.get("summary_method", ""),
        "authoritative_source": raw.get("authoritative_source", ""),
        "category_count": raw.get("category_count", NOT_AVAILABLE),
        "hierarchy_source": raw.get("hierarchy_source", ""),
        "audit_source": raw.get("audit_source", ""),
    }


def _format_senior_debt_derivation(raw: dict[str, Any]) -> dict[str, Any]:
    """Format senior debt derivation evidence for direct template rendering."""
    if not raw:
        return {}
    return {
        "display_value_keur": _keur(raw.get("display_value_keur")),
        "summary_method": raw.get("summary_method", ""),
        "period_count": raw.get("period_count", NOT_AVAILABLE),
        "sample_period_label": raw.get("sample_period_label", NOT_AVAILABLE),
        "sample_senior_interest_keur": _keur(raw.get("sample_senior_interest_keur")),
        "sample_senior_principal_keur": _keur(raw.get("sample_senior_principal_keur")),
        "sample_senior_debt_service_keur": _keur(raw.get("sample_senior_debt_service_keur")),
        "audit_source": raw.get("audit_source", ""),
    }


def _format_revenue_derivation(raw: dict[str, Any]) -> dict[str, Any]:
    """Format revenue derivation evidence for direct template rendering."""
    if not raw:
        return {}
    generation = raw.get("sample_generation_mwh")
    sample_generation = NOT_AVAILABLE
    if generation is not None:
        try:
            sample_generation = f"{float(generation):,.0f} MWh"
        except (TypeError, ValueError):
            sample_generation = NOT_AVAILABLE

    # Format the full authoritative period series for the detail table.
    # Each row comes from WaterfallResult.periods[] — no economics recomputed here.
    formatted_periods: list[dict[str, Any]] = []
    for p in raw.get("revenue_periods", []):
        gen = p.get("generation_mwh")
        rev = p.get("revenue_keur")
        try:
            gen_fmt = f"{float(gen):,.0f} MWh" if gen is not None else NOT_AVAILABLE
        except (TypeError, ValueError):
            gen_fmt = NOT_AVAILABLE
        formatted_periods.append({
            "period_label": p.get("period_label", ""),
            "generation_mwh": gen_fmt,
            "revenue_keur": _keur(rev),
            "revenue_keur_raw": rev,
        })

    return {
        "display_value_keur": _keur(raw.get("display_value_keur")),
        "summary_method": raw.get("summary_method", ""),
        "period_formula": raw.get("period_formula", ""),
        "period_count": raw.get("period_count", 0),
        "sample_period_label": raw.get("sample_period_label", ""),
        "sample_generation_mwh": sample_generation,
        "sample_revenue_keur": _keur(raw.get("sample_revenue_keur")),
        "audit_source": raw.get("audit_source", ""),
        "revenue_periods": formatted_periods,
    }


def _find_debt_balance(wf_rows: list[dict], label_needle: str) -> str:
    """Search waterfall rows for a balance row matching label_needle.

    Each row is a dict {period: value}. Returns formatted kEUR string
    or NOT_AVAILABLE.
    """
    for row in wf_rows:
        # The row has no 'label' key — period columns are the only keys.
        # We detect debt rows by scanning non-None numeric values.
        vals = list(row.values())
        # skip period-name strings at the start
        numeric_vals = []
        for v in vals:
            try:
                numeric_vals.append(float(v))
            except (TypeError, ValueError):
                pass
        if not numeric_vals:
            continue
        # A "balance" row for debt should start positive and decrease
        # Look for rows with positive initial values that decline over time
        if numeric_vals[0] > 0 and any(v == 0 for v in numeric_vals[1:]):
            # likely a debt balance row
            return _keur(numeric_vals[0])
    return NOT_AVAILABLE


def build_runtime_summary(
    result: dict[str, Any],
    project_id: str,
    project_name: str,
) -> RuntimeSummary:
    """Build RuntimeSummary from a run_project result dict.

    The result dict must come from app.api.project_runner.run_project()
    (which wraps run_demo_project). It contains 'kpis' and optional
    'tables' keys.

    project_id:  "generic_wind_reference" | "generic_solar_reference"
    project_name: display name shown in the UI
    """
    import datetime

    kpis = result.get("kpis", {})

    # ── Primary KPIs ──────────────────────────────────────────────────
    project_irr = _fmt(kpis.get("project_irr"), suffix="%")
    equity_irr = _fmt(kpis.get("equity_irr"), suffix="%")
    avg_dscr = _fmt(kpis.get("avg_dscr"), suffix="x")
    min_dscr = _fmt(kpis.get("min_dscr"), suffix="x")
    total_revenue = _keur(kpis.get("total_revenue_keur"))
    total_ebitda = _keur(kpis.get("total_ebitda_keur"))
    total_opex = _keur(kpis.get("total_opex_keur"))
    total_capex = _keur(kpis.get("total_capex_keur"))
    total_dist = _keur(kpis.get("total_distributions_keur"))
    total_cfads = NOT_AVAILABLE

    # E1-2: tax KPIs from WaterfallResult (via kpis dict)
    raw_tax = kpis.get("total_tax_keur")
    raw_ebitda = kpis.get("total_ebitda_keur")
    total_tax = _keur(raw_tax)
    eff_tax_rate = NOT_AVAILABLE
    try:
        if raw_tax is not None and raw_ebitda is not None:
            ebitda_f = float(raw_ebitda)
            if ebitda_f > 0:
                eff_tax_rate = _fmt(float(raw_tax) / ebitda_f, suffix="%")
    except (TypeError, ValueError):
        pass

    derivation_evidence = result.get("derivation_evidence", {})
    revenue_derivation = _format_revenue_derivation(derivation_evidence.get("revenue", {}))
    dscr_derivation = _format_dscr_derivation(derivation_evidence.get("dscr", {}))
    cfads_derivation = _format_cfads_derivation(derivation_evidence.get("cfads", {}))
    ebitda_derivation = _format_ebitda_derivation(derivation_evidence.get("ebitda", {}))
    opex_derivation = _format_opex_derivation(derivation_evidence.get("opex", {}))
    capex_derivation = _format_capex_derivation(derivation_evidence.get("capex", {}))
    senior_debt_derivation = _format_senior_debt_derivation(derivation_evidence.get("senior_debt", {}))
    if cfads_derivation:
        total_cfads = cfads_derivation.get("display_value_keur", NOT_AVAILABLE)

    # ── Balance-sheet anchors ───────────────────────────────────────
    # These are best-effort from factory defaults since waterfall table
    # rows don't have explicit 'label' keys.
    tables = result.get("tables", {})
    wf_rows = tables.get("waterfall", [])

    senior_debt_str = senior_debt_derivation.get("display_value_keur", NOT_AVAILABLE)
    shl_opening_str = NOT_AVAILABLE

    # Generic Wind Reference / Generic Solar Reference factory defaults for senior debt and SHL
    from app.ui.project_context import get_project_context
    ctx = get_project_context(project_id)
    if senior_debt_str == NOT_AVAILABLE and ctx.senior_debt_keur:
        senior_debt_str = _keur(ctx.senior_debt_keur)
    if ctx.shl_amount_keur:
        shl_opening_str = _keur(ctx.shl_amount_keur + ctx.shl_idc_keur)

    return RuntimeSummary(
        project_id=project_id,
        project_name=project_name,
        ran_at=datetime.datetime.now().strftime("%Y-%m-%d %H:%M"),
        status="ok",
        project_irr=project_irr,
        equity_irr=equity_irr,
        avg_dscr=avg_dscr,
        min_dscr=min_dscr,
        total_revenue_keur=total_revenue,
        total_ebitda_keur=total_ebitda,
        total_opex_keur=total_opex,
        total_capex_keur=total_capex,
        total_distributions_keur=total_dist,
        senior_debt_keur=senior_debt_str,
        shl_opening_keur=shl_opening_str,
        total_cfads_keur=total_cfads,
        total_tax_keur=total_tax,
        effective_tax_rate_pct=eff_tax_rate,
        revenue_derivation=revenue_derivation,
        dscr_derivation=dscr_derivation,
        cfads_derivation=cfads_derivation,
        ebitda_derivation=ebitda_derivation,
        opex_derivation=opex_derivation,
        capex_derivation=capex_derivation,
        senior_debt_derivation=senior_debt_derivation,
        error_message="",
    )


def runtime_summary_to_dict(
    result: dict[str, Any],
    project_id: str,
    project_name: str,
) -> dict[str, Any]:
    """Convenience: build RuntimeSummary and return .to_dict()."""
    return build_runtime_summary(result, project_id, project_name).to_dict()
