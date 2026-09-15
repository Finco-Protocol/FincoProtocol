"""Persistence record dataclasses for the Finco pilot workflow.

This module holds the 5 record dataclasses used by the persistence
layer. They were relocated from `app/persistence/repository.py`,
`app/persistence/runs_repository.py`, and
`app/persistence/exports_repository.py` during Phase 53I-2.

All records are re-exported from `app.persistence.repository` for
backward compatibility. `WorkspaceStateRecord` is also re-exported
from `app.persistence.repository`. `ProjectRecord`, `ScenarioRecord`,
`RunRecord`, and `ScenarioExportRecord` are also re-exported from
`app.persistence` (the `__init__.py`).

Function inventory (Phase 53I-2):

- ProjectRecord         (16 fields, @dataclass + slots)
- ScenarioRecord        (19 fields, manual __init__ + slots)
- WorkspaceStateRecord  (19 fields, @dataclass + slots)
- RunRecord             (10 fields, @dataclass + slots, in runs_repository)
- ScenarioExportRecord  (12 fields, @dataclass + slots, in exports_repository)

Public surface preserved:

- app.persistence.repository.ProjectRecord         ✓ (re-exported)
- app.persistence.repository.ScenarioRecord        ✓ (re-exported)
- app.persistence.repository.WorkspaceStateRecord  ✓ (re-exported)
- app.persistence.repository.RunRecord             ✓ (re-exported)
- app.persistence.repository.ScenarioExportRecord  ✓ (re-exported)
- app.persistence.records.<all 5>                   ✓ (direct)

Behavior is preserved exactly as it was before Phase 53I-2.
"""
from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from typing import Any, Optional

from app.persistence._helpers import _from_iso, _from_json


# ============================================================
# ProjectRecord
# ============================================================


@dataclass(slots=True)
class ProjectRecord:
    project_id: str
    user_id: str
    project_code: str
    project_name: str
    project_type: Optional[str]
    project_origin: str
    source_project_template: str
    template_source: Optional[str]
    baseline_snapshot: dict[str, Any]
    archived: bool
    is_readonly: bool
    governance_state: dict[str, Any]
    last_run_summary: dict[str, Any]
    replay_metadata: dict[str, Any]
    created_at: datetime
    updated_at: datetime
    full_inputs: Optional[dict[str, Any]] = None  # V3-7: full-fidelity ProjectInputs dict
    # Project Library fields (project-library-reference-working-copies)
    project_role: str = "user_project"           # "reference" | "working_copy" | "user_project"
    is_protected: bool = False                   # True for reference projects
    source_project_id: Optional[str] = None      # lineage: working_copy → source reference

    @classmethod
    def from_row(cls, row) -> "ProjectRecord":
        keys = row.keys()
        return cls(
            project_id=row["project_id"],
            user_id=row["user_id"],
            project_code=row["project_code"],
            project_name=row["project_name"],
            project_type=row["project_type"],
            project_origin=row["project_origin"] or "factory_template",
            source_project_template=row["source_project_template"],
            template_source=row["template_source"],
            baseline_snapshot=_from_json(row["baseline_snapshot_json"], {}),
            archived=bool(row["archived"]),
            is_readonly=bool(row["is_readonly"]) if "is_readonly" in keys else False,
            governance_state=_from_json(row["governance_state_json"], {}),
            last_run_summary=_from_json(row["last_run_summary_json"], {}),
            replay_metadata=_from_json(row["replay_metadata_json"], {}),
            created_at=_from_iso(row["created_at"]),
            updated_at=_from_iso(row["updated_at"]),
            full_inputs=_from_json(row["full_inputs_json"], None) if "full_inputs_json" in keys else None,
            project_role=row["project_role"] if "project_role" in keys else "user_project",
            is_protected=bool(row["is_protected"]) if "is_protected" in keys else False,
            source_project_id=row["source_project_id"] if "source_project_id" in keys else None,
        )


# ============================================================
# ScenarioRecord (manual __init__ with __slots__)
# ============================================================


