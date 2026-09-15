"""Strict validation for generic hierarchical OPEX inputs.

Validation returns a tuple of issues and never raises.  Callers use
has_errors() to gate calculation.  Every structural error has a machine
code (OPXnnn) for stable programmatic matching.

Error-code registry
-------------------
OPX001  duplicate category code
OPX010  duplicate subitem code
OPX011  unsupported amount_basis
OPX012  (WARNING) negative base_amount_keur
OPX020  SENIOR_DEBT_TENOR_ACTIVE with zero/negative tenor
OPX030  PERCENTAGE category has subitems
OPX031  PERCENTAGE category has no base codes
OPX032  (WARNING) percentage_rate ≤ 0
OPX033  self-referencing base code
OPX034  duplicate base code within percentage_base_codes
OPX040  inflation_rate below −1.0
OPX050  MANUAL activation without activation_schedule
OPX051  activation_schedule shorter than horizon
OPX052  period override year outside horizon
OPX053  period override half not in {1, 2}
OPX054  duplicate (year, half) key in period_overrides
OPX060  base code not found in categories or external_annual_series
OPX061  chained PERCENTAGE dependency (circular risk)
OPX070  duplicate code in external_annual_series
OPX071  external series code collides with a category code
OPX072  external series referenced by a percentage category is shorter than horizon
"""
from __future__ import annotations

from dataclasses import dataclass
from enum import Enum
from typing import Iterable

from ._inputs import (
    OpexActivationSchedule,
    OpexCalculationContext,
    OpexCategoryInput,
    OpexModelInput,
    OpexSubitemInput,
)
from ._types import (
    OpexActivationMode,
    OpexAmountBasis,
    OpexCategoryCalculationType,
)

_SUPPORTED_AMOUNT_BASES: frozenset[OpexAmountBasis] = frozenset(
    {OpexAmountBasis.ANNUAL_RUN_RATE}
)


class ValidationSeverity(str, Enum):
    ERROR = "ERROR"
    WARNING = "WARNING"


@dataclass(frozen=True)
class OpexValidationIssue:
    code: str
    path: str
    severity: ValidationSeverity
    message: str


def _err(code: str, path: str, message: str) -> OpexValidationIssue:
    return OpexValidationIssue(
        code=code, path=path, severity=ValidationSeverity.ERROR, message=message
    )


def _warn(code: str, path: str, message: str) -> OpexValidationIssue:
    return OpexValidationIssue(
        code=code, path=path, severity=ValidationSeverity.WARNING, message=message
    )


def has_errors(issues: Iterable[OpexValidationIssue]) -> bool:
    """Return True if any issue has severity ERROR."""
    return any(i.severity == ValidationSeverity.ERROR for i in issues)


def validate_opex_model_input(
    model: OpexModelInput,
    context: OpexCalculationContext,
    *,
    horizon_years: int,
) -> tuple[OpexValidationIssue, ...]:
    """Validate OpexModelInput + context for the given horizon.

    Returns a tuple of issues (possibly empty).  Issues with severity ERROR
    must block calculation.  Issues with severity WARNING are informational.
    """
    issues: list[OpexValidationIssue] = []

    # --- duplicate category codes --------------------------------------------
    seen_cat_codes: set[str] = set()
    for cat in model.categories:
        if cat.code in seen_cat_codes:
            issues.append(
                _err("OPX001", f"categories[{cat.code}]",
                     f"Duplicate category code: {cat.code!r}")
            )
        seen_cat_codes.add(cat.code)

    all_cat_codes: set[str] = set(seen_cat_codes)

    # --- external_annual_series validation -----------------------------------
    ext_codes: set[str] = set()
    _validate_external_series(context, all_cat_codes, issues, ext_codes)

    # --- per-category validation ---------------------------------------------
    needs_tenor = False
    percentage_cats: list[tuple[str, OpexCategoryInput]] = []

    for cat in model.categories:
        p = f"categories[{cat.code}]"
        _validate_category(
            cat, p, horizon_years, issues, percentage_cats, needs_tenor_ref=[]
        )
        for si in cat.subitems:
            if si.activation_mode == OpexActivationMode.SENIOR_DEBT_TENOR_ACTIVE:
                needs_tenor = True

    # --- SENIOR_DEBT_TENOR_ACTIVE requires a positive tenor ------------------
    if needs_tenor and context.senior_debt_tenor_years <= 0:
        issues.append(
            _err(
                "OPX020",
                "context.senior_debt_tenor_years",
                "One or more subitems use SENIOR_DEBT_TENOR_ACTIVE but "
                "context.senior_debt_tenor_years is 0 or negative",
            )
        )

    # --- percentage category dependency graph --------------------------------
    _validate_percentage_deps(
        percentage_cats, all_cat_codes, ext_codes, issues, context, horizon_years
    )

    return tuple(issues)


