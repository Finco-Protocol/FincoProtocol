"""A5 Model Reference Run API — stateless production engine execution.

No DB calls. No project creation. No scenario creation. No workspace mutation.
No persistence. Exactly one canonical production financial calculation per call.

reference + capacity_mw → canonical PER_MW scaling → run_project → summary KPIs
"""
from __future__ import annotations

import dataclasses
import math
from typing import Any

from app.api.v1.model_reference import (
    _financing_section,
    _identity_section,
    _revenue_section,
    _tax_section,
    get_pi,
)
from app.services.reference_seed_service import (
    _canonical_capex_items,
    _canonical_opex_items,
    build_reference_scaling_preview,
)

_PROJECT_TYPE_BY_KEY: dict[str, str] = {
    "generic_solar_reference": "Generic Solar Reference",
    "generic_wind_reference": "Generic Wind Reference",
    "generic_data_center_reference": "Generic Data Center Reference",
}


def _build_scaled_project_inputs(
    pi: Any, ratio: float, capacity_mw: float, *, key_is_data_center: bool = False
) -> Any:
    """Scale canonical ProjectInputs using the established canonical PER_MW authority.

    Only fields classified PER_MW by _canonical_capex_items / _canonical_opex_items
    are scaled. Zero CAPEX items, non-PER_MW CAPEX float fields, and percentage-based
    OPEX items are left unchanged. Pure in-memory; no DB, no financial recalculation.
    """
    canonical_capex_fields = _canonical_capex_items(pi)
    capex_overrides = {
        f: dataclasses.replace(
            getattr(pi.capex, f),
            amount_keur=getattr(pi.capex, f).amount_keur * ratio,
        )
        for f in canonical_capex_fields
    }
    scaled_capex = dataclasses.replace(pi.capex, **capex_overrides)

    canonical_opex_keys = set(_canonical_opex_items(pi).keys())
    scaled_opex = tuple(
        dataclasses.replace(item, y1_amount_keur=item.y1_amount_keur * ratio)
        if str(item.name) in canonical_opex_keys
        else item
        for item in pi.opex
    )

    scaled_technical = dataclasses.replace(pi.technical, capacity_mw=capacity_mw)
    scaled = dataclasses.replace(
        pi,
        technical=scaled_technical,
        capex=scaled_capex,
        opex=scaled_opex,
    )
    if key_is_data_center:
        # Correction A: generic PER_MW scaling cannot re-derive the Data
        # Center authority (B.08 power expenses are DERIVED, sponsor equity
        # is capacity-proportional, revenue rides the occupancy ramp).
        # Re-apply the single application-layer authority with the canonical
        # default drivers appropriate to this stateless Base run.  The
        # formulas are NOT duplicated here.
        from app.data_center_authority import (
            GENERIC_DATA_CENTER_REFERENCE_DRIVERS,
            apply_data_center_runtime_adapter,
        )
        scaled = apply_data_center_runtime_adapter(
            scaled, GENERIC_DATA_CENTER_REFERENCE_DRIVERS
        )
    return scaled


def _finite_float(v: Any) -> float | None:
    """Return finite float or None. Maps NaN, +Inf, -Inf to None."""
    if v is None:
        return None
    try:
        f = float(v)
    except (TypeError, ValueError):
        return None
    if math.isnan(f) or math.isinf(f):
        return None
    return f


def _safe_int(v: Any) -> int | None:
    if v is None:
        return None
    try:
        return int(v)
    except (TypeError, ValueError):
        return None


