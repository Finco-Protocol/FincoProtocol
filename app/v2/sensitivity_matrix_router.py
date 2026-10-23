"""Two-driver sensitivity matrix routes (M3).

Read-only, ephemeral analysis.  The Working Copy, scenarios, Last Run and Run History are never written, and the
result is never presented as CURRENT.  One admitted request executes ONE ordered batch in the bounded model executor.
"""
from __future__ import annotations

import logging
import time
from html import escape

from fastapi import APIRouter, Depends, Form, Request
from fastapi.responses import HTMLResponse

from app.auth import resolve_request_session
from app.persistence.projects_repository import resolve_accessible_project
from app.ui.protected_reference_service import is_protected_reference
from app.utils.workbook_flag import require_v2_active
from app.v2.sensitivity_matrix_projection import (
    MAX_CELLS, MatrixRequestError, build_matrix, drivers_for, parse_grid_size, parse_levels, parse_threshold,
    resolve_metric, resolve_pair, supported_metrics, vertical_key,
)

router = APIRouter()
log = logging.getLogger(__name__)
NO_STORE = {"Cache-Control": "no-store"}
#: Marks a typed user-facing error fragment; static/js/sensitivity_matrix.js lets HTMX swap it (HTMX ignores 4xx).
ERROR_HEADERS = {**NO_STORE, "X-Finco-Matrix-Error": "1"}


def _templates():
    from app.v2.router import _templates as templates
    return templates


def _error(status: int, code: str, message: str) -> HTMLResponse:
    return HTMLResponse(
        f'<p class="d-context v2-matrix-error" role="alert" data-testid="matrix-error" data-code="{escape(code)}">'
        f"{escape(code)} — {escape(message)} Nothing was changed.</p>", status_code=status, headers=ERROR_HEADERS)


def _scope(request: Request, project: str):
    user = resolve_request_session(request)
    if not user:
        return None, None, None, _error(401, "MATRIX_UNAUTHENTICATED", "Sign in to run a sensitivity matrix.")
    record, owner = resolve_accessible_project(user.user_id, project)
    if record is None:
        return None, None, None, _error(404, "MATRIX_PROJECT_NOT_FOUND", "Project not found.")
    return user, record, owner, None


