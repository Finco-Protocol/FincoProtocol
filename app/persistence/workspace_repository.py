"""Workspace state persistence functions extracted from app.persistence.repository.

This module holds Group C (workspace_state) persistence functions extracted
during Phase 53F-2. The functions are re-exported from
app.persistence.repository for backward compatibility.

Function inventory (Group C, from Phase 52A/52C/52E/52G + 53F-1):

- save_workspace_state          (high-risk write, P0 pinned in 53F-1)
- get_workspace_state
- discard_workspace_draft
- bind_workspace_to_scenario

Functions NOT in this module:

- record_workspace_runtime      (stays in repository.py; runtime helper)
- runtime_guard_for_snapshot    (stays in repository.py; runtime guard)

Behavior is preserved exactly as it was in repository.py. The only
differences from the originals are:

1. TYPE_CHECKING forward-reference for WorkspaceStateRecord and ScenarioRecord
   to avoid circular imports. The class objects themselves are still
   resolved at runtime via lazy import inside function bodies where needed.
2. Module-level import of helper functions (_now_utc, _to_json) is local
   to this module.

Public surface preserved:

- app.persistence.repository.save_workspace_state     ✓
- app.persistence.repository.get_workspace_state      ✓
- app.persistence.repository.discard_workspace_draft  ✓
- app.persistence.repository.bind_workspace_to_scenario ✓
- app.persistence.repository.WorkspaceStateRecord     (re-exported)
"""
from __future__ import annotations

import hashlib
import json
import uuid
from datetime import datetime
from typing import TYPE_CHECKING, Any, Mapping, Optional

from app.persistence.db import get_cursor
from app.persistence._helpers import _now_utc, _to_json


def _draft_content_hash(draft_snapshot: dict) -> str:
    """Stable SHA-256 over the serialised draft snapshot.

    Fallback hash for rows that pre-date the draft_content_hash column.
    The V2 edit pipeline stores pis.content_hash instead (passed explicitly
    via the draft_content_hash parameter of save_workspace_state / v2_atomic_draft_update).
    """
    raw = json.dumps(draft_snapshot or {}, sort_keys=True, ensure_ascii=True)
    return hashlib.sha256(raw.encode()).hexdigest()

if TYPE_CHECKING:
    from app.model_v2.persistence import ModelV2WorkingState
    from app.persistence.records import ScenarioRecord, WorkspaceStateRecord


def _model_v2_state_json(
    model_v2_working_state: "Optional[ModelV2WorkingState]",
    existing_json: Optional[str],
) -> str:
    """Resolve the persisted Model V2 Working Copy payload for a save.

    None (the default for every legacy caller) merge-preserves the existing
    payload — a legacy save can never invent or erase V2 selections. A
    provided state is validated and canonically serialized (fail closed)."""
    if model_v2_working_state is None:
        return existing_json or ""
    from app.model_v2.persistence import working_state_to_json
    return working_state_to_json(model_v2_working_state)


def _payload_working_copy_ref(raw_payload: str) -> str:
    """Extract the working_copy_ref of a persisted V2 payload (fail closed
    on anything unreadable). Used to police project_code changes that would
    otherwise silently retain a payload bound to another working copy."""
    import json as _json

    from app.model_v2.persistence import ModelV2PersistenceError
    try:
        payload = _json.loads(raw_payload)
    except ValueError as exc:
        raise ModelV2PersistenceError(
            f"MODEL_V2_PERSISTENCE_MALFORMED: persisted Model V2 payload is "
            f"not valid JSON ({exc})"
        ) from None
    if not isinstance(payload, dict) \
            or not isinstance(payload.get("working_copy_ref"), str):
        raise ModelV2PersistenceError(
            "MODEL_V2_PERSISTENCE_MALFORMED: persisted Model V2 payload "
            "carries no readable working_copy_ref"
        )
    return payload["working_copy_ref"]


# -----------------------------------------------------------------
# get_workspace_state
# -----------------------------------------------------------------

def get_workspace_state(user_id: str, project_id: str) -> "Optional[WorkspaceStateRecord]":
    from app.persistence.records import WorkspaceStateRecord
    with get_cursor() as cur:
        cur.execute(
            "SELECT * FROM workspace_states WHERE user_id=? AND project_id=?",
            (user_id, project_id),
        )
        row = cur.fetchone()
    return WorkspaceStateRecord.from_row(row) if row else None


# -----------------------------------------------------------------
# Model V2 Working Copy selections (Workflow 07)
#
# The V2 selection state is WORKING COPY input state, persisted on the
# workspace row (1:1 per user+project) exactly like the draft snapshot it
# composes alongside. The persisted state is bound to the workspace's
# project_code (the working-copy identity used by existing runtime
# semantics): writes with a foreign working_copy_ref fail closed, and a
# read whose stored ref no longer matches the workspace fails closed
# instead of silently composing another project's economics.
# -----------------------------------------------------------------

def get_workspace_model_v2_state(
    user_id: str,
    project_id: str,
) -> "Optional[ModelV2WorkingState]":
    """Load the persisted Model V2 Working Copy state (None = no V2
    selections — the legacy state). Malformed payloads and identity
    mismatches fail closed."""
    from app.model_v2.persistence import (
        ModelV2PersistenceError,
        working_state_from_json,
    )

    record = get_workspace_state(user_id, project_id)
    if record is None or not record.model_v2_working_state_json:
        return None
    state = working_state_from_json(record.model_v2_working_state_json)
    if state is None:
        return None
    if state.working_copy_ref != record.project_code:
        raise ModelV2PersistenceError(
            f"MODEL_V2_WORKING_COPY_REF_MISMATCH: persisted Model V2 state "
            f"is bound to working_copy_ref {state.working_copy_ref!r} but "
            f"the workspace belongs to project_code {record.project_code!r}; "
            "refusing to compose another working copy's economics"
        )
    return state


