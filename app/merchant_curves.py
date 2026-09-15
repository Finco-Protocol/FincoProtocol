"""Synthetic merchant price-curve profiles for FINCO Model demos.

The corporate repository intentionally contains no third-party or client-derived
market curves.  Profiles below are illustrative deterministic assumptions only.
"""
from typing import NamedTuple


class MerchantProfile(NamedTuple):
    name: str
    description: str
    curve: tuple[float, ...]
    market_inflation: float = 0.0
    is_nominal: bool = True


GENERIC_MARKET_A_SOLAR_CENTRAL = MerchantProfile(
    name="GENERIC_MARKET_A_SOLAR_CENTRAL",
    description="Synthetic Generic Market A solar central case",
    curve=tuple(round(62.0 * (1.018 ** i), 4) for i in range(30)),
    market_inflation=0.0,
    is_nominal=True,
)

GENERIC_SOLAR_ESCALATION_2PCT = MerchantProfile(
    name="GENERIC_SOLAR_ESCALATION_2PCT",
    description="Synthetic solar 2% annual escalation from 65 EUR/MWh",
    curve=tuple(round(65.0 * (1.02 ** i), 4) for i in range(30)),
    market_inflation=0.0,
    is_nominal=True,
)

GENERIC_WIND_ESCALATION_2PCT = MerchantProfile(
    name="GENERIC_WIND_ESCALATION_2PCT",
    description="Synthetic wind 2% annual escalation from 55 EUR/MWh",
    curve=tuple(round(55.0 * (1.02 ** i), 4) for i in range(30)),
    market_inflation=0.0,
    is_nominal=True,
)

PROFILE_REGISTRY: dict[str, MerchantProfile] = {
    p.name: p for p in (
        GENERIC_MARKET_A_SOLAR_CENTRAL,
        GENERIC_SOLAR_ESCALATION_2PCT,
        GENERIC_WIND_ESCALATION_2PCT,
    )
}


def get_profile(name: str) -> MerchantProfile:
    """Return a synthetic profile by name."""
    return PROFILE_REGISTRY[name]
