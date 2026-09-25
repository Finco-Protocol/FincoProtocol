"""
financial_engine.validation — Deterministic input validation for Phase 2A.

validate_operating_model_input() returns a tuple of ValidationIssue objects.
It does NOT mutate inputs, raise exceptions for expected invalid inputs,
auto-correct values, or silently clamp values.

run_operating_model() refuses to execute when ERROR issues exist.
"""
from __future__ import annotations

import math
from dataclasses import dataclass
from enum import Enum
from typing import TYPE_CHECKING, Any

if TYPE_CHECKING:
    from financial_engine.inputs import OperatingModelInput


class ValidationSeverity(str, Enum):
    ERROR = "ERROR"
    WARNING = "WARNING"


@dataclass(frozen=True)
class ValidationIssue:
    code: str
    path: str
    severity: ValidationSeverity
    message: str


def _is_finite(v: float | None) -> bool:
    return v is not None and math.isfinite(v)


def _err(code: str, path: str, msg: str) -> ValidationIssue:
    return ValidationIssue(code=code, path=path, severity=ValidationSeverity.ERROR, message=msg)


def _warn(code: str, path: str, msg: str) -> ValidationIssue:
    return ValidationIssue(code=code, path=path, severity=ValidationSeverity.WARNING, message=msg)


def validate_operating_model_input(
    inputs: "OperatingModelInput",
) -> tuple[ValidationIssue, ...]:
    """Validate a Phase 2A OperatingModelInput.

    Returns a deterministically ordered tuple of ValidationIssue objects.
    """
    issues: list[ValidationIssue] = []

    cal = inputs.calendar
    tech = inputs.technical
    rev = inputs.revenue
    opex = inputs.opex
    dep = inputs.depreciation

    # Calendar
    if cal.financial_close is None:
        issues.append(_err("CAL001", "calendar.financial_close", "financial_close is required"))

    if cal.construction_months < 0:
        issues.append(_err("CAL002", "calendar.construction_months",
                           f"construction_months must be non-negative, got {cal.construction_months}"))

    if cal.horizon_years <= 0:
        issues.append(_err("CAL003", "calendar.horizon_years",
                           f"horizon_years must be positive, got {cal.horizon_years}"))

    if cal.ppa_years < 0:
        issues.append(_err("CAL004", "calendar.ppa_years",
                           f"ppa_years must be non-negative, got {cal.ppa_years}"))

    if cal.ppa_years > cal.horizon_years:
        issues.append(_warn("CAL005", "calendar.ppa_years",
                            f"ppa_years ({cal.ppa_years}) exceeds horizon_years ({cal.horizon_years})"))

    # Technical
    if not _is_finite(tech.capacity_mw) or tech.capacity_mw < 0:
        issues.append(_err("TECH001", "technical.capacity_mw",
                           f"capacity_mw must be finite and non-negative, got {tech.capacity_mw}"))

    if not _is_finite(tech.operating_hours_p50) or tech.operating_hours_p50 < 0:
        issues.append(_err("TECH002", "technical.operating_hours_p50",
                           f"operating_hours_p50 must be finite and non-negative"))

    if not _is_finite(tech.operating_hours_p90_10y) or tech.operating_hours_p90_10y < 0:
        issues.append(_err("TECH003", "technical.operating_hours_p90_10y",
                           f"operating_hours_p90_10y must be finite and non-negative"))

    if tech.yield_scenario.value in ("P90-10y",) and tech.operating_hours_p90_10y <= 0:
        issues.append(_err("TECH004", "technical.operating_hours_p90_10y",
                           "P90-10y scenario requires operating_hours_p90_10y > 0"))

    if not _is_finite(tech.pv_degradation):
        issues.append(_err("TECH005", "technical.pv_degradation",
                           "pv_degradation must be finite"))

    if not _is_finite(tech.plant_availability) or not (0.0 <= tech.plant_availability <= 1.0):
        issues.append(_err("TECH006", "technical.plant_availability",
                           f"plant_availability must be finite and in [0, 1], got {tech.plant_availability}"))

    if not _is_finite(tech.grid_availability) or not (0.0 <= tech.grid_availability <= 1.0):
        issues.append(_err("TECH007", "technical.grid_availability",
                           f"grid_availability must be finite and in [0, 1], got {tech.grid_availability}"))

    # Revenue
    if not _is_finite(rev.ppa_base_tariff_eur_mwh):
        issues.append(_err("REV001", "revenue.ppa_base_tariff_eur_mwh",
                           "ppa_base_tariff_eur_mwh must be finite"))

    if not _is_finite(rev.ppa_index):
        issues.append(_err("REV002", "revenue.ppa_index", "ppa_index must be finite"))

    if not (0.0 <= rev.ppa_production_share <= 1.0):
        issues.append(_err("REV003", "revenue.ppa_production_share",
                           f"ppa_production_share must be in [0, 1], got {rev.ppa_production_share}"))

    for i, p in enumerate(rev.market_prices_curve_eur_mwh):
        if not _is_finite(p):
            issues.append(_err("REV004", f"revenue.market_prices_curve_eur_mwh[{i}]",
                               f"market price at index {i} is not finite: {p}"))

    if rev.co2_enabled and not _is_finite(rev.co2_price_eur_mwh):
        issues.append(_err("REV005", "revenue.co2_price_eur_mwh",
                           "co2_price_eur_mwh must be finite when co2_enabled"))

    # OPEX
    for i, item in enumerate(opex.items):
        if not _is_finite(item.y1_amount_keur):
            issues.append(_err("OPEX001", f"opex.items[{i}].y1_amount_keur",
                               f"y1_amount_keur for item {item.name!r} is not finite"))
        if not _is_finite(item.annual_inflation):
            issues.append(_err("OPEX002", f"opex.items[{i}].annual_inflation",
                               f"annual_inflation for item {item.name!r} is not finite"))

    if opex.hierarchical_external_annual_series and opex.hierarchical_model is None:
        issues.append(_err("OPEX003", "opex.hierarchical_external_annual_series",
                           "hierarchical_external_annual_series supplied without hierarchical_model; "
                           "supply hierarchical_model or clear the external series"))

    if opex.hierarchical_model is not None:
        if opex.senior_debt_tenor_years is None:
            issues.append(_err("OPEX004", "opex.senior_debt_tenor_years",
                               "senior_debt_tenor_years is required when hierarchical_model is present; "
                               "map from financing.senior_tenor_years in the adapter"))
        elif opex.senior_debt_tenor_years <= 0:
            issues.append(_err("OPEX004", "opex.senior_debt_tenor_years",
                               f"senior_debt_tenor_years must be a positive integer, "
                               f"got {opex.senior_debt_tenor_years}"))

    # Depreciation
    if dep.financial_cost_useful_life_years <= 0:
        issues.append(_err("DEP004", "depreciation.financial_cost_useful_life_years",
                           f"financial_cost_useful_life_years must be positive, "
                           f"got {dep.financial_cost_useful_life_years}"))

    _RECOGNIZED_ASSET_CLASSES = frozenset({
        "solar_panels", "wind_turbines", "bess_cells", "bess_pe",
        "civil_grid", "soft_costs", "financial_costs",
    })

    for basis_label, basis_items in (
        ("book_capex_items_for_depreciation", dep.book_capex_items_for_depreciation),
        ("tax_capex_items_for_depreciation", dep.tax_capex_items_for_depreciation),
    ):
        for i, item in enumerate(basis_items):
            if not _is_finite(item.amount_keur):
                issues.append(_err("DEP001", f"depreciation.{basis_label}[{i}].amount_keur",
                                   f"amount_keur for item {item.name!r} must be finite, got {item.amount_keur}"))
            elif item.amount_keur < 0:
                issues.append(_err("DEP001", f"depreciation.{basis_label}[{i}].amount_keur",
                                   f"amount_keur for item {item.name!r} must be non-negative, got {item.amount_keur}"))

            if item.asset_class_code not in _RECOGNIZED_ASSET_CLASSES:
                issues.append(_err("DEP002", f"depreciation.{basis_label}[{i}].asset_class_code",
                                   f"asset_class_code {item.asset_class_code!r} is not recognized; "
                                   f"valid: {sorted(_RECOGNIZED_ASSET_CLASSES)}"))

            if item.useful_life_override is not None and item.useful_life_override <= 0:
                issues.append(_err("DEP003", f"depreciation.{basis_label}[{i}].useful_life_override",
                                   f"useful_life_override for item {item.name!r} must be positive "
                                   f"or None, got {item.useful_life_override}"))

    return tuple(issues)


