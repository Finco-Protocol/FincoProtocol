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
from typing import TYPE_CHECKING, Any, Optional

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
    from app.persistence.records import ScenarioRecord, WorkspaceStateRecord


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
# save_workspace_state
# -----------------------------------------------------------------

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
        with get_cursor() as cur:
            cur.execute(
                """
                UPDATE workspace_states
                SET project_code=?, active_scenario_id=?, active_scenario_name=?, draft_snapshot_json=?,
                    saved_snapshot_json=?, last_runtime_snapshot_json=?, last_runtime_summary_json=?,
                    last_runtime_snapshot_id=?, last_runtime_origin=?, last_runtime_scenario_id=?,
                    last_financial_statements_json=?, last_debt_schedule_json=?,
                    last_tax_schedule_json=?, last_distribution_schedule_json=?,
                    last_sponsor_schedule_json=?, draft_content_hash=?,
                    dirty=?, governance_state_json=?, replay_metadata_json=?, updated_at=?, last_runtime_at=?
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
                    workspace_id,
                    user_id,
                ),
            )
    else:
        workspace_id = uuid.uuid4().hex[:16]
        created_at = now
        replay_metadata.setdefault("workspace_id", workspace_id)
        with get_cursor() as cur:
            cur.execute(
                """
                INSERT INTO workspace_states (
                    workspace_id, project_id, user_id, project_code, active_scenario_id, active_scenario_name,
                    draft_snapshot_json, saved_snapshot_json, last_runtime_snapshot_json, last_runtime_summary_json,
                    last_runtime_snapshot_id, last_runtime_origin, last_runtime_scenario_id,
                    last_financial_statements_json, last_debt_schedule_json, last_tax_schedule_json,
                    last_distribution_schedule_json, last_sponsor_schedule_json, draft_content_hash,
                    dirty, governance_state_json, replay_metadata_json, created_at, updated_at, last_runtime_at
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
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
                ),
            )

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
        updated_pis = current_pis.with_value(field_id, typed_value)
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
