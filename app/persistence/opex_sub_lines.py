"""
app.persistence.opex_sub_lines — OPEX user-added sub-lines persistence.

Mirrors capex_sub_lines.py for the OPEX domain.

Table: opex_sub_lines
Schema differences from capex_sub_lines:
  - parent_group_code  TEXT  (B.NN format, not C.NN)
  - business_code      TEXT  (B.NN.UNNN format)
  - inflation_pct      REAL  (escalation rate — needed for year projection)
  - No schedule_json / governance_state_json / replay_metadata_json
    (OPEX custom rows are simpler; those fields can be added later)

Protected groups (never accept custom rows):
  B.13 — Contingencies (always DERIVED/computed)

All other groups B.01–B.12 accept custom rows, including:
  B.09 — Fees (no registry BOUND field; user creates fee lines directly)
"""
from __future__ import annotations

import re
import uuid
from dataclasses import dataclass
from typing import Any, Iterable, Mapping, Optional, Sequence, Tuple

from app.persistence.db import get_cursor


# ---------------------------------------------------------------------------
# Group eligibility
# ---------------------------------------------------------------------------

_OPEX_GROUPS: frozenset[str] = frozenset(
    f"B.{n:02d}" for n in range(1, 14)   # B.01–B.13
)

REJECTED_PARENT_GROUPS: frozenset[str] = frozenset({"B.13"})

ALLOWED_PARENT_GROUPS: frozenset[str] = _OPEX_GROUPS - REJECTED_PARENT_GROUPS


# ---------------------------------------------------------------------------
# Business code format: B.NN.UNNN
# ---------------------------------------------------------------------------

_BUSINESS_CODE_RE = re.compile(r"^B\.(\d{2})\.U(\d{3})$")
_PARENT_GROUP_RE = re.compile(r"^B\.(\d{2})$")


# ---------------------------------------------------------------------------
# Record shape
# ---------------------------------------------------------------------------

@dataclass(slots=True)
class OpexSubLine:
    """In-memory record for a user-added OPEX sub-line."""

    sub_line_id: str
    project_id: str
    parent_group_code: str    # e.g. "B.09"
    business_code: str        # e.g. "B.09.U001"
    display_order: int
    label: str
    amount_keur: float = 0.0       # Y1 amount
    inflation_pct: float = 0.0     # annual escalation rate
    comments: str = ""
    source: str = "user"
    is_active: bool = True
    created_at: Optional[str] = None
    updated_at: Optional[str] = None
    id: Optional[int] = None

    @classmethod
    def from_row(cls, row: Any) -> "OpexSubLine":
        def _get(key: str, default: Any = None) -> Any:
            try:
                return row[key]
            except (KeyError, IndexError):
                return default

        return cls(
            id=_get("id"),
            sub_line_id=_get("sub_line_id"),
            project_id=_get("project_id"),
            parent_group_code=_get("parent_group_code"),
            business_code=_get("business_code"),
            display_order=int(_get("display_order", 0) or 0),
            label=_get("label", "") or "",
            amount_keur=float(_get("amount_keur", 0.0) or 0.0),
            inflation_pct=float(_get("inflation_pct", 0.0) or 0.0),
            comments=_get("comments", "") or "",
            source=_get("source", "user") or "user",
            is_active=bool(_get("is_active", 0)),
            created_at=_get("created_at"),
            updated_at=_get("updated_at"),
        )


# ---------------------------------------------------------------------------
# Pure validators
# ---------------------------------------------------------------------------

def validate_parent_group(code: Any) -> str:
    """Validate a parent group code (e.g. "B.02").

    Returns the code unchanged on success. Raises ValueError for an
    unknown, malformed, or rejected code.
    """
    if not isinstance(code, str) or not code:
        raise ValueError(
            f"parent_group_code must be a non-empty string, got {code!r}"
        )
    m = _PARENT_GROUP_RE.match(code)
    if not m:
        raise ValueError(
            f"parent_group_code must match B.NN (NN is 2 digits), got {code!r}"
        )
    if code in REJECTED_PARENT_GROUPS:
        raise ValueError(
            f"parent_group_code {code!r} is rejected: "
            f"B.13 (Contingencies) is always DERIVED and does not accept custom rows."
        )
    if code not in ALLOWED_PARENT_GROUPS:
        raise ValueError(
            f"parent_group_code {code!r} is not a known OPEX group; "
            f"allowed groups are {sorted(ALLOWED_PARENT_GROUPS)}"
        )
    return code


