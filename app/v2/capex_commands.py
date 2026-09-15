"""
app.v2.capex_commands — CAPEX custom-row command layer.

Each command function enforces:
  - Protected-reference guard (factory_template → PermissionError)
  - Category eligibility (C.17/C.18 → ValueError; C.13 contingency → ValueError)
  - Workbook version check (browser registry must match server)
  - Composite workbook identity CAS (expected_content_hash must match current
    composite identity before any mutation is applied)
  - Row-level optimistic concurrency (updated_at token) for precise row conflicts
  - Atomic DB write covering capex_sub_lines, workspace_states, and the new
    composite hash (BEGIN EXCLUSIVE — all steps in one transaction)

Aggregate identity and row version solve different problems; both are required:
  - Composite identity: cross-type CAS — prevents a stale CAPEX client from
    mutating after an OPEX row or scalar change (or vice versa).
  - Row version: precise row-level conflict detection within the CAPEX domain.

Transaction sequence (every mutating command)
----------------------------------------------
1. BEGIN EXCLUSIVE
2. Read workspace row (draft_snapshot + active_scenario_id + active_scenario_name)
3. Read active CAPEX rows inside transaction
4. Read active OPEX rows inside transaction
5. Read active scenario overrides inside transaction
6. Compute current composite identity → compare submitted expected_content_hash
7. Reject stale with CapexStaleIdentityError before any mutation
8. Apply row mutation (create / update / deactivate / reorder)
9. Recompute composite identity from the new in-transaction state
10. Persist the new composite hash + dirty=1 to workspace_states
11. COMMIT
12. Return (row_result, new_composite_hash) to the caller

Reorder semantics
-----------------
Reorder is presentation-only; display_order is excluded from the hash.
The composite hash is INVARIANT to reorder — the new hash will equal the
expected_content_hash already held by the client.  The expected_content_hash
is still validated before reordering to catch cross-type stale state.

Dirty-state guarantee
---------------------
Every successful command sets workspace_states.dirty=1 inside the same
exclusive transaction as the capex_sub_lines write.  If the dirty-state
UPDATE fails the whole transaction rolls back.
"""
from __future__ import annotations

from contextlib import contextmanager
from datetime import datetime, timezone
from typing import Any, Iterator, List, Mapping, Optional, Sequence

from app.persistence.capex_sub_lines import (
    REJECTED_PARENT_CATEGORIES,
    CapexSubLine,
    ReorderConflictError,
    assert_project_allows_capex_sub_lines,
    create_sub_line,
    deactivate_sub_line_with_version,
    list_sub_lines_for_project,
    reorder_sub_lines,
    update_sub_line,
    validate_parent_category,
)
from app.persistence.db import get_connection
from app.persistence.workspace_repository import update_composite_hash_cursor
from app.workbook.numeric_guard import NumericGuardError, assert_finite_float
from app.workbook.registry import WORKBOOK

# Groups that are derived/computed — no custom rows allowed even though the
# persistence layer permits C.13 in its allowed list.
_DERIVED_GROUP_CODES: frozenset[str] = frozenset({"C.13"})


# ---------------------------------------------------------------------------
# Error hierarchy
# ---------------------------------------------------------------------------

class CapexCommandError(ValueError):
    """Base for all CAPEX command errors."""


class CapexProtectedReferenceError(CapexCommandError):
    """Project is a factory_template and cannot be mutated."""


class CapexProtectedGroupError(CapexCommandError):
    """The target CAPEX group does not accept custom rows."""


class CapexConcurrentEditError(CapexCommandError):
    """Row version is stale — concurrent edit detected."""


class CapexStaleIdentityError(CapexConcurrentEditError):
    """Composite workbook identity is stale — cross-type concurrent change detected.

    Raised when the submitted expected_content_hash does not match the
    current composite identity.  Covers: scalar change by another client,
    OPEX row mutation, scenario switch — any engine-effective change that
    rotated the composite hash since the client loaded the page.
    """


class CapexVersionMismatchError(CapexCommandError):
    """Workbook version submitted by browser is stale."""


class CapexRowNotFoundError(CapexCommandError):
    """Sub-line not found or not active for this project."""


