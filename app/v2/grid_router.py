"""app.v2.grid_router — Hybrid Inputs grid: validate / atomic batch Save / sheet refresh.

Presentation-facing routes for the Excel-like input grids (CAPEX, OPEX).  They add NO economic
authority:

* ``POST /workbook/grid/validate``  — dry validation of staged cells with the canonical
  single-field validator (``WorkbookUpdateService.validate_field_update``) and the shared
  technology-applicability rule.  Persists nothing, runs no engine.
* ``POST /workbook/grid/save``      — ONE call to the existing C0 canonical batch writer
  (``WorkbookUpdateService.apply_batch_draft_update`` → ``v2_atomic_batch_draft_update``,
  a single ``BEGIN EXCLUSIVE`` transaction with composite CAS).  All cells persist or none.
  The model is never executed; a persisted economic change classifies the existing Last Run
  as STALE through the canonical freshness authority.
* ``POST /workbook/grid/cost-lines/save`` — ONE atomic Save of several EXISTING CAPEX/OPEX line items
  (``app.v2.cost_batch_commands``: one ``BEGIN EXCLUSIVE`` transaction around the existing row-versioned
  repositories, composite CAS, rollback of every row on any failure).  Never the scalar C0 writer.
* ``GET  /workbook/grid/sheet``     — re-render of one sheet partial (same renderer the
  per-field editor uses) so totals refresh without a full page load.

Session ownership, CSRF and a JSON content type are required.  Reference projects are never
mutable here.
"""
from __future__ import annotations

from typing import Any, Literal, Optional

from fastapi import APIRouter, Depends, Form, Request
from fastapi.responses import HTMLResponse, JSONResponse
from pydantic import BaseModel, Field, TypeAdapter, ValidationError

from app.auth import resolve_request_session, validate_csrf_token
from app.persistence.projects_repository import resolve_accessible_project
from app.persistence.workspace_repository import get_workspace_state
from app.services.project_library_service import is_protected_reference
from app.utils.workbook_flag import require_v2_active
from app.workbook.financing_csrf import extract_bound_token
from app.workbook.input_set import ProjectInputSet
from app.workbook.registry import WORKBOOK
from app.workbook.update_service import (
    BatchApplyError,
    FieldValidationError,
    NonEditableFieldError,
    ProtectedReferenceError,
    StaleContentError,
    UnknownFieldError,
    VersionMismatchError,
    WorkbookUpdateService,
    _assert_batch_field_applicable,
)
from app.workbook.workbook_identity import assemble_consistent_for_get

router = APIRouter()

# Canonical F3 rejections raised inside the C0 transaction are ValueError subclasses carrying a stable
# ``.code``.  They are handled through the ValueError boundary below: this router must NOT import the
# financing engine or the F3 candidate package (governance-owned boundaries).
_F3_CONFLICT_CODES = frozenset({
    "F3_COMPETING_FINANCING_EDITOR_REJECTED", "F3_COLLECTION_EDITOR_ONLY", "F3_SELECTED_SCENARIO_UNAVAILABLE",
})

MAX_GRID_CELLS = 50          # identical to the C0 batch bound
MAX_VALUE_CHARS = 64

# Sheets whose partial can be re-rendered through the grid refresh route.
GRID_SHEETS = ("capex", "opex", "revenue", "project_setup", "tax")


class GridCell(BaseModel):
    field_id: str = Field(..., min_length=1, max_length=200)
    value: str = Field("", max_length=MAX_VALUE_CHARS)


class GridValidateRequest(BaseModel):
    project: str
    csrf_token: str
    cells: list[GridCell] = Field(..., min_length=1, max_length=MAX_GRID_CELLS)


class GridSaveRequest(GridValidateRequest):
    workbook_version: str
    content_hash: str
    scenario_id: Optional[str] = None


def _json(payload: dict[str, Any], status: int = 200) -> JSONResponse:
    return JSONResponse(payload, status_code=status, headers={"Cache-Control": "no-store"})


