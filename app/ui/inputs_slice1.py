"""Canonical Inputs Slice 1 projection.

This module prepares a small, feature-flagged Inputs surface for project,
schedule, technical, and supported production assumptions. It is deliberately
read-only except for registry BOUND fields already writable through the
canonical WorkbookUpdateService pipeline.
"""
from __future__ import annotations

import os
from dataclasses import dataclass
from typing import Any

from app.workbook.input_set import ProjectInputSet
from app.workbook.registry import WORKBOOK
from app.workbook.specs import BindingStatus, FieldSpec, FieldType


SLICE1_FLAG = "FINCO_INPUTS_SLICE1_ENABLED"

EDITABLE_BOUND = "EDITABLE_BOUND"
READ_ONLY_DERIVED = "READ_ONLY_DERIVED"
READ_ONLY_TEMPLATE_LOCKED = "READ_ONLY_TEMPLATE_LOCKED"
READ_ONLY_REFERENCE_PROJECT = "READ_ONLY_REFERENCE_PROJECT"
UNAVAILABLE_UNRESOLVED = "UNAVAILABLE_UNRESOLVED"

KNOWN_SLICE1_EDITABLE = "KNOWN_SLICE1_EDITABLE"
KNOWN_SLICE1_READ_ONLY = "KNOWN_SLICE1_READ_ONLY"
KNOWN_REGISTRY_OUTSIDE_SLICE1 = "KNOWN_REGISTRY_OUTSIDE_SLICE1"
UNKNOWN_REGISTRY_FIELD = "UNKNOWN_REGISTRY_FIELD"


SLICE1_FIELD_IDS: tuple[str, ...] = (
    "project_setup.identity.project_type",
    "project_setup.identity.country_market",
    "project_setup.technical.cod_date",
    "project_setup.technical.construction_months",
    "project_setup.technical.horizon_years",
    "project_setup.technical.capacity_mw",
    "project_setup.technical.p50_hours",
)

SLICE1_EDITABLE_FIELD_IDS: frozenset[str] = frozenset({
    "project_setup.technical.cod_date",
    "project_setup.technical.construction_months",
    "project_setup.technical.horizon_years",
    "project_setup.technical.capacity_mw",
    "project_setup.technical.p50_hours",
})

SLICE1_SECTIONS: tuple[tuple[str, str, tuple[str, ...]], ...] = (
    (
        "project",
        "Project",
        (
            "project_setup.identity.project_type",
            "project_setup.identity.country_market",
        ),
    ),
    (
        "schedule",
        "Schedule",
        (
            "project_setup.technical.cod_date",
            "project_setup.technical.construction_months",
            "project_setup.technical.horizon_years",
        ),
    ),
    (
        "technical",
        "Technical",
        ("project_setup.technical.capacity_mw",),
    ),
    (
        "production",
        "Production",
        ("project_setup.technical.p50_hours",),
    ),
)

_STATUS_LABELS = {
    EDITABLE_BOUND: "Editable",
    READ_ONLY_DERIVED: "Derived",
    READ_ONLY_TEMPLATE_LOCKED: "Template locked",
    READ_ONLY_REFERENCE_PROJECT: "Reference read-only",
    UNAVAILABLE_UNRESOLVED: "Unavailable",
}

_STATUS_NOTES = {
    EDITABLE_BOUND: "Canonical input. Saves through ProjectInputSet and requires Run.",
    READ_ONLY_DERIVED: "Read-only derived display from backend state.",
    READ_ONLY_TEMPLATE_LOCKED: "Set by the template or project creation path.",
    READ_ONLY_REFERENCE_PROJECT: "Reference project is protected. Create a working copy to edit.",
    UNAVAILABLE_UNRESOLVED: "Visible as evidence only until binding is fully resolved.",
}

_FIELD_NOTES = {
    "project_setup.identity.country_market": (
        "Country is displayed but not editable in Slice 1 because the free-text "
        "country label to country_iso mapping is not fully registered."
    ),
    "project_setup.technical.p50_hours": (
        "Current product meaning: P50 operating hours (h/yr). Excel P50/yield "
        "semantics remain unresolved; no MWh conversion or parity claim is made."
    ),
}

DEFERRED_FIELD_REASONS = {
    "project_setup.identity.project_name": (
        "Project Name requires a dedicated project metadata rename contract."
    ),
    "project_setup.technical.capacity_factor": (
        "Capacity Factor requires an authoritative runtime-derived projection "
        "with explicit stale-state semantics."
    ),
}


@dataclass(frozen=True)
class Slice1Row:
    field_id: str
    label: str
    value: Any
    display_value: str
    unit: str
    status: str
    status_label: str
    note: str
    editable: bool
    field_type: str
    required: bool
    min_value: float | None
    max_value: float | None
    step: str
    help_text: str


@dataclass(frozen=True)
class Slice1Section:
    section_id: str
    label: str
    rows: tuple[Slice1Row, ...]


def inputs_slice1_enabled() -> bool:
    """Return True when Slice 1 is active (default: active when flag is absent).

    Delegates to the canonical flag helper. Kept for call sites that
    import directly from this module; new code should use
    ``app.utils.workbook_flag.inputs_slice1_active``.
    """
    from app.utils.workbook_flag import inputs_slice1_active
    return inputs_slice1_active()


def build_inputs_slice1_sections(
    pis: ProjectInputSet,
    *,
    project_editable: bool,
    submitted_values: dict[str, str] | None = None,
    field_errors: dict[str, str] | None = None,
) -> list[dict[str, Any]]:
    """Build template context for the canonical Inputs Slice 1 grid."""
    submitted_values = submitted_values or {}
    field_errors = field_errors or {}
    sections: list[dict[str, Any]] = []
    for section_id, label, field_ids in SLICE1_SECTIONS:
        rows = [
            _row_for_field(
                WORKBOOK.field(field_id),
                pis,
                project_editable=project_editable,
                submitted_value=submitted_values.get(field_id),
                field_error=field_errors.get(field_id, ""),
            )
            for field_id in field_ids
        ]
        sections.append({
            "section_id": section_id,
            "label": label,
            "rows": rows,
        })
    return sections


