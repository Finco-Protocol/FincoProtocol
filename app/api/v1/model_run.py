"""A5 Model Reference Run API — stateless production engine execution.

No DB calls. No project creation. No scenario creation. No workspace mutation.
No persistence. Exactly one canonical production financial calculation per call.

reference + capacity_mw → scaled ProjectInputs → clean G2C engine → summary KPIs
"""
from __future__ import annotations

import dataclasses
from typing import Any

from app.api.v1.model_reference import (
    _financing_section,
    _identity_section,
    _revenue_section,
    _tax_section,
    get_pi,
)
from app.services.production_financial_authority import run_clean_production
from app.services.reference_seed_service import build_reference_scaling_preview

_CAPEX_ITEM_FIELDS = (
    "epc_contract", "production_units", "epc_other", "grid_connection",
    "ops_prep", "insurances", "lease_tax", "construction_mgmt_a",
    "commissioning", "audit_legal", "construction_mgmt_b", "contingencies",
    "taxes", "project_acquisition", "project_rights",
)


def _build_scaled_project_inputs(pi: Any, ratio: float, capacity_mw: float) -> Any:
    """Return a copy of canonical ProjectInputs proportionally scaled to capacity_mw.

    CAPEX and OPEX amounts multiply by ratio = capacity_mw / reference_capacity_mw.
    Revenue, financing, and tax assumptions are preserved exactly.
    Pure in-memory transformation; no DB calls, no financial recalculation.
    """
    scaled_capex = dataclasses.replace(
        pi.capex,
        **{
            f: dataclasses.replace(
                getattr(pi.capex, f),
                amount_keur=getattr(pi.capex, f).amount_keur * ratio,
            )
            for f in _CAPEX_ITEM_FIELDS
        },
        idc_keur=pi.capex.idc_keur * ratio,
        commitment_fees_keur=pi.capex.commitment_fees_keur * ratio,
        bank_fees_keur=pi.capex.bank_fees_keur * ratio,
        other_financial_keur=pi.capex.other_financial_keur * ratio,
        vat_costs_keur=pi.capex.vat_costs_keur * ratio,
        vat_facility_idc_keur=pi.capex.vat_facility_idc_keur * ratio,
        vat_facility_commitment_fee_keur=pi.capex.vat_facility_commitment_fee_keur * ratio,
        reserve_accounts_keur=pi.capex.reserve_accounts_keur * ratio,
    )
    scaled_opex = tuple(
        dataclasses.replace(item, y1_amount_keur=item.y1_amount_keur * ratio)
        for item in pi.opex
    )
    scaled_technical = dataclasses.replace(pi.technical, capacity_mw=capacity_mw)
    return dataclasses.replace(
        pi,
        technical=scaled_technical,
        capex=scaled_capex,
        opex=scaled_opex,
    )


def _safe_float(v: Any) -> float | None:
    if v is None:
        return None
    try:
        return float(v)
    except (TypeError, ValueError):
        return None


def _safe_int(v: Any) -> int | None:
    if v is None:
        return None
    try:
        return int(v)
    except (TypeError, ValueError):
        return None


def _kpi_section(view: Any, scaled_capex_total: float) -> dict[str, Any]:
    """Extract summary KPI fields from CleanWaterfallView. No financial computation."""
    return {
        "project_irr": _safe_float(getattr(view, "project_irr", None)),
        "equity_irr": _safe_float(getattr(view, "equity_irr", None)),
        "sponsor_irr": _safe_float(getattr(view, "sponsor_irr", None)),
        "project_npv_keur": _safe_float(getattr(view, "project_npv", None)),
        "equity_npv_keur": _safe_float(getattr(view, "equity_npv", None)),
        "min_dscr": _safe_float(getattr(view, "actual_min_dscr", None)),
        "avg_dscr": _safe_float(getattr(view, "actual_avg_dscr", None)),
        "target_dscr": _safe_float(getattr(view, "target_dscr", None)),
        "min_llcr": _safe_float(getattr(view, "min_llcr", None)),
        "total_revenue_keur": _safe_float(getattr(view, "total_revenue_keur", None)),
        "total_ebitda_keur": _safe_float(getattr(view, "total_ebitda_keur", None)),
        "total_opex_keur": _safe_float(getattr(view, "total_opex_keur", None)),
        "total_tax_keur": _safe_float(getattr(view, "total_tax_keur", None)),
        "total_capex_keur": scaled_capex_total,
        "total_distributions_keur": _safe_float(getattr(view, "total_distribution_keur", None)),
        "total_senior_ds_keur": _safe_float(getattr(view, "total_senior_ds_keur", None)),
        "total_shl_service_keur": _safe_float(getattr(view, "total_shl_service_keur", None)),
        "periods_in_lockup": _safe_int(getattr(view, "periods_in_lockup", None)),
    }


def build_run_response_data(key: str, capacity_mw: float) -> dict[str, Any]:
    """Build A5 run response data.

    Stateless: no DB calls, no project creation, no persistence, no mutation.
    One canonical production financial calculation; summary KPIs only.
    """
    pi = get_pi(key)
    preview = build_reference_scaling_preview(key, capacity_mw)
    ratio = preview["ratio"]
    scaled_pi = _build_scaled_project_inputs(pi, ratio, capacity_mw)

    clean_run = run_clean_production(scaled_pi, "Base")

    from app.services.clean_presentation_adapter import build_clean_waterfall_view
    view = build_clean_waterfall_view(clean_run)

    scaled_capex_total = float(scaled_pi.capex.total_capex)

    return {
        "identity": _identity_section(key, pi),
        "scaling": {
            "reference_capacity_mw": preview["reference_capacity_mw"],
            "requested_capacity_mw": preview["requested_capacity_mw"],
            "scale_ratio": ratio,
            "project_created": False,
            "engine_executed": True,
            "db_writes": False,
        },
        "capex": {
            "reference_total_capex_keur": preview["reference_total_capex_keur"],
            "scaled_total_capex_keur": scaled_capex_total,
            "items": preview["capex_items"],
        },
        "opex": {
            "reference_opex_y1_keur": preview["reference_opex_y1_keur"],
            "scaled_opex_y1_keur": preview["scaled_opex_y1_keur"],
            "items": preview["opex_items"],
        },
        "results": _kpi_section(view, scaled_capex_total),
        "preserved_assumptions": {
            "revenue": _revenue_section(pi),
            "financing": _financing_section(pi),
            "tax": _tax_section(pi),
        },
        "authority": {
            "runtime_authority": clean_run.authority_metadata.get(
                "runtime_authority", "clean_g2c"
            ),
            "calculation_count": clean_run.authority_metadata.get("calculation_count", 1),
            "scenario": clean_run.scenario,
            "synthetic_reference": True,
            "market_benchmark": False,
            "engine_executed": True,
            "project_created": False,
            "db_writes": False,
        },
    }
