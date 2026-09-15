"""Lightweight provenance helpers for audit replay metadata.

These helpers capture informational metadata only. They do not replay runs,
override runtime values, or become a second source of truth for the model.
"""

from __future__ import annotations

from datetime import datetime, timezone
import json
from pathlib import Path
import subprocess
from typing import Any


ROOT = Path(__file__).resolve().parents[2]
REPLAY_LIMITATIONS_NOTICE = (
    "Replay metadata improves traceability, but deterministic replay is not fully "
    "guaranteed yet. Runtime trees, editable-state replay, and full environment "
    "capture are not persisted in this branch."
)
UNAVAILABLE = "unavailable"
NOT_APPLICABLE = "not_applicable"
LEGACY_FROZEN = "legacy_frozen"
EXPORT_TEMPLATE_VERSION = "not separately versioned"

_INFO_FLAG_NAMES = (
    "use_opex_line_item_engine",
    "use_construction_schedule_engine",
    "use_senior_rate_schedule_engine",
    "use_senior_sculpting_basis_engine",
    "use_shl_fcf_waterfall_engine",
    "use_shl_canonical_engine",
    "use_canonical_tax_depreciation_bridge",
    "use_depreciation_canonical_engine",
    "use_tax_bridge_engine",
    "use_senior_debt_sizing_engine",
    "use_shl_gross_accrued_for_pnl",
    "use_book_depreciation_for_pnl",
)

_FINANCING_FLAG_NAMES = (
    "use_senior_sweep_cash_cap_for_shl",
    "use_reference_covenant_input_engine",
    "use_reference_shl_repayment_alignment",
)


def utc_now_iso() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


def _run_git(args: list[str]) -> str:
    try:
        completed = subprocess.run(
            ["git", *args],
            cwd=str(ROOT),
            capture_output=True,
            check=True,
            text=True,
            timeout=3,
        )
    except Exception:
        return "unknown"
    return completed.stdout.strip() or "unknown"


def get_git_commit_sha() -> str:
    return _run_git(["rev-parse", "HEAD"])


def get_git_branch_name() -> str:
    branch = _run_git(["rev-parse", "--abbrev-ref", "HEAD"])
    return branch if branch and branch != "HEAD" else "unknown"


def runtime_flag_snapshot(project_inputs: Any) -> dict[str, bool]:
    info = getattr(project_inputs, "info", None)
    financing = getattr(project_inputs, "financing", None)
    snapshot: dict[str, bool] = {}
    for name in _INFO_FLAG_NAMES:
        snapshot[name] = bool(getattr(info, name, False))
    for name in _FINANCING_FLAG_NAMES:
        snapshot[name] = bool(getattr(financing, name, False))
    return snapshot


def template_provenance(project_key: str, project_inputs: Any) -> dict[str, str]:
    info = getattr(project_inputs, "info", None)
    code = getattr(info, "code", project_key or "unknown")
    return {
        "project_template_key": (project_key or "unknown").lower(),
        "template_origin": f"project_factory:{(project_key or 'unknown').lower()}",
        "template_code": str(code),
        "template_revision": "not separately versioned",
    }


def provenance_marker(value: Any, *, missing: str = UNAVAILABLE) -> Any:
    if value in (None, "", [], {}, ()):
        return missing
    return value


def governance_posture_summary(governance_state: dict[str, Any] | None) -> str:
    state = governance_state or {}
    g20_status = state.get("g20_status", "BLOCKED")
    r99_status = state.get("r99_r102_status", "NOT APPROVED")
    return f"G20 remains {g20_status}; R99/R102 remain {r99_status}"


def build_replay_metadata(
    *,
    project_key: str,
    project_inputs: Any,
    governance_state: dict[str, Any] | None = None,
    project_id: str | None = None,
    scenario_id: str | None = None,
    run_id: str | None = None,
    export_id: str | None = None,
    runtime_timestamp: str | None = None,
    export_timestamp: str | None = None,
    runtime_snapshot_id: str | None = None,
    artifact_name: str | None = None,
    export_type: str | None = None,
    workbook_type: str | None = None,
    active_project: str | None = None,
    scenario_name: str | None = None,
    scenario_revision: str | None = None,
    runtime_origin: str | None = None,
    export_template_version: str | None = None,
) -> dict[str, Any]:
    flags = runtime_flag_snapshot(project_inputs)
    template_meta = template_provenance(project_key, project_inputs)
    runtime_generated_at = runtime_timestamp or utc_now_iso()
    export_generated_at = export_timestamp or utc_now_iso()
    normalized_governance_state = governance_state or {}
    return {
        "commit_sha": get_git_commit_sha(),
        "branch_name": get_git_branch_name(),
        "runtime_timestamp": runtime_generated_at,
        "runtime_generated_at": runtime_generated_at,
        "export_timestamp": export_generated_at,
        "export_generated_at": export_generated_at,
        "active_project": provenance_marker(active_project or project_key.lower()),
        "project_id": project_id,
        "scenario_id": provenance_marker(scenario_id, missing=NOT_APPLICABLE),
        "scenario_name": provenance_marker(scenario_name, missing=NOT_APPLICABLE),
        "scenario_revision": provenance_marker(
            scenario_revision or scenario_id,
            missing=NOT_APPLICABLE,
        ),
        "run_id": run_id,
        "export_id": export_id,
        "runtime_snapshot_id": provenance_marker(runtime_snapshot_id),
        "runtime_origin": provenance_marker(runtime_origin, missing=NOT_APPLICABLE),
        "artifact_name": artifact_name,
        "export_type": export_type,
        "workbook_type": provenance_marker(workbook_type, missing=NOT_APPLICABLE),
        "export_template_version": provenance_marker(
            export_template_version or EXPORT_TEMPLATE_VERSION,
            missing=NOT_APPLICABLE,
        ),
        "governance_state": normalized_governance_state,
        "governance_posture_summary": governance_posture_summary(normalized_governance_state),
        "runtime_flag_snapshot": flags,
        "runtime_flag_count": len(flags),
        "runtime_flags_json": json.dumps(flags, sort_keys=True),
        "replay_limitations_notice": REPLAY_LIMITATIONS_NOTICE,
        **template_meta,
    }
