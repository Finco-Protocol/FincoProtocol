"""Excel row mappings for the offline P&L assembly."""

from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True)
class ExcelRowMapping:
    row_code: str
    row_number: int
    label: str
    field_name: str
    source_owner: str
    sign_convention: str
    notes: str = ""


PNL_ROW_MAPPINGS: tuple[ExcelRowMapping, ...] = (
    ExcelRowMapping("R8", 8, "Revenues", "revenues_keur", "WaterfallPeriod.revenue_keur", "positive income"),
    ExcelRowMapping("R10", 10, "Operating expenses", "operating_expenses_keur", "WaterfallPeriod.opex_keur", "negative expense"),
    ExcelRowMapping("R11", 11, "Local tax", "local_tax_keur", "placeholder", "negative expense", "Not exposed in runtime P&L source yet."),
    ExcelRowMapping("R12", 12, "WHT on interests", "wht_on_interests_keur", "placeholder", "negative expense", "Not exposed in runtime P&L source yet."),
    ExcelRowMapping("R13", 13, "Depreciation", "depreciation_keur", "WaterfallPeriod.tax_depreciation_audit_keur", "negative expense"),
    ExcelRowMapping("R14", 14, "Total expenses", "total_expenses_keur", "assembled", "negative expense subtotal"),
    ExcelRowMapping("R16", 16, "EBIT", "ebit_keur", "assembled", "positive or negative result"),
    ExcelRowMapping("R19", 19, "Interests from reserve accounts", "interest_from_reserve_accounts_keur", "placeholder", "positive income"),
    ExcelRowMapping("R20", 20, "Interests from cash", "interest_from_cash_keur", "placeholder", "positive income"),
    ExcelRowMapping("R21", 21, "WHT on financing revenues", "wht_on_financing_revenues_keur", "placeholder", "negative expense"),
    ExcelRowMapping("R24", 24, "Senior interests", "senior_interest_expense_keur", "WaterfallPeriod.senior_interest_keur", "negative expense"),
    ExcelRowMapping("R25", 25, "Refinancing interest", "refinancing_interest_keur", "placeholder", "negative expense"),
    ExcelRowMapping("R26", 26, "Junior interest", "junior_interest_keur", "placeholder", "negative expense"),
    ExcelRowMapping("R27", 27, "SHL interest", "shl_interest_expense_keur", "WaterfallPeriod.shl_interest_keur", "negative expense"),
    ExcelRowMapping("R28", 28, "Interests on cash", "interest_on_cash_keur", "placeholder", "positive income"),
    ExcelRowMapping("R30", 30, "Financial earnings", "financial_earnings_keur", "assembled", "positive or negative subtotal"),
    ExcelRowMapping("R32", 32, "EBT", "earnings_before_tax_keur", "assembled", "positive or negative result"),
    ExcelRowMapping("R34", 34, "Fiscal reintegration", "fiscal_reintegration_keur", "WaterfallPeriod.fiscal_reintegration_audit_keur", "positive taxable add-back"),
    ExcelRowMapping("R35", 35, "Taxable income", "taxable_income_before_losses_keur", "WaterfallPeriod.taxable_income_before_losses_audit_keur", "positive or zero audit value"),
    ExcelRowMapping("R36", 36, "Losses N-1", "losses_n_1_keur", "WaterfallPeriod.tax_loss_opening_audit_keur", "negative balance presentation"),
    ExcelRowMapping("R37", 37, "Allocated losses", "allocated_losses_keur", "WaterfallPeriod.tax_loss_used_audit_keur", "positive loss utilization"),
    ExcelRowMapping("R38", 38, "Losses N", "losses_n_keur", "WaterfallPeriod.tax_loss_closing_audit_keur", "negative balance presentation"),
    ExcelRowMapping("R39", 39, "Carriable losses", "carriable_losses_keur", "WaterfallPeriod.tax_loss_closing_audit_keur", "negative balance presentation"),
    ExcelRowMapping("R41", 41, "Taxable profit N", "taxable_profit_after_losses_keur", "WaterfallPeriod.taxable_profit_after_losses_audit_keur", "positive taxable profit"),
    ExcelRowMapping("R43", 43, "CIT accrual", "cit_accrual_keur", "WaterfallPeriod.cit_accrual_audit_keur", "negative expense presentation"),
    ExcelRowMapping("R44", 44, "Cash tax diagnostic", "cash_tax_excel_style_h2_diagnostic_keur", "WaterfallPeriod.cash_tax_excel_style_h2_diagnostic_keur", "negative cash outflow diagnostic"),
    ExcelRowMapping("R46", 46, "Net income", "net_income_keur", "assembled", "positive or negative result"),
    ExcelRowMapping("R48", 48, "Legal reserve", "legal_reserve_keur", "placeholder", "negative appropriation"),
    ExcelRowMapping("R49", 49, "Retained earnings", "retained_earnings_keur", "assembled", "cumulative balance"),
    ExcelRowMapping("R50", 50, "Net dividends", "net_dividends_keur", "WaterfallPeriod.distribution_keur", "negative distribution presentation"),
)

PNL_ROW_BY_CODE = {mapping.row_code: mapping for mapping in PNL_ROW_MAPPINGS}
PNL_ROW_BY_FIELD = {mapping.field_name: mapping for mapping in PNL_ROW_MAPPINGS}

