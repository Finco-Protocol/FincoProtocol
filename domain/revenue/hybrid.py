"""Pure hybrid (solar+BESS or wind+BESS) period-level revenue model.

This is a period-level approximation, NOT hourly dispatch.
Curtailment is modeled as a simple grid-connection clipping factor.

Grid clipping logic:
  If renewable_capacity_mw <= grid_connection_mw:
      clipped_mwh = 0 (no curtailment)
  Else:
      clipped_mwh = total_generation_mwh * (renewable_capacity_mw - grid_connection_mw) / renewable_capacity_mw

BESS curtailment capture:
  BESS charges from clipped energy (curtailment), then discharges at discharge_price.
"""
from dataclasses import dataclass
from typing import Optional

from domain.revenue.bess import BessParams


@dataclass(frozen=True)
class HybridInputs:
    """Hybrid project: renewable generation + colocated BESS."""
    # --- Renewable ---
    solar_capacity_mw: float = 0.0
    wind_capacity_mw: float = 0.0
    operating_hours_p50: float = 0.0
    pv_degradation: float = 0.004
    wind_degradation: float = 0.005
    plant_availability: float = 0.99
    grid_availability: float = 0.99
    # Grid connection limit
    grid_connection_mw: float = 0.0

    # --- Revenue ---
    tariff_eur_mwh: float = 0.0
    tariff_escalation: float = 0.02

    # --- BESS ---
    bess: Optional[BessParams] = None
    charge_from_curtailment_share: float = 1.0  # 0..1
    grid_charge_allowed: bool = True
    grid_charge_mwh: float = 0.0               # grid charge limit for arbitrage
    grid_arbitrage_spread_eur_mwh: float = 0.0  # buy/sell spread for grid arbitrage
    discharge_price_eur_mwh: float = 0.0  # if 0, uses tariff

    @property
    def total_capacity_mw(self) -> float:
        return self.solar_capacity_mw + self.wind_capacity_mw

    @property
    def effective_discharge_price(self) -> float:
        return self.discharge_price_eur_mwh if self.discharge_price_eur_mwh > 0 else self.tariff_eur_mwh


@dataclass(frozen=True)
class HybridRevenueBreakdown:
    """Explicit hybrid revenue breakdown with curtailment capture."""
    # Renewable generation
    solar_generation_mwh: float
    wind_generation_mwh: float
    total_generation_mwh: float
    # Clipping / curtailment
    exported_mwh: float          # generation exported (total - curtailment)
    curtailment_mwh: float       # energy not exported
    # Renewable revenue
    renewable_revenue_keur: float
    # BESS charge from curtailment
    bess_charge_from_curtailment_mwh: float
    bess_discharge_from_curtailment_mwh: float
    bess_curtailment_revenue_keur: float
    bess_grid_arbitrage_revenue_keur: float
    # BESS services
    ancillary_revenue_keur: float
    capacity_revenue_keur: float
    # BESS totals
    total_bess_revenue_keur: float
    # Hybrid total
    total_hybrid_revenue_keur: float

    # Backward-compatible aliases (read-only properties)
    @property
    def clipped_mwh(self) -> float:
        """Backward-compatible alias for curtailed/clipped energy (energy lost due to grid constraint)."""
        return self.curtailment_mwh
    @property
    def ppa_revenue_keur(self) -> float:
        return self.renewable_revenue_keur
    @property
    def merchant_revenue_keur(self) -> float:
        return 0.0
    @property
    def co2_revenue_keur(self) -> float:
        return 0.0
    @property
    def gross_revenue_keur(self) -> float:
        return self.total_hybrid_revenue_keur
    @property
    def net_revenue_keur(self) -> float:
        return self.total_hybrid_revenue_keur


def _degradation_factor(degradation: float, year_index: int) -> float:
    return (1.0 - degradation) ** max(year_index - 1, 0)


def hybrid_solar_generation_mwh(inputs: HybridInputs, year_index: int, day_fraction: float = 1.0) -> float:
    if inputs.solar_capacity_mw <= 0 or inputs.operating_hours_p50 <= 0:
        return 0.0
    avail = inputs.plant_availability * inputs.grid_availability
    deg = _degradation_factor(inputs.pv_degradation, year_index)
    return inputs.solar_capacity_mw * inputs.operating_hours_p50 * day_fraction * avail * deg


def hybrid_wind_generation_mwh(inputs: HybridInputs, year_index: int, day_fraction: float = 1.0) -> float:
    if inputs.wind_capacity_mw <= 0 or inputs.operating_hours_p50 <= 0:
        return 0.0
    avail = inputs.plant_availability * inputs.grid_availability
    deg = _degradation_factor(inputs.wind_degradation, year_index)
    return inputs.wind_capacity_mw * inputs.operating_hours_p50 * day_fraction * avail * deg


def hybrid_total_generation_mwh(inputs: HybridInputs, year_index: int, day_fraction: float = 1.0) -> float:
    return hybrid_solar_generation_mwh(inputs, year_index, day_fraction) + hybrid_wind_generation_mwh(inputs, year_index, day_fraction)


