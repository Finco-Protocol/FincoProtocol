"""Scenario persistence functions extracted from app.persistence.repository.

This module holds Group B scenario persistence functions extracted
during Phase 53G-2 (reads) and Phase 53G-3 (low-risk actions). The
functions are re-exported from app.persistence.repository for
backward compatibility.

Function inventory (Group B-reads, Phase 53G-2):

- get_scenario
- list_scenarios
- resolve_scenario_snapshot
- resolve_active_scenario_runtime_snapshot

Function inventory (Group B low-risk actions, Phase 53G-3):

- rename_scenario
- archive_scenario
- select_scenario
- duplicate_scenario
- promote_scenario_to_base_case

Functions NOT in this module (stay in repository.py until their own
extraction PR):

- save_scenario                         (Group B high-risk write, 53G-4)
- add_scenario                          (Group B high-risk write, 53G-5)
- update_scenario_overrides             (Group B high-risk write, 53G-6)
- get_or_create_base_case_scenario      (Group B high-risk write, 53G-7)
- seed_scenarios_if_needed              (NOT Group B, stays in repository.py)
- get_scenario_provenance               (NOT Group B, stays in repository.py)
- get_base_case_scenario                (NOT Group B, stays in repository.py)
- record_workspace_runtime              (NOT Group B, stays in repository.py)
- runtime_guard_for_snapshot            (NOT Group B, stays in repository.py)

Behavior is preserved exactly as it was in repository.py. The only
differences from the originals are:

1. TYPE_CHECKING forward-reference for ScenarioRecord to avoid circular
   imports. The class object is resolved at runtime via lazy import
   inside function bodies where needed.

Public surface preserved:

- app.persistence.repository.get_scenario                 ✓
- app.persistence.repository.list_scenarios               ✓
- app.persistence.repository.resolve_scenario_snapshot     ✓
- app.persistence.repository.resolve_active_scenario_runtime_snapshot ✓
- app.persistence.repository.rename_scenario              ✓
- app.persistence.repository.archive_scenario             ✓
- app.persistence.repository.select_scenario              ✓
- app.persistence.repository.duplicate_scenario           ✓
- app.persistence.repository.promote_scenario_to_base_case ✓
"""
from __future__ import annotations

import uuid
from typing import TYPE_CHECKING, Any, Optional

from app.persistence._helpers import _now_utc, _to_json, SCENARIO_INPUT_FIELDS
from app.persistence.db import get_cursor

if TYPE_CHECKING:
    from app.persistence.records import ScenarioRecord


# ============================================================
# Group B-reads (Phase 53G-2)
# ============================================================


def resolve_scenario_snapshot(
    base_input_set: dict[str, Any],
    overrides: dict[str, Any],
) -> dict[str, Any]:
    """Resolve effective snapshot: base + overrides.

    Missing override keys inherit from base_input_set.
    Unknown keys in overrides are silently dropped.
    Empty overrides returns a copy of base_input_set.
    """
    base = dict(base_input_set)
    for key, value in overrides.items():
        if key in SCENARIO_INPUT_FIELDS:
            base[key] = value
    return base


def get_scenario(scenario_id: str, user_id: str) -> "Optional[ScenarioRecord]":
    from app.persistence.records import ScenarioRecord
    with get_cursor() as cur:
        cur.execute("SELECT * FROM scenarios WHERE scenario_id=? AND user_id=?", (scenario_id, user_id))
        row = cur.fetchone()
    return ScenarioRecord.from_row(row) if row else None


def list_scenarios(
    user_id: str,
    project_id: Optional[str] = None,
    include_archived: bool = False,
    limit: int = 25,
) -> "list[ScenarioRecord]":
    from app.persistence.records import ScenarioRecord
    query = "SELECT * FROM scenarios WHERE user_id=?"
    params: list[Any] = [user_id]
    if project_id:
        query += " AND project_id=?"
        params.append(project_id)
    if not include_archived:
        query += " AND archived=0"
    query += " ORDER BY updated_at DESC LIMIT ?"
    params.append(limit)

    with get_cursor() as cur:
        cur.execute(query, tuple(params))
        return [ScenarioRecord.from_row(row) for row in cur.fetchall()]


