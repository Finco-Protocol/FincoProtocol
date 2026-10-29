"""app.v2.save_all_commands — ONE all-or-none Save across Project/PPA/CAPEX/OPEX/Financing-scalar edits.

No new validation authority
---------------------------
This module owns no financial rule and no persistence format.  It composes the three existing guarded
writers, each already split into a *body that runs on the caller's cursor* and its original single-section
wrapper (behaviour of the wrappers is unchanged):

* scalar cells   — ``workspace_repository.v2_apply_batch_draft_update_in_tx`` (C0 batch validators, F3 / senior /
  bankability / capacity guards, side-effect fences);
* revenue contracts — ``revenue_contracts_service.save_contracts_in_tx`` (scenario-aware);
* CAPEX/OPEX lines — ``cost_batch_commands.apply_cost_lines_in_tx`` (row-version verified before the first write).

Transaction contract
--------------------
Shape validation first (nothing opened).  Then exactly one ``BEGIN EXCLUSIVE``, one idempotency lookup, ONE composite
identity CAS, the bodies in the fixed order scalar -> contracts -> cost lines, ONE final identity recompute (hash +
``dirty=1``), the idempotency row, and ONE ``COMMIT``.  Any exception rolls the whole transaction back: no cell, no
contract, no line, no hash, no dirty flag and no ledger row survives.  The model is never run and Run history is
never touched; a persisted change leaves the Last Run STALE through the canonical freshness authority.

Idempotency: ``(user, project, request_id)`` is unique.  The same id with the same canonical body returns the stored
outcome without writing; the same id with a different body is refused.  F3 financing collections are outside Save All.
"""
from __future__ import annotations

import hashlib
import json
import re
from dataclasses import dataclass, field
from typing import Any, Optional, Sequence

from app.persistence._helpers import _now_utc
from app.persistence.db import get_connection
from app.v2.capex_commands import (
    _check_project_allows as _capex_project_allows,
    _check_workbook_version,
    check_identity_in_tx,
    finalize_identity_in_tx,
)
from app.v2.cost_batch_commands import (
    MAX_BATCH_LINES, CostBatchInvalidError, CostLineEdit, apply_cost_lines_in_tx, validate_cost_line_edits,
)
from app.v2.opex_commands import _check_project_allows as _opex_project_allows

MAX_ITEMS = 200                 # cells + lines + (1 if a contracts document)
MAX_CELLS = 50                  # the C0 batch bound
MAX_CONTRACTS_BYTES = 200_000   # same bound as the contracts form
_REQUEST_ID = re.compile(r"^[A-Za-z0-9_-]{8,64}$")

#: Fields with their own, separately authorised editor: never part of a Save All cell list.
EXCLUDED_FIELDS = frozenset({"debt.financing.instruments", "revenue.multistream.contracts"})


class SaveAllError(ValueError):
    """Base: stable ``code`` for the HTTP layer; nothing was written."""

    code = "SAVE_ALL_REJECTED"

    def __init__(self, message: str, code: Optional[str] = None, detail: Optional[dict[str, Any]] = None):
        super().__init__(message)
        if code:
            self.code = code
        self.detail = detail or {}


class SaveAllInvalid(SaveAllError):
    code = "SAVE_ALL_INVALID"


class SaveAllRequestIdReused(SaveAllError):
    code = "SAVE_ALL_REQUEST_ID_REUSED"


@dataclass(frozen=True)
class SaveAllInput:
    request_id: str
    workbook_version: str
    content_hash: str
    scenario_id: Optional[str]
    cells: Sequence[tuple[str, str]] = field(default_factory=tuple)
    contracts_json: Optional[str] = None
    cost_lines: Sequence[CostLineEdit] = field(default_factory=tuple)

    def canonical_body(self) -> str:
        return json.dumps({
            "workbook_version": self.workbook_version, "content_hash": self.content_hash, "scenario_id": self.scenario_id,
            "cells": [list(c) for c in self.cells], "contracts_json": self.contracts_json,
            "cost_lines": [[l.kind, l.sub_line_id, l.label, str(l.amount_keur), l.row_version,
                            None if l.inflation_pct is None else str(l.inflation_pct), l.notes] for l in self.cost_lines],
        }, sort_keys=True, separators=(",", ":"))


@dataclass(frozen=True)
class SaveAllResult:
    content_hash: str
    counts: dict[str, int]
    replayed: bool = False