def hybrid_period_revenue(inputs: HybridInputs, year_index: int, day_fraction: float = 1.0) -> HybridRevenueBreakdown:
    """Compute hybrid revenue for one period using explicit curtailment capture."""
    solar = hybrid_solar_generation_mwh(inputs, year_index, day_fraction)
    wind = hybrid_wind_generation_mwh(inputs, year_index, day_fraction)
    total = solar + wind

    # Grid clipping
    cap = inputs.total_capacity_mw
    grid_conn = inputs.grid_connection_mw
    if cap <= grid_conn or grid_conn <= 0:
        exported = total
        curtailment = 0.0
    else:
        exported = total * grid_conn / cap
        curtailment = total - exported

    # Renewable revenue: exported MWh × tariff
    indexed_tariff = inputs.tariff_eur_mwh * (1 + inputs.tariff_escalation) ** max(year_index - 1, 0)
    renewable_rev = exported * indexed_tariff / 1000

    # BESS charge from curtailment
    bess_charge = 0.0
    bess_discharge = 0.0
    bess_curtail_rev = 0.0
    bess_grid_arb = 0.0
    ancillary = 0.0
    capacity = 0.0
    bess_total = 0.0

    if inputs.bess is not None:
        bess = inputs.bess
        max_throughput = bess.energy_mwh * bess.cycles_per_year * day_fraction
        bess_charge = min(curtailment * inputs.charge_from_curtailment_share, max_throughput)
        bess_discharge = bess_charge * bess.round_trip_efficiency
        discharge_price = inputs.effective_discharge_price
        bess_curtail_rev = bess_discharge * discharge_price / 1000

        # Grid arbitrage (after curtailment charge)
        if inputs.grid_charge_allowed:
            total_limit = bess.energy_mwh * bess.cycles_per_year * day_fraction
            # First charge from curtailment
            curtail_charged = bess_charge
            remaining_throughput = max(0.0, total_limit - curtail_charged)
            # Then grid charge limited by remaining throughput
            grid_charge_limited = min(inputs.grid_charge_mwh, remaining_throughput)
            grid_discharge = grid_charge_limited * bess.round_trip_efficiency
            bess_grid_arb = grid_discharge * inputs.grid_arbitrage_spread_eur_mwh / 1000

        ancillary = bess.power_mw * bess.ancillary_revenue_eur_mw_year * day_fraction / 1000
        capacity = bess.power_mw * bess.capacity_revenue_eur_mw_year * day_fraction / 1000
        bess_total = bess_curtail_rev + bess_grid_arb + ancillary + capacity

    total_hybrid = renewable_rev + bess_total

    return HybridRevenueBreakdown(
        solar_generation_mwh=solar,
        wind_generation_mwh=wind,
        total_generation_mwh=total,
        exported_mwh=exported,
        curtailment_mwh=curtailment,
        renewable_revenue_keur=renewable_rev,
        bess_charge_from_curtailment_mwh=bess_charge,
        bess_discharge_from_curtailment_mwh=bess_discharge,
        bess_curtailment_revenue_keur=bess_curtail_rev,
        bess_grid_arbitrage_revenue_keur=bess_grid_arb,
        ancillary_revenue_keur=ancillary,
        capacity_revenue_keur=capacity,
        total_bess_revenue_keur=bess_total,
        total_hybrid_revenue_keur=total_hybrid,
    )


def annual_hybrid_revenue(inputs: HybridInputs, year_index: int) -> HybridRevenueBreakdown:
    """Aggregate two semi-annual periods into one year."""
    h1 = hybrid_period_revenue(inputs, year_index, day_fraction=0.5)
    h2 = hybrid_period_revenue(inputs, year_index, day_fraction=0.5)
    return HybridRevenueBreakdown(
        solar_generation_mwh=h1.solar_generation_mwh + h2.solar_generation_mwh,
        wind_generation_mwh=h1.wind_generation_mwh + h2.wind_generation_mwh,
        total_generation_mwh=h1.total_generation_mwh + h2.total_generation_mwh,
        exported_mwh=h1.exported_mwh + h2.exported_mwh,
        curtailment_mwh=h1.curtailment_mwh + h2.curtailment_mwh,
        renewable_revenue_keur=h1.renewable_revenue_keur + h2.renewable_revenue_keur,
        bess_charge_from_curtailment_mwh=h1.bess_charge_from_curtailment_mwh + h2.bess_charge_from_curtailment_mwh,
        bess_discharge_from_curtailment_mwh=h1.bess_discharge_from_curtailment_mwh + h2.bess_discharge_from_curtailment_mwh,
        bess_curtailment_revenue_keur=h1.bess_curtailment_revenue_keur + h2.bess_curtailment_revenue_keur,
        bess_grid_arbitrage_revenue_keur=h1.bess_grid_arbitrage_revenue_keur + h2.bess_grid_arbitrage_revenue_keur,
        ancillary_revenue_keur=h1.ancillary_revenue_keur + h2.ancillary_revenue_keur,
        capacity_revenue_keur=h1.capacity_revenue_keur + h2.capacity_revenue_keur,
        total_bess_revenue_keur=h1.total_bess_revenue_keur + h2.total_bess_revenue_keur,
        total_hybrid_revenue_keur=h1.total_hybrid_revenue_keur + h2.total_hybrid_revenue_keur,
    )


__all__ = [
    "HybridInputs",
    "HybridRevenueBreakdown",
    "hybrid_solar_generation_mwh",
    "hybrid_wind_generation_mwh",
    "hybrid_total_generation_mwh",
    "hybrid_period_revenue",
    "annual_hybrid_revenue",
]