class ScenarioRecord:
    __slots__ = (
        "scenario_id", "project_id", "user_id", "scenario_name", "project_code",
        "source_project_template", "copied_from_scenario_id", "archived",
        "is_base_case", "parent_scenario_id", "base_input_set", "overrides",
        "schema_version", "snapshot", "governance_state", "last_run_summary",
        "replay_metadata", "created_at", "updated_at",
        "full_inputs",  # V3-8: full-fidelity ProjectInputs dict (nullable)
    )

    def __init__(
        self,
        scenario_id: str,
        project_id: str,
        user_id: str,
        scenario_name: str,
        project_code: str,
        source_project_template: str,
        copied_from_scenario_id: Optional[str],
        archived: bool,
        is_base_case: bool = False,
        parent_scenario_id: Optional[str] = None,
        base_input_set: Optional[dict] = None,
        overrides: Optional[dict] = None,
        schema_version: str = "1.0",
        snapshot: Optional[dict] = None,
        governance_state: Optional[dict] = None,
        last_run_summary: Optional[dict] = None,
        replay_metadata: Optional[dict] = None,
        created_at: Optional[datetime] = None,
        updated_at: Optional[datetime] = None,
        full_inputs: Optional[dict] = None,  # V3-8
    ):
        self.scenario_id = scenario_id
        self.project_id = project_id
        self.user_id = user_id
        self.scenario_name = scenario_name
        self.project_code = project_code
        self.source_project_template = source_project_template
        self.copied_from_scenario_id = copied_from_scenario_id
        self.archived = archived
        self.is_base_case = is_base_case
        self.parent_scenario_id = parent_scenario_id
        self.base_input_set = base_input_set or {}
        self.overrides = overrides or {}
        self.schema_version = schema_version
        self.snapshot = snapshot or {}
        self.governance_state = governance_state or {}
        self.last_run_summary = last_run_summary or {}
        self.replay_metadata = replay_metadata or {}
        self.created_at = created_at
        self.updated_at = updated_at
        self.full_inputs = full_inputs

    @classmethod
    def from_row(cls, row) -> "ScenarioRecord":
        raw_snapshot = _from_json(row["snapshot_json"], {})
        raw_bis = _from_json(
            row["base_input_set_json"] if "base_input_set_json" in row.keys() else "{}", {}
        )
        raw_gov = _from_json(row["governance_state_json"], {})

        # SCENARIO-2 runtime repair for Base Case records written before the
        # snapshot/governance_state INSERT swap was fixed.  Symptoms of a
        # corrupted record: snapshot contains only governance keys while
        # base_input_set contains real project assumptions.  When detected,
        # swap them in memory so readers always see correct data without a
        # schema migration.
        _GOVERNANCE_ONLY_KEYS = frozenset({"g20", "lender_ready", "r99_r102"})
        _snap_keys = frozenset(raw_snapshot.keys())
        if (
            raw_snapshot          # non-empty
            and _snap_keys <= _GOVERNANCE_ONLY_KEYS   # only governance keys
            and raw_bis           # base_input_set has real data
            and not (frozenset(raw_bis.keys()) <= _GOVERNANCE_ONLY_KEYS)
        ):
            # Corrupted record: snapshot and governance_state were swapped at
            # write time.  Restore correct semantics in memory.
            raw_snapshot, raw_gov = raw_bis, raw_snapshot

        return cls(
            scenario_id=row["scenario_id"],
            project_id=row["project_id"],
            user_id=row["user_id"],
            scenario_name=row["scenario_name"],
            project_code=row["project_code"],
            source_project_template=row["source_project_template"],
            copied_from_scenario_id=row["copied_from_scenario_id"],
            archived=bool(row["archived"]),
            is_base_case=bool(row["is_base_case"]) if "is_base_case" in row.keys() else False,
            parent_scenario_id=row["parent_scenario_id"] if "parent_scenario_id" in row.keys() else None,
            base_input_set=raw_bis,
            overrides=_from_json(row["overrides_json"] if "overrides_json" in row.keys() else "{}", {}),
            schema_version=row["schema_version"] if "schema_version" in row.keys() else "1.0",
            snapshot=raw_snapshot,
            governance_state=raw_gov,
            last_run_summary=_from_json(row["last_run_summary_json"], {}),
            replay_metadata=_from_json(row["replay_metadata_json"], {}),
            created_at=_from_iso(row["created_at"]),
            updated_at=_from_iso(row["updated_at"]),
            full_inputs=_from_json(row["full_inputs_json"], None) if "full_inputs_json" in row.keys() else None,
        )


# ============================================================
# WorkspaceStateRecord
# ============================================================


