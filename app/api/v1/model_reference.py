"""A3 Model Reference API — pure read-only serialization adapter.

No DB calls. No engine execution. No modification of economic authority.

Identity / name / code / capacity: derived from factory (pi.info.*, pi.technical.*).
Technology: explicit key→technology mapping (no typed field on ProjectInputs).
"""
from __future__ import annotations

from typing import Any

from app.services.reference_seed_service import (
    canonical_capex_reference_items,
    canonical_opex_reference_items,
    get_reference_inputs,
)

VALID_REFERENCE_KEYS: frozenset[str] = frozenset({
    "generic_solar_reference",
    "generic_wind_reference",
})

_TECHNOLOGY: dict[str, str] = {
    "generic_solar_reference": "solar",
    "generic_wind_reference": "wind",
}


def _enum_val(v: Any) -> Any:
    """Return enum .value if present, else v unchanged."""
    return v.value if hasattr(v, "value") else v


def is_supported_key(key: str) -> bool:
    return isinstance(key, str) and key in VALID_REFERENCE_KEYS


def get_pi(key: str):
    """Return canonical reference ProjectInputs. Read-only; no DB."""
    return get_reference_inputs(key)


# ── List ──────────────────────────────────────────────────────────────────────

def build_list_entry(key: str, pi: Any) -> dict[str, Any]:
    return {
        "reference_key": key,
        "technology": _TECHNOLOGY[key],
        "name": pi.info.name,
        "reference_code": pi.info.code,
        "reference_capacity_mw": float(pi.technical.capacity_mw),
        "synthetic_reference": True,
        "market_benchmark": False,
    }


def build_references_list_data() -> dict[str, Any]:
    entries = []
    for key in sorted(VALID_REFERENCE_KEYS):
        pi = get_pi(key)
        entries.append(build_list_entry(key, pi))
    return {
        "count": len(entries),
        "references": entries,
        "synthetic_reference": True,
        "market_benchmark": False,
    }


# ── Detail (grouped sections) ─────────────────────────────────────────────────

def _identity_section(key: str, pi: Any) -> dict[str, Any]:
    return {
        "reference_key": key,
        "technology": _TECHNOLOGY[key],
        "name": pi.info.name,
        "reference_code": pi.info.code,
        "country_iso": pi.info.country_iso,
        "synthetic_reference": True,
        "market_benchmark": False,
    }