def resolve_active_scenario_runtime_snapshot(
    user_id: str,
    project_id: str,
    active_scenario_id: Optional[str],
) -> tuple[Optional["ScenarioRecord"], Optional[dict[str, Any]], Optional[str]]:
    """Resolve the clean saved runtime snapshot for the active scenario.

    Returns a tuple of:
      (scenario_record, resolved_snapshot, warning_message)

    Rules:
    - Base Case => full base_input_set / snapshot
    - Non-base => resolve_scenario_snapshot(base_case.base_input_set, overrides_json)
    - Missing / invalid scenario => (None, None, warning)
    """
    from app.persistence.repository import get_base_case_scenario

    if not active_scenario_id:
        return None, None, None

    scenario_record = get_scenario(active_scenario_id, user_id)
    if scenario_record is None or scenario_record.archived or scenario_record.project_id != project_id:
        return None, None, (
            "Selected saved scenario was unavailable, so runtime fell back to the last clean saved boundary."
        )

    if scenario_record.is_base_case:
        snapshot = dict(scenario_record.base_input_set or scenario_record.snapshot or {})
        return scenario_record, snapshot, None

    base_case = None
    if scenario_record.parent_scenario_id:
        parent = get_scenario(scenario_record.parent_scenario_id, user_id)
        if parent is not None and parent.project_id == project_id and parent.is_base_case and not parent.archived:
            base_case = parent
    if base_case is None:
        base_case = get_base_case_scenario(user_id, project_id)

    base_input_set = {}
    if base_case is not None:
        base_input_set = dict(base_case.base_input_set or base_case.snapshot or {})
    elif scenario_record.base_input_set:
        base_input_set = dict(scenario_record.base_input_set)

    snapshot = resolve_scenario_snapshot(base_input_set, scenario_record.overrides or {})
    warning = None
    if base_case is None:
        warning = (
            "Selected scenario did not have a resolvable Base Case record, so runtime used the scenario's saved base input set."
        )
    return scenario_record, snapshot, warning


# ============================================================
# Group B low-risk actions (Phase 53G-3)
# ============================================================


def rename_scenario(user_id: str, scenario_id: str, new_name: str) -> bool:
    with get_cursor() as cur:
        cur.execute(
            "UPDATE scenarios SET scenario_name=?, updated_at=? WHERE scenario_id=? AND user_id=?",
            (new_name, _now_utc().isoformat(), scenario_id, user_id),
        )
        return cur.rowcount > 0


def archive_scenario(user_id: str, scenario_id: str) -> bool:
    with get_cursor() as cur:
        cur.execute(
            "UPDATE scenarios SET archived=1, updated_at=? WHERE scenario_id=? AND user_id=?",
            (_now_utc().isoformat(), scenario_id, user_id),
        )
        return cur.rowcount > 0


def promote_scenario_to_base_case(user_id: str, scenario_id: str) -> "Optional[ScenarioRecord]":
    """Promote an existing scenario to be the project's Base Case.

    Clears is_base_case flag from all other scenarios for this project first,
    then sets it on the target scenario.
    Idempotent: safe to call on a scenario that is already the base case.
    """
    with get_cursor() as cur:
        # Clear any existing base case — scoped via subquery so it only clears
        # one of the user's scenarios (not a different user's scenario accidentally)
        cur.execute(
            """
            UPDATE scenarios
            SET is_base_case=0, updated_at=?
            WHERE scenario_id=(
                SELECT scenario_id FROM scenarios
                WHERE user_id=? AND is_base_case=1
                LIMIT 1
            )
            """,
            (_now_utc().isoformat(), user_id),
        )
        # Promote the target scenario
        cur.execute(
            """
            UPDATE scenarios
            SET is_base_case=1, updated_at=?
            WHERE scenario_id=? AND user_id=?
            """,
            (_now_utc().isoformat(), scenario_id, user_id),
        )
        if cur.rowcount == 0:
            return None
    return get_scenario(scenario_id, user_id)


