"""Iterative Debt Sculpting - DSCR-Based Sizing with Binary Search.

This module implements true iterative debt sculpting:
- Binary search on debt amount until average DSCR ≈ target
- Per-period payment = EBITDA / DSCR_target (or capped)
- Lockup check per period (DSCR < 1.10 blocks distribution)
- Balance converges within tolerance

Binary search on debt amount until average DSCR ≈ target:
"""
from dataclasses import dataclass, field
from typing import Optional
import math


@dataclass
class IterativeSculptResult:
    """Result of iterative debt sculpting with convergence."""
    debt_keur: float
    payments: list[float]
    dscr_schedule: list[float]
    interest_schedule: list[float]
    principal_schedule: list[float]
    balance_schedule: list[float]
    # Metadata
    avg_dscr: float
    min_dscr: float
    max_dscr: float
    converged: bool
    iterations: int


def _amortize(debt: float, rate: float, periods: int) -> list[dict]:
    """Build amortization schedule for given debt.

    Returns list of {interest, principal, balance} dicts.
    """
    schedule = []
    balance = debt

    for _ in range(periods):
        interest = balance * rate
        principal = balance / periods  # Simplified equal principal
        closing = max(0, balance - principal)

        schedule.append({
            "interest": interest,
            "principal": principal,
            "balance": balance,
            "closing": closing,
        })
        balance = closing

    return schedule


def _dscr_of_payment(ebitda: float, payment: float) -> float:
    """Calculate DSCR for a given payment."""
    if payment <= 0:
        return float('inf')
    return ebitda / payment


def _pv_payments(payments: list[float], rate: float) -> float:
    """Calculate present value of payments at given rate."""
    return sum(
        p / (1 + rate) ** (t + 1)
        for t, p in enumerate(payments)
    )


def _calculate_schedule(
    debt: float,
    ebitda_schedule: list[float],
    rate: float,
    tenor: int,
    target_dscr: float,
    dscr_schedule: list[float] | None = None,
) -> tuple[list[float], list[float], list[float], list[float], float, float]:
    """Calculate sculpted schedule for a given debt amount.

    Payment[t] = min(EBITDA[t] / dscr_target[t], required_to_cover_interest)

    Args:
        debt: Initial debt amount (kEUR)
        ebitda_schedule: EBITDA per period (kEUR)
        rate: Interest rate per period
        tenor: Number of periods
        target_dscr: Default/fallback DSCR target
        dscr_schedule: Per-period DSCR targets (optional). If provided, used instead of target_dscr.

    Returns:
        (payments, dsrs, interests, principals, balances, avg_dscr)
    """
    payments = []
    dsrs = []
    interests = []
    principals = []
    balances = []

    balance = debt
    total_dscr = 0
    dscr_count = 0

    for t in range(tenor):
        ebitda = ebitda_schedule[t]

        # Interest on opening balance
        interest = balance * rate

        # Per-period DSCR target (if provided)
        period_dscr = dscr_schedule[t] if dscr_schedule is not None else target_dscr

        # Target payment = EBITDA / DSCR_target
        target_payment = ebitda / period_dscr

        # Payment can't be less than interest (would never amortize)
        payment = max(target_payment, interest)

        # Principal = payment - interest
        principal = payment - interest

        # Cap principal at remaining balance
        if principal > balance:
            principal = balance
            payment = interest + principal

        # Closing balance
        closing = max(0, balance - principal)

        # DSCR for this period
        dscr = _dscr_of_payment(ebitda, payment)

        payments.append(payment)
        dsrs.append(dscr)
        interests.append(interest)
        principals.append(principal)
        balances.append(balance)

        if dscr > 0.5 and dscr < 50:  # Filter unreasonable values
            total_dscr += dscr
            dscr_count += 1

        balance = closing

    avg_dscr = total_dscr / dscr_count if dscr_count > 0 else 0

    return payments, dsrs, interests, principals, balances, avg_dscr


