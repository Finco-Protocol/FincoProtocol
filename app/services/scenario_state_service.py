"""Scenario state service — low-risk helpers only.

Phase 50B: Extract build_workspace_state_metadata and scenario_provenance_for_record.
Phase 50C-2: Extract resolve_runtime_snapshot and RuntimeSnapshotResolution.
"""
from dataclasses import dataclass
from typing import Any

from app.persistence.repository import (
    get_scenario_provenance,
    get_workspace_state,
    resolve_active_scenario_runtime_snapshot,
    runtime_guard_for_snapshot,
)


def build_workspace_state_metadata(workspace_state) -> dict:
    """Build UI-visible dirty/runtime state metadata.

    Equivalent to main_web._workspace_state_meta().
    Returns same dict shape regardless of workspace_state being None.
    """
    if workspace_state is None:
        return {
            "dirty": False,
            "dirty_label": "Clean saved state",
            "active_scenario_id": "",
            "active_scenario_name": "",
            "last_runtime_origin": "",
            "last_runtime_origin_label": "No runtime bound yet",
            "last_runtime_snapshot_id": "",
            "last_runtime_scenario_id": None,  # None = never run
        "any_run_committed": False,
        }
    runtime_origin = workspace_state.last_runtime_origin or ""
    if runtime_origin == "saved_state":
        runtime_label = "Runtime bound to saved scenario snapshot"
    elif runtime_origin == "workspace_base":
        runtime_label = "Runtime bound to clean workspace base"
    elif runtime_origin == "preview_only":
        runtime_label = "Preview only; runtime not executed"
    else:
        runtime_label = "No runtime bound yet"
    if workspace_state.dirty and workspace_state.last_runtime_snapshot_id:
        runtime_label = f"{runtime_label} (older than current draft)"
    return {
        "dirty": bool(workspace_state.dirty),
        "dirty_label": "Unsaved edits" if workspace_state.dirty else "Clean saved state",
        "active_scenario_id": workspace_state.active_scenario_id or "",
        "active_scenario_name": workspace_state.active_scenario_name or "",
        "last_runtime_origin": runtime_origin,
        "last_runtime_origin_label": runtime_label,
        "last_runtime_snapshot_id": workspace_state.last_runtime_snapshot_id or "",
        "last_runtime_scenario_id": workspace_state.last_runtime_scenario_id,  # None = never run or Base run
        "any_run_committed": bool(workspace_state.any_run_committed),
    }


def _normalize_template_source(template_source: str | None, project_type: str | None) -> str:
    """Normalize template source string.

    Duplicated from main_web.py to avoid circular import.
    Must stay in sync with main_web._normalize_template_source().
    """
    source = (template_source or "").strip().lower()
    if source in {"generic_wind_reference", "generic_solar_reference", "generic_storage_reference", "generic_data_center_reference", "generic_ev_charging_reference", "generic_wind", "generic_solar", "generic_storage", "generic_data_center", "generic_ev_charging"}:
        return source
    if (project_type or "").strip().lower() in {"data center", "data_center", "datacenter"}:
        return "generic_data_center"
    return "generic_solar" if (project_type or "").strip().lower() == "solar" else ("generic_storage" if (project_type or "").strip().lower() == "storage" else "generic_wind")


def _template_origin_for_record(project_record) -> str:
    """Build template origin string for scenario provenance.

    Duplicated from main_web.py to avoid circular import.
    Must stay in sync with main_web._template_origin_for_record().
    """
    template_seed = _normalize_template_source(
        project_record.template_source or project_record.source_project_template,
        project_record.project_type,
    )
    return f"project_factory:{(template_seed or project_record.project_code or 'unknown').lower()}"


def scenario_provenance_for_record(project_record, scenario_record) -> dict | None:
    """Build scenario provenance dict for UI context.

    Equivalent to main_web._scenario_provenance_for_record().
    Returns None if scenario_record is None (passthrough behavior preserved).
    Returns None if project_record is None (early exit, avoids crash).
    """
    if scenario_record is None:
        return None
    if project_record is None:
        return None
    return get_scenario_provenance(
        scenario_record,
        project_record,
        _template_origin_for_record(project_record),
    )


@dataclass(frozen=True)
class RuntimeSnapshotResolution:
    """Return type for resolve_runtime_snapshot.

    snapshot: dict of clean backend-authored inputs (with project_name/type/origin setdefaulted)
    scenario_record: ScenarioRecord | None — bound active scenario (only in Branch A)
    warning: str | None — if scenario unavailable or resolver returned a warning
    effective_runtime_origin: str — actual origin used (may differ from input)
    """

    snapshot: dict[str, Any]
    scenario_record: Any | None
    warning: str | None
    effective_runtime_origin: str


