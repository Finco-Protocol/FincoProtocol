"""financial_engine.tax.tax_year — Calendar tax-year period allocator.

Splits model periods into calendar-year fragments and aggregates them into
TaxYearCalculationBasis records.  Periods that cross 31 December are split
on that boundary; the allocation fraction is proportional to the calendar-day
count in each fragment.

Rules
-----
* ``tax_year`` is the 4-digit calendar year of the fragment (e.g. 2030).
* All fragments for a period sum to ``allocation_fraction == 1.0``.
* Fragment ``days`` uses ``(frag_end − frag_start).days`` so the sum equals
  ``(period_end − period_start).days``.  For periods of length 0 the single
  fragment has ``days=0`` and ``allocation_fraction=1.0``.
* EBITDA, tax depreciation, interest and fiscal reintegration are allocated
  proportionally and stored directly on each fragment.
* Every calendar year that contains at least one fragment from any period
  produces a ``TaxYearCalculationBasis`` — no year is skipped because a period
  only has a "minority" allocation to it.  Cross-year periods appear in the
  ``period_indices`` of every year they contribute to.

Pure function.  No imports from app, finco_core or any framework.
"""
from __future__ import annotations

from collections import defaultdict
from datetime import date, timedelta

from financial_engine.inputs import PeriodInterestInput
from financial_engine.policies.tax import TaxPolicy
from financial_engine.tax.models import TaxYearCalculationBasis, TaxYearPeriodFragment


def _resolve_shl_tax_eligible_interest(
    period_interest: PeriodInterestInput,
    policy: TaxPolicy | None,
) -> tuple[float, float]:
    """Resolve deductible-only SHL interest from one authoritative input path."""

    gross = period_interest.shl_interest_keur
    override = period_interest.shl_deductible_interest_keur
    if override is not None:
        if override < -1e-12 or override > gross + 1e-12:
            raise ValueError(
                "SHL_DEDUCTIBLE_INTEREST_OUT_OF_RANGE: deductible SHL interest "
                f"{override} must be in [0, gross={gross}]"
            )
        eligible = min(max(override, 0.0), gross)
    else:
        fraction = policy.shl_tax_deductible_fraction() if policy is not None else 1.0
        eligible = gross * fraction
    non_deductible = gross - eligible
    if abs((eligible + non_deductible) - gross) > 1e-10:
        raise ArithmeticError("SHL_DEDUCTIBLE_DISALLOWED_IDENTITY_BROKEN")
    return eligible, non_deductible


