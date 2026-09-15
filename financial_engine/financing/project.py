"""Project-owned G2A financing fixed point over existing clean kernels."""

from __future__ import annotations

from dataclasses import dataclass, replace
import math
from numbers import Real

from finco_core.inputs import GearingBasisMode, ProjectInputs, SponsorFundingMode
from finco_core._numeric import require_finite_real
from financial_engine.adapters.project_inputs import (
    build_senior_debt_model_input_from_project_inputs,
    _coerce_shl_day_count,
)
from domain.construction.config import FundingSourceCaps
from domain.construction.funding_allocation import allocate_source_waterfall
from finco_core.construction.allocator import ConstructionPeriodAllocation
from financial_engine.financing.contracts import (
    ConstructionFundingPeriod,
    ConstructionFundingResult,
    ConstructionFinancingResult,
    ProjectFinancingResult,
    ProjectUses,
)
from financial_engine.financing.project_uses import compute_project_uses
from financial_engine.financing.stack import (
    build_construction_funding_schedule,
    reconcile_financing_stack,
)
from financial_engine.adapters.project_inputs import from_project_inputs
from financial_engine.orchestrator import run_operating_model, run_senior_debt_model
from financial_engine.shl.construction import (
    build_shl_construction_draw_schedule,
    compute_shl_construction_schedule,
    ShlConstructionPeriodInput,
)
from finco_core.inputs._models import (
    ShlConstructionDayCountConvention,
    SponsorFundingTimingPolicy,
)
from financial_engine.shl.day_count import compute_shl_dcf


# Dimensionless comparison tolerance for typed-date DCF authority. Financial
# convergence tolerances are denominated in kEUR and must never participate.
SHL_DCF_AUTHORITY_TOLERANCE = 1e-9

# Fixed kEUR equality tolerance for canonical CAPEX authority. Solver
# convergence tolerance must never decide whether a CAPEX input exists.
PR9_CAPEX_AUTHORITY_TOLERANCE_KEUR = 1e-6

# Construction SHL accrual semantics (Fix 3):
#
# None  → no explicit construction DCF authority. Fall back to model_result.shareholder_loan
#         (backward-compat path). Generic Solar/Wind return 0 PIK here because those projects
#         have no explicit construction SHL DCF configured.
# 0.0   → explicit zero accrual. Distinct from None — activates timing path but produces 0 PIK.
# > 0.0 → timing policy resolves construction draw schedule per-period inside the fixed-point loop.
#          Multi-period causal integration: per-period DCFs are derived from the operating model
#          (run once pre-loop, calendar-derived, timing-policy-independent).
#          ALL_AT_FC vs PRO_RATA produce different opening SHL and hence different DSCR capacity.
#          Backward compat: None/0.0 DCF path unchanged (Solar PIK=0, Wind PIK=0).


@dataclass(frozen=True)
class _ShlConstructionDcfAuthority:
    """Validated interpretation of the legacy construction DCF scalar."""

    state: str
    accrual_enabled: bool
    validation_scalar: float | None


def _resolve_shl_construction_dcf_authority(
    raw_scalar: object,
) -> _ShlConstructionDcfAuthority:
    """Resolve None, zero, or positive dimensionless DCF evidence once."""
    if raw_scalar is None:
        return _ShlConstructionDcfAuthority("NONE", False, None)
    if isinstance(raw_scalar, bool) or not isinstance(raw_scalar, Real):
        raise ValueError(
            "PR9_SHL_CONSTRUCTION_DCF_INVALID: "
            f"expected a real dimensionless scalar, got {raw_scalar!r}"
        )
    scalar = float(raw_scalar)
    if not math.isfinite(scalar) or scalar < 0.0:
        raise ValueError(
            "PR9_SHL_CONSTRUCTION_DCF_INVALID: "
            f"expected None, zero, or a positive finite scalar, got {raw_scalar!r}"
        )
    if scalar == 0.0:
        return _ShlConstructionDcfAuthority("ZERO", False, 0.0)
    return _ShlConstructionDcfAuthority("POSITIVE", True, scalar)


def _validate_typed_construction_shl_rate(raw_rate: object) -> float:
    """Fail closed before typed construction SHL financial arithmetic."""
    if isinstance(raw_rate, bool) or not isinstance(raw_rate, Real):
        raise ValueError(
            "PR9_SHL_CONSTRUCTION_RATE_INVALID: "
            f"expected a real annual rate, got {raw_rate!r}"
        )
    rate = float(raw_rate)
    if not math.isfinite(rate) or rate < 0.0:
        raise ValueError(
            "PR9_SHL_CONSTRUCTION_RATE_INVALID: "
            f"expected a finite non-negative annual rate, got {raw_rate!r}"
        )
    return rate


@dataclass(frozen=True)
class _TypedConstructionShlContext:
    """Explicit PR-9 handoff from Stage B2 allocation to the SHL kernel."""

    periods: tuple[ShlConstructionPeriodInput, ...]
    period_dates: tuple[tuple, ...]
    shl_allocation_to_uses_keur: tuple[float, ...]
    canonical_allocations: tuple[ConstructionPeriodAllocation, ...]
    timing_policy: SponsorFundingTimingPolicy
    accrual_enabled: bool
    provisional: bool


def _typed_construction_shl_context(
    *,
    construction: object,
    financing: object,
    canonical_allocations: tuple[ConstructionPeriodAllocation, ...],
    provisional: bool,
) -> _TypedConstructionShlContext:
    """Derive SHL periods only from typed PR-9 dates and SHL day count."""
    funding_periods = tuple(construction.periods)
    if len(canonical_allocations) != len(funding_periods):
        raise ValueError(
            "PR9_TYPED_SHL_PERIOD_COUNT_MISMATCH: "
            f"allocations={len(canonical_allocations)}, periods={len(funding_periods)}"
        )
    tail_periods = tuple(getattr(construction, "shl_accrual_tail_periods", ()))
    typed_periods = funding_periods + tail_periods
    zero_tail_allocations = tuple(
        ConstructionPeriodAllocation(
            period_index=len(funding_periods) + index,
            period_uses_keur=0.0,
            share_capital_draw_keur=0.0,
            share_premium_draw_keur=0.0,
            other_committed_equity_draw_keur=0.0,
            additional_equity_draw_keur=0.0,
            shl_draw_keur=0.0,
            junior_draw_keur=0.0,
            senior_draw_keur=0.0,
            total_sources_keur=0.0,
            residual_keur=0.0,
        )
        for index, _ in enumerate(tail_periods)
    )
    effective_allocations = canonical_allocations + zero_tail_allocations
    convention = _coerce_shl_day_count(financing.shl_day_count_convention)
    construction_day_count = getattr(
        financing,
        "shl_construction_day_count_convention",
        ShlConstructionDayCountConvention.OPERATING_SHL_CONVENTION,
    )
    if construction_day_count is ShlConstructionDayCountConvention.ELAPSED_ACT_365_FIXED:
        axis_start = typed_periods[0].start_date
        prior_end = axis_start
        elapsed_dcfs = []
        for period in typed_periods:
            elapsed_dcfs.append((period.end_date - prior_end).days / 365.0)
            prior_end = period.end_date
        derived_dcfs = tuple(elapsed_dcfs)
    else:
        derived_dcfs = tuple(
            compute_shl_dcf(period.start_date, period.end_date, convention)
            for period in typed_periods
        )
    authority = _resolve_shl_construction_dcf_authority(
        financing.shl_construction_day_count_fraction
    )
    if authority.accrual_enabled:
        assert authority.validation_scalar is not None
        if (
            abs(sum(derived_dcfs) - authority.validation_scalar)
            > SHL_DCF_AUTHORITY_TOLERANCE
        ):
            raise ValueError(
                "PR9_DUAL_SHL_CONSTRUCTION_DCF_AUTHORITY_MISMATCH: "
                f"typed_total={sum(derived_dcfs):.12f}, "
                f"legacy_scalar={authority.validation_scalar:.12f}, "
                f"dimensionless_tolerance={SHL_DCF_AUTHORITY_TOLERANCE:.1e}"
            )
        effective_dcfs = derived_dcfs
    else:
        # Existing None/zero contracts explicitly disable construction SHL
        # accrual. Dates still come only from the typed PR-9 axis.
        effective_dcfs = tuple(0.0 for _ in typed_periods)
    return _TypedConstructionShlContext(
        periods=tuple(
            ShlConstructionPeriodInput(
                draw_keur=0.0,
                day_count_fraction=dcf,
                period_index=index,
            )
            for index, dcf in enumerate(effective_dcfs)
        ),
        period_dates=tuple(
            (period.start_date, period.end_date, period.end_date)
            for period in typed_periods
        ),
        shl_allocation_to_uses_keur=tuple(
            allocation.shl_draw_keur for allocation in effective_allocations
        ),
        canonical_allocations=effective_allocations,
        timing_policy=financing.sponsor_funding_timing_policy,
        accrual_enabled=authority.accrual_enabled,
        provisional=provisional,
    )