def _technical_section(pi: Any) -> dict[str, Any]:
    p99 = getattr(pi.technical, "operating_hours_p99_1y", None)
    return {
        "capacity_mw": float(pi.technical.capacity_mw),
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


def _revenue_section(pi: Any) -> dict[str, Any]:
    co2_price = getattr(pi.revenue, "co2_certificate_price_eur_per_mwh", None)
    if co2_price is None:
        co2_price = getattr(pi.revenue, "co2_price_eur", None)
    return {
        "ppa_base_tariff_eur_mwh": float(pi.revenue.ppa_base_tariff),
        "ppa_term_years": int(pi.revenue.ppa_term_years),
        "ppa_index_rate": float(pi.revenue.ppa_index),
        "market_scenario": str(pi.revenue.market_scenario),
        "market_prices_curve_eur_mwh": [float(v) for v in pi.revenue.market_prices_curve],
        "market_inflation_rate": float(pi.revenue.market_inflation),
        "balancing_cost_wind_eur_mwh": float(
            getattr(pi.revenue, "balancing_cost_wind_eur_mwh", 0.0) or 0.0
        ),
        "co2_enabled": bool(pi.revenue.co2_enabled),
        "co2_certificate_price_eur_mwh": float(co2_price) if co2_price is not None else 0.0,
    }


def _financing_section(pi: Any) -> dict[str, Any]:
    f = pi.financing
    return {
        "gearing_ratio": float(f.gearing_ratio),
        "senior_tenor_years": int(f.senior_tenor_years),
        "base_rate": float(f.base_rate),
        "margin_bps": int(f.margin_bps),
        "floating_share": float(f.floating_share),
        "fixed_share": float(f.fixed_share),
        "hedge_coverage": float(f.hedge_coverage),
        "target_dscr": float(f.target_dscr),
        "lockup_dscr": float(f.lockup_dscr),
        "min_llcr": float(f.min_llcr),
        "dsra_months": int(f.dsra_months),
        "debt_sizing_method": _enum_val(f.debt_sizing_method),
        "debt_sizing_mode": _enum_val(f.debt_sizing_mode),
        "sponsor_funding_mode": _enum_val(f.sponsor_funding_mode),
        "gearing_basis_mode": _enum_val(f.gearing_basis_mode),
        "clean_shl_repayment_method": _enum_val(f.clean_shl_repayment_method),
        "shl_day_count_convention": _enum_val(f.shl_day_count_convention),
    }


def _tax_section(pi: Any) -> dict[str, Any]:
    t = pi.tax
    return {
        "corporate_rate": float(t.corporate_rate),
        "loss_carryforward_years": int(t.loss_carryforward_years),
        "loss_carryforward_cap": float(t.loss_carryforward_cap),
        "atad_ebitda_limit": float(t.atad_ebitda_limit),
        "atad_min_interest_keur": float(t.atad_min_interest_keur),
        "clean_cash_tax_timing_enabled": bool(
            getattr(t, "clean_cash_tax_timing_enabled", False)
        ),
    }


def _capex_summary_section(pi: Any, items: dict) -> dict[str, Any]:
    seedable_total = sum(v["reference_amount_keur"] for v in items.values())
    return {
        "total_capex_keur": float(pi.capex.total_capex),
        "seedable_capex_total_keur": seedable_total,
        "capacity_mw": float(pi.technical.capacity_mw),
    }


def _opex_summary_section(pi: Any, items: dict) -> dict[str, Any]:
    canonical_total = sum(float(item.y1_amount_keur) for item in pi.opex)
    seedable_total = sum(v["reference_amount_keur"] for v in items.values())
    return {
        "opex_y1_keur": canonical_total,
        "seedable_opex_y1_keur": seedable_total,
        "capacity_mw": float(pi.technical.capacity_mw),
    }


def build_reference_detail_data(key: str, pi: Any) -> dict[str, Any]:
    capex_items = canonical_capex_reference_items(pi)
    opex_items = canonical_opex_reference_items(pi)
    return {
        "identity": _identity_section(key, pi),
        "technical": _technical_section(pi),
        "revenue": _revenue_section(pi),
        "financing": _financing_section(pi),
        "tax": _tax_section(pi),
        "capex_summary": _capex_summary_section(pi, capex_items),
        "opex_summary": _opex_summary_section(pi, opex_items),
        "reference_semantics": {
            "synthetic_reference": True,
            "market_benchmark": False,
        },
    }


# ── CAPEX ─────────────────────────────────────────────────────────────────────

def build_reference_capex_data(key: str, pi: Any) -> dict[str, Any]:
    items_dict = canonical_capex_reference_items(pi)
    items = list(items_dict.values())
    seedable_total = sum(it["reference_amount_keur"] for it in items)
    return {
        "key": key,
        "capacity_mw": float(pi.technical.capacity_mw),
        "total_capex_keur": float(pi.capex.total_capex),
        "seedable_capex_total_keur": seedable_total,
        "items": items,
        "synthetic_reference": True,
        "market_benchmark": False,
    }


# ── OPEX ──────────────────────────────────────────────────────────────────────

def build_reference_opex_data(key: str, pi: Any) -> dict[str, Any]:
    items_dict = canonical_opex_reference_items(pi)
    items = list(items_dict.values())
    canonical_total = sum(float(item.y1_amount_keur) for item in pi.opex)
    seedable_total = sum(it["reference_amount_keur"] for it in items)
    return {
        "key": key,
        "capacity_mw": float(pi.technical.capacity_mw),
        "opex_y1_keur": canonical_total,
        "seedable_opex_y1_keur": seedable_total,
        "items": items,
        "synthetic_reference": True,
        "market_benchmark": False,
    }
