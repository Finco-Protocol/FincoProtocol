"""app.v2.cost_batch_commands — atomic multi-row Save of EXISTING CAPEX / OPEX line items.

One transaction, the existing authorities, no new financial rule
----------------------------------------------------------------
CAPEX and OPEX line items are persisted by two row-versioned repositories
(``capex_sub_lines`` / ``opex_sub_lines``; ``row_version`` is the row's ``updated_at``) and are
written by the guarded command layers ``capex_commands`` / ``opex_commands``.  Both command layers
wrap their repository calls in the SAME kind of transaction: ``BEGIN EXCLUSIVE`` + composite
workbook-identity CAS + dirty flag/hash in the same commit + ROLLBACK on any exception.  The
repository ``update_sub_line`` functions take the caller's cursor and own no transaction.

This module therefore adds exactly one thing: it applies N row updates inside ONE of those
transactions instead of N.  It does not route anything through the scalar C0 writer, does not
touch ``ProjectInputSet`` / scalar fields, runs no engine and calculates nothing.

Contract (all-or-nothing)
-------------------------
1. Project guards identical to the single-row commands (protected reference, workbook version).
2. Shape validation BEFORE the transaction: 1..MAX_BATCH_LINES edits, no duplicate line, finite
   numbers, non-empty descriptions.  Any failure -> ``CostBatchInvalidError`` (nothing opened).
3. ``BEGIN EXCLUSIVE`` + composite CAS (``CapexStaleIdentityError`` on mismatch, before any write).
4. Every line is verified INSIDE the transaction before the first write: it must exist in THIS
   project, be active and carry the submitted ``row_version``.  Unknown/foreign-project ids,
   inactive rows and stale versions are all reported per line -> ``CostBatchConflictError``;
   nothing was written.
5. Writes use the existing guarded ``update_sub_line`` (still row_version-conditional).  Any
   failure raises, the shared transaction manager rolls back every row and the hash/dirty flag.
6. On success the new composite hash and ``dirty=1`` are committed with the rows, so the Last Run
   is classified STALE by the canonical freshness authority.  No run, no retry, no history write.
"""
from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Optional, Sequence

from app.persistence.capex_sub_lines import list_sub_lines_for_project as _list_capex
from app.persistence.capex_sub_lines import update_sub_line as _update_capex
from app.persistence.opex_sub_lines import list_sub_lines_for_project as _list_opex
from app.persistence.opex_sub_lines import update_sub_line as _update_opex
from app.v2.capex_commands import (
    _HashOut,
    _check_project_allows as _capex_project_allows,
    _check_workbook_version,
    _exclusive_tx,
    _parse_finite_amount_keur,
)
from app.v2.opex_commands import _check_project_allows as _opex_project_allows
from app.v2.opex_commands import _parse_finite_opex_numerics

MAX_BATCH_LINES = 50
KINDS = ("capex", "opex")


class CostBatchError(ValueError):
    """Base: carries a stable ``code`` and per-line ``verdicts`` (index, kind, sub_line_id, code)."""

    code = "COST_BATCH_REJECTED"

    def __init__(self, message: str, verdicts: Optional[list[dict[str, Any]]] = None):
        super().__init__(message)
        self.verdicts = verdicts or []


class CostBatchInvalidError(CostBatchError):
    """The submitted edits are malformed (shape / numbers / duplicates).  Nothing was written."""

    code = "COST_BATCH_INVALID"


class CostBatchConflictError(CostBatchError):
    """A line is unknown, inactive or carries a stale row_version.  Nothing was written."""

    code = "COST_BATCH_CONFLICT"


@dataclass(frozen=True)
class CostLineEdit:
    """One staged edit.  ``inflation_pct`` (OPEX only) and ``notes`` default to the stored value."""

    kind: str
    sub_line_id: str
    label: str
    amount_keur: Any
    row_version: str
    inflation_pct: Any = None
    notes: Optional[str] = None


def _invalid(index: int, edit: Any, message: str) -> dict[str, Any]:
    return {"index": index, "kind": getattr(edit, "kind", None), "sub_line_id": getattr(edit, "sub_line_id", None),
            "ok": False, "code": "LINE_INVALID", "message": message}