def set_workspace_model_v2_state(
    *,
    user_id: str,
    project_id: str,
    state: "ModelV2WorkingState",
) -> "WorkspaceStateRecord":
    """Persist (or replace) the Model V2 Working Copy selections.

    The state's working_copy_ref must equal the workspace's project_code
    (fail closed otherwise). The write is a narrow single-column UPDATE —
    no other column on the row is read or rewritten, so a concurrent
    draft/row mutation can never be silently reverted by this call."""
    from app.model_v2.persistence import (
        ModelV2PersistenceError,
        working_state_to_json,
    )
    from app.persistence._helpers import _now_utc

    record = get_workspace_state(user_id, project_id)
    if record is None:
        raise ValueError(
            f"WORKSPACE_NOT_FOUND: no workspace state for user={user_id!r} "
            f"project_id={project_id!r}; Model V2 selections attach to an "
            "existing working copy")
    state.validate()
    if state.working_copy_ref != record.project_code:
        raise ModelV2PersistenceError(
            f"MODEL_V2_WORKING_COPY_REF_MISMATCH: state is bound to "
            f"working_copy_ref {state.working_copy_ref!r} but the workspace "
            f"belongs to project_code {record.project_code!r}"
        )
    payload_json = working_state_to_json(state)
    with get_cursor() as cur:
        cur.execute(
            "UPDATE workspace_states SET model_v2_working_state_json=?, "
            "updated_at=? WHERE workspace_id=? AND user_id=?",
            (payload_json, _now_utc().isoformat(), record.workspace_id, user_id),
        )
    return get_workspace_state(user_id, project_id)


def clear_workspace_model_v2_state(
    *,
    user_id: str,
    project_id: str,
) -> "WorkspaceStateRecord":
    """Explicitly remove the Model V2 Working Copy selections (back to the
    exact legacy absence). Everything else on the row is preserved."""
    record = get_workspace_state(user_id, project_id)
    if record is None:
        raise ValueError(
            f"WORKSPACE_NOT_FOUND: no workspace state for user={user_id!r} "
            f"project_id={project_id!r}")
    from app.persistence._helpers import _now_utc
    with get_cursor() as cur:
        cur.execute(
            "UPDATE workspace_states SET model_v2_working_state_json='', "
            "updated_at=? WHERE workspace_id=? AND user_id=?",
            (_now_utc().isoformat(), record.workspace_id, user_id),
        )
    return get_workspace_state(user_id, project_id)


# -----------------------------------------------------------------
# save_workspace_state
# -----------------------------------------------------------------

def _prove_history_commit_correlation(
    payload, *, user_id, project_id, project_code,
    last_runtime_snapshot_id, last_runtime_origin,
    last_runtime_scenario_id, active_scenario_id, active_scenario_name,
):
    """Correction A1: the history payload must describe EXACTLY the Last
    Run this save commits. Any disagreement is a typed fail-closed error
    before the workspace row is mutated - never silently rewritten."""
    from app.persistence.run_history_repository import (
        RunHistoryError as _RunHistoryError,
    )

    mismatches = []

    def _eq(field, expected):
        if payload.get(field) != expected:
            mismatches.append(
                f"{field}: payload {payload.get(field)!r} != commit {expected!r}"
            )

    _eq("user_id", user_id)
    _eq("project_id", project_id)
    _eq("project_code", project_code)
    _eq("runtime_snapshot_id", last_runtime_snapshot_id)
    _eq("runtime_origin", last_runtime_origin)
    _eq("last_runtime_scenario_id", last_runtime_scenario_id)
    _eq("active_scenario_id", active_scenario_id)
    _eq("active_scenario_name", active_scenario_name)
    if mismatches:
        raise _RunHistoryError(
            "RUN_HISTORY_COMMIT_CORRELATION_MISMATCH: the run history "
            "payload does not describe the Last Run being committed - "
            + "; ".join(mismatches)
        )