def _resolve(request: Request, project: str):
    """(user, record, owner, ws) or a ready JSONResponse for the failure."""
    user = resolve_request_session(request)
    if user is None:
        return _json({"ok": False, "code": "AUTH_REQUIRED"}, 401)
    record, owner = resolve_accessible_project(user.user_id, project)
    if record is None:
        return _json({"ok": False, "code": "PROJECT_NOT_FOUND"}, 404)
    if is_protected_reference(record):
        return _json({"ok": False, "code": "PROTECTED_REFERENCE",
                      "message": "Protected reference models are read-only. Create a working copy to edit."}, 403)
    if owner != user.user_id:
        return _json({"ok": False, "code": "OWNER_MISMATCH"}, 403)
    ws = get_workspace_state(owner, record.project_id)
    if ws is None:
        return _json({"ok": False, "code": "WORKSPACE_NOT_FOUND"}, 404)
    return user, record, owner, ws


def _cell_verdicts(record, cells: list[GridCell]) -> list[dict[str, Any]]:
    """Canonical per-cell verdicts (no persistence).  Duplicates are rejected, never merged."""
    verdicts: list[dict[str, Any]] = []
    seen: set[str] = set()
    for cell in cells:
        verdict: dict[str, Any] = {"field_id": cell.field_id, "ok": True}
        try:
            if cell.field_id in seen:
                raise BatchApplyError("BATCH_DUPLICATE_FIELD", cell.field_id)
            seen.add(cell.field_id)
            check = WorkbookUpdateService.validate_field_update(cell.field_id, cell.value)
            if not check.is_valid:
                verdict.update(ok=False, code="FIELD_INVALID", message=check.error,
                               error_class=check.error_class.value if check.error_class else None)
            else:
                _assert_batch_field_applicable(
                    cell.field_id, project_type=record.project_type or "",
                    template_source=record.template_source or "")
        except (UnknownFieldError, NonEditableFieldError) as exc:
            verdict.update(ok=False, code=type(exc).__name__, message=str(exc), error_class=None)
        except BatchApplyError as exc:
            verdict.update(ok=False, code=exc.code, message=str(exc), error_class=None)
        verdicts.append(verdict)
    return verdicts


@router.post("/workbook/grid/validate")
async def grid_validate(body: GridValidateRequest, request: Request,
                        _: None = Depends(require_v2_active)):
    from app.workbook.mutation_csrf import validate_mutation_token
    if not (validate_csrf_token(body.csrf_token) or
            validate_mutation_token(request, body.project, body.csrf_token, "grid-save")):
        return _json({"ok": False, "code": "CSRF_INVALID"}, 403)
    resolved = _resolve(request, body.project)
    if isinstance(resolved, JSONResponse):
        return resolved
    _user, record, _owner, _ws = resolved
    verdicts = _cell_verdicts(record, body.cells)
    return _json({"ok": all(v["ok"] for v in verdicts), "cells": verdicts})


