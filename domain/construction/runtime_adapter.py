"""Runtime adapter for offline construction schedule diagnostics.

The adapter is intentionally diagnostic-only in this PR. It selects a supported
offline construction template and returns the computed construction schedule,
but it does not mutate project inputs and does not import the waterfall domain.
"""

from __future__ import annotations

from dataclasses import dataclass

from domain.construction.engine import compute_construction_schedule
from domain.construction.result import ConstructionMonthlyEntry, ConstructionScheduleResult
from domain.construction.templates.generic_solar_reference import build_generic_solar_reference_construction_config
from domain.construction.templates.generic_wind_reference import build_generic_wind_reference_construction_config


SUPPORTED_PROJECT_CODES = {"REF-WIND-B", "REF-SOLAR-A"}


@dataclass(frozen=True)
class SeniorDebtConstructionDiagnostic:
    """Audit-only senior opening debt reconciliation."""

    opening_balance_source: str
    manual_opening_senior_balance_keur: float
    computed_senior_principal_draw_keur: float
    computed_senior_idc_keur: float
    computed_opening_senior_excluding_idc_keur: float
    computed_opening_senior_including_idc_keur: float
    senior_idc_manual_value_keur: float
    opening_balance_delta_excluding_idc_keur: float
    opening_balance_delta_including_idc_keur: float
    idc_delta_keur: float
    repayment_timing_notes: tuple[str, ...]
    cod_transition_notes: tuple[str, ...]


@dataclass(frozen=True)
class ConstructionRuntimeResult:
    """Diagnostic construction runtime bridge result."""

    project_code: str
    construction_months: int
    total_uses_keur: float
    equity_draw_keur: float
    shl_principal_draw_keur: float
    junior_draw_keur: float
    senior_principal_draw_keur: float
    shl_idc_keur: float
    senior_idc_keur: float
    opening_shl_balance_keur: float
    opening_senior_balance_keur: float
    uses_funding_delta_keur: float
    senior_idc_delta_to_target_keur: float | None
    monthly_entries: tuple[ConstructionMonthlyEntry, ...]
    validation_notes: tuple[str, ...]
    senior_debt_diagnostic: SeniorDebtConstructionDiagnostic
    source_result: ConstructionScheduleResult


def build_runtime_construction_schedule(inputs) -> ConstructionRuntimeResult:
    """Build diagnostic construction outputs for a supported project."""

    project_code = getattr(getattr(inputs, "info", None), "code", "")
    if project_code == "REF-WIND-B":
        config = build_generic_wind_reference_construction_config()
    elif project_code == "REF-SOLAR-A":
        config = build_generic_solar_reference_construction_config()
    else:
        raise ValueError(
            "Construction schedule runtime engine is only supported for "
            f"REF-WIND-B and REF-SOLAR-A; got project code {project_code!r}."
        )

    result = compute_construction_schedule(config)
    notes = _build_validation_notes(inputs, result)
    senior_diagnostic = _build_senior_debt_diagnostic(inputs, result)
    return ConstructionRuntimeResult(
        project_code=project_code,
        construction_months=len(result.monthly_entries),
        total_uses_keur=result.total_uses_keur,
        equity_draw_keur=result.total_equity_draw_keur,
        shl_principal_draw_keur=result.total_shl_draw_keur,
        junior_draw_keur=result.total_junior_draw_keur,
        senior_principal_draw_keur=result.total_senior_draw_keur,
        shl_idc_keur=result.total_shl_idc_keur,
        senior_idc_keur=result.total_senior_idc_keur,
        opening_shl_balance_keur=result.opening_shl_balance_keur,
        opening_senior_balance_keur=result.opening_senior_balance_keur,
        uses_funding_delta_keur=result.uses_funding_delta_keur,
        senior_idc_delta_to_target_keur=result.senior_idc_delta_to_target_keur,
        monthly_entries=result.monthly_entries,
        validation_notes=tuple(notes),
        senior_debt_diagnostic=senior_diagnostic,
        source_result=result,
    )


def _build_validation_notes(inputs, result: ConstructionScheduleResult) -> list[str]:
    notes = [
        "diagnostic_only: construction outputs are not routed into waterfall cash flows",
        "manual_precedence: existing project inputs remain authoritative for runtime balances",
    ]
    financing = getattr(inputs, "financing", None)
    if financing is None:
        return notes

    manual_shl_principal = float(getattr(financing, "shl_amount_keur", 0.0) or 0.0)
    manual_shl_idc = float(getattr(financing, "shl_idc_keur", 0.0) or 0.0)
    manual_senior_debt = float(
        getattr(financing, "fixed_debt_keur", None)
        or getattr(financing, "senior_debt_amount_keur", 0.0)
        or 0.0
    )

    if abs(manual_shl_principal - result.total_shl_draw_keur) > 0.01:
        notes.append(
            "manual_mismatch: shl_amount_keur differs from computed SHL principal draw"
        )
    if abs(manual_shl_idc - result.total_shl_idc_keur) > 0.01:
        notes.append(
            "manual_mismatch: shl_idc_keur differs from computed SHL IDC; computed IDC remains diagnostic"
        )
    if abs(manual_senior_debt - result.total_senior_draw_keur) > 0.01:
        notes.append(
            "manual_mismatch: senior debt input differs from computed senior principal draw"
        )
    notes.append(
        "double_count_guard: computed IDC is not added on top of manual SHL or senior debt inputs"
    )
    return notes


def _build_senior_debt_diagnostic(
    inputs,
    result: ConstructionScheduleResult,
) -> SeniorDebtConstructionDiagnostic:
    financing = getattr(inputs, "financing", None)
    capex = getattr(inputs, "capex", None)
    manual_opening = 0.0
    if financing is not None:
        manual_opening = float(
            getattr(financing, "fixed_debt_keur", None)
            or getattr(financing, "senior_debt_amount_keur", 0.0)
            or 0.0
        )
    manual_idc = float(getattr(capex, "idc_keur", 0.0) or 0.0)
    computed_excluding_idc = result.total_senior_draw_keur
    computed_including_idc = result.total_senior_draw_keur + result.total_senior_idc_keur
    return SeniorDebtConstructionDiagnostic(
        opening_balance_source="manual_fixed_debt_keur_diagnostic_only",
        manual_opening_senior_balance_keur=manual_opening,
        computed_senior_principal_draw_keur=result.total_senior_draw_keur,
        computed_senior_idc_keur=result.total_senior_idc_keur,
        computed_opening_senior_excluding_idc_keur=computed_excluding_idc,
        computed_opening_senior_including_idc_keur=computed_including_idc,
        senior_idc_manual_value_keur=manual_idc,
        opening_balance_delta_excluding_idc_keur=manual_opening - computed_excluding_idc,
        opening_balance_delta_including_idc_keur=manual_opening - computed_including_idc,
        idc_delta_keur=manual_idc - result.total_senior_idc_keur,
        repayment_timing_notes=(
            "runtime senior repayment starts in first operating period",
            "fixed_debt_keur overrides sculpted opening debt when provided",
            "no construction IDC is added to fixed_debt_keur in this branch",
        ),
        cod_transition_notes=(
            "construction diagnostic COD balance is audit-only",
            "runtime COD opening balance remains the manual financing input",
            "computed senior IDC is not capitalized into runtime debt",
        ),
    )


__all__ = [
    "ConstructionRuntimeResult",
    "SeniorDebtConstructionDiagnostic",
    "build_runtime_construction_schedule",
]
