"""finco_core.financial_statements — Canonical financial statements aggregation.

V3-4: Generates Income Statement, Balance Sheet, and Cash Flow Statement
exclusively from existing WaterfallPeriod engine outputs. No new financial logic.
"""
from finco_core.financial_statements.statement_models import (
    IncomeStatementPeriod,
    BalanceSheetPeriod,
    CashFlowPeriod,
    FinancialStatements,
)
from finco_core.financial_statements.income_statement import generate_income_statement
from finco_core.financial_statements.balance_sheet import generate_balance_sheet
from finco_core.financial_statements.cash_flow import generate_cash_flow_statement
from finco_core.financial_statements.aggregation import generate_financial_statements

__all__ = [
    "IncomeStatementPeriod",
    "BalanceSheetPeriod",
    "CashFlowPeriod",
    "FinancialStatements",
    "generate_income_statement",
    "generate_balance_sheet",
    "generate_cash_flow_statement",
    "generate_financial_statements",
]