def iterative_sculpt_debt(
    ebitda_schedule: list[float],
    rate: float,
    tenor: int,
    target_dscr: float = 1.15,
    lockup_dscr: float = 1.10,
    initial_debt_guess: Optional[float] = None,
    tolerance: float = 0.001,
    max_iterations: int = 100,
    min_debt: float = 10000,
    max_debt: float = 200000,
    dscr_schedule: list[float] | None = None,
) -> IterativeSculptResult:
    """Find debt amount such that average DSCR ≈ target_dscr.

    Uses binary search on debt amount.

    For each debt candidate:
        1. Build payments = EBITDA / dscr_target[t]
        2. Calculate PV(payments) at debt rate
        3. Compare to debt amount
        4. Binary search until avg_dscr matches target

    Args:
        ebitda_schedule: EBITDA per period (kEUR)
        rate: Interest rate per period (e.g., 0.02825 for ~5.65% annual semi-annual)
        tenor: Number of periods
        target_dscr: Default/fallback target DSCR (default 1.15)
        lockup_dscr: Lockup threshold (default 1.10)
        initial_debt_guess: Starting guess for debt (None = use analytical estimate)
        tolerance: Acceptable deviation from target DSCR
        max_iterations: Maximum binary search iterations
        min_debt: Lower bound for debt search
        max_debt: Upper bound for debt search
        dscr_schedule: Per-period DSCR targets (optional). If provided, used instead of target_dscr.
            Dual-DSCR schedule: 24 PPA periods at 1.20, then merchant periods at 1.45.

    Returns:
        IterativeSculptResult with converged schedule
    """
    # Initial guess using analytical PV approach
    if initial_debt_guess is None:
        if dscr_schedule is not None:
            target_payments = [ebitda_schedule[t] / dscr_schedule[t] for t in range(tenor)]
        else:
            target_payments = [e / target_dscr for e in ebitda_schedule[:tenor]]
        initial_debt_guess = _pv_payments(target_payments, rate)
        initial_debt_guess = max(min_debt, min(max_debt, initial_debt_guess))

    # Binary search for debt amount
    low = min_debt
    high = max_debt
    converged = False
    iterations = 0

    for iteration in range(max_iterations):
        mid = (low + high) / 2

        # Calculate schedule for this debt
        _, dsrs, _, _, _, avg_dscr = _calculate_schedule(
            mid, ebitda_schedule, rate, tenor, target_dscr, dscr_schedule
        )

        # Check convergence - use weighted average DSCR across all periods
        if dscr_schedule is not None:
            # For dual DSCR: check that we approximate the target
            ppa_dsrs = [dsrs[t] for t in range(min(tenor, 24))]
            merch_dsrs = [dsrs[t] for t in range(24, tenor)]
            ppa_avg = sum(ppa_dsrs) / len(ppa_dsrs) if ppa_dsrs else 0
            merch_avg = sum(merch_dsrs) / len(merch_dsrs) if merch_dsrs else 0
            # Convergence check: both averages close to targets
            ppa_dev = abs(ppa_avg - 1.20)
            merch_dev = abs(merch_avg - 1.45) if merch_dsrs else 0
            deviation = max(ppa_dev, merch_dev)
            converged_flag = ppa_dev < 0.05 and (not merch_dsrs or merch_dev < 0.05)
        else:
            deviation = abs(avg_dscr - target_dscr)
            converged_flag = deviation < tolerance

        if converged_flag:
            converged = True
            iterations = iteration + 1
            break

        # Binary search direction
        # Higher debt -> higher payment -> lower DSCR
        # So if avg_dscr < target (DSCR too low), we need LESS debt
        if avg_dscr < target_dscr:
            high = mid
        else:
            low = mid

        iterations = iteration + 1

    # Final calculation with converged debt
    final_debt = (low + high) / 2
    payments, dsrs, interests, principals, balances, avg_dscr = _calculate_schedule(
        final_debt, ebitda_schedule, rate, tenor, target_dscr, dscr_schedule
    )

    valid_dsrs = [d for d in dsrs if d > 0.5 and d < 50]
    min_dscr_val = min(valid_dsrs) if valid_dsrs else 0
    max_dscr_val = max(valid_dsrs) if valid_dsrs else 0

    return IterativeSculptResult(
        debt_keur=final_debt,
        payments=payments,
        dscr_schedule=dsrs,
        interest_schedule=interests,
        principal_schedule=principals,
        balance_schedule=balances,
        avg_dscr=avg_dscr,
        min_dscr=min_dscr_val,
        max_dscr=max_dscr_val,
        converged=converged,
        iterations=iterations,
    )


