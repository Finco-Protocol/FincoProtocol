"""domain/shl/result — SHL Engine result dataclasses."""
from dataclasses import dataclass
from typing import Tuple


@dataclass(frozen=True)
class ShlPeriodResult:
    """Canonical output for one semiannual period.

    Attributes
    ----------
    period_index : int
        1-based semiannual period index.
    opening_balance_keur : float
        SHL opening balance at start of period.
    drawdown_keur : float
        New SHL funding drawn this period.
    gross_accrued_interest_keur : float
        Interest accrued on opening balance: opening × rate × day_frac.
    cash_interest_paid_keur : float
        Cash actually paid for interest this period.
    pik_capitalized_keur : float
        Interest capitalized as PIK (not paid in cash).
    principal_repaid_keur : float
        Principal repaid this period from remaining cash.
    closing_balance_keur : float
        SHL closing balance = opening + drawdown + PIK - principal.
    cash_consumed_by_shl_keur : float
        Total cash consumed by SHL = cash_interest + principal.
    cash_after_shl_keur : float
        Cash remaining after SHL service.
    cash_for_distribution_keur : float
        Cash available for distribution (residual after SHL fully served).
    pik_triggered : bool
        True if PIK > 0 this period.
    cash_sweep_100_pct : bool
        True if 100% of post-senior cash went to SHL.
    reserve_applied : bool
        True if minimum cash reserve was retained.
    distribution_account_r102_sweep_candidate_keur : float | None, default None
        R102 sweep candidate provided by DistributionAccount (kEUR).
        None means no external R102 input was provided (legacy behavior).
    r102_sweep_applied_keur : float, default 0.0
        R102 sweep amount consumed from available cash before interest (kEUR).
        Always 0.0 when candidate is None.
    tranche_opening_balances_keur : Tuple[float, ...]
        Opening balance per tranche.
    tranche_gross_accrued_keur : Tuple[float, ...]
        Gross accrued interest per tranche.
    tranche_cash_int_paid_keur : Tuple[float, ...]
        Cash interest paid per tranche.
    tranche_pik_keur : Tuple[float, ...]
        PIK capitalized per tranche.
    tranche_principal_keur : Tuple[float, ...]
        Principal repaid per tranche.
    tranche_closing_balances_keur : Tuple[float, ...]
        Closing balance per tranche.
    """
    period_index: int
    opening_balance_keur: float
    drawdown_keur: float
    gross_accrued_interest_keur: float
    cash_interest_paid_keur: float
    pik_capitalized_keur: float
    principal_repaid_keur: float
    closing_balance_keur: float
    cash_consumed_by_shl_keur: float
    cash_after_shl_keur: float
    cash_for_distribution_keur: float
    pik_triggered: bool
    cash_sweep_100_pct: bool
    reserve_applied: bool
    distribution_account_r102_sweep_candidate_keur: float | None = None
    r102_sweep_applied_keur: float = 0.0
    tranche_opening_balances_keur: Tuple[float, ...] = ()
    tranche_gross_accrued_keur: Tuple[float, ...] = ()
    tranche_cash_int_paid_keur: Tuple[float, ...] = ()
    tranche_pik_keur: Tuple[float, ...] = ()
    tranche_principal_keur: Tuple[float, ...] = ()
    tranche_closing_balances_keur: Tuple[float, ...] = ()


@dataclass(frozen=True)
class ShlEngineResult:
    """Full SHL engine result across all periods.

    Attributes
    ----------
    project_name : str
        Project name.
    period_count : int
        Total number of periods.
    period_results : Tuple[ShlPeriodResult, ...]
        One result per period.
    total_gross_accrued_interest_keur : float
        Sum of gross accrued interest across all periods.
    total_cash_interest_paid_keur : float
        Sum of cash interest paid.
    total_pik_capitalized_keur : float
        Sum of PIK capitalized.
    total_principal_repaid_keur : float
        Sum of principal repaid.
    total_shl_debt_service_incl_wht_keur : float
        Total SHL debt service including WHT.
    total_cash_consumed_keur : float
        Total cash consumed by SHL.
    final_closing_balance_keur : float
        Final closing balance (should be ~0 if fully repaid).
    pik_period_count : int
        Number of periods with PIK > 0.
    cash_sweep_100_pct_period_count : int
        Number of periods with 100% cash sweep.
    audit_table : Tuple[ShlAuditRow, ...]
        Full audit table.
    """
    project_name: str
    period_count: int
    period_results: Tuple[ShlPeriodResult, ...]
    total_gross_accrued_interest_keur: float
    total_cash_interest_paid_keur: float
    total_pik_capitalized_keur: float
    total_principal_repaid_keur: float
    total_shl_debt_service_incl_wht_keur: float
    total_cash_consumed_keur: float
    final_closing_balance_keur: float
    pik_period_count: int
    cash_sweep_100_pct_period_count: int
    audit_table: Tuple["ShlAuditRow", ...]


@dataclass(frozen=True)
class ShlAuditRow:
    """One row of the SHL audit export.

    Attributes
    ----------
    period_index : int
        1-based semiannual period index.
    excel_col : str
        Excel column letter (e.g., "H", "AF").
    operating_period_index : int
        Semiannual operating period index (0–30).
    shl_opening_keur : float
        Opening balance.
    drawdown_keur : float
        New SHL funding drawn.
    shl_closing_keur : float
        Closing balance.
    gross_accrued_keur : float
        Gross accrued interest.
    cash_int_paid_keur : float
        Cash interest paid.
    pik_capitalized_keur : float
        PIK capitalized.
    post_senior_cash_keur : float
        Cash available after senior debt.
    cash_consumed_keur : float
        Total cash consumed by SHL.
    cash_after_shl_keur : float
        Cash after SHL service.
    cash_for_distribution_keur : float
        Cash available for distribution.
    pik_triggered : bool
        True if PIK > 0.
    cash_sweep_100_pct : bool
        True if 100% cash sweep.
    reserve_applied : bool
        True if reserve was applied.
    classification : str
        "SHL_Active", "SHL_Inactive", or "N/A".
    warnings : Tuple[str, ...]
        Non-fatal warnings.
    distribution_account_r102_sweep_candidate_keur : float | None
        R102 sweep candidate from DistributionAccount (kEUR). None if not provided.
    r102_sweep_applied_keur : float
        R102 sweep consumed from available cash (kEUR). 0.0 when candidate is None.
    """
    period_index: int
    excel_col: str
    operating_period_index: int
    shl_opening_keur: float
    drawdown_keur: float
    shl_closing_keur: float
    gross_accrued_keur: float
    cash_int_paid_keur: float
    pik_capitalized_keur: float
    post_senior_cash_keur: float
    cash_consumed_keur: float
    cash_after_shl_keur: float
    cash_for_distribution_keur: float
    pik_triggered: bool
    cash_sweep_100_pct: bool
    reserve_applied: bool
    classification: str
    warnings: Tuple[str, ...] = ()
    distribution_account_r102_sweep_candidate_keur: float | None = None
    r102_sweep_applied_keur: float = 0.0