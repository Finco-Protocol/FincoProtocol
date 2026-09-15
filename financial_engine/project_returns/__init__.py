"""Canonical Project / Sponsor return summary and terminal-state authority."""

from financial_engine.project_returns.contracts import (
    CashAccountTerminalState,
    CashAccountTerminalStatus,
    DebtTerminalState,
    DebtTerminalStatus,
    DecisionCompleteReturnSummary,
    ProjectReturnCashFlow,
    ProjectReturnResult,
    ProjectReturnStatus,
    ReturnMetricSummary,
    ShlTerminalState,
    ShlTerminalStatus,
    TerminalFinancialState,
)
from financial_engine.project_returns.model import (
    build_decision_complete_return_summary,
)

__all__ = [
    "CashAccountTerminalState",
    "CashAccountTerminalStatus",
    "DebtTerminalState",
    "DebtTerminalStatus",
    "DecisionCompleteReturnSummary",
    "ProjectReturnCashFlow",
    "ProjectReturnResult",
    "ProjectReturnStatus",
    "ReturnMetricSummary",
    "ShlTerminalState",
    "ShlTerminalStatus",
    "TerminalFinancialState",
    "build_decision_complete_return_summary",
]
