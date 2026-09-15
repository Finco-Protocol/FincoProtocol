"""financial_engine.tax.engine — Phase 2B annual tax calculation engine.

Pure function.  No imports from app, finco_core or any framework.

Calculation order
-----------------
1.  Split every model period into calendar-year fragments (crosses 31 Dec).
2.  Aggregate fragments → ``TaxYearCalculationBasis`` per calendar year.
3.  Per tax year: annual ATAD → annual taxable income → annual FIFO LCF → CIT.
4.  Allocate cash tax payments to periods.

    * ``TAX_YEAR_LAST_PERIOD``: full annual CIT in the last period of the year
      (determined by the latest fragment end-date) plus the configured lag.
    * ``SAME_PERIOD``: each period pays its own prorated CIT accrual share.

5.  Record ``terminal_unpaid_tax_keur`` for liabilities outside the horizon.

Taxable income formula (correct — no double ATAD addback)::

    taxable_income_before_lcf = EBITDA
                                − tax_depreciation
                                − deductible_interest   ← ATAD-limited
                                + other_fiscal_reintegration

Example:
    EBITDA=10 000, tax_dep=2 000, gross_interest=4 000,
    deductible_interest=3 000 → taxable = 10 000 − 2 000 − 3 000 = 5 000  ✓
    (disallowed_interest is NOT added back separately)

Multi-year periods
------------------
A period that spans 31 December appears in ``period_indices`` for BOTH the
preceding and following calendar year.  CIT accrual for such a period is
computed by summing (annual_CIT × allocation_fraction) across every year
the period contributes to.  ATAD deductible/disallowed are similarly
accumulated across all years.  Cash-tax timing is unchanged: under
TAX_YEAR_LAST_PERIOD the full annual CIT lands in a single payment period.
"""
from __future__ import annotations

from financial_engine.inputs import TaxCalculationInput, PeriodInterestInput
from financial_engine.policies.tax import CashTaxTiming, TaxLossUtilisationGate, TaxPolicy
from financial_engine.tax.atad import calculate_annual_atad, allocate_atad_to_periods
from financial_engine.tax.loss_ledger import run_annual_fifo_ledger
from financial_engine.tax.models import (
    PeriodCashTaxResult,
    PeriodTaxYearAllocation,
    TaxAndCfadsResult,
    TaxAnnualResult,
)
from financial_engine.tax.tax_year import build_tax_year_bases


def _build_interest_map(
    period_interest: tuple[PeriodInterestInput, ...],
) -> dict[int, PeriodInterestInput]:
    return {pi.period_index: pi for pi in period_interest}


def _build_adj_map(period_adjustments: tuple) -> dict[int, float]:
    return {
        adj.period_index: adj.other_fiscal_reintegration_keur
        for adj in period_adjustments
    }


def _period_alloc_fraction(
    period_index: int,
    frags_for_year: tuple,
) -> float:
    """Sum of allocation_fraction for fragments of ``period_index`` in one year."""
    return sum(
        f.allocation_fraction
        for f in frags_for_year
        if f.source_period_index == period_index
    )


