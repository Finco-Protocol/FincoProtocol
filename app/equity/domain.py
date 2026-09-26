"""Canonical FINCO Equity domain contracts.

These dataclasses are the canonical domain boundary. Provider-specific
fields MUST NOT be added here — Massive (or any future provider) details
stop at the adaptor boundary (see app/equity/providers/).
"""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import Optional


PROVIDER_MASSIVE = "MASSIVE"
SOURCE_CONTRACT_MASSIVE_LEGACY = "LEGACY_MASSIVE_VX"


@dataclass(frozen=True)
class EquityAsset:
    """A tokenized equity/ETF in the Robinhood Chain universe."""
    robinhood_token_symbol: str
    underlying_ticker: str
    name: str
    token_contract_address: Optional[str] = None
    chain_network: Optional[str] = None
    underlying_exchange: Optional[str] = None
    cik: Optional[str] = None
    figi: Optional[str] = None
    currency: Optional[str] = None
    security_type: Optional[str] = None
    active: bool = True


@dataclass(frozen=True)
class CompanyProfile:
    ticker: str
    name: str
    cik: Optional[str] = None
    figi: Optional[str] = None
    primary_exchange: Optional[str] = None
    security_type: Optional[str] = None
    currency: Optional[str] = None
    description: Optional[str] = None
    sic_code: Optional[str] = None
    sic_description: Optional[str] = None
    homepage_url: Optional[str] = None
    total_employees: Optional[int] = None
    list_date: Optional[str] = None
    address: Optional[dict] = None
    phone_number: Optional[str] = None
    share_class_shares_outstanding: Optional[int] = None


@dataclass(frozen=True)
class EquitySnapshot:
    """Normalized financial statement snapshot (canonical contract)."""
    ticker: str
    cik: Optional[str]
    timeframe: str            # ttm | annual | quarterly
    fiscal_year: Optional[str]
    fiscal_quarter: Optional[str]
    period_end: Optional[str]
    filing_date: Optional[str]
    income_statement: dict = field(default_factory=dict)
    balance_sheet: dict = field(default_factory=dict)
    cash_flow_statement: dict = field(default_factory=dict)


@dataclass(frozen=True)
class Dividend:
    ticker: str
    cash_amount: float
    currency: Optional[str]
    declaration_date: Optional[str]
    ex_dividend_date: Optional[str]
    record_date: Optional[str]
    pay_date: Optional[str]
    frequency: Optional[int]
    dividend_type: Optional[str]


@dataclass(frozen=True)
class Split:
    ticker: str
    execution_date: Optional[str]
    split_from: Optional[float]
    split_to: Optional[float]


# ---------------------------------------------------------------------------
# Derived fundamentals (transparent, statements-only, no market data).
# ---------------------------------------------------------------------------

def _num(stmt: dict, *keys: str) -> Optional[float]:
    for key in keys:
        value = stmt.get(key)
        if isinstance(value, (int, float)):
            return float(value)
    return None


def _ratio(num: Optional[float], den: Optional[float]) -> Optional[float]:
    if num is None or den is None or den == 0:
        return None
    return num / den


def derive_fundamentals(snapshot: EquitySnapshot) -> dict:
    """Derive statement-only fundamentals. No market-dependent ratios."""
    income = snapshot.income_statement
    balance = snapshot.balance_sheet
    cash = snapshot.cash_flow_statement

    revenues = _num(income, "revenues")
    gross_profit = _num(income, "gross_profit")
    operating_income = _num(income, "operating_income_loss")
    net_income = _num(income, "net_income_loss")
    ebitda = _num(income, "ebitda")
    cfo = _num(cash, "net_cash_flow_from_operating_activities")
    capex = _num(cash, "capital_expenditure")
    if capex is not None and capex > 0:
        capex = -capex  # canonical: outflow negative
    total_debt = _num(balance, "total_debt", "long_term_debt")
    cash_and_eq = _num(balance, "cash_and_cash_equivalents")
    equity = _num(
        balance, "stockholders_equity", "equity",
        "equity_attributable_to_parent",
    )

    fcf = None
    if cfo is not None and capex is not None:
        fcf = cfo + capex

    return {
        "revenues": revenues,
        "revenue_growth": None,  # filled by caller with prior period if desired
        "gross_margin": _ratio(gross_profit, revenues),
        "ebit_margin": _ratio(operating_income, revenues),
        "ebitda_margin": _ratio(ebitda, revenues),
        "net_margin": _ratio(net_income, revenues),
        "free_cash_flow": fcf,
        "fcf_margin": _ratio(fcf, revenues),
        "return_on_equity": _ratio(net_income, equity),
        "net_debt": (total_debt - cash_and_eq)
        if total_debt is not None and cash_and_eq is not None
        else None,
        "debt_to_equity": _ratio(total_debt, equity),
    }