def _validate_external_series(
    context: OpexCalculationContext,
    all_cat_codes: set[str],
    issues: list[OpexValidationIssue],
    ext_codes_out: set[str],
) -> None:
    """Validate external_annual_series: no duplicates, no cat-code collision."""
    seen: set[str] = set()
    for code, _ in context.external_annual_series:
        p = f"context.external_annual_series[{code!r}]"
        if code in seen:
            issues.append(
                _err("OPX070", p,
                     f"Duplicate code {code!r} in external_annual_series; "
                     "last-write-wins semantics are not permitted")
            )
        else:
            seen.add(code)
            ext_codes_out.add(code)

        if code in all_cat_codes:
            issues.append(
                _err("OPX071", p,
                     f"External series code {code!r} collides with a category code; "
                     "base-code resolution would be ambiguous")
            )


def _validate_category(
    cat: OpexCategoryInput,
    p: str,
    horizon_years: int,
    issues: list[OpexValidationIssue],
    percentage_cats: list[tuple[str, OpexCategoryInput]],
    needs_tenor_ref: list,  # unused; kept for clarity
) -> None:
    if cat.calculation_type == OpexCategoryCalculationType.PERCENTAGE_OF_SELECTED_BASES:
        if cat.subitems:
            issues.append(
                _err("OPX030", f"{p}.subitems",
                     "PERCENTAGE_OF_SELECTED_BASES categories must have no subitems")
            )
        if not cat.percentage_base_codes:
            issues.append(
                _err("OPX031", f"{p}.percentage_base_codes",
                     "PERCENTAGE_OF_SELECTED_BASES requires at least one base code")
            )
        if cat.percentage_rate <= 0:
            issues.append(
                _warn("OPX032", f"{p}.percentage_rate",
                      f"percentage_rate is {cat.percentage_rate} (≤ 0); "
                      "derived category will always be zero or negative")
            )
        if cat.code in cat.percentage_base_codes:
            issues.append(
                _err("OPX033", f"{p}.percentage_base_codes",
                     f"Self-reference: category {cat.code!r} cannot be in its own base")
            )
        # --- duplicate base codes within percentage_base_codes ---------------
        seen_base: set[str] = set()
        for base_code in cat.percentage_base_codes:
            if base_code in seen_base:
                issues.append(
                    _err("OPX034", f"{p}.percentage_base_codes",
                         f"Duplicate base code {base_code!r} in percentage_base_codes; "
                         "would silently double-count the base category")
                )
            seen_base.add(base_code)
        percentage_cats.append((cat.code, cat))
        return

    # SUBITEM_SUM ------------------------------------------------------------
    if cat.inflation_rate < -1.0:
        issues.append(
            _err("OPX040", f"{p}.inflation_rate",
                 f"inflation_rate {cat.inflation_rate} is below economic bound −1.0")
        )

    seen_si: set[str] = set()
    for si in cat.subitems:
        si_p = f"{p}.subitems[{si.code}]"

        if si.code in seen_si:
            issues.append(
                _err("OPX010", si_p, f"Duplicate subitem code: {si.code!r} in {cat.code!r}")
            )
        seen_si.add(si.code)

        if si.amount_basis not in _SUPPORTED_AMOUNT_BASES:
            issues.append(
                _err("OPX011", f"{si_p}.amount_basis",
                     f"Unsupported amount_basis {si.amount_basis!r}; "
                     "no calculation support exists yet for this basis type")
            )

        if si.base_amount_keur < 0:
            issues.append(
                _warn("OPX012", f"{si_p}.base_amount_keur",
                      f"Negative base_amount_keur ({si.base_amount_keur:.4f} kEUR); "
                      "verify this is intentional")
            )

        if si.activation_mode == OpexActivationMode.MANUAL:
            _validate_manual_schedule(si, si_p, horizon_years, issues)