@router.post("/workbook/grid/save")
async def grid_save(body: GridSaveRequest, request: Request,
                    _: None = Depends(require_v2_active)):
    """Atomic batch Save over the C0 canonical writer.  Never runs the model."""
    from app.workbook.mutation_csrf import validate_mutation_token
    if not validate_mutation_token(request, body.project, body.csrf_token, "grid-save"):
        return _json({"ok": False, "code": "CSRF_INVALID"}, 403)
    resolved = _resolve(request, body.project)
    if isinstance(resolved, JSONResponse):
        return resolved
    user, record, owner, ws = resolved


    # Per-cell attribution BEFORE the transaction; the writer repeats every check atomically.
    verdicts = _cell_verdicts(record, body.cells)
    if not all(v["ok"] for v in verdicts):
        return _json({"ok": False, "code": "GRID_VALIDATION_FAILED", "cells": verdicts}, 422)

    updates = [(c.field_id, c.value) for c in body.cells]
    try:
        WorkbookUpdateService.apply_batch_draft_update(
            ws=ws, updates=updates,
            content_hash=body.content_hash,
            workbook_version=body.workbook_version,
            expected_scenario_id=body.scenario_id,
            project_record=record, actor_user_id=user.user_id,
        )
    except (StaleContentError, VersionMismatchError) as exc:
        return _json({"ok": False, "code": getattr(exc, "args", ["STALE"])[0] or "STALE_CONTENT",
                      "message": "The model changed since this page loaded. Reload to continue; "
                                 "your staged edits were not saved.",
                      "reload": True}, 409)
    except ProtectedReferenceError:
        return _json({"ok": False, "code": "PROTECTED_REFERENCE"}, 403)
    except FieldValidationError as exc:
        from app.input_adapter import rate_unit_error_code
        return _json({"ok": False, "code": rate_unit_error_code(exc) or "FIELD_INVALID", "message": str(exc),
                      "error_class": exc.error_class.value if exc.error_class else None}, 422)
    except (BatchApplyError, UnknownFieldError, NonEditableFieldError) as exc:
        return _json({"ok": False, "code": getattr(exc, "code", type(exc).__name__),
                      "message": str(exc)}, 422)
    except ValueError as exc:
        # ValueError is the canonical fail-closed boundary of the C0 transaction (it rolled back: nothing
        # persisted, CAS hash and Last Run unchanged).  A recognised F3_* code keeps its meaning:
        # authority/scope conflicts are 409, other F3 validation failures 422.  Anything else is the
        # generic BATCH_REJECTED 422.  Never an unhandled 500.
        code = str(getattr(exc, "code", "") or "")
        if code.startswith("F3_"):
            return _json({"ok": False, "code": code,
                          "message": "Financing authority rejected the batch; nothing was saved. "
                                     "Edit financing fields in the Senior Debt financing editor.",
                          "detail": str(exc)}, 409 if code in _F3_CONFLICT_CODES else 422)
        return _json({"ok": False, "code": "BATCH_REJECTED", "message": str(exc)}, 422)

    fresh = get_workspace_state(owner, record.project_id) or ws
    identity = assemble_consistent_for_get(owner, record.project_id, WORKBOOK.version)
    from app.workbook.runtime_authority import resolve_runtime_freshness
    freshness = resolve_runtime_freshness(fresh, current_composite_hash=identity.composite_hash)
    pis = ProjectInputSet.from_snapshot(fresh.draft_snapshot, workbook=WORKBOOK)
    return _json({
        "ok": True,
        "saved": [{"field_id": fid, "value": _display(pis.get(fid))} for fid, _ in updates],
        "content_hash": identity.composite_hash,
        "workbook_version": WORKBOOK.version,
        "scenario_id": fresh.active_scenario_id,
        "run_state": freshness.state.value,
        "model_executed": False,
    })


# ── CAPEX / OPEX line items: staged multi-row atomic Save ────────────────────────────────────────

class CostLinePayload(BaseModel):
    kind: Literal["capex", "opex"]
    sub_line_id: str = Field(..., min_length=1, max_length=64)
    label: str = Field(..., max_length=200)
    amount_keur: str = Field(..., max_length=MAX_VALUE_CHARS)
    row_version: str = Field(..., min_length=1, max_length=64)
    inflation_pct: Optional[str] = Field(None, max_length=MAX_VALUE_CHARS)
    notes: Optional[str] = Field(None, max_length=2000)


_COST_LINES = TypeAdapter(list[CostLinePayload])


