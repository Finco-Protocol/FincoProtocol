"""RC-M Lane B — read-only JSON adapter for React Analysis > Sensitivity.

A presentation/adapter layer over the EXISTING canonical sensitivity authorities.  It adds NO economic or persistence
authority and re-implements NO formula:

* every evaluated point is the original ``run_project`` executed in the bounded model executor
  (``app.services.sensitivity_matrix.run_matrix_points`` — the worker the legacy two-driver matrix uses);
* inputs are constructed by the same ``sensitivity_matrix`` service (scenario basis, field/typed shocks, CAPEX/OPEX sub-line fold,
  financing materialisation, rate-lock gate), so a point equals the Legacy result for the same driver and level;
* the only arithmetic here is presentational: a delta against the unshocked base point and a display string via the existing
  catalog formatters.

Endpoints (all GET, ephemeral, nothing is written, the Working Copy / scenarios / Last Run / Run History are never touched and a
result is never presented as a Run):

* ``GET /model-react/analysis/sensitivity/catalog`` — drivers, metrics, limits and the availability of the tool for the project.
* ``GET /model-react/analysis/sensitivity/strip``   — ONE driver at 3–5 levels with every headline KPI per point (5 evaluations).
* ``GET /model-react/analysis/sensitivity/matrix``  — TWO drivers, 3×3 or 5×5, one metric (the canonical matrix view model).

Because these calls spend executor capacity they require the ``X-Finco-React-Request: 1`` header, which a cross-site page cannot
send without a CORS preflight (this is read-only, so no CSRF token is involved).  Feature flag: ``FINCO_MODEL_REACT_V1``.
"""
from __future__ import annotations

import logging
import time
from typing import Any, Optional

from fastapi import APIRouter, Request
from fastapi.responses import JSONResponse

from app.auth import resolve_request_session
from app.v2.react_poc_router import react_poc_enabled

router = APIRouter()
log = logging.getLogger(__name__)

REQUEST_HEADER = "x-finco-react-request"
STRIP_COLUMNS = ("project_irr", "equity_irr", "sponsor_irr", "min_dscr", "avg_dscr", "min_llcr",
                 "project_npv_keur", "equity_npv_keur", "sponsor_moic")
#: The unshocked partner axis of a one-driver strip (level 0 = no shock; never evaluated as a second driver).
_NEUTRAL_PARTNER = ("capex", "opex")


def _json(payload: dict[str, Any], status: int = 200, headers: Optional[dict[str, str]] = None) -> JSONResponse:
    return JSONResponse(payload, status_code=status, headers={"Cache-Control": "no-store", **(headers or {})})


def _fail(status: int, code: str, message: str, headers: Optional[dict[str, str]] = None) -> JSONResponse:
    return _json({"ok": False, "code": code, "message": message + " Nothing was changed."}, status, headers)


def _scope(request: Request, project: str):
    """(record, owner, vertical) or a ready JSONResponse — flag, header, session, project access, protected reference."""
    if not react_poc_enabled():
        return None, None, None, _json({"ok": False, "code": "REACT_POC_DISABLED"}, 404)
    if request.headers.get(REQUEST_HEADER) != "1":
        return None, None, None, _fail(400, "REQUEST_HEADER_REQUIRED", "This analysis can only be started from the FINCO Model workspace.")
    user = resolve_request_session(request)
    if user is None:
        return None, None, None, _json({"ok": False, "code": "AUTH_REQUIRED"}, 401)
    from app.persistence.projects_repository import resolve_accessible_project
    from app.ui.protected_reference_service import is_protected_reference
    from app.v2.sensitivity_matrix_projection import vertical_key

    record, owner = resolve_accessible_project(user.user_id, project)
    if record is None:
        return None, None, None, _json({"ok": False, "code": "PROJECT_NOT_FOUND"}, 404)
    if is_protected_reference(record):
        return None, None, None, _fail(409, "MATRIX_PROTECTED_REFERENCE",
                                       "Protected reference — create a working copy to run sensitivity.")
    vertical = vertical_key(record.project_type)
    if vertical is None:
        return None, None, None, _fail(409, "MATRIX_VERTICAL_UNSUPPORTED",
                                       "Sensitivity supports Solar, Wind and Data Center projects only.")
    return record, owner, vertical, None


