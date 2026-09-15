"""Tariff calculations - PPA and market pricing.

PPA tariff:
- Base tariff at Y1 (from inputs)
- Annual index escalation (PPA index)
- Capped at maximum (if applicable)

Market price:
- From market prices curve
- Extrapolated with market inflation after curve ends
- Different scenarios (Central, Bull, Bear)
"""
from typing import Optional


def ppa_tariff_at_period(
    base_tariff: float,
    ppa_index: float,
    year_index: int,
    cap_eur_mwh: Optional[float] = None,
) -> float:
    """Calculate PPA tariff for a given year.
    
    Args:
        base_tariff: Base tariff in EUR/MWh (Y1)
        ppa_index: Annual escalation rate (e.g., 0.02 for 2%)
        year_index: Year index (1=Y1, 2=Y2, etc.)
        cap_eur_mwh: Optional tariff cap
    
    Returns:
        Tariff in EUR/MWh
    """
    tariff = base_tariff * (1 + ppa_index) ** (year_index - 1)
    
    if cap_eur_mwh is not None and tariff > cap_eur_mwh:
        return cap_eur_mwh
    
    return tariff


def market_price_at_period(
    year_index: int,
    market_prices_curve: tuple[float, ...],
    market_inflation: float,
) -> float:
    """Calculate market price for a given year.
    
    Args:
        year_index: Year index (1-based)
        market_prices_curve: Tuple of prices for years 1..N
        market_inflation: Annual escalation after curve ends
    
    Returns:
        Market price in EUR/MWh
    """
    idx = year_index - 1
    
    # Within curve
    if idx < len(market_prices_curve):
        return market_prices_curve[idx]
    
    # Extrapolate with market inflation
    if market_prices_curve:
        base_price = market_prices_curve[-1]
        return base_price * (1 + market_inflation) ** (idx - len(market_prices_curve) + 1)
    
    # No curve, use 0
    return 0.0


def apply_reduced_tariff(
    full_tariff: float,
    reduced_tariff: float,
    production_mwh: float,
    cap_mwh_per_mw: float,
    capacity_mw: float,
) -> float:
    """Apply reduced tariff for production above cap.
    
    Generic Solar Reference has:
    - Full tariff up to 2,250 MWh × MW
    - Reduced tariff above that
    
    Args:
        full_tariff: Full PPA tariff EUR/MWh
        reduced_tariff: Reduced tariff EUR/MWh (usually same as full for Generic Solar Reference)
        production_mwh: Total production in MWh
        cap_mwh_per_mw: Cap in MWh per MW (2,250 for Generic Solar Reference)
        capacity_mw: Installed capacity in MW
    
    Returns:
        Weighted average tariff EUR/MWh
    """
    cap_total_mwh = cap_mwh_per_mw * capacity_mw
    
    if production_mwh <= cap_total_mwh:
        return full_tariff
    
    # Production above cap
    above_cap = production_mwh - cap_total_mwh
    
    # Weighted average
    revenue = full_tariff * cap_total_mwh + reduced_tariff * above_cap
    return revenue / production_mwh


def balancing_cost_deduction(
    revenue_keur: float,
    balancing_cost_pct: float,
) -> float:
    """Calculate balancing cost deduction from revenue.
    
    Balancing costs represent grid imbalance costs (2.5% for Generic Solar Reference PV).
    These are deducted from revenue.
    
    Args:
        revenue_keur: Gross revenue in kEUR
        balancing_cost_pct: Balancing cost as percentage (e.g., 0.025)
    
    Returns:
        Balancing cost in kEUR
    """
    return revenue_keur * balancing_cost_pct


def net_revenue_after_balancing(
    gross_revenue_keur: float,
    balancing_cost_pct: float,
) -> float:
    """Calculate net revenue after balancing cost deduction.
    
    Args:
        gross_revenue_keur: Gross revenue in kEUR
        balancing_cost_pct: Balancing cost percentage
    
    Returns:
        Net revenue in kEUR
    """
    return gross_revenue_keur * (1 - balancing_cost_pct)


def co2_certificates_revenue(
    generation_mwh: float,
    co2_price_eur_per_mwh: float,
) -> float:
    """Calculate CO2 certificate revenue.
    
    Args:
        generation_mwh: Generation in MWh
        co2_price_eur_per_mwh: CO2 price in EUR/MWh
    
    Returns:
        CO2 revenue in kEUR
    """
    return generation_mwh * co2_price_eur_per_mwh / 1000