@router.post("/workbook/grid/cost-lines/save")
async def grid_cost_lines_save(
    request: Request,
    project: str = Form(...),
    csrf_token: str = Form(""),
    workbook_version: str = Form(...),
    content_hash: str = Form(...),
    sheet: str = Form("capex"),
    payload: str = Form(..., max_length=200_000),
    _: None = Depends(require_v2_active),
):
    """Atomic Save of staged CAPEX/OPEX line edits.  All lines persist or none; the model is never run.

    Success returns the re-rendered ``sheet`` partial plus the same post-Save out-of-band refresh as a
    single-row save (toolbar/strip STALE state, run controls with the new CAS token).  Failure is a
    JSON 4xx that the htmx client does not swap, so every typed value stays on screen.
    """
    from app.v2.capex_commands import (
        CapexCommandError, CapexProtectedReferenceError, CapexStaleIdentityError, CapexVersionMismatchError)
    from app.v2.cost_batch_commands import (
        MAX_BATCH_LINES, CostBatchConflictError, CostBatchInvalidError, CostLineEdit, update_cost_lines_batch)
    from app.v2.opex_commands import OpexProtectedReferenceError, OpexStaleIdentityError, OpexVersionMismatchError

    from app.workbook.mutation_csrf import validate_mutation_token
    if not validate_mutation_token(request, project, csrf_token, "grid-cost-lines-save"):
        return _json({"ok": False, "code": "CSRF_INVALID"}, 403)
    if sheet not in ("capex", "opex"):
        return _json({"ok": False, "code": "SHEET_UNKNOWN"}, 404)
    resolved = _resolve(request, project)
    if isinstance(resolved, JSONResponse):
        return resolved
    user, record, owner, ws = resolved


    try:
        lines = _COST_LINES.validate_json(payload)
    except ValidationError:
        return _json({"ok": False, "code": "COST_BATCH_INVALID", "message": "Malformed edited lines; nothing was saved."}, 422)
    if not 1 <= len(lines) <= MAX_BATCH_LINES:
        return _json({"ok": False, "code": "COST_BATCH_INVALID",
                      "message": f"Between 1 and {MAX_BATCH_LINES} lines can be saved together."}, 422)

    edits = [CostLineEdit(kind=l.kind, sub_line_id=l.sub_line_id, label=l.label, amount_keur=l.amount_keur,
                          row_version=l.row_version, inflation_pct=l.inflation_pct, notes=l.notes) for l in lines]
    try:
        _saved, new_hash = update_cost_lines_batch(
            project_record=record, user_id=user.user_id, edits=edits,
            workbook_version=workbook_version, expected_content_hash=content_hash)
    except (CapexProtectedReferenceError, OpexProtectedReferenceError):
        return _json({"ok": False, "code": "PROTECTED_REFERENCE"}, 403)
    except (CapexStaleIdentityError, OpexStaleIdentityError, CapexVersionMismatchError, OpexVersionMismatchError):
        return _json({"ok": False, "code": "STALE_CONTENT", "reload": True,
                      "message": "The model changed since this page loaded. Reload to continue; "
                                 "your staged edits were not saved."}, 409)
    except CostBatchConflictError as exc:
        return _json({"ok": False, "code": exc.code, "reload": True, "message": str(exc), "lines": exc.verdicts}, 409)
    except CostBatchInvalidError as exc:
        return _json({"ok": False, "code": exc.code, "message": str(exc), "lines": exc.verdicts}, 422)
    except (CapexCommandError, ValueError) as exc:
        return _json({"ok": False, "code": "BATCH_REJECTED", "message": str(exc)}, 422)

    from app.workbook.service import WorkbookService
    fresh = get_workspace_state(owner, record.project_id) or ws
    pis = WorkbookService.build_draft_input_set_from_workspace(fresh).with_composite_hash(new_hash)
    if sheet == "opex":
        from app.v2.opex_router import _render_opex_sheet_with_oob as _render
    else:
        from app.v2.capex_router import _render_capex_sheet_with_oob as _render
    response = _render(request, record, pis, fresh, project, workspace_owner=owner)
    response.headers["Cache-Control"] = "no-store"
    response.headers["X-Cost-Batch-Saved"] = str(len(lines))
    return response


SAVE_ALL_CSRF_PURPOSE = "model-save-all-v1"

# ── Save All: ONE all-or-none transaction across scalar cells, PPA contracts and CAPEX/OPEX lines ─────────────────

class SaveAllCostLine(BaseModel):
    kind: Literal["capex", "opex"]
    sub_line_id: str = Field(..., min_length=1, max_length=64)
    label: str = Field(..., max_length=200)
    amount_keur: str = Field(..., max_length=MAX_VALUE_CHARS)
    row_version: str = Field(..., min_length=1, max_length=64)
    inflation_pct: Optional[str] = Field(None, max_length=MAX_VALUE_CHARS)
    notes: Optional[str] = Field(None, max_length=2000)


class SaveAllBody(BaseModel):
    project: str
    csrf_token: str
    workbook_version: str
    content_hash: str
    scenario_id: Optional[str] = None
    request_id: str = Field(..., min_length=8, max_length=64)
    cells: list[GridCell] = Field(default_factory=list, max_length=200)
    contracts_json: Optional[str] = Field(None, max_length=250_000)
    cost_lines: list[SaveAllCostLine] = Field(default_factory=list, max_length=200)


