"""SHL (Shareholder Loan) engine - v3 with correct gross/net PIK handling.

Implements Blueprint S1-2 fix:
- PIK is computed on GROSS interest, not NET (after WHT)
- WHT is computed on cash interest paid, not on capitalized interest
- This prevents WHT from incorrectly inflating the SHL balance

Key insight from Generic Wind Reference calibration:
- WHT = 18% applies to CASH interest payments
- When interest is PIK'd (capitalized), there's no cash outflow → no WHT
- PIK amount = gross interest (shl_balance * rate), not net
- New balance = old balance + PIK (GROSS), not old balance + (net interest - paid)

v2 bug:
    pik = interest_net - interest_paid  # WRONG: net-based PIK
    new_balance = shl_balance + pik    # WRONG: would include WHT effect

v3 fix:
    pik = interest_full - interest_paid  # CORRECT: gross interest minus cash paid
    new_balance = shl_balance + pik     # CORRECT: gross PIK accumulates

Example for Generic Wind Reference (shl_balance=33,047, rate=7.93%/yr = 3.97%/period):
    interest_full = 33,047 * 0.0397 = 1,312 kEUR (gross)
    interest_net  = 1,312 * (1-0) = 1,312 kEUR (WHT=0% for Generic Wind Reference)

    If cf_after_senior_ds = 954 (Y1-H1):
      - interest_paid = min(954, 1312) = 954 (partial payment)
      - pik = 1312 - 954 = 358 (GROSS difference, capitalizes)
      - WHT = 0 (no cash interest payment triggers WHT)
      - new_balance = 33,047 + 358 = 33,405

vs v2 buggy:
      - pik = 1312 - 954 = 358... wait that looks same

The bug is more subtle - for methods where wht_rate > 0:
    v2: pik = interest_net - interest_paid  (wrong)
    v3: pik = interest_full - interest_paid (correct)

For WHT=0 (Generic Wind Reference), difference is 0.
For WHT>0 (other projects), difference is: (gross - net) = interest_full * wht_rate

Example with WHT=18%:
    interest_full = 1000
    interest_net = 820
    cf_available = 500

    v2 (buggy): interest_paid=500, pik = 820-500=320, new_balance += 320
    v3 (correct): interest_paid=500, pik = 1000-500=500, new_balance += 500

The 180 kEUR difference (500-320) is the WHT that was incorrectly PIK'd.
"""
from dataclasses import dataclass
from typing import Optional


@dataclass(frozen=True)
class SHLPeriodResult:
    """Result of SHL computation for one period.

    All amounts in kEUR.
    """
    interest_paid_keur: float      # Cash interest paid to investor (after WHT)
    interest_wht_keur: float      # WHT withheld and paid to tax authority
    principal_keur: float         # Principal repaid (reduces balance)
    pik_addition_keur: float      # PIK capitalization (increases balance)
    new_balance_keur: float       # Closing SHL balance

    @property
    def gross_interest_keur(self) -> float:
        """Gross interest before WHT."""
        return self.interest_paid_keur + self.interest_wht_keur

    @property
    def net_cash_outflow_keur(self) -> float:
        """Net cash outflow = interest_paid + principal (excludes WHT)."""
        return self.interest_paid_keur + self.principal_keur


