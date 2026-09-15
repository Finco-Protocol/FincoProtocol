"""Export metadata helper for FINCO Model.

Provides a consistent metadata block added to all reviewer-facing export artefacts.
Metadata is purely informational and does not feed into model calculations.

No financial formulas, runtime calculations, or model outputs are changed by
this module.
"""

from __future__ import annotations

from datetime import datetime, timezone
from typing import Any


REFERENCE_SCOPE = (
    "Protected synthetic reference model. Solar/Wind are covered by the public regression ring; "
    "Storage currently has narrower runtime coverage."
)

GENERIC_BOUNDARY = (
    "Generic solar and wind project paths are exploratory and unvalidated. "
    "Not for financial decisions. Do not use for lender, bank, audit, "
    "or certification purposes."
)

NON_CLAIMS = (
    "Financial modelling estimates only. Not legal, tax, accounting, credit, audit, certification, or investment advice."
)

BACKEND_SOURCE_OF_TRUTH = (
    "Backend is source of truth. Exports reflect the last clean backend run, "
    "not unsaved draft edits. Re-run model after any input change before exporting."
)

REFERENCE_PROJECT_KEYS = {"generic_wind_reference", "generic_solar_reference", "generic_storage_reference"}


def _is_generic_project(project_key: str | None) -> bool:
    """Return True for generic/exploratory project paths."""
    if not project_key:
        return False
    key = project_key.strip().lower()
    return key not in REFERENCE_PROJECT_KEYS


def build_export_metadata(
    project_id: str,
    project_name: str | None = None,
    scenario_id: str | None = None,
    scenario_name: str | None = None,
    active_project: str | None = None,
    run_at: str | None = None,
    saved_at: str | None = None,
    is_dirty: bool | None = None,
    validation_status: str | None = None,
    export_type: str = "unknown",
) -> dict[str, str]:
    """Build a lightweight metadata dictionary for export artefacts.

    Parameters
    ----------
    project_id:
        Unique identifier for the project.
    project_name:
        Human-readable project name.
    scenario_id:
        Scenario identifier if applicable.
    scenario_name:
        Scenario name if applicable.
    active_project:
        The active project key used in the runtime (generic_wind_reference/generic_solar_reference/generic).
    run_at:
        ISO timestamp of the runtime execution.
    saved_at:
        ISO timestamp of the last scenario save.
    is_dirty:
        True if the workspace has unsaved changes relative to the last clean run.
    validation_status:
        Validation status string (e.g. "pass", "warn", "pending_review").
    export_type:
        Type of export artefact (e.g. "institutional_workbook", "runtime_summary_csv").

    Returns
    -------
    dict[str, str]
        Metadata dictionary with consistently-named fields.
    """
    now = datetime.now(timezone.utc).isoformat(timespec="seconds")
    is_generic = _is_generic_project(active_project)

    # Determine last_clean_backend_run_at (use run_at as proxy; in the UI layer
    # this would be the last confirmed clean backend run timestamp)
    last_clean_run = run_at if run_at else now

    # Dirty/stale warning
    if is_dirty is True:
        dirty_warning = (
            "WARNING: Workspace has unsaved changes. "
            "This export may not reflect the last clean backend run. "
            "Re-run model before exporting."
        )
    elif is_dirty is False:
        dirty_warning = "No unsaved changes detected."
    else:
        dirty_warning = "Unknown workspace state."

    # Validation status default
    if validation_status is None:
        validation_status = "not_validated"

    # Trusted scope / generic boundary
    if is_generic:
        reference_scope = "Exploratory only — generic project path"
        generic_boundary = GENERIC_BOUNDARY
    else:
        reference_scope = REFERENCE_SCOPE
        generic_boundary = (
            "Protected synthetic reference model. Review the project validation status before relying on outputs."
        )

    return {
        "export_generated_at": now,
        "export_type": export_type,
        "active_project": active_project or "",
        "project_id": project_id,
        "project_name": project_name or "",
        "scenario_id": scenario_id or "",
        "scenario_name": scenario_name or "",
        "scenario_saved_at": saved_at or "",
        "last_clean_backend_run_at": last_clean_run,
        "dirty_or_stale_warning": dirty_warning,
        "validation_status": validation_status,
        "reference_scope": reference_scope,
        "generic_boundary": generic_boundary,
        "non_claims": NON_CLAIMS,
        "backend_source_of_truth": BACKEND_SOURCE_OF_TRUTH,
    }


def metadata_rows(metadata: dict[str, str]) -> list[tuple[str, str]]:
    """Convert a metadata dict to ordered (label, value) rows for display."""
    order = [
        "export_generated_at",
        "export_type",
        "active_project",
        "project_id",
        "project_name",
        "scenario_id",
        "scenario_name",
        "scenario_saved_at",
        "last_clean_backend_run_at",
        "dirty_or_stale_warning",
        "validation_status",
        "reference_scope",
        "generic_boundary",
        "non_claims",
        "backend_source_of_truth",
    ]
    rows = []
    for key in order:
        if key in metadata:
            rows.append((_LABEL_MAP.get(key, key), metadata[key]))
    return rows


_LABEL_MAP: dict[str, str] = {
    "export_generated_at": "Export generated at",
    "export_type": "Export type",
    "active_project": "Active project",
    "project_id": "Project ID",
    "project_name": "Project name",
    "scenario_id": "Scenario ID",
    "scenario_name": "Scenario name",
    "scenario_saved_at": "Scenario saved at",
    "last_clean_backend_run_at": "Last clean backend run at",
    "dirty_or_stale_warning": "Workspace state",
    "validation_status": "Validation status",
    "reference_scope": "Reference scope",
    "generic_boundary": "Generic boundary",
    "non_claims": "Non-claims",
    "backend_source_of_truth": "Backend source of truth",
}