"""Audit-only tax bridge assembly from waterfall period fields."""

from __future__ import annotations

from domain.financial_statements.result import TaxBridgePeriodResult, TaxBridgeResult
from domain.waterfall.waterfall_engine import WaterfallPeriod, WaterfallResult


def assemble_tax_bridge_period(period: WaterfallPeriod) -> TaxBridgePeriodResult:
    return TaxBridgePeriodResult(
        period=period.period,
        date=period.date,
        year_index=period.year_index,
        period_in_year=period.period_in_year,
        tax_depreciation_keur=period.tax_depreciation_audit_keur,
        fiscal_reintegration_keur=period.fiscal_reintegration_audit_keur,
        taxable_income_before_losses_keur=period.taxable_income_before_losses_audit_keur,
        tax_loss_opening_keur=period.tax_loss_opening_audit_keur,
        tax_loss_used_keur=period.tax_loss_used_audit_keur,
        tax_loss_closing_keur=period.tax_loss_closing_audit_keur,
        taxable_profit_after_losses_keur=period.taxable_profit_after_losses_audit_keur,
        cit_accrual_keur=period.cit_accrual_audit_keur,
        cash_tax_current_period_keur=period.cash_tax_current_period_audit_keur,
        cash_tax_excel_style_h2_diagnostic_keur=period.cash_tax_excel_style_h2_diagnostic_keur,
        r99_runtime_source_accepted=False,
    )


def assemble_tax_bridge(waterfall_result: WaterfallResult) -> TaxBridgeResult:
    return TaxBridgeResult(
        periods=tuple(assemble_tax_bridge_period(period) for period in waterfall_result.periods)
    )