BS_ROW_MAPPINGS: tuple[ExcelRowMapping, ...] = (
    ExcelRowMapping("BS_R8", 8, "Gross Fixed Assets", "gross_fixed_assets_keur", "assembly placeholder until capex ledger is exposed", "positive asset"),
    ExcelRowMapping("BS_R9", 9, "Accumulated Depreciation", "accumulated_depreciation_keur", "P&L depreciation cumulative", "positive contra-asset"),
    ExcelRowMapping("BS_R10", 10, "Net Fixed Assets", "net_fixed_assets_keur", "assembled", "positive asset"),
    ExcelRowMapping("BS_R12", 12, "DSRA", "dsra_balance_keur", "WaterfallPeriod.dsra_balance_keur", "positive asset"),
    ExcelRowMapping("BS_R13", 13, "J-DSRA", "jdsra_balance_keur", "placeholder", "positive asset"),
    ExcelRowMapping("BS_R14", 14, "Distribution Account", "distribution_account_keur", "WaterfallPeriod.r100_carryforward_keur", "positive asset"),
    ExcelRowMapping("BS_R15", 15, "Cash", "cash_keur", "residual assembly line", "positive or negative residual"),
    ExcelRowMapping("BS_R17", 17, "Total Assets", "total_assets_keur", "assembled", "positive total"),
    ExcelRowMapping("BS_R21", 21, "Share Capital", "share_capital_keur", "placeholder", "positive equity"),
    ExcelRowMapping("BS_R22", 22, "Legal Reserve", "legal_reserve_keur", "P&L legal reserve cumulative placeholder", "positive equity"),
    ExcelRowMapping("BS_R23", 23, "Retained Earnings", "retained_earnings_keur", "P&L retained earnings", "positive or negative equity"),
    ExcelRowMapping("BS_R24", 24, "Shareholder Loan", "shl_balance_keur", "WaterfallPeriod.shl_balance_keur", "positive liability"),
    ExcelRowMapping("BS_R25", 25, "Junior Balance", "junior_balance_keur", "placeholder", "positive liability"),
    ExcelRowMapping("BS_R26", 26, "Senior Debt", "senior_balance_keur", "WaterfallPeriod.senior_balance_keur", "positive liability"),
    ExcelRowMapping("BS_R27", 27, "Refinancing", "refinancing_keur", "placeholder", "positive liability"),
    ExcelRowMapping("BS_R29", 29, "Short Term Loan", "short_term_loan_keur", "placeholder", "positive liability"),
    ExcelRowMapping("BS_R31", 31, "Total Liabilities + Equity", "total_liabilities_equity_keur", "assembled", "positive total"),
    ExcelRowMapping("BS_R33", 33, "Balance Check", "balance_check_keur", "assembled invariant", "zero target"),
)

PF_CASH_WATERFALL_ROW_MAPPINGS: tuple[ExcelRowMapping, ...] = (
    ExcelRowMapping("CF_R20", 20, "Operating Revenues", "revenue_cash_keur", "WaterfallPeriod.revenue_keur", "positive cash inflow"),
    ExcelRowMapping("CF_R38", 38, "OPEX", "opex_cash_keur", "WaterfallPeriod.opex_keur", "negative cash outflow"),
    ExcelRowMapping("CF_R40", 40, "EBITDA", "ebitda_cash_keur", "WaterfallPeriod.ebitda_keur", "positive or negative subtotal"),
    ExcelRowMapping("CF_R63", 63, "Senior Cash Interest", "senior_cash_interest_keur", "WaterfallPeriod.senior_interest_keur", "negative cash outflow"),
    ExcelRowMapping("CF_R67", 67, "Cash CIT", "cash_tax_keur", "WaterfallPeriod.corporate_tax_cash_keur", "negative cash outflow"),
    ExcelRowMapping("CF_R69", 69, "FCF Banks", "fcf_banks_keur", "WaterfallPeriod.r69_fcf_banks_keur", "audit-only C1d bridge"),
    ExcelRowMapping("CF_R70", 70, "Senior Debt Service", "senior_total_ds_keur", "WaterfallPeriod.senior_ds_keur", "negative cash outflow"),
    ExcelRowMapping("CF_R84", 84, "FCF Junior", "fcf_junior_keur", "WaterfallPeriod.r84_fcf_junior_keur", "audit-only C1d bridge"),
    ExcelRowMapping("CF_R98", 98, "Distribution Account Pre-Lockup", "distribution_account_pre_lockup_keur", "WaterfallPeriod.r98_distribution_account_keur", "audit-only C1d bridge"),
    ExcelRowMapping("CF_R99", 99, "FCF for Distribution", "fcf_for_distribution_keur", "WaterfallPeriod.r99_fcf_for_distribution_keur", "audit-only C1d bridge"),
    ExcelRowMapping("CF_R100", 100, "Distribution Account Carryforward", "distribution_account_carryforward_keur", "WaterfallPeriod.r100_carryforward_keur", "audit-only C1d bridge"),
    ExcelRowMapping("CF_R102", 102, "FCF for SHL", "fcf_for_shl_keur", "WaterfallPeriod.r102_fcf_for_shl_keur", "audit-only C1d bridge"),
    ExcelRowMapping("CF_R104", 104, "Net SHL Cash Outflow", "net_shl_cash_outflow_keur", "WaterfallPeriod SHL service fields", "negative cash outflow"),
    ExcelRowMapping("CF_R106", 106, "FCF for Dividends", "fcf_for_dividends_keur", "assembled from R102 and SHL cash outflow", "positive or negative subtotal"),
    ExcelRowMapping("CF_R119", 119, "Net Dividends", "net_dividends_keur", "WaterfallPeriod.distribution_keur", "positive cash distribution"),
)

BS_ROW_BY_CODE = {mapping.row_code: mapping for mapping in BS_ROW_MAPPINGS}
PF_CASH_WATERFALL_ROW_BY_CODE = {
    mapping.row_code: mapping for mapping in PF_CASH_WATERFALL_ROW_MAPPINGS
}
