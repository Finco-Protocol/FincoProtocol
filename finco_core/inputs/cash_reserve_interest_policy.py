"""Canonical typed upstream input contract for cash / reserve interest income.

UNRESOLVED authority fails closed — yields 0.0 for all periods until a project
can prove eligible-account identity and deposit rate from source.

Causal chain:
    eligible_balance × annual_rate × day_fraction
        → financing_income_keur (below EBITDA — EBITDA is unmodified)
        → added to taxable income: TI = EBITDA + financing_income - tax_dep - deductible_interest
        → CIT increases
        → CFADS = EBITDA + financing_income - cash_tax

No project-code dispatch. No workbook-vector replay. No output-calibration.
"""

from __future__ import annotations

import math
import numbers
from dataclasses import dataclass
from enum import Enum


class CashReserveInterestAuthority(str, Enum):
    """Authority level for the cash/reserve interest policy.

    UNRESOLVED: Account identity or rate not provable from available source.
                Fails closed — interest income = 0.0 for all periods.
    GENERIC_FINCO_POLICY: Generic Finco deposit rate applied to a typed
                          eligible balance. Rate must be explicitly set.
    SOURCE_PROVEN: Rate and eligible-account identity both traceable to a
                   project source document. All conditions in §5 are met.
    """
    UNRESOLVED = "UNRESOLVED"
    GENERIC_FINCO_POLICY = "GENERIC_FINCO_POLICY"
    SOURCE_PROVEN = "SOURCE_PROVEN"


class EligibilityStatus(str, Enum):
    """Whether a specific account is eligible for reserve interest accrual.

    ELIGIBLE: Account is confirmed to earn cash/reserve interest.
    INELIGIBLE: Account is confirmed not to earn interest (e.g. operating account).
    UNRESOLVED: Account's eligibility is not yet provable from source.
                Not accepted for SOURCE_PROVEN or GENERIC_FINCO_POLICY — every
                account modeled by the policy must be classified explicitly.
    """
    ELIGIBLE = "ELIGIBLE"
    INELIGIBLE = "INELIGIBLE"
    UNRESOLVED = "UNRESOLVED"


class DayCountConvention(str, Enum):
    ACTUAL_365 = "actual_365"
    ACTUAL_360 = "actual_360"


class BalanceConvention(str, Enum):
    OPENING = "opening"
    CLOSING = "closing"
    AVERAGE = "average"


def _validate_real_finite(value: object, name: str) -> None:
    """Raise ValueError if value is not a real, finite, non-bool number."""
    if isinstance(value, bool):
        raise ValueError(
            f"CashReserveInterestPolicy: {name} must be numeric, not bool"
        )
    if not isinstance(value, numbers.Real):
        raise ValueError(
            f"CashReserveInterestPolicy: {name} must be a real number, "
            f"got {type(value).__name__!r}"
        )
    if not math.isfinite(float(value)):
        raise ValueError(
            f"CashReserveInterestPolicy: {name} must be finite, got {value!r}"
        )