def _project_uses(project_inputs: ProjectInputs) -> ProjectUses:
    """Thin wrapper — delegates to the canonical compute_project_uses authority."""
    return compute_project_uses(project_inputs)


def _build_generic_book_basis(capex_structure):
    """Build BookDepreciableAssetBasis for the generic (Solar/Wind) path."""
    from financial_engine.book_basis import build_book_depreciable_asset_basis
    return build_book_depreciable_asset_basis(capex_structure, construction_financing_result=None)


def _provisional_typed_construction_funding(
    context: _TypedConstructionShlContext,
    cash_contributions_keur: tuple[float, ...],
) -> ConstructionFundingResult:
    """Expose outer-state lag without weakening the strict funding validator."""
    cumulative = {
        "uses": 0.0,
        "senior": 0.0,
        "junior": 0.0,
        "share": 0.0,
        "premium": 0.0,
        "other": 0.0,
        "additional": 0.0,
        "shl": 0.0,
        "sources": 0.0,
    }
    unutilised = 0.0
    rows = []
    for allocation, contribution, dates in zip(
        context.canonical_allocations,
        cash_contributions_keur,
        context.period_dates,
    ):
        cumulative["uses"] += allocation.period_uses_keur
        cumulative["senior"] += allocation.senior_draw_keur
        cumulative["junior"] += allocation.junior_draw_keur
        cumulative["share"] += allocation.share_capital_draw_keur
        cumulative["premium"] += allocation.share_premium_draw_keur
        cumulative["other"] += allocation.other_committed_equity_draw_keur
        cumulative["additional"] += allocation.additional_equity_draw_keur
        cumulative["shl"] += allocation.shl_draw_keur
        cumulative["sources"] += allocation.total_sources_keur
        closing_unutilised = (
            unutilised + contribution - allocation.shl_draw_keur
        )
        rows.append(ConstructionFundingPeriod(
            period_index=allocation.period_index + 1,
            project_cash_uses_keur=allocation.period_uses_keur,
            senior_draw_keur=allocation.senior_draw_keur,
            junior_or_other_main_funding_draw_keur=allocation.junior_draw_keur,
            share_capital_draw_keur=allocation.share_capital_draw_keur,
            share_premium_draw_keur=allocation.share_premium_draw_keur,
            other_committed_equity_draw_keur=allocation.other_committed_equity_draw_keur,
            additional_equity_draw_keur=allocation.additional_equity_draw_keur,
            shl_cash_draw_keur=allocation.shl_draw_keur,
            total_sponsor_cash_draw_keur=(
                allocation.share_capital_draw_keur
                + allocation.share_premium_draw_keur
                + allocation.other_committed_equity_draw_keur
                + allocation.additional_equity_draw_keur
                + allocation.shl_draw_keur
            ),
            total_sources_keur=allocation.total_sources_keur,
            sources_uses_difference_keur=allocation.residual_keur,
            cumulative_project_cash_uses_keur=cumulative["uses"],
            cumulative_senior_draw_keur=cumulative["senior"],
            cumulative_junior_or_other_main_funding_draw_keur=cumulative["junior"],
            cumulative_share_capital_draw_keur=cumulative["share"],
            cumulative_share_premium_draw_keur=cumulative["premium"],
            cumulative_other_committed_equity_draw_keur=cumulative["other"],
            cumulative_additional_equity_draw_keur=cumulative["additional"],
            cumulative_shl_cash_draw_keur=cumulative["shl"],
            cumulative_total_sources_keur=cumulative["sources"],
            cumulative_sources_uses_difference_keur=(
                cumulative["sources"] - cumulative["uses"]
            ),
            period_start=dates[0],
            period_end=dates[1],
            cashflow_date=dates[2],
            shl_allocation_to_uses_keur=allocation.shl_draw_keur,
            sponsor_shl_cash_contribution_keur=contribution,
            opening_unutilised_shl_cash_keur=unutilised,
            closing_unutilised_shl_cash_keur=closing_unutilised,
        ))
        unutilised = closing_unutilised
    period_residuals = tuple(row.sources_uses_difference_keur for row in rows)
    cumulative_residuals = tuple(
        row.cumulative_sources_uses_difference_keur for row in rows
    )
    return ConstructionFundingResult(
        policy="PR9_PROVISIONAL_OUTER_STATE_AUDIT",
        periods=tuple(rows),
        maximum_period_difference_keur=max(
            (abs(value) for value in period_residuals), default=0.0
        ),
        maximum_cumulative_difference_keur=max(
            (abs(value) for value in cumulative_residuals), default=0.0
        ),
        total_audit_uses_keur=cumulative["uses"],
        total_audit_sources_keur=cumulative["sources"],
        total_audit_residual_keur=cumulative["sources"] - cumulative["uses"],
    )


