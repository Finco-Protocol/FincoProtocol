"""Export service — extracted from main_web.py for Phase 49B.

Behavior-preserving refactor — no financial formulas, runtime calculations,
or model output changes.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

from fastapi.responses import HTMLResponse, StreamingResponse
from app.ui.dirty_state import _scenario_changed


# ── Single-read export authority ──────────────────────────────────────────────

@dataclass(frozen=True)
class ResolvedExportAuthority:
    """Immutable result of ONE workspace read for an export request.

    R5/F04-C: the workspace is read ONCE per export.  Both the runtime
    economics (project_inputs) and the workbook presentation context
    (current_snapshot) are derived from that single read, so no save that
    arrives between two reads can produce a workbook whose economics and
    presentation come from different project versions.

    ``project_inputs``          – effective ProjectInputs (scenario-folded); None
                                 for factory/reference projects (factory path).
    ``current_snapshot``        – the raw draft_snapshot dict used to build
                                 project_inputs; None for factory/reference projects.
    ``runtime_origin``          – provenance label ("saved_state" or None).
    ``active_scenario_id``      – workspace active_scenario_id at read time (R9/N03).
    ``active_scenario_name``    – workspace active_scenario_name at read time.
    ``last_runtime_scenario_id``– scenario that produced the last persisted Run.
                                 Differs from active_scenario_id when the user
                                 switched scenario after the last Run without
                                 re-running (scenario-switch stale).
    """
    project_inputs: Any  # ProjectInputs | None
    current_snapshot: dict[str, Any] | None
    runtime_origin: str | None
    active_scenario_id: str | None = None
    active_scenario_name: str | None = None
    last_runtime_scenario_id: str | None = None
    any_run_committed: bool = False  # R9/N03-CorrA: True when ≥1 Run committed (Base or Scenario)


@dataclass(frozen=True)
class ExportResponse:
    """Result of an export service function.

    Attributes
    ----------
    bytes_data : bytes | None
        Raw export bytes, if generated successfully.
    filename : str | None
        Suggested filename for the Content-Disposition header.
    media_type : str | None
        MIME content type.
    status_code : int
        HTTP status code (200 = success, 400 = bad request).
    error_content : str | None
        HTML error page content, if status_code != 200.
    metadata : dict[str, Any]
        Provenance/runtime metadata extracted during export generation.
        Used by route handlers to populate record_export replay_metadata
        with the same timestamps/origin values the runtime generated.

        CSV / workbook exports populate these keys from runtime_rows[0]:
          - export_generated_at  : str  (ISO timestamp of export generation)
          - runtime_generated_at  : str  (ISO timestamp of the runtime run)
          - runtime_origin        : str  (e.g. "factory_base_runtime", "saved_state")
          - generated_at          : str  (alias for export_generated_at)
          - source_branch         : str  (git branch at runtime generation)

        Excel export (GET /download) accepts an optional replay_metadata
        dict that is passed through to build_excel_export unchanged.
    """
    bytes_data: bytes | None = None
    filename: str | None = None
    media_type: str | None = None
    status_code: int = 200
    error_content: str | None = None
    metadata: dict[str, Any] = field(default_factory=dict)

    def has_error(self) -> bool:
        return self.error_content is not None

    def has_bytes(self) -> bool:
        return self.bytes_data is not None


def _make_streaming_response(export: ExportResponse) -> StreamingResponse | HTMLResponse:
    """Convert an ExportResponse to the appropriate FastAPI response."""
    if export.has_error():
        return HTMLResponse(content=export.error_content, status_code=export.status_code)
    return StreamingResponse(
        iter([export.bytes_data]),
        media_type=export.media_type,
        headers={
            "Content-Disposition": f'attachment; filename="{export.filename}"',
            "Content-Length": str(len(export.bytes_data)),
        },
    )


# ── Values-only Excel export ──────────────────────────────────────────────────

def build_values_only_export_for_project(
    result,
    project_inputs,
    project_type: str,
    scenario: str,
    *,
    replay_metadata: dict | None = None,
) -> ExportResponse:
    """Build values-only Excel export bytes.

    ``result`` and ``project_inputs`` come from the completed model run
    (e.g. ``run_demo_project(...).result`` / ``run_demo_project(...).project_inputs``).
    ``replay_metadata`` is passed directly to ``build_excel_export`` unchanged,
    giving the Excel file the same provenance timestamps as the route's
    ``record_export`` call.

    Behavior matches the original download_get logic in main_web.py.
    """
    from app.excel_export import build_excel_export

    try:
        filename = f"finco_model_{project_type.lower()}_{scenario.lower()}.xlsx"
        excel_bytes = build_excel_export(
            result=result,
            project_inputs=project_inputs,
            provenance_metadata=replay_metadata or {},
        )
        return ExportResponse(
            bytes_data=excel_bytes,
            filename=filename,
            media_type="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
            status_code=200,
        )
    except (ValueError, Exception) as e:
        return ExportResponse(
            status_code=400,
            error_content=(
                f"<html><body><h2>Excel generation failed</h2>"
                f"<p>Invalid input: {str(e)}</p><a href='/'>Back</a></body></html>"
            ),
        )


# ── Runtime Summary CSV export ────────────────────────────────────────────────

def resolve_export_authority(project_record, user_id) -> ResolvedExportAuthority:
    """R5/F04-C — single-read export authority resolver.

    Reads the workspace ONCE and returns a ResolvedExportAuthority containing
    both the effective ProjectInputs (scenario-folded) and the raw
    current_snapshot dict.  Both fields come from the same workspace read so
    no concurrent save can produce a torn workbook.

    Returns a factory-path authority (project_inputs=None, current_snapshot=None)
    for factory/reference projects — callers keep the historical factory path.

    Raises ValueError (fail-closed) when a user-owned project has no usable
    persisted state.  No ``except Exception: pass`` anywhere in this path.
    """
    if project_record is None or user_id is None:
        return ResolvedExportAuthority(
            project_inputs=None, current_snapshot=None, runtime_origin=None,
        )
    origin = getattr(project_record, "project_origin", "") or ""
    if origin != "user_created":
        return ResolvedExportAuthority(
            project_inputs=None, current_snapshot=None, runtime_origin=None,
        )
    from app.persistence.workspace_repository import get_workspace_state

    ws = get_workspace_state(user_id, project_record.project_id)
    if ws is None or not ws.draft_snapshot:
        raise ValueError(
            "No saved working-copy state exists for this project yet. "
            "Open the workbook and save before exporting."
        )
    # Capture current_snapshot from this single read before any mutation.
    current_snapshot: dict[str, Any] = dict(ws.draft_snapshot)

    # ONE authority path: the exact materialization Workbook V2 Run uses
    # (ProjectInputSet.from_snapshot on the draft -> to_projectinputs()).
    from app.workbook.service import WorkbookService

    pis = WorkbookService.build_draft_input_set_from_workspace(ws)
    project_inputs = pis.to_projectinputs()

    # Scenario overlay — EXACT parity with the live /v2/workbook/run path
    # (R5 Correction D): Run materialises the persisted pis_draft via
    # WorkbookService.to_projectinputs, validates the active scenario
    # (fail-closed on missing/archived/cross-project), and passes
    # sc.overrides ONLY to the CAPEX replace-fold and OPEX additive-fold.
    # select_scenario() does NOT rewrite draft_snapshot with scalar
    # overrides, so the export must not invent scalar scenario economics
    # that Run does not apply.  Scalar scenario overrides remain a separate,
    # not-yet-supported remediation — out of R5 scope.
    _sc_overrides = None
    if ws.active_scenario_id:
        from app.persistence.scenarios_repository import get_scenario

        sc = get_scenario(scenario_id=ws.active_scenario_id, user_id=user_id)
        if sc is None:
            raise ValueError(
                f"Active scenario {ws.active_scenario_id!r} cannot be found; "
                "export aborted. Select a valid scenario or deselect the active scenario."
            )
        if getattr(sc, "archived", False):
            raise ValueError(
                f"Active scenario {getattr(sc, 'scenario_name', ws.active_scenario_id)!r} "
                "is archived; export aborted. Select a valid scenario or deselect the active scenario."
            )
        if getattr(sc, "project_id", None) != project_record.project_id:
            raise ValueError(
                f"Active scenario {getattr(sc, 'scenario_name', ws.active_scenario_id)!r} "
                "belongs to a different project; export aborted."
            )
        _sc_overrides = sc.overrides

    # R7/N01: the supported CAPEX/OPEX folds apply for the Base case too
    # (persisted user sub-lines are part of the working copy's effective
    # authority); _sc_overrides carries the scenario-specific overrides
    # when a scenario is active, else None — same as /v2/workbook/run.
    import dataclasses as _dc

    from app.services.capex_sub_lines_integration import (
        apply_user_sub_lines_replacing_base,
    )
    from app.services.opex_sub_lines_integration import (
        apply_user_sub_lines_to_opex,
    )

    folded_capex = apply_user_sub_lines_replacing_base(
        project_inputs.capex,
        project_id=project_record.project_id,
        scenario_overrides=_sc_overrides,
    )
    if folded_capex is not project_inputs.capex:
        project_inputs = _dc.replace(project_inputs, capex=folded_capex)
    folded_opex = apply_user_sub_lines_to_opex(
        project_inputs.opex,
        project_id=project_record.project_id,
        scenario_overrides=_sc_overrides,
    )
    if folded_opex is not project_inputs.opex:
        project_inputs = _dc.replace(project_inputs, opex=folded_opex)

    return ResolvedExportAuthority(
        project_inputs=project_inputs,
        current_snapshot=current_snapshot,
        runtime_origin="saved_state",
        active_scenario_id=ws.active_scenario_id or None,
        active_scenario_name=ws.active_scenario_name or None,
        last_runtime_scenario_id=ws.last_runtime_scenario_id,  # None = never run or Base run
        any_run_committed=bool(ws.any_run_committed),
    )


def resolve_snapshot_authoritative_project_inputs(project_record, user_id):
    """Backwards-compatible delegate — returns only project_inputs.

    Non-export callers (tests, helpers) that need only the effective
    ProjectInputs may continue to use this.  Export paths must use
    resolve_export_authority() to obtain the single-read authority object.
    """
    authority = resolve_export_authority(project_record, user_id)
    return authority.project_inputs


def build_runtime_summary_csv_export(
    runtime_project_code: str,
    *,
    safe_project: str | None = None,
    project_record=None,
    user_id=None,
) -> ExportResponse:
    """Build runtime summary CSV bytes.

    Populates ExportResponse.metadata with fields extracted from
    runtime_rows[0] so that callers can use the same
    export_generated_at / runtime_generated_at / runtime_origin values
    in their record_export() calls that the runtime itself recorded.

    Behavior matches the original runtime_summary_export logic in main_web.py.
    """
    from app.export.runtime_summary import build_runtime_summary_csv, build_runtime_summary_rows

    try:
        # R5/F04-C: ONE workspace read → authority → rows.
        authority = resolve_export_authority(project_record, user_id)
        if authority.project_inputs is not None:
            runtime_rows = build_runtime_summary_rows(
                runtime_project_code, _project_inputs=authority.project_inputs,
                runtime_origin=authority.runtime_origin,
            )
        else:
            runtime_rows = build_runtime_summary_rows(runtime_project_code)
        first_row = runtime_rows[0]
        csv_text = build_runtime_summary_csv(
            runtime_project_code,
            generated_at=first_row["generated_at"],
            source_branch=first_row["source_branch"],
            rows=runtime_rows,
        )
    except ValueError as exc:
        return ExportResponse(
            status_code=400,
            error_content=(
                f"<html><body><h2>Runtime summary export failed</h2>"
                f"<p>{str(exc)}</p><a href='/'>Back</a></body></html>"
            ),
        )

    # Preserve provenance timestamps for the caller's record_export.
    # These must match what the runtime itself recorded.
    # R9/N03: include scenario lineage so callers can detect stale-scenario state.
    metadata = {
        "export_generated_at": first_row["export_generated_at"],
        "runtime_generated_at": first_row["runtime_generated_at"],
        "runtime_origin": first_row["runtime_origin"],
        "generated_at": first_row["generated_at"],
        "source_branch": first_row["source_branch"],
        "export_active_scenario_id": authority.active_scenario_id or "",
        "export_active_scenario_name": authority.active_scenario_name or "",
        "export_last_runtime_scenario_id": authority.last_runtime_scenario_id or "",
        "export_scenario_lineage_stale": (
            _scenario_changed(authority.active_scenario_id or "", authority.last_runtime_scenario_id, any_run_committed=authority.any_run_committed)
            if authority.project_inputs is not None else False
        ),
    }

    filename = f"phase10_{safe_project or runtime_project_code}_runtime_summary.csv"
    data = csv_text.encode("utf-8")
    return ExportResponse(
        bytes_data=data,
        filename=filename,
        media_type="text/csv",
        status_code=200,
        metadata=metadata,
    )


# ── Institutional Workbook export ─────────────────────────────────────────────

def build_institutional_workbook_export(
    runtime_project_code: str,
    *,
    safe_project: str | None = None,
    project_record=None,
    user_id=None,
) -> ExportResponse:
    """Build institutional workbook bytes.

    Populates ExportResponse.metadata with fields extracted from
    runtime_rows[0] so that callers can use the same
    export_generated_at / runtime_generated_at / runtime_origin values
    in their record_export() calls that the runtime itself recorded.

    Behavior matches the original institutional_workbook_export logic in main_web.py.
    """
    from app.export.institutional_workbook import (
        _build_export_bundle,
        export_institutional_workbook_from_bundle,
    )

    try:
        # R5/F04-C: ONE workspace read → authority → bundle.
        # The authority carries both project_inputs and current_snapshot from
        # the same read, preventing torn-snapshot workbooks.
        authority = resolve_export_authority(project_record, user_id)
        bundle = _build_export_bundle(
            runtime_project_code,
            project_inputs=authority.project_inputs,
            runtime_origin=authority.runtime_origin,
            project_record=project_record,
            current_snapshot=authority.current_snapshot,
        )
        first_row = bundle.runtime_rows[0]
        workbook_bytes = export_institutional_workbook_from_bundle(bundle)
    except ValueError as exc:
        return ExportResponse(
            status_code=400,
            error_content=(
                f"<html><body><h2>Institutional workbook export failed</h2>"
                f"<p>{str(exc)}</p><a href='/'>Back</a></body></html>"
            ),
        )

    # Preserve provenance timestamps for the caller's record_export.
    # R9/N03: include scenario lineage so callers can detect stale-scenario state.
    metadata = {
        "export_generated_at": first_row["export_generated_at"],
        "runtime_generated_at": first_row["runtime_generated_at"],
        "runtime_origin": first_row["runtime_origin"],
        "generated_at": first_row["generated_at"],
        "source_branch": first_row["source_branch"],
        "export_active_scenario_id": authority.active_scenario_id or "",
        "export_active_scenario_name": authority.active_scenario_name or "",
        "export_last_runtime_scenario_id": authority.last_runtime_scenario_id or "",
        "export_scenario_lineage_stale": (
            _scenario_changed(authority.active_scenario_id or "", authority.last_runtime_scenario_id, any_run_committed=authority.any_run_committed)
            if authority.project_inputs is not None else False
        ),
    }

    filename = f"phase10_{safe_project or runtime_project_code}_institutional_workbook_skeleton.xlsx"
    return ExportResponse(
        bytes_data=workbook_bytes,
        filename=filename,
        media_type="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
        status_code=200,
        metadata=metadata,
    )


def build_excel_export_for_post_request(
    result,
    project_inputs,
    project_type: str,
    scenario: str,
    runtime_origin: str,
    replay_metadata: dict,
) -> ExportResponse:
    """Build Excel export for POST /download request.

    This function encapsulates the Excel generation portion of the POST /download
    route. It receives a fully-constructed ``replay_metadata`` dict (already mutated
    by the route for ``baseline_source`` when applicable) and produces an
    ExportResponse with bytes, filename, and media type.

    The route retains all orchestration responsibility:
      - authentication / session
      - form parsing
      - project record lookup
      - runtime guard
      - runtime origin resolution
      - build_projectinputs vs build_projectinputs_from_snapshot selection
      - record_export
      - StreamingResponse / HTMLResponse return

    Parameters
    ----------
    result : ModelResult
        Completed model run result (e.g. demo.result).
    project_inputs : ProjectInputs
        Project inputs from the model run (e.g. demo.project_inputs).
    project_type : str
        Project type string from the form (e.g. "Solar", "Wind").
    scenario : str
        Scenario string from the form (e.g. "Base", "Downside").
    runtime_origin : str
        Runtime origin string (e.g. "factory_base_runtime", "saved_state").
        Passed to build_excel_export as provenance_metadata["runtime_origin"].
    replay_metadata : dict
        Provenance metadata already built by the route. Must include all fields
        required for record_export including scenario_id, active_scenario_id,
        template_origin_override, scenario_provenance, warning_note, and
        baseline_source (already set by route before calling this function
        when project_origin == "saved_baseline").

    Returns
    -------
    ExportResponse
        With bytes_data, filename, media_type, and status_code on success;
        or error_content and status_code on failure.

    Behavior matches the original Excel generation portion of download_post
    in main_web.py. No financial formulas, runtime calculations, or model outputs
    are changed.
    """
    from app.excel_export import build_excel_export

    # Ensure runtime_origin is in metadata (build_excel_export expects it)
    metadata = dict(replay_metadata)
    metadata["runtime_origin"] = runtime_origin
    metadata.setdefault("capex_sub_lines_audit_mode", "active_only")

    filename = f"finco_model_{project_type.lower()}_{scenario.lower()}.xlsx"

    try:
        excel_bytes = build_excel_export(
            result=result,
            project_inputs=project_inputs,
            provenance_metadata=metadata,
        )
        return ExportResponse(
            bytes_data=excel_bytes,
            filename=filename,
            media_type="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
            status_code=200,
        )
    except (ValueError, Exception) as e:
        return ExportResponse(
            status_code=500,
            error_content=(
                f"<html><body><h2>Excel generation failed</h2>"
                f"<p>{str(e)}</p><a href='/'>Back</a></body></html>"
            ),
        )


# ── Public API — compose and return FastAPI response ─────────────────────────

def serve_runtime_summary_csv(
    runtime_project_code: str,
    safe_project: str | None = None,
) -> StreamingResponse | HTMLResponse:
    """Thin wrapper for route handlers — returns FastAPI response."""
    export = build_runtime_summary_csv_export(
        runtime_project_code,
        safe_project=safe_project,
    )
    return _make_streaming_response(export)


def serve_institutional_workbook(
    runtime_project_code: str,
    safe_project: str | None = None,
) -> StreamingResponse | HTMLResponse:
    """Thin wrapper for route handlers — returns FastAPI response."""
    export = build_institutional_workbook_export(
        runtime_project_code,
        safe_project=safe_project,
    )
    return _make_streaming_response(export)