@router.post("/workbook/save-all")
async def workbook_save_all(body: SaveAllBody, request: Request, _: None = Depends(require_v2_active)):
    """Atomic Save All.  One transaction, one CAS, one commit; never runs the model; idempotent by ``request_id``."""
    # Session-, project- and operation-bound token with its own purpose (the existing bound-token primitive).
    if not validate_csrf_token(extract_bound_token(request, body.project, body.csrf_token, purpose=SAVE_ALL_CSRF_PURPOSE)):
        return _json({"ok": False, "code": "CSRF_INVALID"}, 403)
    resolved = _resolve(request, body.project)
    if isinstance(resolved, JSONResponse):
        return resolved
    user, record, owner, ws = resolved
    if owner != user.user_id:
        return _json({"ok": False, "code": "OWNER_MISMATCH"}, 403)

    from app.v2.capex_commands import (
        CapexCommandError, CapexProtectedReferenceError, CapexStaleIdentityError, CapexVersionMismatchError)
    from app.v2.cost_batch_commands import CostBatchConflictError, CostBatchInvalidError, CostLineEdit
    from app.v2.opex_commands import OpexProtectedReferenceError, OpexStaleIdentityError, OpexVersionMismatchError
    from app.v2.save_all_commands import SaveAllError, SaveAllInput, SaveAllRequestIdReused, save_all
    from app.workbook.revenue_contracts_service import RevenueContractConflict

    data = SaveAllInput(
        request_id=body.request_id, workbook_version=body.workbook_version, content_hash=body.content_hash,
        scenario_id=body.scenario_id, cells=tuple((c.field_id, c.value) for c in body.cells),
        contracts_json=body.contracts_json,
        cost_lines=tuple(CostLineEdit(kind=l.kind, sub_line_id=l.sub_line_id, label=l.label, amount_keur=l.amount_keur,
                                      row_version=l.row_version, inflation_pct=l.inflation_pct, notes=l.notes)
                         for l in body.cost_lines))
    stale = {"ok": False, "reload": True, "message": "The model changed since this page loaded. Reload to continue; "
                                                     "your staged edits were not saved."}
    try:
        result = save_all(project_record=record, user_id=user.user_id, data=data)
    except SaveAllRequestIdReused as exc:
        return _json({"ok": False, "code": exc.code, "message": str(exc)}, 409)
    except SaveAllError as exc:
        return _json({"ok": False, "code": exc.code, "message": str(exc), **exc.detail}, 422)
    except (StaleContentError, VersionMismatchError, CapexStaleIdentityError, OpexStaleIdentityError,
            CapexVersionMismatchError, OpexVersionMismatchError, RevenueContractConflict) as exc:
        return _json({**stale, "code": "STALE_CONTENT", "detail": str(exc)}, 409)
    except (ProtectedReferenceError, CapexProtectedReferenceError, OpexProtectedReferenceError):
        return _json({"ok": False, "code": "PROTECTED_REFERENCE"}, 403)
    except CostBatchConflictError as exc:
        return _json({"ok": False, "code": exc.code, "reload": True, "section": "cost_lines", "message": str(exc),
                      "lines": exc.verdicts}, 409)
    except CostBatchInvalidError as exc:
        return _json({"ok": False, "code": exc.code, "section": "cost_lines", "message": str(exc), "lines": exc.verdicts}, 422)
    except FieldValidationError as exc:
        from app.input_adapter import rate_unit_error_code
        return _json({"ok": False, "code": rate_unit_error_code(exc) or "FIELD_INVALID", "section": "cells",
                      "message": str(exc)}, 422)
    except (BatchApplyError, UnknownFieldError, NonEditableFieldError) as exc:
        return _json({"ok": False, "code": getattr(exc, "code", type(exc).__name__), "section": "cells", "message": str(exc)}, 422)
    except CapexCommandError as exc:
        return _json({"ok": False, "code": "SAVE_ALL_REJECTED", "message": str(exc)}, 422)
    except ValueError as exc:
        code = str(getattr(exc, "code", "") or "")
        if code.startswith("F3_"):
            return _json({"ok": False, "code": code, "message": "Financing authority rejected the request; nothing was saved.",
                          "detail": str(exc)}, 409 if code in _F3_CONFLICT_CODES else 422)
        return _json({"ok": False, "code": "SAVE_ALL_REJECTED", "message": str(exc)}, 422)

    fresh = get_workspace_state(owner, record.project_id) or ws
    identity = assemble_consistent_for_get(owner, record.project_id, WORKBOOK.version)
    from app.workbook.runtime_authority import resolve_runtime_freshness
    freshness = resolve_runtime_freshness(fresh, current_composite_hash=identity.composite_hash)
    return _json({
        "ok": True, "replayed": result.replayed, "saved": result.counts,
        "content_hash": identity.composite_hash, "workbook_version": WORKBOOK.version,
        "scenario_id": fresh.active_scenario_id, "run_state": freshness.state.value, "model_executed": False,
    })


