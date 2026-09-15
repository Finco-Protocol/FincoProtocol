"""XIRR calculation using Newton-Raphson method with fallback to bisection."""
from datetime import date
from typing import List, Optional, Sequence

from finco_core.sponsor.xnpv import xnpv


def xirr(
    cash_flows: Sequence[float],
    dates: Sequence[date],
    guess: float = 0.10,
    tolerance: float = 1e-7,
    max_iterations: int = 200,
) -> Optional[float]:
    """Calculate Internal Rate of Return using dates (reference-compatible).
    
    Uses Newton-Raphson method. Excel uses 365-day year, max 100 iterations,
    and guess defaults to 0.1 (10%).
    
    Args:
        cash_flows: Sequence of cash flows (must have at least one positive
                   and one negative value for IRR to exist)
        dates: Corresponding dates (must be same length as cash_flows)
        guess: Initial guess for IRR (default 0.10 = 10%)
        tolerance: Convergence tolerance (default 1e-7)
        max_iterations: Maximum Newton-Raphson iterations (default 200)
    
    Returns:
        IRR as decimal (e.g., 0.0842 for 8.42%), or None if no solution found
    
    Raises:
        ValueError: If cash_flows and dates have different lengths
                   or fewer than 2 cash flows
    
    Note:
        Excel XIRR requires at least one positive and one negative cash flow.
        If all cash flows have the same sign, XIRR returns #NUM!
    """
    if not cash_flows or len(cash_flows) < 2:
        return None
    if len(cash_flows) != len(dates):
        raise ValueError("cash_flows and dates must have the same length")
    
    # Check for sign change (required for IRR to exist)
    has_positive = any(cf > 0 for cf in cash_flows)
    has_negative = any(cf < 0 for cf in cash_flows)
    if not (has_positive and has_negative):
        return None
    
    d0 = dates[0]
    year_fractions = [(d - d0).days / 365.0 for d in dates]
    
    rate = guess
    
    for _ in range(max_iterations):
        # Calculate NPV at current rate
        npv = sum(
            cf / (1 + rate) ** t
            for cf, t in zip(cash_flows, year_fractions)
        )
        
        # Calculate derivative d(NPV)/d(rate)
        # d/d(rate)[cf/(1+r)^t] = -t * cf / (1+r)^(t+1)
        d_npv = sum(
            -t * cf / (1 + rate) ** (t + 1)
            for cf, t in zip(cash_flows, year_fractions)
        )
        
        if abs(d_npv) < 1e-15:
            # Derivative too small, abort
            return None
        
        # Newton-Raphson step
        new_rate = rate - npv / d_npv
        
        # Check convergence
        if abs(new_rate - rate) < tolerance:
            return new_rate
        
        # Check for divergence (rate outside reasonable bounds)
        if new_rate < -0.99 or new_rate > 100:
            return None
        
        rate = new_rate
    
    # Did not converge within max_iterations
    return None


def xirr_bisection(
    cash_flows: Sequence[float],
    dates: Sequence[date],
    tolerance: float = 1e-7,
    max_iterations: int = 1000,
) -> Optional[float]:
    """Alternative XIRR using bisection method (more robust, slower).
    
    Use when Newton-Raphson may fail to converge for pathological cash flows.
    
    Args:
        cash_flows: Sequence of cash flows
        dates: Corresponding dates
        tolerance: Convergence tolerance
        max_iterations: Maximum iterations
    
    Returns:
        IRR as decimal, or None if no solution found
    """
    if not cash_flows or len(cash_flows) < 2:
        return None
    
    has_positive = any(cf > 0 for cf in cash_flows)
    has_negative = any(cf < 0 for cf in cash_flows)
    if not (has_positive and has_negative):
        return None
    
    d0 = dates[0]
    year_fractions = [(d - d0).days / 365.0 for d in dates]
    
    # Bisection bounds
    low = -0.9999
    high = 100.0
    
    def npv_at(rate: float) -> float:
        return sum(
            cf / (1 + rate) ** t
            for cf, t in zip(cash_flows, year_fractions)
        )
    
    # Check signs at bounds
    npv_low = npv_at(low)
    npv_high = npv_at(high)
    
    if npv_low * npv_high > 0:
        return None  # No root in range
    
    for _ in range(max_iterations):
        mid = (low + high) / 2
        npv_mid = npv_at(mid)
        
        if abs(npv_mid) < tolerance:
            return mid
        
        if npv_at(low) * npv_mid < 0:
            high = mid
        else:
            low = mid
    
    return (low + high) / 2


def robust_xirr(
    cash_flows: Sequence[float],
    dates: Sequence[date],
    guess: float = 0.10,
) -> Optional[float]:
    """XIRR with automatic fallback to bisection method.

    Tries Newton-Raphson; if it fails to converge, falls back to bisection.
    Bisection is slower but more robust for unconventional CF profiles
    (debt sweeps in late years, lockup-triggered negative cashflows).
    """
    result = xirr(cash_flows, dates, guess=guess)
    if result is not None:
        return result
    # Fallback to bisection
    return xirr_bisection(cash_flows, dates)