def _extract_kpis(kpis: dict[str, Any]) -> dict[str, Any]:
    """Select canonical A5 KPI fields from run_project payload["kpis"]."""
    return {
        "project_irr": _finite_float(kpis.get("project_irr")),
        "equity_irr": _finite_float(kpis.get("equity_irr")),
        "sponsor_irr": _finite_float(kpis.get("sponsor_irr")),
        "project_npv_keur": _finite_float(kpis.get("project_npv_keur")),
        "equity_npv_keur": _finite_float(kpis.get("equity_npv_keur")),
        "min_dscr": _finite_float(kpis.get("min_dscr")),
        "avg_dscr": _finite_float(kpis.get("avg_dscr")),
        "target_dscr": _finite_float(kpis.get("target_dscr")),
        "min_llcr": _finite_float(kpis.get("min_llcr")),
        "total_revenue_keur": _finite_float(kpis.get("total_revenue_keur")),
        "total_ebitda_keur": _finite_float(kpis.get("total_ebitda_keur")),
        "total_opex_keur": _finite_float(kpis.get("total_opex_keur")),
        "total_tax_keur": _finite_float(kpis.get("total_tax_keur")),
        "total_capex_keur": _finite_float(kpis.get("total_capex_keur")),
        "total_distributions_keur": _finite_float(kpis.get("total_distributions_keur")),
        "total_senior_ds_keur": _finite_float(kpis.get("total_senior_ds_keur")),
        "total_shl_service_keur": _finite_float(kpis.get("total_shl_service_keur")),
        "periods_in_lockup": _safe_int(kpis.get("periods_in_lockup")),
    }


def _validate_authority_metadata(authority_metadata: Any) -> dict:
    """Fail closed if required authority metadata is missing or contradictory.

    Invariants: must be a dict, runtime_authority=='clean_g2c', calculation_count==1.
    Raises RuntimeError on any violation — programming error, not a domain error.
    """
    if not isinstance(authority_metadata, dict):
        raise RuntimeError(
            f"A5_AUTHORITY_INVARIANT: authority_metadata must be a dict, "
            f"got {type(authority_metadata).__name__}"
        )
    runtime_authority = authority_metadata.get("runtime_authority")
    calculation_count = authority_metadata.get("calculation_count")
    if runtime_authority != "clean_g2c":
        raise RuntimeError(
            f"A5_AUTHORITY_INVARIANT: expected runtime_authority='clean_g2c', "
            f"got {runtime_authority!r}"
        )
    if calculation_count != 1:
        raise RuntimeError(
            f"A5_AUTHORITY_INVARIANT: expected calculation_count=1, "
            f"got {calculation_count!r}"
        )
    return authority_metadata


def build_run_response_data(key: str, capacity_mw: float) -> dict[str, Any]:
    """Build A5 run response data.

    Stateless: no DB calls, no project creation, no persistence, no mutation.
    Exactly one canonical production financial calculation via run_project.
    Summary KPIs are sourced directly from payload["kpis"]; no recomputation.
    """
    from app.api.project_runner import run_project

    pi = get_pi(key)
    project_type = _PROJECT_TYPE_BY_KEY[key]
    preview = build_reference_scaling_preview(key, capacity_mw)
    ratio = preview["ratio"]
    scaled_pi = _build_scaled_project_inputs(
        pi, ratio, capacity_mw,
        key_is_data_center=(key == "generic_data_center_reference"),
    )

    payload = run_project(
        project_type=project_type,
        scenario="Base",
        project_inputs_override=scaled_pi,
        use_dualrun_validation=False,
    )

    authority_metadata = _validate_authority_metadata(payload.get("runtime_authority"))
    kpis = payload["kpis"]

    return {
        "identity": _identity_section(key, pi),
        "scaling": {
            "reference_capacity_mw": preview["reference_capacity_mw"],
            "requested_capacity_mw": preview["requested_capacity_mw"],
            "scale_ratio": ratio,
            "stateless": True,
            "project_created": False,
            "engine_executed": True,
            "db_writes": False,
        },
        "capex": {
            "reference_total_capex_keur": preview["reference_total_capex_keur"],
            "scaled_total_capex_keur": preview["scaled_total_capex_keur"],
            "items": preview["capex_items"],
        },
        "opex": {
            "reference_opex_y1_keur": preview["reference_opex_y1_keur"],
            "scaled_opex_y1_keur": preview["scaled_opex_y1_keur"],
            "items": preview["opex_items"],
        },
        "results": _extract_kpis(kpis),
        "preserved_assumptions": {
            "revenue": _revenue_section(pi),
            "financing": _financing_section(pi),
            "tax": _tax_section(pi),
        },
        "authority": {
            "runtime_authority": authority_metadata["runtime_authority"],
            "calculation_count": authority_metadata["calculation_count"],
            "scenario": authority_metadata["scenario"],
            "stateless": True,
            "synthetic_reference": True,
            "market_benchmark": False,
            "engine_executed": True,
            "project_created": False,
            "scenario_created": False,
            "workspace_mutated": False,
            "persisted": False,
        },
    }
