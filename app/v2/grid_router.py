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
* ``GET  /workbook/grid/sheet``     — re-render of one sheet partial (same renderer the
  per-field editor uses) so totals refresh without a full page load.

Session ownership, CSRF and a JSON content type are required.  Reference projects are never
mutable here.
"""
from __future__ import annotations

from typing import Any, Optional

from fastapi import APIRouter, Depends, Request
from fastapi.responses import HTMLResponse, JSONResponse
from pydantic import BaseModel, Field

from app.auth import resolve_request_session, validate_csrf_token
from app.persistence.projects_repository import resolve_accessible_project
from app.persistence.workspace_repository import get_workspace_state
from app.services.project_library_service import is_protected_reference
from app.utils.workbook_flag import require_v2_active
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

# The C0 transaction raises the finco_core FinancingError; the candidate contract defines a sibling
# class of the same shape.  Catch both precisely (never a bare Exception).
from app.model_v2.financing_f3_candidate.contracts import FinancingError as _CandidateFinancingError  # noqa: E402
from finco_core.inputs.financing_instruments import FinancingError as _CoreFinancingError  # noqa: E402

_FINANCING_ERRORS = (_CoreFinancingError, _CandidateFinancingError)
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
    if not validate_csrf_token(body.csrf_token):
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
    if not validate_csrf_token(body.csrf_token):
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
        return _json({"ok": False, "code": "FIELD_INVALID", "message": str(exc),
                      "error_class": exc.error_class.value if exc.error_class else None}, 422)
    except (BatchApplyError, UnknownFieldError, NonEditableFieldError) as exc:
        return _json({"ok": False, "code": getattr(exc, "code", type(exc).__name__),
                      "message": str(exc)}, 422)
    except _FINANCING_ERRORS as exc:
        # Canonical F3 gates raised inside the C0 transaction (competing financing editor, collection
        # editor only, selected scenario unavailable, effective-financing boundary).  The transaction
        # already rolled back: nothing persisted, CAS hash and Last Run unchanged.  Never a 500.
        code = getattr(exc, "code", "F3_REJECTED")
        status = 409 if code in _F3_CONFLICT_CODES else 422
        return _json({"ok": False, "code": code,
                      "message": "Financing authority rejected the batch; nothing was saved. "
                                 "Edit financing fields in the Senior Debt financing editor.",
                      "detail": str(exc)}, status)
    except ValueError as exc:
        # Any other canonical fail-closed rejection (e.g. senior authority gate): controlled, no write.
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
                     _: None = Depends(require_v2_active)):
    """Re-render one grid sheet (+ OOB banner / run controls) for an in-place swap."""
    user = resolve_request_session(request)
    if user is None:
        return HTMLResponse("", status_code=401)
    if sheet not in GRID_SHEETS:
        return HTMLResponse("", status_code=404)
    record, owner = resolve_accessible_project(user.user_id, project)
    if record is None:
        return HTMLResponse("", status_code=404)
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
                     _: None = Depends(require_v2_active)):
    """Re-render the Inputs grid panel (after Save) for an in-place swap that keeps focus/scroll."""
    user = resolve_request_session(request)
    if user is None:
        return HTMLResponse("", status_code=401)
    record, owner = resolve_accessible_project(user.user_id, project)
    if record is None:
        return HTMLResponse("", status_code=404)
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
