"""Immutable G2A Sources & Uses and financing-stack audit contracts."""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import date
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from finco_core.inputs.book_depreciable_asset_basis import BookDepreciableAssetBasis


@dataclass(frozen=True)
class ProjectUses:
    hard_project_capex_keur: float
    explicit_financing_cost_uses_keur: float
    reserve_account_funding_keur: float
    other_explicit_project_uses_keur: float
    total_project_uses_keur: float


@dataclass(frozen=True)
class ConstructionFundingPeriod:
    period_index: int
    project_cash_uses_keur: float
    senior_draw_keur: float
    junior_or_other_main_funding_draw_keur: float
    share_capital_draw_keur: float
    share_premium_draw_keur: float
    other_committed_equity_draw_keur: float
    additional_equity_draw_keur: float
    shl_cash_draw_keur: float
    total_sponsor_cash_draw_keur: float
    total_sources_keur: float
    sources_uses_difference_keur: float
    cumulative_project_cash_uses_keur: float
    cumulative_senior_draw_keur: float
    cumulative_junior_or_other_main_funding_draw_keur: float
    cumulative_share_capital_draw_keur: float
    cumulative_share_premium_draw_keur: float
    cumulative_other_committed_equity_draw_keur: float
    cumulative_additional_equity_draw_keur: float
    cumulative_shl_cash_draw_keur: float
    cumulative_total_sources_keur: float
    cumulative_sources_uses_difference_keur: float
    # Canonical period axis dates (Fix 3: single source of truth from model periods).
    # None = legacy path (no explicit model period dates available).
    period_start: date | None = None
    period_end: date | None = None
    cashflow_date: date | None = None
    # GAP 2 — ALL_AT_FC prefunding bridge (Fix 3 closeout).
    # shl_allocation_to_uses_keur: from SPONSOR_FIRST_RESIDUAL_SENIOR waterfall (Layer A).
    # sponsor_shl_cash_contribution_keur: from SponsorFundingTimingPolicy (Layer B cash in).
    # For PRO_RATA: allocation == contribution (no prefunding balance).
    # For ALL_AT_FC: contribution[0] = full principal; allocation follows waterfall; bridge tracks excess.
    shl_allocation_to_uses_keur: float = 0.0
    sponsor_shl_cash_contribution_keur: float = 0.0
    opening_unutilised_shl_cash_keur: float = 0.0
    closing_unutilised_shl_cash_keur: float = 0.0


@dataclass(frozen=True)
class NonConstructionFcUse:
    """A typed FC/COD project use that is NOT part of the construction timeline.

    Policy: NON_CONSTRUCTION_FC_USES
    Typical source: CASH_DSRA reserve account funding, other COD lump-sum uses.
    These uses do NOT participate in Stage-B2 IDC calculation.
    """
    policy: str  # e.g. "NON_CONSTRUCTION_FC_USES"
    uses_keur: float
    senior_draw_keur: float
    shl_draw_keur: float
    junior_draw_keur: float
    share_capital_draw_keur: float
    share_premium_draw_keur: float
    other_committed_equity_draw_keur: float
    additional_equity_draw_keur: float
    total_sources_keur: float
    residual_keur: float  # total_sources - uses_keur (should be ~0)


@dataclass(frozen=True)
class ConstructionFundingResult:
    policy: str
    periods: tuple[ConstructionFundingPeriod, ...]
    maximum_period_difference_keur: float
    maximum_cumulative_difference_keur: float
    # PR-9: non-construction FC/COD uses (e.g. CASH_DSRA reserve funding).
    # None when total_project_uses == sum(construction period uses).
    non_construction_fc_use: "NonConstructionFcUse | None" = None
    # Full-audit totals: construction + non-construction == total_project_uses.
    total_audit_uses_keur: float = 0.0
    total_audit_sources_keur: float = 0.0
    total_audit_residual_keur: float = 0.0