def validate_business_code(code: Any) -> str:
    """Validate a business code (e.g. "B.09.U001")."""
    if not isinstance(code, str) or not code:
        raise ValueError(
            f"business_code must be a non-empty string, got {code!r}"
        )
    m = _BUSINESS_CODE_RE.match(code)
    if not m:
        raise ValueError(
            f"business_code {code!r} does not match the required "
            f"format B.NN.U### (NN=2 digits, ###=3 digits)"
        )
    return code


# ---------------------------------------------------------------------------
# Factory project guard
# ---------------------------------------------------------------------------

def assert_project_allows_opex_sub_lines(project_record: Any) -> None:
    """Raise PermissionError if the project forbids OPEX sub-lines."""
    if project_record is None:
        raise PermissionError(
            "Cannot add OPEX sub-lines: project record is None"
        )
    origin = getattr(project_record, "project_origin", None)
    is_readonly = bool(getattr(project_record, "is_readonly", False))
    if origin == "factory_template" or is_readonly:
        raise PermissionError(
            f"Cannot add OPEX sub-lines to a {origin!r} project "
            f"(is_readonly={is_readonly}). Sub-lines are only "
            f"allowed on user_project or saved_baseline origins."
        )
    if origin not in ("user_project", "user_created", "saved_baseline"):
        raise PermissionError(
            f"Cannot add OPEX sub-lines: unknown project_origin "
            f"{origin!r}; expected one of 'user_project', 'user_created', "
            f"'saved_baseline', 'factory_template'"
        )


# ---------------------------------------------------------------------------
# Business code counter
# ---------------------------------------------------------------------------

def _counter_for_existing_codes(
    existing_codes: Iterable[str],
    parent_group_code: str,
) -> int:
    max_seen = 0
    matched_any = False
    for code in existing_codes:
        try:
            validate_business_code(code)
        except ValueError:
            continue
        m = _BUSINESS_CODE_RE.match(code)
        assert m is not None
        code_parent = f"B.{m.group(1)}"
        if code_parent != parent_group_code:
            continue
        matched_any = True
        counter = int(m.group(2))
        if counter > max_seen:
            max_seen = counter
    if not matched_any:
        return 1
    return max_seen + 1


def generate_next_business_code(
    existing_codes: Iterable[str],
    parent_group_code: str,
) -> str:
    """Generate the next business code for the given parent group.

    Format: B.NN.UNNN — the U prefix distinguishes user-added lines.
    Gaps from soft-deletes are preserved (audit trail).
    """
    validate_parent_group(parent_group_code)
    counter = _counter_for_existing_codes(existing_codes, parent_group_code)
    nn = parent_group_code.split(".")[1]
    return f"B.{nn}.U{counter:03d}"


# ---------------------------------------------------------------------------
# DB-backed helpers (all take an explicit cursor — caller owns the transaction)
# ---------------------------------------------------------------------------

def list_sub_lines_for_project(
    cur: Any,
    project_id: str,
    include_inactive: bool = False,
) -> Tuple[OpexSubLine, ...]:
    """List OPEX sub-lines for a project, ordered by group + display_order."""
    if include_inactive:
        cur.execute(
            """
            SELECT * FROM opex_sub_lines
            WHERE project_id = ?
            ORDER BY parent_group_code ASC, display_order ASC
            """,
            (project_id,),
        )
    else:
        cur.execute(
            """
            SELECT * FROM opex_sub_lines
            WHERE project_id = ? AND is_active = 1
            ORDER BY parent_group_code ASC, display_order ASC
            """,
            (project_id,),
        )
    return tuple(OpexSubLine.from_row(row) for row in cur.fetchall())


def list_business_codes_for_project(cur: Any, project_id: str) -> Tuple[str, ...]:
    """Return all business codes (active + soft-deleted) for business-code generation."""
    cur.execute(
        "SELECT business_code FROM opex_sub_lines WHERE project_id = ?",
        (project_id,),
    )
    return tuple(row[0] for row in cur.fetchall())


