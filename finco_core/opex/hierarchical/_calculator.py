"""Hierarchical OPEX calculation — public checked API and internal helpers.

Public API
----------
compute_annual()   — validates model + context, then computes annual OPEX.
compute_periods()  — validates model + context, then computes period OPEX.

Both raise OpexInputValidationError (carrying all issues) if validation
finds any ERROR-severity issue.

Internal helpers
----------------
_compute_annual_unchecked()
_compute_periods_unchecked()
Pure calculation, no validation.  Called by the public checked wrappers after
successful validation.  May also be used by tests that deliberately supply
pre-validated or intentionally invalid inputs.

Design constraints
------------------
* All functions are side-effect-free.
* No project identifiers, scenario names, or debt-solver outputs are accessed.
* _ext_value() asserts that the requested code and year_idx are in bounds;
  it never silently converts missing data to zero.  A series entry of 0.0 is
  a valid explicit zero; absence is an invariant violation.
"""
from __future__ import annotations

from typing import Iterable

from ._inputs import (
    OpexCalculationContext,
    OpexCategoryInput,
    OpexModelInput,
    OpexSubitemInput,
)
from ._results import (
    CategoryAnnualResult,
    CategoryPeriodResult,
    OpexAnnualResult,
    OpexPeriodResult,
    SubitemAnnualResult,
    SubitemPeriodResult,
)
from ._types import (
    OpexActivationMode,
    OpexAmountBasis,
    OpexCategoryCalculationType,
    OpexEscalationConvention,
)
from ._validation import OpexValidationIssue, has_errors, validate_opex_model_input


# ---------------------------------------------------------------------------
# Public exception
# ---------------------------------------------------------------------------


class OpexInputValidationError(Exception):
    """Raised by public compute functions when validation finds ERROR issues.

    Attributes
    ----------
    issues : tuple[OpexValidationIssue, ...]
        All issues returned by validate_opex_model_input; always contains at
        least one ERROR-severity entry.
    """

    def __init__(self, issues: tuple[OpexValidationIssue, ...]) -> None:
        self.issues = issues
        codes = ", ".join(i.code for i in issues if i.severity.value == "ERROR")
        super().__init__(
            f"OPEX model input is invalid ({len(issues)} issue(s)); "
            f"ERROR codes: {codes}"
        )


# ---------------------------------------------------------------------------
# Activation helpers
# ---------------------------------------------------------------------------


def _resolve_annual_activation(
    si: OpexSubitemInput,
    year_idx: int,  # 0-based: year_idx=0 → operating year 1
    context: OpexCalculationContext,
) -> bool:
    mode = si.activation_mode
    if mode == OpexActivationMode.ALWAYS:
        return True
    if mode == OpexActivationMode.SENIOR_DEBT_TENOR_ACTIVE:
        return (year_idx + 1) <= context.senior_debt_tenor_years
    if mode == OpexActivationMode.MANUAL:
        flags = si.activation_schedule.annual_flags  # type: ignore[union-attr]
        return bool(flags[year_idx]) if year_idx < len(flags) else False
    raise ValueError(f"Unsupported activation_mode: {mode!r}")


def _resolve_period_activation(
    si: OpexSubitemInput,
    year_idx: int,   # 0-based
    period_in_year: int,  # 1 or 2
    context: OpexCalculationContext,
) -> bool:
    """Resolve activation for a specific period half, honouring H1/H2 overrides.

    A period override takes precedence over the annual flag.
    For ALWAYS / SENIOR_DEBT_TENOR_ACTIVE there are no period overrides,
    so this always falls back to the annual activation logic.
    """
    if (
        si.activation_mode == OpexActivationMode.MANUAL
        and si.activation_schedule is not None
    ):
        key = (year_idx + 1, period_in_year)  # year_idx 0-based → 1-based year
        for override_key, val in si.activation_schedule.period_overrides:
            if override_key == key:
                return bool(val)
    return _resolve_annual_activation(si, year_idx, context)


# ---------------------------------------------------------------------------
# Escalation helper
# ---------------------------------------------------------------------------


def _escalation_factor(
    inflation_rate: float,
    convention: OpexEscalationConvention,
    year_idx: int,  # 0-based
) -> float:
    """Return the escalation multiplier for operating year (year_idx+1).

    YEAR_1_AS_BASE:    Y1 = 1.0,  Yn = (1+inf)^(n-1)
    PRE_OPERATION_BASE: Y1 = (1+inf),  Yn = (1+inf)^n
    """
    if convention == OpexEscalationConvention.YEAR_1_AS_BASE:
        return (1.0 + inflation_rate) ** year_idx
    if convention == OpexEscalationConvention.PRE_OPERATION_BASE:
        return (1.0 + inflation_rate) ** (year_idx + 1)
    raise ValueError(f"Unsupported escalation_convention: {convention!r}")


