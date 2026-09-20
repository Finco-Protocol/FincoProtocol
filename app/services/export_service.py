"""Export service — extracted from main_web.py for Phase 49B.

Behavior-preserving refactor — no financial formulas, runtime calculations,
or model output changes.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

from fastapi.responses import HTMLResponse, StreamingResponse
from app.ui.dirty_state import _scenario_changed


# ── Export authority mode constants ───────────────────────────────────────────

EXPORT_AUTHORITY_PREVIEW_WORKING = "PREVIEW_WORKING"
EXPORT_AUTHORITY_FACTORY_REFERENCE = "FACTORY_REFERENCE"
EXPORT_AUTHORITY_CANONICAL_LAST_RUN = "CANONICAL_LAST_RUN"


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
    ``current_snapshot``        – the snapshot used to build project_inputs; None for
                                 factory/reference. For CANONICAL this is
                                 last_runtime_snapshot; for PREVIEW this is draft_snapshot.
    ``runtime_origin``          – provenance label ("saved_state" or None).
    ``active_scenario_id``      – the scenario identity for this export:
                                   CANONICAL  → last_runtime_scenario_id (run-bound)
                                   PREVIEW    → active_scenario_id (current Working)
    ``active_scenario_name``    – name matching active_scenario_id above.
    ``last_runtime_scenario_id``– scenario that produced the last persisted Run.
                                 Only set on CANONICAL paths; used for stale-check logic.
    ``run_id``                  – canonical run UUID if available.
                                 The workspace persists a compact-timestamp snapshot ID
                                 (last_runtime_snapshot_id), NOT a UUID run ID; a run_id
                                 can only be known when a RunRecord is explicitly linked.
                                 CANONICAL: None (truthfully unavailable — no UUID linked).
                                 PREVIEW/FACTORY: None (not_applicable).
    ``run_at``                  – ISO timestamp of the actual calculation run.
                                 CANONICAL: last_runtime_at. PREVIEW/FACTORY: None.
    ``working_changed_since_run`` – True when draft_snapshot differs from last_runtime_snapshot.
                                   CANONICAL: True/False. PREVIEW/FACTORY: False (not_applicable).
    """
    project_inputs: Any  # ProjectInputs | None
    current_snapshot: dict[str, Any] | None
    runtime_origin: str | None
    active_scenario_id: str | None = None
    active_scenario_name: str | None = None
    last_runtime_scenario_id: str | None = None
    any_run_committed: bool = False  # R9/N03-CorrA: True when ≥1 Run committed (Base or Scenario)
    authority_mode: str = EXPORT_AUTHORITY_FACTORY_REFERENCE
    # run_id: NOT the runtime_snapshot_id (compact timestamp). Only set when a
    # canonical UUID run ID is explicitly persisted and linked to this workspace.
    # Currently unavailable in this persistence schema.
    run_id: str | None = None
    run_at: str | None = None            # ISO timestamp of last committed run
    # None → "not_applicable" (FACTORY/PREVIEW); True/False → "true"/"false" (CANONICAL only)
    working_changed_since_run: bool | None = None


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

def _apply_capex_opex_folds(project_inputs, project_id, sc_overrides):
    """Apply CAPEX replace-fold and OPEX additive-fold for the given scenario overrides.

    PREVIEW-ONLY: reads live mutable CAPEX/OPEX tables. Must NOT be called
    for CANONICAL_LAST_RUN — use _apply_capex_opex_folds_from_identity instead.
    """
    import dataclasses as _dc
    from app.services.capex_sub_lines_integration import apply_user_sub_lines_replacing_base
    from app.services.opex_sub_lines_integration import apply_user_sub_lines_to_opex

    folded_capex = apply_user_sub_lines_replacing_base(
        project_inputs.capex,
        project_id=project_id,
        scenario_overrides=sc_overrides,
    )
    if folded_capex is not project_inputs.capex:
        project_inputs = _dc.replace(project_inputs, capex=folded_capex)
    folded_opex = apply_user_sub_lines_to_opex(
        project_inputs.opex,
        project_id=project_id,
        scenario_overrides=sc_overrides,
    )
    if folded_opex is not project_inputs.opex:
        project_inputs = _dc.replace(project_inputs, opex=folded_opex)
    return project_inputs


