"""FINCO Verified Assets V1 — static asset registry.

V1 ships with two reference assets:
  - generic_solar_reference  → solar PPA reference model
  - generic_wind_reference   → wind PPA reference model

Both are MODEL_ONLY: run certificates are available via the canonical
reference engine, but neither has an approved, source-proven model-to-market
economic identity binding.

This registry is the single source of truth for which assets appear
on the /verified surface. Extending V1 to VERIFIED status requires
a canonical model↔market bridge (R10+) — not fabricated here.

FINCO_P5_NO_FABRICATED_MARKET_IDENTITY
FINCO_P5_V1_ASSET_SET_STABLE
"""
from __future__ import annotations

from typing import Optional

from app.verified.contracts import VerifiedAssetDefinition


# Ordered registry — display order matches definition order.
_REGISTRY: list[VerifiedAssetDefinition] = [
    VerifiedAssetDefinition(
        asset_id="generic_solar_reference",
        display_name="Generic Solar Reference",
        asset_type="Solar PPA",
        template_source="generic_solar_reference",
        description=(
            "Utility-scale solar PPA reference project. "
            "Canonical run certificate available via FINCO Compute."
        ),
    ),
    VerifiedAssetDefinition(
        asset_id="generic_wind_reference",
        display_name="Generic Wind Reference",
        asset_type="Wind PPA",
        template_source="generic_wind_reference",
        description=(
            "Onshore wind PPA reference project. "
            "Canonical run certificate available via FINCO Compute."
        ),
    ),
]

# Fast lookup by asset_id.
_BY_ID: dict[str, VerifiedAssetDefinition] = {a.asset_id: a for a in _REGISTRY}


def list_asset_definitions() -> list[VerifiedAssetDefinition]:
    """Return all V1 asset definitions in display order."""
    return list(_REGISTRY)


def get_asset_definition(asset_id: str) -> Optional[VerifiedAssetDefinition]:
    """Return the definition for asset_id, or None if unknown."""
    return _BY_ID.get(asset_id)
