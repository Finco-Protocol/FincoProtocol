"""Dataclasses for financial statement periods."""
from dataclasses import dataclass, field
from datetime import date
from typing import Optional


@dataclass
class IncomeStatementPeriod:
    period: int
    date: date
    revenue_keur: float
    opex_keur: float
    ebitda_keur: float
    depreciation_keur: float
    ebit_keur: float
    interest_senior_keur: float
    interest_shl_keur: float
    total_interest_keur: float
    ebt_keur: float
    tax_keur: float
    net_income_keur: float


@dataclass
class BalanceSheetPeriod:
    period: int
    date: date
    # Assets
    net_fixed_assets_keur: float
    dsra_balance_keur: float
    mra_balance_keur: float
    cash_balance_keur: float
    total_assets_keur: float
    # Liabilities
    senior_balance_keur: float
    shl_balance_keur: float
    tax_payable_keur: float  # cumulative accrued tax not yet deducted from cf_after_tax
    total_liabilities_keur: float
    # Equity
    share_capital_keur: float
    share_premium_keur: float
    retained_earnings_keur: float  # includes shl_principal notional equity reserve
    total_equity_keur: float
    # Check
    check_keur: float  # total_assets - total_liabilities - total_equity (should be ~0)


@dataclass
class CashFlowPeriod:
    period: int
    date: date
    # Operating
    net_income_keur: float
    add_depreciation_keur: float
    add_interest_senior_keur: float
    add_interest_shl_keur: float
    tax_payable_adjustment_keur: float  # Δaccrued tax payable: tax_keur - cash_tax_this_period
    operating_cash_flow_keur: float
    # Investing
    capex_keur: float
    investing_cash_flow_keur: float
    # Financing
    senior_principal_keur: float
    shl_principal_keur: float
    interest_paid_senior_keur: float
    interest_paid_shl_keur: float
    dsra_movement_keur: float
    mra_movement_keur: float
    distribution_keur: float
    financing_cash_flow_keur: float
    # Net
    net_cash_flow_keur: float
    opening_cash_keur: float
    closing_cash_keur: float
    check_keur: float  # closing_cash - (opening_cash + net_cash_flow), should be ~0


@dataclass
class FinancialStatements:
    income_statement: list[IncomeStatementPeriod] = field(default_factory=list)
    balance_sheet: list[BalanceSheetPeriod] = field(default_factory=list)
    cash_flow: list[CashFlowPeriod] = field(default_factory=list)
