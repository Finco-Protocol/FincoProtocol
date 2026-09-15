"""Export audit service — extracted from main_web.py for Phase 49D-3B.

Provides typed wrappers around the record_export() repository function for
export audit/purposes. Behavior is identical to the original calls in
main_web.py — no financial formulas, runtime calculations, or model output
changes.

Phase 49D-3B extracts the two simpler export routes first:
  - GET /exports/runtime-summary.csv
  - GET /exports/institutional-workbook.xlsx

Both routes have an identical pattern: inline _replay_metadata_for_project
call inside the record_export invocation, with no scenario_id, no complex
pre-built replay_metadata, and no conditional baseline_source logic beyond
the simple saved_baseline check.
"""
from __future__ import annotations

from typing import Any

from app.persistence.repository import record_export


def record_runtime_summary_export(
    user_id: str,
    project_code: str,
    artifact_name: str,
    project_id: str | None,
    governance_state: dict[str, Any],
    replay_metadata: dict[str, Any],
) -> None:
    """Record a runtime summary CSV export audit entry.

    This is a typed wrapper around record_export() for the
    GET /exports/runtime-summary.csv route. The route continues to own:
      - authentication
      - project lookup
      - runtime_project_code normalization
      - export service call
      - StreamingResponse

    Parameters
    ----------
    user_id
        Current user's ID from get_current_user().
    project_code
        Lower-cased, stripped project code (e.g. "generic_wind_reference", "generic_solar_reference").
    artifact_name
        Filename from build_runtime_summary_csv_export (e.g.
        "phase10_generic_wind_reference_runtime_summary.csv").
    project_id
        project_record.project_id if project record exists, else None.
    governance_state
        Output of _governance_snapshot(project_code).
    replay_metadata
        Built inline via _replay_metadata_for_project() using the same
        keys as the original route: export_type, export_timestamp,
        runtime_timestamp, runtime_origin, artifact_name, baseline_source.

    Returns
    -------
    None
        record_export is called for its side-effect (persistence) only.
    """
    record_export(
        user_id=user_id,
        project_code=project_code,
        export_type="runtime_summary_csv",
        artifact_name=artifact_name,
        artifact_path=f"/exports/runtime-summary.csv?project={project_code}",
        project_id=project_id,
        governance_state=governance_state,
        replay_metadata=replay_metadata,
    )


def record_institutional_workbook_export(
    user_id: str,
    project_code: str,
    artifact_name: str,
    project_id: str | None,
    governance_state: dict[str, Any],
    replay_metadata: dict[str, Any],
) -> None:
    """Record an institutional workbook export audit entry.

    This is a typed wrapper around record_export() for the
    GET /exports/institutional-workbook.xlsx route. The route continues to own:
      - authentication
      - project lookup
      - runtime_project_code normalization
      - export service call
      - StreamingResponse

    Parameters
    ----------
    user_id
        Current user's ID from get_current_user().
    project_code
        Lower-cased, stripped project code (e.g. "generic_wind_reference", "generic_solar_reference").
    artifact_name
        Filename from build_institutional_workbook_export (e.g.
        "phase10_generic_wind_reference_institutional_workbook_skeleton.xlsx").
    project_id
        project_record.project_id if project record exists, else None.
    governance_state
        Output of _governance_snapshot(project_code).
    replay_metadata
        Built inline via _replay_metadata_for_project() using the same
        keys as the original route: export_type, workbook_type, export_timestamp,
        runtime_timestamp, runtime_origin, artifact_name, baseline_source.

    Returns
    -------
    None
        record_export is called for its side-effect (persistence) only.
    """
    record_export(
        user_id=user_id,
        project_code=project_code,
        export_type="institutional_workbook",
        artifact_name=artifact_name,
        artifact_path=f"/exports/institutional-workbook.xlsx?project={project_code}",
        project_id=project_id,
        governance_state=governance_state,
        replay_metadata=replay_metadata,
    )


def record_download_export(
    user_id: str,
    project_code: str,
    export_type: str,
    artifact_name: str,
    artifact_path: str,
    project_id: str | None,
    governance_state: dict[str, Any],
    replay_metadata: dict[str, Any],
    scenario_id: str | None = None,
) -> None:
    """Record an Excel model export audit entry.

    This is a typed wrapper around record_export() for both the
    GET /download and POST /download routes. The routes continue to own:
      - authentication
      - form parsing / project lookup
      - runtime_origin resolution
      - replay_metadata construction (including baseline_source timing)
      - record_export timing (post-bytes for POST, post-helper for GET)
      - StreamingResponse

    Parameters
    ----------
    user_id
        Current user's ID from get_current_user().
    project_code
        Project code string (e.g. "generic_wind_reference", "generic_solar_reference").
    export_type
        Always "excel_model_export" for download routes.
    artifact_name
        Filename (e.g. "finco_model_solar_base.xlsx").
    artifact_path
        Route URL with query params
        (e.g. "/download?project_type=Solar&scenario=Base").
    project_id
        project_record.project_id if project record exists, else None.
    governance_state
        Output of _governance_snapshot(project_code).
    replay_metadata
        Pre-built provenance dict from the route. Must already contain
        baseline_source (set by route BEFORE calling this function when
        project_origin == "saved_baseline").
    scenario_id
        active_scenario_record.scenario_id if in saved_state path, else None.
        Only applicable to POST /download; GET /download passes None.

    Returns
    -------
    None
        record_export is called for its side-effect (persistence) only.
    """
    kwargs: dict[str, Any] = dict(
        user_id=user_id,
        project_code=project_code,
        export_type=export_type,
        artifact_name=artifact_name,
        artifact_path=artifact_path,
        project_id=project_id,
        governance_state=governance_state,
        replay_metadata=replay_metadata,
    )
    if scenario_id is not None:
        kwargs["scenario_id"] = scenario_id
    record_export(**kwargs)