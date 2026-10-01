"""Serialize the clean runtime's own financial-statements package.

This adapter is a PRESENTATION bridge only.  It wraps the exact
``financial_statements_result`` assembled by the clean production runtime
(``CleanProductionRun.financial_statements_result``) into the field shape
the institutional workbook writers already consume.  Rules:

- NO arithmetic: every exposed value is read verbatim from the runtime
  authority.  Quantities the clean runtime does not publish are exposed as
  ``None`` and render as typed NOT_AVAILABLE rows (missing != 0).
- NO balancing plug: balance reconciliation is the runtime's own
  ``balance_check_keur`` (computed by the statement authority itself).
- SAME-RUN identity: the wrapper carries the run identity that the bundle
  stamped, so cross-run substitution is detectable.
"""
from __future__ import annotations

from dataclasses import dataclass
from datetime import date
from typing import Any


class _AttrView:
    """Duck-typed view exposing writer-expected attribute names verbatim."""

    def __init__(self, source: Any, mapping: dict[str, str | None]):
        object.__setattr__(self, "_source", source)
        object.__setattr__(self, "_mapping", mapping)

    def __getattr__(self, name: str):
        mapping = object.__getattribute__(self, "_mapping")
        source = object.__getattribute__(self, "_source")
        if name in mapping:
            target = mapping[name]
            if target is None:
                return None  # typed NOT_AVAILABLE — clean runtime has no such field
            return getattr(source, target)
        return getattr(source, name)  # pass-through (period_index, date, ...)


def _wrap_periods(periods: Any, mapping: dict[str, str | None]) -> tuple:
    return tuple(_AttrView(period, mapping) for period in periods)


class _PeriodsView:
    def __init__(self, periods: tuple):
        object.__setattr__(self, "periods", periods)


@dataclass(frozen=True)
class CleanStatementsSerializationView:
    """Legacy-shaped view over the clean runtime statements package."""

    run_id: str | None
    run_identity_hash: str | None
    tax_bridge: Any
    pnl: Any
    pf_cash_waterfall: Any
    balance_sheet: Any
    status: Any = None


def serialize_clean_statements(
    financial_statements_result: Any,
    *,
    run_id: str | None = None,
    run_identity_hash: str | None = None,
) -> CleanStatementsSerializationView:
    """Wrap the clean runtime's statements package for the workbook writers.

    Mapping is identity-preserving: each target field reads ONE source field
    verbatim.  Fields the clean runtime does not publish map to None.
    """
    fs = financial_statements_result
    if fs is None:
        raise ValueError("clean financial_statements_result is required")

    tax_periods = _wrap_periods(fs.tax_bridge_periods, {
        # the clean TaxBridgePeriod has no calendar date; writers label by
        # period_index instead (no fabricated dates)
        "date": None,
        # identical names — pass-through
        "tax_depreciation_keur": "tax_depreciation_keur",
        "fiscal_reintegration_keur": "fiscal_reintegration_keur",
        "taxable_income_before_losses_keur": "taxable_income_before_losses_keur",
        "tax_loss_opening_keur": "tax_loss_opening_keur",
        "tax_loss_used_keur": "tax_loss_used_keur",
        "tax_loss_closing_keur": "tax_loss_closing_keur",
        "taxable_profit_after_losses_keur": "taxable_profit_after_losses_keur",
        "cit_accrual_keur": "cit_accrual_keur",
        "cash_tax_current_period_keur": "cash_tax_current_period_keur",
    })

    pnl_periods = _wrap_periods(fs.income_statement_periods, {
        "date": "period_end",
        "revenues_keur": "revenue_keur",
        "operating_expenses_keur": "opex_keur",
        "depreciation_keur": "book_depreciation_keur",
        "ebit_keur": "ebit_keur",
        "senior_interest_expense_keur": "senior_interest_expense_keur",
        "shl_interest_expense_keur": "shl_interest_expense_keur",
        "earnings_before_tax_keur": "earnings_before_tax_keur",
        "net_income_keur": "net_income_keur",
        # clean P&L does not publish these legacy fields:
        "fiscal_reintegration_keur": None,
        "taxable_income_before_losses_keur": None,
        "net_dividends_keur": None,
    })

    cf_periods = _wrap_periods(fs.pf_cash_waterfall_periods, {
        "date": "cashflow_date",
        "revenue_cash_keur": "revenue_cash_keur",
        "opex_cash_keur": "opex_cash_keur",
        "ebitda_cash_keur": "ebitda_keur",
        "cash_tax_keur": "cash_tax_keur",
        "fcf_banks_keur": "fcf_banks_keur",
        "senior_total_ds_keur": "senior_debt_service_keur",
        "shl_cash_interest_keur": "shl_cash_interest_keur",
        "shl_principal_keur": "shl_principal_paid_keur",
        # clean PF cash waterfall does not publish these legacy fields:
        "fcf_for_shl_keur": None,
        "net_dividends_keur": None,
    })

    bs_periods = _wrap_periods(fs.balance_sheet_periods, {
        "date": "period_end",
        "gross_fixed_assets_keur": "gross_fixed_assets_keur",
        "accumulated_depreciation_keur": "accumulated_book_depreciation_keur",
        # net fixed assets: gross - accumulated would be arithmetic; the
        # writers get the two published components verbatim and the runtime's
        # own balance_check for reconciliation.
        "net_fixed_assets_keur": None,
        "cash_keur": "unrestricted_cash_keur",
        "senior_balance_keur": "senior_debt_balance_keur",
        "shl_balance_keur": "shl_balance_keur",
        "retained_earnings_keur": "retained_earnings_keur",
        # the clean runtime does not publish pre-aggregated totals:
        "total_assets_keur": None,
        "total_liabilities_equity_keur": None,
        "balance_check_keur": "balance_check_keur",
        "dsra_balance_keur": "dsra_balance_keur",
        "distribution_account_keur": "distribution_account_balance_keur",
        "share_capital_keur": "share_capital_keur",
        "net_cit_payable_keur": "net_cit_payable_keur",
        "legal_reserve_keur": "legal_reserve_keur",
    })

    return CleanStatementsSerializationView(
        run_id=run_id,
        run_identity_hash=run_identity_hash,
        tax_bridge=_PeriodsView(tax_periods),
        pnl=_PeriodsView(pnl_periods),
        pf_cash_waterfall=_PeriodsView(cf_periods),
        balance_sheet=_PeriodsView(bs_periods),
        status=getattr(fs, "status", None),
    )
