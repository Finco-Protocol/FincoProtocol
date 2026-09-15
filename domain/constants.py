"""Projektne konstante za OpusCore financijski model.

Služi kao single source of truth za sve magic numbers u projektu.
"""
from decimal import Decimal

# === Tehničke konstante (fizikalni defaulti) ===
DEFAULT_PV_DEGRADATION: float = 0.004        # 0.4% godišnje
DEFAULT_BESS_DEGRADATION: float = 0.003      # 0.3% godišnje
DEFAULT_PLANT_AVAILABILITY: float = 0.99     # 99%
DEFAULT_GRID_AVAILABILITY: float = 0.99      # 99%

# === Financijske konstante (generic) ===
DEFAULT_PPA_INDEX: float = 0.02              # 2% godišnje
DEFAULT_MARKET_INFLATION: float = 0.02       # 2% godišnje
# NOTE: Tax rates are jurisdiction-specific — set to 0.0 to force explicit input
DEFAULT_CORPORATE_TAX: float = 0.0

# === OPEX po MW ===
SOLAR_OPEX_PER_MW: float = 15_000           # EUR/kW
WIND_OPEX_PER_MW: float = 35_000             # EUR/kW

# === BESS konstante ===
DEFAULT_BESS_ROUNDTRIP_EFF: float = 0.85
DEFAULT_BESS_CYCLE_LIFE: int = 5000
DEFAULT_BESS_DEGRADATION_RATE: float = 0.02

# === DSCR/LLCR parametri ===
DEFAULT_TARGET_DSCR: float = 1.15
DEFAULT_LOCKUP_DSCR: float = 1.10
DEFAULT_MIN_LLCR: float = 1.15

# === UI slider granice ===
MIN_CAPACITY_MW: float = 1.0
MAX_CAPACITY_MW: float = 500.0
MIN_TARIFF_EUR: float = 10.0
MAX_TARIFF_EUR: float = 200.0
MIN_GEARING: float = 0.0
MAX_GEARING: float = 0.95
MIN_HORIZON_YEARS: int = 10
MAX_HORIZON_YEARS: int = 40