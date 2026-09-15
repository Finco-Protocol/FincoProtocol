"""financial_engine.senior_debt.models — Immutable result types for Phase 2C."""
from __future__ import annotations

from dataclasses import dataclass


class SeniorDebtNonConvergenceError(Exception):
    "Raised to signal a non-authoritative senior debt result."


@dataclass(frozen=True)
class SolverDiagnostics:
    """Fixed-point solver convergence diagnostics.

    termination_reason values:
      CONVERGED                  : every tracked field (debt_size, opening, interest,
                                   principal, closing, CFADS, cash_tax) satisfies
                                   |Δ| ≤ convergence_tolerance_keur  OR
                                   |Δ|/max(|a|,|b|,1) ≤ convergence_relative_tolerance
                                   for all periods; self-consistency finalisation passed.
      MAX_ITERATIONS_REACHED     : iteration cap hit before convergence
      INVALID_INPUT              : input validation failure
      NO_DEBT_CAPACITY           : zero sculpted capacity (CFADS too low)
      TERMINAL_BALANCE_NOT_ALLOWED : residual terminal balance and balloon prohibited
      INPUT_SOURCE_BLOCKED       : baseline blocked (opening-loss unresolved)
    """
    converged: bool
    iteration_count: int
    initial_debt_guess_keur: float
    final_debt_size_keur: float
    maximum_absolute_difference_keur: float
    maximum_relative_difference: float
    binding_constraint: str | None  # "DSCR", "GEARING", "BOTH", or None
    termination_reason: str
    is_authoritative: bool = True
    """True only when termination_reason == CONVERGED. Downstream code must reject non-authoritative results."""
    dscr_debt_capacity_keur: float | None = None
    gearing_debt_capacity_keur: float | None = None


@dataclass(frozen=True)
class SeniorDebtSchedules:
    """Per-period senior debt schedules (all operating periods).

    senior_dscr : None where debt service is zero (avoids division by zero).
    debt_size_keur : final sized/solved opening debt balance at COD.
    binding_constraint : "DSCR", "GEARING", "BOTH", or None.
    """
    period_indices: tuple[int, ...]
    senior_debt_opening_keur: tuple[float, ...]
    senior_interest_keur: tuple[float, ...]
    senior_principal_keur: tuple[float, ...]
    senior_debt_service_keur: tuple[float, ...]
    senior_debt_closing_keur: tuple[float, ...]
    senior_dscr: tuple[float | None, ...]
    debt_size_keur: float
    binding_constraint: str | None
    diagnostics: SolverDiagnostics
