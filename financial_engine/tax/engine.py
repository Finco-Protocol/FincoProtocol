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

from datetime import timedelta
from typing import NamedTuple

from financial_engine.cfads import calculate_canonical_cfads
from financial_engine.run_scope import current_run_scope as _current_run_scope
from financial_engine.inputs import TaxCalculationInput, PeriodInterestInput
from financial_engine.policies.tax import (
    CashTaxTiming,
    TaxBasisPeriodisation,
    TaxLossUtilisationGate,
    TaxPolicy,
)
from financial_engine.tax.atad import calculate_annual_atad, allocate_atad_to_periods
from financial_engine.tax.loss_ledger import run_annual_fifo_ledger, taxable_income_after_lcf_series
from financial_engine.tax.models import (
    PeriodCashTaxResult,
    PeriodTaxYearAllocation,
    TaxAndCfadsResult,
    TaxAnnualResult,
)
from financial_engine.tax.tax_year import (
    _period_geometry,
    _resolve_shl_tax_eligible_interest,
    build_tax_year_bases,
)


def _build_interest_map(
    period_interest: tuple[PeriodInterestInput, ...],
) -> dict[int, PeriodInterestInput]:
    return {pi.period_index: pi for pi in period_interest}


def _build_adj_map(period_adjustments: tuple) -> dict[int, float]:
    return {
        adj.period_index: adj.other_fiscal_reintegration_keur
        for adj in period_adjustments
    }


_KNOWN_AUTHORITIES = {"UNRESOLVED", "GENERIC_FINCO_POLICY", "SOURCE_PROVEN"}


def _build_financing_income_map(tax_input: TaxCalculationInput) -> dict[int, float]:
    """U2: Build financing-income map from period_financing_income (below EBITDA).

    UNRESOLVED + nonzero raises — must not silently enter taxable income.
    Unknown authority strings raise — fail closed against future enum drift.
    """
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
    return financing_income_map


def _fragments_by_period(frags_for_year: tuple) -> dict[int, list]:
    """Group one year's fragments by source period, preserving fragment order."""
    grouped: dict[int, list] = {}
    for f in frags_for_year:
        grouped.setdefault(f.source_period_index, []).append(f)
    return grouped


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

    financing_income_map = _build_financing_income_map(tax_input)

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
    # Per-year fragment index, built once: replaces repeated O(periods x fragments)
    # scans. Each sum() below runs over the same elements in the same order as before.
    frags_by_period_by_year: dict[int, dict[int, list]] = {
        b.tax_year: _fragments_by_period(b.fragments) for b in bases  # type: ignore[attr-defined]
    }
    raw_frac_by_year: dict[int, dict[int, float]] = {
        yr: {idx: sum(f.allocation_fraction for f in frs) for idx, frs in by_idx.items()}
        for yr, by_idx in frags_by_period_by_year.items()
    }

    first_pos_by_year: dict[int, dict[int, int]] = {}
    for ar in annual_results:
        first_pos: dict[int, int] = {}
        for i, pidx in enumerate(ar.period_indices):
            first_pos.setdefault(pidx, i)
        first_pos_by_year[ar.tax_year] = first_pos

    year_alloc_sum: dict[int, float] = {}
    for ar in annual_results:
        raw_fracs = raw_frac_by_year[ar.tax_year]
        year_alloc_sum[ar.tax_year] = sum(
            raw_fracs.get(idx, 0) for idx in ar.period_indices
        )

    # Build per-period → list of (tax_year, alloc_fraction_normalised, annual_result).
    # Used for PeriodTaxYearAllocation and SAME_PERIOD accrual.
    period_year_contributions: dict[int, list[tuple[int, float, TaxAnnualResult]]] = {
        idx: [] for idx in all_period_indices
    }
    for ar in annual_results:
        raw_fracs = raw_frac_by_year[ar.tax_year]
        denom = year_alloc_sum.get(ar.tax_year, 1.0) or 1.0
        for idx in ar.period_indices:
            raw_frac = raw_fracs.get(idx, 0)
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
            # Per-year ATAD for this period (from ar.period_atad_* arrays).
            pos = first_pos_by_year[yr].get(idx)
            if pos is not None:
                yr_ded = ar.period_atad_deductible[pos]
                yr_dis = ar.period_atad_disallowed[pos]
            else:
                yr_ded = 0.0
                yr_dis = 0.0

            # Allocated amounts for this period in this year (from fragment amounts).
            frs = frags_by_period_by_year[yr].get(idx, ())
            yr_ebitda = sum(f.ebitda_keur for f in frs)
            yr_reint = sum(f.other_fiscal_reintegration_keur for f in frs)
            yr_shl_tax_eligible = sum(f.shl_tax_eligible_interest_keur for f in frs)
            yr_shl_non_deductible = sum(f.shl_non_deductible_interest_keur for f in frs)
            yr_financing_income = sum(f.financing_income_keur for f in frs)
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


