"""Repository helpers for lightweight project, scenario, run, and export persistence.

This module is the authoritative persistence repository for the web app.
It persists snapshots and review metadata, but never computes or overrides
financial model outputs.
"""

from __future__ import annotations

import uuid
from dataclasses import dataclass
from datetime import datetime, timezone
from typing import Any, Optional

from app.persistence.db import get_cursor


# Phase 53A: Group F helpers re-exported from app.persistence._helpers for
# backward compatibility. The original implementations live in
# app/persistence/_helpers.py.
from app.persistence._helpers import (
    _now_utc,
    _to_json,
    _from_json,
    _from_iso,
    SCENARIO_INPUT_FIELDS,
    _safe_number,
    _metric_value,
    snapshots_equal,
    _strip_empty_fields,
    _get_least_created_scenario_for_project,
)


# Phase 53B: Group D (runs) re-exported from app.persistence.runs_repository
# for backward compatibility. The original implementations live in
# app/persistence/runs_repository.py.
from app.persistence.runs_repository import (
    RunRecord,
    save_run,
    get_run,
    list_runs,
    delete_run,
    count_runs,
)


# Phase 53C: Group E (exports+audit) re-exported from
# app.persistence.exports_repository for backward compatibility.
# The original implementations live in app/persistence/exports_repository.py.
from app.persistence.exports_repository import (
    ScenarioExportRecord,
    record_export,
    list_exports,
    get_scenario_history,
    compare_scenarios,
    build_export_lineage,
    base_vs_active_compare,
    _scenario_runtime_dict,
    _build_compare_metrics,
    _delta_sign_class,
    _format_db_timestamp,
)


# Phase 53D: Group A-reads (project reads) re-exported from
# app.persistence.projects_repository for backward compatibility.
# The original implementations live in app/persistence/projects_repository.py.
# Project writes (save_project, create_project_record, update_project_record,
# seed_baseline_projects_if_needed, etc.) remain in repository.py for now
# and will move in Group A-2 with the P0 pin for save_project.
from app.persistence.projects_repository import (
    get_project,
    get_project_by_code,
    list_projects,
    list_baseline_records,
    get_project_record,
    list_project_records,
    # Project Library (project-library-reference-working-copies)
    REFERENCE_USER_ID,
    get_reference_projects,
    get_reference_by_template_source,
    get_project_by_id,
    get_canonical_reference_by_id,
    list_projects_paged,
    list_recent_projects,
    resolve_accessible_project,
)


# Phase 53E-2: Group A-2 (project writes) re-exported from
# app.persistence.projects_repository for backward compatibility.
# The original implementations live in app/persistence/projects_repository.py.
from app.persistence.projects_repository import (
    save_project,
    create_project_record,
    update_project_record,
    seed_baseline_projects_if_needed,
    _compute_baseline_snapshot,
    _build_default_snapshot,
    _fill_missing_defaults,
)


# Phase 53F-2: Group C (workspace_state) re-exported from
# app.persistence.workspace_repository for backward compatibility.
# The original implementations live in app/persistence/workspace_repository.py.
from app.persistence.workspace_repository import (
    save_workspace_state,
    get_workspace_state,
    discard_workspace_draft,
    bind_workspace_to_scenario,
)


# Phase 53I-2: Record dataclasses re-exported from
# app.persistence.records for backward compatibility.
# The original implementations live in app/persistence/records.py.
from app.persistence.records import (
    ProjectRecord,
    ScenarioRecord,
    WorkspaceStateRecord,
)


# Phase 53G-2 + 53G-3 + 53G-4: Group B (scenario reads + low-risk actions + save_scenario)
# re-exported from app.persistence.scenarios_repository for backward compatibility.
# The original implementations live in app/persistence/scenarios_repository.py.
from app.persistence.scenarios_repository import (
    get_scenario,
    list_scenarios,
    resolve_scenario_snapshot,
    resolve_active_scenario_runtime_snapshot,
    rename_scenario,
    archive_scenario,
    select_scenario,
    duplicate_scenario,
    promote_scenario_to_base_case,
    save_scenario,
    add_scenario,
    update_scenario_overrides,
    get_or_create_base_case_scenario,
    get_base_case_scenario,
)






def seed_scenarios_if_needed(
    user_id: str,
    project_id: str,
    project_code: str,
    project_type: str,
    source_project_template: str,
    baseline_snapshot: dict[str, Any],
    governance_state: dict[str, Any],
    template_origin: str,
) -> "ScenarioRecord":
    """Seed (or return existing) Base Case scenario for a project."""
    rm = {
        "baseline_source": True,
        "template_origin": template_origin,
    }
    return get_or_create_base_case_scenario(
        user_id=user_id,
        project_id=project_id,
        project_code=project_code,
        project_name=baseline_snapshot.get("project_name", project_code),
        project_type=project_type,
        source_project_template=source_project_template,
        base_input_set=baseline_snapshot,
        governance_state=governance_state,
        replay_metadata=rm,
    )


def get_scenario_provenance(
    scenario_record: "ScenarioRecord",
    project_record: Optional["ProjectRecord"],
    template_origin: str,
) -> dict[str, Any]:
    """Build scenario provenance dict for export replay_metadata."""
    return {
        "project_id": scenario_record.project_id,
        "project_name": (
            project_record.project_name if project_record else scenario_record.project_code
        ),
        "scenario_id": scenario_record.scenario_id,
        "scenario_name": scenario_record.scenario_name,
        "is_base_case": scenario_record.is_base_case,
        "parent_scenario_id": scenario_record.parent_scenario_id,
        "override_field_list": (
            sorted(scenario_record.overrides.keys())
            if not scenario_record.is_base_case
            else []
        ),
        "baseline_source": (
            (project_record.project_origin == "saved_baseline")
            if project_record
            else False
        ),
        "template_origin": template_origin,
    }