@dataclass(slots=True)
class WorkspaceStateRecord:
    workspace_id: str
    project_id: str
    user_id: str
    project_code: str
    active_scenario_id: Optional[str]
    active_scenario_name: Optional[str]
    draft_snapshot: dict[str, Any]
    saved_snapshot: dict[str, Any]
    last_runtime_snapshot: dict[str, Any]
    last_runtime_summary: dict[str, Any]
    last_runtime_snapshot_id: Optional[str]
    last_runtime_origin: Optional[str]
    last_runtime_scenario_id: Optional[str]
    # Workbook V2 PR 3: full schedule payloads persisted to DB.
    last_financial_statements: dict[str, Any]
    last_debt_schedule: dict[str, Any]
    last_tax_schedule: dict[str, Any]
    last_distribution_schedule: dict[str, Any]
    last_sponsor_schedule: dict[str, Any]
    dirty: bool
    governance_state: dict[str, Any]
    replay_metadata: dict[str, Any]
    created_at: datetime
    updated_at: datetime
    last_runtime_at: Optional[datetime]
    any_run_committed: bool = False  # R9/N03-CorrA: True when ≥1 Run has been committed (including Base runs)

    @classmethod
    def from_row(cls, row) -> "WorkspaceStateRecord":
        return cls(
            workspace_id=row["workspace_id"],
            project_id=row["project_id"],
            user_id=row["user_id"],
            project_code=row["project_code"],
            active_scenario_id=row["active_scenario_id"],
            active_scenario_name=row["active_scenario_name"],
            draft_snapshot=_from_json(row["draft_snapshot_json"], {}),
            saved_snapshot=_from_json(row["saved_snapshot_json"], {}),
            last_runtime_snapshot=_from_json(row["last_runtime_snapshot_json"], {}),
            last_runtime_summary=_from_json(row["last_runtime_summary_json"], {}),
            last_runtime_snapshot_id=row["last_runtime_snapshot_id"],
            last_runtime_origin=row["last_runtime_origin"],
            last_runtime_scenario_id=row["last_runtime_scenario_id"],
            last_financial_statements=_from_json(row["last_financial_statements_json"] if "last_financial_statements_json" in row.keys() else "{}", {}),
            last_debt_schedule=_from_json(row["last_debt_schedule_json"] if "last_debt_schedule_json" in row.keys() else "{}", {}),
            last_tax_schedule=_from_json(row["last_tax_schedule_json"] if "last_tax_schedule_json" in row.keys() else "{}", {}),
            last_distribution_schedule=_from_json(row["last_distribution_schedule_json"] if "last_distribution_schedule_json" in row.keys() else "{}", {}),
            last_sponsor_schedule=_from_json(row["last_sponsor_schedule_json"] if "last_sponsor_schedule_json" in row.keys() else "{}", {}),
            dirty=bool(row["dirty"]),
            governance_state=_from_json(row["governance_state_json"], {}),
            replay_metadata=_from_json(row["replay_metadata_json"], {}),
            created_at=_from_iso(row["created_at"]),
            updated_at=_from_iso(row["updated_at"]),
            last_runtime_at=_from_iso(row["last_runtime_at"]) if row["last_runtime_at"] else None,
            any_run_committed=bool(row["any_run_committed"]) if "any_run_committed" in row.keys() else False,
        )


# ============================================================
# RunRecord (moved from app/persistence/runs_repository.py)
# ============================================================


@dataclass(slots=True)
class RunRecord:
    run_id: str
    user_id: str
    project_type: str
    scenario: str
    created_at: datetime
    inputs: dict[str, Any]
    kpis: dict[str, Any]
    excel_path: Optional[str] = None
    notes: Optional[str] = None
    replay_metadata: dict[str, Any] | None = None

    def to_dict(self) -> dict[str, Any]:
        return {
            "run_id": self.run_id,
            "user_id": self.user_id,
            "project_type": self.project_type,
            "scenario": self.scenario,
            "created_at": self.created_at.isoformat(),
            "inputs": self.inputs,
            "kpis": self.kpis,
            "excel_path": self.excel_path,
            "notes": self.notes,
            "replay_metadata": self.replay_metadata or {},
        }

    @classmethod
    def from_row(cls, row) -> "RunRecord":
        return cls(
            run_id=row["run_id"],
            user_id=row["user_id"],
            project_type=row["project_type"],
            scenario=row["scenario"],
            created_at=_from_iso(row["created_at"]),
            inputs=_from_json(row["inputs_json"], {}),
            kpis=_from_json(row["kpis_json"], {}),
            excel_path=row["excel_path"],
            notes=row["notes"],
            replay_metadata=_from_json(row["replay_metadata_json"], {}),
        )


# ============================================================
# ScenarioExportRecord (moved from app/persistence/exports_repository.py)
# ============================================================


@dataclass(slots=True)
class ScenarioExportRecord:
    export_id: str
    scenario_id: Optional[str]
    project_id: Optional[str]
    user_id: str
    export_type: str
    artifact_name: str
    artifact_path: Optional[str]
    project_code: str
    governance_state: dict[str, Any]
    runtime_snapshot_id: Optional[str]
    replay_metadata: dict[str, Any]
    created_at: datetime

    @classmethod
    def from_row(cls, row) -> "ScenarioExportRecord":
        return cls(
            export_id=row["export_id"],
            scenario_id=row["scenario_id"],
            project_id=row["project_id"],
            user_id=row["user_id"],
            export_type=row["export_type"],
            artifact_name=row["artifact_name"],
            artifact_path=row["artifact_path"],
            project_code=row["project_code"],
            governance_state=_from_json(row["governance_state_json"], {}),
            runtime_snapshot_id=row["runtime_snapshot_id"],
            replay_metadata=_from_json(row["replay_metadata_json"], {}),
            created_at=_from_iso(row["created_at"]),
        )