def duplicate_scenario(user_id: str, scenario_id: str, new_name: Optional[str] = None) -> "Optional[ScenarioRecord]":
    from app.persistence.records import ScenarioRecord
    import copy
    record = get_scenario(scenario_id, user_id)
    if record is None:
        return None
    copy_name = new_name or f"{record.scenario_name} Copy"
    new_scenario_id = uuid.uuid4().hex[:16]
    now = _now_utc()
    replay_metadata = copy.deepcopy(record.replay_metadata or {})
    replay_metadata.setdefault("project_id", record.project_id)
    replay_metadata["scenario_id"] = new_scenario_id

    # Duplicate preserves scenario payload integrity (snapshot, base_input_set,
    # and overrides) while still creating a fresh non-base scenario shell with
    # a new scenario_id / name / timestamps and copied_from_scenario_id lineage.
    snapshot = copy.deepcopy(record.snapshot or {})
    governance_state = copy.deepcopy(record.governance_state or {})
    last_run_summary = copy.deepcopy(record.last_run_summary or {})
    base_input_set = copy.deepcopy(record.base_input_set or {})
    overrides = copy.deepcopy(record.overrides or {})

    with get_cursor() as cur:
        cur.execute(
            """
            INSERT INTO scenarios (
                scenario_id, project_id, user_id, scenario_name, project_code,
                source_project_template, copied_from_scenario_id, archived,
                is_base_case, parent_scenario_id,
                base_input_set_json, overrides_json,
                snapshot_json, governance_state_json,
                last_run_summary_json, replay_metadata_json,
                schema_version, created_at, updated_at
            ) VALUES (?, ?, ?, ?, ?, ?, ?, 0, 0, NULL, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                new_scenario_id,
                record.project_id,
                user_id,
                copy_name,
                record.project_code,
                record.source_project_template,
                record.scenario_id,
                _to_json(base_input_set),
                _to_json(overrides),
                _to_json(snapshot),
                _to_json(governance_state),
                _to_json(last_run_summary),
                _to_json(replay_metadata),
                record.schema_version or "1.0",
                now.isoformat(),
                now.isoformat(),
            ),
        )

    return ScenarioRecord(
        scenario_id=new_scenario_id,
        project_id=record.project_id,
        user_id=user_id,
        scenario_name=copy_name,
        project_code=record.project_code,
        source_project_template=record.source_project_template,
        copied_from_scenario_id=record.scenario_id,
        archived=False,
        is_base_case=False,
        parent_scenario_id=None,
        base_input_set=base_input_set,
        overrides=overrides,
        schema_version=record.schema_version or "1.0",
        snapshot=snapshot,
        governance_state=governance_state,
        last_run_summary=last_run_summary,
        replay_metadata=replay_metadata,
        created_at=now,
        updated_at=now,
    )


def select_scenario(
    user_id: str,
    project_id: str,
    scenario_id: str,
) -> bool:
    """Set the active scenario for the given project in workspace_state.

    P1-UX-FIX-1: When the active scenario changes, clear the
    cached runtime evidence (``last_runtime_snapshot``,
    ``last_runtime_summary``, ``last_runtime_origin``) so that
    any subsequent ``POST /download`` returns a clear
    "Run the model before exporting." error instead of exporting
    stale values from the previously-active scenario. The user
    must re-run ``/run`` to populate runtime evidence for the
    newly-selected scenario.

    No persistence schema change; existing rows are reused.
    """
    from app.persistence.repository import get_workspace_state
    from app.persistence.db import get_cursor
    record = get_scenario(scenario_id, user_id)
    if record is None:
        return False
    ws = get_workspace_state(user_id, project_id)
    if ws is None:
        return False
    # P1-UX-FIX-1: Direct DB update so we can clear fields to NULL/empty
    # without the merge semantics of save_workspace_state (which would
    # otherwise keep the previous scenario's runtime evidence).
    from app.persistence.workspace_repository import _now_utc
    now = _now_utc()
    merged_replay_metadata = dict(ws.replay_metadata or {})
    merged_replay_metadata.update({
        "action": "select_scenario",
        "scenario_id": scenario_id,
        "p1_ux_fix_1": "cleared_runtime_evidence",
    })
    with get_cursor() as cur:
        cur.execute(
            """
            UPDATE workspace_states
            SET active_scenario_id=?, active_scenario_name=?,
                saved_snapshot_json=?,
                last_runtime_snapshot_json='{}',
                last_runtime_summary_json='{}',
                last_runtime_snapshot_id=NULL,
                last_runtime_origin=NULL,
                dirty=0,
                replay_metadata_json=?,
                updated_at=?,
                last_runtime_at=NULL
            WHERE workspace_id=? AND user_id=?
            """,
            (
                scenario_id,
                record.scenario_name,
                # saved_snapshot preserved (form state is project-level)
                # use existing snapshot, never fall back to draft
                _workspace_state_to_json(ws.saved_snapshot if ws.saved_snapshot else ws.draft_snapshot),
                # R9/N03: last_runtime_scenario_id is NOT updated here.
                # It records which scenario produced the LAST RUN, not the
                # newly selected scenario. Preserving it allows stale-scenario
                # detection (active_scenario_id != last_runtime_scenario_id).
                _workspace_state_to_json(merged_replay_metadata),
                now.isoformat(),
                ws.workspace_id,
                user_id,
            ),
        )
    return True


def _workspace_state_to_json(value) -> str:
    """Local helper to serialise workspace snapshot fields."""
    import json
    return json.dumps(value if value is not None else {})


# ============================================================
# Group B high-risk write: save_scenario (Phase 53G-4)
# ============================================================


def save_scenario(
    user_id: str,
    project_id: str,
    scenario_name: str,
    project_code: str,
    source_project_template: str,
    snapshot: dict[str, Any],
    governance_state: Optional[dict[str, Any]] = None,
    last_run_summary: Optional[dict[str, Any]] = None,
    copied_from_scenario_id: Optional[str] = None,
    replay_metadata: Optional[dict[str, Any]] = None,
    full_inputs: Optional[dict[str, Any]] = None,  # V3-8
) -> "ScenarioRecord":
    from app.persistence.records import ScenarioRecord
    scenario_id = uuid.uuid4().hex[:16]
    now = _now_utc()
    governance_state = governance_state or {}
    last_run_summary = last_run_summary or {}
    replay_metadata = dict(replay_metadata or {})
    replay_metadata.setdefault("project_id", project_id)
    replay_metadata.setdefault("scenario_id", scenario_id)

    with get_cursor() as cur:
        cur.execute(
            """
            INSERT INTO scenarios (
                scenario_id, project_id, user_id, scenario_name, project_code,
                source_project_template, copied_from_scenario_id, archived,
                snapshot_json, governance_state_json, last_run_summary_json, replay_metadata_json,
                full_inputs_json, created_at, updated_at
            ) VALUES (?, ?, ?, ?, ?, ?, ?, 0, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                scenario_id,
                project_id,
                user_id,
                scenario_name,
                project_code,
                source_project_template,
                copied_from_scenario_id,
                _to_json(snapshot),
                _to_json(governance_state),
                _to_json(last_run_summary),
                _to_json(replay_metadata),
                _to_json(full_inputs) if full_inputs is not None else None,
                now.isoformat(),
                now.isoformat(),
            ),
        )

    return ScenarioRecord(
        scenario_id=scenario_id,
        project_id=project_id,
        user_id=user_id,
        scenario_name=scenario_name,
        project_code=project_code,
        source_project_template=source_project_template,
        copied_from_scenario_id=copied_from_scenario_id,
        archived=False,
        snapshot=snapshot,
        governance_state=governance_state,
        last_run_summary=last_run_summary,
        replay_metadata=replay_metadata,
        created_at=now,
        updated_at=now,
        full_inputs=full_inputs,
    )