def _split_period(
    period_index: int,
    period_start: date,
    period_end: date,
    ebitda_keur: float = 0.0,
    tax_depreciation_keur: float = 0.0,
    total_interest_keur: float = 0.0,
    other_fiscal_reintegration_keur: float = 0.0,
    shl_tax_eligible_interest_keur: float = 0.0,
    shl_non_deductible_interest_keur: float = 0.0,
    financing_income_keur: float = 0.0,  # U2: cash/reserve interest income (below EBITDA)
) -> list[TaxYearPeriodFragment]:
    """Split one period into calendar-year fragments with allocated amounts.

    Uses the half-open interval convention [period_start, period_end) so that
    fragment days sum to (period_end − period_start).days.

    Year boundary: fragment for calendar year Y covers
        [max(period_start, Jan 1 Y),  min(period_end, Jan 1 (Y+1)))

    fragment.days = (frag_end - frag_start).days   (consistent with the
    period engine's own days_in_period computation for crossing periods)

    Allocation fraction: frag_days / sum(all_frag_days).  The last fragment's
    fraction is adjusted to ensure exact sum == 1.0.

    Each fragment carries the pre-allocated amounts: period_amount × fraction.

    Zero-length periods ((period_end - period_start).days == 0) receive a
    single zero-day fragment with allocation_fraction == 1.0 and the full
    period amounts (fraction = 1.0 so amounts pass through unchanged).
    """
    total_days = (period_end - period_start).days

    if total_days == 0:
        return [TaxYearPeriodFragment(
            tax_year=period_end.year,
            source_period_index=period_index,
            start_date=period_start,
            end_date=period_end,
            days=0,
            source_period_days=0,
            allocation_fraction=1.0,
            ebitda_keur=ebitda_keur,
            tax_depreciation_keur=tax_depreciation_keur,
            total_interest_keur=total_interest_keur,
            other_fiscal_reintegration_keur=other_fiscal_reintegration_keur,
            shl_tax_eligible_interest_keur=shl_tax_eligible_interest_keur,
            shl_non_deductible_interest_keur=shl_non_deductible_interest_keur,
            financing_income_keur=financing_income_keur,
        )]

    fragments: list[tuple[int, date, date, int]] = []
    cur_start = period_start

    while cur_start < period_end:
        cur_year = cur_start.year
        next_jan1 = date(cur_year + 1, 1, 1)
        frag_end = min(period_end, next_jan1)
        frag_days = (frag_end - cur_start).days
        fragments.append((cur_year, cur_start, frag_end, frag_days))
        cur_start = frag_end  # move to start of next year (= frag_end)

    # Compute fractions; last fraction is adjusted for exact 1.0 sum.
    total_frag_days = sum(fd for _, _, _, fd in fragments)
    assert total_frag_days > 0, (
        f"Internal error: fragments sum to 0 for period {period_index} "
        f"({period_start} → {period_end}, total_days={total_days})"
    )
    fracs = [fd / total_frag_days for _, _, _, fd in fragments]
    fracs[-1] = 1.0 - sum(fracs[:-1])

    result = []
    accumulated_ebitda = 0.0
    accumulated_dep = 0.0
    accumulated_int = 0.0
    accumulated_reint = 0.0
    accumulated_shl_tax_eligible = 0.0
    accumulated_shl_non_deductible = 0.0
    accumulated_financing_income = 0.0

    for i, ((yr, fs, fe, fd), frac) in enumerate(zip(fragments, fracs)):
        if i < len(fragments) - 1:
            frag_ebitda = ebitda_keur * frac
            frag_dep = tax_depreciation_keur * frac
            frag_int = total_interest_keur * frac
            frag_reint = other_fiscal_reintegration_keur * frac
            frag_shl_tax_eligible = shl_tax_eligible_interest_keur * frac
            frag_shl_non_deductible = shl_non_deductible_interest_keur * frac
            frag_financing_income = financing_income_keur * frac
            accumulated_ebitda += frag_ebitda
            accumulated_dep += frag_dep
            accumulated_int += frag_int
            accumulated_reint += frag_reint
            accumulated_shl_tax_eligible += frag_shl_tax_eligible
            accumulated_shl_non_deductible += frag_shl_non_deductible
            accumulated_financing_income += frag_financing_income
        else:
            # Last fragment: use remainder to preserve exact totals.
            frag_ebitda = ebitda_keur - accumulated_ebitda
            frag_dep = tax_depreciation_keur - accumulated_dep
            frag_int = total_interest_keur - accumulated_int
            frag_reint = other_fiscal_reintegration_keur - accumulated_reint
            frag_shl_tax_eligible = (
                shl_tax_eligible_interest_keur - accumulated_shl_tax_eligible
            )
            frag_shl_non_deductible = (
                shl_non_deductible_interest_keur - accumulated_shl_non_deductible
            )
            frag_financing_income = financing_income_keur - accumulated_financing_income

        result.append(TaxYearPeriodFragment(
            tax_year=yr,
            source_period_index=period_index,
            start_date=fs,
            end_date=fe,
            days=fd,
            source_period_days=total_frag_days,
            allocation_fraction=frac,
            ebitda_keur=frag_ebitda,
            tax_depreciation_keur=frag_dep,
            total_interest_keur=frag_int,
            other_fiscal_reintegration_keur=frag_reint,
            shl_tax_eligible_interest_keur=frag_shl_tax_eligible,
            shl_non_deductible_interest_keur=frag_shl_non_deductible,
            financing_income_keur=frag_financing_income,
        ))

    return result


def _payment_period_for_year(
    tax_year: int,
    frags_for_year: tuple[TaxYearPeriodFragment, ...],
    periods_by_index: dict[int, object],
) -> int:
    """Return the period_index that receives TAX_YEAR_LAST_PERIOD cash tax.

    Selects the period whose ``period_end`` falls within ``tax_year`` and has
    the latest period_index.  If no period ends within the tax year (edge case),
    falls back to the period with the maximum allocation fraction.
    """
    candidates: list[int] = []
    for frag in frags_for_year:
        p = periods_by_index.get(frag.source_period_index)
        if p is None:
            continue
        p_end: date = p.period_end  # type: ignore[attr-defined]
        # Under the half-open [start, end) convention, the last calendar day of
        # the period is p_end - 1 day. If that day falls in tax_year, the period
        # "ends" in this tax year and is a payment candidate.
        # This handles both Jun30→Jan1 H2 periods (last day Dec31 = tax_year ✓)
        # and Dec31→Jun30 H1 periods with a 1-day fragment in the prior year (last day Jun29 ✗ correct).
        last_day = p_end - timedelta(days=1)
        if last_day.year == tax_year:
            candidates.append(frag.source_period_index)
    if candidates:
        # latest by period_index (chronological order)
        return max(set(candidates))
    # Fallback: period with maximum total allocation fraction to this year
    period_fracs: dict[int, float] = {}
    for frag in frags_for_year:
        period_fracs[frag.source_period_index] = (
            period_fracs.get(frag.source_period_index, 0.0) + frag.allocation_fraction
        )
    return max(period_fracs, key=lambda k: (period_fracs[k], k))


