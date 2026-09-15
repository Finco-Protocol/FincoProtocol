"""LCOE - Levelized Cost of Energy calculation.

LCOE = (Total CAPEX + PV(OPEX)) / Total Generation
     = (Σ(CAPEX_t + OPEX_t) / (1+r)^t) / (Σ(Gen_t / (1+r)^t))
"""
from dataclasses import dataclass


@dataclass
class LCOEResult:
    """Result of LCOE calculation."""
    lcoe_eur_mwh: float
    total_capex_keur: float
    total_opex_keur: float
    pv_capex_opex_keur: float
    total_generation_mwh: float
    pv_generation_mwh: float
    # Components
    capex_per_mw: float
    opex_y1_keur: float
    capacity_mw: float
    horizon_years: int


def calculate_lcoe(
    capacity_mw: float,
    operating_hours_p50: float,
    total_capex_keur: float,
    opex_y1_keur: float,
    opex_inflation: float,
    discount_rate: float,
    horizon_years: int,
    availability: float = 0.99,
    degradation: float = 0.0,
) -> LCOEResult:
    """Calculate Levelized Cost of Energy.
    
    Args:
        capacity_mw: Installed capacity in MW
        operating_hours_p50: P50 yield hours per year
        total_capex_keur: Total capital expenditure in kEUR
        opex_y1_keur: OPEX in year 1 in kEUR
        opex_inflation: Annual OPEX inflation rate
        discount_rate: Discount rate (e.g., 0.0641 for 6.41%)
        horizon_years: Investment horizon in years
        availability: Plant availability (default 0.99)
        degradation: Annual degradation rate (default 0)
    
    Returns:
        LCOEResult with all components
    """
    # Total generation over project life (discounted)
    total_gen = 0.0
    pv_gen = 0.0
    
    for year in range(1, horizon_years + 1):
        # Generation with degradation
        gen = capacity_mw * operating_hours_p50 * availability
        if degradation > 0:
            gen *= (1 - degradation) ** year
        
        total_gen += gen
        
        # Discounted generation
        pv_gen += gen / (1 + discount_rate) ** year
    
    # Total OPEX (discounted)
    total_opex = 0.0
    pv_opex = 0.0
    
    for year in range(1, horizon_years + 1):
        opex = opex_y1_keur * (1 + opex_inflation) ** (year - 1)
        total_opex += opex
        pv_opex += opex / (1 + discount_rate) ** year
    
    # PV of CAPEX (assumed at Y0, already in present value)
    pv_capex = total_capex_keur
    
    # Total PV cost
    pv_total = pv_capex + pv_opex
    
    # LCOE
    lcoe = pv_total / pv_gen if pv_gen > 0 else 0
    lcoe_eur_mwh = lcoe  # Already in €/MWh (pv in kEUR, gen in MWh)
    
    return LCOEResult(
        lcoe_eur_mwh=lcoe_eur_mwh,
        total_capex_keur=total_capex_keur,
        total_opex_keur=total_opex,
        pv_capex_opex_keur=pv_total,
        total_generation_mwh=total_gen,
        pv_generation_mwh=pv_gen,
        capex_per_mw=total_capex_keur / capacity_mw if capacity_mw > 0 else 0,
        opex_y1_keur=opex_y1_keur,
        capacity_mw=capacity_mw,
        horizon_years=horizon_years,
    )


def calculate_lcoe_components(result: LCOEResult) -> dict:
    """Break down LCOE into component costs.
    
    Args:
        result: LCOEResult from calculate_lcoe
    
    Returns:
        Dict with component costs in €/MWh
    """
    if result.pv_generation_mwh == 0:
        return {}
    
    return {
        "CAPEX component": result.pv_capex_opex_keur * result.total_capex_keur / result.pv_total / result.pv_generation_mwh * 1000 if result.pv_total > 0 else 0,
        "OPEX component": result.pv_capex_opex_keur * result.total_opex_keur / result.pv_total / result.pv_generation_mwh * 1000 if result.pv_total > 0 else 0,
        "Total LCOE": result.lcoe_eur_mwh,
    }


def compare_lcoe(lcoe1: LCOEResult, lcoe2: LCOEResult) -> dict:
    """Compare two LCOE results.
    
    Args:
        lcoe1: First LCOE result
        lcoe2: Second LCOE result
    
    Returns:
        Dict with comparison metrics
    """
    diff = lcoe2.lcoe_eur_mwh - lcoe1.lcoe_eur_mwh
    pct = diff / lcoe1.lcoe_eur_mwh * 100 if lcoe1.lcoe_eur_mwh > 0 else 0
    
    return {
        "LCOE 1 (€/MWh)": lcoe1.lcoe_eur_mwh,
        "LCOE 2 (€/MWh)": lcoe2.lcoe_eur_mwh,
        "Difference (€/MWh)": diff,
        "Difference (%)": pct,
    }