def _display(value: Any) -> str:
    if value is None:
        return ""
    if isinstance(value, bool):
        return "true" if value else "false"
    if isinstance(value, float):
        text = f"{value:.10f}".rstrip("0").rstrip(".")
        return text or "0"
    return str(value)


@router.get("/workbook/grid/sheet", response_class=HTMLResponse)
async def grid_sheet(request: Request, project: str = "", sheet: str = "",
                     presentation_only: bool = False, content_hash: str = "",
                     _: None = Depends(require_v2_active)):
    """Re-render one grid sheet (+ OOB banner / run controls) for an in-place swap."""
    user = resolve_request_session(request)
    if user is None:
        return HTMLResponse("", status_code=401)
    from app.v2.presentation_views import PRESENTATION_SHEETS, render_sheet
    if sheet not in (PRESENTATION_SHEETS if presentation_only else GRID_SHEETS):
        return HTMLResponse("", status_code=404)
    record, owner = resolve_accessible_project(user.user_id, project)
    if record is None:
        return HTMLResponse("", status_code=404)
    if presentation_only:
        return render_sheet(request, record, owner, project, sheet, content_hash)
    ws = get_workspace_state(owner, record.project_id)
    if ws is None:
        return HTMLResponse("", status_code=404)
    from app.v2 import router as _v2
    pis = _v2._build_pis_with_composite_identity(ws, record, owner)
    if sheet == "capex":
        return _v2._render_capex_htmx_sheet(request, pis, ws, record, project, workspace_owner=owner)
    if sheet == "revenue":
        return _v2._render_revenue_htmx_sheet(request, pis, ws, record, project)
    if sheet == "tax":
        return _v2._render_tax_htmx_sheet(request, pis, ws, record, project)
    if sheet == "project_setup":
        return _v2._render_htmx_sheet(request, pis, ws, record, project)
    return _v2._render_opex_htmx_sheet(request, pis, ws, record, project)


@router.get("/workbook/grid/panel", response_class=HTMLResponse)
async def grid_panel(request: Request, project: str = "",
                     refresh_state: bool = False, content_hash: str = "", grid_only: bool = False,
                     _: None = Depends(require_v2_active)):
    """Re-render the Inputs grid panel (after Save) for an in-place swap that keeps focus/scroll."""
    user = resolve_request_session(request)
    if user is None:
        return HTMLResponse("", status_code=401)
    record, owner = resolve_accessible_project(user.user_id, project)
    if record is None:
        return HTMLResponse("", status_code=404)
    if refresh_state:
        from app.v2.presentation_views import render_saved_grid
        return render_saved_grid(request, record, owner, project, content_hash, include_shared_state=not grid_only)
    ws = get_workspace_state(owner, record.project_id)
    if ws is None:
        return HTMLResponse("", status_code=404)
    from app.auth import generate_csrf_token
    from app.v2 import router as _v2
    pis = _v2._build_pis_with_composite_identity(ws, record, owner)
    editable = not is_protected_reference(record)
    ctx = {"request": request, "project_code": project, "project_editable": editable,
           "grid_csrf_token": generate_csrf_token()}
    ctx.update(_v2._build_input_grid_ctx(record, pis, ws, owner, project_editable=editable))
    html = _v2._templates.get_template("partials/sheet_input_grid.html").render(ctx)
    return HTMLResponse(html, headers={"Cache-Control": "no-store"})
