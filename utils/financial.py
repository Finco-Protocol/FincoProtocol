"""Financial math utilities - safe operations for KPI calculations.

Provides safe division and formatting functions for financial metrics.
"""
import math
from typing import Optional
from datetime import date


def safe_ratio(
    numerator: float,
    denominator: float,
    default: float = 0.0
) -> float:
    """Safe division for financial KPIs.
    
    Args:
        numerator: The dividend
        denominator: The divisor
        default: Value to return if denominator is effectively zero
    
    Returns:
        Result of division, or default if denominator is near-zero
    """
    if abs(denominator) < 1e-10:
        return default
    return numerator / denominator


def safe_irr(
    cash_flows: list[float],
    dates: list[date],
    guess: float = 0.08,
) -> Optional[float]:
    """XIRR with graceful fallback.
    
    Args:
        cash_flows: List of cash flows
        dates: Corresponding dates for cash flows
        guess: Initial guess for IRR
    
    Returns:
        IRR as decimal, or None if no solution exists
    """
    if not cash_flows or len(cash_flows) < 2:
        return None
    
    has_pos = any(cf > 0 for cf in cash_flows)
    has_neg = any(cf < 0 for cf in cash_flows)
    if not (has_pos and has_neg):
        return None
    
    from domain.returns.xirr import xirr
    return xirr(cash_flows, dates, guess=guess)


def safe_npv(
    rate: float,
    cash_flows: list[float],
    dates: list[date],
) -> float:
    """XNPV with validation.
    
    Args:
        rate: Discount rate (decimal)
        cash_flows: List of cash flows
        dates: Corresponding dates
    
    Returns:
        NPV value, or 0.0 if calculation fails
    """
    if rate <= -1.0:
        return float('inf')
    if not cash_flows:
        return 0.0
    
    from domain.returns.xirr import xnpv
    return xnpv(rate, cash_flows, dates)


def format_keur(value: float, decimals: int = 0) -> str:
    """Standard format for kEUR display.
    
    Args:
        value: Value in kEUR
        decimals: Number of decimal places
    
    Returns:
        Formatted string like "12,345 k€"
    """
    return f"{value:,.{decimals}f} k€"


def format_pct(value: float, decimals: int = 2) -> str:
    """Standard format for percentages.
    
    Args:
        value: Value as decimal (e.g., 0.1234 for 12.34%)
        decimals: Number of decimal places
    
    Returns:
        Formatted string like "12.34%"
    """
    return f"{value * 100:.{decimals}f}%"


def format_multiple(value: float, decimals: int = 2) -> str:
    """Standard format for multiples (DSCR, LLCR, etc.).
    
    Args:
        value: Multiple value
        decimals: Number of decimal places
    
    Returns:
        Formatted string like "1.23x" or "∞"
    """
    if math.isinf(value):
        return "∞"
    return f"{value:.{decimals}f}x"


def format_mw(value: float, decimals: int = 1) -> str:
    """Format MW capacity.
    
    Args:
        value: Value in MW
        decimals: Number of decimal places
    
    Returns:
        Formatted string like "75.0 MW"
    """
    return f"{value:.{decimals}f} MW"


def format_mwh(value: float, decimals: int = 0) -> str:
    """Format MWh energy.
    
    Args:
        value: Value in MWh
        decimals: Number of decimal places
    
    Returns:
        Formatted string like "110,000 MWh"
    """
    return f"{value:,.{decimals}f} MWh"


def format_lcoe(value: float, decimals: int = 2) -> str:
    """Format LCOE in EUR/MWh.
    
    Args:
        value: LCOE in EUR/MWh
        decimals: Number of decimal places
    
    Returns:
        Formatted string like "52.75 €/MWh"
    """
    return f"{value:.{decimals}f} €/MWh"