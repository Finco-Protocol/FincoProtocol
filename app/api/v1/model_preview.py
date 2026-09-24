"""A4 Model Reference Preview API — stateless capacity-scaling preview.

No DB calls. No engine execution. No project/workspace creation or mutation.
Only capacity_mw changes; all other reference assumptions are preserved.
"""
from __future__ import annotations

import math
from typing import Any

from app.api.v1.model_reference import (
    _TECHNOLOGY,
    _enum_val,
    _financing_section,
    _identity_section,
    _revenue_section,
    _tax_section,
    get_pi,
    is_supported_key,
)
from app.services.reference_seed_service import build_reference_scaling_preview

MAX_CAPACITY_MW: float = 10_000.0


def validate_capacity_mw(v: Any) -> tuple[float | None, str | None]:
    """Return (float, None) on success, (None, detail) on failure."""
    if v is None:
        return None, "capacity_mw is required."
    if isinstance(v, bool):
        return None, "capacity_mw must be a finite number greater than zero."
    if not isinstance(v, (int, float)):
        return None, "capacity_mw must be a finite number greater than zero."
    try:
        f = float(v)
    except (TypeError, ValueError):
        return None, "capacity_mw must be a finite number greater than zero."
    if not math.isfinite(f):
        return None, "capacity_mw must be a finite number greater than zero."
    if f <= 0:
        return None, "capacity_mw must be a finite number greater than zero."
    if f > MAX_CAPACITY_MW:
        return None, f"capacity_mw must be at most {MAX_CAPACITY_MW:g} MW."
    return f, None


def _technical_preview_section(pi: Any, capacity_mw: float) -> dict[str, Any]:
    p99 = getattr(pi.technical, "operating_hours_p99_1y", None)
    return {
        "capacity_mw": capacity_mw,
        "horizon_years": int(pi.info.horizon_years),
        "construction_months": int(pi.info.construction_months),
        "period_frequency": _enum_val(pi.info.period_frequency),
        "operating_hours_p50": float(pi.technical.operating_hours_p50),
        "operating_hours_p90_10y": (
            float(pi.technical.operating_hours_p90_10y)
            if pi.technical.operating_hours_p90_10y is not None else None
        ),
        "operating_hours_p99_1y": float(p99) if p99 is not None else None,
        "pv_degradation": float(pi.technical.pv_degradation),
        "bess_enabled": bool(pi.technical.bess_enabled),
    }


def build_preview_response_data(key: str, capacity_mw: float) -> dict[str, Any]:
    """Build A4 preview data. Pure: no DB, no engine, no mutation."""
    pi = get_pi(key)
    preview = build_reference_scaling_preview(key, capacity_mw)
    return {
        "identity": _identity_section(key, pi),
        "scaling": {
            "reference_capacity_mw": preview["reference_capacity_mw"],
            "requested_capacity_mw": preview["requested_capacity_mw"],
            "scale_ratio": preview["ratio"],
            "project_created": False,
            "engine_executed": False,
        },
        "technical": _technical_preview_section(pi, capacity_mw),
        "capex": {
            "reference_total_capex_keur": preview["reference_total_capex_keur"],
            "scaled_total_capex_keur": preview["scaled_total_capex_keur"],
            "reference_seedable_capex_keur": preview["reference_seedable_capex_keur"],
            "scaled_seedable_capex_keur": preview["scaled_seedable_capex_keur"],
            "items": preview["capex_items"],
        },
        "opex": {
            "reference_opex_y1_keur": preview["reference_opex_y1_keur"],
            "scaled_opex_y1_keur": preview["scaled_opex_y1_keur"],
            "reference_seedable_opex_y1_keur": preview["reference_seedable_opex_y1_keur"],
            "scaled_seedable_opex_y1_keur": preview["scaled_seedable_opex_y1_keur"],
            "items": preview["opex_items"],
        },
        "preserved_assumptions": {
            "revenue": _revenue_section(pi),
            "financing": _financing_section(pi),
            "tax": _tax_section(pi),
        },
        "reference_semantics": {
            "synthetic_reference": True,
            "market_benchmark": False,
            "scaling_authority": "REFERENCE_SEED",
            "preview_only": True,
        },
    }