def _run_with_construction_idc(
    *,
    project_inputs: ProjectInputs,
    source_id: str,
    baseline_commit_sha: str,
    outer_tolerance_keur: float,
    outer_max_iterations: int,
    _u2_period_financing_income: "tuple | None" = None,
) -> "ProjectFinancingResult":
    """Outer G2A / construction IDC fixed point for construction_financing.enabled=True.

    Each outer iteration:
      1. Derives canonical construction CAPEX amounts from ProjectInputs.capex.
      2. Runs Stage B2 (with current Senior/SHL estimates) to compute IDC, commitment
         fee, and structuring fee.
      3. Applies those costs IMMUTABLY to the original base CapexStructure (never
         accumulates across iterations).
      4. Recomputes Total Project Uses on the updated CapexStructure.
      5. Calls the inner SHL/Senior fixed point (run_project_financing_model without
         construction gate) on the updated project inputs.
      6. Checks outer convergence: max(|ΔSenior|, |ΔSHL|, |ΔProjectUses|, |ΔIDC|, |Δfee|).
      7. After convergence: one final verification iteration confirms idempotence.

    On convergence: builds ConstructionFinancingResult and returns full ProjectFinancingResult.
    """
    from finco_core.construction.stage_b2 import (
        apply_capitalized_financing_costs,
        run_stage_b2,
        run_stage_b2_provisional,
        CapitalizedFinancingCosts,
    )
    from financial_engine.construction.adapter import (
        build_construction_runtime_config,
        resolve_capex_amounts_from_capex_structure,
    )

    fin = project_inputs.financing
    cf = fin.construction_financing  # guaranteed non-None and enabled
    _validate_typed_construction_shl_rate(fin.shl_rate)

    # Validate: fail if manual IDC/fees already set (would create dual authority)
    orig_capex = project_inputs.capex
    if (
        getattr(orig_capex, "idc_keur", 0.0) != 0.0
        or getattr(orig_capex, "commitment_fees_keur", 0.0) != 0.0
        or getattr(orig_capex, "bank_fees_keur", 0.0) != 0.0
    ):
        raise ValueError(
            "PR9_MANUAL_DERIVED_CONSTRUCTION_COST_CONFLICT: "
            "construction_financing.enabled=True but CapexStructure already contains "
            "non-zero idc_keur/commitment_fees_keur/bank_fees_keur. "
            "Clear those fields when using typed construction authority."
        )

    # Manual VAT financing costs are the same dual-authority conflict as
    # manual Senior construction costs. VAT rates/facility inputs are allowed;
    # derived VAT financing amounts must start at zero.
    if any(
        getattr(orig_capex, field_name, 0.0) != 0.0
        for field_name in (
            "vat_costs_keur",
            "vat_facility_idc_keur",
            "vat_facility_commitment_fee_keur",
        )
    ):
        raise ValueError(
            "PR9_MANUAL_DERIVED_VAT_FINANCING_COST_CONFLICT: typed VAT facility "
            "authority requires zero manual vat_costs_keur / VAT IDC / commitment fee"
        )

    # Resolve CAPEX amounts from canonical CapexStructure.
    # Construction timing inputs own payment_weights; amounts come from ProjectInputs.capex.
    capex_amounts = resolve_capex_amounts_from_capex_structure(
        cf.capex_items, orig_capex
    )

    # Fix 1: validate CAPEX authority using the correct property name.
    canonical_hard_capex = orig_capex.hard_capex_keur

    # Validate: no duplicate codes
    codes_seen: list[str] = [item.code for item in cf.capex_items]
    if len(codes_seen) != len(set(codes_seen)):
        from collections import Counter
        dupes = [c for c, n in Counter(codes_seen).items() if n > 1]
        raise ValueError(
            f"PR9_CONSTRUCTION_CAPEX_AUTHORITY_MISMATCH: "
            f"duplicate capex_item codes: {dupes}"
        )

    # Validate: no omitted non-zero canonical CAPEX fields
    capex_item_fields = getattr(orig_capex, "_CAPEX_ITEM_FIELDS", ())
    for field_code in capex_item_fields:
        field_val = getattr(orig_capex, field_code, None)
        if field_val is None:
            continue
        field_amount = require_finite_real(
            f"ProjectInputs.capex.{field_code}",
            getattr(field_val, "amount_keur", field_val),
            minimum=0.0,
            error_code="PR9_INVALID_CAPEX_AMOUNT",
        )
        if (
            field_amount > PR9_CAPEX_AUTHORITY_TOLERANCE_KEUR
            and field_code not in capex_amounts
        ):
            raise ValueError(
                f"PR9_CONSTRUCTION_CAPEX_AUTHORITY_MISMATCH: "
                f"non-zero canonical CAPEX field '{field_code}' (amount={field_amount:.6f} kEUR) "
                f"not present in construction capex_items"
            )

    # Validate: empty capex_items when canonical hard CAPEX > 0
    if (
        not cf.capex_items
        and canonical_hard_capex > PR9_CAPEX_AUTHORITY_TOLERANCE_KEUR
    ):
        raise ValueError(
            f"PR9_CONSTRUCTION_CAPEX_AUTHORITY_MISMATCH: "
            f"capex_items is empty but canonical hard CAPEX = {canonical_hard_capex:.6f} kEUR"
        )

    # Validate: totals match canonical hard_capex_keur
    construction_total = sum(capex_amounts.values())
    if (
        abs(construction_total - canonical_hard_capex)
        > PR9_CAPEX_AUTHORITY_TOLERANCE_KEUR
    ):
        raise ValueError(
            f"PR9_CONSTRUCTION_CAPEX_AUTHORITY_MISMATCH: "
            f"construction items total {construction_total:.6f} kEUR != "
            f"canonical hard CAPEX {canonical_hard_capex:.6f} kEUR"
        )

    # PR9_SHL_TIMELINE_AUTHORITY: when typed construction financing is enabled,
    # legacy construction_period_uses_keur must not independently set a different timeline.
    if (
        getattr(project_inputs.financing, "construction_period_uses_keur", None)
        and project_inputs.financing.construction_period_uses_keur
    ):
        raise ValueError(
            "PR9_DUAL_CONSTRUCTION_TIMELINE: typed construction_financing.periods is active "
            "but legacy construction_period_uses_keur is also set. "
            "Remove construction_period_uses_keur when using typed PR-9 construction financing."
        )

    # Outer state — all start at zero (neutral seed)
    prev_idc = 0.0
    prev_fee = 0.0
    prev_struct = 0.0
    prev_senior = 0.0
    prev_shl = 0.0
    prev_pik = 0.0
    prev_uses = 0.0
    outer_residual = float("inf")
    outer_iteration = 0
    working_inputs = project_inputs  # updated immutably each iteration

    # Seed step 1: run inner model once on original capex (zero IDC) to get
    # initial Senior/SHL/equity estimates.
    _seed_fin = replace(project_inputs.financing, construction_financing=None)
    _seed_inputs = replace(project_inputs, financing=_seed_fin)
    _seed_shl_context = _typed_construction_shl_context(
        construction=cf,
        financing=fin,
        canonical_allocations=tuple(
            ConstructionPeriodAllocation(
                period_index=index,
                period_uses_keur=0.0,
                share_capital_draw_keur=0.0,
                share_premium_draw_keur=0.0,
                other_committed_equity_draw_keur=0.0,
                additional_equity_draw_keur=0.0,
                shl_draw_keur=0.0,
                junior_draw_keur=0.0,
                senior_draw_keur=0.0,
                total_sources_keur=0.0,
                residual_keur=0.0,
            )
            for index, _ in enumerate(cf.periods)
        ),
        provisional=True,
    )
    inner_result = run_project_financing_model(
        _seed_inputs,
        source_id=source_id,
        baseline_commit_sha=baseline_commit_sha,
        convergence_tolerance_keur=outer_tolerance_keur,
        maximum_iterations=outer_max_iterations,
        _typed_shl_context=(
            _seed_shl_context if _seed_shl_context.accrual_enabled else None
        ),
        _u2_period_financing_income=_u2_period_financing_income,
    )

    # Neutral seed: inner_result from step 1 is used directly as the starting state.
    # No virtual Senior headroom, no IDC estimate, no broad exception fallback.
    # PR9_NEUTRAL_SEED: Senior_0 == seed inner G2A Senior commitment, exactly.

    stage_b2_result = None
    prev_unfunded = float("inf")

    for outer_iteration in range(1, outer_max_iterations + 1):
        uses = _project_uses(working_inputs)
        working_fin = working_inputs.financing

        # PR9_OUTER_AND_FINAL_SEVEN_SOURCE_COMPOSITION_IDENTITY:
        # Pass the full seven-source breakdown from the current inner result — identical
        # field mapping used here and in the final strict _verify_b2 configuration.
        # No source may be collapsed, relabelled, or combined into a generic pool.
        # PR9_NEUTRAL_SEED: Senior == inner_result.final_senior_commitment_keur exactly.
        runtime_cfg = build_construction_runtime_config(
            construction=cf,
            senior_commitment_keur=inner_result.final_senior_commitment_keur,
            equity_available_keur=inner_result.share_capital_keur,
            shl_available_keur=inner_result.derived_shl_cash_principal_keur,
            capex_amounts_keur=capex_amounts,
            share_premium_keur=inner_result.share_premium_keur,
            other_committed_equity_keur=inner_result.other_equity_funding_before_shl_keur,
            additional_equity_keur=inner_result.additional_equity_keur,
            junior_keur=inner_result.junior_or_other_main_project_funding_keur,
        )
        # Provisional Stage B2: Senior may not yet be fully sized for IDC.
        # Returns ProvisionalStageB2Result — NOT a final ConstructionRuntimeResult.
        # unfunded_uses_keur is diagnostic; outer loop drives it to zero at convergence.
        stage_b2_prov = run_stage_b2_provisional(runtime_cfg)
        new_financing = stage_b2_prov.capitalized_financing_costs
        _iteration_shl_context = _typed_construction_shl_context(
            construction=cf,
            financing=fin,
            canonical_allocations=stage_b2_prov.canonical_allocations,
            provisional=True,
        )

        # Apply costs IMMUTABLY from original base CapexStructure (not working_inputs.capex).
        updated_capex = apply_capitalized_financing_costs(orig_capex, new_financing)
        working_inputs = replace(project_inputs, capex=updated_capex)

        # Run inner SHL/Senior fixed point on updated inputs (construction gate disabled).
        # Temporarily clear construction_financing to avoid re-entering this function.
        inner_fin = replace(working_inputs.financing, construction_financing=None)
        inner_inputs = replace(working_inputs, financing=inner_fin)
        inner_result = run_project_financing_model(
            inner_inputs,
            source_id=source_id,
            baseline_commit_sha=baseline_commit_sha,
            convergence_tolerance_keur=outer_tolerance_keur,
            maximum_iterations=outer_max_iterations,
            _typed_shl_context=(
                _iteration_shl_context
                if _iteration_shl_context.accrual_enabled
                else None
            ),
            _u2_period_financing_income=_u2_period_financing_income,
        )

        # Check outer convergence across all material state components.
        # unfunded_uses_keur is included: convergence requires funded Sources == Uses.
        # PR9_NEUTRAL_SEED: no artificial headroom; unfunded must converge to zero.
        d_idc = abs(new_financing.senior_idc_keur - prev_idc)
        d_fee = abs(new_financing.senior_commitment_fee_keur - prev_fee)
        d_struct = abs(new_financing.structuring_fee_keur - prev_struct)
        d_senior = abs(inner_result.final_senior_commitment_keur - prev_senior)
        d_shl = abs(inner_result.derived_shl_cash_principal_keur - prev_shl)
        d_pik = abs(inner_result.shl_construction_pik_keur - prev_pik)
        d_uses = abs(inner_result.project_uses.total_project_uses_keur - prev_uses)
        d_unfunded = abs(stage_b2_prov.unfunded_uses_keur - prev_unfunded)
        outer_residual = max(d_idc, d_fee, d_struct, d_senior, d_shl, d_pik, d_uses, d_unfunded)
        prev_idc = new_financing.senior_idc_keur
        prev_fee = new_financing.senior_commitment_fee_keur
        prev_struct = new_financing.structuring_fee_keur
        prev_senior = inner_result.final_senior_commitment_keur
        prev_shl = inner_result.derived_shl_cash_principal_keur
        prev_pik = inner_result.shl_construction_pik_keur
        prev_uses = inner_result.project_uses.total_project_uses_keur
        prev_unfunded = stage_b2_prov.unfunded_uses_keur

        if outer_residual <= outer_tolerance_keur:
            break
    else:
        raise RuntimeError(
            f"PR9_OUTER_G2A_CONSTRUCTION_FIXED_POINT_DID_NOT_CONVERGE: "
            f"outer_residual={outer_residual:.12f} kEUR after {outer_max_iterations} iterations"
        )

    # Final invariant: unfunded must be zero at convergence.
    if stage_b2_prov.unfunded_uses_keur > outer_tolerance_keur:
        raise RuntimeError(
            f"PR9_OUTER_G2A_UNFUNDED_AT_CONVERGENCE: "
            f"unfunded_uses_keur={stage_b2_prov.unfunded_uses_keur:.6f} kEUR > tolerance "
            f"{outer_tolerance_keur:.6f} kEUR at outer convergence. "
            "Senior is insufficient to fund all construction Uses."
        )

    assert inner_result is not None and stage_b2_prov is not None

    # Final idempotence verification: one full outer transition from converged state must
    # produce identical outputs (Section 14 — true outer transition idempotence).
    _verify_b2_cfg = build_construction_runtime_config(
        construction=cf,
        senior_commitment_keur=inner_result.final_senior_commitment_keur,
        equity_available_keur=inner_result.share_capital_keur,
        shl_available_keur=inner_result.derived_shl_cash_principal_keur,
        capex_amounts_keur=capex_amounts,
        share_premium_keur=inner_result.share_premium_keur,
        other_committed_equity_keur=inner_result.other_equity_funding_before_shl_keur,
        additional_equity_keur=inner_result.additional_equity_keur,
        junior_keur=inner_result.junior_or_other_main_project_funding_keur,
    )
    _verify_b2 = run_stage_b2(_verify_b2_cfg)
    _verify_capex = apply_capitalized_financing_costs(orig_capex, _verify_b2.capitalized_financing_costs)
    _verify_inputs = replace(project_inputs, capex=_verify_capex)
    _verify_fin = replace(_verify_inputs.financing, construction_financing=None)
    _verify_inputs = replace(_verify_inputs, financing=_verify_fin)
    _verify_shl_context = _typed_construction_shl_context(
        construction=cf,
        financing=fin,
        canonical_allocations=_verify_b2.canonical_allocations,
        provisional=False,
    )
    _verify_result = run_project_financing_model(
        _verify_inputs,
        source_id=source_id,
        baseline_commit_sha=baseline_commit_sha,
        convergence_tolerance_keur=outer_tolerance_keur,
        maximum_iterations=outer_max_iterations,
        _typed_shl_context=(
            _verify_shl_context if _verify_shl_context.accrual_enabled else None
        ),
        _u2_period_financing_income=_u2_period_financing_income,
    )
    _idempotence_residual = max(
        abs(_verify_result.final_senior_commitment_keur - inner_result.final_senior_commitment_keur),
        abs(_verify_result.derived_shl_cash_principal_keur - inner_result.derived_shl_cash_principal_keur),
        abs(_verify_result.project_uses.total_project_uses_keur - inner_result.project_uses.total_project_uses_keur),
        abs(_verify_b2.capitalized_financing_costs.senior_idc_keur - stage_b2_prov.capitalized_financing_costs.senior_idc_keur),
        abs(_verify_b2.capitalized_financing_costs.senior_commitment_fee_keur - stage_b2_prov.capitalized_financing_costs.senior_commitment_fee_keur),
        abs(_verify_b2.capitalized_financing_costs.structuring_fee_keur - stage_b2_prov.capitalized_financing_costs.structuring_fee_keur),
    )
    if _idempotence_residual > outer_tolerance_keur * 10:
        raise RuntimeError(
            f"PR9_OUTER_G2A_IDEMPOTENCE_FAILED: residual={_idempotence_residual:.12f} kEUR"
        )

    # Build typed ConstructionFinancingResult from final strict Stage B2 (_verify_b2).
    # _verify_b2 is the canonical fully-funded result after outer convergence with
    # the full source breakdown. stage_b2_prov was provisional; _verify_b2 is strict.
    b2 = _verify_b2
    b2_idc = b2.senior_idc_accrual_keur
    b2_fee = b2.senior_commitment_fee_accrual_keur
    b2_draws = b2.senior_period_draw_keur
    b2_cumul = b2.cumulative_senior_draw_keur
    b2_uses = b2.total_permanent_uses_keur
    b2_hard = b2.monthly_hard_capex_keur
    n = len(b2_draws)

    derived_shl = inner_result.derived_shl_cash_principal_keur
    if n > 0 and b2_uses:
        _canonical_alloc = b2.canonical_allocations
        shl_alloc = tuple(a.shl_draw_keur for a in _canonical_alloc)
        _share_capital_draws = tuple(a.share_capital_draw_keur for a in _canonical_alloc)
        _share_premium_draws = tuple(a.share_premium_draw_keur for a in _canonical_alloc)
        _other_committed_draws = tuple(a.other_committed_equity_draw_keur for a in _canonical_alloc)
        _additional_equity_draws = tuple(a.additional_equity_draw_keur for a in _canonical_alloc)
        _junior_draws = tuple(a.junior_draw_keur for a in _canonical_alloc)
        _period_residuals = tuple(a.residual_keur for a in _canonical_alloc)
        _cumul_residuals = tuple(
            sum(_period_residuals[:i+1]) for i in range(len(_period_residuals))
        )
        _max_period_residual = max(abs(r) for r in _period_residuals) if _period_residuals else 0.0
        _max_cumul_residual = max(abs(c) for c in _cumul_residuals) if _cumul_residuals else 0.0
    else:
        _canonical_alloc = ()
        shl_alloc = ()
        _share_capital_draws = ()
        _share_premium_draws = ()
        _other_committed_draws = ()
        _additional_equity_draws = ()
        _junior_draws = ()
        _period_residuals = ()
        _max_period_residual = 0.0
        _max_cumul_residual = 0.0

    _final_typed_context = _typed_construction_shl_context(
        construction=cf,
        financing=fin,
        canonical_allocations=_canonical_alloc,
        provisional=False,
    )
    if fin.sponsor_funding_timing_policy == SponsorFundingTimingPolicy.PRO_RATA_CONSTRUCTION:
        _final_shl_cash = shl_alloc
        _post_construction_shl = max(0.0, derived_shl - sum(shl_alloc))
    else:
        _final_shl_cash = tuple(
            derived_shl if index == 0 else 0.0 for index in range(n)
        )
        _post_construction_shl = 0.0
    _final_shl_cash_with_tail = _final_shl_cash + (0.0,) * (
        len(_final_typed_context.periods) - len(_final_shl_cash)
    )
    _final_shl_periods = tuple(
        ShlConstructionPeriodInput(
            draw_keur=draw,
            day_count_fraction=period.day_count_fraction,
            period_index=period.period_index,
        )
        for draw, period in zip(_final_shl_cash_with_tail, _final_typed_context.periods)
    )
    _final_shl_schedule = compute_shl_construction_schedule(
        opening_balance_keur=0.0,
        periods=_final_shl_periods,
        annual_rate=fin.shl_rate,
        method=fin.shl_construction_interest_method,
    )
    _final_shl_pik_vector = tuple(
        period.pik_interest_keur for period in _final_shl_schedule.periods
    )
    _final_opening_shl = (
        _final_shl_schedule.opening_operating_shl_balance_keur
        + _post_construction_shl
    )
    if abs(_final_opening_shl - (derived_shl + sum(_final_shl_pik_vector))) > 1e-9:
        raise RuntimeError("PR9_OPENING_OPERATING_SHL_IDENTITY_FAILED")

    # Build the canonical ConstructionFundingResult from the exact converged allocations.
    # This is the single Layer-A authority: the same canonical_alloc tuple is passed to
    # build_construction_funding_schedule so ConstructionFundingResult == ConstructionFinancingResult
    # for every source class (identity holds within 1e-9 kEUR).
    if n > 0 and b2_uses and _canonical_alloc:
        _pr9_period_dates: "tuple | None" = tuple(
            (p.start_date, p.end_date, None) for p in cf.periods[:n]
        )
        _pr9_construction_funding = build_construction_funding_schedule(
            construction_period_count=n,
            total_project_uses_keur=inner_result.project_uses.total_project_uses_keur,
            senior_keur=inner_result.final_senior_commitment_keur,
            junior_keur=inner_result.junior_or_other_main_project_funding_keur,
            share_capital_keur=inner_result.share_capital_keur,
            share_premium_keur=inner_result.share_premium_keur,
            other_committed_equity_keur=inner_result.other_equity_funding_before_shl_keur,
            additional_equity_keur=inner_result.additional_equity_keur,
            shl_cash_keur=derived_shl,
            shl_cash_per_period_keur=_final_shl_cash,
            post_construction_shl_cash_contribution_keur=_post_construction_shl,
            period_dates=_pr9_period_dates,
            canonical_economic_allocations=_canonical_alloc,
        )
    else:
        _pr9_construction_funding = inner_result.construction_funding

    # Period dates from construction financing spec
    period_starts = tuple(p.start_date for p in cf.periods[:n])
    period_ends = tuple(p.end_date for p in cf.periods[:n])

    # Structuring fee per period
    from finco_core.construction.stage_b2 import allocate_structuring_fee
    struct_per_period = allocate_structuring_fee(
        b2.config.funding_policy,
        b2.capitalized_financing_costs.structuring_fee_keur,
    )

    final_uses = inner_result.project_uses.total_project_uses_keur
    final_senior = inner_result.final_senior_commitment_keur
    sources_uses_diff = sum(_pr9_construction_funding.periods[i].sources_uses_difference_keur
                            for i in range(len(_pr9_construction_funding.periods))) if _pr9_construction_funding.periods else 0.0

    construction_result = ConstructionFinancingResult(
        period_start_dates=period_starts,
        period_end_dates=period_ends,
        hard_capex_uses_keur=b2_hard,
        total_period_uses_keur=b2_uses,
        senior_draws_keur=b2_draws,
        cumulative_senior_keur=b2_cumul,
        senior_idc_accrual_keur=b2_idc,
        senior_commitment_fee_accrual_keur=b2_fee,
        structuring_fee_keur=struct_per_period,
        shl_allocation_keur=shl_alloc,
        shl_cash_contribution_keur=_final_shl_cash,
        shl_day_count_fraction=tuple(
            period.day_count_fraction for period in _final_typed_context.periods
        ),
        shl_pik_accrual_keur=_final_shl_pik_vector,
        share_capital_draws_keur=_share_capital_draws,
        share_premium_draws_keur=_share_premium_draws,
        other_committed_equity_draws_keur=_other_committed_draws,
        additional_equity_draws_keur=_additional_equity_draws,
        junior_draws_keur=_junior_draws,
        period_sources_uses_residual_keur=_period_residuals,
        maximum_period_residual_keur=_max_period_residual,
        maximum_cumulative_residual_keur=_max_cumul_residual,
        total_capitalized_financing_keur=b2.capitalized_financing_costs.total_keur,
        shl_construction_pik_keur=sum(_final_shl_pik_vector),
        opening_operating_shl_keur=_final_opening_shl,
        final_total_project_uses_keur=final_uses,
        final_senior_commitment_keur=final_senior,
        sources_uses_residual_keur=sources_uses_diff,
        outer_iterations=outer_iteration,
        outer_residual_keur=outer_residual,
        stage_b2_iterations=b2.iterations,
        stage_b2_residual_keur=b2.final_residual_keur,
        outer_idc_residual_keur=d_idc,
        outer_fee_residual_keur=d_fee,
        outer_struct_residual_keur=d_struct,
        outer_senior_residual_keur=d_senior,
        outer_shl_residual_keur=d_shl,
        outer_pik_residual_keur=d_pik,
        outer_uses_residual_keur=d_uses,
        final_verification_outer_residual_keur=_idempotence_residual,
        vat_payable_keur=tuple(row.vat_payable_keur for row in b2.vat_schedule),
        vat_requirement_keur=tuple(row.vat_requirement_keur for row in b2.vat_schedule),
        vat_drawn_keur=tuple(row.vat_drawn_keur for row in b2.vat_schedule),
        vat_undrawn_keur=tuple(row.vat_undrawn_keur for row in b2.vat_schedule),
        senior_idc_capitalized_uses_keur=b2.senior_idc_capitalized_uses_keur,
        senior_commitment_fee_capitalized_keur=b2.capitalized_financing_costs.senior_commitment_fee_keur,
        vat_idc_keur=b2.capitalized_financing_costs.vat_idc_keur,
        vat_commitment_fee_keur=b2.capitalized_financing_costs.vat_commitment_fee_keur,
        vat_commitment_mode=(
            cf.vat_facility.commitment_mode.value
            if cf.vat_facility is not None and cf.vat_facility.enabled
            else "DISABLED"
        ),
        vat_effective_commitment_keur=max(
            (
                row.vat_requirement_keur + row.vat_undrawn_keur
                for row in b2.vat_schedule
            ),
            default=0.0,
        ),
        vat_peak_requirement_keur=max(
            (row.vat_requirement_keur for row in b2.vat_schedule), default=0.0
        ),
        vat_peak_requirement_period=max(
            b2.vat_schedule,
            key=lambda row: row.vat_requirement_keur,
            default=None,
        ).period if b2.vat_schedule else 0,
        vat_authority=(
            "TYPED_CONSTRUCTION_VAT_FACILITY_AUTHORITY"
            if cf.vat_facility is not None and cf.vat_facility.enabled
            else "TYPED_CONSTRUCTION_VAT_FACILITY_DISABLED"
        ),
    )

    from financial_engine.book_basis import build_book_depreciable_asset_basis
    construction_basis = build_book_depreciable_asset_basis(orig_capex, construction_result)

    return ProjectFinancingResult(
        project_model_result=inner_result.project_model_result,
        project_uses=inner_result.project_uses,
        dscr_debt_capacity_keur=inner_result.dscr_debt_capacity_keur,
        gearing_basis_keur=inner_result.gearing_basis_keur,
        gearing_ratio=inner_result.gearing_ratio,
        gearing_debt_capacity_keur=inner_result.gearing_debt_capacity_keur,
        final_senior_commitment_keur=inner_result.final_senior_commitment_keur,
        binding_senior_constraint=inner_result.binding_senior_constraint,
        junior_or_other_main_project_funding_keur=inner_result.junior_or_other_main_project_funding_keur,
        share_capital_keur=inner_result.share_capital_keur,
        share_premium_keur=inner_result.share_premium_keur,
        other_equity_funding_before_shl_keur=inner_result.other_equity_funding_before_shl_keur,
        additional_equity_keur=inner_result.additional_equity_keur,
        derived_shl_cash_principal_keur=inner_result.derived_shl_cash_principal_keur,
        shl_construction_pik_keur=sum(_final_shl_pik_vector),
        opening_operating_shl_balance_keur=_final_opening_shl,
        construction_funding=_pr9_construction_funding,
        fixed_point_iteration_count=inner_result.fixed_point_iteration_count,
        fixed_point_maximum_difference_keur=inner_result.fixed_point_maximum_difference_keur,
        construction_financing=construction_result,
        book_depreciable_asset_basis=construction_basis,
        shareholder_loan_model_input=inner_result.shareholder_loan_model_input,
    )


