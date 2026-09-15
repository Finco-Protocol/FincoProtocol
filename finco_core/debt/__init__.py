"""finco_core.debt — Senior debt engine.

V2-4: Authoritative. finco_core.debt.* are compatibility shims.

Covers: senior debt schedule, DSCR sculpting, covenant engine, debt sizing,
amortisation schedule.
"""
from finco_core.debt.schedule import (
    AmortizationResult,
    DebtServiceResult,
    senior_debt_amount,
    standard_amortization,
    annuity_payment,
    balance_after_n_periods,
    sculpted_amortization,
)
from finco_core.debt.sculpting_iterative import (
    IterativeSculptResult,
    ClosedFormSculptResult,
    iterative_sculpt_debt,
    closed_form_sculpt,
    sculpt_senior_debt,
    dsra_rolling_target,
    dsra_update,
    cash_sweep,
    dscr_at_period,
    average_dscr,
    min_dscr,
)
from finco_core.debt.covenants import dscr, llcr, plcr

__all__ = [
    # Schedule
    "AmortizationResult",
    "DebtServiceResult",
    "senior_debt_amount",
    "standard_amortization",
    "annuity_payment",
    "balance_after_n_periods",
    "sculpted_amortization",
    # Sculpting
    "IterativeSculptResult",
    "ClosedFormSculptResult",
    "iterative_sculpt_debt",
    "closed_form_sculpt",
    "sculpt_senior_debt",
    "dsra_rolling_target",
    "dsra_update",
    "cash_sweep",
    # DSCR utilities
    "dscr_at_period",
    "average_dscr",
    "min_dscr",
    # Covenants
    "dscr",
    "llcr",
    "plcr",
]
