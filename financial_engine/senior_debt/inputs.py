"""financial_engine.senior_debt.inputs — Immutable senior debt input contract."""
from __future__ import annotations

from dataclasses import dataclass
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from financial_engine.senior_debt.policy import SeniorDebtPolicy


@dataclass(frozen=True)
class PeriodRate:
    """Explicit annual interest rate applicable to one model period."""
    period_index: int
    annual_rate: float


@dataclass(frozen=True)
class PeriodPrincipal:
    """Explicit principal repayment in one model period (EXPLICIT_SCHEDULE mode)."""
    period_index: int
    principal_keur: float


@dataclass(frozen=True)
class PeriodDscrTarget:
    """Per-period DSCR ratio used in backward induction and sculpting.

    When supplied, the resolved ratio for this period is dt.target_dscr.
    Periods not present fall back to the scalar policy.target_dscr.
    """
    period_index: int
    target_dscr: float


@dataclass(frozen=True)
class PeriodDebtServiceAvailability:
    """Per-period debt-service availability fraction (debt_source_ref in reference methodologys).

    Scales allowed_debt_service[p] = max(0, CFADS[p] / DSCR[p]) * availability[p].
    Missing periods fall back to 1.0 (full availability).
    0.0 <= availability_fraction <= 1.0.
    """
    period_index: int
    availability_fraction: float


@dataclass(frozen=True)
class SeniorDebtInputs:
    """All senior debt inputs for a Phase 2C run.

    eligible_project_cost_keur          : gearing base for GEARING_CAP / COMBINED_MINIMUM
    initial_debt_guess_keur             : solver starting point (DSCR_SCULPTED / COMBINED_MINIMUM)
    period_rates                        : per-period annual rates; empty → use policy.annual_fixed_rate
    explicit_principal_schedule         : required for EXPLICIT_SCHEDULE; ignored otherwise
    opening_debt_balance_keur           : used for EXPLICIT_SCHEDULE; 0 otherwise
    period_dscr_targets                 : per-period DSCR ratios; empty → scalar policy.target_dscr for all
    period_debt_service_availability    : per-period availability fractions; empty → 1.0 for all
    """
    eligible_project_cost_keur: float
    initial_debt_guess_keur: float
    period_rates: tuple[PeriodRate, ...]
    explicit_principal_schedule: tuple[PeriodPrincipal, ...] | None
    opening_debt_balance_keur: float = 0.0
    period_dscr_targets: tuple[PeriodDscrTarget, ...] = ()
    period_debt_service_availability: tuple[PeriodDebtServiceAvailability, ...] = ()