def _validate_shape(data: SaveAllInput) -> list:
    if not _REQUEST_ID.match(data.request_id or ""):
        raise SaveAllInvalid("A request id of 8-64 letters, digits, '-' or '_' is required.", "SAVE_ALL_REQUEST_ID_INVALID")
    n_cells, n_lines = len(data.cells), len(data.cost_lines)
    n_contracts = 1 if data.contracts_json is not None else 0
    total = n_cells + n_lines + n_contracts
    if total < 1:
        raise SaveAllInvalid("There is nothing to save.", "SAVE_ALL_EMPTY")
    if total > MAX_ITEMS:
        raise SaveAllInvalid(f"At most {MAX_ITEMS} items can be saved together.", "SAVE_ALL_TOO_MANY_ITEMS")
    if n_cells > MAX_CELLS:
        raise SaveAllInvalid(f"At most {MAX_CELLS} scalar cells can be saved together.", "SAVE_ALL_TOO_MANY_CELLS")
    if n_lines > MAX_BATCH_LINES:
        raise SaveAllInvalid(f"At most {MAX_BATCH_LINES} CAPEX/OPEX lines can be saved together.", "SAVE_ALL_TOO_MANY_LINES")
    if data.contracts_json is not None and len(data.contracts_json.encode("utf-8")) > MAX_CONTRACTS_BYTES:
        raise SaveAllInvalid("The contracts document is too large.", "SAVE_ALL_CONTRACTS_TOO_LARGE")
    for field_id, _value in data.cells:
        if field_id in EXCLUDED_FIELDS:
            raise SaveAllInvalid(
                f"{field_id} has its own editor and is not part of Save All.", "SAVE_ALL_SECTION_NOT_SUPPORTED",
                {"field_id": field_id})
    # Cost-line shape (duplicates, finite numbers, row versions) BEFORE any transaction is opened.
    return validate_cost_line_edits(data.cost_lines) if n_lines else []


def save_all(*, project_record: Any, user_id: str, data: SaveAllInput) -> SaveAllResult:
    """Apply every submitted section atomically.  Raises on ANY failure with nothing persisted."""
    from app.persistence.workspace_repository import v2_apply_batch_draft_update_in_tx
    from app.workbook.revenue_contracts_service import save_contracts_in_tx

    _capex_project_allows(project_record)
    _opex_project_allows(project_record)
    _check_workbook_version(data.workbook_version)
    parsed_lines = _validate_shape(data)

    project_id: str = project_record.project_id
    body = data.canonical_body()
    body_sha = hashlib.sha256(body.encode("utf-8")).hexdigest()
    counts = {"cells": len(data.cells), "contracts": 1 if data.contracts_json is not None else 0, "cost_lines": len(data.cost_lines)}

    conn = get_connection()
    conn.execute("BEGIN EXCLUSIVE")
    cur = conn.cursor()
    try:
        prior = cur.execute(
            "SELECT body_sha256, outcome_json FROM save_all_requests WHERE user_id=? AND project_id=? AND request_id=?",
            (user_id, project_id, data.request_id)).fetchone()
        if prior is not None:
            if prior["body_sha256"] != body_sha:
                raise SaveAllRequestIdReused("This request id was already used with different content; nothing was saved.")
            stored = json.loads(prior["outcome_json"])
            conn.execute("ROLLBACK")          # read-only replay: nothing to commit
            return SaveAllResult(content_hash=stored["content_hash"], counts=stored["counts"], replayed=True)

        ws_row = check_identity_in_tx(cur, user_id, project_id, data.content_hash)      # the ONE composite CAS
        ws_full = cur.execute("SELECT workspace_id, active_scenario_id FROM workspace_states WHERE user_id=? AND project_id=?",
                              (user_id, project_id)).fetchone()
        if ws_full["active_scenario_id"] != data.scenario_id:
            from app.workbook.update_service import StaleContentError
            raise StaleContentError("SAVE_ALL_SCENARIO_MISMATCH")

        if data.cells:
            v2_apply_batch_draft_update_in_tx(
                cur, user_id=user_id, project_id=project_id, expected_workspace_id=ws_full["workspace_id"],
                expected_scenario_id=data.scenario_id, expected_content_hash=data.content_hash,
                expected_workbook_version=data.workbook_version, updates=[(f, v) for f, v in data.cells], skip_cas=True)
        if data.contracts_json is not None:
            save_contracts_in_tx(cur, owner=user_id, project_id=project_id, expected_hash=data.content_hash,
                                 raw=data.contracts_json, skip_cas=True)
        if parsed_lines:
            apply_cost_lines_in_tx(cur, project_id, parsed_lines)

        new_hash = finalize_identity_in_tx(cur, user_id, project_id, ws_row)               # ONE final identity
        cur.execute(
            "INSERT INTO save_all_requests (user_id, project_id, request_id, body_sha256, outcome_json, created_at) VALUES (?,?,?,?,?,?)",
            (user_id, project_id, data.request_id, body_sha,
             json.dumps({"content_hash": new_hash, "counts": counts}, sort_keys=True), _now_utc().isoformat()))
        conn.execute("COMMIT")
        return SaveAllResult(content_hash=new_hash, counts=counts)
    except Exception:
        try:
            conn.execute("ROLLBACK")
        except Exception:
            pass
        raise
    finally:
        cur.close()
        conn.close()


__all__ = ["MAX_ITEMS", "MAX_CELLS", "MAX_CONTRACTS_BYTES", "SaveAllError", "SaveAllInvalid", "SaveAllRequestIdReused",
           "SaveAllInput", "SaveAllResult", "save_all"]