def _driver_json(spec) -> dict[str, Any]:
    from app.v2.sensitivity_matrix_projection import level_label

    return {"key": spec.key, "label": spec.label, "unit": spec.unit_label, "mode": spec.mode,
            "default_levels": [{"value": v, "label": level_label(spec, v)} for v in spec.default_levels],
            "default_levels_3": [{"value": v, "label": level_label(spec, v)} for v in spec.default_levels_3],
            "max_abs_level": spec.max_abs_level}


def _vertical_json(record) -> dict[str, Any]:
    from app.v2.react_workspace_router import _vertical_scope

    scope = _vertical_scope(record)
    return {k: scope[k] for k in ("key", "public_name", "pilot_tier", "limitations")}


@router.get("/model-react/analysis/sensitivity/catalog")
async def react_sensitivity_catalog(request: Request, project: str):
    record, owner, vertical, refused = _scope(request, project)
    if refused is not None:
        return refused
    from app.services.sensitivity_execution import MAX_SENSITIVITY_EVALUATIONS
    from app.v2.sensitivity_matrix_projection import GRID_SIZES, MAX_CELLS, drivers_for, supported_metrics

    metrics = supported_metrics()
    return _json({
        "ok": True, "vertical": _vertical_json(record),
        "drivers": [_driver_json(d) for d in drivers_for(vertical)],
        "metrics": metrics, "strip_columns": [k for k in STRIP_COLUMNS if any(m["key"] == k for m in metrics)],
        "limits": {"strip_points": 5, "grid_sizes": list(GRID_SIZES), "max_cells": MAX_CELLS,
                   "max_evaluations": MAX_SENSITIVITY_EVALUATIONS},
        "semantics": {"ephemeral": True, "writes_nothing": True, "is_a_run": False,
                      "basis": "The Working Copy draft (or the selected scenario) as saved on the server — not the last Run."},
    })