def runtime_guard_for_snapshot(workspace_state: Optional[WorkspaceStateRecord], current_snapshot: dict[str, Any]) -> tuple[bool, str, str]:
    if workspace_state is None:
        return True, "workspace_base", ""
    saved = workspace_state.saved_snapshot
    has_prior_save = saved and snapshots_equal(saved, {}) is False

    if not has_prior_save:
        if workspace_state.dirty:
            return False, "preview_only", (
                "Unsaved edits are active. Save the scenario or discard edits before running so runtime results stay bound to an immutable snapshot."
            )
        return True, "workspace_base", ""

    # Normalize empty-string fields before comparing so that new form fields
    # (e.g. capex_* fields added by _collect_form_snapshot) don't cause a
    # false mismatch with workspace snapshots saved before those fields existed.
    saved_norm = _strip_empty_fields(saved)
    current_norm = _strip_empty_fields(current_snapshot)
    if snapshots_equal(saved_norm, current_norm):
        if workspace_state.active_scenario_id:
            return True, "saved_state", ""
        return True, "workspace_base", ""
    if workspace_state.dirty:
        return False, "preview_only", (
            "Unsaved edits are active. Save the scenario or discard edits before running so runtime results stay bound to an immutable snapshot."
        )
    return False, "preview_only", (
        "Current form state no longer matches the last saved runtime boundary. Refresh or discard edits before running."
    )




def update_scenario_last_run_summary(
    user_id: str,
    scenario_id: str,
    last_run_summary: dict[str, Any],
    replay_metadata: Optional[dict[str, Any]] = None,
) -> bool:
    record = get_scenario(scenario_id, user_id)
    if record is None:
        return False
    merged_replay_metadata = dict(record.replay_metadata or {})
    if replay_metadata:
        merged_replay_metadata.update(replay_metadata)
    # Phase 25B-3 — preserve the previous run summary inside replay_metadata
    # before it is overwritten by the new last_run_summary. This enables the
    # read-only "What changed since previous run?" delta panel (UI only).
    # Behavioural notes:
    # - Only acts when the *current* (about-to-be-overwritten) summary is
    #   non-empty (a real prior run exists).
    # - The stored value lives only in replay_metadata; the new
    #   last_run_summary still becomes the authoritative current run.
    # - second_last_run_summary keeps the older "previous" so the UI can
    #   still show a chain (run N-2 -> run N-1) if needed. UI side may
    #   ignore it for now.
    if record.last_run_summary:
        if "previous_run_summary" in merged_replay_metadata:
            merged_replay_metadata["second_last_run_summary"] = (
                merged_replay_metadata["previous_run_summary"]
            )
        merged_replay_metadata["previous_run_summary"] = dict(record.last_run_summary)
        if record.updated_at is not None:
            merged_replay_metadata["previous_run_at"] = record.updated_at.isoformat()
    with get_cursor() as cur:
        cur.execute(
            """
            UPDATE scenarios
            SET last_run_summary_json=?, replay_metadata_json=?, updated_at=?
            WHERE scenario_id=? AND user_id=?
            """,
            (
                _to_json(last_run_summary or {}),
                _to_json(merged_replay_metadata),
                _now_utc().isoformat(),
                scenario_id,
                user_id,
            ),
        )
        return cur.rowcount > 0



def record_workspace_runtime(
    *,
    user_id: str,
    project_id: str,
    project_code: str,
    runtime_snapshot: dict[str, Any],
    runtime_summary: dict[str, Any],
    runtime_snapshot_id: str,
    runtime_origin: str,
    governance_state: Optional[dict[str, Any]] = None,
    active_scenario_id: Optional[str] = None,
    active_scenario_name: Optional[str] = None,
    replay_metadata: Optional[dict[str, Any]] = None,
    # Workbook V2 PR 3: full schedule payloads — DB is now authoritative.
    financial_statements: Optional[dict[str, Any]] = None,
    debt_schedule: Optional[dict[str, Any]] = None,
    tax_schedule: Optional[dict[str, Any]] = None,
    distribution_schedule: Optional[dict[str, Any]] = None,
    sponsor_schedule: Optional[dict[str, Any]] = None,
) -> WorkspaceStateRecord:
    existing = get_workspace_state(user_id, project_id)
    saved_snapshot = existing.saved_snapshot if existing else runtime_snapshot
    draft_snapshot = existing.draft_snapshot if existing else runtime_snapshot
    dirty = existing.dirty if existing else False
    return save_workspace_state(
        user_id=user_id,
        project_id=project_id,
        project_code=project_code,
        active_scenario_id=active_scenario_id if active_scenario_id is not None else (existing.active_scenario_id if existing else None),
        active_scenario_name=active_scenario_name if active_scenario_name is not None else (existing.active_scenario_name if existing else None),
        draft_snapshot=draft_snapshot,
        saved_snapshot=saved_snapshot,
        last_runtime_snapshot=runtime_snapshot,
        last_runtime_summary=runtime_summary,
        last_runtime_snapshot_id=runtime_snapshot_id,
        last_runtime_origin=runtime_origin,
        last_runtime_scenario_id=active_scenario_id if runtime_origin == "saved_state" else None,
        last_financial_statements=financial_statements,
        last_debt_schedule=debt_schedule,
        last_tax_schedule=tax_schedule,
        last_distribution_schedule=distribution_schedule,
        last_sponsor_schedule=sponsor_schedule,
        dirty=dirty,
        governance_state=governance_state or (existing.governance_state if existing else {}),
        replay_metadata=replay_metadata,
        last_runtime_at=_now_utc(),
    )