class CapexInvalidAmountError(CapexCommandError):
    """amount_keur is non-finite (NaN, +Inf, -Inf, or overflow)."""


# ---------------------------------------------------------------------------
# Guard helpers
# ---------------------------------------------------------------------------


def _parse_finite_amount_keur(raw: Any) -> float:
    """Convert *raw* to a finite float for amount_keur.

    Raises CapexInvalidAmountError for NaN, +Inf, -Inf, or overflow.
    """
    try:
        v = float(raw)
        assert_finite_float(v, label="Amount (kEUR)")
    except (ValueError, TypeError, NumericGuardError) as exc:
        raise CapexInvalidAmountError(
            f"Amount (kEUR) must be a finite number (got {raw!r})."
        ) from exc
    return v

def _check_project_allows(project_record: Any) -> None:
    try:
        assert_project_allows_capex_sub_lines(project_record)
    except PermissionError as exc:
        raise CapexProtectedReferenceError(str(exc)) from exc


def _check_workbook_version(submitted_version: str) -> None:
    current = WORKBOOK.version
    if submitted_version != current:
        raise CapexVersionMismatchError(
            f"Browser workbook version {submitted_version!r} is stale "
            f"(server: {current!r}). Reload the page before editing."
        )


def _check_group_eligible(parent_category_code: str) -> None:
    """Raise if the group is rejected or derived."""
    if parent_category_code in REJECTED_PARENT_CATEGORIES:
        raise CapexProtectedGroupError(
            f"Group {parent_category_code!r} is read-only "
            "(C.17 and C.18 do not accept custom rows)."
        )
    if parent_category_code in _DERIVED_GROUP_CODES:
        raise CapexProtectedGroupError(
            f"Group {parent_category_code!r} is a derived/contingency group "
            "and does not accept custom rows."
        )
    try:
        validate_parent_category(parent_category_code)
    except ValueError as exc:
        raise CapexProtectedGroupError(str(exc)) from exc


def _now_utc_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


# ---------------------------------------------------------------------------
# Mutable hash output container
# ---------------------------------------------------------------------------

class _HashOut:
    """Carries the new composite hash out of the context manager."""
    __slots__ = ("value",)
    def __init__(self) -> None:
        self.value: str = ""


# ---------------------------------------------------------------------------
# Atomic transaction context manager
# ---------------------------------------------------------------------------