def build_tax_year_bases(
    periods: tuple,              # tuple[OperatingPeriodResult]
    interest_map: dict[int, PeriodInterestInput],
    adj_map: dict[int, float],
    policy: TaxPolicy | None = None,
    financing_income_map: dict[int, float] | None = None,  # U2: period_index → financing_income_keur
) -> tuple[TaxYearCalculationBasis, ...]:
    """Aggregate period amounts into calendar-year TaxYearCalculationBasis records.

    Periods are split on 31 December when they cross year-end.  Each fragment
    contributes its allocated amounts to the fragment's calendar year.

    Every calendar year that contains at least one fragment from any period
    produces a ``TaxYearCalculationBasis``.  A period that spans two years
    appears in ``period_indices`` for BOTH years.  There is no primary-year
    ownership — minority-year contributions are never dropped.

    Parameters
    ----------
    periods:
        All model periods (including construction) from the Phase 2A orchestrator.
    interest_map:
        Mapping period_index → PeriodInterestInput.
    adj_map:
        Mapping period_index → other_fiscal_reintegration_keur.

    Returns
    -------
    Tuple of TaxYearCalculationBasis, sorted by ascending calendar year.
    """
    from financial_engine.policies.tax import TaxBasisPeriodisation

    if (
        policy is not None
        and policy.tax_basis_periodisation == TaxBasisPeriodisation.MODEL_YEAR_PAIRING
    ):
        return _build_model_year_pairing_bases(periods, interest_map, adj_map, policy, financing_income_map)

    # Single-pass: use shl_tax_deductible_fraction() for all modes.
    # For SUBJECT_TO_LIMITATIONS, shl_tax_deductible_fraction() returns 1.0 (SHL fully
    # included in total_interest). The ATAD mechanism (atad_enabled=True) then applies the
    # annual EBITDA-based limitation to total interest including SHL.
    # The unsourced absolute annual SHL cap (two-pass per-year approach) has been removed.

    year_fragments: dict[int, list[TaxYearPeriodFragment]] = defaultdict(list)

    for p in periods:
        idx: int = p.period_index          # type: ignore[attr-defined]
        p_start: date = p.period_start     # type: ignore[attr-defined]
        p_end: date = p.period_end         # type: ignore[attr-defined]
        ebitda: float = p.ebitda_keur      # type: ignore[attr-defined]
        tax_dep: float = p.tax_depreciation_keur  # type: ignore[attr-defined]

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
            shl_tax_eligible = 0.0
            shl_non_deductible = 0.0
        reint = adj_map.get(idx, 0.0)
        fin_income = (financing_income_map or {}).get(idx, 0.0)

        frags = _split_period(
            idx, p_start, p_end,
            ebitda_keur=ebitda,
            tax_depreciation_keur=tax_dep,
            total_interest_keur=gross_int,
            other_fiscal_reintegration_keur=reint,
            shl_tax_eligible_interest_keur=shl_tax_eligible,
            shl_non_deductible_interest_keur=shl_non_deductible,
            financing_income_keur=fin_income,
        )

        for frag in frags:
            year_fragments[frag.tax_year].append(frag)

    # Build index for payment_period resolution
    periods_by_index: dict[int, object] = {
        p.period_index: p  # type: ignore[attr-defined]
        for p in periods
    }

    bases: list[TaxYearCalculationBasis] = []
    for yr in sorted(year_fragments.keys()):
        frags_for_year = tuple(year_fragments[yr])

        # Every period with any fragment in this year is listed.
        # Preserve insertion order (chronological by source_period_index).
        period_indices = tuple(dict.fromkeys(
            frag.source_period_index for frag in frags_for_year
        ))

        # Sum amounts from the pre-allocated fragment fields.
        year_ebitda = sum(f.ebitda_keur for f in frags_for_year)
        year_tax_dep = sum(f.tax_depreciation_keur for f in frags_for_year)
        year_interest = sum(f.total_interest_keur for f in frags_for_year)
        year_reint = sum(f.other_fiscal_reintegration_keur for f in frags_for_year)
        year_shl_tax_eligible = sum(
            f.shl_tax_eligible_interest_keur for f in frags_for_year
        )
        year_shl_non_deductible = sum(
            f.shl_non_deductible_interest_keur for f in frags_for_year
        )
        year_financing_income = sum(f.financing_income_keur for f in frags_for_year)

        payment_idx = _payment_period_for_year(yr, frags_for_year, periods_by_index)
        bases.append(TaxYearCalculationBasis(
            tax_year=yr,
            fragments=frags_for_year,
            period_indices=period_indices,
            payment_period_index=payment_idx,
            ebitda_keur=year_ebitda,
            tax_depreciation_keur=year_tax_dep,
            total_interest_keur=year_interest,
            other_fiscal_reintegration_keur=year_reint,
            shl_tax_eligible_interest_keur=year_shl_tax_eligible,
            shl_non_deductible_interest_keur=year_shl_non_deductible,
            financing_income_keur=year_financing_income,
        ))

    return tuple(bases)


