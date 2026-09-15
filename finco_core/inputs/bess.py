"""BESS input parameters — extracted to finco_core (V2-6).

Contains only the BessParams dataclass: pure data, no financial logic.
The revenue-calculation helpers (bess_discharged_mwh, bess_arbitrage_revenue_keur,
etc.) remain in domain.revenue.bess and are NOT extracted here — they depend
on Revenue engine logic that is out of V2-6 scope.

domain.revenue.bess is structurally compatible with this class (same fields,
same types, same defaults) so duck-typing callers continue to work unchanged.
"""
from dataclasses import dataclass


@dataclass(frozen=True)
class BessParams:
    power_mw: float
    energy_mwh: float
    cycles_per_year: float
    round_trip_efficiency: float = 0.88
    availability: float = 0.98
    annual_degradation: float = 0.02
    arbitrage_spread_eur_mwh: float = 40.0
    ancillary_revenue_eur_mw_year: float = 25000.0
    capacity_revenue_eur_mw_year: float = 0.0
    augmentation_capex_keur: float = 0.0
    # V4-7 extended fields
    frequency_regulation_eur_mw_year: float = 0.0
    reserve_market_eur_mw_year: float = 0.0
    fixed_contracted_eur_mw_year: float = 0.0
    depth_of_discharge: float = 0.85
    cycle_life: int = 4000
    replacement_year: int = 0