@contextmanager
def _exclusive_tx(
    user_id: str,
    project_id: str,
    *,
    expected_content_hash: str,
    hash_out: _HashOut,
) -> Iterator[Any]:
    """BEGIN EXCLUSIVE transaction with composite identity CAS.

    Validates current composite workbook identity against
    ``expected_content_hash`` before yielding the cursor.  After the body
    returns, recomputes the identity from the new state, persists the new
    hash + dirty=1, and COMMITs.  Any failure triggers ROLLBACK.

    The new composite hash after commit is written to ``hash_out.value``.

    Raises CapexStaleIdentityError on hash mismatch (before any mutation).
    Raises CapexCommandError if identity assembly fails or workspace is missing.
    """
    from app.workbook.workbook_identity import WorkbookIdentityError, assemble_transactional

    conn = get_connection()
    conn.execute("BEGIN EXCLUSIVE")
    cur = conn.cursor()
    try:
        # Read workspace row (draft_snapshot + scenario)
        cur.execute(
            "SELECT draft_snapshot_json, active_scenario_id, active_scenario_name "
            "FROM workspace_states WHERE user_id=? AND project_id=?",
            (user_id, project_id),
        )
        ws_row = cur.fetchone()
        if ws_row is None:
            raise CapexCommandError(
                "Workspace state is missing; CAPEX row mutation rejected."
            )

        # Compute current composite identity (reads CAPEX + OPEX + scenario inside tx)
        try:
            current_identity = assemble_transactional(
                draft_snapshot_json=ws_row["draft_snapshot_json"] or "{}",
                project_id=project_id,
                user_id=user_id,
                active_scenario_id=ws_row["active_scenario_id"],
                active_scenario_name=ws_row["active_scenario_name"],
                cursor=cur,
                workbook_version=WORKBOOK.version,
            )
        except WorkbookIdentityError as exc:
            raise CapexCommandError(
                f"Identity assembly failed before mutation; rolling back: {exc}"
            ) from exc

        # CAS check: reject stale before any mutation
        if current_identity.composite_hash != expected_content_hash:
            raise CapexStaleIdentityError(
                "Workbook changed since page loaded — values refreshed. "
                "Please try your edit again."
            )

        # Execute row mutation (caller's body)
        yield cur

        # Recompute composite identity from new in-transaction state
        try:
            cur.execute(
                "SELECT draft_snapshot_json, active_scenario_id, active_scenario_name "
                "FROM workspace_states WHERE user_id=? AND project_id=?",
                (user_id, project_id),
            )
            ws_row_after = cur.fetchone() or ws_row
            new_identity = assemble_transactional(
                draft_snapshot_json=ws_row_after["draft_snapshot_json"] or "{}",
                project_id=project_id,
                user_id=user_id,
                active_scenario_id=ws_row_after["active_scenario_id"],
                active_scenario_name=ws_row_after["active_scenario_name"],
                cursor=cur,
                workbook_version=WORKBOOK.version,
            )
        except WorkbookIdentityError as exc:
            raise CapexCommandError(
                f"Identity assembly failed after mutation; rolling back: {exc}"
            ) from exc

        # Persist new hash + dirty flag atomically with the row mutation
        updated = update_composite_hash_cursor(
            cur,
            user_id=user_id,
            project_id=project_id,
            composite_hash=new_identity.composite_hash,
            now_iso=_now_utc_iso(),
        )
        if not updated:
            raise CapexCommandError(
                "Workspace state disappeared during mutation; rolling back."
            )

        hash_out.value = new_identity.composite_hash
        conn.execute("COMMIT")

    except Exception:
        try:
            conn.execute("ROLLBACK")
        except Exception:
            pass
        raise
    finally:
        cur.close()
        conn.close()


# ---------------------------------------------------------------------------
# Commands
# ---------------------------------------------------------------------------

def add_capex_line(
    *,
    project_record: Any,
    user_id: str,
    label: str,
    parent_category_code: str,
    amount_keur: float = 0.0,
    notes: str = "",
    workbook_version: str,
    expected_content_hash: str,
) -> tuple[CapexSubLine, str]:
    """Add a custom sub-line to an eligible CAPEX group.

    Returns ``(sub_line, new_composite_hash)``.  The workspace is marked
    dirty and the new composite hash is persisted in the same exclusive
    transaction.

    Raises
    ------
    CapexProtectedReferenceError
        Project is a factory_template.
    CapexProtectedGroupError
        Group does not accept custom rows (C.13, C.17, C.18, unknown).
    CapexVersionMismatchError
        Browser workbook version is stale.
    CapexStaleIdentityError
        Composite workbook identity is stale (cross-type concurrent change).
    ValueError
        label is empty or amount_keur is not numeric.
    """
    _check_project_allows(project_record)
    _check_workbook_version(workbook_version)
    _check_group_eligible(parent_category_code)
    _amount = _parse_finite_amount_keur(amount_keur)

    project_id: str = project_record.project_id
    hash_out = _HashOut()
    result_holder: list[Any] = [None]
    with _exclusive_tx(user_id, project_id, expected_content_hash=expected_content_hash, hash_out=hash_out) as cur:
        result_holder[0] = create_sub_line(
            cur,
            project_id=project_id,
            parent_category_code=parent_category_code,
            label=label,
            amount_keur=_amount,
            comments=notes,
        )
    return result_holder[0], hash_out.value


