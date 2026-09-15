"""
app.v2.opex_commands — OPEX custom-row command layer.

Mirrors capex_commands.py for the OPEX domain.

Each command function enforces:
  - Protected-reference guard (factory_template → PermissionError)
  - Group eligibility (B.13 → ValueError; unknown → ValueError)
  - Workbook version check (browser registry must match server)
  - Composite workbook identity CAS (expected_content_hash must match current
    composite identity before any mutation is applied)
  - Row-level optimistic concurrency (updated_at token) for precise row conflicts
  - Atomic DB write covering opex_sub_lines, workspace_states, and the new
    composite hash (BEGIN EXCLUSIVE — all steps in one transaction)

See capex_commands.py for the full transaction sequence and design rationale.
"""
from __future__ import annotations

from contextlib import contextmanager
from datetime import datetime, timezone
from typing import Any, Iterator, List, Mapping, Optional, Sequence

from app.persistence.opex_sub_lines import (
    REJECTED_PARENT_GROUPS,
    OpexSubLine,
    ReorderConflictError,
    assert_project_allows_opex_sub_lines,
    create_sub_line,
    deactivate_sub_line_with_version,
    list_sub_lines_for_project,
    reorder_sub_lines,
    update_sub_line,
    validate_parent_group,
)
from app.persistence.db import get_connection
from app.persistence.workspace_repository import update_composite_hash_cursor
from app.workbook.numeric_guard import NumericGuardError, assert_finite_float
from app.workbook.registry import WORKBOOK

# B.13 Contingencies is always DERIVED — no custom rows allowed.
_DERIVED_GROUP_CODES: frozenset[str] = frozenset({"B.13"})


# ---------------------------------------------------------------------------
# Error hierarchy
# ---------------------------------------------------------------------------

class OpexCommandError(ValueError):
    """Base for all OPEX command errors."""


class OpexProtectedReferenceError(OpexCommandError):
    """Project is a factory_template and cannot be mutated."""


class OpexProtectedGroupError(OpexCommandError):
    """The target OPEX group does not accept custom rows."""


class OpexConcurrentEditError(OpexCommandError):
    """Row version is stale — concurrent edit detected."""


class OpexStaleIdentityError(OpexConcurrentEditError):
    """Composite workbook identity is stale — cross-type concurrent change detected.

    Raised when the submitted expected_content_hash does not match the
    current composite identity.  Covers: scalar change, CAPEX row mutation,
    scenario switch — any engine-effective change that rotated the composite
    hash since the client loaded the page.
    """


class OpexVersionMismatchError(OpexCommandError):
    """Workbook version submitted by browser is stale."""


class OpexRowNotFoundError(OpexCommandError):
    """Sub-line not found or not active for this project."""


class OpexInvalidAmountError(OpexCommandError):
    """amount_keur or inflation_pct is non-finite (NaN, +Inf, -Inf, or overflow)."""


# ---------------------------------------------------------------------------
# Guard helpers
# ---------------------------------------------------------------------------


def _parse_finite_opex_numerics(raw_amount: Any, raw_inflation: Any) -> tuple[float, float]:
    """Validate and convert amount_keur and inflation_pct to finite floats.

    Raises OpexInvalidAmountError for NaN, +Inf, -Inf, or overflow.
    """
    results = []
    for raw, label in ((raw_amount, "Amount (kEUR)"), (raw_inflation, "Inflation (%)")):
        try:
            v = float(raw)
            assert_finite_float(v, label=label)
        except (ValueError, TypeError, NumericGuardError) as exc:
            raise OpexInvalidAmountError(
                f"{label} must be a finite number (got {raw!r})."
            ) from exc
        results.append(v)
    return results[0], results[1]

def _check_project_allows(project_record: Any) -> None:
    try:
        assert_project_allows_opex_sub_lines(project_record)
    except PermissionError as exc:
        raise OpexProtectedReferenceError(str(exc)) from exc