def _apply_capex_opex_folds_from_identity(project_inputs, project_id, identity_dict):
    """Apply run-bound CAPEX/OPEX folds using persisted identity data.

    Uses the exact sub-line rows and scenario overrides captured at run commit
    time — no live DB reads. Guarantees canonical export reproduces the
    run-time effective inputs without touching mutable tables.

    CAPEX fold uses REPLACE semantics (zero base, then add sub-lines).
    OPEX fold uses ADDITIVE semantics (append sub-lines to existing tuple).
    """
    if not identity_dict:
        return project_inputs

    capex_rows = identity_dict.get("capex_rows") or []
    opex_rows_data = identity_dict.get("opex_rows") or []
    sc_overrides = identity_dict.get("scenario_overrides") or {}

    import dataclasses as _dc

    # CAPEX: REPLACE semantics — zero category base, then fold persisted rows.
    if capex_rows:
        from app.persistence.capex_sub_lines import (
            CapexSubLine,
            CAPEX_CATEGORY_TO_FIELD,
            fold_sub_lines_into_capex,
        )

        cap_sub_lines = tuple(
            CapexSubLine(
                sub_line_id=r["sub_line_id"],
                project_id=project_id,
                parent_category_code=r["parent_category_code"],
                business_code=r.get("business_code", r["sub_line_id"]),
                display_order=0,
                label="",
                amount_keur=float(r["amount_keur"]),
                is_active=True,
            )
            for r in capex_rows
        )

        fields_with_sub_lines: set = set()
        for sub in cap_sub_lines:
            field_name = CAPEX_CATEGORY_TO_FIELD.get(sub.parent_category_code)
            if field_name:
                fields_with_sub_lines.add(field_name)

        zero_updates = {}
        for field_name in fields_with_sub_lines:
            existing_item = getattr(project_inputs.capex, field_name)
            zero_updates[field_name] = _dc.replace(existing_item, amount_keur=0.0)

        zeroed_capex = _dc.replace(project_inputs.capex, **zero_updates) if zero_updates else project_inputs.capex
        capex_line_overrides = (sc_overrides.get("_capex_sub_line_overrides") or {}) if sc_overrides else {}
        folded_capex = fold_sub_lines_into_capex(zeroed_capex, cap_sub_lines, scenario_overrides=capex_line_overrides)
        if folded_capex is not project_inputs.capex:
            project_inputs = _dc.replace(project_inputs, capex=folded_capex)

    # OPEX: ADDITIVE semantics — append persisted sub-line rows.
    if opex_rows_data:
        from app.persistence.opex_sub_lines import OpexSubLine
        from app.services.opex_sub_lines_integration import fold_sub_lines_into_opex

        opex_sub_lines = tuple(
            OpexSubLine(
                sub_line_id=r["sub_line_id"],
                project_id=project_id,
                parent_group_code=r["parent_group_code"],
                business_code=r["business_code"],
                display_order=0,
                label="",
                amount_keur=float(r["amount_keur"]),
                inflation_pct=float(r["inflation_pct"]),
                is_active=True,
            )
            for r in opex_rows_data
        )

        opex_line_overrides = (sc_overrides.get("_opex_sub_line_overrides") or {}) if sc_overrides else {}
        folded_opex = fold_sub_lines_into_opex(project_inputs.opex, opex_sub_lines, scenario_overrides=opex_line_overrides)
        if folded_opex is not project_inputs.opex:
            project_inputs = _dc.replace(project_inputs, opex=folded_opex)

    return project_inputs


def _validate_scenario(sc, scenario_id, project_id):
    """Raise ValueError if scenario is missing, archived, or cross-project."""
    if sc is None:
        raise ValueError(
            f"Scenario {scenario_id!r} cannot be found; export aborted."
        )
    if getattr(sc, "archived", False):
        raise ValueError(
            f"Scenario {getattr(sc, 'scenario_name', scenario_id)!r} "
            "is archived; export aborted."
        )
    if getattr(sc, "project_id", None) != project_id:
        raise ValueError(
            f"Scenario {getattr(sc, 'scenario_name', scenario_id)!r} "
            "belongs to a different project; export aborted."
        )