def has_errors(issues: tuple[ValidationIssue, ...]) -> bool:
    """Return True if any issue has ERROR severity."""
    return any(i.severity == ValidationSeverity.ERROR for i in issues)


# ---------------------------------------------------------------------------
# Phase 2B Tax validation
# ---------------------------------------------------------------------------

def validate_tax_calculation_input(
    tax_input: "Any",  # TaxCalculationInput
    known_period_indices: "frozenset[int] | None" = None,
) -> tuple[ValidationIssue, ...]:
    """Validate TaxCalculationInput. Returns tuple of ValidationIssue.

    Error codes:
      TAX001  corporate_rate outside [0, 1]
      TAX002  periods_per_tax_year <= 0
      TAX003  loss_carryforward_years < 0
      TAX004  atad_ebitda_limit outside [0, 1]
      TAX005  atad_de_minimis_threshold_keur_annual < 0
      TAX006  cash_tax_payment_lag_periods < 0
      TAX007  opening vintage amount invalid (negative or nonfinite)
      TAX008  opening vintage origin_tax_year invalid (not an int)
      TAX009  period_interest component nonfinite or negative
      TAX010  period_interest has duplicate period_index
      TAX011  period_interest period_index not in known model periods
      TAX012  period_adjustments has duplicate period_index
      TAX013  fiscal reintegration value is nonfinite
      TAX014  policy is not a TaxPolicy instance
      TAX015  period_interest out-of-order (period_index not ascending)
      TAX016  period_adjustments period_index not in known model periods
      TAX017  period_adjustments out-of-order (period_index not ascending)
    """
    from financial_engine.policies.tax import TaxPolicy

    issues: list[ValidationIssue] = []

    policy = tax_input.policy
    if not isinstance(policy, TaxPolicy):
        issues.append(_err(
            "TAX014", "tax.policy",
            f"policy must be a TaxPolicy instance, got {type(policy).__name__}",
        ))
        return tuple(issues)  # can't validate further

    if not (0.0 <= policy.corporate_rate <= 1.0):
        issues.append(_err("TAX001", "tax.policy.corporate_rate",
                           f"corporate_rate must be in [0, 1], got {policy.corporate_rate}"))

    if policy.periods_per_tax_year <= 0:
        issues.append(_err("TAX002", "tax.policy.periods_per_tax_year",
                           f"periods_per_tax_year must be > 0, got {policy.periods_per_tax_year}"))

    if policy.loss_carryforward_years < 0:
        issues.append(_err("TAX003", "tax.policy.loss_carryforward_years",
                           f"loss_carryforward_years must be >= 0, got {policy.loss_carryforward_years}"))

    if policy.atad_enabled and not (0.0 <= policy.atad_ebitda_limit <= 1.0):
        issues.append(_err("TAX004", "tax.policy.atad_ebitda_limit",
                           f"atad_ebitda_limit must be in [0, 1], got {policy.atad_ebitda_limit}"))

    if policy.atad_de_minimis_threshold_keur_annual < 0:
        issues.append(_err("TAX005", "tax.policy.atad_de_minimis_threshold_keur_annual",
                           f"atad_de_minimis_threshold_keur_annual must be >= 0"))

    if policy.cash_tax_payment_lag_periods < 0:
        issues.append(_err("TAX006", "tax.policy.cash_tax_payment_lag_periods",
                           f"cash_tax_payment_lag_periods must be >= 0, got {policy.cash_tax_payment_lag_periods}"))

    for i, v in enumerate(tax_input.opening_loss_vintages):
        if not _is_finite(v.amount_keur) or v.amount_keur < 0:
            issues.append(_err("TAX007",
                               f"tax.opening_loss_vintages[{i}].amount_keur",
                               f"amount_keur must be finite and non-negative, got {v.amount_keur}"))
        if not isinstance(v.origin_tax_year, int):
            issues.append(_err("TAX008",
                               f"tax.opening_loss_vintages[{i}].origin_tax_year",
                               f"origin_tax_year must be an integer, got {type(v.origin_tax_year).__name__}"))

    seen_pi: set[int] = set()
    prev_pi_idx: int | None = None
    for i, pi in enumerate(tax_input.period_interest):
        if pi.period_index in seen_pi:
            issues.append(_err("TAX010",
                               f"tax.period_interest[{i}].period_index",
                               f"duplicate period_index {pi.period_index}"))
        seen_pi.add(pi.period_index)

        if prev_pi_idx is not None and pi.period_index <= prev_pi_idx:
            issues.append(_err("TAX015",
                               f"tax.period_interest[{i}].period_index",
                               f"period_index {pi.period_index} is not ascending "
                               f"(previous was {prev_pi_idx})"))
        prev_pi_idx = pi.period_index

        for component, label in [
            (pi.senior_interest_keur, "senior_interest_keur"),
            (pi.shl_interest_keur, "shl_interest_keur"),
            (pi.other_interest_keur, "other_interest_keur"),
        ]:
            if not _is_finite(component) or component < 0:
                issues.append(_err("TAX009",
                                   f"tax.period_interest[{i}].{label}",
                                   f"{label} must be finite and non-negative, got {component}"))

        if known_period_indices is not None and pi.period_index not in known_period_indices:
            issues.append(_err("TAX011",
                               f"tax.period_interest[{i}].period_index",
                               f"period_index {pi.period_index} is not a known model period"))

    seen_adj: set[int] = set()
    prev_adj_idx: int | None = None
    for i, adj in enumerate(tax_input.period_adjustments):
        if adj.period_index in seen_adj:
            issues.append(_err("TAX012",
                               f"tax.period_adjustments[{i}].period_index",
                               f"duplicate period_index {adj.period_index}"))
        seen_adj.add(adj.period_index)

        if prev_adj_idx is not None and adj.period_index <= prev_adj_idx:
            issues.append(_err("TAX017",
                               f"tax.period_adjustments[{i}].period_index",
                               f"period_index {adj.period_index} is not ascending "
                               f"(previous was {prev_adj_idx})"))
        prev_adj_idx = adj.period_index

        if known_period_indices is not None and adj.period_index not in known_period_indices:
            issues.append(_err("TAX016",
                               f"tax.period_adjustments[{i}].period_index",
                               f"period_index {adj.period_index} is not a known model period"))

        if not _is_finite(adj.other_fiscal_reintegration_keur):
            issues.append(_err("TAX013",
                               f"tax.period_adjustments[{i}].other_fiscal_reintegration_keur",
                               "must be finite"))

    return tuple(issues)
