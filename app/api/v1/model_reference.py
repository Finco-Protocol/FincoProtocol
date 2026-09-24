"""A3 Model Reference API — pure read-only serialization adapter.

No DB calls. No engine execution. No modification of economic authority.
"""
from __future__ import annotations

import re
from typing import Any, Optional

from app.services.reference_seed_service import (
    canonical_capex_reference_items,
    canonical_opex_reference_items,
    get_reference_inputs,
)

VALID_REFERENCE_KEYS: frozenset[str] = frozenset({
    "generic_solar_reference",
    "generic_wind_reference",
})

_DISPLAY_NAMES: dict[str, str] = {
    "generic_solar_reference": "Generic Solar Reference",
    "generic_wind_reference": "Generic Wind Reference",
}

_TECHNOLOGY: dict[str, str] = {
    "generic_solar_reference": "solar",
    "generic_wind_reference": "wind",
}

_KEY_RE = re.compile(r'^[a-z][a-z0-9_]{0,63}$')


def validate_reference_key(key: str) -> Optional[str]:
    """Return key if format is valid, else None."""
    if not isinstance(key, str) or not _KEY_RE.match(key):
        return None
    return key


def get_pi(key: str):
    """Return canonical reference ProjectInputs. Read-only; no DB."""
    return get_reference_inputs(key)


def build_references_list_data() -> dict[str, Any]:
    refs = [
        {
            "key": k,
            "display_name": _DISPLAY_NAMES[k],
            "technology": _TECHNOLOGY[k],
        }
        for k in sorted(VALID_REFERENCE_KEYS)
    ]
    return {"count": len(refs), "references": refs}


def build_reference_template_data(key: str, pi: Any) -> dict[str, Any]:
    return {
        "key": key,
        "display_name": _DISPLAY_NAMES[key],
        "technology": _TECHNOLOGY[key],
        "code": pi.info.code,
        "country_iso": pi.info.country_iso,
        "capacity_mw": float(pi.technical.capacity_mw),
        "horizon_years": int(pi.info.horizon_years),
        "construction_months": int(pi.info.construction_months),
        "operating_hours_p50": float(pi.technical.operating_hours_p50),
        "operating_hours_p90_10y": (
            float(pi.technical.operating_hours_p90_10y)
            if pi.technical.operating_hours_p90_10y is not None else None
        ),
        "ppa_base_tariff": float(pi.revenue.ppa_base_tariff),
        "ppa_term_years": int(pi.revenue.ppa_term_years),
        "gearing_ratio": float(pi.financing.gearing_ratio),
        "senior_tenor_years": int(pi.financing.senior_tenor_years),
        "target_dscr": float(pi.financing.target_dscr),
        "lockup_dscr": float(pi.financing.lockup_dscr),
        "corporate_tax_rate": float(pi.tax.corporate_rate),
    }


def build_reference_capex_data(key: str, pi: Any) -> dict[str, Any]:
    items_dict = canonical_capex_reference_items(pi)
    items = list(items_dict.values())
    total = sum(item["reference_amount_keur"] for item in items)
    return {
        "key": key,
        "capacity_mw": float(pi.technical.capacity_mw),
        "total_capex_keur": total,
        "items": items,
    }


def build_reference_opex_data(key: str, pi: Any) -> dict[str, Any]:
    items_dict = canonical_opex_reference_items(pi)
    items = list(items_dict.values())
    total_y1 = sum(item["reference_amount_keur"] for item in items)
    return {
        "key": key,
        "capacity_mw": float(pi.technical.capacity_mw),
        "total_opex_y1_keur": total_y1,
        "items": items,
    }
