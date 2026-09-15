"""Central input validation for generic project and portfolio inputs.

Scope:
- Input-level validation (reject / warn on invalid schema values)
- Model-output warnings (flag unrealistic results after computation)

For DSCR reconciliation (target vs actual), see WaterfallResult fields:
  target_dscr, actual_min_dscr, actual_avg_dscr
"""
from __future__ import annotations
from dataclasses import dataclass, field
from typing import Optional


@dataclass(frozen=True)
class ValidationIssue:
    severity: str  # "error" | "warning"
    field: str
    message: str
    code: str = ""  # machine-readable code, e.g. "E_INVALID_ENUM"


# ── Valid enum string sets ─────────────────────────────────────────────────────
_VALID_AMORTIZATION_TYPES = frozenset({"sculpted", "annuity", "straight_line", "bullet"})
_VALID_EQUITY_IRR_METHODS = frozenset({"equity_only", "combined", "shl_plus_dividends"})
_VALID_DEBT_SIZING_METHODS = frozenset({"dscr_sculpt", "gearing_cap", "fixed"})
_VALID_SHL_REPAYMENT_METHODS = frozenset({
    "bullet", "cash_sweep", "pik", "accrued",
    "pik_then_sweep", "partial_pay_sweep", "fcf_waterfall",
})
_VALID_YIELD_SCENARIOS = frozenset({"P_50", "P90-10y", "P99-1y"})
_VALID_PERIOD_FREQUENCIES = frozenset({"Semestrial", "Annual", "Quarterly"})


@dataclass(frozen=True)
class ModelWarning:
    """Post-run warning — flags unrealistic model outputs."""
    code: str          # short machine-readable code, e.g. "W_DSCR_BELOW_TARGET"
    severity: str     # "warning" | "error"
    message: str       # human-readable explanation


# Registry of known model-warning codes
MODEL_WARNING_CODES = frozenset({
    "W_DSCR_BELOW_TARGET",
    "W_IRR_UNREALISTIC_HIGH",
    "W_IRR_UNREALISTIC_LOW",
    "W_ZERO_GENERATION",
    "W_NEGATIVE_CAPEX",
    "W_INVALID_TENOR",
    "W_COD_BEFORE_FINANCIAL_CLOSE",
    "W_NEGATIVE_TARIFF",
    "W_NEGATIVE_PRODUCTION",
})