class _CashTaxRow(NamedTuple):
    """The three ``PeriodCashTaxResult`` fields ``calculate_canonical_cfads`` reads."""
    period_index: int
    cash_tax_keur: float
    financing_income_keur: float


def _cfads_and_cash_tax_via_full_tax(
    periods: tuple, tax_input: TaxCalculationInput,
) -> tuple[dict[int, float], dict[int, float]]:
    tax_result = calculate_tax(periods, tax_input)
    cfads_results = calculate_canonical_cfads(periods, tax_result.period_results)
    return (
        {cr.period_index: cr.cfads_keur for cr in cfads_results},
        {pr.period_index: pr.cash_tax_keur for pr in tax_result.period_results},
    )


def _payment_period_for_year_lean(
    tax_year: int,
    idx_fracs: list[tuple[int, float]],
    period_end_by_index: dict[int, object],
) -> int:
    """Numeric twin of ``tax_year._payment_period_for_year`` (same rule, same order)."""
    candidates: list[int] = []
    for idx, _frac in idx_fracs:
        p_end = period_end_by_index.get(idx)
        if p_end is None:
            continue
        last_day = p_end - timedelta(days=1)  # type: ignore[operator]
        if last_day.year == tax_year:
            candidates.append(idx)
    if candidates:
        return max(set(candidates))
    period_fracs: dict[int, float] = {}
    for idx, frac in idx_fracs:
        period_fracs[idx] = period_fracs.get(idx, 0.0) + frac
    return max(period_fracs, key=lambda k: (period_fracs[k], k))


# Fragment kinds: how a period's amounts are distributed over calendar years.
_PASS_THROUGH = 0      # zero-length period: amounts unchanged (``_split_period``)
_SINGLE_FRAGMENT = 1   # one calendar year: the remainder fragment, amount - 0.0
_MULTI_FRAGMENT = 2    # spans 31 Dec: amount * fraction, last fragment takes the remainder


class _TaxPlan:
    """Everything ``calculate_cfads_and_cash_tax`` derives from the period axis alone.

    Depends only on ``periods`` (indices, dates, EBITDA, tax depreciation) — never on
    interest, adjustments, financing income or policy — so it is built once per period
    axis and reused by every solver evaluation of the run.
    """

    __slots__ = (
        "fallback", "year_keys", "rows", "y_ebitda", "y_dep", "payment_idx",
        "sorted_idx", "max_idx", "same_period_contributions",
    )