@dataclass(frozen=True)
class ConstructionFinancingResult:
    """Typed result for the PR-9 outer G2A fixed point with construction IDC.

    Authority: PR9_TYPED_CONSTRUCTION_FINANCING_IDC_AUTHORITY
    """
    # Period data
    period_start_dates: tuple[date, ...]
    period_end_dates: tuple[date, ...]
    hard_capex_uses_keur: tuple[float, ...]
    total_period_uses_keur: tuple[float, ...]
    senior_draws_keur: tuple[float, ...]
    cumulative_senior_keur: tuple[float, ...]
    senior_idc_accrual_keur: tuple[float, ...]
    senior_commitment_fee_accrual_keur: tuple[float, ...]
    structuring_fee_keur: tuple[float, ...]
    shl_allocation_keur: tuple[float, ...]
    shl_cash_contribution_keur: tuple[float, ...]
    shl_day_count_fraction: tuple[float, ...]
    shl_pik_accrual_keur: tuple[float, ...]
    # Scalar results
    total_capitalized_financing_keur: float
    shl_construction_pik_keur: float
    opening_operating_shl_keur: float
    final_total_project_uses_keur: float
    final_senior_commitment_keur: float
    sources_uses_residual_keur: float
    # Convergence audit
    outer_iterations: int
    outer_residual_keur: float
    stage_b2_iterations: int
    stage_b2_residual_keur: float
    # Source period vectors from canonical allocator (all None-safe tuples)
    share_capital_draws_keur: tuple[float, ...] = ()
    share_premium_draws_keur: tuple[float, ...] = ()
    other_committed_equity_draws_keur: tuple[float, ...] = ()
    additional_equity_draws_keur: tuple[float, ...] = ()
    junior_draws_keur: tuple[float, ...] = ()
    # Per-period sources-uses residuals
    period_sources_uses_residual_keur: tuple[float, ...] = ()
    maximum_period_residual_keur: float = 0.0
    maximum_cumulative_residual_keur: float = 0.0
    # Outer convergence component residuals (Section 12 — for diagnostics)
    outer_idc_residual_keur: float = 0.0
    outer_fee_residual_keur: float = 0.0
    outer_struct_residual_keur: float = 0.0
    outer_senior_residual_keur: float = 0.0
    outer_shl_residual_keur: float = 0.0
    outer_pik_residual_keur: float = 0.0
    outer_uses_residual_keur: float = 0.0
    # Final idempotence verification residual (Section 14)
    final_verification_outer_residual_keur: float = 0.0
    # Typed VAT-facility audit vectors and authority.
    vat_payable_keur: tuple[float, ...] = ()
    vat_requirement_keur: tuple[float, ...] = ()
    vat_drawn_keur: tuple[float, ...] = ()
    vat_undrawn_keur: tuple[float, ...] = ()
    senior_idc_capitalized_uses_keur: tuple[float, ...] = ()
    # Canonical capitalized commitment fee scalar (sum of capitalized fee uses).
    # Source: b2.capitalized_financing_costs.senior_commitment_fee_keur.
    # NOT sum(senior_commitment_fee_accrual_keur) — use this field for the basis.
    senior_commitment_fee_capitalized_keur: float = 0.0
    vat_idc_keur: float = 0.0
    vat_commitment_fee_keur: float = 0.0
    vat_commitment_mode: str = "DISABLED"
    vat_effective_commitment_keur: float = 0.0
    vat_peak_requirement_keur: float = 0.0
    vat_peak_requirement_period: int = 0
    vat_authority: str = "TYPED_CONSTRUCTION_VAT_FACILITY_DISABLED"
    # Authority token
    authority: str = "PR9_TYPED_CONSTRUCTION_FINANCING_IDC_AUTHORITY"


@dataclass(frozen=True)
class ProjectFinancingResult:
    project_model_result: object
    project_uses: ProjectUses
    dscr_debt_capacity_keur: float
    gearing_basis_keur: float
    gearing_ratio: float
    gearing_debt_capacity_keur: float
    final_senior_commitment_keur: float
    binding_senior_constraint: str
    junior_or_other_main_project_funding_keur: float
    share_capital_keur: float
    share_premium_keur: float
    other_equity_funding_before_shl_keur: float
    additional_equity_keur: float
    derived_shl_cash_principal_keur: float
    shl_construction_pik_keur: float
    opening_operating_shl_balance_keur: float
    construction_funding: ConstructionFundingResult
    fixed_point_iteration_count: int
    fixed_point_maximum_difference_keur: float
    # PR-9 typed construction financing result (None when construction_financing disabled)
    construction_financing: "ConstructionFinancingResult | None" = None
    # Canonical book depreciable asset basis — exposed for downstream consumers
    # (C3 financial statements, depreciation schedule audit). Always non-None for
    # projects processed through run_project_financing_model.
    book_depreciable_asset_basis: "BookDepreciableAssetBasis | None" = None
    # Exact typed SHL contract used by the converged financing model. This is
    # a downstream handoff, not a second principal authority.
    shareholder_loan_model_input: object | None = None
    # U2 Correction F C3 handoff: cash/reserve interest income schedule.
    # None when no policy is configured (authority=UNRESOLVED or policy=None).
    # C3 uses this to replace FINANCING_INCOME_AUTHORITY_UNAVAILABLE /
    # UNRESTRICTED_CASH_AUTHORITY_UNAVAILABLE sentinel strings.
    cash_reserve_interest_schedules: object | None = None  # CashReserveInterestSchedules | None
