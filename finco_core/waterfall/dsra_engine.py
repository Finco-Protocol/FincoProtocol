"""DSRA Engine - Debt Service Reserve Account with equity funding.

Implements Blueprint S1-5 fix:
- DSRA is funded from EQUITY at Financial Close, not from operating CF
- Initial DSRA is part of the project funding structure
- Operating CF can contribute to DSRA top-up, but initial funding is from equity

Policy summary:
- DSRA target is derived from senior debt service.
- Initial funding is part of the project funding structure.
- Operating cash flow may top up a reserve if required.
"""
from dataclasses import dataclass


@dataclass(frozen=True)
class DSRAEngineResult:
    """Result of DSRA calculation for a period."""
    dsra_initial_keur: float         # Initial DSRA at FC (for first period only)
    dsra_contribution_keur: float    # Contribution this period
    dsra_withdrawal_keur: float      # Withdrawal this period (for DS payment)
    dsra_balance_start_keur: float   # Opening balance
    dsra_balance_end_keur: float     # Closing balance
    dsra_target_keur: float          # Target balance
    is_fully_funded: bool            # True if balance >= target

    @property
    def net_change_keur(self) -> float:
        """Net change in DSRA balance."""
        return self.dsra_contribution_keur - self.dsra_withdrawal_keur


def compute_initial_dsra(
    sculpted_payment_schedule: list[float],
    dsra_months: int = 6,
    periods_per_year: int = 2,
) -> float:
    """Compute initial DSRA balance at Financial Close.

    DSRA initial = dsra_months / 12 × annual_debt_service
    where annual_debt_service = sculpted_payment_schedule[0] × periods_per_year

    Args:
        sculpted_payment_schedule: First period payment from sculpting engine
        dsra_months: Number of months of DSRA (default 6)
        periods_per_year: Number of periods per year (2 for semi-annual)

    Returns:
        Initial DSRA balance in kEUR

    """
    if not sculpted_payment_schedule:
        return 0.0

    # First period payment × periods_per_year = annual debt service
    first_period_payment = sculpted_payment_schedule[0]
    annual_debt_service = first_period_payment * periods_per_year

    # DSRA = months/12 × annual
    dsra_initial = annual_debt_service * (dsra_months / 12)
    return dsra_initial


def compute_dsra_target(
    current_period_payment: float,
    dsra_months: int = 6,
    periods_per_year: int = 2,
) -> float:
    """Compute DSRA target balance for a period.

    The DSRA target = months × monthly debt service
    where monthly = period_payment / (12/periods_per_year)

    Args:
        current_period_payment: Current period debt service payment
        dsra_months: Number of months of DSRA (default 6)
        periods_per_year: Number of periods per year (2 for semi-annual)

    Returns:
        DSRA target balance in kEUR
    """
    # Periods per year = 2 (semi-annual), so months per period = 6
    # DSRA target = (dsra_months / 12) × annual_ds = (dsra_months/12) × (payment × periods_per_year)
    annual_ds = current_period_payment * periods_per_year
    dsra_target = annual_ds * (dsra_months / 12)
    return dsra_target


def dsra_top_up_from_fcf(
    current_balance: float,
    target_balance: float,
    fcf_after_ds_keur: float,
    top_up_rate: float = 0.5,
) -> float:
    """Calculate DSRA top-up contribution from operating FCF.

    Only contributes if:
    1. Current balance < target (underfunded)
    2. FCF after debt service is positive
    3. Contribution doesn't exceed available FCF × top_up_rate

    Args:
        current_balance: Current DSRA balance
        target_balance: Target DSRA balance
        fcf_after_ds_keur: FCF after debt service
        top_up_rate: % of excess FCF to contribute (default 50%)

    Returns:
        DSRA contribution amount in kEUR
    """
    gap = target_balance - current_balance
    if gap <= 0 or fcf_after_ds_keur <= 0:
        return 0.0

    # Contribute 50% of available FCF (or less if gap is smaller)
    available = max(0.0, fcf_after_ds_keur)
    contribution = min(available * top_up_rate, gap)
    return contribution


def dsra_withdrawal_for_payment(
    dsra_balance: float,
    payment_amount: float,
) -> float:
    """Calculate DSRA withdrawal for a debt service payment.

    DSRA is drawn when operating CF is insufficient for debt service.
    The withdrawal = amount needed beyond operating CF.

    Args:
        dsra_balance: Current DSRA balance
        payment_amount: Debt service payment needed

    Returns:
        Withdrawal amount (0 if balance is sufficient or no payment needed)
    """
    if payment_amount <= 0:
        return 0.0

    # If payment > available, withdraw from DSRA
    # This is called with fcf_after_ds as the available amount
    # and payment_amount as the debt service required
    # Note: actual withdrawal logic in the waterfall uses: payment - available
    return 0.0  # Placeholder - actual usage is in waterfall engine