def run_project_financing_model(
    project_inputs: ProjectInputs,
    *,
    source_id: str = "",
    baseline_commit_sha: str = "",
    convergence_tolerance_keur: float = 1e-7,
    maximum_iterations: int = 50,
    _typed_shl_context: _TypedConstructionShlContext | None = None,
    _u2_period_financing_income: "tuple | None" = None,
) -> ProjectFinancingResult:
    """Run the derived-SHL/Senior fixed point for an explicitly enabled project."""
    fin = project_inputs.financing
    if fin.sponsor_funding_mode is None:
        raise ValueError("G2A_SPONSOR_FUNDING_MODE_EXPLICIT_INPUT_REQUIRED")
    if fin.gearing_basis_mode != GearingBasisMode.TOTAL_PROJECT_USES:
        raise ValueError("G2A_GEARING_BASIS_EXPLICIT_INPUT_REQUIRED")

    # PR-9 construction IDC outer fixed point — gated; disabled path is structurally frozen.
    # When construction_financing is None or enabled=False this block is never entered.
    _construction_result: ConstructionFinancingResult | None = None
    if fin.construction_financing is not None and fin.construction_financing.enabled:
        result = _run_with_construction_idc(
            project_inputs=project_inputs,
            source_id=source_id,
            baseline_commit_sha=baseline_commit_sha,
            outer_tolerance_keur=convergence_tolerance_keur,
            outer_max_iterations=maximum_iterations,
            _u2_period_financing_income=_u2_period_financing_income,
        )
        return result

    uses = _project_uses(project_inputs)
    gearing_capacity = uses.total_project_uses_keur * fin.gearing_ratio

    # Fix 3: pre-compute construction period template for timing-resolved SHL.
    # Run the operating model once (calendar-only, timing-policy-independent) to get
    # per-period DCFs for construction periods. Used inside the fixed-point loop to
    # compute timing-resolved opening SHL for each candidate_shl.
    _construction_period_template: tuple[ShlConstructionPeriodInput, ...] | None = None
    # BLOCKER C: canonical period dates from model periods, populated below when template built.
    _model_period_dates: "tuple[tuple, ...] | None" = None  # (period_start, period_end, cashflow_date)
    if _typed_shl_context is not None:
        _construction_period_template = _typed_shl_context.periods
        _model_period_dates = _typed_shl_context.period_dates
    elif (
        fin.shl_construction_day_count_fraction is not None
        and fin.shl_construction_day_count_fraction > 0.0
    ):
        _operating_for_periods = from_project_inputs(
            project_inputs, source_id=source_id, baseline_commit_sha=baseline_commit_sha
        )
        _op_periods = run_operating_model(_operating_for_periods).periods
        _construction_periods_raw = [p for p in _op_periods if p.is_construction]
        if _construction_periods_raw:
            _total_period_dcf = sum(p.day_fraction for p in _construction_periods_raw)
            _total_shl_dcf = fin.shl_construction_day_count_fraction
            # Scale per-period DCFs so they sum to total_shl_construction_dcf.
            _scale = _total_shl_dcf / _total_period_dcf if _total_period_dcf > 0.0 else 1.0
            _construction_period_template = tuple(
                ShlConstructionPeriodInput(
                    draw_keur=0.0,  # draw computed by build_shl_construction_draw_schedule
                    day_count_fraction=p.day_fraction * _scale,
                    period_index=i,
                )
                for i, p in enumerate(_construction_periods_raw)
            )
            # BLOCKER C: capture canonical dates from model periods.
            # cashflow_date = period_end (standard project-finance convention).
            _model_period_dates = tuple(
                (p.period_start, p.period_end, p.period_end)
                for p in _construction_periods_raw
            )
            # GAP 3: fail closed for multi-period PRO_RATA without explicit Uses vector.
            # PRO_RATA with DCF>0 and >1 construction period REQUIRES construction_period_uses_keur.
            # Single-period exception: timing is unambiguous (no split needed).
            # Legacy Solar/Wind paths with None/0.0 DCF are unaffected (gate above prevents reaching here).
            _n_template_periods = len(_construction_period_template)
            if (
                fin.sponsor_funding_timing_policy == SponsorFundingTimingPolicy.PRO_RATA_CONSTRUCTION
                and _n_template_periods > 1
                and not fin.construction_period_uses_keur
            ):
                raise ValueError(
                    "PRO_RATA_CONSTRUCTION with multi-period construction requires "
                    "explicit construction_period_uses_keur"
                )

    # Neutral seed: the factory's legacy clean_shl_principal_keur is deliberately
    # not read. The authoritative principal must emerge from the fixed point.
    candidate_shl = (
        sum(_typed_shl_context.shl_allocation_to_uses_keur)
        if _typed_shl_context is not None
        else 0.0
    )
    if _typed_shl_context is not None and candidate_shl <= 0.0:
        # A provisional Stage-B2 seed has no allocations yet. Seed the generic
        # fixed point from the typed gearing cap and fixed funding sources; this
        # is a causal estimate, not a source output or a final-value target.
        candidate_shl = max(
            0.0,
            uses.total_project_uses_keur
            - gearing_capacity
            - fin.junior_or_other_project_funding_keur
            - fin.share_capital_keur
            - fin.share_premium_keur
            - fin.other_equity_funding_before_shl_keur,
        )

    model_result = None
    authoritative_dscr_capacity = 0.0
    maximum_difference = float("inf")
    derived_shl = candidate_shl
    additional_equity = 0.0  # derived residual; overwritten each iteration by reconcile_financing_stack
    for iteration in range(1, maximum_iterations + 1):
        capacity_inputs = replace(
            project_inputs,
            financing=replace(
                fin,
                clean_shl_principal_keur=candidate_shl,
                sponsor_funding_mode=None,
                gearing_basis_mode=None,
            ),
        )
        # Fix 3: compute timing-resolved construction draw schedule for this candidate_shl.
        # Uses the pre-computed per-period construction DCFs (_construction_period_template).
        # PRO_RATA vs ALL_AT_FC produce different draws per period → different PIK → different
        # opening SHL → different operating interest → different CFADS → different DSCR capacity.
        # Fix 3 canonical (BLOCKER B): pass construction_periods_override to SHL model so that
        # model construction PIK == ProjectFinancingResult.shl_construction_pik_keur.
        _iter_draw_schedule: "tuple[ShlConstructionPeriodInput, ...] | None" = None
        _iter_post_construction_principal = 0.0
        if (
            _construction_period_template is not None
        ):
            _timing_policy = (
                _typed_shl_context.timing_policy
                if _typed_shl_context is not None
                else fin.sponsor_funding_timing_policy
            )
            if _typed_shl_context is not None:
                _layer_a_shl = _typed_shl_context.shl_allocation_to_uses_keur
                _construction_shl_total = sum(_layer_a_shl)
                if (
                    candidate_shl + convergence_tolerance_keur < _construction_shl_total
                    and not _typed_shl_context.provisional
                ):
                    raise ValueError(
                        "PR9_TYPED_SHL_PRINCIPAL_BELOW_CONSTRUCTION_ALLOCATION: "
                        f"principal={candidate_shl:.12f}, "
                        f"construction_allocation={_construction_shl_total:.12f}"
                    )
                if _timing_policy == SponsorFundingTimingPolicy.PRO_RATA_CONSTRUCTION:
                    _shl_cash_per_period = _layer_a_shl
                    _iter_post_construction_principal = max(
                        0.0, candidate_shl - _construction_shl_total
                    )
                else:
                    _cash_principal = (
                        max(candidate_shl, _construction_shl_total)
                        if _typed_shl_context.provisional
                        else candidate_shl
                    )
                    _shl_cash_per_period = tuple(
                        _cash_principal if i == 0 else 0.0
                        for i in range(len(_construction_period_template))
                    )
                _iter_draw_schedule = tuple(
                    ShlConstructionPeriodInput(
                        draw_keur=draw,
                        day_count_fraction=period.day_count_fraction,
                        period_index=period.period_index,
                    )
                    for draw, period in zip(
                        _shl_cash_per_period, _construction_period_template
                    )
                )
            # BLOCKER A: use actual construction Uses for PRO_RATA when provided.
            _uses = getattr(fin, "construction_period_uses_keur", ())
            if _typed_shl_context is None and _uses:
                from finco_core.inputs._models import SponsorFundingTimingPolicy as _Policy
                if len(_uses) != len(_construction_period_template):
                    raise ValueError(
                        "CONSTRUCTION_USES_PERIOD_AXIS_MISMATCH: "
                        f"expected={len(_construction_period_template)}, actual={len(_uses)}"
                    )
                # Layer A — cumulative SPONSOR_FIRST_RESIDUAL_SENIOR waterfall.
                # Equity cap = all fixed equity sources + additional_equity from previous iteration
                # (additional_equity starts at 0.0 and converges each iteration).
                # Senior cap set to total_project_uses to guarantee waterfall coverage;
                # the waterfall fills senior last so per-period SHL draws are unaffected by
                # how much senior is allocated.
                _equity_cap = (
                    fin.share_capital_keur
                    + fin.share_premium_keur
                    + fin.other_equity_funding_before_shl_keur
                    + additional_equity
                )
                _waterfall_caps = FundingSourceCaps(
                    equity_shares_keur=_equity_cap,
                    shl_keur=candidate_shl,
                    junior_keur=fin.junior_or_other_project_funding_keur,
                    senior_debt_keur=uses.total_project_uses_keur,  # generous cap; senior is residual
                )
                _waterfall_entries = allocate_source_waterfall(tuple(_uses), _waterfall_caps)
                _waterfall_shl_per_period = tuple(e.shl_draw_keur for e in _waterfall_entries)

                # Layer B — SHL cash timing policy (orthogonal to Layer A allocation).
                if _timing_policy == _Policy.PRO_RATA_CONSTRUCTION:
                    _shl_cash_per_period = _waterfall_shl_per_period
                else:  # ALL_AT_FC
                    _shl_cash_per_period = tuple(
                        candidate_shl if i == 0 else 0.0 for i in range(len(_uses))
                    )
                _iter_draw_schedule = tuple(
                    ShlConstructionPeriodInput(
                        draw_keur=d,
                        day_count_fraction=p.day_count_fraction,
                        period_index=p.period_index,
                    )
                    for d, p in zip(_shl_cash_per_period, _construction_period_template)
                )
            elif _typed_shl_context is None:
                _iter_draw_schedule = build_shl_construction_draw_schedule(
                    shl_cash_principal_keur=candidate_shl,
                    construction_periods=_construction_period_template,
                    policy=_timing_policy,
                )

        capacity_model_input = build_senior_debt_model_input_from_project_inputs(
            capacity_inputs,
            source_id=source_id,
            baseline_commit_sha=baseline_commit_sha,
        )
        # Fix 3 canonical: inject construction_periods_override into capacity model input.
        # This causes the SHL model to compute canonical per-period construction PIK,
        # eliminating the dual truth (model PIK=0 vs result PIK>0).
        if _iter_draw_schedule is not None and capacity_model_input.shareholder_loan is not None:
            capacity_model_input = replace(
                capacity_model_input,
                shareholder_loan=replace(
                    capacity_model_input.shareholder_loan,
                    construction_periods_override=_iter_draw_schedule,
                    construction_period_end_dates_override=(
                        tuple(row[1] for row in _typed_shl_context.period_dates)
                        if _typed_shl_context is not None
                        else None
                    ),
                    post_construction_principal_contribution_keur=(
                        _iter_post_construction_principal
                    ),
                ),
            )
        # U2 Phase L: inject cash-reserve financing income into tax input
        if _u2_period_financing_income and capacity_model_input.tax is not None:
            capacity_model_input = replace(
                capacity_model_input,
                tax=replace(
                    capacity_model_input.tax,
                    period_financing_income=_u2_period_financing_income,
                ),
            )
        capacity_result = run_senior_debt_model(capacity_model_input)
        if capacity_result.senior_debt is None:
            raise RuntimeError("G2A DSCR capacity result is unavailable")
        authoritative_dscr_capacity = capacity_result.senior_debt.debt_size_keur
        expected_final_senior = min(authoritative_dscr_capacity, gearing_capacity)

        funded_inputs = replace(
            project_inputs,
            financing=replace(fin, clean_shl_principal_keur=candidate_shl),
        )
        funded_model_input = build_senior_debt_model_input_from_project_inputs(
            funded_inputs,
            source_id=source_id,
            baseline_commit_sha=baseline_commit_sha,
        )
        # The adapter now correctly maps gearing_basis_mode=TOTAL_PROJECT_USES to
        # COMBINED_MINIMUM with the canonical eligible cost and maximum_gearing.
        # No downstream patch is required here.
        # Fix 3 canonical: inject construction_periods_override into funded model input.
        if _iter_draw_schedule is not None and funded_model_input.shareholder_loan is not None:
            funded_model_input = replace(
                funded_model_input,
                shareholder_loan=replace(
                    funded_model_input.shareholder_loan,
                    construction_periods_override=_iter_draw_schedule,
                    construction_period_end_dates_override=(
                        tuple(row[1] for row in _typed_shl_context.period_dates)
                        if _typed_shl_context is not None
                        else None
                    ),
                    post_construction_principal_contribution_keur=(
                        _iter_post_construction_principal
                    ),
                ),
            )
        # U2 Phase L: inject cash-reserve financing income into funded tax input
        if _u2_period_financing_income and funded_model_input.tax is not None:
            funded_model_input = replace(
                funded_model_input,
                tax=replace(
                    funded_model_input.tax,
                    period_financing_income=_u2_period_financing_income,
                ),
            )
        model_result = run_senior_debt_model(funded_model_input)
        senior = model_result.senior_debt
        if senior is None:
            raise RuntimeError("G2A Senior result is unavailable")
        diagnosed_gearing = senior.diagnostics.get("gearing_debt_capacity_keur")
        if diagnosed_gearing is None:
            raise RuntimeError("G2A Senior capacity audit fields are unavailable")
        if abs(diagnosed_gearing - gearing_capacity) > 1e-7:
            raise RuntimeError("G2A gearing capacity handshake failed")
        if abs(senior.debt_size_keur - expected_final_senior) > convergence_tolerance_keur:
            raise RuntimeError(
                "G2A_FINAL_SENIOR_DOES_NOT_MATCH_CAPACITY_MINIMUM: "
                f"expected={expected_final_senior}, actual={senior.debt_size_keur}"
            )

        derived_shl, additional_equity = reconcile_financing_stack(
            total_project_uses_keur=uses.total_project_uses_keur,
            final_senior_commitment_keur=senior.debt_size_keur,
            junior_or_other_main_project_funding_keur=fin.junior_or_other_project_funding_keur,
            share_capital_keur=fin.share_capital_keur,
            share_premium_keur=fin.share_premium_keur,
            other_equity_funding_before_shl_keur=fin.other_equity_funding_before_shl_keur,
            sponsor_funding_mode=fin.sponsor_funding_mode,
        )
        maximum_difference = abs(derived_shl - candidate_shl)
        if maximum_difference <= convergence_tolerance_keur:
            break
        candidate_shl = derived_shl
    else:
        raise RuntimeError("G2A_SHL_SENIOR_FIXED_POINT_DID_NOT_CONVERGE")

    assert model_result is not None and model_result.senior_debt is not None

    # Construction SHL schedule — see module-level comment for None/0.0/explicit-DCF semantics.
    # Fix 3 canonical (BLOCKER B): PIK now comes from canonical model result because the model
    # received construction_periods_override. Direct reading from model result is authoritative.
    shl_pik = 0.0
    opening_operating_shl = 0.0
    _final_draw_schedule: "tuple[ShlConstructionPeriodInput, ...] | None" = None
    # GAP 1 & 2: initialized here; populated inside the explicit-DCF block below.
    _post_uses_vector: "tuple[float, ...] | None" = None
    _post_waterfall_shl: "tuple[float, ...] | None" = None
    _final_post_construction_principal = 0.0

    if _construction_period_template is not None:
        # Explicit positive DCF: compute final post-convergence draw schedule.
        timing_policy = fin.sponsor_funding_timing_policy
        _uses = getattr(fin, "construction_period_uses_keur", ())
        if _typed_shl_context is not None:
            _final_waterfall_shl = _typed_shl_context.shl_allocation_to_uses_keur
            _post_waterfall_shl = _final_waterfall_shl
            if timing_policy == SponsorFundingTimingPolicy.PRO_RATA_CONSTRUCTION:
                _final_shl_cash = _final_waterfall_shl
                _final_post_construction_principal = max(
                    0.0, derived_shl - sum(_final_waterfall_shl)
                )
            else:
                _final_cash_principal = (
                    max(derived_shl, sum(_final_waterfall_shl))
                    if _typed_shl_context.provisional
                    else derived_shl
                )
                _final_shl_cash = tuple(
                    _final_cash_principal if i == 0 else 0.0
                    for i in range(len(_construction_period_template))
                )
            _final_draw_schedule = tuple(
                ShlConstructionPeriodInput(
                    draw_keur=draw,
                    day_count_fraction=period.day_count_fraction,
                    period_index=period.period_index,
                )
                for draw, period in zip(
                    _final_shl_cash, _construction_period_template
                )
            )
        elif _uses:
            from finco_core.inputs._models import SponsorFundingTimingPolicy as _Policy
            # Post-convergence: Layer A waterfall with authoritative final values.
            _final_equity_cap = (
                fin.share_capital_keur
                + fin.share_premium_keur
                + fin.other_equity_funding_before_shl_keur
                + additional_equity
            )
            _final_caps = FundingSourceCaps(
                equity_shares_keur=_final_equity_cap,
                shl_keur=derived_shl,
                junior_keur=fin.junior_or_other_project_funding_keur,
                senior_debt_keur=uses.total_project_uses_keur,
            )
            _final_waterfall = allocate_source_waterfall(tuple(_uses), _final_caps)
            _final_waterfall_shl = tuple(e.shl_draw_keur for e in _final_waterfall)
            # GAP 1 & 2: capture for funding schedule bridge computation below.
            _post_uses_vector = tuple(_uses)
            _post_waterfall_shl = _final_waterfall_shl
            if timing_policy == _Policy.PRO_RATA_CONSTRUCTION:
                _final_shl_cash = _final_waterfall_shl
            else:  # ALL_AT_FC
                _final_shl_cash = tuple(
                    derived_shl if i == 0 else 0.0 for i in range(len(_uses))
                )
            _final_draw_schedule = tuple(
                ShlConstructionPeriodInput(
                    draw_keur=d,
                    day_count_fraction=p.day_count_fraction,
                    period_index=p.period_index,
                )
                for d, p in zip(_final_shl_cash, _construction_period_template)
            )
        else:
            _final_draw_schedule = build_shl_construction_draw_schedule(
                shl_cash_principal_keur=derived_shl,
                construction_periods=_construction_period_template,
                policy=timing_policy,
            )
        construction_shl_schedule = compute_shl_construction_schedule(
            opening_balance_keur=0.0,
            periods=_final_draw_schedule,
            annual_rate=fin.shl_rate,
            method=fin.shl_construction_interest_method,
        )
        shl_pik = construction_shl_schedule.total_pik_keur
        opening_operating_shl = (
            construction_shl_schedule.opening_operating_shl_balance_keur
            + _final_post_construction_principal
        )
    elif model_result.shareholder_loan is not None:
        # Backward-compat path: no explicit construction DCF. Read from canonical model result.
        # Generic Solar/Wind return 0 PIK here (no construction SHL DCF configured).
        shl = model_result.shareholder_loan
        construction_indices = {
            period.period_index for period in model_result.periods if period.is_construction
        }
        shl_pik = sum(
            value
            for idx, value in zip(shl.period_indices, shl.shl_pik_interest_keur)
            if idx in construction_indices
        )
        first_operating_index = next(
            period.period_index for period in model_result.periods if period.is_operation
        )
        opening_operating_shl = dict(
            zip(shl.period_indices, shl.shl_opening_keur)
        ).get(first_operating_index, 0.0)

    # BLOCKER C resolved: use model construction periods (same axis as SHL/tax) as the single
    # source of truth for G2A/G2B. _final_draw_schedule is indexed by model periods.
    # BLOCKER B resolved: if explicit timing is provided, always use it (no len() fallback).
    _model_construction_period_count = len(_construction_period_template) if _construction_period_template is not None else project_inputs.info.construction_months
    _shl_draws_per_period: tuple[float, ...] | None = None
    if _final_draw_schedule is not None:
        if len(_final_draw_schedule) != _model_construction_period_count:
            raise ValueError(
                f"G2B_PERIOD_COUNT_MISMATCH: draw schedule length {len(_final_draw_schedule)} "
                f"!= model construction period count {_model_construction_period_count}"
            )
        _shl_draws_per_period = tuple(p.draw_keur for p in _final_draw_schedule)
    # GAP 1: pass explicit period Uses vector to funding schedule (single source of truth).
    # GAP 2: pass waterfall allocation vector for prefunding bridge computation.
    # Both are None in the legacy path (no explicit uses vector provided).
    if _typed_shl_context is not None and _typed_shl_context.provisional:
        funding = _provisional_typed_construction_funding(
            _typed_shl_context,
            _shl_draws_per_period or tuple(
                0.0 for _ in _typed_shl_context.periods
            ),
        )
    else:
        funding = build_construction_funding_schedule(
            construction_period_count=_model_construction_period_count,
            total_project_uses_keur=uses.total_project_uses_keur,
            senior_keur=model_result.senior_debt.debt_size_keur,
            junior_keur=fin.junior_or_other_project_funding_keur,
            share_capital_keur=fin.share_capital_keur,
            share_premium_keur=fin.share_premium_keur,
            other_committed_equity_keur=fin.other_equity_funding_before_shl_keur,
            additional_equity_keur=additional_equity,
            shl_cash_keur=derived_shl,
            shl_cash_per_period_keur=_shl_draws_per_period,
            post_construction_shl_cash_contribution_keur=(
                _final_post_construction_principal
            ),
            period_dates=_model_period_dates,
            period_uses_keur=_post_uses_vector,
            shl_allocation_per_period_keur=_post_waterfall_shl,
            canonical_economic_allocations=(
                _typed_shl_context.canonical_allocations
                if _typed_shl_context is not None
                else None
            ),
        )
    return ProjectFinancingResult(
        project_model_result=model_result,
        project_uses=uses,
        dscr_debt_capacity_keur=authoritative_dscr_capacity,
        gearing_basis_keur=uses.total_project_uses_keur,
        gearing_ratio=fin.gearing_ratio,
        gearing_debt_capacity_keur=gearing_capacity,
        final_senior_commitment_keur=model_result.senior_debt.debt_size_keur,
        binding_senior_constraint=str(model_result.senior_debt.binding_constraint),
        junior_or_other_main_project_funding_keur=fin.junior_or_other_project_funding_keur,
        share_capital_keur=fin.share_capital_keur,
        share_premium_keur=fin.share_premium_keur,
        other_equity_funding_before_shl_keur=fin.other_equity_funding_before_shl_keur,
        additional_equity_keur=additional_equity,
        derived_shl_cash_principal_keur=derived_shl,
        shl_construction_pik_keur=shl_pik,
        opening_operating_shl_balance_keur=opening_operating_shl,
        construction_funding=funding,
        fixed_point_iteration_count=iteration,
        fixed_point_maximum_difference_keur=maximum_difference,
        shareholder_loan_model_input=funded_model_input.shareholder_loan,
        book_depreciable_asset_basis=_build_generic_book_basis(project_inputs.capex),
    )