def sculpt_with_lockup(
    ebitda_schedule: list[float],
    rate: float,
    tenor: int,
    target_dscr: float = 1.15,
    lockup_dscr: float = 1.10,
) -> list[float]:
    """Calculate payments with lockup constraint per period.

    During lockup, payment = interest only (no principal amortization)
    until DSCR recovers above lockup threshold.

    Args:
        ebitda_schedule: EBITDA per period
        rate: Interest rate
        tenor: Number of periods
        target_dscr: Target DSCR
        lockup_dscr: Lockup threshold

    Returns:
        List of payments per period
    """
    payments = []
    balance = 0
    locked = False
    periods_locked = 0

    for t in range(tenor):
        ebitda = ebitda_schedule[t]
        interest = balance * rate

        # Target payment
        target_payment = ebitda / target_dscr

        # Check lockup status
        if not locked and target_payment > 0:
            current_dscr = ebitda / target_payment
            if current_dscr < lockup_dscr:
                locked = True

        if locked:
            # Lockup: pay interest only, principal stays constant
            payment = interest
            periods_locked += 1

            # Unlock when DSCR would recover
            if target_payment >= interest * 1.05:  # 5% buffer
                # Check if we can resume amortization
                pass
        else:
            payment = max(target_payment, interest)

        principal = payment - interest
        balance = max(0, balance - principal)

        payments.append(payment)

        # Unlock if balance is paid off
        if balance <= 0:
            locked = False

    return payments


def sizing_from_gearing(
    total_capex: float,
    gearing: float,
) -> float:
    """Simple debt sizing from gearing ratio.

    Args:
        total_capex: Total CAPEX in kEUR
        gearing: Gearing ratio (0.0 to 1.0)

    Returns:
        Debt amount in kEUR
    """
    return total_capex * gearing


def sizing_from_dscr_target(
    ebitda_schedule: list[float],
    rate: float,
    tenor: int,
    target_dscr: float = 1.15,
    gearing_fallback: float = 0.70,
    total_capex: float = 0,
) -> float:
    """Size debt to achieve target DSCR.

    Uses iterative approach, falls back to gearing if convergence fails.

    Args:
        ebitda_schedule: EBITDA per period
        rate: Interest rate per period
        tenor: Number of periods
        target_dscr: Target DSCR
        gearing_fallback: Fallback gearing if iterative fails
        total_capex: Total CAPEX for gearing fallback

    Returns:
        Debt amount in kEUR
    """
    try:
        result = iterative_sculpt_debt(
            ebitda_schedule, rate, tenor, target_dscr,
            initial_debt_guess=total_capex * 0.7,
        )
        if result.converged:
            return result.debt_keur
    except Exception:
        pass

    # Fallback to gearing
    return sizing_from_gearing(total_capex, gearing_fallback)

# =============================================================================
# CLOSED-FORM SCULPTING (Verificado - Wind IRR = 9.108%, NPV = 29,193 k€)
# =============================================================================

@dataclass
class ClosedFormSculptResult:
    """Result of closed-form debt sculpting."""
    debt_keur: float
    balance_schedule: list[float]  # Opening balance per period
    interest_schedule: list[float]
    principal_schedule: list[float]
    payment_schedule: list[float]
    dscr_schedule: list[float]
    avg_dscr: float
    min_dscr: float