def _validate_manual_schedule(
    si: OpexSubitemInput,
    si_p: str,
    horizon_years: int,
    issues: list[OpexValidationIssue],
) -> None:
    if si.activation_schedule is None:
        issues.append(
            _err("OPX050", f"{si_p}.activation_schedule",
                 "MANUAL activation requires an activation_schedule")
        )
        return

    sched = si.activation_schedule
    if len(sched.annual_flags) < horizon_years:
        issues.append(
            _err("OPX051", f"{si_p}.activation_schedule.annual_flags",
                 f"Schedule has {len(sched.annual_flags)} annual flags "
                 f"but horizon is {horizon_years} years")
        )

    seen_keys: set[tuple[int, int]] = set()
    for (year, half), _ in sched.period_overrides:
        if year < 1 or year > horizon_years:
            issues.append(
                _err("OPX052", f"{si_p}.activation_schedule.period_overrides",
                     f"Period override year {year} is outside horizon [1, {horizon_years}]")
            )
        if half not in (1, 2):
            issues.append(
                _err("OPX053", f"{si_p}.activation_schedule.period_overrides",
                     f"Period override half must be 1 or 2, got {half}")
            )
        key = (year, half)
        if key in seen_keys:
            issues.append(
                _err("OPX054", f"{si_p}.activation_schedule.period_overrides",
                     f"Duplicate period override key {key!r}; "
                     "financial result must not depend on tuple ordering")
            )
        seen_keys.add(key)


def _validate_percentage_deps(
    percentage_cats: list[tuple[str, OpexCategoryInput]],
    all_cat_codes: set[str],
    ext_codes: set[str],
    issues: list[OpexValidationIssue],
    context: OpexCalculationContext,
    horizon_years: int,
) -> None:
    """Validate percentage base codes, circular/missing deps, and series length."""
    pct_codes: set[str] = {code for code, _ in percentage_cats}

    ext_lengths: dict[str, int] = {}
    for code, vals in context.external_annual_series:
        ext_lengths[code] = len(vals)

    for code, cat in percentage_cats:
        p = f"categories[{code}].percentage_base_codes"
        for base_code in cat.percentage_base_codes:
            if base_code not in all_cat_codes and base_code not in ext_codes:
                issues.append(
                    _err("OPX060", p,
                         f"Base code {base_code!r} not found in categories "
                         "or external_annual_series")
                )
            # Chained derived-category dependency → circular risk
            if base_code in pct_codes and base_code != code:
                issues.append(
                    _err("OPX061", p,
                         f"Derived-category dependency: {code!r} → {base_code!r}. "
                         "Chaining PERCENTAGE_OF_SELECTED_BASES categories is not "
                         "supported; refactor base codes to reference SUBITEM_SUM "
                         "categories only")
                )
            # External series too short for horizon
            if base_code in ext_lengths and ext_lengths[base_code] < horizon_years:
                issues.append(
                    _err("OPX072", p,
                         f"External series {base_code!r} has {ext_lengths[base_code]} "
                         f"values but horizon is {horizon_years} years; "
                         "missing years must not silently resolve to zero")
                )
