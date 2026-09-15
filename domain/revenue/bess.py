"""Pure BESS revenue model — no waterfall dependencies."""
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


def bess_discharged_mwh(params: BessParams, year_index: int, day_fraction: float = 1.0) -> float:
    """MWh discharged in a period, accounting for degradation and availability.

    effective_energy = energy_mwh * (1 - degradation)^(year_index - 1)
    discharged_mwh = effective_energy * cycles * availability * RTE * day_fraction
    """
    effective_energy = params.energy_mwh * (1 - params.annual_degradation) ** max(year_index - 1, 0)
    return effective_energy * params.cycles_per_year * params.availability * params.round_trip_efficiency * day_fraction


def bess_arbitrage_revenue_keur(params: BessParams, year_index: int, day_fraction: float = 1.0) -> float:
    """Arbitrage revenue in kEUR for a period.

    arbitrage_revenue = discharged_mwh * spread_eur_mwh / 1000
    """
    discharged = bess_discharged_mwh(params, year_index, day_fraction)
    return discharged * params.arbitrage_spread_eur_mwh / 1000


def bess_capacity_revenue_keur(params: BessParams, day_fraction: float = 1.0) -> float:
    """Capacity (steadfast) revenue in kEUR for a period, scaled by day_fraction."""
    return params.power_mw * params.capacity_revenue_eur_mw_year * day_fraction / 1000


def bess_ancillary_revenue_keur(params: BessParams, day_fraction: float = 1.0) -> float:
    """Ancillary services revenue in kEUR for a period, scaled by day_fraction."""
    return params.power_mw * params.ancillary_revenue_eur_mw_year * day_fraction / 1000


def bess_augmentation_cost_keur(params: BessParams, year_index: int) -> float:
    """Augmentation capex allocation for a year (linear over 10 years if capex > 0)."""
    if params.augmentation_capex_keur <= 0 or year_index > 10:
        return 0.0
    return params.augmentation_capex_keur / 10


def bess_frequency_regulation_revenue_keur(params: BessParams, day_fraction: float = 1.0) -> float:
    """Frequency regulation revenue in kEUR for a period."""
    return params.power_mw * params.frequency_regulation_eur_mw_year * day_fraction / 1000


def bess_reserve_market_revenue_keur(params: BessParams, day_fraction: float = 1.0) -> float:
    """Reserve market revenue in kEUR for a period."""
    return params.power_mw * params.reserve_market_eur_mw_year * day_fraction / 1000


def bess_fixed_contracted_revenue_keur(params: BessParams, day_fraction: float = 1.0) -> float:
    """Fixed contracted revenue in kEUR for a period."""
    return params.power_mw * params.fixed_contracted_eur_mw_year * day_fraction / 1000


def bess_state_of_health(params: BessParams, year_index: int) -> float:
    """State of health (SoH) as a fraction at end of year_index."""
    return max(0.0, (1 - params.annual_degradation) ** max(year_index - 1, 0))


def bess_effective_energy_mwh(params: BessParams, year_index: int) -> float:
    """Effective energy capacity in MWh after degradation."""
    return params.energy_mwh * bess_state_of_health(params, year_index)


@dataclass(frozen=True)
class BessRevenueBreakdown:
    """Period-level BESS revenue breakdown."""
    discharged_mwh: float
    arbitrage_revenue_keur: float
    capacity_revenue_keur: float
    ancillary_revenue_keur: float
    frequency_regulation_keur: float
    reserve_market_keur: float
    fixed_contracted_keur: float
    augmentation_cost_keur: float
    total_revenue_keur: float  # all revenue streams before augmentation
    net_revenue_keur: float   # after augmentation cost deduction
    state_of_health: float


def bess_revenue_breakdown(params: BessParams, year_index: int, day_fraction: float = 1.0) -> BessRevenueBreakdown:
    """Compute full revenue breakdown for one period."""
    discharged = bess_discharged_mwh(params, year_index, day_fraction)
    arbitrage = bess_arbitrage_revenue_keur(params, year_index, day_fraction)
    capacity = bess_capacity_revenue_keur(params, day_fraction)
    ancillary = bess_ancillary_revenue_keur(params, day_fraction)
    freq_reg = bess_frequency_regulation_revenue_keur(params, day_fraction)
    reserve = bess_reserve_market_revenue_keur(params, day_fraction)
    fixed = bess_fixed_contracted_revenue_keur(params, day_fraction)
    augmentation = bess_augmentation_cost_keur(params, year_index)
    soh = bess_state_of_health(params, year_index)
    total = arbitrage + capacity + ancillary + freq_reg + reserve + fixed
    net = total - augmentation
    return BessRevenueBreakdown(
        discharged_mwh=discharged,
        arbitrage_revenue_keur=arbitrage,
        capacity_revenue_keur=capacity,
        ancillary_revenue_keur=ancillary,
        frequency_regulation_keur=freq_reg,
        reserve_market_keur=reserve,
        fixed_contracted_keur=fixed,
        augmentation_cost_keur=augmentation,
        total_revenue_keur=total,
        net_revenue_keur=net,
        state_of_health=soh,
    )


def annual_bess_revenue(params: BessParams, year_index: int) -> float:
    """Total annual net BESS revenue in kEUR (two semesters summed)."""
    # Each year has two semesters, each with day_fraction ≈ 0.5
    h1 = bess_revenue_breakdown(params, year_index, day_fraction=0.5)
    h2 = bess_revenue_breakdown(params, year_index, day_fraction=0.5)
    return h1.net_revenue_keur + h2.net_revenue_keur


__all__ = [
    "BessParams",
    "BessRevenueBreakdown",
    "bess_discharged_mwh",
    "bess_arbitrage_revenue_keur",
    "bess_capacity_revenue_keur",
    "bess_ancillary_revenue_keur",
    "bess_frequency_regulation_revenue_keur",
    "bess_reserve_market_revenue_keur",
    "bess_fixed_contracted_revenue_keur",
    "bess_augmentation_cost_keur",
    "bess_state_of_health",
    "bess_effective_energy_mwh",
    "bess_revenue_breakdown",
    "annual_bess_revenue",
]
