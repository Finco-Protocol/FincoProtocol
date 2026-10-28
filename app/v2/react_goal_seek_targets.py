"""RC-UX — typed-unit Goal Seek targets (IRR %, minimum DSCR multiple, NPV kEUR) for the React Analysis > Goal Seek panel.

The FIN-V2 canonical Goal Seek (``app.services.goal_seek``, merged through #395) offers six targets with DIFFERENT units:

* IRR targets (``unit == "ratio"``)  — the user types a percentage; the canonical target is the fraction (8.5 -> 0.085);
* minimum DSCR (``unit == "multiple"``) — the user types a multiple (1.35); the canonical target is that same number;
* Project / Total Sponsor NPV (``unit == "kEUR"``) — the user types kEUR; the canonical target is that same number.

The earlier RC-M adapter (``react_goal_seek``, byte-pinned in the FIN-V2-3 cohort) serves only the ratio targets, because dividing every target by 100
would silently mis-scale a multiple or an NPV.  This module serves all six with an EXPLICIT target unit: the request must name the unit it was typed
in, it must equal the metric's canonical unit, and a mismatch (a percent sign on a multiple, kEUR sent for an IRR, a missing unit) is refused (422) before
any model work.  The conversion mirrors the Legacy ``/v2/workbook/goal-seek/run`` route (``target / 100`` only for ratio metrics) — nothing is re-derived here.

Everything else is reused unchanged from the pinned adapter: scope/ownership/protected-reference refusal, the canonical input construction, the bounded
solver and evaluator, the context-changed discard, and the signed apply binding (the apply stays the one pinned CAS write route; this module writes nothing).

* ``GET /model-react/analysis/goal-seek/targets`` — the typed target catalog (key, label, canonical unit, the unit the user types, input hint).
* ``GET /model-react/analysis/goal-seek/solve-typed?project=&target_metric=&target_value=&target_unit=`` — PREVIEW only, as the earlier solve.

Feature flag ``FINCO_MODEL_REACT_V1`` and the ``X-Finco-React-Request: 1`` header apply, as for the pinned module.
"""
from __future__ import annotations

import math
from typing import Any

from fastapi import APIRouter, Request

from app.v2.react_goal_seek import (
    PURPOSE, _budgets, _candidate, _construct, _current_tariff, _fail, _identity, _json, _RUNTIME_KEYS, _scope, _vertical_json,
)
from app.workbook.financing_csrf import issue_token

router = APIRouter()

#: canonical metric unit -> (unit token the client must send, label for the input, example, display of one target value)
UNITS: dict[str, dict[str, str]] = {
    "ratio": {"target_unit": "percent", "input_label": "Target (%)", "example": "8.5"},
    "multiple": {"target_unit": "multiple", "input_label": "Target (x)", "example": "1.35"},
    "kEUR": {"target_unit": "keur", "input_label": "Target (kEUR)", "example": "5000"},
}


def _typed_json(metric) -> dict[str, Any]:
    spec = UNITS[metric.unit]
    return {"key": metric.key, "label": metric.label, "unit": metric.unit, **spec}


def _metrics() -> dict:
    from app.services.goal_seek import GOAL_SEEK_METRICS

    return {key: metric for key, metric in GOAL_SEEK_METRICS.items() if metric.unit in UNITS}


def parse_target(metric, raw: str, unit_token: str) -> tuple[float | None, str]:
    """(canonical target, "") or (None, reason).  The unit is explicit and must equal the metric's canonical unit."""
    spec = UNITS[metric.unit]
    given = str(unit_token or "").strip().lower()
    if given != spec["target_unit"]:
        return None, (f"{metric.label} is a target in {spec['target_unit']}; the request named "
                      f"{given or 'no unit'}. Enter the target in {spec['target_unit']}.")
    text = str(raw or "").strip().replace(",", "")
    if metric.unit == "ratio":
        text = text.replace("%", "")
    elif metric.unit == "multiple":
        text = text.rstrip("xX")
    if "%" in text:
        return None, f"A percent sign does not belong in a {spec['target_unit']} target."
    try:
        number = float(text)
    except (TypeError, ValueError):
        return None, f"Target {raw!r} is not a valid number."
    if not math.isfinite(number):
        return None, f"Target {raw!r} is not a valid number."
    if metric.unit == "ratio":
        if number <= -100.0:
            return None, "A percentage target must be above -100%."
        return number / 100.0, ""
    if metric.unit == "multiple" and number <= 0:
        return None, "A DSCR target must be a positive multiple (for example 1.35)."
    return number, ""


def display_target(metric, value: float) -> str:
    if metric.unit == "ratio":
        return f"{value * 100:.2f}%"
    if metric.unit == "multiple":
        return f"{value:.2f}x"
    return f"{value:,.0f} kEUR"


def display_metric(metric, value: float) -> str:
    if metric.unit == "ratio":
        return f"{value * 100:.4f}%"
    if metric.unit == "multiple":
        return f"{value:.4f}x"
    return f"{value:,.2f} kEUR"


def display_error(metric, value: float) -> str:
    if metric.unit == "ratio":
        return f"{value * 100:.4f} pp"
    if metric.unit == "multiple":
        return f"{value:.4f}x"
    return f"{value:,.4f} kEUR"


@router.get("/model-react/analysis/goal-seek/targets")
async def react_goal_seek_targets(request: Request, project: str):
    user, record, owner, refused = _scope(request, project, header=True)
    if refused is not None:
        return refused
    return _json({"ok": True, "metrics": [_typed_json(m) for m in _metrics().values()],
                  "semantics": {"explicit_unit_required": True, "writes_nothing": True}})