def build_inputs_slice1_section(
    section_id: str,
    pis: ProjectInputSet,
    *,
    project_editable: bool,
    submitted_values: dict[str, str] | None = None,
    field_errors: dict[str, str] | None = None,
) -> dict[str, Any]:
    """Build one Slice 1 section by id."""
    for candidate_id, label, field_ids in SLICE1_SECTIONS:
        if candidate_id == section_id:
            rows = [
                _row_for_field(
                    WORKBOOK.field(field_id),
                    pis,
                    project_editable=project_editable,
                    submitted_value=(submitted_values or {}).get(field_id),
                    field_error=(field_errors or {}).get(field_id, ""),
                )
                for field_id in field_ids
            ]
            return {"section_id": candidate_id, "label": label, "rows": rows}
    raise KeyError(f"Unknown Inputs Slice 1 section: {section_id!r}")


def slice1_edit_allowed(field_id: str) -> bool:
    """Return True only for fields this feature exposes as editable."""
    return field_id in SLICE1_EDITABLE_FIELD_IDS


def classify_slice1_field_id(field_id: str) -> str:
    """Classify a submitted field ID without throwing for user input."""
    if field_id in SLICE1_EDITABLE_FIELD_IDS:
        return KNOWN_SLICE1_EDITABLE
    if field_id in SLICE1_FIELD_IDS:
        return KNOWN_SLICE1_READ_ONLY
    try:
        WORKBOOK.field(field_id)
    except KeyError:
        return UNKNOWN_REGISTRY_FIELD
    return KNOWN_REGISTRY_OUTSIDE_SLICE1


def slice1_rejection_message(field_id: str, classification: str) -> str:
    """Return a controlled, user-safe rejection message for a non-editable ID."""
    if classification == KNOWN_SLICE1_READ_ONLY:
        return f"Field {field_id!r} is read-only in Inputs Slice 1."
    if classification == KNOWN_REGISTRY_OUTSIDE_SLICE1:
        reason = DEFERRED_FIELD_REASONS.get(
            field_id,
            "This registry field is outside the Inputs Slice 1 editable contract.",
        )
        return f"Field {field_id!r} is not editable in Inputs Slice 1. {reason}"
    if classification == UNKNOWN_REGISTRY_FIELD:
        return f"Unknown workbook field: {field_id!r}."
    return f"Field {field_id!r} is not editable in Inputs Slice 1."


def slice1_section_id_for_field(field_id: str) -> str:
    """Return the Slice 1 section containing field_id."""
    for section_id, _label, field_ids in SLICE1_SECTIONS:
        if field_id in field_ids:
            return section_id
    raise KeyError(f"Field {field_id!r} is not part of Inputs Slice 1.")


def _row_for_field(
    spec: FieldSpec,
    pis: ProjectInputSet,
    *,
    project_editable: bool,
    submitted_value: str | None = None,
    field_error: str = "",
) -> dict[str, Any]:
    status = _status_for_spec(spec, project_editable=project_editable)
    editable = status == EDITABLE_BOUND
    value = pis.get(spec.field_id)
    input_value = submitted_value if submitted_value is not None else _format_value(value, spec)
    note = _FIELD_NOTES.get(spec.field_id, _STATUS_NOTES[status])
    return {
        "field_id": spec.field_id,
        "label": spec.label,
        "value": value,
        "display_value": _format_value(value, spec),
        "input_value": input_value,
        "unit": spec.unit or "",
        "status": status,
        "status_label": _STATUS_LABELS[status],
        "note": note,
        "field_error": field_error,
        "editable": editable,
        "field_type": spec.field_type.value,
        "required": spec.required,
        "min_value": spec.min_value,
        "max_value": spec.max_value,
        "step": _step_for_spec(spec),
        "help_text": spec.description or note,
    }


def _status_for_spec(spec: FieldSpec, *, project_editable: bool) -> str:
    if not project_editable:
        return READ_ONLY_REFERENCE_PROJECT
    if spec.binding_status == BindingStatus.BOUND and spec.field_id in SLICE1_EDITABLE_FIELD_IDS:
        return EDITABLE_BOUND
    if spec.binding_status == BindingStatus.DISPLAY_ONLY:
        return READ_ONLY_DERIVED
    if spec.binding_status == BindingStatus.TEMPLATE_LOCKED:
        return READ_ONLY_TEMPLATE_LOCKED
    return UNAVAILABLE_UNRESOLVED


def _step_for_spec(spec: FieldSpec) -> str:
    field_type = spec.field_type.value
    if field_type in ("months", "years", "int"):
        return "1"
    if spec.decimals is None:
        return "any"
    if spec.decimals == 0:
        return "1"
    return str(round(10 ** (-spec.decimals), spec.decimals))


def _format_value(value: Any, spec: FieldSpec) -> str:
    if value is None or value == "":
        return ""
    if spec.field_type in {FieldType.FLOAT, FieldType.MW, FieldType.MWH, FieldType.KEUR, FieldType.PCT}:
        if isinstance(value, (int, float)) and spec.decimals is not None:
            return f"{float(value):.{spec.decimals}f}"
    if spec.field_type in {FieldType.INT, FieldType.MONTHS, FieldType.YEARS}:
        if isinstance(value, float) and value.is_integer():
            return str(int(value))
    return str(value)