def create_sub_line(
    cur: Any,
    *,
    project_id: str,
    parent_group_code: str,
    label: str,
    amount_keur: float = 0.0,
    inflation_pct: float = 0.0,
    comments: str = "",
    source: str = "user",
    business_code: Optional[str] = None,
) -> OpexSubLine:
    """Insert a new OPEX sub-line row.

    Validates the parent group (B.01–B.12; B.13 rejected) and business code
    format. If no business_code is provided, the next counter is computed.
    Returns the persisted record with DB-assigned id and timestamps.

    The caller is responsible for the transaction and the
    assert_project_allows_opex_sub_lines guard.
    """
    validate_parent_group(parent_group_code)
    if not isinstance(label, str) or not label.strip():
        raise ValueError(f"label must be a non-empty string, got {label!r}")
    if not isinstance(amount_keur, (int, float)):
        raise ValueError(f"amount_keur must be a number, got {amount_keur!r}")
    if not isinstance(inflation_pct, (int, float)):
        raise ValueError(f"inflation_pct must be a number, got {inflation_pct!r}")

    if business_code is None:
        existing = list_business_codes_for_project(cur, project_id)
        business_code = generate_next_business_code(existing, parent_group_code)
    else:
        validate_business_code(business_code)

    sub_line_id = str(uuid.uuid4())

    cur.execute(
        """
        SELECT COALESCE(MAX(display_order), 0) FROM opex_sub_lines
        WHERE project_id = ? AND parent_group_code = ?
        """,
        (project_id, parent_group_code),
    )
    row = cur.fetchone()
    max_order = int(row[0]) if row and row[0] is not None else 0
    display_order = max_order + 1

    from datetime import datetime, timezone
    now = datetime.now(timezone.utc).isoformat()

    cur.execute(
        """
        INSERT INTO opex_sub_lines (
            sub_line_id, project_id, parent_group_code, business_code,
            display_order, label, amount_keur, inflation_pct, comments,
            source, is_active, created_at, updated_at
        ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, 1, ?, ?)
        """,
        (
            sub_line_id,
            project_id,
            parent_group_code,
            business_code,
            display_order,
            label,
            float(amount_keur),
            float(inflation_pct),
            comments,
            source,
            now,
            now,
        ),
    )
    inserted_id = cur.lastrowid
    return OpexSubLine(
        id=inserted_id,
        sub_line_id=sub_line_id,
        project_id=project_id,
        parent_group_code=parent_group_code,
        business_code=business_code,
        display_order=display_order,
        label=label,
        amount_keur=float(amount_keur),
        inflation_pct=float(inflation_pct),
        comments=comments,
        source=source,
        is_active=True,
        created_at=now,
        updated_at=now,
    )


def update_sub_line(
    cur: Any,
    *,
    project_id: str,
    sub_line_id: str,
    label: str,
    amount_keur: float,
    inflation_pct: float = 0.0,
    comments: str = "",
    row_version: str,
) -> Optional[OpexSubLine]:
    """Update an active OPEX sub-line, guarded by row_version (updated_at).

    Returns the updated OpexSubLine on success, or None if no matching
    active row with that updated_at was found (concurrent edit or stale token).
    """
    if not isinstance(label, str) or not label.strip():
        raise ValueError(f"label must be a non-empty string, got {label!r}")
    if not isinstance(amount_keur, (int, float)):
        raise ValueError(f"amount_keur must be a number, got {amount_keur!r}")

    from datetime import datetime, timezone
    now = datetime.now(timezone.utc).isoformat()

    cur.execute(
        """
        UPDATE opex_sub_lines
        SET label = ?, amount_keur = ?, inflation_pct = ?, comments = ?,
            updated_at = ?
        WHERE project_id = ? AND sub_line_id = ?
          AND is_active = 1 AND updated_at = ?
        """,
        (
            label, float(amount_keur), float(inflation_pct), comments or "",
            now,
            project_id, sub_line_id, row_version,
        ),
    )
    if cur.rowcount == 0:
        return None
    cur.execute(
        "SELECT * FROM opex_sub_lines WHERE project_id = ? AND sub_line_id = ?",
        (project_id, sub_line_id),
    )
    row = cur.fetchone()
    return OpexSubLine.from_row(row) if row else None


def deactivate_sub_line_with_version(
    cur: Any,
    *,
    project_id: str,
    sub_line_id: str,
    row_version: str,
) -> bool:
    """Soft-delete an OPEX sub-line, guarded by row_version (updated_at).

    Returns True if the row was deactivated, False if no matching active row
    with that updated_at was found.
    """
    from datetime import datetime, timezone
    now = datetime.now(timezone.utc).isoformat()
    cur.execute(
        """
        UPDATE opex_sub_lines
        SET is_active = 0, updated_at = ?
        WHERE project_id = ? AND sub_line_id = ?
          AND is_active = 1 AND updated_at = ?
        """,
        (now, project_id, sub_line_id, row_version),
    )
    return cur.rowcount > 0