def _resolve_canonical_last_run_path(project_record, user_id, ws) -> "ResolvedExportAuthority":
    """CANONICAL_LAST_RUN: economics from persisted last-run snapshot. FAIL CLOSED.

    When last_runtime_identity is available (post-Correction B runs), uses the
    persisted run-bound CAPEX/OPEX rows and scenario overrides — never reads
    mutable live tables.  Falls back to live-table reads for pre-Correction B
    rows that have no persisted identity.
    """
    if not ws.any_run_committed:
        raise ValueError(
            "CANONICAL_LAST_RUN_UNAVAILABLE: no committed run exists for this project. "
            "Run the model at least once before exporting."
        )
    if not ws.last_runtime_snapshot:
        raise ValueError(
            "CANONICAL_LAST_RUN_UNAVAILABLE: last-run snapshot is missing. "
            "Run the model again to re-establish canonical state."
        )

    from app.workbook.service import WorkbookService

    pis = WorkbookService.build_input_set(ws.last_runtime_snapshot)
    project_inputs = pis.to_projectinputs()
    current_snapshot: dict[str, Any] = dict(ws.last_runtime_snapshot)

    _ri = getattr(ws, "last_runtime_identity", None)
    active_scenario_name = None

    if _ri is not None:
        # Run-bound path (post-Correction B): use persisted identity — no live DB reads.
        active_scenario_name = _ri.get("scenario_name")
        project_inputs = _apply_capex_opex_folds_from_identity(
            project_inputs, project_record.project_id, _ri
        )
    else:
        # Legacy fallback (pre-Correction B rows without persisted identity):
        # resolve scenario and apply folds using live tables.
        _sc_overrides = None
        if ws.last_runtime_scenario_id:
            from app.persistence.scenarios_repository import get_scenario

            sc = get_scenario(scenario_id=ws.last_runtime_scenario_id, user_id=user_id)
            _validate_scenario(sc, ws.last_runtime_scenario_id, project_record.project_id)
            _sc_overrides = sc.overrides
            active_scenario_name = getattr(sc, "scenario_name", None)

        project_inputs = _apply_capex_opex_folds(
            project_inputs, project_record.project_id, _sc_overrides
        )

    # Staleness check: prefer composite hash when available, fall back to scalar.
    _runtime_composite_hash = getattr(ws, "last_runtime_composite_hash", None)
    if _runtime_composite_hash:
        from app.workbook.workbook_identity import assemble_for_workspace
        from app.workbook.registry import WORKBOOK
        _cur_identity = assemble_for_workspace(
            ws,
            user_id=user_id,
            project_id=project_record.project_id,
            workbook_version=WORKBOOK.version,
        )
        _working_changed = (_cur_identity.composite_hash != _runtime_composite_hash)
    else:
        from app.persistence._helpers import snapshots_equal
        _working_changed = not snapshots_equal(
            ws.draft_snapshot or {}, ws.last_runtime_snapshot or {}
        )

    _run_at = (
        ws.last_runtime_at.isoformat(timespec="seconds")
        if getattr(ws, "last_runtime_at", None) else None
    )
    return ResolvedExportAuthority(
        project_inputs=project_inputs,
        current_snapshot=current_snapshot,
        runtime_origin="saved_state",
        active_scenario_id=ws.last_runtime_scenario_id or None,
        active_scenario_name=active_scenario_name or None,
        last_runtime_scenario_id=ws.last_runtime_scenario_id,
        any_run_committed=bool(ws.any_run_committed),
        authority_mode=EXPORT_AUTHORITY_CANONICAL_LAST_RUN,
        run_id=None,  # truthfully unavailable — no UUID linked to workspace state
        run_at=_run_at,
        working_changed_since_run=_working_changed,
    )


def _resolve_preview_working_path(project_record, user_id, ws) -> "ResolvedExportAuthority":
    """PREVIEW_WORKING: current draft economics; no run identity."""
    if not ws.draft_snapshot:
        raise ValueError(
            "No saved working-copy state exists for this project yet. "
            "Open the workbook and save before exporting."
        )
    current_snapshot: dict[str, Any] = dict(ws.draft_snapshot)

    from app.workbook.service import WorkbookService

    pis = WorkbookService.build_draft_input_set_from_workspace(ws)
    project_inputs = pis.to_projectinputs()

    _sc_overrides = None
    if ws.active_scenario_id:
        from app.persistence.scenarios_repository import get_scenario

        sc = get_scenario(scenario_id=ws.active_scenario_id, user_id=user_id)
        _validate_scenario(sc, ws.active_scenario_id, project_record.project_id)
        _sc_overrides = sc.overrides

    project_inputs = _apply_capex_opex_folds(
        project_inputs, project_record.project_id, _sc_overrides
    )

    return ResolvedExportAuthority(
        project_inputs=project_inputs,
        current_snapshot=current_snapshot,
        runtime_origin="saved_state",
        active_scenario_id=ws.active_scenario_id or None,
        active_scenario_name=ws.active_scenario_name or None,
        last_runtime_scenario_id=ws.last_runtime_scenario_id,
        any_run_committed=bool(ws.any_run_committed),
        authority_mode=EXPORT_AUTHORITY_PREVIEW_WORKING,
        run_id=None,         # not_applicable — preview has no committed run identity
        run_at=None,         # not_applicable
        working_changed_since_run=None,  # not_applicable — Preview IS current Working state
    )