def _build_model_year_pairing_bases(
    periods: tuple,
    interest_map: dict[int, PeriodInterestInput],
    adj_map: dict[int, float],
    policy: TaxPolicy,
    financing_income_map: dict[int, float] | None = None,
) -> tuple[TaxYearCalculationBasis, ...]:
    """Aggregate H2(period N) + H1(period N+1) reference methodology tax years.

    This source-compatibility mode is selected only by an explicit runtime tax
    policy. It is not project identity dispatch and it does not consume source
    output vectors. The resulting tax-year label is the H1 period end year and
    the cash payment period is the H1 period itself, matching the source model's
    paired-period CIT convention.
    """
    fragments_by_year: dict[int, list[TaxYearPeriodFragment]] = defaultdict(list)

    for p in periods:
        idx: int = p.period_index  # type: ignore[attr-defined]
        if not getattr(p, "is_operation", False):
            continue
        period_in_year = int(getattr(p, "period_in_year", 0))
        if period_in_year not in (1, 2):
            raise ValueError(
                "MODEL_YEAR_PAIRING_REQUIRES_SEMI_ANNUAL_PERIODS: "
                f"period_index={idx}; period_in_year={period_in_year!r}"
            )

        period_end = p.period_end  # type: ignore[attr-defined]
        if period_end.month == 6:
            tax_year = period_end.year
        elif period_end.month == 12:
            tax_year = period_end.year + 1
        else:
            raise ValueError(
                "MODEL_YEAR_PAIRING_REQUIRES_JUNE_DECEMBER_PERIOD_ENDS: "
                f"period_index={idx}; period_end={period_end!r}"
            )
        pi_obj = interest_map.get(idx)
        if pi_obj:
            shl_tax_eligible, shl_non_deductible = _resolve_shl_tax_eligible_interest(
                pi_obj, policy
            )
            gross_int = pi_obj.senior_interest_keur + pi_obj.other_interest_keur + shl_tax_eligible
        else:
            gross_int = 0.0
            shl_tax_eligible = 0.0
            shl_non_deductible = 0.0

        fragments_by_year[tax_year].append(
            TaxYearPeriodFragment(
                tax_year=tax_year,
                source_period_index=idx,
                start_date=p.period_start,  # type: ignore[attr-defined]
                end_date=p.period_end,  # type: ignore[attr-defined]
                days=p.days_in_period,  # type: ignore[attr-defined]
                source_period_days=p.days_in_period,  # type: ignore[attr-defined]
                allocation_fraction=1.0,
                ebitda_keur=p.ebitda_keur,  # type: ignore[attr-defined]
                tax_depreciation_keur=p.tax_depreciation_keur,  # type: ignore[attr-defined]
                total_interest_keur=gross_int,
                other_fiscal_reintegration_keur=adj_map.get(idx, 0.0),
                shl_tax_eligible_interest_keur=shl_tax_eligible,
                shl_non_deductible_interest_keur=shl_non_deductible,
                financing_income_keur=(financing_income_map or {}).get(idx, 0.0),
            )
        )

    bases: list[TaxYearCalculationBasis] = []
    for tax_year in sorted(fragments_by_year):
        frags_for_year = tuple(fragments_by_year[tax_year])
        period_indices = tuple(f.source_period_index for f in frags_for_year)
        h1_periods = [
            p for p in periods
            if p.period_index in period_indices  # type: ignore[attr-defined]
            and p.period_end.month == 6  # type: ignore[attr-defined]
        ]
        payment_idx = (
            h1_periods[-1].period_index  # type: ignore[attr-defined]
            if h1_periods
            else period_indices[-1]
        )
        bases.append(
            TaxYearCalculationBasis(
                tax_year=tax_year,
                fragments=frags_for_year,
                period_indices=period_indices,
                payment_period_index=payment_idx,
                ebitda_keur=sum(f.ebitda_keur for f in frags_for_year),
                tax_depreciation_keur=sum(f.tax_depreciation_keur for f in frags_for_year),
                total_interest_keur=sum(f.total_interest_keur for f in frags_for_year),
                other_fiscal_reintegration_keur=sum(
                    f.other_fiscal_reintegration_keur for f in frags_for_year
                ),
                shl_tax_eligible_interest_keur=sum(
                    f.shl_tax_eligible_interest_keur for f in frags_for_year
                ),
                shl_non_deductible_interest_keur=sum(
                    f.shl_non_deductible_interest_keur for f in frags_for_year
                ),
                financing_income_keur=sum(f.financing_income_keur for f in frags_for_year),
            )
        )
    return tuple(bases)
