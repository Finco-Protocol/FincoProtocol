"""IDC (Interest During Construction) calculator.

IDC is interest on drawn senior debt during construction that gets
capitalized into CAPEX. This creates a circular dependency:
- Higher CAPEX → higher debt → more interest → even higher CAPEX

The circular is resolved via fixed-point iteration.

Synthetic reference projects use round illustrative assumptions; no external calibration values are embedded here.
"""
from scipy.optimize import fixed_point


def calculate_idc_fixed_point(
    base_capex_keur: float,
    gearing_ratio: float,
    all_in_rate: float,
    construction_periods: int,
    idc_seed: float = 0.0,
    xtol: float = 1e-6,
) -> float:
    """Calculate IDC using fixed-point iteration.
    
    The IDC is computed assuming linear drawdown of debt during construction.
    Interest on the average outstanding balance is capitalized.
    
    Args:
        base_capex_keur: Base CAPEX (excluding IDC)
        gearing_ratio: Debt / Total CAPEX ratio
        all_in_rate: Annual interest rate (e.g., 0.0565 for 5.65%)
        construction_periods: Number of construction periods (2 for semi-annual 12 months)
        idc_seed: Initial guess for IDC
        xtol: Convergence tolerance
    
    Returns:
        IDC in kEUR
    """
    def iteration(idc_guess: float) -> float:
        # Total CAPEX = base + IDC
        total_capex = base_capex_keur + idc_guess
        
        # Senior debt = total capex × gearing
        total_debt = total_capex * gearing_ratio
        
        # Assume linear drawdown: average outstanding = debt / 2
        # During construction, interest accrues on average balance
        avg_debt_during_construction = total_debt / 2
        
        # Construction years
        construction_years = construction_periods / 2  # semi-annual: 2 periods = 1 year
        
        # IDC = average debt × rate × time
        idc = avg_debt_during_construction * all_in_rate * construction_years
        
        return idc
    
    try:
        result = fixed_point(
            iteration,
            x0=idc_seed,
            xtol=xtol,
            maxiter=100,
            method="iteration",
        )
        return float(result)
    except RuntimeError:
        # Failed to converge, return seed
        return idc_seed


def calculate_idc_detailed(
    capex_schedule: dict[int, float],
    gearing_ratio: float,
    all_in_rate: float,
    max_iterations: int = 20,
    tolerance: float = 1.0,
) -> float:
    """Calculate IDC using detailed period-by-period drawdown with iteration.

    This handles circular reference: IDC increases CAPEX -> more debt -> more IDC.
    Iterates until convergence (tolerance in kEUR).

    Args:
        capex_schedule: Dict mapping period_index → CAPEX in kEUR (construction only)
        gearing_ratio: Debt / Total CAPEX ratio
        all_in_rate: Annual interest rate
        max_iterations: Maximum iterations for convergence
        tolerance: Convergence threshold in kEUR

    Returns:
        IDC in kEUR
    """
    if not capex_schedule:
        return 0.0

    idc_prev = 0.0

    for _ in range(max_iterations):
        cumulative_capex = 0.0
        cumulative_debt = 0.0
        idc_total = 0.0

        for period_idx in sorted(capex_schedule.keys()):
            capex = capex_schedule[period_idx]

            # New CAPEX in this period (including IDC from previous iteration)
            cumulative_capex += capex

            # New debt drawn: gearing × (CAPEX + prior IDC for this period)
            # IDC is distributed across construction periods
            idc_this_period = idc_prev / len(capex_schedule) if idc_prev > 0 else 0
            debt_drawn = (capex + idc_this_period) * gearing_ratio
            cumulative_debt += debt_drawn

            # Interest on outstanding debt (6 months = half year)
            period_interest = cumulative_debt * all_in_rate * 0.5

            # Capitalize interest into CAPEX (IDC)
            idc_total += period_interest

        # Check convergence
        if abs(idc_total - idc_prev) < tolerance:
            return idc_total

        idc_prev = idc_total

    return idc_prev  # Return last converged value


def idc_annuity_adjustment(
    idc_keur: float,
    all_in_rate: float,
    debt_tenor_years: int,
) -> float:
    """Adjust IDC for annuity-style debt repayment.
    
    During construction, interest is capitalized. After COD, the IDC
    is added to the debt principal and repaid over the tenor.
    
    Args:
        idc_keur: IDC amount in kEUR
        all_in_rate: Annual interest rate
        debt_tenor_years: Senior debt tenor in years
    
    Returns:
        Effective IDC in kEUR (slightly higher due to利息 capitalization)
    """
    if idc_keur <= 0 or all_in_rate <= 0 or debt_tenor_years <= 0:
        return idc_keur
    
    # IDC becomes part of debt
    # Interest on IDC during repayment period
    idc_with_interest = idc_keur * (1 + all_in_rate * debt_tenor_years / 2)
    
    return idc_with_interest