def _check_workbook_version(submitted_version: str) -> None:
    current = WORKBOOK.version
    if submitted_version != current:
        raise OpexVersionMismatchError(
            f"Browser workbook version {submitted_version!r} is stale "
            f"(server: {current!r}). Reload the page before editing."
        )


def _check_group_eligible(parent_group_code: str) -> None:
    """Raise if the group is rejected or derived."""
    if parent_group_code in REJECTED_PARENT_GROUPS:
        raise OpexProtectedGroupError(
            f"Group {parent_group_code!r} is read-only "
            "(B.13 Contingencies does not accept custom rows)."
        )
    if parent_group_code in _DERIVED_GROUP_CODES:
        raise OpexProtectedGroupError(
            f"Group {parent_group_code!r} is a derived/contingency group "
            "and does not accept custom rows."
        )
    try:
        validate_parent_group(parent_group_code)
    except ValueError as exc:
        raise OpexProtectedGroupError(str(exc)) from exc


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

    Validates the current composite workbook identity against
    ``expected_content_hash`` before yielding the cursor.  After the body
    returns, recomputes the identity from the new state, persists the new
    hash + dirty=1, and COMMITs.  Any failure triggers ROLLBACK.

    The new composite hash is written to ``hash_out.value`` after commit.
    """
    from app.workbook.workbook_identity import WorkbookIdentityError, assemble_transactional

    conn = get_connection()
    conn.execute("BEGIN EXCLUSIVE")
    cur = conn.cursor()
    try:
        # Read workspace row
        cur.execute(
            "SELECT draft_snapshot_json, active_scenario_id, active_scenario_name "
            "FROM workspace_states WHERE user_id=? AND project_id=?",
            (user_id, project_id),
        )
        ws_row = cur.fetchone()
        if ws_row is None:
            raise OpexCommandError(
                "Workspace state is missing; OPEX row mutation rejected."
            )

        # Compute current composite identity
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
            raise OpexCommandError(
                f"Identity assembly failed before mutation; rolling back: {exc}"
            ) from exc

        # CAS check
        if current_identity.composite_hash != expected_content_hash:
            raise OpexStaleIdentityError(
                "Workbook changed since page loaded — values refreshed. "
                "Please try your edit again."
            )

        # Execute row mutation
        yield cur

        # Recompute composite identity after mutation
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
            raise OpexCommandError(
                f"Identity assembly failed after mutation; rolling back: {exc}"
            ) from exc

        # Persist new hash + dirty flag
        updated = update_composite_hash_cursor(
            cur,
            user_id=user_id,
            project_id=project_id,
            composite_hash=new_identity.composite_hash,
            now_iso=_now_utc_iso(),
        )
        if not updated:
            raise OpexCommandError(
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

def add_opex_line(
    *,
    project_record: Any,
    user_id: str,
    label: str,
    parent_group_code: str,
    amount_keur: float = 0.0,
    inflation_pct: float = 0.0,
    notes: str = "",
    workbook_version: str,
    expected_content_hash: str,
) -> tuple[OpexSubLine, str]:
    """Add a custom sub-line to an eligible OPEX group.

    Returns ``(sub_line, new_composite_hash)``.

    Raises
    ------
    OpexProtectedReferenceError / OpexProtectedGroupError /
    OpexVersionMismatchError / OpexStaleIdentityError / ValueError
    """
    _check_project_allows(project_record)
    _check_workbook_version(workbook_version)
    _check_group_eligible(parent_group_code)
    _amount, _inflation = _parse_finite_opex_numerics(amount_keur, inflation_pct)

    project_id: str = project_record.project_id
    hash_out = _HashOut()
    result_holder: list[Any] = [None]

    with _exclusive_tx(user_id, project_id, expected_content_hash=expected_content_hash, hash_out=hash_out) as cur:
        result_holder[0] = create_sub_line(
            cur,
            project_id=project_id,
            parent_group_code=parent_group_code,
            label=label,
            amount_keur=_amount,
            inflation_pct=_inflation,
            comments=notes,
        )
    return result_holder[0], hash_out.value


def update_opex_line(
    *,
    project_record: Any,
    user_id: str,
    sub_line_id: str,
    label: str,
    amount_keur: float,
    inflation_pct: float = 0.0,
    notes: str = "",
    row_version: str,
    workbook_version: str,
    expected_content_hash: str,
) -> tuple[OpexSubLine, str]:
    """Update an existing custom OPEX sub-line's label, amount, inflation, and notes.

    Returns ``(updated_sub_line, new_composite_hash)``.

    Raises
    ------
    OpexProtectedReferenceError / OpexVersionMismatchError /
    OpexStaleIdentityError / OpexConcurrentEditError / OpexRowNotFoundError
    """
    _check_project_allows(project_record)
    _check_workbook_version(workbook_version)
    _amount, _inflation = _parse_finite_opex_numerics(amount_keur, inflation_pct)

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
            inflation_pct=_inflation,
            comments=notes,
            row_version=row_version,
        )
        if result is None:
            rows = list_sub_lines_for_project(cur, project_id, include_inactive=True)
            if not any(r.sub_line_id == sub_line_id for r in rows):
                raise OpexRowNotFoundError(
                    f"Sub-line {sub_line_id!r} not found for project {project_id!r}."
                )
            raise OpexConcurrentEditError(
                f"Sub-line {sub_line_id!r} was modified concurrently. "
                "Reload and try again."
            )
        result_holder[0] = result

    return result_holder[0], hash_out.value


def deactivate_opex_line(
    *,
    project_record: Any,
    user_id: str,
    sub_line_id: str,
    row_version: str,
    workbook_version: str,
    expected_content_hash: str,
) -> tuple[bool, str]:
    """Deactivate (soft-delete) a custom OPEX sub-line.

    Returns ``(True, new_composite_hash)`` on success.

    Raises
    ------
    OpexProtectedReferenceError / OpexVersionMismatchError /
    OpexStaleIdentityError / OpexConcurrentEditError / OpexRowNotFoundError
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
                raise OpexRowNotFoundError(
                    f"Sub-line {sub_line_id!r} not found for project {project_id!r}."
                )
            raise OpexConcurrentEditError(
                f"Sub-line {sub_line_id!r} was modified concurrently. "
                "Reload and try again."
            )

    return True, hash_out.value


