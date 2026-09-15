"""
financial_engine.results — Immutable result types (Phase 2A + 2B).

All types are frozen dataclasses. No setattr, no post-construction mutation,
no mutable period lists.

Phase 2A provides: period_grid, operating_schedules.
Phase 2B adds: tax_and_cfads (annual tax, period cash tax, canonical CFADS).
Unimplemented: financing, financial_statements, returns.
"""
from __future__ import annotations

from dataclasses import dataclass
from datetime import date
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from financial_engine.provenance import EngineProvenance
    from financial_engine.validation import ValidationIssue
    from finco_core.engine.axis_contract import CanonicalAxisContract
    from financial_engine.tax.models import TaxAnnualResult


@dataclass(frozen=True)
class OperatingPeriodResult:
    """Immutable result for one period in the operating core."""
    period_index: int
    period_start: date
    period_end: date
    year_index: float
    period_in_year: float
    is_construction: bool
    is_operation: bool
    is_ppa_active: bool
    days_in_period: int
    day_fraction: float

    production_mwh: float
    revenue_keur: float
    opex_keur: float
    ebitda_keur: float
    book_depreciation_keur: float
    tax_depreciation_keur: float
    ebit_keur: float


@dataclass(frozen=True)
class OperatingSchedules:
    """Period-indexed operating schedule arrays."""
    period_indices: tuple[int, ...]
    production_mwh: tuple[float, ...]
    revenue_keur: tuple[float, ...]
    opex_keur: tuple[float, ...]
    ebitda_keur: tuple[float, ...]
    book_depreciation_keur: tuple[float, ...]
    tax_depreciation_keur: tuple[float, ...]
    ebit_keur: tuple[float, ...]


@dataclass(frozen=True)
class TaxAndCfadsSchedules:
    """Parallel-array tax and CFADS schedules for all model periods.

    Field names match the Phase 1 baseline snapshot schema for tax_and_cfads.

    Phase 2B populates all fields that the clean engine computes.
    Unimplemented waterfall rows (fcf_for_shl, r69, r84, r99, r102) are NOT
    included here — they belong to Phase 2C+ and are declared unavailable in
    the candidate snapshot's unavailable_fields map.

    terminal_unpaid_tax_keur : annual CIT liabilities whose cash-tax payment
        falls outside the model horizon due to the payment lag.
    """
    period_indices: tuple[int, ...]
    # Taxable income trail
    taxable_profit_keur: tuple[float, ...]
    taxable_income_before_losses_audit_keur: tuple[float, ...]
    taxable_profit_after_losses_audit_keur: tuple[float, ...]
    # Tax (accrual and cash)
    tax_keur: tuple[float, ...]                          # CIT accrual share per period
    corporate_tax_cash_keur: tuple[float, ...]           # actual cash payment per period
    cit_accrual_audit_keur: tuple[float, ...]
    cash_tax_bridge_reconciliation_keur: tuple[float, ...]
    cash_tax_current_period_audit_keur: tuple[float, ...]
    # LCF audit trail
    tax_loss_opening_audit_keur: tuple[float, ...]
    tax_loss_closing_audit_keur: tuple[float, ...]
    tax_loss_used_audit_keur: tuple[float, ...]
    # Supplementary audit fields
    fiscal_reintegration_audit_keur: tuple[float, ...]
    tax_depreciation_audit_keur: tuple[float, ...]
    cf_after_tax_keur: tuple[float, ...]  # EBITDA - cash_tax per period (matches legacy definition)
    # Canonical CFADS (primary deliverable)
    cfads_keur: tuple[float, ...]
    # Terminal unpaid tax (annual liabilities not yet paid within the model horizon)
    terminal_unpaid_tax_keur: float
    capitalisation_ratio_audit: tuple[float | None, ...] = ()
    capitalisation_gate_audit: tuple[bool | None, ...] = ()
    shl_gross_interest_audit_keur: tuple[float, ...] = ()
    shl_deductible_interest_audit_keur: tuple[float, ...] = ()
    shl_disallowed_interest_audit_keur: tuple[float, ...] = ()
    shl_absolute_limit_component_audit_keur: tuple[float, ...] = ()
    shl_ebitda_limit_component_audit_keur: tuple[float, ...] = ()
    shl_additional_non_deductible_component_audit_keur: tuple[float, ...] = ()
    # Canonical annual tax authority — typed handoff of the already-computed
    # TaxAndCfadsResult.annual_results.  Tax is NOT recomputed; this retains
    # the result produced by calculate_tax() so downstream consumers (incl. the
    # freeze evidence contract) can inspect the authoritative FIFO ledger without
    # a side-channel recalculation.
    annual_results: tuple["TaxAnnualResult", ...] = ()