async def _evaluate(record, owner: str, vertical: str, spec_a, axis_a, spec_b, axis_b, scenario_id: str):
    """Run the canonical batch.  Returns (state dict) or a ready JSONResponse for a typed refusal."""
    from app.persistence.workspace_repository import get_workspace_state
    from app.runtime.model_execution import BUSY_MESSAGE, ModelExecutionBusy, ModelExecutionTimeout, run_model_process
    from app.runtime.native_activation import activated, native_result
    from app.services import sensitivity_matrix as svc
    from app.services.sensitivity_execution import sensitivity_grid_size_error
    from app.v2.post_run_context import PostRunContextChanged, PostRunRequestContext
    from app.v2.sensitivity_matrix_projection import MAX_CELLS, MatrixRequestError
    from app.workbook.workbook_identity import WorkbookIdentityError

    cells = len(axis_a) * len(axis_b)
    evaluations = cells + (0 if (0 in axis_a and 0 in axis_b) else 1)
    oversize = sensitivity_grid_size_error(evaluations)
    if oversize or cells > MAX_CELLS:
        return _fail(422, "SENSITIVITY_GRID_TOO_LARGE", oversize or f"{cells} cells exceed {MAX_CELLS}.")
    ws = get_workspace_state(user_id=owner, project_id=record.project_id)
    if ws is None:
        return _fail(404, "MATRIX_WORKSPACE_NOT_FOUND", "Workspace not found.")
    try:
        context = PostRunRequestContext.capture(owner_id=owner, project_id=record.project_id)
        basis = svc.resolve_basis(workspace_owner=owner, project_record=record, ws=ws, scenario_id=scenario_id or None)
    except MatrixRequestError as exc:
        return _fail(404 if exc.code == "MATRIX_SCENARIO_NOT_FOUND" else 422, exc.code, exc.message)
    except (PostRunContextChanged, WorkbookIdentityError, PermissionError):
        return _fail(409, "MATRIX_CONTEXT_CHANGED", "The workspace changed. Reopen Sensitivity and retry.")
    try:
        work, failures, evidence, base_pi, reuse_zero = svc.build_all(basis, spec_a, axis_a, spec_b, axis_b)
    except MatrixRequestError as exc:
        return _fail(422, exc.code, exc.message)
    except Exception as exc:  # noqa: BLE001 - base construction failure fails the whole request, typed
        log.exception("react_sensitivity: base construction failed project=%s", record.project_code)
        return _fail(422, "MATRIX_BASE_INPUTS_UNAVAILABLE", str(exc)[:120])

    batch = [pi for _idx, pi in work] + ([base_pi] if base_pi is not None else [])
    started = time.perf_counter()
    outputs: list[dict] = []
    if batch:
        try:
            outputs = native_result(await run_model_process(activated(svc.run_matrix_points), svc.RUNTIME_KEYS[vertical], batch))
        except ModelExecutionBusy:
            return _json({"ok": False, "code": "MODEL_BUSY", "message": BUSY_MESSAGE + " Nothing was changed."}, 429,
                         {"Retry-After": "5", "X-Finco-Model-Busy": "1"})
        except ModelExecutionTimeout:
            outputs = [{"error": "CALCULATION_TIMEOUT"}] * len(batch)
        except Exception:  # noqa: BLE001
            log.exception("react_sensitivity: executor failure project=%s", record.project_code)
            outputs = [{"error": "Calculation could not be completed."}] * len(batch)
    elapsed = time.perf_counter() - started

    cell_outputs: dict = {idx: out for (idx, _pi), out in zip(work, outputs)}
    for idx, info in failures.items():
        cell_outputs[idx] = {"error": info["error"]}
    base_output = outputs[len(work)] if base_pi is not None else cell_outputs.get((axis_a.index(0), axis_b.index(0)))
    try:    # the Working Copy / scenario must not have changed while the batch ran
        context.validate_current()
    except (PostRunContextChanged, WorkbookIdentityError, PermissionError):
        return _fail(409, "MATRIX_CONTEXT_CHANGED", "The workspace changed while the analysis was running; results were discarded.")
    return {
        "cell_outputs": cell_outputs, "base_output": base_output, "evidence": evidence, "evaluations": len(batch),
        "cells": cells, "seconds": round(elapsed, 2), "reuse_zero": reuse_zero,
        "run": {"evaluations": len(batch), "cells": cells, "seconds": round(elapsed, 2), "base_reused_from_zero_cell": reuse_zero,
                "scenario": basis.scenario_display, "scenario_id": basis.scenario_id or "",
                "basis_hash": str(context.identity.composite_hash)[:12], "ephemeral": True, "writes_nothing": True,
                "is_a_run": False},
    }


def _request_error(exc) -> JSONResponse:
    return _fail(422, exc.code, exc.message)


