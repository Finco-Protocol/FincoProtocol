"""financial_engine.dsra — Canonical clean CASH_DSRA reserve roll-forward.

PR-3: implements P1-1 (DSRA_NOT_IMPLEMENTED_IN_CLEAN_ENGINE).

Public API:
    CashDsraInput     — input contract
    CashDsraPeriodResult — per-period result
    CashDsraSchedules — aggregate schedule
    run_cash_dsra_model — canonical roll-forward function
"""
from financial_engine.dsra.contracts import (
    CashDsraInput,
    CashDsraPeriodResult,
    CashDsraSchedules,
)
from financial_engine.dsra.model import run_cash_dsra_model

__all__ = [
    "CashDsraInput",
    "CashDsraPeriodResult",
    "CashDsraSchedules",
    "run_cash_dsra_model",
]