@dataclass(frozen=True)
class SeniorDebtSchedules:
    """Phase 2C per-period senior debt schedules.

    base_dscr: Base-case actual DSCR (base_cfads / senior_ds) per period.
        None where debt service is zero (avoids division by zero).
        C3B3D2B4: renamed from senior_dscr (which was Bank DSCR — a misnomer).
        The backward-compat property senior_dscr is preserved below.
    debt_size_keur: final sized/solved opening debt balance at COD.
    binding_constraint: "DSCR", "GEARING", "BOTH", or None.
    diagnostics: solver convergence metadata (dict for JSON serialisability).
    """
    period_indices: tuple[int, ...]
    senior_debt_opening_keur: tuple[float, ...]
    senior_interest_keur: tuple[float, ...]
    senior_principal_keur: tuple[float, ...]
    senior_debt_service_keur: tuple[float, ...]
    senior_debt_closing_keur: tuple[float, ...]
    base_dscr: tuple[float | None, ...]
    debt_size_keur: float
    binding_constraint: str | None
    diagnostics: dict  # SolverDiagnostics serialised to dict

    @property
    def senior_dscr(self) -> tuple[float | None, ...]:
        """Backward-compat alias for base_dscr.

        SENIOR_DSCR_LEGACY_NAME_MIGRATED_TO_BASE_ACTUAL_DSCR (C3B3D2B4):
        All callers compare against Base-case reference debt serviceCR rows; the migration
        from ``senior_dscr`` (which was inadvertently Bank DSCR) to
        ``base_dscr`` is semantically correct.  Prefer ``base_dscr`` in new code.

        Serialization contract: dataclasses.asdict() serialises dataclass
        FIELDS only; ``senior_dscr`` is a property and is NOT included in
        asdict output.  ``base_dscr`` (the field) IS included.  Callers that
        require the value in serialised form must use ``base_dscr`` directly.
        """
        return self.base_dscr


@dataclass(frozen=True)
class DebtSizingSchedules:
    """Phase 2C bank/debt-sizing case economic schedules.

    Captures the bank-case operating and CFADS outputs used as inputs to the
    DSCR sizing constraint.  The Base case results remain in operating_schedules
    and tax_and_cfads; these schedules reflect the debt-sizing yield scenario
    (and optional merchant price override) from DebtSizingCaseInput.

    bank_cfads_keur:
        Canonical bank-case CFADS (bank EBITDA − bank cash tax) used as the
        DSCR denominator in the senior debt sculpting algorithm.  NOT Base CFADS.
    bank_sizing_dscr:
        Bank-case sizing DSCR per period (bank_cfads / senior_ds).
        None where debt service is zero. This is the lender constraint metric.
        NOT the Base actual DSCR — see SeniorDebtSchedules.base_dscr for that.
    """
    period_indices: tuple[int, ...]
    bank_production_mwh: tuple[float, ...]
    bank_revenue_keur: tuple[float, ...]
    bank_opex_keur: tuple[float, ...]
    bank_ebitda_keur: tuple[float, ...]
    bank_cash_tax_keur: tuple[float, ...]
    bank_cfads_keur: tuple[float, ...]
    bank_sizing_dscr: tuple[float | None, ...]
    solver_bank_dscr: tuple[float | None, ...]
    """Solver-internal Bank DSCR at convergence (sd_result.senior_dscr per period).

    SOLVER_BANK_DSCR_HANDSHAKE_PROOF (C3B3D2B4.2):
    The solver populates senior_dscr as bank_cfads / senior_ds from its internal
    fixed-point iterations.  Exposing it here enables period-by-period handshake:
    solver_bank_dscr[p] * senior_ds[p] ≈ bank_cfads_keur[p]  (within solver tolerance).
    """


