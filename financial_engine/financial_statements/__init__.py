"""financial_engine.financial_statements — Phase C3 clean statement authority.

Strictly downstream accounting/assembly over authoritative clean-engine
results. See docs/PHASE_C3_CLEAN_FINANCIAL_STATEMENTS_AUTHORITY.md.
"""
from financial_engine.financial_statements.contracts import (
    AccountingPolicies,
    AccountingPolicyAuthority,
    BalanceSheetPeriod,
    BookCapitalizationTreatment,
    FinancialStatementsResult,
    FixedAssetRollForwardPeriod,
    IncomeStatementPeriod,
    LineAuthority,
    PFCashWaterfallPeriod,
    RetainedEarningsPeriod,
    StatementStatus,
    TaxBridgePeriod,
)
from financial_engine.financial_statements.assembly import (
    assemble_decision_complete_financial_statements,
)

__all__ = [
    "AccountingPolicies",
    "AccountingPolicyAuthority",
    "BalanceSheetPeriod",
    "BookCapitalizationTreatment",
    "FinancialStatementsResult",
    "FixedAssetRollForwardPeriod",
    "IncomeStatementPeriod",
    "LineAuthority",
    "PFCashWaterfallPeriod",
    "RetainedEarningsPeriod",
    "StatementStatus",
    "TaxBridgePeriod",
    "assemble_decision_complete_financial_statements",
]