def save_workspace_state(
    *,
    user_id: str,
    project_id: str,
    project_code: str,
    draft_snapshot: dict[str, Any],
    saved_snapshot: dict[str, Any],
    governance_state: Optional[dict[str, Any]] = None,
    active_scenario_id: Optional[str] = None,
    active_scenario_name: Optional[str] = None,
    last_runtime_snapshot: Optional[dict[str, Any]] = None,
    last_runtime_summary: Optional[dict[str, Any]] = None,
    last_runtime_snapshot_id: Optional[str] = None,
    last_runtime_origin: Optional[str] = None,
    last_runtime_scenario_id: Optional[str] = None,
    # Workbook V2 PR 3: full schedule payloads — DB is now authoritative.
    last_financial_statements: Optional[dict[str, Any]] = None,
    last_debt_schedule: Optional[dict[str, Any]] = None,
    last_tax_schedule: Optional[dict[str, Any]] = None,
    last_distribution_schedule: Optional[dict[str, Any]] = None,
    last_sponsor_schedule: Optional[dict[str, Any]] = None,
    dirty: bool = False,
    replay_metadata: Optional[dict[str, Any]] = None,
    last_runtime_at: Optional[datetime] = None,
    # Workbook V2 PR 7: caller-supplied content hash for atomic CAS.
    # Pass pis.content_hash here when saving from the V2 edit pipeline.
    # Falls back to a raw JSON hash if not provided (for legacy callers).
    v2_draft_content_hash: Optional[str] = None,
    # Workflow 07: Model V2 Working Copy selections (typed by
    # app.model_v2.persistence). None keeps the existing persisted state
    # (legacy saves never invent or erase V2 state); pass a
    # ModelV2WorkingState to write it — or use
    # clear_workspace_model_v2_state to remove it explicitly.
    model_v2_working_state: "Optional[ModelV2WorkingState]" = None,
    # Run History V1: a fully-validated history payload (built by
    # app.persistence.run_history_repository.prepare_run_history_payload).
    # When provided, the immutable history row is appended INSIDE this
    # save's transaction so a legacy Last Run promotion and its history
    # append commit or roll back together. Ordinary (non-run) saves never
    # pass it, so they never append history.
    run_history_payload: "Optional[Mapping[str, Any]]" = None,
) -> "WorkspaceStateRecord":
    from app.persistence.records import WorkspaceStateRecord
    now = _now_utc()
    governance_state = governance_state or {}
    replay_metadata = dict(replay_metadata or {})
    # V2-only snapshot keys that legacy save paths never include.
    # These must be preserved from the existing draft when the incoming
    # draft_snapshot omits or blanks them — prevents legacy saves from
    # silently erasing V2-set Tax field values.
    _V2_ONLY_SNAPSHOT_KEYS = frozenset({"tax_corporate_rate_pct", "tax_loss_carryforward_years"})

    existing = get_workspace_state(user_id, project_id)
    # Correction A (A3): EVERY write path that stores a supplied Model V2
    # state enforces the same working-copy identity rule as
    # set_workspace_model_v2_state — a foreign state fails closed before
    # any mutation.
    if model_v2_working_state is not None:
        from app.model_v2.persistence import ModelV2PersistenceError as _MV2Err
        if model_v2_working_state.working_copy_ref != project_code:
            raise _MV2Err(
                f"MODEL_V2_WORKING_COPY_REF_MISMATCH: supplied Model V2 "
                f"state is bound to working_copy_ref "
                f"{model_v2_working_state.working_copy_ref!r} but this save "
                f"targets project_code {project_code!r}"
            )
        model_v2_working_state.validate()
    # Correction A (A3): a project_code change must never silently retain a
    # merge-preserved V2 payload bound to the OLD working-copy identity —
    # require an explicit correctly rebound state (or an explicit clear).
    if existing is not None and project_code != existing.project_code \
            and model_v2_working_state is None \
            and existing.model_v2_working_state_json:
        _prev_ref = _payload_working_copy_ref(
            existing.model_v2_working_state_json)
        if _prev_ref != project_code:
            from app.model_v2.persistence import ModelV2PersistenceError as _MV2Err
            raise _MV2Err(
                f"MODEL_V2_WORKING_COPY_REF_REBIND_REQUIRED: project_code "
                f"changed {existing.project_code!r} -> {project_code!r} but "
                f"the persisted Model V2 payload is bound to {_prev_ref!r}; "
                "clear_workspace_model_v2_state or save an explicitly "
                "rebound Model V2 state with this save"
            )
    if existing is not None:
        workspace_id = existing.workspace_id
        created_at = existing.created_at
        # Merge-preserve: copy any non-empty V2-only key from existing draft
        # when the incoming draft_snapshot is absent/blank for that key.
        if existing.draft_snapshot:
            for _k in _V2_ONLY_SNAPSHOT_KEYS:
                _existing_val = existing.draft_snapshot.get(_k)
                _incoming_val = draft_snapshot.get(_k)
                _incoming_blank = not str(_incoming_val or "").strip()
                _existing_nonempty = bool(str(_existing_val or "").strip())
                if _incoming_blank and _existing_nonempty:
                    draft_snapshot = {**draft_snapshot, _k: _existing_val}
        if last_runtime_snapshot is None:
            last_runtime_snapshot = existing.last_runtime_snapshot
        if last_runtime_summary is None:
            last_runtime_summary = existing.last_runtime_summary
        if last_runtime_snapshot_id is None:
            last_runtime_snapshot_id = existing.last_runtime_snapshot_id
        if last_runtime_origin is None:
            last_runtime_origin = existing.last_runtime_origin
        if last_runtime_scenario_id is None:
            last_runtime_scenario_id = existing.last_runtime_scenario_id
        if last_runtime_at is None:
            last_runtime_at = existing.last_runtime_at
        if last_financial_statements is None:
            last_financial_statements = existing.last_financial_statements
        if last_debt_schedule is None:
            last_debt_schedule = existing.last_debt_schedule
        if last_tax_schedule is None:
            last_tax_schedule = existing.last_tax_schedule
        if last_distribution_schedule is None:
            last_distribution_schedule = existing.last_distribution_schedule
        if last_sponsor_schedule is None:
            last_sponsor_schedule = existing.last_sponsor_schedule
        if not governance_state:
            governance_state = existing.governance_state
        merged_replay_metadata = dict(existing.replay_metadata or {})
        merged_replay_metadata.update(replay_metadata)
        replay_metadata = merged_replay_metadata
        _dch = v2_draft_content_hash or _draft_content_hash(draft_snapshot or {})
        _model_v2_json = _model_v2_state_json(
            model_v2_working_state, existing.model_v2_working_state_json)
        if run_history_payload is not None:
            _prove_history_commit_correlation(
                run_history_payload,
                user_id=user_id,
                project_id=project_id,
                project_code=project_code,
                last_runtime_snapshot_id=last_runtime_snapshot_id,
                last_runtime_origin=last_runtime_origin,
                last_runtime_scenario_id=last_runtime_scenario_id,
                active_scenario_id=active_scenario_id,
                active_scenario_name=active_scenario_name,
            )
        with get_cursor() as cur:
            if run_history_payload is not None:
                # Run History V1: the connection runs in autocommit mode, so
                # an atomic history append needs an explicit transaction -
                # a history failure must roll back the Last Run promotion.
                cur.execute("BEGIN IMMEDIATE")
            cur.execute(
                """
                UPDATE workspace_states
                SET project_code=?, active_scenario_id=?, active_scenario_name=?, draft_snapshot_json=?,
                    saved_snapshot_json=?, last_runtime_snapshot_json=?, last_runtime_summary_json=?,
                    last_runtime_snapshot_id=?, last_runtime_origin=?, last_runtime_scenario_id=?,
                    last_financial_statements_json=?, last_debt_schedule_json=?,
                    last_tax_schedule_json=?, last_distribution_schedule_json=?,
                    last_sponsor_schedule_json=?, draft_content_hash=?,
                    dirty=?, governance_state_json=?, replay_metadata_json=?, updated_at=?, last_runtime_at=?,
                    model_v2_working_state_json=?
                WHERE workspace_id=? AND user_id=?
                """,
                (
                    project_code,
                    active_scenario_id,
                    active_scenario_name,
                    _to_json(draft_snapshot or {}),
                    _to_json(saved_snapshot or {}),
                    _to_json(last_runtime_snapshot or {}),
                    _to_json(last_runtime_summary or {}),
                    last_runtime_snapshot_id,
                    last_runtime_origin,
                    last_runtime_scenario_id,
                    _to_json(last_financial_statements or {}),
                    _to_json(last_debt_schedule or {}),
                    _to_json(last_tax_schedule or {}),
                    _to_json(last_distribution_schedule or {}),
                    _to_json(last_sponsor_schedule or {}),
                    _dch,
                    int(dirty),
                    _to_json(governance_state),
                    _to_json(replay_metadata),
                    now.isoformat(),
                    last_runtime_at.isoformat() if last_runtime_at else None,
                    _model_v2_json,
                    workspace_id,
                    user_id,
                ),
            )
            if run_history_payload is not None:
                from app.persistence.run_history_repository import (
                    append_run_history_cursor as _append_history,
                )
                _append_history(cur, run_history_payload)
                cur.execute("COMMIT")
    else:
        workspace_id = uuid.uuid4().hex[:16]
        created_at = now
        replay_metadata.setdefault("workspace_id", workspace_id)
        _model_v2_json = _model_v2_state_json(model_v2_working_state, "")
        if run_history_payload is not None:
            _prove_history_commit_correlation(
                run_history_payload,
                user_id=user_id,
                project_id=project_id,
                project_code=project_code,
                last_runtime_snapshot_id=last_runtime_snapshot_id,
                last_runtime_origin=last_runtime_origin,
                last_runtime_scenario_id=last_runtime_scenario_id,
                active_scenario_id=active_scenario_id,
                active_scenario_name=active_scenario_name,
            )
        with get_cursor() as cur:
            if run_history_payload is not None:
                cur.execute("BEGIN IMMEDIATE")
            cur.execute(
                """
                INSERT INTO workspace_states (
                    workspace_id, project_id, user_id, project_code, active_scenario_id, active_scenario_name,
                    draft_snapshot_json, saved_snapshot_json, last_runtime_snapshot_json, last_runtime_summary_json,
                    last_runtime_snapshot_id, last_runtime_origin, last_runtime_scenario_id,
                    last_financial_statements_json, last_debt_schedule_json, last_tax_schedule_json,
                    last_distribution_schedule_json, last_sponsor_schedule_json, draft_content_hash,
                    dirty, governance_state_json, replay_metadata_json, created_at, updated_at, last_runtime_at,
                    model_v2_working_state_json
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    workspace_id,
                    project_id,
                    user_id,
                    project_code,
                    active_scenario_id,
                    active_scenario_name,
                    _to_json(draft_snapshot or {}),
                    _to_json(saved_snapshot or {}),
                    _to_json(last_runtime_snapshot or {}),
                    _to_json(last_runtime_summary or {}),
                    last_runtime_snapshot_id,
                    last_runtime_origin,
                    last_runtime_scenario_id,
                    _to_json(last_financial_statements or {}),
                    _to_json(last_debt_schedule or {}),
                    _to_json(last_tax_schedule or {}),
                    _to_json(last_distribution_schedule or {}),
                    _to_json(last_sponsor_schedule or {}),
                    v2_draft_content_hash or _draft_content_hash(draft_snapshot or {}),
                    int(dirty),
                    _to_json(governance_state),
                    _to_json(replay_metadata),
                    created_at.isoformat(),
                    now.isoformat(),
                    last_runtime_at.isoformat() if last_runtime_at else None,
                    _model_v2_json,
                ),
            )
            if run_history_payload is not None:
                from app.persistence.run_history_repository import (
                    append_run_history_cursor as _append_history,
                )
                _append_history(cur, run_history_payload)
                cur.execute("COMMIT")

    return WorkspaceStateRecord(
        workspace_id=workspace_id,
        project_id=project_id,
        user_id=user_id,
        project_code=project_code,
        active_scenario_id=active_scenario_id,
        active_scenario_name=active_scenario_name,
        draft_snapshot=draft_snapshot or {},
        saved_snapshot=saved_snapshot or {},
        last_runtime_snapshot=last_runtime_snapshot or {},
        last_runtime_summary=last_runtime_summary or {},
        last_runtime_snapshot_id=last_runtime_snapshot_id,
        last_runtime_origin=last_runtime_origin,
        last_runtime_scenario_id=last_runtime_scenario_id,
        last_financial_statements=last_financial_statements or {},
        last_debt_schedule=last_debt_schedule or {},
        last_tax_schedule=last_tax_schedule or {},
        last_distribution_schedule=last_distribution_schedule or {},
        last_sponsor_schedule=last_sponsor_schedule or {},
        dirty=dirty,
        governance_state=governance_state,
        replay_metadata=replay_metadata,
        created_at=created_at,
        updated_at=now,
        last_runtime_at=last_runtime_at,
        model_v2_working_state_json=_model_v2_json,
    )


# -----------------------------------------------------------------
# bind_workspace_to_scenario
# -----------------------------------------------------------------

def bind_workspace_to_scenario(
    user_id: str,
    project_id: str,
    project_code: str,
    record: "ScenarioRecord",
    governance_state: Optional[dict[str, Any]] = None,
    replay_metadata: Optional[dict[str, Any]] = None,
) -> "WorkspaceStateRecord":
    return save_workspace_state(
        user_id=user_id,
        project_id=project_id,
        project_code=project_code,
        active_scenario_id=record.scenario_id,
        active_scenario_name=record.scenario_name,
        draft_snapshot=record.snapshot,
        saved_snapshot=record.snapshot,
        dirty=False,
        governance_state=governance_state or record.governance_state,
        replay_metadata=replay_metadata,
    )


# -----------------------------------------------------------------
# discard_workspace_draft
# -----------------------------------------------------------------

def discard_workspace_draft(user_id: str, project_id: str) -> "Optional[WorkspaceStateRecord]":
    record = get_workspace_state(user_id, project_id)
    if record is None:
        return None
    return save_workspace_state(
        user_id=user_id,
        project_id=project_id,
        project_code=record.project_code,
        active_scenario_id=record.active_scenario_id,
        active_scenario_name=record.active_scenario_name,
        draft_snapshot=record.saved_snapshot,
        saved_snapshot=record.saved_snapshot,
        last_runtime_snapshot=record.last_runtime_snapshot,
        last_runtime_summary=record.last_runtime_summary,
        last_runtime_snapshot_id=record.last_runtime_snapshot_id,
        last_runtime_origin=record.last_runtime_origin,
        last_runtime_scenario_id=record.last_runtime_scenario_id,
        last_financial_statements=record.last_financial_statements,
        last_debt_schedule=record.last_debt_schedule,
        last_tax_schedule=record.last_tax_schedule,
        last_distribution_schedule=record.last_distribution_schedule,
        last_sponsor_schedule=record.last_sponsor_schedule,
        dirty=False,
        governance_state=record.governance_state,
        replay_metadata=record.replay_metadata,
        last_runtime_at=record.last_runtime_at,
    )


# -----------------------------------------------------------------
# v2_atomic_draft_update
# -----------------------------------------------------------------

def v2_atomic_draft_update(
    *,
    user_id: str,
    project_id: str,
    expected_content_hash: str,
    field_id: str,
    typed_value: Any,
) -> "Optional[WorkspaceStateRecord]":
    """Atomic compare-and-swap for Workbook V2 single-field draft edits.

    All steps execute inside a single ``BEGIN EXCLUSIVE`` transaction:

    1. Read ``draft_snapshot_json`` from the DB.
    2. Build a ``ProjectInputSet`` from that snapshot and compute its
       canonical ``content_hash``.
    3. Compare the canonical hash against ``expected_content_hash``.
       Return ``None`` (stale) on mismatch — the caller raises StaleContentError.
    4. Apply ``field_id`` / ``typed_value`` to that ``ProjectInputSet``
       via ``with_value()``.
    5. Persist the resulting snapshot and the new canonical content hash.

    The snapshot used to build the updated ProjectInputSet is always the one
    read inside the transaction, never a pre-transaction copy.  This prevents
    a lost update when a concurrent write (including legacy non-CAS saves)
    changes the draft between the caller's read and this write.

    The stored ``draft_content_hash`` column is **not used for comparison**
    (it may be a legacy raw-JSON hash on rows that pre-date this pipeline).
    Only the canonical hash derived from the persisted snapshot is authoritative.
    On success ``draft_content_hash`` is always updated to the new canonical
    ``pis.content_hash``, migrating legacy rows in place.

    Returns the updated WorkspaceStateRecord on success, or None on stale.
    """
    from app.persistence.db import get_connection
    from app.persistence.records import WorkspaceStateRecord
    from app.workbook.input_set import ProjectInputSet
    from app.workbook.registry import WORKBOOK

    import json as _json

    now = _now_utc()
    conn = get_connection()
    cur = None
    try:
        # Exclusive lock: prevents any concurrent read or write until COMMIT/ROLLBACK.
        conn.execute("BEGIN EXCLUSIVE")
        cur = conn.cursor()

        cur.execute(
            "SELECT * FROM workspace_states WHERE user_id=? AND project_id=?",
            (user_id, project_id),
        )
        row = cur.fetchone()
        if row is None:
            conn.execute("ROLLBACK")
            return None

        # STAB-1B: Build composite workbook identity from the persisted snapshot
        # (scalar + CAPEX rows + OPEX rows + scenario) inside the already-open
        # BEGIN EXCLUSIVE cursor, then compare the composite hash against the
        # client-supplied expected_content_hash.
        # Legacy scalar-only tokens (no _schema:composite_v1 discriminator) will
        # never match composite hashes, so they are correctly rejected with a
        # stale-content 409 — the client refreshes and receives a composite token.
        from app.workbook.workbook_identity import assemble_transactional

        identity = assemble_transactional(
            draft_snapshot_json=row["draft_snapshot_json"] or "{}",
            project_id=project_id,
            user_id=user_id,
            active_scenario_id=row["active_scenario_id"],
            active_scenario_name=row["active_scenario_name"],
            cursor=cur,
            workbook_version=WORKBOOK.version,
        )

        if identity.composite_hash != expected_content_hash:
            conn.execute("ROLLBACK")
            return None  # stale — caller raises StaleContentError

        # Apply the validated update to the snapshot read inside the transaction.
        row_snapshot = _json.loads(row["draft_snapshot_json"] or "{}")
        current_pis = ProjectInputSet.from_snapshot(row_snapshot, workbook=WORKBOOK)
        from app.workbook.multisenior_config import (
            FIELD_ID as f3_field, SNAPSHOT_KEY as f3_key, validate_transition,
            parse_state, apply_state,
        )
        if field_id == f3_field or row_snapshot.get(f3_key):
            scope = "base"
            if row["active_scenario_id"]:
                cur.execute("SELECT * FROM scenarios WHERE scenario_id=? AND user_id=? AND project_id=?",
                    (row["active_scenario_id"], user_id, project_id))
                scenario = cur.fetchone()
                if scenario is None or scenario["archived"]:
                    from finco_core.inputs.financing_instruments import FinancingError
                    raise FinancingError("F3_SELECTED_SCENARIO_UNAVAILABLE")
                scope = "base" if scenario["is_base_case"] else row["active_scenario_id"]
            if field_id == f3_field:
                validate_transition(row_snapshot.get(f3_key), typed_value, scope)
            else:
                entry = parse_state(row_snapshot.get(f3_key))["scopes"].get(scope)
                # Gearing and covenant thresholds remain project constraints;
                # competing single-Senior/SHL/reserve editors do not own terms.
                if entry and entry["activation"] and field_id.startswith("debt.") and field_id not in {
                    "debt.senior.gearing_pct", "debt.senior.lockup_dscr", "debt.senior.min_llcr"}:
                    from finco_core.inputs.financing_instruments import FinancingError
                    raise FinancingError("F3_COMPETING_FINANCING_EDITOR_REJECTED")
        updated_pis = current_pis.with_value(field_id, typed_value)
        if field_id == f3_field:
            # Validate the effective project boundary inside the same CAS. A
            # proposal remains inert; activation requires the release gate.
            apply_state(updated_pis.to_projectinputs(), typed_value, scope,
                bankability_raw=row_snapshot.get("bankability_config_json"))
        new_snapshot = updated_pis.to_snapshot()

        # Re-assemble composite identity after scalar mutation (rows/scenario unchanged).
        new_identity = assemble_transactional(
            draft_snapshot_json=_to_json(new_snapshot),
            project_id=project_id,
            user_id=user_id,
            active_scenario_id=row["active_scenario_id"],
            active_scenario_name=row["active_scenario_name"],
            cursor=cur,
            workbook_version=WORKBOOK.version,
        )
        new_content_hash = new_identity.composite_hash

        cur.execute(
            """
            UPDATE workspace_states
            SET draft_snapshot_json=?, draft_content_hash=?, dirty=1, updated_at=?
            WHERE workspace_id=? AND user_id=?
            """,
            (
                _to_json(new_snapshot),
                new_content_hash,
                now.isoformat(),
                row["workspace_id"],
                user_id,
            ),
        )
        conn.execute("COMMIT")

        cur.execute(
            "SELECT * FROM workspace_states WHERE user_id=? AND project_id=?",
            (user_id, project_id),
        )
        updated_row = cur.fetchone()
        return WorkspaceStateRecord.from_row(updated_row) if updated_row else None
    except Exception:
        try:
            conn.execute("ROLLBACK")
        except Exception:
            pass
        raise
    finally:
        if cur is not None:
            cur.close()
        conn.close()


# mark_workspace_dirty
# -----------------------------------------------------------------

def update_composite_hash_cursor(
    cur: Any,
    *,
    user_id: str,
    project_id: str,
    composite_hash: str,
    now_iso: str,
) -> bool:
    """Set dirty=1 and update draft_content_hash using an existing cursor.

    STAB-1B: used by CAPEX/OPEX row commands after a successful mutation so
    the workspace record carries the new composite identity token.  Must be
    called inside the same exclusive transaction as the row mutation.

    Returns True if the workspace row was found and updated, False otherwise.
    """
    cur.execute(
        """
        UPDATE workspace_states
        SET dirty=1, draft_content_hash=?, updated_at=?
        WHERE user_id=? AND project_id=?
        """,
        (composite_hash, now_iso, user_id, project_id),
    )
    return cur.rowcount > 0


class V2RunCommitConflictError(Exception):
    """Raised when the final CAS check fails in v2_atomic_run_commit.

    The composite identity changed between the initial pre-engine check
    and the post-engine commit window.  The run result is discarded; the
    caller must return a truthful conflict response without mutating state.
    """


def v2_atomic_run_commit(
    *,
    user_id: str,
    project_id: str,
    project_code: str,
    expected_composite_hash: str,
    runtime_snapshot_id: str,
    runtime_origin: str,
    runtime_summary: dict,
    financial_statements,
    debt_schedule,
    tax_schedule,
    distribution_schedule,
    sponsor_schedule,
    active_scenario_id,
    active_scenario_name,
    ran_at,
    last_runtime_scenario_id=None,
    replay_metadata: "dict | None" = None,
    integrity_evidence: "dict | None" = None,
    # Workflow 07: optional Model V2 run binding (payload built by
    # app.model_v2.persistence.build_run_binding_payload). When provided it
    # is validated (fail closed) and embedded under the "model_v2" key of
    # last_runtime_identity_json INSIDE this transaction — the Last Run
    # then proves which V2 Working Copy economic state produced it. The
    # workbook composite hash remains the canonical input identity; the
    # V2 composition hash is never promoted to a run identity.
    model_v2_run_binding: "Mapping[str, Any] | None" = None,
) -> "WorkspaceStateRecord":
    """Atomic V2 run commit: final CAS + promote draft → saved + clear dirty.

    All steps execute inside a single BEGIN EXCLUSIVE transaction:

    1. Re-read the workspace state.
    2. Re-assemble composite identity from the current draft state.
    3. Final CAS: if composite_hash != expected_composite_hash raise
       V2RunCommitConflictError without mutating anything.
    4. Promote draft_snapshot → saved_snapshot.
    5. Persist all runtime schedule payloads, summary, and metadata.
    6. Set dirty=False.
    7. COMMIT.

    Raises V2RunCommitConflictError on hash mismatch (another tab edited
    the workbook while the engine was running).  All other exceptions
    propagate unchanged; the caller must not partially commit on error.
    """
    from app.persistence.db import get_connection
    from app.persistence.records import WorkspaceStateRecord
    from app.workbook.workbook_identity import assemble_transactional
    from app.workbook.registry import WORKBOOK
    import json as _json

    now = _now_utc()
    conn = get_connection()
    cur = None
    try:
        conn.execute("BEGIN EXCLUSIVE")
        cur = conn.cursor()

        cur.execute(
            "SELECT * FROM workspace_states WHERE user_id=? AND project_id=?",
            (user_id, project_id),
        )
        row = cur.fetchone()
        if row is None:
            conn.execute("ROLLBACK")
            raise V2RunCommitConflictError("Workspace not found during run commit.")

        # Final CAS: re-derive composite hash from current draft state.
        identity = assemble_transactional(
            draft_snapshot_json=row["draft_snapshot_json"] or "{}",
            project_id=project_id,
            user_id=user_id,
            active_scenario_id=row["active_scenario_id"],
            active_scenario_name=row["active_scenario_name"],
            cursor=cur,
            workbook_version=WORKBOOK.version,
        )
        if identity.composite_hash != expected_composite_hash:
            conn.execute("ROLLBACK")
            raise V2RunCommitConflictError(
                f"Workbook changed during engine run "
                f"(expected {expected_composite_hash[:8]}…, "
                f"found {identity.composite_hash[:8]}…). "
                "Please run again."
            )

        # Promote draft → saved; clear dirty.
        draft_snapshot = _json.loads(row["draft_snapshot_json"] or "{}")

        # F07-B Correction B: persist run-bound composite identity so canonical
        # export can reproduce the exact effective inputs without re-reading
        # mutable live tables (CAPEX/OPEX rows, scenario record).
        _identity_payload = {
            "workbook_version": WORKBOOK.version,
            "capex_rows": [
                {
                    "sub_line_id": r.sub_line_id,
                    "parent_category_code": r.parent_category_code,
                    "amount_keur": r.amount_keur,
                }
                for r in identity.capex_rows
            ],
            "opex_rows": [
                {
                    "sub_line_id": r.sub_line_id,
                    "parent_group_code": r.parent_group_code,
                    "business_code": r.business_code,
                    "amount_keur": r.amount_keur,
                    "inflation_pct": r.inflation_pct,
                }
                for r in identity.opex_rows
            ],
            "scenario_overrides": dict(identity.scenario.overrides or {}),
            "scenario_name": identity.scenario.scenario_name,
            "composite_hash": identity.composite_hash,
        }
        # OPEX fold authority: record which seeded reference items this Run's OPEX
        # fold replaced, from immutable seed provenance only.  Canonical export
        # replays the SAME fold from this record; a Run without it used the
        # earlier fold and is reported unavailable/stale rather than guessed.
        try:
            from app.persistence.opex_sub_lines import list_sub_lines_for_project as _list_opex
            from app.services.opex_sub_lines_integration import opex_fold_provenance as _opex_prov
            _identity_payload["opex_fold"] = _opex_prov(
                _list_opex(cur, project_id, include_inactive=True)
            )
        except Exception as _exc:  # fail closed
            conn.execute("ROLLBACK")
            raise V2RunCommitConflictError(
                f"OPEX fold authority could not be captured for run identity: {_exc}"
            ) from _exc
        # Typed contingency authority (C.13 / B.13): capture the EFFECTIVE pct
        # (scenario override beats project value) so canonical export replays the
        # same economics even if the authority is edited after the run.
        try:
            from app.contingency_authority import resolve_pct as _resolve_cont_pct
            cur.execute(
                "SELECT replay_metadata_json FROM projects WHERE project_id=?",
                (project_id,),
            )
            _prow = cur.fetchone()
            _proj_meta = _json.loads((_prow["replay_metadata_json"] if _prow else "{}") or "{}")
            _cap_pct, _cap_src = _resolve_cont_pct(_proj_meta, identity.scenario.overrides, "capex")
            _ox_pct, _ox_src = _resolve_cont_pct(_proj_meta, identity.scenario.overrides, "opex")
            if _cap_pct is not None or _ox_pct is not None:
                _identity_payload["contingency_authority"] = {
                    "capex_pct": _cap_pct, "capex_source": _cap_src,
                    "opex_pct": _ox_pct, "opex_source": _ox_src,
                }
        except Exception as _exc:  # fail closed: never silently drop an authority
            conn.execute("ROLLBACK")
            raise V2RunCommitConflictError(
                f"Contingency authority could not be captured for run identity: {_exc}"
            ) from _exc

        # Correction C: persist engine version at run commit time so the XLSX export
        # reads the version that CREATED this run, not the current export-time version.
        try:
            from financial_engine.version import ENGINE_VERSION as _EV
            _identity_payload["engine_version"] = str(_EV)
        except Exception:
            _identity_payload["engine_version"] = "NOT_AVAILABLE"

        # Workflow 07: bind the Model V2 economic state that produced this
        # run, atomically with the Last Run commit. Fail closed: an invalid
        # binding or a foreign working_copy_ref aborts the commit (rollback
        # via the generic handler below) — the prior successful Last Run is
        # never replaced by a partially identified run.
        if model_v2_run_binding is not None:
            from app.model_v2.persistence import (
                working_state_from_json as _decode_v2_state,
            )
            from app.model_v2.persistence import (
                validate_run_binding_payload as _validate_v2_binding,
            )
            _v2_binding = _validate_v2_binding(dict(model_v2_run_binding))
            if _v2_binding["working_copy_ref"] != row["project_code"]:
                raise ValueError(
                    f"MODEL_V2_RUN_BINDING_REF_MISMATCH: run binding is bound "
                    f"to working_copy_ref "
                    f"{_v2_binding['working_copy_ref']!r} but the workspace "
                    f"belongs to project_code {row['project_code']!r}"
                )
            if _v2_binding["snapshot_id"] != runtime_snapshot_id:
                raise ValueError(
                    f"MODEL_V2_RUN_BINDING_SNAPSHOT_MISMATCH: run binding "
                    f"correlates with snapshot "
                    f"{_v2_binding['snapshot_id']!r} but this commit is "
                    f"writing snapshot {runtime_snapshot_id!r}"
                )
            # Correction A (A1): the V2 Working Copy payload is NOT part of
            # the workbook composite hash, so a concurrent V2 edit during
            # the engine run would pass the composite CAS silently. Inside
            # the SAME exclusive transaction: decode the CURRENT persisted
            # V2 state and require its economic identity to still equal the
            # identity the run was composed from.
            _v2_raw = (row["model_v2_working_state_json"]
                       if "model_v2_working_state_json" in row.keys() else "") or ""
            try:
                _current_v2_state = _decode_v2_state(_v2_raw)
            except Exception as _exc:
                raise V2RunCommitConflictError(
                    "MODEL_V2_RUN_COMMIT_V2_STATE_UNREADABLE: the persisted "
                    f"Model V2 Working Copy state could not be decoded "
                    f"during run commit: {_exc}"
                ) from _exc
            if _current_v2_state is None:
                raise V2RunCommitConflictError(
                    "MODEL_V2_RUN_COMMIT_V2_STATE_MISSING: a Model V2 run "
                    "binding was supplied but the workspace carries no "
                    "persisted Model V2 state"
                )
            if _current_v2_state.working_copy_ref != row["project_code"]:
                raise V2RunCommitConflictError(
                    f"MODEL_V2_WORKING_COPY_REF_MISMATCH: persisted Model V2 "
                    f"state is bound to "
                    f"{_current_v2_state.working_copy_ref!r} but the "
                    f"workspace belongs to project_code "
                    f"{row['project_code']!r}"
                )
            _current_v2_identity = _current_v2_state.selection_digest()
            if _current_v2_identity != _v2_binding["economic_identity"]:
                raise V2RunCommitConflictError(
                    "MODEL_V2_RUN_COMMIT_STALE_V2_STATE: the persisted Model "
                    "V2 Working Copy state changed while the engine was "
                    f"running (run composed identity "
                    f"{_v2_binding['economic_identity'][:8]}…, current "
                    f"{_current_v2_identity[:8]}…); the run is discarded — "
                    "please re-run"
                )
            # Correction A (A2): the binding scenario must be the scenario
            # this commit actually persists for the Last Run
            # (last_runtime_scenario_id with the existing active_scenario_id
            # fallback). No new scenario naming convention is invented.
            _committed_scenario_id = (
                last_runtime_scenario_id
                if last_runtime_scenario_id is not None
                else active_scenario_id
            )
            if _v2_binding["scenario_id"] != _committed_scenario_id:
                raise ValueError(
                    f"MODEL_V2_RUN_BINDING_SCENARIO_MISMATCH: run binding "
                    f"names scenario {_v2_binding['scenario_id']!r} but this "
                    f"commit persists Last Run scenario "
                    f"{_committed_scenario_id!r}"
                )
            _identity_payload["model_v2"] = _v2_binding

        # Preserve existing replay_metadata when caller passes None; merge when provided.
        _existing_meta = _json.loads(row["replay_metadata_json"] or "{}")
        if replay_metadata is not None:
            _replay_meta_json = _json.dumps(replay_metadata, sort_keys=True)
        else:
            _replay_meta_json = _json.dumps(_existing_meta, sort_keys=True)

        cur.execute(
            """
            UPDATE workspace_states
            SET saved_snapshot_json=?,
                last_runtime_snapshot_json=?,
                last_runtime_summary_json=?,
                last_runtime_snapshot_id=?,
                last_runtime_origin=?,
                last_financial_statements_json=?,
                last_debt_schedule_json=?,
                last_tax_schedule_json=?,
                last_distribution_schedule_json=?,
                last_sponsor_schedule_json=?,
                last_integrity_evidence_json=?,
                active_scenario_id=?,
                active_scenario_name=?,
                last_runtime_scenario_id=?,
                dirty=0,
                any_run_committed=1,
                updated_at=?,
                last_runtime_at=?,
                last_runtime_composite_hash=?,
                last_runtime_identity_json=?,
                replay_metadata_json=?
            WHERE workspace_id=? AND user_id=?
            """,
            (
                _to_json(draft_snapshot),
                _to_json(draft_snapshot),
                _to_json(runtime_summary or {}),
                runtime_snapshot_id,
                runtime_origin,
                _to_json(financial_statements or {}),
                _to_json(debt_schedule or {}),
                _to_json(tax_schedule or {}),
                _to_json(distribution_schedule or {}),
                _to_json(sponsor_schedule or {}),
                _to_json(integrity_evidence or {}),
                active_scenario_id,
                active_scenario_name,
                last_runtime_scenario_id if last_runtime_scenario_id is not None else active_scenario_id,
                now.isoformat(),
                ran_at.isoformat() if hasattr(ran_at, "isoformat") else str(ran_at),
                identity.composite_hash,
                _json.dumps(_identity_payload, sort_keys=True),
                _replay_meta_json,
                row["workspace_id"],
                user_id,
            ),
        )
        # Run History V1: append the immutable successful-run ledger row
        # INSIDE the same exclusive transaction as the Last Run promotion.
        # If the append fails, the generic rollback below reverts the Last
        # Run promotion too - Last Run=C with History C missing (and the
        # inverse) is unrepresentable.
        from app.persistence.run_history_repository import (
            append_run_history_cursor as _append_history,
            prepare_run_history_payload as _prepare_history,
        )
        _history_payload = _prepare_history(
            user_id=user_id,
            project_id=project_id,
            project_code=project_code,
            runtime_snapshot_id=runtime_snapshot_id,
            runtime_origin=runtime_origin,
            ran_at=(
                ran_at.isoformat() if hasattr(ran_at, "isoformat")
                else str(ran_at)
            ),
            runtime_summary=runtime_summary or {},
            financial_statements=financial_statements or {},
            debt_schedule=debt_schedule or {},
            tax_schedule=tax_schedule or {},
            distribution_schedule=distribution_schedule or {},
            sponsor_schedule=sponsor_schedule or {},
            engine_version=_identity_payload.get("engine_version"),
            workbook_version=_identity_payload.get(
                "workbook_version", WORKBOOK.version
            ),
            composite_hash=identity.composite_hash,
            last_runtime_identity=_identity_payload,
            active_scenario_id=active_scenario_id,
            active_scenario_name=active_scenario_name,
            last_runtime_scenario_id=(
                last_runtime_scenario_id
                if last_runtime_scenario_id is not None
                else active_scenario_id
            ),
            integrity_evidence=integrity_evidence or {},
            replay_metadata=replay_metadata,
        )
        _append_history(cur, _history_payload)
        conn.execute("COMMIT")

        cur.execute(
            "SELECT * FROM workspace_states WHERE user_id=? AND project_id=?",
            (user_id, project_id),
        )
        updated_row = cur.fetchone()
        return WorkspaceStateRecord.from_row(updated_row) if updated_row else None
    except V2RunCommitConflictError:
        try:
            conn.execute("ROLLBACK")
        except Exception:
            pass
        raise
    except Exception:
        try:
            conn.execute("ROLLBACK")
        except Exception:
            pass
        raise
    finally:
        if cur is not None:
            cur.close()
        conn.close()


def mark_workspace_dirty_cursor(cur: Any, *, user_id: str, project_id: str) -> bool:
    """Set dirty=1 on the workspace row using an existing cursor.

    Intended for use inside an already-open exclusive transaction so the
    dirty-state update is atomic with the row mutation that triggered it.

    Returns True if the workspace row was found and updated, False if no
    workspace row exists for (user_id, project_id).

    Callers that perform Workbook V2 row mutations MUST treat a False
    return as a hard error and roll back the transaction.  A missing
    workspace row means the project has no initialised draft state, and
    committing a CAPEX mutation without recording the dirty flag would
    leave the workspace in a silently inconsistent state.
    """
    now = _now_utc().isoformat()
    cur.execute(
        "UPDATE workspace_states SET dirty=1, updated_at=? WHERE user_id=? AND project_id=?",
        (now, user_id, project_id),
    )
    return cur.rowcount > 0