# ============================================================
# Group B high-risk write: add_scenario (Phase 53G-5)
# ============================================================


def add_scenario(
    user_id: str,
    project_id: str,
    project_code: str,
    scenario_name: str,
    parent_scenario_id: str,
    base_input_set: dict[str, Any],
    overrides: Optional[dict[str, Any]] = None,
    governance_state: Optional[dict[str, Any]] = None,
    replay_metadata: Optional[dict[str, Any]] = None,
    full_inputs: Optional[dict[str, Any]] = None,  # V3-8
) -> "Optional[ScenarioRecord]":
    """Add a non-base scenario inheriting from a parent (typically the Base Case).

    The new scenario starts with empty overrides, so its effective snapshot
    is identical to the parent's base_input_set.
    """
    from app.persistence.records import ScenarioRecord
    # Resolve effective snapshot = base_input_set merged with overrides
    resolved = resolve_scenario_snapshot(base_input_set, overrides or {})

    scenario_id = uuid.uuid4().hex[:16]
    now = _now_utc()
    governance_state = dict(governance_state or {})
    replay_metadata = dict(replay_metadata or {})
    replay_metadata.setdefault("scenario_id", scenario_id)
    replay_metadata["parent_scenario_id"] = parent_scenario_id
    replay_metadata["action"] = "add_scenario"

    with get_cursor() as cur:
        cur.execute(
            """
            INSERT INTO scenarios (
                scenario_id, project_id, user_id, scenario_name, project_code,
                source_project_template, copied_from_scenario_id, archived,
                is_base_case, parent_scenario_id,
                base_input_set_json, overrides_json,
                snapshot_json, governance_state_json,
                last_run_summary_json, replay_metadata_json,
                schema_version, full_inputs_json, created_at, updated_at
            ) VALUES (?, ?, ?, ?, ?, ?, NULL, 0, 0, ?, ?, ?, ?, ?, ?, ?, '1.0', ?, ?, ?)
            """,
            (
                scenario_id,
                project_id,
                user_id,
                scenario_name,
                project_code,
                "",
                parent_scenario_id,
                _to_json(dict(base_input_set)),
                _to_json(dict(overrides or {})),
                _to_json(resolved),
                _to_json(governance_state),
                _to_json({}),
                _to_json(replay_metadata),
                _to_json(full_inputs) if full_inputs is not None else None,
                now.isoformat(),
                now.isoformat(),
            ),
        )

    return ScenarioRecord(
        scenario_id=scenario_id,
        project_id=project_id,
        user_id=user_id,
        scenario_name=scenario_name,
        project_code=project_code,
        source_project_template="",
        copied_from_scenario_id=None,
        archived=False,
        is_base_case=False,
        parent_scenario_id=parent_scenario_id,
        base_input_set=dict(base_input_set),
        overrides=dict(overrides or {}),
        schema_version="1.0",
        snapshot=resolved,
        governance_state=governance_state,
        last_run_summary={},
        replay_metadata=replay_metadata,
        created_at=now,
        updated_at=now,
        full_inputs=full_inputs,
    )


