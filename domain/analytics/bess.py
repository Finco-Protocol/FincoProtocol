"""BESS - Battery Energy Storage System modeling.

Models:
- Charge/discharge cycles
- Roundtrip efficiency (RTE)
- Degradation over time
- Revenue from energy arbitrage
- Participation in ancillary services markets

BESS revenue model:
- Energy arbitrage: buy when prices low, sell when high
- Capacity payment: for providing firm capacity
- Ancillary services: frequency regulation, reserves
"""
from dataclasses import dataclass
from typing import Optional


@dataclass
class BESSParams:
    """BESS parameters."""
    capacity_mwh: float       # Energy capacity (MWh)
    power_mw: float           # Power rating (MW)
    cost_per_mwh: float       # CAPEX cost per MWh (EUR/MWh)
    rte: float = 0.88         # Roundtrip efficiency (0-1)
    cycle_life: int = 5000    # Total cycles before EOL
    degradation_rate: float = 0.02  # Annual capacity degradation
    annual_cycles: int = 365  # Full cycles per year
    soc_min_pct: float = 10   # Minimum state of charge
    soc_max_pct: float = 95  # Maximum state of charge
    efficiency_curve: bool = False  # Use efficiency curve vs constant


@dataclass
class BESSResult:
    """Result of BESS simulation."""
    # CAPEX
    total_capex_eur: float
    capex_per_mw: float
    capex_per_mwh: float
    # Annual metrics
    avg_annual_cycles: float
    capacity_factor: float
    rte_actual: float
    # Revenue components
    energy_arbitrage_eur: float
    capacity_payment_eur: float
    ancillary_revenue_eur: float
    total_revenue_eur: float
    # Costs
    opex_annual_eur: float
    replacement_cost_eur: float
    # Degradation
    capacity_at_year_10_mwh: float
    capacity_at_year_20_mwh: float
    # Net
    net_revenue_eur: float


def size_bess(
    required_storage_hours: float,
    peak_power_mw: float,
) -> tuple[float, float]:
    """Size BESS for required storage duration.
    
    Args:
        required_storage_hours: Hours of storage (e.g., 4 for 4-hour BESS)
        peak_power_mw: Peak power requirement
    
    Returns:
        (capacity_mwh, power_mw)
    """
    capacity = peak_power_mw * required_storage_hours
    return capacity, peak_power_mw


def calculate_bess_capex(params: BESSParams) -> dict:
    """Calculate BESS CAPEX.
    
    Args:
        params: BESS parameters
    
    Returns:
        Dict with CAPEX breakdown
    """
    energy_cost = params.capacity_mwh * params.cost_per_mwh
    power_cost = params.power_mw * params.cost_per_mwh * 0.3  # ~30% of energy cost
    
    total = energy_cost + power_cost
    
    return {
        "energy_cost_eur": energy_cost,
        "power_cost_eur": power_cost,
        "total_capex_eur": total,
        "capex_per_mw": total / params.power_mw if params.power_mw > 0 else 0,
        "capex_per_mwh": params.cost_per_mwh,
    }