# ---------------------------------------------------------------------------
# External series lookup
# ---------------------------------------------------------------------------


def _build_ext_lookup(context: OpexCalculationContext) -> dict[str, tuple[float, ...]]:
    return dict(context.external_annual_series)


def _ext_value(ext: dict[str, tuple[float, ...]], code: str, year_idx: int) -> float:
    """Return the external series value for code at year_idx.

    Raises AssertionError if:
    - code is not in ext (invariant violation — validation should have caught this)
    - year_idx is out of range (invariant violation — series is shorter than horizon)

    An explicit 0.0 in the series is a valid value and is returned as-is.
    Missing data must never silently become 0.0.
    """
    assert code in ext, (
        f"_ext_value: code {code!r} not in external_annual_series — "
        "this is a validation invariant violation; validate before computing"
    )
    vals = ext[code]
    assert year_idx < len(vals), (
        f"_ext_value: code {code!r} has {len(vals)} values but year_idx={year_idx} "
        "is out of range — series is shorter than the computation horizon; "
        "validate before computing"
    )
    return float(vals[year_idx])


# ---------------------------------------------------------------------------
# Internal unchecked computation (pure, no validation)
# ---------------------------------------------------------------------------


def _compute_annual_unchecked(
    model: OpexModelInput,
    context: OpexCalculationContext,
    horizon_years: int,
) -> tuple[OpexAnnualResult, ...]:
    """Compute annual OPEX without validation. Use compute_annual() for the public API."""
    ext = _build_ext_lookup(context)
    results: list[OpexAnnualResult] = []

    for year_idx in range(horizon_years):
        year_num = year_idx + 1

        # --- Pass 1: SUBITEM_SUM -------------------------------------------
        cat_annual_keur: dict[str, float] = {}
        cat_si_results: dict[str, list[SubitemAnnualResult]] = {}

        for cat in model.categories:
            if cat.calculation_type != OpexCategoryCalculationType.SUBITEM_SUM:
                continue
            esc = _escalation_factor(cat.inflation_rate, cat.escalation_convention, year_idx)
            si_results: list[SubitemAnnualResult] = []
            active_base_sum = 0.0

            for si in cat.subitems:
                if si.amount_basis not in (OpexAmountBasis.ANNUAL_RUN_RATE,):
                    raise ValueError(
                        f"Unsupported amount_basis {si.amount_basis!r} for subitem "
                        f"{si.code!r} in category {cat.code!r}"
                    )
                active = _resolve_annual_activation(si, year_idx, context)
                contribution = si.base_amount_keur if active else 0.0
                active_base_sum += contribution
                si_results.append(
                    SubitemAnnualResult(
                        code=si.code,
                        name=si.name,
                        base_amount_keur=si.base_amount_keur,
                        active=active,
                        escalation_factor=esc,
                        annual_keur=contribution * esc,
                    )
                )

            total = active_base_sum * esc
            cat_annual_keur[cat.code] = total
            cat_si_results[cat.code] = si_results

        # --- Pass 2: PERCENTAGE_OF_SELECTED_BASES ---------------------------
        for cat in model.categories:
            if cat.calculation_type != OpexCategoryCalculationType.PERCENTAGE_OF_SELECTED_BASES:
                continue
            base_sum = 0.0
            for base_code in cat.percentage_base_codes:
                if base_code in cat_annual_keur:
                    base_sum += cat_annual_keur[base_code]
                else:
                    base_sum += _ext_value(ext, base_code, year_idx)

            total = cat.percentage_rate * base_sum
            cat_annual_keur[cat.code] = total
            cat_si_results[cat.code] = []

        # --- Assemble in original category order ----------------------------
        cat_results: list[CategoryAnnualResult] = []
        for cat in model.categories:
            cat_results.append(
                CategoryAnnualResult(
                    code=cat.code,
                    name=cat.name,
                    subitems=tuple(cat_si_results.get(cat.code, [])),
                    annual_keur=cat_annual_keur.get(cat.code, 0.0),
                )
            )

        total_keur = sum(r.annual_keur for r in cat_results)
        results.append(
            OpexAnnualResult(
                year_index=year_num,
                categories=tuple(cat_results),
                total_keur=total_keur,
            )
        )

    return tuple(results)