class ReorderConflictError(ValueError):
    """Raised when a reorder operation detects stale, unknown, duplicate,
    or missing row IDs. The transaction must be rolled back by the caller."""


def reorder_sub_lines(
    cur: Any,
    *,
    project_id: str,
    parent_group_code: str,
    ordered_rows: Sequence[Mapping[str, str]],
) -> list[OpexSubLine]:
    """Atomically reorder active OPEX sub-lines within a group.

    ordered_rows must be the COMPLETE active set for the group, each as
    {"sub_line_id": str, "row_version": str}.

    Validation rules (ALL must pass or ReorderConflictError is raised):
    - No duplicate sub_line_id.
    - Submitted IDs exactly equal the current active ID set (no unknown,
      no missing, no inactive IDs).
    - Every row_version must equal the row's current updated_at.

    On success: display_order values are set to 1..N (contiguous, no gaps).
    """
    validate_parent_group(parent_group_code)
    from datetime import datetime, timezone
    now = datetime.now(timezone.utc).isoformat()

    cur.execute(
        """
        SELECT sub_line_id, updated_at FROM opex_sub_lines
        WHERE project_id = ? AND parent_group_code = ? AND is_active = 1
        """,
        (project_id, parent_group_code),
    )
    db_rows = {r["sub_line_id"]: r["updated_at"] for r in cur.fetchall()}
    current_ids: set[str] = set(db_rows.keys())

    submitted_ids: list[str] = [r["sub_line_id"] for r in ordered_rows]
    submitted_versions: dict[str, str] = {
        r["sub_line_id"]: r["row_version"] for r in ordered_rows
    }

    # Duplicate IDs
    if len(submitted_ids) != len(set(submitted_ids)):
        seen: set[str] = set()
        dups = [sid for sid in submitted_ids if sid in seen or seen.add(sid)]  # type: ignore[func-returns-value]
        raise ReorderConflictError(
            f"Duplicate sub_line_id(s) in reorder request: {dups!r}."
        )

    submitted_id_set = set(submitted_ids)

    # Unknown or inactive IDs
    unknown = submitted_id_set - current_ids
    if unknown:
        raise ReorderConflictError(
            f"Unknown or inactive sub_line_id(s): {sorted(unknown)!r}. "
            "Reload the page and try again."
        )

    # Missing active IDs
    missing = current_ids - submitted_id_set
    if missing:
        raise ReorderConflictError(
            f"Missing active sub_line_id(s) from reorder request: {sorted(missing)!r}. "
            "Submit the complete active set for the group."
        )

    # Stale row_version
    stale = [
        sid for sid in submitted_ids
        if submitted_versions[sid] != db_rows[sid]
    ]
    if stale:
        raise ReorderConflictError(
            f"Stale row_version for sub_line_id(s): {stale!r}. "
            "Reload and try again."
        )

    # Update display_order 1..N
    for new_order, sid in enumerate(submitted_ids, start=1):
        cur.execute(
            """
            UPDATE opex_sub_lines
            SET display_order = ?, updated_at = ?
            WHERE project_id = ? AND sub_line_id = ?
              AND parent_group_code = ? AND is_active = 1
            """,
            (new_order, now, project_id, sid, parent_group_code),
        )

    # Read back in new order
    cur.execute(
        """
        SELECT * FROM opex_sub_lines
        WHERE project_id = ? AND parent_group_code = ? AND is_active = 1
        ORDER BY display_order ASC
        """,
        (project_id, parent_group_code),
    )
    return [OpexSubLine.from_row(row) for row in cur.fetchall()]


def get_active_sub_lines_for_project(project_id: str) -> list[OpexSubLine]:
    """Convenience wrapper — opens a short-lived cursor."""
    with get_cursor() as cur:
        return list(
            list_sub_lines_for_project(cur, project_id, include_inactive=False)
        )


__all__ = [
    "ALLOWED_PARENT_GROUPS",
    "OpexSubLine",
    "REJECTED_PARENT_GROUPS",
    "ReorderConflictError",
    "assert_project_allows_opex_sub_lines",
    "create_sub_line",
    "deactivate_sub_line_with_version",
    "generate_next_business_code",
    "get_active_sub_lines_for_project",
    "list_business_codes_for_project",
    "list_sub_lines_for_project",
    "reorder_sub_lines",
    "update_sub_line",
    "validate_business_code",
    "validate_parent_group",
]