def _validate_shape(edits: Sequence[CostLineEdit]) -> list[tuple[CostLineEdit, float, Optional[float]]]:
    if not edits:
        raise CostBatchInvalidError("No edited lines were submitted.")
    if len(edits) > MAX_BATCH_LINES:
        raise CostBatchInvalidError(f"At most {MAX_BATCH_LINES} lines can be saved together.")
    problems: list[dict[str, Any]] = []
    parsed: list[tuple[CostLineEdit, float, Optional[float]]] = []
    seen: set[tuple[str, str]] = set()
    for index, edit in enumerate(edits):
        key = (edit.kind, edit.sub_line_id)
        try:
            if edit.kind not in KINDS:
                raise ValueError("Unknown line kind.")
            if not isinstance(edit.sub_line_id, str) or not edit.sub_line_id.strip():
                raise ValueError("Line identity is required.")
            if key in seen:
                raise ValueError("The same line was submitted twice.")
            seen.add(key)
            if not isinstance(edit.label, str) or not edit.label.strip():
                raise ValueError("Description required.")
            if not isinstance(edit.row_version, str) or not edit.row_version:
                raise ValueError("Row version is required.")
            if edit.kind == "capex":
                if edit.inflation_pct not in (None, ""):
                    raise ValueError("Escalation does not apply to CAPEX lines.")
                amount, inflation = _parse_finite_amount_keur(edit.amount_keur), None
            else:
                amount, inflation = _parse_finite_opex_numerics(
                    edit.amount_keur, 0.0 if edit.inflation_pct in (None, "") else edit.inflation_pct)
                if edit.inflation_pct in (None, ""):
                    inflation = None            # keep the stored escalation
            parsed.append((edit, amount, inflation))
        except ValueError as exc:               # includes Capex/OpexInvalidAmountError
            problems.append(_invalid(index, edit, str(exc)))
    if problems:
        raise CostBatchInvalidError("One or more edited lines are invalid; nothing was saved.", problems)
    return parsed


def update_cost_lines_batch(
    *,
    project_record: Any,
    user_id: str,
    edits: Sequence[CostLineEdit],
    workbook_version: str,
    expected_content_hash: str,
) -> tuple[list[dict[str, Any]], str]:
    """Atomically update many existing CAPEX/OPEX lines.  Returns ``(saved, new_composite_hash)``.

    Raises the single-row command errors (protected reference, workbook version, stale composite
    identity), ``CostBatchInvalidError`` (422) or ``CostBatchConflictError`` (409).  After ANY
    exception no row, no hash and no dirty flag has changed.
    """
    _capex_project_allows(project_record)
    _opex_project_allows(project_record)
    _check_workbook_version(workbook_version)
    parsed = _validate_shape(edits)

    project_id: str = project_record.project_id
    hash_out = _HashOut()
    saved: list[dict[str, Any]] = []
    with _exclusive_tx(user_id, project_id, expected_content_hash=expected_content_hash, hash_out=hash_out) as cur:
        stored = {
            "capex": {r.sub_line_id: r for r in _list_capex(cur, project_id, include_inactive=True)},
            "opex": {r.sub_line_id: r for r in _list_opex(cur, project_id, include_inactive=True)},
        }
        verdicts: list[dict[str, Any]] = []
        for index, (edit, _amount, _inflation) in enumerate(parsed):
            row = stored[edit.kind].get(edit.sub_line_id)
            verdict = {"index": index, "kind": edit.kind, "sub_line_id": edit.sub_line_id, "ok": True}
            if row is None:
                verdict.update(ok=False, code="ROW_NOT_FOUND", message="Line not found in this project.")
            elif not row.is_active:
                verdict.update(ok=False, code="ROW_INACTIVE", message="Line is deactivated.")
            elif row.updated_at != edit.row_version:
                verdict.update(ok=False, code="ROW_STALE", message="Line was changed since the page loaded.")
            verdicts.append(verdict)
        if not all(v["ok"] for v in verdicts):
            raise CostBatchConflictError("One or more lines changed; nothing was saved.", verdicts)

        for index, (edit, amount, inflation) in enumerate(parsed):
            row = stored[edit.kind][edit.sub_line_id]
            notes = row.comments if edit.notes is None else edit.notes
            label = edit.label.strip()
            if edit.kind == "capex":
                result = _update_capex(cur, project_id=project_id, sub_line_id=edit.sub_line_id, label=label,
                                       amount_keur=amount, comments=notes, row_version=edit.row_version)
            else:
                result = _update_opex(cur, project_id=project_id, sub_line_id=edit.sub_line_id, label=label,
                                      amount_keur=amount,
                                      inflation_pct=row.inflation_pct if inflation is None else inflation,
                                      comments=notes, row_version=edit.row_version)
            if result is None:      # cannot happen inside BEGIN EXCLUSIVE after verification; fail closed anyway
                raise CostBatchConflictError("A line changed during the save; nothing was saved.", [
                    {"index": index, "kind": edit.kind, "sub_line_id": edit.sub_line_id, "ok": False,
                     "code": "ROW_STALE", "message": "Line was changed during the save."}])
            saved.append({"kind": edit.kind, "sub_line_id": edit.sub_line_id, "row_version": result.updated_at,
                          "label": result.label, "amount_keur": result.amount_keur})
    return saved, hash_out.value


__all__ = ["CostBatchError", "CostBatchInvalidError", "CostBatchConflictError", "CostLineEdit",
           "MAX_BATCH_LINES", "update_cost_lines_batch"]
