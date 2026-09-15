"""Reserve accounts - DSRA, J-DSRA, MRA funding and balances.

DSRA: Debt Service Reserve Account
- 6 months of senior debt service funded at financial close
- Synthetic references derive reserve funding from their debt-service profile.

MRA: Maintenance Reserve Account
- For major maintenance when configured

J-DSRA: Junior DSRA (for subordinated debt, not used in Generic Solar Reference)
"""
from typing import Optional


def dsra_funding(
    annual_debt_service_keur: float,
    dsra_months: int = 6,
) -> float:
    """Calculate initial DSRA funding.
    
    Args:
        annual_debt_service_keur: Annual senior debt service in kEUR
        dsra_months: Number of months of DSRA (default 6)
    
    Returns:
        Initial DSRA balance in kEUR
    """
    return annual_debt_service_keur * (dsra_months / 12)


def dsra_balance_update(
    prior_balance_keur: float,
    contribution_keur: float,
    withdrawal_keur: float = 0,
) -> float:
    """Update DSRA balance.
    
    Args:
        prior_balance_keur: Prior period balance
        contribution_keur: Contribution this period
        withdrawal_keur: Withdrawal this period (for debt service)
    
    Returns:
        New balance
    """
    return max(0, prior_balance_keur + contribution_keur - withdrawal_keur)


def dsra_contribution_needed(
    current_balance_keur: float,
    target_balance_keur: float,
    annual_debt_service_keur: float,
    fcf_after_ds_keur: float,
    contribution_rate: float = 0.3,
) -> float:
    """Calculate DSRA contribution from FCF.
    
    Args:
        current_balance_keur: Current DSRA balance
        target_balance_keur: Target DSRA balance
        annual_debt_service_keur: Annual debt service
        fcf_after_ds_keur: FCF after debt service
        contribution_rate: % of excess FCF to contribute (default 30%)
    
    Returns:
        Contribution amount in kEUR
    """
    gap = target_balance_keur - current_balance_keur
    
    if gap <= 0:
        return 0.0
    
    # Contribute 30% of available FCF
    available = max(0, fcf_after_ds_keur)
    contribution = min(available * contribution_rate, gap)
    
    return contribution


def reserve_account_balances(
    dsra_initial_keur: float,
    dsra_contributions: list[float],
    dsra_withdrawals: list[float],
) -> list[float]:
    """Calculate DSRA balance over time.
    
    Args:
        dsra_initial_keur: Initial DSRA funding
        dsra_contributions: List of contributions per period
        dsra_withdrawals: List of withdrawals per period
    
    Returns:
        List of DSRA balances per period
    """
    balances = []
    balance = dsra_initial_keur
    
    for contrib, withdraw in zip(dsra_contributions, dsra_withdrawals):
        balance = dsra_balance_update(balance, contrib, withdraw)
        balances.append(balance)
    
    return balances


def mra_funding(
    capacity_mw: float,
    mra_rate_per_mw: float = 5.0,
) -> float:
    """Calculate maintenance reserve account funding.
    
    Args:
        capacity_mw: Installed capacity in MW
        mra_rate_per_mw: Rate per MW in kEUR (default 5 kEUR/MW)
    
    Returns:
        MRA balance in kEUR
    """
    return capacity_mw * mra_rate_per_mw