def _build_tax_plan(periods: tuple) -> _TaxPlan:
    plan = _TaxPlan()
    plan.fallback = True
    plan.same_period_contributions = None
    try:
        all_idx = [p.period_index for p in periods]  # type: ignore[attr-defined]
        if not periods or len(set(all_idx)) != len(all_idx):
            return plan

        # year -> [ebitda list, tax_dep list, [(period_index, allocation_fraction), ...]]
        years: dict[int, list] = {}
        raw_rows: list[tuple] = []
        for p in periods:
            idx = p.period_index          # type: ignore[attr-defined]
            p_start = p.period_start      # type: ignore[attr-defined]
            p_end = p.period_end          # type: ignore[attr-defined]
            ebitda = p.ebitda_keur        # type: ignore[attr-defined]
            tax_dep = p.tax_depreciation_keur  # type: ignore[attr-defined]
            total_days = (p_end - p_start).days
            if total_days < 0:
                return plan               # malformed axis: the full path reports it
            if total_days == 0:
                yr = p_end.year
                acc = years.setdefault(yr, [[], [], []])
                acc[0].append(ebitda)
                acc[1].append(tax_dep)
                acc[2].append((idx, 1.0))
                raw_rows.append((idx, _PASS_THROUGH, ((yr, 1.0),)))
                continue
            frag_geometry, fracs, _total = _period_geometry(p_start, p_end)
            last = len(frag_geometry) - 1
            acc_e = acc_d = 0.0
            slots = []
            for i, (yr, _fs, _fe, _fd) in enumerate(frag_geometry):
                frac = fracs[i]
                if i < last:
                    f_e = ebitda * frac
                    f_d = tax_dep * frac
                    acc_e += f_e
                    acc_d += f_d
                else:
                    f_e = ebitda - acc_e
                    f_d = tax_dep - acc_d
                acc = years.setdefault(yr, [[], [], []])
                acc[0].append(f_e)
                acc[1].append(f_d)
                acc[2].append((idx, frac))
                slots.append((yr, frac))
            raw_rows.append(
                (idx, _SINGLE_FRAGMENT if last == 0 else _MULTI_FRAGMENT, tuple(slots))
            )

        year_keys = sorted(years)
        pos_of_year = {yr: k for k, yr in enumerate(year_keys)}
        period_end_by_index = {p.period_index: p.period_end for p in periods}  # type: ignore[attr-defined]
        plan.year_keys = tuple(year_keys)
        plan.rows = tuple(
            (idx, kind, tuple((pos_of_year[yr], frac) for yr, frac in slots))
            for idx, kind, slots in raw_rows
        )
        plan.y_ebitda = tuple(sum(years[yr][0]) for yr in year_keys)
        plan.y_dep = tuple(sum(years[yr][1]) for yr in year_keys)
        plan.payment_idx = tuple(
            _payment_period_for_year_lean(yr, years[yr][2], period_end_by_index)
            for yr in year_keys
        )
        plan.sorted_idx = tuple(sorted(all_idx))
        plan.max_idx = max(all_idx)
        # SAME_PERIOD: per period, the (year position, normalised fraction) it contributes to.
        contributions: dict[int, list[tuple[int, float]]] = {idx: [] for idx in plan.sorted_idx}
        for k, yr in enumerate(year_keys):
            idx_fracs = years[yr][2]
            grouped: dict[int, list[float]] = {}
            for idx, frac in idx_fracs:
                grouped.setdefault(idx, []).append(frac)
            raw_fracs = {idx: sum(fr) for idx, fr in grouped.items()}
            period_indices = tuple(dict.fromkeys(idx for idx, _f in idx_fracs))
            year_alloc_sum = sum(raw_fracs.get(idx, 0) for idx in period_indices)
            denom = year_alloc_sum or 1.0
            for idx in period_indices:
                contributions[idx].append((k, raw_fracs.get(idx, 0) / denom))
        plan.same_period_contributions = contributions
        plan.fallback = False
        return plan
    except Exception:  # anything unexpected: let the full path behave exactly as before
        plan.fallback = True
        return plan


def _tax_plan_for(periods: tuple) -> _TaxPlan:
    """The plan for this period axis — reused within the current engine run scope."""
    scope = _current_run_scope()
    if scope is None:
        return _build_tax_plan(periods)
    plans = scope.setdefault("tax_plan", {})
    entry = plans.get(id(periods))
    if entry is not None and entry[0] is periods:
        return entry[1]
    plan = _build_tax_plan(periods)
    plans[id(periods)] = (periods, plan)   # keeps `periods` alive, so its id stays unique
    return plan