def validate_project_inputs(inputs) -> tuple[ValidationIssue, ...]:
    """Validate project input schema values."""
    issues = []
    fin = inputs.financing
    tax = inputs.tax
    capex = inputs.capex
    info = inputs.info
    rev = inputs.revenue

    # ── Errors ────────────────────────────────────────────────────────────────
    if hasattr(inputs.technical, 'capacity_mw') and inputs.technical.capacity_mw <= 0:
        issues.append(ValidationIssue("error", "capacity_mw", "Capacity must be positive"))
    if info.horizon_years <= 0:
        issues.append(ValidationIssue("error", "horizon_years", "Horizon years must be positive"))
    if info.construction_months < 0:
        issues.append(ValidationIssue("error", "construction_months", "Construction months cannot be negative"))
    if tax.corporate_rate < 0 or tax.corporate_rate > 1:
        issues.append(ValidationIssue("error", "corporate_rate", "Tax rate must be between 0 and 1"))
    if fin.target_dscr <= 1.0:
        issues.append(ValidationIssue("error", "target_dscr", "Target DSCR must exceed 1.0"))
    if fin.lockup_dscr <= 1.0:
        issues.append(ValidationIssue("error", "lockup_dscr", "Lockup DSCR must exceed 1.0"))
    if fin.senior_tenor_years <= 0:
        issues.append(ValidationIssue("error", "senior_tenor_years", "Senior tenor must be positive"))
    if fin.senior_tenor_years > info.horizon_years:
        issues.append(ValidationIssue("error", "senior_tenor_years", "Senior tenor cannot exceed horizon"))
    if capex.total_capex < 0:
        issues.append(ValidationIssue("error", "capex.total_capex", "CapEx cannot be negative"))
    if capex.total_capex == 0:
        issues.append(ValidationIssue("error", "capex.total_capex", "Total CapEx must be positive"))

    # COD before financial close
    if hasattr(info, 'cod_date') and hasattr(info, 'financial_close'):
        if info.cod_date is not None and info.financial_close is not None:
            if info.cod_date < info.financial_close:
                issues.append(ValidationIssue(
                    "error", "cod_date",
                    f"COD ({info.cod_date}) cannot be before financial close ({info.financial_close})"
                ))

    # Negative tariff
    if rev.ppa_base_tariff < 0:
        issues.append(ValidationIssue("error", "ppa_base_tariff", "Tariff cannot be negative"))
    if hasattr(inputs.technical, 'capacity_mw') and inputs.technical.capacity_mw < 0:
        issues.append(ValidationIssue("error", "capacity_mw", "Capacity cannot be negative"))

    # BESS validation
    if hasattr(inputs, 'bess') and inputs.bess is not None:
        bess = inputs.bess
        bess_eff = getattr(bess, 'roundtrip_efficiency', None) or getattr(bess, 'round_trip_efficiency', None)
        if bess_eff is None or bess_eff <= 0 or bess_eff > 1:
            issues.append(ValidationIssue("error", "bess.roundtrip_efficiency", "BESS efficiency must be between 0 and 1"))
        if getattr(bess, 'cycles_per_year', 0) < 0:
            issues.append(ValidationIssue("error", "bess.cycles_per_year", "BESS cycles per year cannot be negative"))

    # ── Cross-field consistency ────────────────────────────────────────────────
    if fin.lockup_dscr >= fin.target_dscr:
        issues.append(ValidationIssue(
            "warning", "lockup_dscr",
            f"Lockup DSCR ({fin.lockup_dscr}) should be less than target DSCR ({fin.target_dscr}) "
            "— distributions will always be locked if lockup_dscr >= target_dscr",
            code="W_LOCKUP_GTE_TARGET",
        ))

    # ── Enum membership ───────────────────────────────────────────────────────
    if getattr(fin, "amortization_type", None) not in _VALID_AMORTIZATION_TYPES:
        issues.append(ValidationIssue(
            "error", "amortization_type",
            f"Invalid amortization_type '{fin.amortization_type}'; "
            f"must be one of {sorted(_VALID_AMORTIZATION_TYPES)}",
            code="E_INVALID_ENUM",
        ))
    if getattr(fin, "equity_irr_method", None) not in _VALID_EQUITY_IRR_METHODS:
        issues.append(ValidationIssue(
            "error", "equity_irr_method",
            f"Invalid equity_irr_method '{fin.equity_irr_method}'; "
            f"must be one of {sorted(_VALID_EQUITY_IRR_METHODS)}",
            code="E_INVALID_ENUM",
        ))
    if getattr(fin, "debt_sizing_method", None) not in _VALID_DEBT_SIZING_METHODS:
        issues.append(ValidationIssue(
            "error", "debt_sizing_method",
            f"Invalid debt_sizing_method '{fin.debt_sizing_method}'; "
            f"must be one of {sorted(_VALID_DEBT_SIZING_METHODS)}",
            code="E_INVALID_ENUM",
        ))
    if getattr(fin, "shl_repayment_method", None) not in _VALID_SHL_REPAYMENT_METHODS:
        issues.append(ValidationIssue(
            "error", "shl_repayment_method",
            f"Invalid shl_repayment_method '{fin.shl_repayment_method}'; "
            f"must be one of {sorted(_VALID_SHL_REPAYMENT_METHODS)}",
            code="E_INVALID_ENUM",
        ))
    tech = inputs.technical
    if getattr(tech, "yield_scenario", None) not in _VALID_YIELD_SCENARIOS:
        issues.append(ValidationIssue(
            "error", "yield_scenario",
            f"Invalid yield_scenario '{tech.yield_scenario}'; "
            f"must be one of {sorted(_VALID_YIELD_SCENARIOS)}",
            code="E_INVALID_ENUM",
        ))
    # ── TechnicalParams range checks ──────────────────────────────────────────
    if hasattr(tech, "pv_degradation") and not (0.0 <= tech.pv_degradation <= 1.0):
        issues.append(ValidationIssue(
            "error", "pv_degradation",
            f"pv_degradation ({tech.pv_degradation}) must be between 0 and 1",
            code="E_OUT_OF_RANGE",
        ))
    if hasattr(tech, "bess_degradation") and not (0.0 <= tech.bess_degradation <= 1.0):
        issues.append(ValidationIssue(
            "error", "bess_degradation",
            f"bess_degradation ({tech.bess_degradation}) must be between 0 and 1",
            code="E_OUT_OF_RANGE",
        ))
    if hasattr(tech, "plant_availability") and not (0.0 < tech.plant_availability <= 1.0):
        issues.append(ValidationIssue(
            "error", "plant_availability",
            f"plant_availability ({tech.plant_availability}) must be between 0 (exclusive) and 1",
            code="E_OUT_OF_RANGE",
        ))
    if hasattr(tech, "grid_availability") and not (0.0 < tech.grid_availability <= 1.0):
        issues.append(ValidationIssue(
            "error", "grid_availability",
            f"grid_availability ({tech.grid_availability}) must be between 0 (exclusive) and 1",
            code="E_OUT_OF_RANGE",
        ))

    # ── OpexItem validation ───────────────────────────────────────────────────
    for i, item in enumerate(getattr(inputs, "opex", ())):
        if hasattr(item, "y1_amount_keur") and item.y1_amount_keur < 0:
            issues.append(ValidationIssue(
                "warning", f"opex[{i}].y1_amount_keur",
                f"OPEX item '{getattr(item, 'name', i)}' has negative y1 amount ({item.y1_amount_keur:.2f} kEUR)",
                code="W_NEGATIVE_OPEX",
            ))
        if hasattr(item, "annual_inflation") and item.annual_inflation < -1.0:
            issues.append(ValidationIssue(
                "warning", f"opex[{i}].annual_inflation",
                f"OPEX item '{getattr(item, 'name', i)}' has extreme negative inflation ({item.annual_inflation:.2%})",
                code="W_OPEX_INFLATION",
            ))

    # ── Warnings ─────────────────────────────────────────────────────────────
    if rev.ppa_term_years > info.horizon_years:
        issues.append(ValidationIssue("warning", "ppa_term_years", "PPA term exceeds horizon — may extend beyond project life"))
    if fin.gearing_ratio < 0 or fin.gearing_ratio > 1:
        issues.append(ValidationIssue("warning", "gearing_ratio", "Gearing ratio should be between 0 and 1"))
    if fin.shl_rate < 0:
        issues.append(ValidationIssue("warning", "shl_rate", "SHL rate cannot be negative"))
    if hasattr(inputs.technical, 'degradation') and inputs.technical.degradation < 0:
        issues.append(ValidationIssue("warning", "degradation", "Degradation cannot be negative"))
    if rev.ppa_base_tariff <= 0:
        issues.append(ValidationIssue("warning", "ppa_base_tariff", "Tariff should be positive"))

    return tuple(issues)