# ============================================================
# Group B high-risk write: update_scenario_overrides (Phase 53G-6)
# ============================================================


def update_scenario_overrides(
    user_id: str,
    scenario_id: str,
    overrides: dict[str, Any],
) -> "Optional[ScenarioRecord]":
    """Patch the overrides_json of a non-base scenario.

    Only keys in SCENARIO_INPUT_FIELDS are accepted; everything else is
    dropped (Phase 20B invariant).

    Phase 57A-9C additive extension: a second allowlist of
    **reserved keys** is consulted BEFORE the silent-drop
    check. Reserved keys (currently ``_capex_sub_line_overrides``
    and ``_capex_sub_line_overrides_metadata``) are accepted
    as opaque blobs and merged into ``overrides_json``
    alongside the flat-path entries. This is the scenario
    override surface for CAPEX user-added sub-lines.

    Returns the updated ScenarioRecord or None if the scenario doesn't exist.
    """
    from app.persistence.records import ScenarioRecord
    record = get_scenario(scenario_id, user_id)
    if record is None:
        return None
    if record.is_base_case:
        return None  # base-case overrides are stored in base_input_set; use Inputs tab

    # Phase 57A-9C: reserved-key allowlist. These keys are
    # opaque blobs (sub-line override maps + metadata). They
    # pass the allowlist check before the SCENARIO_INPUT_FIELDS
    # silent-drop rule fires, so callers can persist CAPEX
    # sub-line per-scenario amounts without that data being
    # dropped on the floor.
    _RESERVED_OVERRIDE_KEYS = frozenset(
        {"_capex_sub_line_overrides", "_capex_sub_line_overrides_metadata"}
    )

    # R3/F05 — Validate _capex_sub_line_overrides before persistence.
    # Each amount value in the map must be a finite float.  NaN / +Inf / -Inf
    # are rejected here so they can never reach the DB.  The metadata key is
    # NOT subjected to amount-map validation.
    if "_capex_sub_line_overrides" in overrides:
        from app.workbook.numeric_guard import NumericGuardError, assert_finite_float
        raw_map = overrides["_capex_sub_line_overrides"]
        if isinstance(raw_map, dict):
            for sub_line_id, amount in raw_map.items():
                try:
                    v = float(amount)
                    assert_finite_float(v, label=f"Sub-line amount ({sub_line_id})")
                except (ValueError, TypeError, NumericGuardError) as exc:
                    raise ValueError(
                        f"_capex_sub_line_overrides: non-finite amount for "
                        f"sub_line_id {sub_line_id!r}: {exc}"
                    ) from exc

    # Merge: existing overrides + new ones (new ones win)
    merged = dict(record.overrides)
    for key, value in overrides.items():
        if key in SCENARIO_INPUT_FIELDS:
            merged[key] = value
        elif key in _RESERVED_OVERRIDE_KEYS:
            merged[key] = value
        # else: silently drop unknown keys per Phase 20B rules

    # Re-resolve effective snapshot. The reserved sub-line
    # overrides are NOT consulted here: the effective CAPEX
    # total at runtime is computed by the 57A-9D integration
    # helper, which folds the sub-lines into CapexStructure
    # at materialization time. For 57A-9C we only wire the
    # persistence + scenario-override surface; the run
    # integration is gated on 57A-9D.
    resolved = resolve_scenario_snapshot(record.base_input_set, merged)
    now = _now_utc()

    with get_cursor() as cur:
        cur.execute(
            """
            UPDATE scenarios
            SET overrides_json=?, snapshot_json=?, updated_at=?
            WHERE scenario_id=? AND user_id=?
            """,
            (
                _to_json(merged),
                _to_json(resolved),
                now.isoformat(),
                scenario_id,
                user_id,
            ),
        )

    record.overrides = merged
    record.snapshot = resolved
    record.updated_at = now
    return record


