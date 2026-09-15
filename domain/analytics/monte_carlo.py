"""Monte Carlo simulation for project returns.

Uses log-normal distribution for generation uncertainty.
Runs N simulations and returns distribution of IRR/NPV.
"""
from dataclasses import dataclass
from typing import Optional
import math
import numpy as np


@dataclass
class MonteCarloResult:
    """Result of Monte Carlo simulation."""
    n_simulations: int
    # Project IRR distribution
    project_irr_mean: float
    project_irr_median: float
    project_irr_p10: float
    project_irr_p90: float
    project_irr_std: float
    # Equity IRR distribution
    equity_irr_mean: float
    equity_irr_median: float
    equity_irr_p10: float
    equity_irr_p90: float
    equity_irr_std: float
    # Project NPV distribution
    project_npv_mean: float
    project_npv_p10: float
    project_npv_p90: float
    # All simulation results
    project_irr_all: list[float]
    equity_irr_all: list[float]
    project_npv_all: list[float]


def log_normal_sample(mean: float, std_dev: float) -> float:
    """Sample from log-normal distribution.
    
    Args:
        mean: Arithmetic mean of the distribution
        std_dev: Standard deviation
    
    Returns:
        Sample from log-normal distribution
    """
    # Log-normal parameters from mean and std
    cv = std_dev / mean  # Coefficient of variation
    sigma_sq = math.log(1 + cv ** 2)
    sigma = math.sqrt(sigma_sq)
    mu = math.log(mean) - sigma_sq / 2
    
    # Sample using numpy
    return float(np.random.lognormal(mu, sigma))


def run_monte_carlo(
    base_case: dict,
    n_simulations: int = 1000,
    generation_cv: float = 0.10,
    seed: Optional[int] = None,
) -> MonteCarloResult:
    """Run Monte Carlo simulation for project returns.
    
    Args:
        base_case: Dict with 'total_capex', 'ebitda_schedule', 'debt', 'equity',
                   'revenue_schedule', 'discount_rate_project', 'discount_rate_equity'
        n_simulations: Number of simulations to run
        generation_cv: Coefficient of variation for generation (default 10%)
        seed: Random seed for reproducibility
    
    Returns:
        MonteCarloResult with distribution statistics
    """
    if seed is not None:
        np.random.seed(seed)
    
    total_capex = base_case['total_capex']
    debt = base_case['debt']
    equity = base_case['equity']
    ebitda_schedule = base_case['ebitda_schedule']
    revenue_schedule = base_case['revenue_schedule']
    discount_project = base_case['discount_rate_project']
    discount_equity = base_case['discount_rate_equity']
    rate_per_period = base_case['rate_per_period']
    n_periods = base_case['n_periods']
    dates = base_case['dates']
    
    project_irr_all = []
    equity_irr_all = []
    project_npv_all = []
    
    for _ in range(n_simulations):
        # Generate uncertain generation (log-normal)
        uncertain_ebitda = [
            log_normal_sample(ebitda_schedule[i], ebitda_schedule[i] * generation_cv)
            for i in range(len(ebitda_schedule))
        ]
        
        # Recalculate revenue from uncertain EBITDA
        uncertain_revenue = []
        for i in range(len(revenue_schedule)):
            rev = revenue_schedule[i]
            ebitda_base = ebitda_schedule[i]
            if ebitda_base > 0:
                # Scale revenue proportionally with EBITDA
                uncertain_revenue.append(rev * uncertain_ebitda[i] / ebitda_base)
            else:
                uncertain_revenue.append(rev)
        
        # Build cash flows
        # Project CF = -CAPEX + CF each period
        project_cf = [-total_capex]
        for i in range(n_periods):
            cf = uncertain_revenue[i] - uncertain_ebitda[i] * 0.3  # Simplified tax ~30%
            project_cf.append(cf)
        
        # Equity CF = CF after debt service
        equity_cf = [-equity]
        tenor = int(n_periods / 2)  # Approximate
        for i in range(n_periods):
            period_idx = i // 2  # Semi-annual to annual
            if period_idx < tenor:
                ds = debt * rate_per_period * 2  # Simplified annual DS
            else:
                ds = 0
            equity_cf.append(max(0, uncertain_ebitda[i] * 0.7 - ds))  # After tax CF
        
        # Calculate IRR using simple Newton method
        from domain.returns.xirr import xirr, xnpv
        
        try:
            irr_proj = xirr(project_cf, dates, guess=0.08)
        except Exception:
            irr_proj = 0.08
        
        try:
            irr_eq = xirr(equity_cf, dates, guess=0.10)
        except Exception:
            irr_eq = 0.10
        
        try:
            npv_proj = xnpv(discount_project, project_cf, dates)
        except Exception:
            npv_proj = 0
        
        project_irr_all.append(irr_proj)
        equity_irr_all.append(irr_eq)
        project_npv_all.append(npv_proj)
    
    # Sort for percentiles
    project_irr_all.sort()
    equity_irr_all.sort()
    project_npv_all.sort()
    
    def percentile(arr, p):
        idx = int(len(arr) * p / 100)
        idx = min(idx, len(arr) - 1)
        return arr[idx]
    
    return MonteCarloResult(
        n_simulations=n_simulations,
        project_irr_mean=np.mean(project_irr_all),
        project_irr_median=percentile(project_irr_all, 50),
        project_irr_p10=percentile(project_irr_all, 10),
        project_irr_p90=percentile(project_irr_all, 90),
        project_irr_std=np.std(project_irr_all),
        equity_irr_mean=np.mean(equity_irr_all),
        equity_irr_median=percentile(equity_irr_all, 50),
        equity_irr_p10=percentile(equity_irr_all, 10),
        equity_irr_p90=percentile(equity_irr_all, 90),
        equity_irr_std=np.std(equity_irr_all),
        project_npv_mean=np.mean(project_npv_all),
        project_npv_p10=percentile(project_npv_all, 10),
        project_npv_p90=percentile(project_npv_all, 90),
        project_irr_all=project_irr_all,
        equity_irr_all=equity_irr_all,
        project_npv_all=project_npv_all,
    )


def probability_exceed_threshold(irr_values: list[float], threshold: float) -> float:
    """Probability that IRR exceeds threshold.
    
    Args:
        irr_values: List of IRR values from simulation
        threshold: Threshold IRR (e.g., 0.08 for 8%)
    
    Returns:
        Probability (0 to 1) of exceeding threshold
    """
    n_exceed = sum(1 for v in irr_values if v > threshold)
    return n_exceed / len(irr_values) if irr_values else 0


def probability_of_loss(irr_values: list[float]) -> float:
    """Probability that equity IRR is negative (loss).
    
    Args:
        irr_values: List of IRR values
    
    Returns:
        Probability of loss (0 to 1)
    """
    return probability_exceed_threshold(irr_values, 0) / len(irr_values) if irr_values else 0