def _compute_periods_unchecked(
    model: OpexModelInput,
    context: OpexCalculationContext,
    periods: Iterable,
) -> tuple[OpexPeriodResult, ...]:
    """Compute period OPEX without validation. Use compute_periods() for the public API."""
    ext = _build_ext_lookup(context)
    results: list[OpexPeriodResult] = []

    for period in periods:
        if not period.is_operation:
            continue

        year_idx = period.year_index - 1
        half = getattr(period, "period_in_year", 1)
        df = period.day_fraction

        # --- Pass 1: SUBITEM_SUM -------------------------------------------
        cat_period_keur: dict[str, float] = {}
        cat_si_period_results: dict[str, list[SubitemPeriodResult]] = {}

        for cat in model.categories:
            if cat.calculation_type != OpexCategoryCalculationType.SUBITEM_SUM:
                continue
            esc = _escalation_factor(cat.inflation_rate, cat.escalation_convention, year_idx)
            si_results: list[SubitemPeriodResult] = []
            active_base_sum = 0.0

            for si in cat.subitems:
                if si.amount_basis not in (OpexAmountBasis.ANNUAL_RUN_RATE,):
                    raise ValueError(
                        f"Unsupported amount_basis {si.amount_basis!r} for subitem "
                        f"{si.code!r} in category {cat.code!r}"
                    )
                active = _resolve_period_activation(si, year_idx, half, context)
                contribution = si.base_amount_keur if active else 0.0
                active_base_sum += contribution
                si_results.append(
                    SubitemPeriodResult(
                        code=si.code,
                        name=si.name,
                        active=active,
                        period_keur=contribution * esc * df,
                    )
                )

            period_total = active_base_sum * esc * df
            cat_period_keur[cat.code] = period_total
            cat_si_period_results[cat.code] = si_results

        # --- Pass 2: PERCENTAGE_OF_SELECTED_BASES ---------------------------
        for cat in model.categories:
            if cat.calculation_type != OpexCategoryCalculationType.PERCENTAGE_OF_SELECTED_BASES:
                continue
            base_sum = 0.0
            for base_code in cat.percentage_base_codes:
                if base_code in cat_period_keur:
                    base_sum += cat_period_keur[base_code]
                else:
                    # External series: scale annual value by day_fraction
                    base_sum += _ext_value(ext, base_code, year_idx) * df

            period_total = cat.percentage_rate * base_sum
            cat_period_keur[cat.code] = period_total
            cat_si_period_results[cat.code] = []

        # --- Assemble ---------------------------------------------------
        cat_results: list[CategoryPeriodResult] = []
        for cat in model.categories:
            cat_results.append(
                CategoryPeriodResult(
                    code=cat.code,
                    name=cat.name,
                    subitems=tuple(cat_si_period_results.get(cat.code, [])),
                    period_keur=cat_period_keur.get(cat.code, 0.0),
                )
            )

        results.append(
            OpexPeriodResult(
                period_index=period.index,
                year_index=period.year_index,
                period_in_year=half,
                day_fraction=df,
                categories=tuple(cat_results),
                total_keur=sum(r.period_keur for r in cat_results),
            )
        )

    return tuple(results)


# ---------------------------------------------------------------------------
# Public checked API
# ---------------------------------------------------------------------------


def compute_annual(
    model: OpexModelInput,
    context: OpexCalculationContext,
    horizon_years: int,
) -> tuple[OpexAnnualResult, ...]:
    """Validate then compute annual OPEX for operating years 1..horizon_years.

    Raises OpexInputValidationError if validation finds any ERROR-severity issue.

    Two-pass per year:
        Pass 1 — SUBITEM_SUM categories (independent of each other).
        Pass 2 — PERCENTAGE_OF_SELECTED_BASES categories (reference pass-1 results
                  and external series; no cross-references between percentage categories).
    """
    issues = validate_opex_model_input(model, context, horizon_years=horizon_years)
    if has_errors(issues):
        raise OpexInputValidationError(issues)
    return _compute_annual_unchecked(model, context, horizon_years)


def compute_periods(
    model: OpexModelInput,
    context: OpexCalculationContext,
    periods: Iterable,
) -> tuple[OpexPeriodResult, ...]:
    """Validate then compute period-level OPEX.

    Raises OpexInputValidationError if validation finds any ERROR-severity issue.

    The required horizon is derived from the maximum year_index among operation
    periods.  If no operation periods are supplied, no validation is performed
    and an empty tuple is returned.

    `periods` must be an iterable of objects exposing:
        .index (int)          — unique period identifier
        .year_index (int)     — 1-based operating year
        .period_in_year (int) — 1 or 2
        .day_fraction (float) — portion of year covered by this period
        .is_operation (bool)  — only operation periods generate OPEX

    For SUBITEM_SUM categories:
        period_keur = SUMPRODUCT(period_active_budgets) × escalation × day_fraction

    For PERCENTAGE_OF_SELECTED_BASES categories:
        period_keur = rate × SUM(base category period_keur values)
        External series values are also scaled by day_fraction.

    H1/H2 overrides on individual subitems propagate naturally into
    contingency (percentage) categories — no special-casing needed.
    """
    periods_list = list(periods)
    op_periods = [p for p in periods_list if p.is_operation]
    if not op_periods:
        return ()

    horizon_years = max(p.year_index for p in op_periods)
    issues = validate_opex_model_input(model, context, horizon_years=horizon_years)
    if has_errors(issues):
        raise OpexInputValidationError(issues)
    return _compute_periods_unchecked(model, context, iter(periods_list))