def validate_portfolio_inputs(inputs) -> tuple[ValidationIssue, ...]:
    issues = []

    if len(inputs.projects) < 2:
        issues.append(ValidationIssue("error", "projects", "Portfolio requires at least 2 projects"))

    codes = [p.info.code for p in inputs.projects]
    if len(codes) != len(set(codes)):
        issues.append(ValidationIssue("error", "projects", "Portfolio contains duplicate project codes"))

    if inputs.shared_financing is None:
        issues.append(ValidationIssue("error", "shared_financing", "Portfolio requires shared_financing"))

    return tuple(issues)


def warn_model_unrealistic(result, inputs=None) -> tuple[ModelWarning, ...]:
    """Check waterfall result for unrealistic values and return warnings.

    Args:
        result: WaterfallResult
        inputs: optional ProjectInputs for additional context

    Returns:
        tuple of ModelWarning (empty if all checks pass)
    """
    warnings = []

    # DSCR below target
    if result.target_dscr > 0 and result.actual_min_dscr < result.target_dscr:
        warnings.append(ModelWarning(
            code="W_DSCR_BELOW_TARGET",
            severity="warning",
            message=(
                f"Actual min DSCR ({result.actual_min_dscr:.2f}x) is below target "
                f"({result.target_dscr:.2f}x) — debt may be oversized or generation too low."
            )
        ))

    # IRR unrealistic — high (>50%)
    if result.project_irr > 0.50:
        warnings.append(ModelWarning(
            code="W_IRR_UNREALISTIC_HIGH",
            severity="warning",
            message=(
                f"Project IRR ({result.project_irr*100:.1f}%) exceeds 50% — "
                "verify inputs (tariff, capex, generation) are realistic."
            )
        ))

    # IRR unrealistic — low / negative
    if result.project_irr < 0.0:
        warnings.append(ModelWarning(
            code="W_IRR_UNREALISTIC_LOW",
            severity="warning",
            message=(
                f"Project IRR ({result.project_irr*100:.1f}%) is negative — "
                "check tariff, capex, and financing assumptions."
            )
        ))

    # Zero or near-zero generation
    total_gen = sum(p.generation_mwh for p in result.periods if p.is_operation)
    if total_gen < 1.0:
        warnings.append(ModelWarning(
            code="W_ZERO_GENERATION",
            severity="error",
            message="Total generation is zero or near-zero — check technical parameters."
        ))

    # Negative CapEx
    if inputs is not None and hasattr(inputs.capex, 'total_capex') and inputs.capex.total_capex < 0:
        warnings.append(ModelWarning(
            code="W_NEGATIVE_CAPEX",
            severity="error",
            message=f"CapEx is negative ({inputs.capex.total_capex:.0f} kEUR) — check capex inputs."
        ))

    # COD before financial close
    if inputs is not None:
        info = inputs.info
        if (hasattr(info, 'cod_date') and info.cod_date is not None
                and hasattr(info, 'financial_close') and info.financial_close is not None
                and info.cod_date < info.financial_close):
            warnings.append(ModelWarning(
                code="W_COD_BEFORE_FINANCIAL_CLOSE",
                severity="error",
                message=(
                    f"COD ({info.cod_date}) is before financial close "
                    f"({info.financial_close}) — construction must complete before financial close."
                )
            ))

    # Revenue zero/negative with positive generation
    total_rev = result.total_revenue_keur
    if total_rev <= 0 and total_gen > 0:
        warnings.append(ModelWarning(
            code="W_NEGATIVE_TARIFF",
            severity="error",
            message="Revenue is zero/negative with positive generation — check tariff input."
        ))

    return tuple(warnings)


def dscr_reconciliation_fields(result) -> dict:
    """Return DSCR reconciliation summary as a dict.

    Use in Excel Notes or result reporting.
    """
    target = result.target_dscr
    actual_min = result.actual_min_dscr
    actual_avg = result.actual_avg_dscr
    if target > 0:
        status = "ok" if actual_min >= target else "below_target"
    else:
        status = "n/a"
    return {
        "target_dscr": target,
        "actual_min_dscr": actual_min,
        "actual_avg_dscr": actual_avg,
        "status": status,
    }