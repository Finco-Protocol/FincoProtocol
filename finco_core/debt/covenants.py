"""Financial covenants - DSCR, LLCR, PLCR.

DSCR: Debt Service Coverage Ratio = EBITDA / Debt Service
LLCR: Loan Life Coverage Ratio = PV(FCF to debt maturity) / Outstanding Debt
PLCR: Project Life Coverage Ratio = PV(FCF to project end) / Outstanding Debt
"""
from typing import Sequence


def dscr(
    ebitda_keur: float,
    debt_service_keur: float,
) -> float:
    """Debt Service Coverage Ratio.
    
    Args:
        ebitda_keur: EBITDA in kEUR
        debt_service_keur: Total debt service (interest + principal) in kEUR
    
    Returns:
        DSCR (e.g., 1.15 means EBITDA is 115% of debt service)
    """
    if debt_service_keur <= 0:
        return float('inf')
    return ebitda_keur / debt_service_keur


def llcr(
    fcf_schedule: Sequence[float],
    debt_balance_keur: float,
    rate_per_period: float,
    periods_remaining: int,
) -> float:
    """Loan Life Coverage Ratio.
    
    LLCR = PV(FCF over remaining loan life) / Outstanding Debt
    
    Args:
        fcf_schedule: Future FCF values (kEUR)
        debt_balance_keur: Current outstanding debt (kEUR)
        rate_per_period: Discount rate per period
        periods_remaining: Number of periods until debt maturity
    
    Returns:
        LLCR
    """
    if debt_balance_keur <= 0:
        return float('inf')
    
    pv_fcf = sum(
        fcf / (1 + rate_per_period) ** (t + 1)
        for t, fcf in enumerate(fcf_schedule[:periods_remaining])
    )
    
    return pv_fcf / debt_balance_keur


def plcr(
    fcf_schedule: Sequence[float],
    debt_balance_keur: float,
    rate_per_period: float,
    total_periods: int,
) -> float:
    """Project Life Coverage Ratio.
    
    PLCR = PV(FCF over entire project life) / Outstanding Debt
    
    Args:
        fcf_schedule: Future FCF values (kEUR)
        debt_balance_keur: Current outstanding debt (kEUR)
        rate_per_period: Discount rate per period
        total_periods: Total project periods
    
    Returns:
        PLCR
    """
    if debt_balance_keur <= 0:
        return float('inf')
    
    pv_fcf = sum(
        fcf / (1 + rate_per_period) ** (t + 1)
        for t, fcf in enumerate(fcf_schedule[:total_periods])
    )
    
    return pv_fcf / debt_balance_keur


def lockup_check(
    dscr: float,
    min_dscr_lockup: float = 1.10,
    cash_balance_keur: float = 0,
    reserves_funded_pct: float = 1.0,
) -> bool:
    """Check if distribution lockup applies.
    
    Distribution is blocked if:
    - DSCR < lockup threshold
    - Cash balance < 0
    - Reserves not fully funded
    
    Args:
        dscr: Current DSCR
        min_dscr_lockup: Lockup threshold (default 1.10)
        cash_balance_keur: Current cash balance
        reserves_funded_pct: % of reserve accounts funded (1.0 = 100%)
    
    Returns:
        True if locked up (no distribution)
    """
    if dscr < min_dscr_lockup:
        return True
    if cash_balance_keur < 0:
        return True
    if reserves_funded_pct < 1.0:
        return True
    return False


def covenant_summary(
    ebitda_schedule: list[float],
    debt_service_schedule: list[float],
    fcf_schedule: list[float],
    debt_balance_keur: float,
    rate_per_period: float,
    tenor_periods: int,
) -> dict[str, float]:
    """Calculate all covenant metrics.
    
    Args:
        ebitda_schedule: EBITDA per period
        debt_service_schedule: Debt service per period
        fcf_schedule: Free cash flow per period
        debt_balance_keur: Current debt balance
        rate_per_period: Discount rate
        tenor_periods: Remaining tenor
    
    Returns:
        Dict with min_dscr, avg_dscr, llcr, plcr
    """
    # DSCR calculations
    dsrs = [dscr(ebitda, ds) for ebitda, ds in zip(ebitda_schedule, debt_service_schedule) if ds > 0]
    min_dscr_val = min(dsrs) if dsrs else 0
    avg_dscr_val = sum(dsrs) / len(dsrs) if dsrs else 0
    
    # LLCR
    llcr_val = llcr(fcf_schedule, debt_balance_keur, rate_per_period, tenor_periods)
    
    # PLCR (full horizon)
    plcr_val = plcr(fcf_schedule, debt_balance_keur, rate_per_period, len(fcf_schedule))
    
    return {
        "min_dscr": min_dscr_val,
        "avg_dscr": avg_dscr_val,
        "llcr": llcr_val,
        "plcr": plcr_val,
    }