def update_capex_line(
    *,
    project_record: Any,
    user_id: str,
    sub_line_id: str,
    label: str,
    amount_keur: float,
    notes: str = "",
    row_version: str,
    workbook_version: str,
    expected_content_hash: str,
) -> tuple[CapexSubLine, str]:
    """Update an existing custom sub-line's label, amount, and notes.

    Returns ``(updated_sub_line, new_composite_hash)``.

    Raises
    ------
    CapexProtectedReferenceError / CapexVersionMismatchError /
    CapexStaleIdentityError / CapexConcurrentEditError / CapexRowNotFoundError
    """
    _check_project_allows(project_record)
    _check_workbook_version(workbook_version)
    _amount = _parse_finite_amount_keur(amount_keur)

    project_id: str = project_record.project_id
    hash_out = _HashOut()
    result_holder: list[Any] = [None]

    with _exclusive_tx(user_id, project_id, expected_content_hash=expected_content_hash, hash_out=hash_out) as cur:
        result = update_sub_line(
            cur,
            project_id=project_id,
            sub_line_id=sub_line_id,
            label=label,
            amount_keur=_amount,
            comments=notes,
            row_version=row_version,
        )
        if result is None:
            rows = list_sub_lines_for_project(cur, project_id, include_inactive=True)
            if not any(r.sub_line_id == sub_line_id for r in rows):
                raise CapexRowNotFoundError(
                    f"Sub-line {sub_line_id!r} not found for project {project_id!r}."
                )
            raise CapexConcurrentEditError(
                f"Sub-line {sub_line_id!r} was modified concurrently. "
                "Reload and try again."
            )
        result_holder[0] = result

    return result_holder[0], hash_out.value


def deactivate_capex_line(
    *,
    project_record: Any,
    user_id: str,
    sub_line_id: str,
    row_version: str,
    workbook_version: str,
    expected_content_hash: str,
) -> tuple[bool, str]:
    """Deactivate (soft-delete) a custom sub-line.

    Returns ``(True, new_composite_hash)`` on success.

    Raises
    ------
    CapexProtectedReferenceError / CapexVersionMismatchError /
    CapexStaleIdentityError / CapexConcurrentEditError / CapexRowNotFoundError
    """
    _check_project_allows(project_record)
    _check_workbook_version(workbook_version)

    project_id: str = project_record.project_id
    hash_out = _HashOut()

    with _exclusive_tx(user_id, project_id, expected_content_hash=expected_content_hash, hash_out=hash_out) as cur:
        ok = deactivate_sub_line_with_version(
            cur,
            project_id=project_id,
            sub_line_id=sub_line_id,
            row_version=row_version,
        )
        if not ok:
            rows = list_sub_lines_for_project(cur, project_id, include_inactive=True)
            if not any(r.sub_line_id == sub_line_id for r in rows):
                raise CapexRowNotFoundError(
                    f"Sub-line {sub_line_id!r} not found for project {project_id!r}."
                )
            raise CapexConcurrentEditError(
                f"Sub-line {sub_line_id!r} was modified concurrently. "
                "Reload and try again."
            )

    return True, hash_out.value


def reorder_capex_lines(
    *,
    project_record: Any,
    user_id: str,
    parent_category_code: str,
    ordered_rows: Sequence[Mapping[str, str]],
    workbook_version: str,
    expected_content_hash: str,
) -> tuple[list[CapexSubLine], str]:
    """Reorder custom sub-lines within a group (atomic, fully validated).

    ``ordered_rows`` must be the COMPLETE active set for the group, each
    entry as ``{"sub_line_id": str, "row_version": str}``.

    Reorder is presentation-only — display_order is excluded from the
    composite hash, so ``new_composite_hash == expected_content_hash``.
    The expected_content_hash is still validated to reject cross-type stale
    state before any mutation is applied.

    Returns ``(ordered_sub_lines, new_composite_hash)``.

    Raises
    ------
    CapexProtectedReferenceError / CapexProtectedGroupError /
    CapexVersionMismatchError / CapexStaleIdentityError / CapexConcurrentEditError
    """
    _check_project_allows(project_record)
    _check_workbook_version(workbook_version)
    _check_group_eligible(parent_category_code)

    project_id: str = project_record.project_id
    hash_out = _HashOut()
    result_holder: list[Any] = [None]

    with _exclusive_tx(user_id, project_id, expected_content_hash=expected_content_hash, hash_out=hash_out) as cur:
        try:
            result_holder[0] = reorder_sub_lines(
                cur,
                project_id=project_id,
                parent_category_code=parent_category_code,
                ordered_rows=ordered_rows,
            )
        except ReorderConflictError as exc:
            raise CapexConcurrentEditError(str(exc)) from exc

    return result_holder[0], hash_out.value