def calculate_cfads_and_cash_tax(
    periods: tuple,                 # tuple[OperatingPeriodResult]
    tax_input: TaxCalculationInput,
) -> tuple[dict[int, float], dict[int, float]]:
    """Per-period ``(cfads_keur, cash_tax_keur)`` maps, numerically identical to
    ``calculate_tax`` followed by ``calculate_canonical_cfads``.

    The senior-debt solver only consumes these two vectors, yet the full
    ``calculate_tax`` builds thousands of frozen result objects (fragments, annual
    and per-period allocation records) it then discards. This performs the same
    arithmetic in the same order — period splitting, annual aggregation, ATAD annual
    capacity, FIFO loss ledger, cash-tax timing — without constructing them, so every
    float is bit-identical. Quantities that depend only on the period axis are taken
    from a ``_TaxPlan`` built once per run. Anything outside the plain calendar-year
    basis (MODEL_YEAR_PAIRING, duplicate period indices, no policy, no periods, a
    malformed axis) is delegated to the full path, so unusual or malformed inputs fail
    exactly as before.
    """
    policy: TaxPolicy = tax_input.policy  # type: ignore[assignment]
    if (
        policy is None
        or policy.tax_basis_periodisation == TaxBasisPeriodisation.MODEL_YEAR_PAIRING
    ):
        return _cfads_and_cash_tax_via_full_tax(periods, tax_input)
    plan = _tax_plan_for(periods)
    if plan.fallback:
        return _cfads_and_cash_tax_via_full_tax(periods, tax_input)

    interest_map = _build_interest_map(tax_input.period_interest)
    adj_map = _build_adj_map(tax_input.period_adjustments)
    financing_income_map = _build_financing_income_map(tax_input)

    # ── Steps 1-2: distribute the period amounts over calendar years ─────────────
    n_years = len(plan.year_keys)
    y_interest_lists: list[list[float]] = [[] for _ in range(n_years)]
    y_reint_lists: list[list[float]] = [[] for _ in range(n_years)]
    y_shl_nd_lists: list[list[float]] = [[] for _ in range(n_years)]
    y_fin_lists: list[list[float]] = [[] for _ in range(n_years)]
    for idx, kind, slots in plan.rows:
        pi_obj = interest_map.get(idx)
        if pi_obj:
            shl_tax_eligible, shl_non_deductible = _resolve_shl_tax_eligible_interest(
                pi_obj, policy
            )
            gross_int = (
                pi_obj.senior_interest_keur
                + pi_obj.other_interest_keur
                + shl_tax_eligible
            )
        else:
            gross_int = 0.0
            shl_non_deductible = 0.0
        reint = adj_map.get(idx, 0.0)
        fin_income = financing_income_map.get(idx, 0.0)

        if kind == _MULTI_FRAGMENT:
            acc_i = acc_r = acc_n = acc_f = 0.0
            last = len(slots) - 1
            for i, (pos, frac) in enumerate(slots):
                if i < last:
                    f_i = gross_int * frac
                    f_r = reint * frac
                    f_n = shl_non_deductible * frac
                    f_f = fin_income * frac
                    acc_i += f_i
                    acc_r += f_r
                    acc_n += f_n
                    acc_f += f_f
                else:
                    f_i = gross_int - acc_i
                    f_r = reint - acc_r
                    f_n = shl_non_deductible - acc_n
                    f_f = fin_income - acc_f
                y_interest_lists[pos].append(f_i)
                y_reint_lists[pos].append(f_r)
                y_shl_nd_lists[pos].append(f_n)
                y_fin_lists[pos].append(f_f)
        elif kind == _SINGLE_FRAGMENT:
            pos = slots[0][0]
            y_interest_lists[pos].append(gross_int - 0.0)
            y_reint_lists[pos].append(reint - 0.0)
            y_shl_nd_lists[pos].append(shl_non_deductible - 0.0)
            y_fin_lists[pos].append(fin_income - 0.0)
        else:
            pos = slots[0][0]
            y_interest_lists[pos].append(gross_int)
            y_reint_lists[pos].append(reint)
            y_shl_nd_lists[pos].append(shl_non_deductible)
            y_fin_lists[pos].append(fin_income)

    # ── Step 3: ATAD annual capacity, taxable income, FIFO loss ledger, CIT ──────
    taxable_before_lcf: list[float] = []
    loss_gate = policy.loss_utilisation_gate == TaxLossUtilisationGate.EBT_POSITIVE
    loss_use_allowed_list: list[bool] = []
    atad_enabled = policy.atad_enabled
    for k in range(n_years):
        y_ebitda = plan.y_ebitda[k]
        y_dep = plan.y_dep[k]
        y_interest = sum(y_interest_lists[k])
        y_reint = sum(y_reint_lists[k])
        y_shl_nd = sum(y_shl_nd_lists[k])
        y_fin = sum(y_fin_lists[k])

        total = y_interest
        if not atad_enabled or total <= 0:
            deductible = total
        else:
            ebitda_based = y_ebitda * policy.atad_ebitda_limit
            threshold = policy.atad_de_minimis_threshold_keur_annual
            capacity = ebitda_based if ebitda_based >= threshold else threshold
            deductible = min(total, max(0.0, capacity))

        taxable_before_lcf.append(
            (
                y_ebitda
                + y_fin
                - y_dep
                - deductible
                + y_reint
            )
        )
        if loss_gate:
            loss_use_allowed_list.append(
                (
                    y_ebitda
                    + y_fin
                    - y_dep
                    - y_interest
                    - y_shl_nd
                    + y_reint
                ) > 0.0
            )

    taxable_after_lcf = taxable_income_after_lcf_series(
        taxable_income_before_lcf=tuple(taxable_before_lcf),
        tax_year_indices=plan.year_keys,
        opening_inputs=tax_input.opening_loss_vintages,
        loss_carryforward_years=policy.loss_carryforward_years,
        loss_use_allowed=tuple(loss_use_allowed_list) if loss_gate else None,
    )
    liabilities: list[float] = [
        policy.corporate_rate * max(0.0, ti_after) for ti_after in taxable_after_lcf
    ]

    # ── Step 4: allocate cash tax to periods ─────────────────────────────────────
    cash_tax_by_period: dict[int, float] = {idx: 0.0 for idx in plan.sorted_idx}

    if policy.cash_tax_timing in (
        CashTaxTiming.TAX_YEAR_LAST_PERIOD,
        CashTaxTiming.MODEL_YEAR_PAYMENT_PERIOD,
    ):
        lag = policy.cash_tax_payment_lag_periods
        max_period_idx = plan.max_idx
        for base_payment, liability in zip(plan.payment_idx, liabilities):
            payment_period = base_payment + lag
            if payment_period <= max_period_idx:
                cash_tax_by_period[payment_period] = (
                    cash_tax_by_period[payment_period] + liability
                )
    else:
        # SAME_PERIOD: each period's share = sum(annual_CIT x normalised alloc_frac).
        contributions = plan.same_period_contributions
        for idx in plan.sorted_idx:
            for k, norm_frac in contributions[idx]:
                cash_tax_by_period[idx] = cash_tax_by_period[idx] + liabilities[k] * norm_frac

    # ── Step 5: canonical CFADS — the formula stays in cfads.py (single authority) ──
    rows = tuple(
        _CashTaxRow(
            p.period_index,  # type: ignore[attr-defined]
            cash_tax_by_period.get(p.period_index, 0.0),  # type: ignore[attr-defined]
            financing_income_map.get(p.period_index, 0.0),  # type: ignore[attr-defined]
        )
        for p in periods
    )
    cfads_results = calculate_canonical_cfads(periods, rows)  # type: ignore[arg-type]
    return (
        {cr.period_index: cr.cfads_keur for cr in cfads_results},
        {row.period_index: row.cash_tax_keur for row in rows},
    )
