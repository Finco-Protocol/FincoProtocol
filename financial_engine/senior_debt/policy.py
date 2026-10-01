"""financial_engine.senior_debt.policy — Immutable senior debt policy contract.

Repayment method is derived from sizing_mode; it cannot be overridden, with ONE explicit,
typed exception (M-6):
  DSCR_SCULPTED sizing   → DSCR_SCULPTED repayment
  GEARING_CAP sizing     → LEVEL_PRINCIPAL repayment (DEFAULT)
                           or DSCR_SCULPTED repayment when the policy explicitly sets
                           gearing_cap_repayment_method = DSCR_SCULPTED (opt-in). The debt size is
                           still eligible_project_cost × maximum_gearing; it is never resized.
  COMBINED_MINIMUM sizing→ DSCR_SCULPTED repayment (never switches to level-principal
                            when gearing binds; sizing and amortisation are separate;
                            gearing_cap_repayment_method has no effect and must stay default)
  EXPLICIT_SCHEDULE sizing→ EXPLICIT repayment
"""
from __future__ import annotations

from dataclasses import dataclass
from enum import Enum


class SeniorDebtSizingMode(str, Enum):
    DSCR_SCULPTED = "DSCR_SCULPTED"
    GEARING_CAP = "GEARING_CAP"
    COMBINED_MINIMUM = "COMBINED_MINIMUM"
    EXPLICIT_SCHEDULE = "EXPLICIT_SCHEDULE"


class GearingCapRepaymentMethod(str, Enum):
    """Repayment method for GEARING_CAP sizing only (M-6).

    LEVEL_PRINCIPAL : straight-line principal over the repayment window (canonical default).
    DSCR_SCULPTED   : the gearing-sized balance is sculpted over the contractual tenor using the
                      canonical DSCR primitives. Debt size is NOT resized to DSCR capacity; a
                      balance the CFADS cannot repay fails closed (DSCR_SCULPTING_INFEASIBLE).
    """
    LEVEL_PRINCIPAL = "LEVEL_PRINCIPAL"
    DSCR_SCULPTED = "DSCR_SCULPTED"


class DayCountConvention(str, Enum):
    ACT_365 = "ACT_365"
    ACT_360 = "ACT_360"


@dataclass(frozen=True)
class SeniorDebtPolicy:
    """Immutable senior debt policy.

    sizing_mode                  : how debt is sized; repayment method is fixed per mode
    target_dscr                  : DSCR target used for sculpting (must be > 1.0)
    maximum_gearing              : fraction of eligible_project_cost; None = unconstrained
    annual_fixed_rate            : uniform annual interest rate; None = use period_rates
    periods_per_year             : model periods per year (2 = semi-annual)
    day_count_convention         : ACT_365 or ACT_360
    repayment_start_period_index : first period in which principal is repaid
    maturity_period_index        : last period in which principal can be repaid
    convergence_tolerance_keur   : absolute threshold; field converged when
                                   |Δ| ≤ convergence_tolerance_keur
    convergence_relative_tolerance: relative threshold; field converged when
                                   |Δ|/max(|a|,|b|,1) ≤ convergence_relative_tolerance
                                   Convergence requires every tracked field (debt size,
                                   opening, interest, principal, closing, CFADS, cash tax)
                                   to satisfy abs OR rel for every period.
    maximum_iterations           : iteration cap; non-convergence → MAX_ITERATIONS_REACHED
    permit_terminal_balloon      : if False, a non-zero closing balance at maturity is an error
    damping_alpha                : iteration damping factor in (0, 1]; 1.0 = no damping
    gearing_cap_repayment_method : GEARING_CAP sizing only. Default LEVEL_PRINCIPAL (unchanged
                                   canonical behaviour). DSCR_SCULPTED is an explicit opt-in.
                                   Any non-default value with another sizing_mode is invalid.
    """
    policy_id: str
    policy_version: str
    sizing_mode: SeniorDebtSizingMode
    target_dscr: float
    maximum_gearing: float | None
    annual_fixed_rate: float | None
    periods_per_year: int
    day_count_convention: DayCountConvention
    repayment_start_period_index: int
    maturity_period_index: int
    convergence_tolerance_keur: float
    convergence_relative_tolerance: float
    maximum_iterations: int
    permit_terminal_balloon: bool
    damping_alpha: float = 1.0
    gearing_cap_repayment_method: GearingCapRepaymentMethod = GearingCapRepaymentMethod.LEVEL_PRINCIPAL