def reorder_opex_lines(
    *,
    project_record: Any,
    user_id: str,
    parent_group_code: str,
    ordered_rows: Sequence[Mapping[str, str]],
    workbook_version: str,
    expected_content_hash: str,
) -> tuple[list[OpexSubLine], str]:
    """Reorder custom sub-lines within a group (atomic, fully validated).

    Reorder is presentation-only — display_order is excluded from the
    composite hash, so ``new_composite_hash == expected_content_hash``.
    The expected_content_hash is still validated to reject cross-type stale
    state before any mutation is applied.

    Returns ``(ordered_sub_lines, new_composite_hash)``.

    Raises
    ------
    OpexProtectedReferenceError / OpexProtectedGroupError /
    OpexVersionMismatchError / OpexStaleIdentityError / OpexConcurrentEditError
    """
    _check_project_allows(project_record)
    _check_workbook_version(workbook_version)
    _check_group_eligible(parent_group_code)

    project_id: str = project_record.project_id
    hash_out = _HashOut()
    result_holder: list[Any] = [None]

    with _exclusive_tx(user_id, project_id, expected_content_hash=expected_content_hash, hash_out=hash_out) as cur:
        try:
            result_holder[0] = reorder_sub_lines(
                cur,
                project_id=project_id,
                parent_group_code=parent_group_code,
                ordered_rows=ordered_rows,
            )
        except ReorderConflictError as exc:
            raise OpexConcurrentEditError(str(exc)) from exc

    return result_holder[0], hash_out.value