def resolve_export_authority(
    project_record,
    user_id,
    *,
    authority_mode: str = EXPORT_AUTHORITY_CANONICAL_LAST_RUN,
) -> ResolvedExportAuthority:
    """R5/F04-C — single-read export authority resolver.

    Reads the workspace ONCE and returns a ResolvedExportAuthority containing
    both the effective ProjectInputs (scenario-folded) and the raw
    current_snapshot dict.  Both fields come from the same workspace read so
    no concurrent save can produce a torn workbook.

    ``authority_mode`` selects the authority contract:
      CANONICAL_LAST_RUN (default) — economics from last committed run; FAIL
        CLOSED if no run committed or snapshot missing.
      PREVIEW_WORKING — economics from current draft; no run identity.
      FACTORY_REFERENCE — always returns factory path (project_inputs=None).

    Returns factory-path authority for factory/reference projects regardless
    of authority_mode.  Raises ValueError (fail-closed) on unknown mode or
    unavailable canonical state.
    """
    if project_record is None or user_id is None:
        return ResolvedExportAuthority(
            project_inputs=None, current_snapshot=None, runtime_origin=None,
            authority_mode=EXPORT_AUTHORITY_FACTORY_REFERENCE,
        )
    origin = getattr(project_record, "project_origin", "") or ""
    if origin != "user_created":
        return ResolvedExportAuthority(
            project_inputs=None, current_snapshot=None, runtime_origin=None,
            authority_mode=EXPORT_AUTHORITY_FACTORY_REFERENCE,
        )

    _KNOWN_MODES = (
        EXPORT_AUTHORITY_CANONICAL_LAST_RUN,
        EXPORT_AUTHORITY_PREVIEW_WORKING,
        EXPORT_AUTHORITY_FACTORY_REFERENCE,
    )
    if authority_mode not in _KNOWN_MODES:
        raise ValueError(f"Unknown authority_mode: {authority_mode!r}")

    if authority_mode == EXPORT_AUTHORITY_FACTORY_REFERENCE:
        return ResolvedExportAuthority(
            project_inputs=None, current_snapshot=None, runtime_origin=None,
            authority_mode=EXPORT_AUTHORITY_FACTORY_REFERENCE,
        )

    from app.persistence.workspace_repository import get_workspace_state

    ws = get_workspace_state(user_id, project_record.project_id)
    if ws is None:
        raise ValueError(
            "No saved working-copy state exists for this project yet. "
            "Open the workbook and save before exporting."
        )

    if authority_mode == EXPORT_AUTHORITY_CANONICAL_LAST_RUN:
        return _resolve_canonical_last_run_path(project_record, user_id, ws)
    else:
        return _resolve_preview_working_path(project_record, user_id, ws)


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
            # F07: bind the artifact's scenario lineage and export authority.
            runtime_rows = build_runtime_summary_rows(
                runtime_project_code, _project_inputs=authority.project_inputs,
                runtime_origin=authority.runtime_origin,
                scenario_id=authority.active_scenario_id,
                scenario_name=authority.active_scenario_name,
                export_authority=authority.authority_mode,
                working_changed_since_run=authority.working_changed_since_run,
                run_id=authority.run_id,
                run_at=authority.run_at,
            )
        else:
            runtime_rows = build_runtime_summary_rows(
                runtime_project_code,
                export_authority=EXPORT_AUTHORITY_FACTORY_REFERENCE,
            )
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
    # R9/N03: include scenario lineage so callers can detect stale-scenario state.
    # F07-B: include export authority mode, run identity, and staleness.
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
        "export_authority": authority.authority_mode,
        "export_run_id": authority.run_id or "",
        "export_run_at": authority.run_at or "",
        "export_working_changed_since_run": str(authority.working_changed_since_run).lower(),
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
            scenario_id=authority.active_scenario_id,
            scenario_name=authority.active_scenario_name,
            export_authority=authority.authority_mode,
            working_changed_since_run=authority.working_changed_since_run,
            run_id=authority.run_id,
            run_at=authority.run_at,
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
    # F07-B: include export authority mode, run identity, and staleness.
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
        "export_authority": authority.authority_mode,
        "export_run_id": authority.run_id or "",
        "export_run_at": authority.run_at or "",
        "export_working_changed_since_run": str(authority.working_changed_since_run).lower(),
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
