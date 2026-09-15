"""Debt amortization schedule - standard and sculpted.

Standard amortization: equal principal payments + interest on outstanding balance.
Sculpted: payments adjusted to maintain target DSCR each period.

For Generic Solar Reference:
- Senior debt: model-derived
- Tenor: 14 years (semi-annual = 28 periods)
- All-in rate: 5.65% (3% base + 265 bps)
- Target DSCR: 1.15
"""
from typing import Optional
from dataclasses import dataclass


@dataclass
class AmortizationResult:
    """Result of amortization schedule calculation."""
    period: int
    opening_balance: float
    interest: float
    principal: float
    closing_balance: float
    payment: float


@dataclass
class DebtServiceResult:
    """Period debt service (interest + principal)."""
    period: int
    interest_keur: float
    principal_keur: float
    total_keur: float
    opening_balance: float
    closing_balance: float


def senior_debt_amount(
    total_capex_keur: float,
    gearing_ratio: float,
) -> float:
    """Calculate senior debt amount from CAPEX and gearing.
    
    Args:
        total_capex_keur: Total project CAPEX in kEUR
        gearing_ratio: Debt / Total CAPEX ratio (e.g., 0.75)
    
    Returns:
        Senior debt amount in kEUR
    """
    return total_capex_keur * gearing_ratio


def standard_amortization(
    debt_keur: float,
    rate_per_period: float,
    tenor_periods: int,
) -> list[DebtServiceResult]:
    """Calculate standard amortization schedule.
    
    Equal principal payments each period with interest on outstanding.
    
    Args:
        debt_keur: Initial debt amount in kEUR
        rate_per_period: Interest rate per period (e.g., 0.02825 for 5.65% annual)
        tenor_periods: Number of payment periods
    
    Returns:
        List of DebtServiceResult for each period
    """
    schedule = []
    balance = debt_keur
    principal_per_period = debt_keur / tenor_periods
    
    for period in range(1, tenor_periods + 1):
        interest = balance * rate_per_period
        principal = min(principal_per_period, balance)
        payment = interest + principal
        closing = balance - principal
        
        schedule.append(DebtServiceResult(
            period=period,
            interest_keur=interest,
            principal_keur=principal,
            total_keur=payment,
            opening_balance=balance,
            closing_balance=max(0, closing),
        ))
        
        balance = closing
    
    return schedule


def sculpted_amortization(
    debt_keur: float,
    ebitda_schedule: list[float],
    rate_per_period: float,
    tenor_periods: int,
    target_dscr: float = 1.15,
) -> tuple[list[DebtServiceResult], list[float]]:
    """Calculate sculpted amortization schedule.
    
    Sculpted payments = EBITDA / target_dscr
    Payment is split between interest and principal such that
    PV(payments) = debt amount at the discount rate.
    
    Args:
        debt_keur: Debt amount in kEUR
        ebitda_schedule: EBITDA per period (kEUR)
        rate_per_period: Discount rate per period
        tenor_periods: Number of periods
        target_dscr: Target DSCR (e.g., 1.15)
    
    Returns:
        Tuple of (debt_service_schedule, dscr_schedule)
    """
    # Sculpted payment = EBITDA / target_dscr
    sculpted_payment = [ebitda / target_dscr for ebitda in ebitda_schedule[:tenor_periods]]
    
    schedule = []
    balance = debt_keur
    dscr_list = []
    
    for period in range(1, tenor_periods + 1):
        ebitda = ebitda_schedule[period - 1]
        payment = sculpted_payment[period - 1]
        
        interest = balance * rate_per_period
        principal = payment - interest
        
        # Ensure principal doesn't exceed balance
        if principal > balance:
            principal = balance
            payment = interest + principal
        
        closing = max(0, balance - principal)
        
        # Actual DSCR = EBITDA / payment
        dscr_actual = ebitda / payment if payment > 0 else 0
        
        schedule.append(DebtServiceResult(
            period=period,
            interest_keur=interest,
            principal_keur=principal,
            total_keur=payment,
            opening_balance=balance,
            closing_balance=closing,
        ))
        
        dscr_list.append(dscr_actual)
        balance = closing
    
    return schedule, dscr_list


def debt_service_from_schedule(
    schedule: list[DebtServiceResult],
) -> tuple[list[float], list[float]]:
    """Extract interest and principal from schedule.
    
    Args:
        schedule: List of DebtServiceResult
    
    Returns:
        Tuple of (interest_list, principal_list) in kEUR
    """
    interest = [s.interest_keur for s in schedule]
    principal = [s.principal_keur for s in schedule]
    return interest, principal


def pv_payments(
    payments: list[float],
    rate_per_period: float,
) -> float:
    """Calculate present value of payments at given rate.
    
    Args:
        payments: List of payment amounts
        rate_per_period: Discount rate per period
    
    Returns:
        PV in same units as payments
    """
    return sum(
        p / (1 + rate_per_period) ** (t + 1)
        for t, p in enumerate(payments)
    )


def annuity_payment(
    principal: float,
    rate_per_period: float,
    periods: int,
) -> float:
    """Calculate fixed annuity payment for a loan.
    
    Args:
        principal: Loan amount
        rate_per_period: Interest rate per period
        periods: Number of payments
    
    Returns:
        Fixed payment amount
    """
    if rate_per_period <= 0:
        return principal / periods
    
    r = rate_per_period
    n = periods
    
    return principal * (r * (1 + r) ** n) / ((1 + r) ** n - 1)


def balance_after_n_periods(
    initial: float,
    rate_per_period: float,
    payment: float,
    periods: int,
) -> float:
    """Calculate remaining balance after n periods of annuity payments.
    
    Args:
        initial: Initial loan amount
        rate_per_period: Interest rate per period
        payment: Fixed payment amount
        periods: Number of periods elapsed
    
    Returns:
        Remaining balance
    """
    if rate_per_period <= 0:
        return initial - payment * periods
    
    r = rate_per_period
    n = periods
    
    # Balance = P*(1+r)^n - PMT*[(1+r)^n - 1]/r
    balance = initial * (1 + r) ** n - payment * ((1 + r) ** n - 1) / r
    
    return max(0, balance)