def resolve_runtime_snapshot(
    *,
    user,
    project_record,
    workspace_state,
    runtime_origin: str,
) -> RuntimeSnapshotResolution:
    """Resolve the clean backend-authored snapshot used for runtime/export binding.

    This is the canonical implementation. main_web._resolve_runtime_snapshot_source
    is a thin backward-compatible wrapper delegating here.

    Parameters
    ----------
    user : User
        Needs user.user_id
    project_record : ProjectRecord
        Needs project_id, project_origin, project_name, project_type,
        project_code, template_source, source_project_template, baseline_snapshot
    workspace_state : WorkspaceStateRecord | None
        Needs active_scenario_id, saved_snapshot
    runtime_origin : str
        From runtime_guard_for_snapshot: "saved_state" | "workspace_base" |
        "factory_base_runtime" | "preview_only"

    Returns
    -------
    RuntimeSnapshotResolution
        snapshot: dict — clean inputs (5 setdefault fields always present)
        scenario_record: ScenarioRecord | None — only non-None in Branch A
        warning: str | None
        effective_runtime_origin: str — may override input in Branch A1
    """
    scenario_record = None
    warning = None
    effective_origin = runtime_origin

    # ── Branch A: saved_state + active_scenario_id ──────────────────────────
    if runtime_origin == "saved_state" and workspace_state and workspace_state.active_scenario_id:
        scenario_record, resolved_snapshot, warning = resolve_active_scenario_runtime_snapshot(
            user.user_id,
            project_record.project_id,
            workspace_state.active_scenario_id,
        )
        # A1: scenario unavailable → override effective_origin to workspace_base
        if scenario_record is None:
            effective_origin = "workspace_base"
            scenario_record = None
            warning = warning or (
                "Selected saved scenario was unavailable, so runtime fell back to the "
                "last clean saved boundary."
            )
            source = dict(workspace_state.saved_snapshot or project_record.baseline_snapshot or {})
        elif resolved_snapshot:
            # A2: resolved snapshot available
            source = dict(resolved_snapshot)
        else:
            # A3: scenario found but no resolved snapshot → saved_snapshot or baseline
            source = dict(workspace_state.saved_snapshot or project_record.baseline_snapshot or {})

    # ── Branch B: user_created projects ────────────────────────────────────
    elif project_record.project_origin == "user_created":
        if runtime_origin == "saved_state" and workspace_state and workspace_state.saved_snapshot:
            # B1: saved_state + saved_snapshot
            source = dict(workspace_state.saved_snapshot)
        else:
            # B2: fallback — baseline_snapshot first (NOT saved_snapshot first!)
            source = dict((project_record.baseline_snapshot or (workspace_state.saved_snapshot if workspace_state else None) or {}))

    # ── Branch C: fallback ────────────────────────────────────────────────
    else:
        source = dict((workspace_state.saved_snapshot if workspace_state else None) or {})

    # ── Post-processing: always setdefault 5 fields ────────────────────────
    source.setdefault("project_name", project_record.project_name)
    source.setdefault("project_type", project_record.project_type)
    source.setdefault("project_origin", project_record.project_origin)
    source.setdefault(
        "template_source",
        project_record.template_source or project_record.source_project_template,
    )
    source.setdefault("active_project", project_record.project_code.lower())

    return RuntimeSnapshotResolution(
        snapshot=source,
        scenario_record=scenario_record,
        warning=warning,
        effective_runtime_origin=effective_origin,
    )


# NOTE: resolve_runtime_snapshot is the canonical implementation as of Phase 50C-2.
# _resolve_runtime_snapshot_source in main_web.py is a thin wrapper around this.
#
# Phase 50C-3: check_runtime_allowed added as thin wrapper around runtime_guard_for_snapshot.


def check_runtime_allowed(workspace_state, snapshot):
    """Thin wrapper around repository.runtime_guard_for_snapshot.

    Phase 50C-3: Wraps runtime_guard_for_snapshot so it can be called from
    scenario_state_service. Returns exactly the same tuple as the underlying
    repository function.

    Parameters
    ----------
    workspace_state : WorkspaceStateRecord | None
        Current workspace state
    snapshot : dict[str, Any]
        Current dirty snapshot

    Returns
    -------
    tuple[bool, str, str]
        (allow_run, runtime_origin, guard_message)
        - allow_run: True if runtime may proceed
        - runtime_origin: "saved_state" | "workspace_base" | "factory_base_runtime" | "preview_only"
        - guard_message: "" if allowed, otherwise blocking reason
    """
    return runtime_guard_for_snapshot(workspace_state, snapshot)