@router.get("/model-react/analysis/sensitivity/strip")
async def react_sensitivity_strip(request: Request, project: str, driver: str = "", levels: str = "", scenario_id: str = ""):
    record, owner, vertical, refused = _scope(request, project)
    if refused is not None:
        return refused
    from app.services import sensitivity_matrix as svc  # noqa: F401  (imported here so a failure is typed below)
    from app.v2.output_metric_projection import KPI_CATALOG, _apply_fmt, _safe_float
    from app.v2.sensitivity_matrix_projection import (
        DRIVERS, MatrixRequestError, drivers_for, format_delta, level_label, parse_levels,
    )

    try:
        spec = DRIVERS.get(driver)
        if spec is None or vertical not in spec.verticals:
            raise MatrixRequestError("MATRIX_DRIVER_UNSUPPORTED", f"Driver {driver!r} is not available for this project type.")
        axis = parse_levels(levels, spec, 5)
        partner = next(d for key in _NEUTRAL_PARTNER for d in drivers_for(vertical) if d.key == key and d.key != spec.key)
    except MatrixRequestError as exc:
        return _request_error(exc)

    state = await _evaluate(record, owner, vertical, spec, axis, partner, (0.0,), scenario_id)
    if isinstance(state, JSONResponse):
        return state
    catalog = {entry[0]: entry for entry in KPI_CATALOG}
    columns = [{"key": k, "label": catalog[k][1], "unit": catalog[k][2], "fmt": catalog[k][3]} for k in STRIP_COLUMNS]

    def read(output) -> tuple[str, dict[str, Optional[float]], str]:
        if output is None:
            return "UNAVAILABLE", {}, "No evaluation."
        if "error" in output:
            return "FAILED", {}, str(output["error"])
        kpis = output.get("kpis") or {}
        return "OK", {k: _safe_float(kpis.get(k)) for k in STRIP_COLUMNS}, ""

    base_status, base_values, base_reason = read(state["base_output"])
    rows = []
    for i, level in enumerate(axis):
        status, values, reason = read(state["cell_outputs"].get((i, 0)))
        evidence = (state["evidence"].get((i, 0)) or {}).get("inputs", {}).get("A", {})
        cells: dict[str, dict[str, Any]] = {}
        for key, _label, _unit, fmt in ((c["key"], c["label"], c["unit"], c["fmt"]) for c in columns):
            raw = values.get(key)
            base_raw = base_values.get(key)
            delta = (raw - base_raw) if (raw is not None and base_raw is not None) else None
            cells[key] = {"raw": raw, "display": _apply_fmt(raw, fmt) if raw is not None else "—",
                          "delta": delta, "delta_display": format_delta(delta, fmt)}
        rows.append({"index": i, "level": level, "label": level_label(spec, level), "is_base": level == 0, "status": status,
                     "reason": reason, "input": {"text": evidence.get("text", ""), "original": evidence.get("original"),
                                                 "shocked": evidence.get("shocked"), "unit": spec.unit_label},
                     "values": cells})
    return _json({
        "ok": True, "kind": "strip", "vertical": _vertical_json(record),
        "driver": _driver_json(spec), "levels": [{"value": v, "label": level_label(spec, v)} for v in axis],
        "columns": columns, "rows": rows,
        "base": {"status": base_status, "reason": base_reason,
                 "values": {k: {"raw": v, "display": _apply_fmt(v, catalog[k][3]) if v is not None else "—"} for k, v in base_values.items()}},
        "counts": {s: sum(1 for r in rows if r["status"] == s) for s in ("OK", "FAILED", "UNAVAILABLE")},
        "run": state["run"],
        "provenance": "Each row is the original run_project result for the Working Copy draft with only this driver shocked; "
                      "nothing is interpolated and nothing was saved.",
    })


@router.get("/model-react/analysis/sensitivity/matrix")
async def react_sensitivity_matrix(request: Request, project: str, driver_a: str = "", driver_b: str = "", metric: str = "",
                                   grid: str = "", levels_a: str = "", levels_b: str = "", threshold: str = "",
                                   scenario_id: str = ""):
    record, owner, vertical, refused = _scope(request, project)
    if refused is not None:
        return refused
    from app.v2.sensitivity_matrix_projection import (
        MatrixRequestError, build_matrix, parse_grid_size, parse_levels, parse_threshold, resolve_metric, resolve_pair,
    )

    try:
        spec_a, spec_b = resolve_pair(driver_a, driver_b, vertical)
        size = parse_grid_size(grid)
        axis_a, axis_b = parse_levels(levels_a, spec_a, size), parse_levels(levels_b, spec_b, size)
        _k, _label, _unit, fmt, _src = resolve_metric(metric)
        limit = parse_threshold(threshold, fmt)
    except MatrixRequestError as exc:
        return _request_error(exc)

    state = await _evaluate(record, owner, vertical, spec_a, axis_a, spec_b, axis_b, scenario_id)
    if isinstance(state, JSONResponse):
        return state
    view = build_matrix(spec_a=spec_a, spec_b=spec_b, levels_a=axis_a, levels_b=axis_b, metric_key=metric,
                        cell_outputs=state["cell_outputs"], base_output=state["base_output"], threshold=limit,
                        shock_info=state["evidence"])
    run = dict(state["run"], completed=view["counts"]["OK"], failed=view["counts"]["FAILED"], unavailable=view["counts"]["UNAVAILABLE"])
    return _json({"ok": True, "kind": "matrix", "vertical": _vertical_json(record), "matrix": _jsonable(view), "run": run,
                  "provenance": "Each cell is the original run_project result with BOTH shocks applied to the inputs; "
                                "single-driver deltas are never added and nothing was saved."})


def _jsonable(value: Any) -> Any:
    """Matrix view tuples (bracket endpoints) become lists; everything else is already JSON."""
    if isinstance(value, dict):
        return {str(k): _jsonable(v) for k, v in value.items()}
    if isinstance(value, (list, tuple)):
        return [_jsonable(v) for v in value]
    return value