@router.get("/model-react/analysis/goal-seek/solve-typed")
async def react_goal_seek_solve_typed(request: Request, project: str, target_metric: str = "", target_value: str = "", target_unit: str = ""):
    user, record, owner, refused = _scope(request, project, header=True)
    if refused is not None:
        return refused
    from app.persistence.workspace_repository import get_workspace_state
    from app.runtime.model_execution import ModelExecutionBusy
    from app.services.goal_seek import (
        GoalSeekModelRunError, GoalSeekResult, GoalSeekStatus, make_canonical_evaluator, solve_tariff_for_metric,
    )

    metric = _metrics().get(str(target_metric or "").strip())
    if metric is None:
        return _fail(422, "INVALID_REQUEST", "Unknown target metric. Supported: Project IRR, Pure Equity IRR, Total Sponsor IRR, "
                                              "Minimum DSCR, Project NPV, Total Sponsor NPV.")
    target, why = parse_target(metric, target_value, target_unit)
    if target is None:
        return _fail(422, "UNIT_MISMATCH" if "named" in why else "INVALID_REQUEST", why)
    ws = get_workspace_state(user_id=owner, project_id=record.project_id)
    if ws is None:
        return _fail(404, "WORKSPACE_NOT_FOUND", "Workspace not found.")
    project_type = (record.project_type or "").strip().lower()
    tariff, variable, _pis = _current_tariff(record, ws)
    runtime_key = _RUNTIME_KEYS.get(project_type)
    if variable is None or runtime_key is None:
        return _fail(422, "INVALID_REQUEST", f"Project type {project_type!r} has no supported scalar revenue-price solve variable in V1 (supported: solar, wind).")
    built = _construct(record, owner, ws)
    if isinstance(built[0], str):
        return _fail(422, built[0], built[1])
    override, _pis_draft = built
    if tariff is None:
        return _fail(422, "INVALID_REQUEST", "The current tariff on this project is missing or not a positive number; Goal Seek cannot derive an adaptive bracket.")

    content_before, workbook_version = _identity(owner, record)
    evaluator = make_canonical_evaluator(runtime_key, override, metric)
    try:
        result = await solve_tariff_for_metric(project_type=project_type, current_tariff=tariff, target_value=target,
                                               metric_key=metric.key, evaluate_batch=evaluator)
    except ModelExecutionBusy:
        return _json({"ok": False, "code": "MODEL_BUSY", "message": "The model engine is busy — please retry in a moment. Nothing was changed."},
                     429, {"Retry-After": "5", "X-Finco-Model-Busy": "1"})
    except GoalSeekModelRunError as exc:
        result = GoalSeekResult(
            status=GoalSeekStatus.MODEL_RUN_FAILED.value, solve_variable=variable.key, solve_variable_label=variable.label,
            solve_variable_unit=variable.unit, solve_field_id=variable.field_id, target_metric=metric.key,
            target_metric_label=metric.label, target_value=target, solved_input_value=None, achieved_metric_value=None,
            absolute_target_error=None, iterations=0, model_evaluations=0, lower_bound=0.0, upper_bound=0.0, bracket_lower=None,
            bracket_upper=None, started_from_value=tariff, message=f"Canonical model run failed: {exc}")

    content_after, _v = _identity(owner, record)
    if content_before and content_after and content_after != content_before:
        return _fail(409, "CONTEXT_CHANGED", "The project changed while the solve was running; the result was discarded.")

    solved = result.solved and result.solved_input_value is not None
    delta = (result.solved_input_value - result.started_from_value) if solved else None
    unit = result.solve_variable_unit
    payload: dict[str, Any] = {
        "ok": True, "preview_only": True, "committed": False, "is_a_run": False, "vertical": _vertical_json(record),
        "target": _typed_json(metric),
        "result": {
            "status": result.status, "solved": bool(result.solved), "message": result.message,
            "target_metric": result.target_metric, "target_metric_label": result.target_metric_label,
            "target_value": result.target_value, "target_unit": UNITS[metric.unit]["target_unit"],
            "target_display": display_target(metric, result.target_value),
            "variable": {"key": result.solve_variable, "label": result.solve_variable_label, "unit": unit, "field_id": result.solve_field_id},
            "started_from": result.started_from_value, "started_from_display": f"{result.started_from_value:.2f} {unit}",
            "solved_input_value": result.solved_input_value,
            "solved_display": None if result.solved_input_value is None else f"{result.solved_input_value:.2f} {unit}",
            "delta_display": None if delta is None else f"{delta:+.2f} {unit}",
            "variance_display": (f"{delta / result.started_from_value * 100:+.1f}%" if delta is not None and result.started_from_value > 0 else None),
            "achieved_metric_value": result.achieved_metric_value,
            "achieved_display": None if result.achieved_metric_value is None else display_metric(metric, result.achieved_metric_value),
            "absolute_target_error": result.absolute_target_error,
            "error_display": None if result.absolute_target_error is None else display_error(metric, result.absolute_target_error),
            "iterations": result.iterations, "model_evaluations": result.model_evaluations, "expansions": result.expansions,
            "lower_bound": result.lower_bound, "upper_bound": result.upper_bound,
            "bracket_lower": result.bracket_lower, "bracket_upper": result.bracket_upper,
        },
        "budgets": _budgets(), "apply": None,
        "provenance": "Every candidate is the original model run on the saved project with only the tariff replaced; "
                      "nothing was saved and no Run was recorded.",
    }
    if solved:
        value = repr(float(result.solved_input_value))
        bound = content_after or content_before
        payload["apply"] = {"field_id": result.solve_field_id, "value": value, "content_hash": bound, "workbook_version": workbook_version,
                            "target_metric": metric.key, "target_value": str(target_value),
                            "csrf_token": issue_token(request, _candidate(record.project_code, result.solve_field_id, value, bound, workbook_version),
                                                      purpose=PURPOSE)}
    return _json(payload)