# ============================================================
# Group B high-risk write: get_or_create_base_case_scenario (Phase 53G-7)
# ============================================================


def get_base_case_scenario(user_id: str, project_id: str) -> "Optional[ScenarioRecord]":
    """Return the non-archived Base Case scenario for a project, if present."""
    from app.persistence.records import ScenarioRecord
    with get_cursor() as cur:
        cur.execute(
            """
            SELECT * FROM scenarios
            WHERE user_id=? AND project_id=? AND is_base_case=1 AND archived=0
            LIMIT 1
            """,
            (user_id, project_id),
        )
        row = cur.fetchone()
    return ScenarioRecord.from_row(row) if row else None


def get_or_create_base_case_scenario(
    user_id: str,
    project_id: str,
    project_code: str,
    project_name: str,
    project_type: str,
    source_project_template: str,
    base_input_set: dict[str, Any],
    governance_state: dict[str, Any],
    replay_metadata: Optional[dict[str, Any]] = None,
    full_inputs: Optional[dict[str, Any]] = None,  # V3-8
) -> "ScenarioRecord":
    """Return the existing Base Case scenario for a project, or create one."""
    from app.persistence.records import ScenarioRecord
    with get_cursor() as cur:
        cur.execute(
            """
            SELECT * FROM scenarios
            WHERE user_id=? AND project_id=? AND is_base_case=1 AND archived=0
            LIMIT 1
            """,
            (user_id, project_id),
        )
        row = cur.fetchone()

    if row:
        return ScenarioRecord.from_row(row)

    scenario_id = uuid.uuid4().hex[:16]
    now = _now_utc()
    governance_state = dict(governance_state or {})
    rm = dict(replay_metadata or {})
    rm.setdefault("project_id", project_id)
    rm.setdefault("scenario_id", scenario_id)
    rm["is_base_case"] = True

    with get_cursor() as cur:
        cur.execute(
            """
            INSERT INTO scenarios (
                scenario_id, project_id, user_id, scenario_name, project_code,
                source_project_template, copied_from_scenario_id, archived,
                is_base_case, parent_scenario_id,
                base_input_set_json, overrides_json, schema_version,
                snapshot_json, governance_state_json, last_run_summary_json,
                replay_metadata_json, full_inputs_json, created_at, updated_at
            ) VALUES (?, ?, ?, ?, ?, ?, NULL, 0, 1, NULL, ?, ?, '1.0', ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                scenario_id,
                project_id,
                user_id,
                project_name or "Base Case",
                project_code,
                source_project_template,
                _to_json(base_input_set),
                _to_json({}),  # overrides_json
                # SCENARIO-2 fix: snapshot_json must be base_input_set (not governance_state).
                # Original code had these two values swapped, causing Base Case snapshot to
                # contain only governance keys {g20, lender_ready, r99_r102} and therefore
                # child scenarios inherited governance keys instead of real assumptions.
                _to_json(base_input_set),  # snapshot_json = full input (base + empty overrides)
                _to_json(governance_state),  # governance_state_json
                _to_json({}),  # last_run_summary_json
                _to_json(rm),
                _to_json(full_inputs) if full_inputs is not None else None,
                now.isoformat(),
                now.isoformat(),
            ),
        )

    return ScenarioRecord(
        scenario_id=scenario_id,
        project_id=project_id,
        user_id=user_id,
        scenario_name=project_name or "Base Case",
        project_code=project_code,
        source_project_template=source_project_template,
        copied_from_scenario_id=None,
        archived=False,
        is_base_case=True,
        parent_scenario_id=None,
        base_input_set=base_input_set,
        overrides={},
        schema_version="1.0",
        snapshot=base_input_set,
        governance_state=governance_state,
        last_run_summary={},
        replay_metadata=rm,
        created_at=now,
        updated_at=now,
        full_inputs=full_inputs,
    )