def compute_shl_period_v3(
    shl_balance: float,
    shl_rate_per_period: float,
    cf_available: float,
    method: str,
    wht_rate: float = 0.0,
    pik_switch_triggered: bool = False,
    is_final_period: bool = False,
) -> SHLPeriodResult:
    """Compute SHL cash flows for one period — v3 with correct gross/net PIK.

    Key fix: PIK = gross_interest - cash_paid (NOT net_interest - cash_paid)
    WHT applies ONLY to cash interest payments, NOT to PIK'd interest.

    Args:
        shl_balance: Current SHL balance (kEUR)
        shl_rate_per_period: SHL rate per period (e.g., 0.03965 for 7.93% annual)
        cf_available: CF available for SHL after senior debt service (kEUR)
        method: "bullet" | "cash_sweep" | "pik" | "accrued" | "pik_then_sweep" | "partial_pay_sweep"
        wht_rate: WHT rate on cash interest (e.g., 0.18)
        pik_switch_triggered: True when PIK → sweep switch is triggered
        is_final_period: True for final SHL period (bullet principal due)

    Returns:
        SHLPeriodResult with all components
    """
    if shl_balance <= 0:
        return SHLPeriodResult(
            interest_paid_keur=0.0,
            interest_wht_keur=0.0,
            principal_keur=0.0,
            pik_addition_keur=0.0,
            new_balance_keur=0.0,
        )

    # Gross interest on current balance (BEFORE any payment)
    gross_interest = shl_balance * shl_rate_per_period
    # Net interest after WHT (what investor receives if fully paid)
    net_interest = gross_interest * (1 - wht_rate)

    # Determine interest paid (cash) and PIK (capitalized)
    if method == "bullet":
        # Interest paid if CF available, else PIK; principal at maturity
        interest_paid = min(max(0.0, cf_available), net_interest)
        # PIK = gross interest - cash paid (THIS IS THE KEY FIX)
        pik = gross_interest - interest_paid if interest_paid < net_interest else 0.0
        # WHT = on cash interest only (no WHT on PIK)
        interest_wht = interest_paid * (wht_rate / (1 - wht_rate)) if wht_rate > 0 and interest_paid > 0 else 0.0

        if is_final_period:
            principal = shl_balance
            new_balance = 0.0
        else:
            principal = 0.0
            new_balance = shl_balance + pik

        return SHLPeriodResult(
            interest_paid_keur=interest_paid,
            interest_wht_keur=interest_wht,
            principal_keur=principal,
            pik_addition_keur=pik,
            new_balance_keur=new_balance,
        )

    elif method == "cash_sweep":
        # Pay interest first, then principal from remaining CF
        available_cash = max(0.0, cf_available)
        interest_paid = min(net_interest, available_cash)
        remaining = max(0.0, cf_available - interest_paid)
        principal = min(remaining, shl_balance)
        # PIK = gross interest - cash paid
        pik = max(0.0, gross_interest - interest_paid)
        # WHT on cash interest paid
        interest_wht = interest_paid * (wht_rate / (1 - wht_rate)) if wht_rate > 0 and interest_paid > 0 else 0.0
        new_balance = max(0.0, shl_balance - principal + pik)

        return SHLPeriodResult(
            interest_paid_keur=interest_paid,
            interest_wht_keur=interest_wht,
            principal_keur=principal,
            pik_addition_keur=pik,
            new_balance_keur=new_balance,
        )

    elif method == "pik":
        # All interest PIK's (capitalizes), no cash outflow
        pik = gross_interest
        interest_paid = 0.0
        interest_wht = 0.0  # No cash payment → no WHT
        return SHLPeriodResult(
            interest_paid_keur=0.0,
            interest_wht_keur=0.0,
            principal_keur=0.0,
            pik_addition_keur=pik,
            new_balance_keur=shl_balance + pik,
        )

    elif method == "accrued":
        # Nothing paid or capitalized (liability for later)
        return SHLPeriodResult(
            interest_paid_keur=0.0,
            interest_wht_keur=0.0,
            principal_keur=0.0,
            pik_addition_keur=0.0,
            new_balance_keur=shl_balance,
        )

    elif method == "pik_then_sweep":
        if not pik_switch_triggered:
            # PIK phase: pay what you can, capitalize the rest (GROSS)
            interest_paid = min(max(0.0, cf_available), net_interest)
            # PIK = gross - cash_paid (NOT net - cash_paid)
            pik = gross_interest - interest_paid
            interest_wht = interest_paid * (wht_rate / (1 - wht_rate)) if wht_rate > 0 and interest_paid > 0 else 0.0
            return SHLPeriodResult(
                interest_paid_keur=interest_paid,
                interest_wht_keur=interest_wht,
                principal_keur=0.0,
                pik_addition_keur=pik,
                new_balance_keur=shl_balance + pik,
            )
        else:
            # SWEEP phase: pay full interest + principal from surplus.
            # Cap interest at available CF — shortfall is PIKed, not overpaid.
            interest_paid = min(net_interest, cf_available)
            pik = gross_interest - interest_paid  # shortfall beyond CF gets PIKed
            remaining = max(0.0, cf_available - interest_paid)
            principal = min(remaining, shl_balance)
            interest_wht = interest_paid * (wht_rate / (1 - wht_rate)) if wht_rate > 0 and interest_paid > 0 else 0.0
            new_balance = max(0.0, shl_balance - principal + pik)
            return SHLPeriodResult(
                interest_paid_keur=interest_paid,
                interest_wht_keur=interest_wht,
                principal_keur=principal,
                pik_addition_keur=pik,
                new_balance_keur=new_balance,
            )

    elif method == "partial_pay_sweep":
        # Every period: pay interest from available cash, PIK remainder, sweep residual.
        # No annual-interest threshold trigger. No PIK/SWITCH phase split.
        # Core partial-pay behavior: interest first, then sweep principal from remaining.
        available = max(0.0, cf_available)
        interest_paid = min(available, net_interest)
        remaining_after_interest = available - interest_paid
        # PIK = gross interest minus cash paid (unpaid interest capitalized)
        pik = gross_interest - interest_paid
        # Principal sweep = min(residual after interest, SHL balance + capitalized PIK)
        # Capped so closing balance never goes negative
        principal = min(remaining_after_interest, shl_balance + pik)
        new_balance = max(0.0, shl_balance + pik - principal)
        interest_wht = (
            interest_paid * (wht_rate / (1 - wht_rate))
            if wht_rate > 0 and interest_paid > 0
            else 0.0
        )
        return SHLPeriodResult(
            interest_paid_keur=interest_paid,
            interest_wht_keur=interest_wht,
            principal_keur=principal,
            pik_addition_keur=pik,
            new_balance_keur=new_balance,
        )

    else:
        raise ValueError(f"Unknown SHL method: {method}")


def shl_schedule_summary(
    initial_balance: float,
    rate_per_period: float,
    cf_schedule: list[float],
    method: str,
    wht_rate: float = 0.0,
    tenor_periods: int = 28,
) -> list[SHLPeriodResult]:
    """Generate full SHL schedule for project life.

    Args:
        initial_balance: Opening SHL balance (including IDC if any)
        rate_per_period: Interest rate per period
        cf_schedule: CF available for SHL per period
        method: SHL repayment method
        wht_rate: WHT rate
        tenor_periods: Number of periods to simulate

    Returns:
        List of SHLPeriodResult for each period
    """
    results = []
    balance = initial_balance

    for period in range(tenor_periods):
        cf = cf_schedule[period] if period < len(cf_schedule) else 0.0
        is_final = (period == tenor_periods - 1)

        result = compute_shl_period_v3(
            shl_balance=balance,
            shl_rate_per_period=rate_per_period,
            cf_available=cf,
            method=method,
            wht_rate=wht_rate,
            is_final_period=is_final,
        )

        results.append(result)
        balance = result.new_balance_keur

    return results


__all__ = [
    "SHLPeriodResult",
    "compute_shl_period_v3",
    "shl_schedule_summary",
]
