"""domain/financing/ — Compatibility shim — V2-4.

Authoritative implementation moved to finco_core.debt.
Uses lazy __getattr__ delegation to avoid circular imports during
finco_core.debt initialization.
"""

__all__ = [
    "AmortizationResult",
    "DebtServiceResult",
    "senior_debt_amount",
    "standard_amortization",
    "annuity_payment",
    "balance_after_n_periods",
    "iterative_sculpt_debt",
    "IterativeSculptResult",
    "dscr_at_period",
    "average_dscr",
    "min_dscr",
    "sculpted_amortization",
    "dscr",
    "llcr",
    "plcr",
]


def __getattr__(name: str):
    import finco_core.debt as _debt
    try:
        return getattr(_debt, name)
    except AttributeError:
        raise AttributeError(f"module {__name__!r} has no attribute {name!r}")