@router.post("/workbook/sensitivity/matrix/run", response_class=HTMLResponse)
async def matrix_run(
    request: Request,
    project: str = Form(...),
    driver_a: str = Form(...),
    driver_b: str = Form(...),
    metric: str = Form(...),
    grid: str = Form(default=""),
    levels_a: str = Form(default=""),
    levels_b: str = Form(default=""),
    threshold: str = Form(default=""),
    scenario_id: str = Form(default=""),
    _: None = Depends(require_v2_active),
):
    from app.persistence.workspace_repository import get_workspace_state
    from app.runtime.model_execution import (
        BUSY_MESSAGE, ModelExecutionBusy, ModelExecutionTimeout, run_model_process,
    )
    from app.runtime.native_activation import run_activated
    from app.services.sensitivity_execution import sensitivity_grid_size_error
    from app.services import sensitivity_matrix as svc
    from app.v2.post_run_context import PostRunContextChanged, PostRunRequestContext
    from app.workbook.workbook_identity import WorkbookIdentityError

    user, record, owner, failure = _scope(request, project)
    if failure is not None:
        return failure
    if is_protected_reference(record):
        return _error(409, "MATRIX_PROTECTED_REFERENCE", "Protected reference — create a working copy to run sensitivity.")
    vertical = vertical_key(record.project_type)
    try:
        spec_a, spec_b = resolve_pair(driver_a, driver_b, vertical)
        size = parse_grid_size(grid)
        axis_a, axis_b = parse_levels(levels_a, spec_a, size), parse_levels(levels_b, spec_b, size)
        _k, _label, _unit, fmt, _src = resolve_metric(metric)
        limit = parse_threshold(threshold, fmt)
        cells = len(axis_a) * len(axis_b)
        evaluations = cells + (0 if (0 in axis_a and 0 in axis_b) else 1)
        oversize = sensitivity_grid_size_error(evaluations)
        if oversize or cells > MAX_CELLS:
            raise MatrixRequestError("SENSITIVITY_GRID_TOO_LARGE", oversize or f"{cells} cells exceed {MAX_CELLS}.")
    except MatrixRequestError as exc:
        return _error(422, exc.code, exc.message)

    ws = get_workspace_state(user_id=owner, project_id=record.project_id)
    if ws is None:
        return _error(404, "MATRIX_WORKSPACE_NOT_FOUND", "Workspace not found.")
    try:
        context = PostRunRequestContext.capture(owner_id=owner, project_id=record.project_id)
        basis = svc.resolve_basis(workspace_owner=owner, project_record=record, ws=ws,
                                  scenario_id=scenario_id or None)
    except MatrixRequestError as exc:
        status = 404 if exc.code == "MATRIX_SCENARIO_NOT_FOUND" else 422
        return _error(status, exc.code, exc.message)
    except (PostRunContextChanged, WorkbookIdentityError, PermissionError):
        return _error(409, "MATRIX_CONTEXT_CHANGED", "The workspace changed. Reopen Sensitivity and retry.")

    try:
        work, failures, evidence, base_pi, reuse_zero = svc.build_all(basis, spec_a, axis_a, spec_b, axis_b)
    except MatrixRequestError as exc:
        return _error(422, exc.code, exc.message)
    except Exception as exc:  # noqa: BLE001 - base construction failure fails the whole request, typed
        log.exception("sensitivity_matrix: base construction failed project=%s", project)
        return _error(422, "MATRIX_BASE_INPUTS_UNAVAILABLE", str(exc)[:120])

    batch = [pi for _idx, pi in work] + ([base_pi] if base_pi is not None else [])
    started = time.perf_counter()
    outputs: list[dict] = []
    if batch:
        try:
            outputs = await run_activated(run_model_process, svc.run_matrix_points, svc.RUNTIME_KEYS[vertical], batch)
        except ModelExecutionBusy:
            return HTMLResponse(f"<p>{BUSY_MESSAGE}</p>", status_code=429,
                                headers={"Retry-After": "5", "X-Finco-Model-Busy": "1", **NO_STORE})
        except ModelExecutionTimeout:
            outputs = [{"error": "CALCULATION_TIMEOUT"}] * len(batch)
        except Exception:  # noqa: BLE001
            log.exception("sensitivity_matrix: executor failure project=%s", project)
            outputs = [{"error": "Calculation could not be completed."}] * len(batch)
    elapsed = time.perf_counter() - started

    cell_outputs: dict = {}
    for (idx, _pi), out in zip(work, outputs):
        cell_outputs[idx] = out
    for idx, info in failures.items():
        cell_outputs[idx] = {"error": info["error"]}
    base_output = outputs[len(work)] if base_pi is not None else cell_outputs.get(
        (axis_a.index(0), axis_b.index(0)))
    view = build_matrix(spec_a=spec_a, spec_b=spec_b, levels_a=axis_a, levels_b=axis_b, metric_key=metric,
                        cell_outputs=cell_outputs, base_output=base_output, threshold=limit, shock_info=evidence)
    view["run"] = {
        "evaluations": len(batch), "cells": cells, "completed": view["counts"]["OK"],
        "failed": view["counts"]["FAILED"], "unavailable": view["counts"]["UNAVAILABLE"],
        "seconds": round(elapsed, 2), "base_reused_from_zero_cell": reuse_zero,
        "scenario": basis.scenario_display, "scenario_id": basis.scenario_id or "",
        "basis_hash": str(context.identity.composite_hash)[:12],
    }
    view["goal_seek_hint"] = "tariff" in (spec_a.key, spec_b.key)

    try:  # the Working Copy / scenario must not have changed while the batch ran
        context.validate_current()
    except (PostRunContextChanged, WorkbookIdentityError, PermissionError):
        return _error(409, "MATRIX_CONTEXT_CHANGED",
                      "The workspace changed while the matrix was running; results were discarded.")
    html = _templates().get_template("partials/sensitivity_matrix_results.html").render(
        {"request": request, "matrix": view, "project_code": project})
    return HTMLResponse(html, headers=NO_STORE)


def register_template_globals() -> None:
    """Expose the (pure) driver / metric catalogues to the Sensitivity sheet template that hosts the matrix form."""
    from app.v2.router import _templates as templates

    templates.env.globals["matrix_drivers"] = lambda vertical: drivers_for(vertical)
    templates.env.globals["matrix_metrics"] = supported_metrics