@dataclass(frozen=True)
class CashReserveInterestPolicy:
    """Typed upstream input contract for cash and reserve account interest income.

    When authority is UNRESOLVED, compute() returns 0.0 regardless of other fields.
    When authority is GENERIC_FINCO_POLICY or SOURCE_PROVEN:
    - annual_rate must be a real finite float in [0.0, 1.0].
    - Both eligible_unrestricted_cash and eligible_dsra must be explicitly
      classified as ELIGIBLE or INELIGIBLE — UNRESOLVED is not accepted.
    - At least one account must be ELIGIBLE.

    Negative cash/reserve balances passed to compute_period_income_keur are floored
    to 0.0 for deposit-interest purposes (a negative balance cannot earn interest).
    Non-finite balances or day_fraction values raise ValueError.
    Negative day_fraction raises ValueError. Values > 1.0 are accepted (periods
    longer than one year, e.g. construction stubs that span >365 days).

    Fields:
        authority: Provenance level. UNRESOLVED → fails closed.
        eligible_unrestricted_cash: Whether the unrestricted cash account accrues interest.
        eligible_dsra: Whether the DSRA accrues interest.
        annual_rate: Deposit rate (e.g. 0.01 for 1%). Required when authority != UNRESOLVED.
        balance_convention: Which balance to use for the accrual base.
        day_count_convention: Day-count for computing the period fraction.
        enabled: Master switch. If False, always yields 0.0.
    """
    authority: CashReserveInterestAuthority
    eligible_unrestricted_cash: EligibilityStatus = EligibilityStatus.UNRESOLVED
    eligible_dsra: EligibilityStatus = EligibilityStatus.UNRESOLVED
    annual_rate: float | None = None
    balance_convention: BalanceConvention = BalanceConvention.OPENING
    day_count_convention: DayCountConvention = DayCountConvention.ACTUAL_365
    enabled: bool = True

    def __post_init__(self) -> None:
        if self.authority in (
            CashReserveInterestAuthority.SOURCE_PROVEN,
            CashReserveInterestAuthority.GENERIC_FINCO_POLICY,
        ):
            # Rate validation
            if self.annual_rate is None:
                raise ValueError(
                    f"CashReserveInterestPolicy: annual_rate is required when "
                    f"authority={self.authority.value}"
                )
            _validate_real_finite(self.annual_rate, "annual_rate")
            if self.annual_rate < 0.0 or self.annual_rate > 1.0:
                raise ValueError(
                    f"CashReserveInterestPolicy: annual_rate economically invalid: "
                    f"{self.annual_rate!r}. Must be in [0.0, 1.0]."
                )

            # Eligibility: both accounts must be explicitly classified — UNRESOLVED
            # is not accepted for non-UNRESOLVED authority. Every modeled account
            # must be stated as ELIGIBLE or INELIGIBLE.
            if self.eligible_unrestricted_cash == EligibilityStatus.UNRESOLVED:
                raise ValueError(
                    f"CashReserveInterestPolicy: authority={self.authority.value} "
                    f"requires eligible_unrestricted_cash to be ELIGIBLE or INELIGIBLE, "
                    f"not UNRESOLVED. Classify the account or downgrade authority."
                )
            if self.eligible_dsra == EligibilityStatus.UNRESOLVED:
                raise ValueError(
                    f"CashReserveInterestPolicy: authority={self.authority.value} "
                    f"requires eligible_dsra to be ELIGIBLE or INELIGIBLE, "
                    f"not UNRESOLVED. Classify the account or downgrade authority."
                )

            # At least one ELIGIBLE account required for enabled income policy.
            if (
                self.eligible_unrestricted_cash != EligibilityStatus.ELIGIBLE
                and self.eligible_dsra != EligibilityStatus.ELIGIBLE
            ):
                raise ValueError(
                    f"CashReserveInterestPolicy: authority={self.authority.value} "
                    f"requires at least one ELIGIBLE account; "
                    f"unrestricted_cash={self.eligible_unrestricted_cash.value}, "
                    f"dsra={self.eligible_dsra.value}"
                )

    def compute_period_income_keur(
        self,
        *,
        unrestricted_cash_balance_keur: float,
        dsra_balance_keur: float,
        day_fraction: float,
    ) -> float:
        """Compute interest income for one period.

        Fails closed when:
        - enabled is False
        - authority is UNRESOLVED
        - annual_rate is None

        Non-finite balance or day_fraction values raise ValueError.
        Negative finite balances floor to 0.0 (documented behavior — a negative
        balance cannot earn deposit interest). Negative day_fraction raises.
        day_fraction > 1.0 is accepted (construction period stubs > 1 year).

        Args:
            unrestricted_cash_balance_keur: Opening/closing/average unrestricted cash.
            dsra_balance_keur: Opening/closing/average DSRA balance.
            day_fraction: Period length as fraction of a year (e.g. 0.5 for semi-annual).

        Returns:
            Interest income in kEUR. Never negative.
        """
        # Validate inputs — non-finite values must raise, not silently produce 0.0.
        for val, name in (
            (unrestricted_cash_balance_keur, "unrestricted_cash_balance_keur"),
            (dsra_balance_keur, "dsra_balance_keur"),
            (day_fraction, "day_fraction"),
        ):
            if isinstance(val, bool):
                raise ValueError(
                    f"compute_period_income_keur: {name} must be numeric, not bool"
                )
            if not isinstance(val, numbers.Real):
                raise ValueError(
                    f"compute_period_income_keur: {name} must be a real number"
                )
            if not math.isfinite(float(val)):
                raise ValueError(
                    f"compute_period_income_keur: {name} must be finite, got {val!r}"
                )
        if day_fraction < 0.0:
            raise ValueError(
                f"compute_period_income_keur: day_fraction must be non-negative, "
                f"got {day_fraction!r}"
            )

        if not self.enabled:
            return 0.0
        if self.authority == CashReserveInterestAuthority.UNRESOLVED:
            return 0.0
        if self.annual_rate is None:
            return 0.0

        eligible_balance = 0.0
        if self.eligible_unrestricted_cash == EligibilityStatus.ELIGIBLE:
            # Negative balances floor to 0.0 — deposit accounts cannot earn on overdraft.
            eligible_balance += max(0.0, unrestricted_cash_balance_keur)
        if self.eligible_dsra == EligibilityStatus.ELIGIBLE:
            eligible_balance += max(0.0, dsra_balance_keur)

        return max(0.0, eligible_balance * self.annual_rate * day_fraction)


# Canonical default: all projects start UNRESOLVED — fails closed.
UNRESOLVED_POLICY = CashReserveInterestPolicy(
    authority=CashReserveInterestAuthority.UNRESOLVED,
    eligible_unrestricted_cash=EligibilityStatus.UNRESOLVED,
    eligible_dsra=EligibilityStatus.UNRESOLVED,
    annual_rate=None,
    enabled=True,
)