def run_dsra_engine(
    period: int,
    dsra_balance_prior: float,
    sculpted_payment_schedule: list[float],
    fcf_after_ds_keur: float,
    is_first_period: bool = False,
    dsra_months: int = 6,
    periods_per_year: int = 2,
    equity_initial_funding: float | None = None,
) -> DSRAEngineResult:
    """Run DSRA engine for a single period.

    Args:
        period: Period index
        dsra_balance_prior: DSRA balance from prior period
        sculpted_payment_schedule: Payment schedule from sculpting engine
        fcf_after_ds_keur: FCF after debt service (available for DSRA top-up)
        is_first_period: True for period 0 (FC date) - initial funding
        dsra_months: DSRA months (default 6)
        periods_per_year: Periods per year (default 2 for semi-annual)
        equity_initial_funding: If provided, use this as initial funding (equity at FC)

    Returns:
        DSRAEngineResult with all DSRA movements

    Note:
        If equity_initial_funding is provided, it represents the equity contribution
        to fund DSRA at FC. This is the correct approach for v3.

        If equity_initial_funding is None, we compute initial DSRA from sculpted
        payment schedule (backward compatible).
    """
    # First period: compute initial DSRA
    if is_first_period:
        if equity_initial_funding is not None:
            initial_dsra = equity_initial_funding
        else:
            initial_dsra = compute_initial_dsra(
                sculpted_payment_schedule, dsra_months, periods_per_year
            )

        # Initial balance = equity funded
        opening_balance = initial_dsra

        # No contribution in first period (already funded via equity)
        contribution = 0.0

        # Target = same as initial (6 months)
        target = compute_dsra_target(
            sculpted_payment_schedule[0] if sculpted_payment_schedule else 0.0,
            dsra_months, periods_per_year
        )

    else:
        # Subsequent periods: balance from prior + potential top-up
        initial_dsra = 0.0  # Only relevant for first period
        opening_balance = dsra_balance_prior

        # Target = 6 months of current debt service
        current_payment = sculpted_payment_schedule[period] if period < len(sculpted_payment_schedule) else 0.0
        target = compute_dsra_target(current_payment, dsra_months, periods_per_year)

        # Contribution from operating FCF if underfunded
        contribution = dsra_top_up_from_fcf(
            current_balance=opening_balance,
            target_balance=target,
            fcf_after_ds_keur=fcf_after_ds_keur,
        )

    # Calculate closing balance
    closing_balance = opening_balance + contribution  # Withdrawal handled separately

    return DSRAEngineResult(
        dsra_initial_keur=initial_dsra,
        dsra_contribution_keur=contribution,
        dsra_withdrawal_keur=0.0,  # Set by caller
        dsra_balance_start_keur=opening_balance,
        dsra_balance_end_keur=closing_balance,
        dsra_target_keur=target,
        is_fully_funded=(closing_balance >= target),
    )


def dsra_schedule_simple(
    payment_schedule: list[float],
    initial_dsra_keur: float = 0.0,
    dsra_months: int = 6,
    periods_per_year: int = 2,
) -> list[float]:
    """Generate simple DSRA balance schedule.

    Simplified version for quick DSRA balance estimation.

    Args:
        payment_schedule: Payment schedule from sculpting
        initial_dsra_keur: Initial DSRA at FC (if funded from equity)
        dsra_months: DSRA months (default 6)
        periods_per_year: Periods per year (default 2 for semi-annual)

    Returns:
        List of DSRA balances per period
    """
    if not payment_schedule:
        return []

    balances = []
    balance = initial_dsra_keur if initial_dsra_keur > 0 else compute_initial_dsra(
        payment_schedule, dsra_months, periods_per_year
    )

    for period in range(len(payment_schedule)):
        payment = payment_schedule[period]
        target = compute_dsra_target(payment, dsra_months, periods_per_year)

        # If balance below target, top up (but no FCF here, so just track)
        if balance < target:
            # In real model, this would come from operating FCF
            pass

        balances.append(balance)

    return balances


__all__ = [
    "DSRAEngineResult",
    "compute_initial_dsra",
    "compute_dsra_target",
    "dsra_top_up_from_fcf",
    "run_dsra_engine",
    "dsra_schedule_simple",
]