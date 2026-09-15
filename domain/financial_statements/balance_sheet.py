"""Offline Balance Sheet assembly from existing waterfall outputs."""

from __future__ import annotations

from domain.financial_statements.result import (
    BalanceSheetPeriodResult,
    BalanceSheetResult,
    PnLStatementResult,
)
from domain.waterfall.waterfall_engine import WaterfallResult


def assemble_balance_sheet(
    waterfall_result: WaterfallResult,
    pnl: PnLStatementResult,
) -> BalanceSheetResult:
    """Assemble an audit-only balance sheet bridge.

    Some accounting rows are not runtime source-of-truth fields yet. Those rows
    are kept as explicit placeholders and cash is derived as the residual needed
    for the statement balance check. The residual does not feed runtime cash.
    """

    periods: list[BalanceSheetPeriodResult] = []
    accumulated_depreciation = 0.0

    for waterfall_period, pnl_period in zip(waterfall_result.periods, pnl.periods):
        accumulated_depreciation += max(0.0, -pnl_period.depreciation_keur)

        # Gross fixed assets are not exposed on WaterfallResult. Until the
        # construction/capex ledger is part of statements, keep net fixed assets
        # at zero and make the cash line the explicit balancing residual.
        gross_fixed_assets = accumulated_depreciation
        net_fixed_assets = gross_fixed_assets - accumulated_depreciation

        dsra_balance = waterfall_period.dsra_balance_keur
        jdsra_balance = 0.0
        distribution_account = waterfall_period.r100_carryforward_keur

        share_capital = 0.0
        legal_reserve = pnl_period.legal_reserve_keur
        retained_earnings = pnl_period.retained_earnings_keur
        shl_balance = waterfall_period.shl_balance_keur
        junior_balance = 0.0
        senior_balance = waterfall_period.senior_balance_keur
        refinancing = 0.0
        short_term_loan = 0.0

        total_liabilities_equity = (
            share_capital
            + legal_reserve
            + retained_earnings
            + shl_balance
            + junior_balance
            + senior_balance
            + refinancing
            + short_term_loan
        )
        cash = total_liabilities_equity - (
            net_fixed_assets + dsra_balance + jdsra_balance + distribution_account
        )
        total_assets = net_fixed_assets + dsra_balance + jdsra_balance + distribution_account + cash
        balance_check = total_assets - total_liabilities_equity

        periods.append(
            BalanceSheetPeriodResult(
                period_index=waterfall_period.period,
                date=waterfall_period.date,
                gross_fixed_assets_keur=gross_fixed_assets,
                accumulated_depreciation_keur=accumulated_depreciation,
                net_fixed_assets_keur=net_fixed_assets,
                dsra_balance_keur=dsra_balance,
                jdsra_balance_keur=jdsra_balance,
                distribution_account_keur=distribution_account,
                cash_keur=cash,
                total_assets_keur=total_assets,
                share_capital_keur=share_capital,
                legal_reserve_keur=legal_reserve,
                retained_earnings_keur=retained_earnings,
                shl_balance_keur=shl_balance,
                junior_balance_keur=junior_balance,
                senior_balance_keur=senior_balance,
                refinancing_keur=refinancing,
                short_term_loan_keur=short_term_loan,
                total_liabilities_equity_keur=total_liabilities_equity,
                balance_check_keur=balance_check,
                cash_is_residual=True,
            )
        )

    return BalanceSheetResult(periods=tuple(periods))