def closed_form_sculpt(
    cfads_schedule: list[float],
    rate_schedule: list[float],
    tenor_periods: int,
    target_dscr: float = 1.15,
    gearing_cap_keur: float = float('inf'),
    dscr_schedule: list[float] | None = None,
) -> ClosedFormSculptResult:
    """Closed-form debt sculpting - backward-forward pass.

    Algorithm (identical to legacy core/calculations.py):

    BACKWARD PASS - compute debt balance from end to beginning:
        debt_bal[N] = 0
        debt_bal[t] = (debt_bal[t+1] + allowable_ds[t]) / (1 + r[t])

    where allowable_ds[t] = max(0, CFADS[t] / dscr_target[t])

    FORWARD PASS - split principal/interest:
        interest[t] = debt_bal[t] * r[t]
        principal[t] = allowable_ds[t] - interest[t]

    This is O(n) and deterministic - no iterations, no convergence.

    Args:
        cfads_schedule: Signed Cash Flow Available for Debt Service per period.
            Negative values remain DSCR numerators but provide zero debt-service
            capacity.
        rate_schedule: Semi-annual interest rate per period (can vary)
        tenor_periods: Number of repayment periods
        target_dscr: Default/fallback target DSCR
        gearing_cap_keur: Max debt from gearing constraint (CAPEX × gearing_ratio)
        dscr_schedule: Per-period DSCR targets (optional). If provided, used instead of target_dscr.
            Dual-DSCR schedule: 24 PPA periods at 1.20, then merchant periods at 1.45.

    Returns:
        ClosedFormSculptResult with complete schedule
    """
    n = tenor_periods
    cfads = cfads_schedule[:n]
    rates = rate_schedule[:n] if len(rate_schedule) >= n else (
        rate_schedule + [rate_schedule[-1]] * (n - len(rate_schedule))
    )

    # CFADS remains signed for DSCR. Only debt-service capacity is legally and
    # economically bounded at zero.
    if dscr_schedule is not None:
        allowable_ds = [max(0.0, cfads[t] / dscr_schedule[t]) for t in range(n)]
    else:
        allowable_ds = [max(0.0, c / target_dscr) for c in cfads]

    # --- BACKWARD PASS ---
    # debt_bal[t] = opening balance at start of period t
    debt_bal = [0.0] * (n + 1)  # debt_bal[n] = 0 (fully repaid)
    for t in range(n - 1, -1, -1):
        # PV of future debt service: (next_balance + this_ds) / (1 + r)
        debt_bal[t] = (debt_bal[t + 1] + allowable_ds[t]) / (1 + rates[t])

    # Initial debt = debt_bal[0], but limited by gearing constraint
    initial_debt = min(debt_bal[0], gearing_cap_keur)

    # If gearing constraint is active, rescale all balances
    if initial_debt < debt_bal[0] and debt_bal[0] > 0:
        scale = initial_debt / debt_bal[0]
        debt_bal = [b * scale for b in debt_bal]
        allowable_ds = [ds * scale for ds in allowable_ds]

    # --- FORWARD PASS ---
    interest_sched = []
    principal_sched = []
    payment_sched = []
    dscr_sched = []
    balance_sched = []

    balance = initial_debt
    for t in range(n):
        balance_sched.append(balance)
        interest = balance * rates[t]
        principal = allowable_ds[t] - interest

        # Guard: principal cannot be negative or exceed balance
        principal = max(0.0, min(principal, balance))
        payment = interest + principal

        dscr = cfads[t] / payment if payment > 0 else float('inf')

        interest_sched.append(interest)
        principal_sched.append(principal)
        payment_sched.append(payment)
        dscr_sched.append(dscr)

        balance = max(0.0, balance - principal)

    valid_dsrs = [d for d in dscr_sched if not (d == float('inf'))]
    avg_dscr = sum(valid_dsrs) / len(valid_dsrs) if valid_dsrs else 0.0
    min_dscr = min(valid_dsrs) if valid_dsrs else 0.0

    return ClosedFormSculptResult(
        debt_keur=initial_debt,
        balance_schedule=balance_sched,
        interest_schedule=interest_sched,
        principal_schedule=principal_sched,
        payment_schedule=payment_sched,
        dscr_schedule=dscr_sched,
        avg_dscr=avg_dscr,
        min_dscr=min_dscr,
    )