@dataclass(frozen=True)
class PostSeniorCashSchedules:
    """Phase 2C post-senior-debt cash schedules (C3B3D2B4).

    Captures Base-case cash remaining after senior debt service — the explicit
    pre-reserve downstream cash authority.  Bank CFADS is NOT included here;
    it is sizing-only and confined to DebtSizingSchedules.

    DSRA_NOT_IMPLEMENTED_IN_THIS_STAGE_POST_SENIOR_CASH_IS_PRE_RESERVE:
    DSRA ordering is unresolved; these figures are pre-reserve.  Do not label
    them as SHL cash or distributable cash without further waterfall evidence.

    All fields are parallel arrays indexed by period_index (all model periods,
    including construction).

    cash_after_senior_before_reserves_keur:
        Signed: base_cfads − senior_ds.  Negative = CFADS insufficient to
        cover senior debt service.  Pre-reserve; DSRA ordering unresolved.

    cash_available_for_shl_before_reserves_keur:
        max(0, cash_after_senior_before_reserves_keur) for operating periods.
        CONSTRUCTION_SHL_AVAILABLE_CASH_IS_ZERO_BY_CONTRACT: construction
        periods return 0.0 regardless of CFADS (SHL is PIK during construction).
        Pre-reserve; DSRA ordering unresolved.
    """
    period_indices: tuple[int, ...]
    base_cfads_keur: tuple[float, ...]
    senior_debt_service_keur: tuple[float, ...]
    cash_after_senior_before_reserves_keur: tuple[float, ...]
    cash_available_for_shl_before_reserves_keur: tuple[float, ...]


@dataclass(frozen=True)
class ShareholderLoanDiagnostics:
    """Convergence diagnostics for the SHL + tax + senior-debt fixed point."""
    converged: bool
    is_authoritative: bool
    iteration_count: int
    max_iterations: int
    convergence_tolerance_keur: float
    convergence_relative_tolerance: float
    max_closing_delta_keur: float
    max_interest_delta_keur: float
    termination_reason: str
    max_final_shl_interest_handshake_delta_keur: float = 0.0
    max_final_shl_closing_handshake_delta_keur: float = 0.0
    max_retained_earnings_delta_keur: float = 0.0
    max_capitalisation_ratio_delta: float = 0.0
    capitalisation_gate_mismatch_count: int = 0


@dataclass(frozen=True)
class ShareholderLoanSchedules:
    """Immutable SHL audit vectors.

    POST_SHL_CASH_IS_PRE_RESERVE: cash remaining after SHL is still before any
    DSRA/reserve/distribution layer. It must not be labelled distributable cash.
    """
    period_indices: tuple[int, ...]
    shl_opening_keur: tuple[float, ...]
    shl_drawdown_keur: tuple[float, ...]
    shl_gross_interest_keur: tuple[float, ...]
    shl_cash_interest_keur: tuple[float, ...]
    shl_pik_interest_keur: tuple[float, ...]
    shl_principal_keur: tuple[float, ...]
    shl_debt_service_keur: tuple[float, ...]
    shl_closing_keur: tuple[float, ...]
    cash_available_for_shl_before_reserves_keur: tuple[float, ...]
    cash_remaining_after_shl_before_reserves_keur: tuple[float, ...]
    diagnostics: ShareholderLoanDiagnostics


@dataclass(frozen=True)
class ProjectModelResult:
    """Top-level immutable result for a clean engine run.

    Phase 2A populates: period_grid, operating_schedules.
    Phase 2B additionally populates: tax_and_cfads.
    Phase 2C additionally populates: senior_debt, debt_sizing, post_senior_cash.
    Sections declared unavailable: financing, financial_statements, returns.
    """
    provenance: "EngineProvenance"
    periods: tuple[OperatingPeriodResult, ...]
    operating_schedules: OperatingSchedules
    unavailable_sections: tuple[str, ...]
    validation_issues: tuple["ValidationIssue", ...]
    warnings: tuple[str, ...]
    tax_and_cfads: TaxAndCfadsSchedules | None = None
    senior_debt: "SeniorDebtSchedules | None" = None
    debt_sizing: "DebtSizingSchedules | None" = None
    post_senior_cash: "PostSeniorCashSchedules | None" = None
    shareholder_loan: "ShareholderLoanSchedules | None" = None
    cash_dsra: "object | None" = None  # CashDsraSchedules | None — PR-3 reserve authority
    # PR-F1 Correction F: immutable canonical axis contract (runtime-only, not serialized).
    # Populated by run_senior_debt_model and _run_senior_debt_model_with_shl after the
    # contract is constructed from typed periods and SeniorDebtPolicy bounds — BEFORE
    # any solver output is accepted.  Downstream consumers use this for Senior axis
    # enforcement instead of self-deriving from result.senior_debt.period_indices.
    axis_contract: "CanonicalAxisContract | None" = None