def simulate_bess_annual(
    params: BESSParams,
    market_price_low: float,  # EUR/MWh when charging
    market_price_high: float,  # EUR/MWh when discharging
    price_spread_days: int = 1,  # Days between charge/discharge
    capacity_payment_eur: float = 0,
    ancillary_rate: float = 0,
) -> BESSResult:
    """Simulate BESS annual performance.
    
    Args:
        params: BESS parameters
        market_price_low: Price when charging (EUR/MWh)
        market_price_high: Price when discharging (EUR/MWh)
        price_spread_days: Average days between charge/discharge cycles
        capacity_payment_eur: Fixed capacity payment (EUR/year)
        ancillary_rate: Ancillary service rate (EUR/MW/year)
    
    Returns:
        BESSResult with annual metrics
    """
    # Calculate cycles
    # Energy throughput per year
    cycles_per_day = 1.0 / price_spread_days if price_spread_days > 0 else 0
    annual_cycles = cycles_per_day * 365
    
    # Degradation
    degradation_factor = 1 - params.degradation_rate
    
    # Average usable capacity (adjusted for degradation)
    avg_capacity = params.capacity_mwh * (1 - params.degradation_rate / 2)
    
    # Roundtrip efficiency losses
    charge_energy = avg_capacity * annual_cycles
    discharge_energy = charge_energy * params.rte
    
    # Energy arbitrage
    spread = market_price_high - market_price_low
    # Account for roundtrip losses
    net_spread = spread * params.rte - (market_price_low * (1 - params.rte))
    energy_arbitrage = discharge_energy / annual_cycles * net_spread if annual_cycles > 0 else 0
    energy_arbitrage = charge_energy * (spread - market_price_low * (1 - params.rte) / params.rte) if charge_energy > 0 and params.rte > 0 else 0
    
    # Simplified: revenue = discharge energy * spread
    discharge_value = discharge_energy * spread / params.rte if params.rte > 0 else 0
    charge_cost = charge_energy * market_price_low
    energy_arbitrage = max(0, discharge_value - charge_cost)
    
    # Capacity payment
    capacity_rev = capacity_payment_eur
    
    # Ancillary services
    ancillary_rev = ancillary_rate * params.power_mw
    
    # OPEX
    opex = params.capacity_mwh * 5000  # ~5000 EUR/MWh/year for O&M
    
    # Replacement cost (simplified)
    replacement = params.capacity_mwh * params.cost_per_mwh * 0.2 * (annual_cycles / params.cycle_life)
    
    # Net revenue
    net_rev = energy_arbitrage + capacity_rev + ancillary_rev - opex - replacement
    
    # Capacity at different years
    cap_10 = params.capacity_mwh * (1 - params.degradation_rate) ** 10
    cap_20 = params.capacity_mwh * (1 - params.degradation_rate) ** 20
    
    return BESSResult(
        total_capex_eur=params.capacity_mwh * params.cost_per_mwh * 1.3,  # Include power equipment
        capex_per_mw=0,
        capex_per_mwh=params.cost_per_mwh,
        avg_annual_cycles=annual_cycles,
        capacity_factor=annual_cycles / params.cycle_life,
        rte_actual=params.rte,
        energy_arbitrage_eur=energy_arbitrage,
        capacity_payment_eur=capacity_rev,
        ancillary_revenue_eur=ancillary_rev,
        total_revenue_eur=energy_arbitrage + capacity_rev + ancillary_rev,
        opex_annual_eur=opex,
        replacement_cost_eur=replacement,
        capacity_at_year_10_mwh=cap_10,
        capacity_at_year_20_mwh=cap_20,
        net_revenue_eur=net_rev,
    )


def bess_revenue_schedule(
    params: BESSParams,
    horizon_years: int,
    price_low_curve: list[float],
    price_high_curve: list[float],
    discount_rate: float,
) -> tuple[list[float], list[float]]:
    """Calculate BESS revenue schedule over project horizon.
    
    Args:
        params: BESS parameters
        horizon_years: Project horizon
        price_low_curve: Low prices per year (EUR/MWh)
        price_high_curve: High prices per year (EUR/MWh)
        discount_rate: Discount rate
    
    Returns:
        (revenue_schedule, present_value_schedule) in EUR
    """
    revenues = []
    pv_revenues = []
    
    current_capacity = params.capacity_mwh
    
    for year in range(1, horizon_years + 1):
        # Degrade capacity
        current_capacity *= (1 - params.degradation_rate)
        
        # Get prices for this year
        low = price_low_curve[year - 1] if year <= len(price_low_curve) else price_low_curve[-1]
        high = price_high_curve[year - 1] if year <= len(price_high_curve) else price_high_curve[-1]
        
        # Simulate year
        year_result = simulate_bess_annual(
            params,
            low,
            high,
            capacity_payment_eur=50000 * current_capacity / params.capacity_mwh if current_capacity > 0 else 0,
        )
        
        rev = year_result.net_revenue_eur
        revenues.append(rev)
        pv_revenues.append(rev / (1 + discount_rate) ** year)
    
    return revenues, pv_revenues


def marginal_loss_factor(rte: float) -> float:
    """Calculate marginal loss factor from RTE.
    
    For energy arbitrage, marginal loss = 1 - RTE.
    
    Args:
        rte: Roundtrip efficiency (0-1)
    
    Returns:
        Marginal loss factor
    """
    return 1 - rte