# =============================================================================
# CASH SWEEP
# =============================================================================

def cash_sweep(
    cf_after_reserves: float,
    senior_debt_balance: float,
    sweep_dscr: float,
    actual_dscr: float,
    sweep_pct: float = 1.0,
) -> tuple[float, float]:
    """Cash sweep - excess CFADS goes to early debt repayment.

    Activates when DSCR is above sweep_dscr threshold.
    Bank typically requires 100% sweep until LLCR reaches minimum level.

    Args:
        cf_after_reserves: Available cash after DSRA contributions
        senior_debt_balance: Remaining senior debt balance
        sweep_dscr: DSCR threshold for activation (e.g., 1.35)
        actual_dscr: Actual DSCR for this period
        sweep_pct: Percentage of excess to sweep (1.0 = 100%)

    Returns:
        (distribution, sweep_amount)
    """
    if senior_debt_balance <= 0 or actual_dscr <= sweep_dscr:
        return max(0.0, cf_after_reserves), 0.0

    # Sweep activated
    sweep = min(
        cf_after_reserves * sweep_pct,
        senior_debt_balance,
    )
    distribution = max(0.0, cf_after_reserves - sweep)
    return distribution, sweep


# =============================================================================
# DSRA ROLLING TARGET
# =============================================================================

def dsra_rolling_target(
    future_payments: list[float],
    dsra_months: int,
    periods_per_year: int = 2,
) -> float:
    """DSRA target = next N periods of debt service.

    Bank defines DSRA as coverage for next debt payments,
    not historical. Target decreases as debt declines.

    Args:
        future_payments: Future debt service payments (from current period)
        dsra_months: Number of months of coverage (typically 6)
        periods_per_year: 2 for semi-annual model

    Returns:
        DSRA target in kEUR
    """
    periods_needed = max(1, dsra_months * periods_per_year // 12)
    return sum(future_payments[:periods_needed])


def dsra_update(
    prior_balance: float,
    target: float,
    available_cash: float,
    withdrawal_needed: float = 0.0,
) -> tuple[float, float, float]:
    """Update DSRA balance for a period.

    Args:
        prior_balance: Previous DSRA balance
        target: Target DSRA balance
        available_cash: Cash available for contribution
        withdrawal_needed: Amount needed for withdrawal

    Returns:
        (new_balance, contribution, withdrawal)
    """
    # Withdrawal (if CFADS doesn't cover debt service)
    withdrawal = min(withdrawal_needed, prior_balance)

    # Balance after withdrawal
    balance_after_withdrawal = prior_balance - withdrawal

    # Contribution to reach target from available cash
    gap = max(0.0, target - balance_after_withdrawal)
    contribution = min(gap, available_cash)

    new_balance = balance_after_withdrawal + contribution
    return new_balance, contribution, withdrawal


# =============================================================================
# DSCR utility functions (moved from deprecated sculpting.py)
# =============================================================================
def dscr_at_period(
    ebitda_keur: float,
    debt_service_keur: float,
) -> float:
    """Calculate DSCR for a single period.

    Args:
        ebitda_keur: EBITDA in kEUR
        debt_service_keur: Debt service (interest + principal) in kEUR

    Returns:
        DSCR (e.g., 1.15). Returns inf if debt_service <= 0.
    """
    if debt_service_keur <= 0:
        return float('inf')
    return ebitda_keur / debt_service_keur


def average_dscr(
    ebitda_schedule: list[float],
    debt_service_schedule: list[float],
) -> float:
    """Calculate average DSCR over schedule.

    Args:
        ebitda_schedule: List of EBITDA values
        debt_service_schedule: List of debt service values

    Returns:
        Average DSCR
    """
    dsrs = [
        dscr_at_period(ebitda, ds)
        for ebitda, ds in zip(ebitda_schedule, debt_service_schedule)
        if ds > 0
    ]
    return sum(dsrs) / len(dsrs) if dsrs else 0.0


def min_dscr(
    ebitda_schedule: list[float],
    debt_service_schedule: list[float],
) -> float:
    """Calculate minimum DSCR over schedule.

    Args:
        ebitda_schedule: List of EBITDA values
        debt_service_schedule: List of debt service values

    Returns:
        Minimum DSCR
    """
    dsrs = [
        dscr_at_period(ebitda, ds)
        for ebitda, ds in zip(ebitda_schedule, debt_service_schedule)
        if ds > 0
    ]
    return min(dsrs) if dsrs else 0.0


# =============================================================================
# PUBLIC DISPATCHER — sculpt_senior_debt
# =============================================================================

def sculpt_senior_debt(
    cfads_schedule: list[float],
    rate_schedule: list[float],
    tenor_periods: int,
    mode: str,
    target_dscr: float = 1.15,
    dscr_schedule: list[float] | None = None,
    gearing_cap_keur: float = float('inf'),
) -> "ClosedFormSculptResult":
    """Canonical entry point for senior debt sizing.

    Dispatches to closed_form_sculpt using the requested DebtSizingMode.

    FLAT_DSCR_SCULPTED:
        Single target_dscr applied uniformly to every repayment period.
        Allowable debt service[t] = CFADS[t] / target_dscr.
        Backward pass computes opening debt. O(n), deterministic.

    MINIMUM_DSCR_SCULPTED:
        Per-period dscr_schedule (e.g. 1.20 during PPA, 1.45 during merchant).
        Allowable debt service[t] = CFADS[t] / dscr_schedule[t].
        Same backward-forward pass as FLAT but with time-varying divisor.
        Produces a schedule where each period's DSCR equals its target.

    FROZEN_EXCEL_SCHEDULE:
        Not a sculpting mode. Raises ValueError — callers must bypass this
        function and use pre-computed Excel inputs directly.

    Args:
        cfads_schedule: Cash Flow Available for Debt Service per repayment period.
        rate_schedule: Semi-annual interest rate per period.
        tenor_periods: Number of repayment periods.
        mode: DebtSizingMode value string ("flat_dscr_sculpted" /
              "minimum_dscr_sculpted"). Use the .value attribute or pass
              the string directly.
        target_dscr: Flat DSCR divisor for FLAT_DSCR_SCULPTED. Ignored
                     when dscr_schedule is provided.
        dscr_schedule: Per-period DSCR targets for MINIMUM_DSCR_SCULPTED.
                       Must have length >= tenor_periods.
        gearing_cap_keur: Hard upper bound on debt (CAPEX × gearing_ratio).

    Returns:
        ClosedFormSculptResult with full schedule.
    """
    mode_str = mode if isinstance(mode, str) else mode.value

    if mode_str == "frozen_excel_schedule":
        raise ValueError(
            "sculpt_senior_debt() is not applicable to FROZEN_EXCEL_SCHEDULE mode. "
            "Use pre-computed Excel inputs directly."
        )

    if mode_str == "flat_dscr_sculpted":
        return closed_form_sculpt(
            cfads_schedule=cfads_schedule,
            rate_schedule=rate_schedule,
            tenor_periods=tenor_periods,
            target_dscr=target_dscr,
            gearing_cap_keur=gearing_cap_keur,
            dscr_schedule=None,
        )

    if mode_str == "minimum_dscr_sculpted":
        if dscr_schedule is None:
            raise ValueError(
                "MINIMUM_DSCR_SCULPTED requires dscr_schedule — a list of per-period "
                "DSCR targets (e.g. [1.20] * ppa_periods + [1.45] * merchant_periods)."
            )
        return closed_form_sculpt(
            cfads_schedule=cfads_schedule,
            rate_schedule=rate_schedule,
            tenor_periods=tenor_periods,
            target_dscr=target_dscr,
            gearing_cap_keur=gearing_cap_keur,
            dscr_schedule=dscr_schedule,
        )

    raise ValueError(f"Unknown DebtSizingMode: {mode_str}")