def calculate_tax(
    periods: tuple,             # tuple[OperatingPeriodResult]
    tax_input: TaxCalculationInput,
) -> TaxAndCfadsResult:
    """Calculate Phase 2B annual tax and return period cash-tax assignments.

    Parameters
    ----------
    periods:
        OperatingPeriodResult tuple from ``run_operating_model()``.
    tax_input:
        TaxCalculationInput with policy, interest schedule and adjustments.

    Returns
    -------
    TaxAndCfadsResult containing per-annual and per-period results plus
    ``terminal_unpaid_tax_keur`` for liabilities outside the model horizon.
    """
    policy: TaxPolicy = tax_input.policy  # type: ignore[assignment]
    interest_map = _build_interest_map(tax_input.period_interest)
    adj_map = _build_adj_map(tax_input.period_adjustments)

    # U2: Build financing-income map from period_financing_income (below EBITDA).
    # UNRESOLVED + nonzero raises — must not silently enter taxable income.
    # Unknown authority strings raise — fail closed against future enum drift.
    _KNOWN_AUTHORITIES = {"UNRESOLVED", "GENERIC_FINCO_POLICY", "SOURCE_PROVEN"}
    financing_income_map: dict[int, float] = {}
    for fi in getattr(tax_input, "period_financing_income", ()):
        _auth = getattr(fi, "authority", "UNRESOLVED")
        if _auth not in _KNOWN_AUTHORITIES:
            raise ValueError(
                f"calculate_tax: PeriodFinancingIncomeInput period_index="
                f"{fi.period_index} has unknown authority={_auth!r}. "
                f"Valid: {sorted(_KNOWN_AUTHORITIES)}"
            )
        if _auth == "UNRESOLVED" and fi.financing_income_keur != 0.0:
            raise ValueError(
                f"calculate_tax: UNRESOLVED authority on period_index="
                f"{fi.period_index} with nonzero financing_income_keur="
                f"{fi.financing_income_keur}. UNRESOLVED must fail closed (0.0)."
            )
        if _auth != "UNRESOLVED":
            financing_income_map[fi.period_index] = fi.financing_income_keur

    # ── Step 1-2: Build calendar-year bases ───────────────────────────────────
    bases = build_tax_year_bases(periods, interest_map, adj_map, policy, financing_income_map)

    # ── Step 3: ATAD + taxable income + LCF + CIT per tax year ───────────────
    atad_results = []
    for basis in bases:
        # Build per-period interest allocation from pre-allocated fragment amounts.
        period_int: dict[int, float] = {}
        for frag in basis.fragments:
            period_int[frag.source_period_index] = (
                period_int.get(frag.source_period_index, 0.0) + frag.total_interest_keur
            )

        period_interests: tuple[float, ...] = tuple(
            period_int.get(idx, 0.0) for idx in basis.period_indices
        )

        annual_atad = calculate_annual_atad(basis, policy)
        annual_atad = allocate_atad_to_periods(annual_atad, period_interests)
        atad_results.append(annual_atad)

    # Annual taxable income before LCF.
    # U2: financing_income_keur (cash/reserve interest) enters taxable income here.
    # EBITDA = revenue - opex is UNCHANGED. Financing income is below EBITDA.
    taxable_before_lcf = [
        (
            basis.ebitda_keur
            + basis.financing_income_keur        # U2: financing income (below EBITDA)
            - basis.tax_depreciation_keur
            - atad.deductible_interest_keur
            + basis.other_fiscal_reintegration_keur
        )
        for basis, atad in zip(bases, atad_results)
    ]

    # Annual FIFO LCF
    tax_year_indices = tuple(b.tax_year for b in bases)
    if policy.loss_utilisation_gate == TaxLossUtilisationGate.EBT_POSITIVE:
        loss_use_allowed = tuple(
            (
                basis.ebitda_keur
                + basis.financing_income_keur        # U2: financing income is above EBT
                - basis.tax_depreciation_keur
                - basis.total_interest_keur
                - basis.shl_non_deductible_interest_keur
                + basis.other_fiscal_reintegration_keur
            ) > 0.0
            for basis in bases
        )
    else:
        loss_use_allowed = None

    lcf_entries = run_annual_fifo_ledger(
        taxable_income_before_lcf=tuple(taxable_before_lcf),
        tax_year_indices=tax_year_indices,
        opening_inputs=tax_input.opening_loss_vintages,
        loss_carryforward_years=policy.loss_carryforward_years,
        loss_use_allowed=loss_use_allowed,
    )

    # Annual CIT + build TaxAnnualResult
    annual_results: list[TaxAnnualResult] = []
    for basis, atad, ti_before, lcf in zip(
        bases, atad_results, taxable_before_lcf, lcf_entries
    ):
        ti_after = lcf.taxable_income_after_lcf_keur
        liability = policy.corporate_rate * max(0.0, ti_after)
        annual_results.append(TaxAnnualResult(
            tax_year=basis.tax_year,
            period_indices=basis.period_indices,
            total_interest_keur=atad.total_interest_keur,
            deduction_capacity_keur=atad.deduction_capacity_keur,
            deductible_interest_keur=atad.deductible_interest_keur,
            disallowed_interest_keur=atad.disallowed_interest_keur,
            atad_binding_rule=atad.binding_rule,
            ebitda_keur=basis.ebitda_keur,
            financing_income_keur=basis.financing_income_keur,
            tax_depreciation_keur=basis.tax_depreciation_keur,
            other_fiscal_reintegration_keur=basis.other_fiscal_reintegration_keur,
            taxable_income_before_lcf_keur=ti_before,
            loss_opening_keur=lcf.opening_loss_pre_expiry_keur,
            loss_expired_keur=lcf.loss_expired_keur,
            loss_used_keur=lcf.loss_used_keur,
            loss_generated_keur=lcf.loss_generated_keur,
            loss_closing_keur=lcf.closing_loss_keur,
            taxable_income_after_lcf_keur=ti_after,
            ledger_entry=lcf,
            current_tax_liability_keur=liability,
            period_atad_deductible=atad.period_deductible_keur,
            period_atad_disallowed=atad.period_disallowed_keur,
        ))

    # ── Step 4: Allocate cash tax to periods ──────────────────────────────────
    # Build lookup: tax_year → (basis, annual_result)
    basis_by_tax_year: dict[int, object] = {b.tax_year: b for b in bases}
    ar_by_tax_year: dict[int, TaxAnnualResult] = {ar.tax_year: ar for ar in annual_results}

    all_period_indices = sorted(p.period_index for p in periods)  # type: ignore[attr-defined]
    max_period_idx = max(all_period_indices) if all_period_indices else -1

    terminal_unpaid = 0.0
    tax_year_cash_period: dict[int, int | None] = {}

    for ar in annual_results:
        if not ar.period_indices:
            continue

        if policy.cash_tax_timing in (
            CashTaxTiming.TAX_YEAR_LAST_PERIOD,
            CashTaxTiming.MODEL_YEAR_PAYMENT_PERIOD,
        ):
            basis = basis_by_tax_year.get(ar.tax_year)
            base = (
                basis.payment_period_index  # type: ignore[union-attr]
                if basis is not None
                else ar.period_indices[-1]
            )
            payment_period = base + policy.cash_tax_payment_lag_periods
            if payment_period > max_period_idx:
                terminal_unpaid += ar.current_tax_liability_keur
                tax_year_cash_period[ar.tax_year] = None
            else:
                tax_year_cash_period[ar.tax_year] = payment_period
        else:
            # SAME_PERIOD: handled per-period below; mark sentinel
            tax_year_cash_period[ar.tax_year] = -1  # sentinel = distribute

    # Accumulate ATAD deductible/disallowed per period across all years.
    # A cross-year period accumulates from multiple annual ATAD results.
    period_ded_lookup: dict[int, float] = {}
    period_dis_lookup: dict[int, float] = {}
    for ar in annual_results:
        for idx, ded, dis in zip(
            ar.period_indices,
            ar.period_atad_deductible,
            ar.period_atad_disallowed,
        ):
            period_ded_lookup[idx] = period_ded_lookup.get(idx, 0.0) + ded
            period_dis_lookup[idx] = period_dis_lookup.get(idx, 0.0) + dis

    # For each year, the sum of per-period allocation fractions may exceed 1.0
    # (e.g. two full-year periods each have frac=1.0 in the same year → sum=2.0).
    # Normalise so that: sum_over_periods(cit_accrual_from_year_Y) == AR_Y.CIT.
    year_alloc_sum: dict[int, float] = {}
    for ar in annual_results:
        basis = basis_by_tax_year[ar.tax_year]
        frags_for_year = basis.fragments  # type: ignore[union-attr]
        year_alloc_sum[ar.tax_year] = sum(
            _period_alloc_fraction(idx, frags_for_year) for idx in ar.period_indices
        )

    # Build per-period → list of (tax_year, alloc_fraction_normalised, annual_result).
    # Used for PeriodTaxYearAllocation and SAME_PERIOD accrual.
    period_year_contributions: dict[int, list[tuple[int, float, TaxAnnualResult]]] = {
        idx: [] for idx in all_period_indices
    }
    for ar in annual_results:
        basis = basis_by_tax_year[ar.tax_year]
        frags_for_year = basis.fragments  # type: ignore[union-attr]
        denom = year_alloc_sum.get(ar.tax_year, 1.0) or 1.0
        for idx in ar.period_indices:
            raw_frac = _period_alloc_fraction(idx, frags_for_year)
            norm_frac = raw_frac / denom
            period_year_contributions[idx].append((ar.tax_year, norm_frac, ar))

    # Build cash_tax_by_period
    cash_tax_by_period: dict[int, float] = {idx: 0.0 for idx in all_period_indices}

    if policy.cash_tax_timing in (
        CashTaxTiming.TAX_YEAR_LAST_PERIOD,
        CashTaxTiming.MODEL_YEAR_PAYMENT_PERIOD,
    ):
        for ar in annual_results:
            payment_period = tax_year_cash_period.get(ar.tax_year)
            if payment_period is not None:
                cash_tax_by_period[payment_period] = (
                    cash_tax_by_period[payment_period] + ar.current_tax_liability_keur
                )
    else:
        # SAME_PERIOD: each period's share = sum(annual_CIT × alloc_frac) over all years.
        for idx in all_period_indices:
            for _yr, alloc_frac, ar in period_year_contributions[idx]:
                share = ar.current_tax_liability_keur * alloc_frac
                cash_tax_by_period[idx] = cash_tax_by_period[idx] + share

    # ── Step 5: Build per-period results ──────────────────────────────────────
    period_results: list[PeriodCashTaxResult] = []
    for p in periods:
        idx = p.period_index   # type: ignore[attr-defined]
        contributions = period_year_contributions[idx]

        # Build PeriodTaxYearAllocation for each year this period contributes to.
        # ``alloc_frac`` here is the normalised share (raw/sum_of_raw_for_year),
        # ensuring sum(cit_accrual_keur over all periods) == AR_Y.CIT for each year.
        allocations: list[PeriodTaxYearAllocation] = []
        for yr, alloc_frac, ar in contributions:
            basis = basis_by_tax_year[yr]
            frags_for_year = basis.fragments  # type: ignore[union-attr]

            # Per-year ATAD for this period (from ar.period_atad_* arrays).
            yr_idx_list = list(ar.period_indices)
            if idx in yr_idx_list:
                pos = yr_idx_list.index(idx)
                yr_ded = ar.period_atad_deductible[pos]
                yr_dis = ar.period_atad_disallowed[pos]
            else:
                yr_ded = 0.0
                yr_dis = 0.0

            # Allocated amounts for this period in this year (from fragment amounts).
            yr_ebitda = sum(
                f.ebitda_keur for f in frags_for_year if f.source_period_index == idx
            )
            yr_reint = sum(
                f.other_fiscal_reintegration_keur
                for f in frags_for_year if f.source_period_index == idx
            )
            yr_shl_tax_eligible = sum(
                f.shl_tax_eligible_interest_keur
                for f in frags_for_year if f.source_period_index == idx
            )
            yr_shl_non_deductible = sum(
                f.shl_non_deductible_interest_keur
                for f in frags_for_year if f.source_period_index == idx
            )
            yr_financing_income = sum(
                f.financing_income_keur
                for f in frags_for_year if f.source_period_index == idx
            )
            yr_ti_share = ar.taxable_income_before_lcf_keur * alloc_frac
            yr_cit = ar.current_tax_liability_keur * alloc_frac

            allocations.append(PeriodTaxYearAllocation(
                tax_year=yr,
                allocation_fraction=alloc_frac,
                ebitda_keur=yr_ebitda,
                deductible_interest_keur=yr_ded,
                disallowed_interest_keur=yr_dis,
                other_fiscal_reintegration_keur=yr_reint,
                shl_tax_eligible_interest_keur=yr_shl_tax_eligible,
                shl_non_deductible_interest_keur=yr_shl_non_deductible,
                taxable_income_share_keur=yr_ti_share,
                cit_accrual_keur=yr_cit,
                financing_income_keur=yr_financing_income,
            ))

        # Primary year = year with largest allocation fraction (display-only).
        if allocations:
            primary_yr = max(allocations, key=lambda a: (a.allocation_fraction, a.tax_year)).tax_year
        else:
            primary_yr = 0

        total_ded = period_ded_lookup.get(idx, 0.0)
        total_dis = period_dis_lookup.get(idx, 0.0)
        total_reint = adj_map.get(idx, 0.0)
        total_shl_tax_eligible = sum(
            a.shl_tax_eligible_interest_keur for a in allocations
        )
        total_shl_non_deductible = sum(
            a.shl_non_deductible_interest_keur for a in allocations
        )
        total_ti_share = sum(a.taxable_income_share_keur for a in allocations)
        total_cit_share = sum(a.cit_accrual_keur for a in allocations)
        period_interest = interest_map.get(idx)

        period_results.append(PeriodCashTaxResult(
            period_index=idx,
            is_operation=p.is_operation,    # type: ignore[attr-defined]
            ebitda_keur=p.ebitda_keur,      # type: ignore[attr-defined]
            primary_tax_year=primary_yr,
            tax_year_allocations=tuple(allocations),
            deductible_interest_keur=total_ded,
            disallowed_interest_keur=total_dis,
            other_fiscal_reintegration_keur=total_reint,
            taxable_income_before_lcf_share_keur=total_ti_share,
            cit_accrual_share_keur=total_cit_share,
            cash_tax_keur=cash_tax_by_period.get(idx, 0.0),
            shl_tax_eligible_interest_keur=total_shl_tax_eligible,
            shl_non_deductible_interest_keur=total_shl_non_deductible,
            capitalisation_ratio=(
                period_interest.capitalisation_ratio if period_interest else None
            ),
            capitalisation_gate_active=(
                period_interest.capitalisation_gate_active if period_interest else None
            ),
            shl_absolute_limit_component_keur=(
                period_interest.absolute_limit_component_keur if period_interest else 0.0
            ),
            shl_ebitda_limit_component_keur=(
                period_interest.ebitda_limit_component_keur if period_interest else 0.0
            ),
            shl_additional_non_deductible_component_keur=(
                period_interest.additional_non_deductible_component_keur
                if period_interest else 0.0
            ),
            financing_income_keur=financing_income_map.get(idx, 0.0),
        ))

    return TaxAndCfadsResult(
        annual_results=tuple(annual_results),
        period_results=tuple(period_results),
        terminal_unpaid_tax_keur=terminal_unpaid,
    )
