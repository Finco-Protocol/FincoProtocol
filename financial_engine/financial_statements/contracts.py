"""financial_engine.financial_statements.contracts — Phase C3 typed contracts.

Clean Financial Statements & Output Completeness Authority.

STRICTLY DOWNSTREAM: assembly consumes already-authoritative clean-engine
outputs (operating / tax / Senior / SHL / G2C / DSRA / construction results)
and performs accounting roll-forwards and identity checks only. Statements
never feed back into tax, debt sizing, SHL, distributions, returns or
valuation. No second engine.

Authority vocabulary (per line):
  EXISTING_CLEAN_AUTHORITY        — direct clean runtime vector;
  DERIVED_ACCOUNTING_ROLL_FORWARD — causal accounting roll-forward of clean
                                    vectors (identities checked);
  GENERIC_FINCO_ACCOUNTING_POLICY — standard Finco accounting convention,
                                    explicitly NOT reference validation;
  SOURCE_PROVEN_CONFIGURATION     — typed input provenance;
  UNRESOLVED                      — no authority; surfaced as unavailable.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from datetime import date
from enum import Enum


class StatementStatus(str, Enum):
    """Overall / per-statement typed status."""

    OK = "OK"
    UPSTREAM_FINANCIAL_RESULT_UNAVAILABLE = "UPSTREAM_FINANCIAL_RESULT_UNAVAILABLE"
    STATEMENT_PERIOD_AXIS_MISMATCH = "STATEMENT_PERIOD_AXIS_MISMATCH"
    BOOK_CAPITALIZATION_BASIS_UNAVAILABLE = "BOOK_CAPITALIZATION_BASIS_UNAVAILABLE"
    OPENING_EQUITY_ACCOUNTING_AUTHORITY_UNAVAILABLE = (
        "OPENING_EQUITY_ACCOUNTING_AUTHORITY_UNAVAILABLE"
    )
    UNRESTRICTED_CASH_AUTHORITY_UNAVAILABLE = "UNRESTRICTED_CASH_AUTHORITY_UNAVAILABLE"
    TAX_PAYABLE_AUTHORITY_UNAVAILABLE = "TAX_PAYABLE_AUTHORITY_UNAVAILABLE"
    FINANCING_INCOME_AUTHORITY_UNAVAILABLE = "FINANCING_INCOME_AUTHORITY_UNAVAILABLE"
    LEGAL_RESERVE_AUTHORITY_UNAVAILABLE = "LEGAL_RESERVE_AUTHORITY_UNAVAILABLE"
    PF_CASH_CONSTRUCTION_AUTHORITY_UNAVAILABLE = (
        "PF_CASH_CONSTRUCTION_AUTHORITY_UNAVAILABLE"
    )
    ACCOUNTING_TREATMENT_UNRESOLVED = "ACCOUNTING_TREATMENT_UNRESOLVED"
    BALANCE_SHEET_DOES_NOT_BALANCE = "BALANCE_SHEET_DOES_NOT_BALANCE"
    CASH_FLOW_DOES_NOT_RECONCILE = "CASH_FLOW_DOES_NOT_RECONCILE"
    NON_FINITE_RESULT = "NON_FINITE_RESULT"


class LineAuthority(str, Enum):
    """Per-line accounting authority label."""

    EXISTING_CLEAN_AUTHORITY = "EXISTING_CLEAN_AUTHORITY"
    DERIVED_ACCOUNTING_ROLL_FORWARD = "DERIVED_ACCOUNTING_ROLL_FORWARD"
    GENERIC_FINCO_ACCOUNTING_POLICY = "GENERIC_FINCO_ACCOUNTING_POLICY"
    SOURCE_PROVEN_CONFIGURATION = "SOURCE_PROVEN_CONFIGURATION"
    USER_CONFIGURED_ACCOUNTING_POLICY = "USER_CONFIGURED_ACCOUNTING_POLICY"
    UNRESOLVED = "UNRESOLVED"


from finco_core.inputs.accounting import (
    AccountingPolicyAuthority,
    BookCapitalizationTreatment,
    LegalReservePolicy,
    AccountingPolicyConfig,
)


@dataclass(frozen=True)
class IncomeStatementPeriod:
    """One period of the clean Income Statement (P&L).

    Book depreciation authority: OperatingSchedules.book_depreciation_keur
    (NOT tax depreciation — the tax bridge carries tax depreciation).
    SHL interest expense = gross accrued interest (cash + PIK).
    CIT = canonical tax accrual (tax_keur) — never recomputed here.
    """

    period_index: int
    period_start: date | None
    period_end: date | None
    is_construction: bool

    revenue_keur: float
    opex_keur: float
    ebitda_keur: float
    book_depreciation_keur: float
    # Financing income: BELOW EBITDA AND BELOW EBIT. Never augments EBITDA.
    # EBIT = EBITDA - book_dep (canonical; FI is NOT added to EBIT).
    # NetFinancial = FI - senior_interest - shl_interest.
    # EBT = EBIT + NetFinancial.
    # Zero by policy for projects without a U2 cash-reserve-interest schedule.
    financing_income_keur: float
    ebit_keur: float

    senior_interest_expense_keur: float
    shl_interest_expense_keur: float
    net_financial_result_keur: float

    earnings_before_tax_keur: float
    cit_accrual_keur: float
    net_income_keur: float

    authority: dict = field(default_factory=dict)


@dataclass(frozen=True)
class TaxBridgePeriod:
    """Accrual vs cash tax bridge + loss carryforward audit (pass-through of
    canonical TaxAndCfadsSchedules audit vectors)."""

    period_index: int
    taxable_income_before_losses_keur: float | None
    taxable_profit_after_losses_keur: float | None
    fiscal_reintegration_keur: float | None
    tax_loss_opening_keur: float | None
    tax_loss_used_keur: float | None
    tax_loss_closing_keur: float | None
    tax_depreciation_keur: float | None
    cit_accrual_keur: float | None
    cash_tax_current_period_keur: float | None
    corporate_tax_cash_keur: float | None
    cash_tax_bridge_reconciliation_keur: float | None


@dataclass(frozen=True)
class PFCashWaterfallPeriod:
    """One period of the PF Cash Waterfall statement (Option A).

    This is the project-finance cash waterfall (clearly labelled as such —
    NOT an IFRS IAS 7 statutory cash flow). Every movement row reconciles
    exactly once to the clean G2C waterfall.
    """

    period_index: int
    cashflow_date: date | None
    is_construction: bool

    revenue_cash_keur: float
    opex_cash_keur: float
    ebitda_keur: float
    cash_tax_keur: float

    # Base FCF / FCF Banks boundary = canonical Base CFADS (NOT the
    # post-Senior boundary). senior_debt_service bridges the two:
    #   post_senior_cash_keur = fcf_banks_keur - senior_debt_service_keur
    fcf_banks_keur: float
    senior_debt_service_keur: float
    post_senior_cash_keur: float

    senior_cash_interest_keur: float
    senior_principal_keur: float

    dsra_top_up_keur: float
    dsra_draw_keur: float
    dsra_release_keur: float

    distribution_account_inflow_keur: float
    distribution_account_release_keur: float
    distribution_account_closing_keur: float

    shl_cash_interest_keur: float
    shl_pik_keur: float                        # non-cash (memo)
    shl_principal_paid_keur: float
    shl_unpaid_principal_keur: float

    legal_equity_distribution_keur: float

    # Construction financing cash rows (typed ConstructionFundingResult
    # authority, joined on construction's own canonical dates). None where
    # the period is not covered by the construction funding axis.
    project_cash_uses_keur: float | None = None
    senior_draw_keur: float | None = None
    junior_or_other_funding_draw_keur: float | None = None
    share_capital_draw_keur: float | None = None
    share_premium_draw_keur: float | None = None
    other_equity_draw_keur: float | None = None
    shl_cash_draw_keur: float | None = None


@dataclass(frozen=True)
class FixedAssetRollForwardPeriod:
    """Accumulated book depreciation roll-forward (causal).

    Gross/NFA basis requires a book-capitalization authority that does not
    exist on clean results yet — gross_fixed_assets_keur is intentionally
    None with BOOK_CAPITALIZATION_BASIS_UNAVAILABLE.
    """

    period_index: int
    period_end: date | None
    book_depreciation_keur: float
    accumulated_book_depreciation_keur: float
    gross_fixed_assets_keur: float | None
    accumulated_depreciation_on_disposals_keur: float
    net_fixed_assets_keur: float | None


@dataclass(frozen=True)
class RetainedEarningsPeriod:
    """Retained earnings roll-forward.

    closing = opening + net income - legal equity distributions
              - legal reserve allocation + explicit equity adjustments

    SHL is debt, NOT retained earnings — never deducted here. No balancing
    residual insert: opening retained earnings requires a construction-period equity
    accounting authority that clean inputs do not yet provide, so the
    opening is surfaced as unavailable rather than defaulted to zero.
    """

    period_index: int
    period_end: date | None
    opening_retained_earnings_keur: float | None   # None = opening authority unavailable
    net_income_keur: float
    legal_equity_distribution_keur: float
    legal_reserve_allocation_keur: float | None
    closing_retained_earnings_keur: float | None   # None while opening unavailable


@dataclass(frozen=True)
class BalanceSheetPeriod:
    """Balance-sheet presentation (closed after Correction I).

    Senior, SHL, DA and DSRA balances are clean closing-balance authority.
    net_cit_payable_keur: signed CIT accrual-vs-cash timing balance
      (positive = tax payable liability; negative = tax receivable / prepaid asset).
    BS identity: Assets - (L+E_excl_cit) - net_cit_payable = 0.
    """

    period_index: int
    period_end: date | None
    senior_debt_balance_keur: float | None
    shl_balance_keur: float | None
    shl_unpaid_principal_keur: float | None
    distribution_account_balance_keur: float | None
    dsra_balance_keur: float | None
    unrestricted_cash_keur: float | None          # None = authority unavailable
    gross_fixed_assets_keur: float | None
    accumulated_book_depreciation_keur: float | None
    share_capital_keur: float | None
    share_premium_keur: float | None
    net_cit_payable_keur: float | None = None     # signed; None = not computed
    legal_reserve_keur: float | None = None       # None = LR not computed
    retained_earnings_keur: float | None = None
    balance_check_keur: float | None = None       # None = not claimed / incomplete


@dataclass(frozen=True)
class ConstructionFundingStatementRow:
    """One ConstructionFundingPeriod at its NATIVE grain (pass-through).

    Phase C3 Correction A: construction financing lives on its own
    canonical construction axis (which may be monthly and undated for
    generic factories). These rows are exposed at that native grain — no
    re-allocation onto the model grid, no silent zeroing. PF operating rows
    and these rows together form the complete PF cash picture.
    """

    funding_period_index: int
    period_start: object | None
    period_end: object | None
    cashflow_date: object | None
    project_cash_uses_keur: float
    senior_draw_keur: float
    junior_or_other_funding_draw_keur: float
    share_capital_draw_keur: float
    share_premium_draw_keur: float
    other_committed_equity_draw_keur: float
    additional_equity_draw_keur: float
    shl_cash_draw_keur: float
    total_sponsor_cash_draw_keur: float
    total_sources_keur: float
    sources_uses_difference_keur: float


@dataclass(frozen=True)
class NonConstructionFcFundingStatementRow:
    """Non-construction FC/COD funding use (Phase C3 Correction B §10).

    Pass-through of `ConstructionFundingResult.non_construction_fc_use`
    (e.g. CASH_DSRA reserve funding at COD that is NOT part of the
    construction timeline). Exposed exactly once as a funding cash
    movement; never merged into construction rows or the DSRA asset.
    """

    kind: str
    policy: str
    uses_keur: float
    senior_draw_keur: float
    shl_draw_keur: float
    junior_draw_keur: float
    share_capital_draw_keur: float
    share_premium_draw_keur: float
    other_committed_equity_draw_keur: float
    additional_equity_draw_keur: float
    total_sources_keur: float


@dataclass(frozen=True)
class AccountingPolicies:
    """Typed accounting-policy labels for every derived rule.

    Provenance fields use AccountingPolicyAuthority to distinguish
    SOURCE_PROVEN (Generic Solar Reference / Generic Wind Reference typed policy trace) from GENERIC_FINCO_POLICY
    (Solar / Wind default) — never conflating the two.
    """

    pnl_depreciation: str = "BOOK_DEPRECIATION (OperatingSchedules.book_depreciation_keur)"
    pnl_shl_interest: str = "GROSS_ACCRUED (cash + PIK)"
    pnl_cit: str = "CANONICAL_TAX_ACCRUAL (TaxAndCfadsSchedules.tax_keur)"
    cash_statement: str = "PF_CASH_WATERFALL (project-finance convention, not IAS 7)"
    retained_earnings: str = "DERIVED_ROLL_FORWARD (NI - legal distributions; SHL is debt)"
    legal_reserve: str = "NOT_APPLICABLE (no generic legal-reserve authority)"
    fixed_asset_basis: str = "BOOK_CAPITALIZATION_BASIS_UNAVAILABLE"
    unrestricted_cash: str = "UNRESTRICTED_CASH_AUTHORITY_UNAVAILABLE"
    opening_retained_earnings: str = "OPENING_EQUITY_ACCOUNTING_AUTHORITY_UNAVAILABLE"

    # Typed provenance per policy dimension (AccountingPolicyAuthority enum).
    shl_construction_accounting_authority: AccountingPolicyAuthority = (
        AccountingPolicyAuthority.UNRESOLVED
    )
    legal_reserve_authority: AccountingPolicyAuthority = (
        AccountingPolicyAuthority.UNRESOLVED
    )
    book_capitalization_authority: AccountingPolicyAuthority = (
        AccountingPolicyAuthority.UNRESOLVED
    )
    opening_re_authority: AccountingPolicyAuthority = (
        AccountingPolicyAuthority.UNRESOLVED
    )
    cash_interest_income_authority: AccountingPolicyAuthority = (
        AccountingPolicyAuthority.UNRESOLVED
    )

    # GFA component-level capitalization treatment map.
    # Keys: component name (str). Values: BookCapitalizationTreatment.
    book_capitalization_components: dict = field(default_factory=dict)

    provenance: dict = field(default_factory=dict)


@dataclass(frozen=True)
class FinancialStatementsResult:
    """Phase C3 decision-complete output (honest partial availability)."""

    status: StatementStatus
    project_inputs_summary: dict

    income_statement_status: StatementStatus
    income_statement_periods: tuple[IncomeStatementPeriod, ...]

    tax_bridge_status: StatementStatus
    tax_bridge_periods: tuple[TaxBridgePeriod, ...]
    terminal_unpaid_tax_keur: float | None

    cash_flow_status: StatementStatus
    pf_cash_waterfall_periods: tuple[PFCashWaterfallPeriod, ...]

    fixed_asset_status: StatementStatus
    fixed_asset_periods: tuple[FixedAssetRollForwardPeriod, ...]

    retained_earnings_status: StatementStatus
    retained_earnings_periods: tuple[RetainedEarningsPeriod, ...]


    balance_sheet_status: StatementStatus
    balance_sheet_periods: tuple[BalanceSheetPeriod, ...]

    accounting_policies: AccountingPolicies
    unavailable_reasons: dict = field(default_factory=dict)
    authority_labels: dict = field(default_factory=dict)
    construction_funding_rows: tuple[ConstructionFundingStatementRow, ...] = ()
    construction_funding_grain: str = ""
    non_construction_fc_row: object | None = None
    funding_audit: dict = field(default_factory=dict)

    # Correction C §9/§11/§28: opening-RE authority, full-RE roll-forward,
    # legal reserve and unrestricted cash are SEPARATE status concepts —
    # never conflated (retained_earnings_status != opening status).
    opening_retained_earnings_status: StatementStatus = (
        StatementStatus.OPENING_EQUITY_ACCOUNTING_AUTHORITY_UNAVAILABLE
    )
    cod_opening_retained_earnings_keur: float | None = None
    legal_reserve_status: StatementStatus = (
        StatementStatus.LEGAL_RESERVE_AUTHORITY_UNAVAILABLE
    )
    unrestricted_cash_status: StatementStatus = (
        StatementStatus.UNRESTRICTED_CASH_AUTHORITY_UNAVAILABLE
    )
