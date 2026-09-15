"""Result objects for offline financial statement assembly."""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import date

from domain.financial_statements.excel_mapping import ExcelRowMapping
from domain.financial_statements.inputs import FinancialStatementsConfig


@dataclass(frozen=True)
class TaxBridgePeriodResult:
    period: int
    date: date
    year_index: int
    period_in_year: int
    tax_depreciation_keur: float
    fiscal_reintegration_keur: float
    taxable_income_before_losses_keur: float
    tax_loss_opening_keur: float
    tax_loss_used_keur: float
    tax_loss_closing_keur: float
    taxable_profit_after_losses_keur: float
    cit_accrual_keur: float
    cash_tax_current_period_keur: float
    cash_tax_excel_style_h2_diagnostic_keur: float
    r99_runtime_source_accepted: bool = False


@dataclass(frozen=True)
class TaxBridgeResult:
    periods: tuple[TaxBridgePeriodResult, ...]

    @property
    def total_cit_accrual_keur(self) -> float:
        return sum(period.cit_accrual_keur for period in self.periods)

    @property
    def total_cash_tax_excel_style_h2_diagnostic_keur(self) -> float:
        return sum(period.cash_tax_excel_style_h2_diagnostic_keur for period in self.periods)


@dataclass(frozen=True)
class BalanceSheetPeriodResult:
    period_index: int
    date: date
    gross_fixed_assets_keur: float
    accumulated_depreciation_keur: float
    net_fixed_assets_keur: float
    dsra_balance_keur: float
    jdsra_balance_keur: float
    distribution_account_keur: float
    cash_keur: float
    total_assets_keur: float
    share_capital_keur: float
    legal_reserve_keur: float
    retained_earnings_keur: float
    shl_balance_keur: float
    junior_balance_keur: float
    senior_balance_keur: float
    refinancing_keur: float
    short_term_loan_keur: float
    total_liabilities_equity_keur: float
    balance_check_keur: float
    cash_is_residual: bool = True


@dataclass(frozen=True)
class BalanceSheetResult:
    periods: tuple[BalanceSheetPeriodResult, ...]

    @property
    def max_abs_balance_check_keur(self) -> float:
        return max((abs(period.balance_check_keur) for period in self.periods), default=0.0)


@dataclass(frozen=True)
class PFCashWaterfallPeriodResult:
    period_index: int
    date: date
    revenue_cash_keur: float
    opex_cash_keur: float
    ebitda_cash_keur: float
    senior_cash_interest_keur: float
    cash_tax_keur: float
    fcf_banks_keur: float
    senior_total_ds_keur: float
    dsra_funding_keur: float
    dsra_release_keur: float
    fcf_junior_keur: float
    junior_ds_keur: float
    other_cash_keur: float
    distribution_account_pre_lockup_keur: float
    lockup_applied: bool
    lockup_reason: str | None
    fcf_for_distribution_keur: float
    distribution_account_carryforward_keur: float
    fcf_for_shl_keur: float
    shl_cash_interest_keur: float
    shl_pik_keur: float
    shl_principal_keur: float
    net_shl_cash_outflow_keur: float
    fcf_for_dividends_keur: float
    net_dividends_keur: float
    r99_runtime_source_accepted: bool = False


@dataclass(frozen=True)
class PFCashWaterfallResult:
    periods: tuple[PFCashWaterfallPeriodResult, ...]

    @property
    def r99_r102_identity_holds(self) -> bool:
        return all(
            abs(period.fcf_for_distribution_keur - period.fcf_for_shl_keur) <= 0.0001
            for period in self.periods
        )


@dataclass(frozen=True)
class PnLPeriodResult:
    period: int
    date: date
    year_index: int
    period_in_year: int
    revenues_keur: float
    operating_expenses_keur: float
    local_tax_keur: float
    wht_on_interests_keur: float
    depreciation_keur: float
    total_expenses_keur: float
    ebit_keur: float
    interest_from_reserve_accounts_keur: float
    interest_from_cash_keur: float
    wht_on_financing_revenues_keur: float
    senior_interest_expense_keur: float
    refinancing_interest_keur: float
    junior_interest_keur: float
    shl_interest_expense_keur: float
    interest_on_cash_keur: float
    financial_earnings_keur: float
    earnings_before_tax_keur: float
    fiscal_reintegration_keur: float
    taxable_income_before_losses_keur: float
    losses_n_1_keur: float
    allocated_losses_keur: float
    losses_n_keur: float
    carriable_losses_keur: float
    taxable_profit_after_losses_keur: float
    cit_accrual_keur: float
    cash_tax_excel_style_h2_diagnostic_keur: float
    net_income_keur: float
    legal_reserve_keur: float
    retained_earnings_keur: float
    net_dividends_keur: float

    def row_values(self) -> dict[str, float]:
        """Return P&L values keyed by Excel row code."""

        return {
            "R8": self.revenues_keur,
            "R10": self.operating_expenses_keur,
            "R11": self.local_tax_keur,
            "R12": self.wht_on_interests_keur,
            "R13": self.depreciation_keur,
            "R14": self.total_expenses_keur,
            "R16": self.ebit_keur,
            "R19": self.interest_from_reserve_accounts_keur,
            "R20": self.interest_from_cash_keur,
            "R21": self.wht_on_financing_revenues_keur,
            "R24": self.senior_interest_expense_keur,
            "R25": self.refinancing_interest_keur,
            "R26": self.junior_interest_keur,
            "R27": self.shl_interest_expense_keur,
            "R28": self.interest_on_cash_keur,
            "R30": self.financial_earnings_keur,
            "R32": self.earnings_before_tax_keur,
            "R34": self.fiscal_reintegration_keur,
            "R35": self.taxable_income_before_losses_keur,
            "R36": self.losses_n_1_keur,
            "R37": self.allocated_losses_keur,
            "R38": self.losses_n_keur,
            "R39": self.carriable_losses_keur,
            "R41": self.taxable_profit_after_losses_keur,
            "R43": self.cit_accrual_keur,
            "R44": self.cash_tax_excel_style_h2_diagnostic_keur,
            "R46": self.net_income_keur,
            "R48": self.legal_reserve_keur,
            "R49": self.retained_earnings_keur,
            "R50": self.net_dividends_keur,
        }


@dataclass(frozen=True)
class PnLStatementResult:
    periods: tuple[PnLPeriodResult, ...]
    row_mapping: tuple[ExcelRowMapping, ...]
    totals_by_row: dict[str, float] = field(default_factory=dict)

    def total_for_row(self, row_code: str) -> float:
        return self.totals_by_row[row_code]


@dataclass(frozen=True)
class FinancialStatementsResult:
    config: FinancialStatementsConfig
    pnl: PnLStatementResult
    tax_bridge: TaxBridgeResult
    balance_sheet: BalanceSheetResult
    pf_cash_waterfall: PFCashWaterfallResult
