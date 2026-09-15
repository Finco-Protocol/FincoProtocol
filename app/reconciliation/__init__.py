"""Reconciliation / audit export helpers.

Provides structured table data for Excel disclosure sheets:
- Debt schedule reconciliation
- Project cashflow bridge
- Equity cashflow bridge

All functions take a DemoResult (or waterfall WaterfallResult) and return
list-of-dicts row tables suitable for DataFrame construction.
"""
from app.reconciliation.debt import build_debt_schedule_rows
from app.reconciliation.project_cashflow import build_project_cf_rows
from app.reconciliation.equity_cashflow import build_equity_cf_rows

__all__ = [
    "build_debt_schedule_rows",
    "build_project_cf_rows",
    "build_equity_cf_rows",
]
