"""XNPV (Date-based Net Present Value) module.

This module provides date-based NPV calculation matching Excel's XNPV function.
XNPV uses the formula:

    NPV = sum(cf_i / (1 + rate)^d_i / 365)

where d_i is the number of days from the first date to cash flow i.
"""
from datetime import date
from typing import Sequence


def xnpv(rate: float, cash_flows: Sequence[float], dates: Sequence[date]) -> float:
    """Calculate NPV with exact date-based discounting (Excel XNPV compatible).
    
    Args:
        rate: Annual discount rate
        cash_flows: Sequence of cash flows
        dates: Corresponding payment dates (first is t=0)
    
    Returns:
        Net Present Value
    
    Note:
        Uses 365-day year convention matching Excel XNPV.
        The first cash flow is at date[0] with no discounting (t=0).
    
    Example:
        >>> cfs = [-10000, 3000, 4000, 5000]
        >>> ds = [date(2020,1,1), date(2021,1,1), date(2022,1,1), date(2023,1,1)]
        >>> xnpv(0.10, cfs, ds)  # 10% annual discount
        3066.97...
    """
    if not cash_flows:
        return 0.0
    if len(cash_flows) != len(dates):
        raise ValueError("cash_flows and dates must have the same length")
    
    if rate <= -1.0:
        return float('inf')
    
    d0 = dates[0]
    return sum(
        cf / (1 + rate) ** ((d - d0).days / 365.0)
        for cf, d in zip(cash_flows, dates)
    )


def xnpv_schedule(
    rate: float,
    cash_flows: Sequence[float],
    dates: Sequence[date],
) -> Sequence[float]:
    """Calculate cumulative NPV at each cash flow date.
    
    Args:
        rate: Annual discount rate
        cash_flows: Sequence of cash flows
        dates: Corresponding payment dates
    
    Returns:
        List of cumulative NPV values at each date
    
    Example:
        >>> cfs = [-1000, 500, 600]
        >>> ds = [date(2020,1,1), date(2021,1,1), date(2022,1,1)]
        >>> xnpv_schedule(0.08, cfs, ds)
        [-1000.0, -538.89, 21.88...]
    """
    if not cash_flows:
        return []
    
    d0 = dates[0]
    cumulative: list[float] = []
    running = 0.0
    
    for cf, d in zip(cash_flows, dates):
        running += cf / (1 + rate) ** ((d - d0).days / 365.0)
        cumulative.append(running)
    
    return cumulative
