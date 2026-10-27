"""RC-M Lane B — JSON adapter for React Analysis > Goal Seek (tender-pricing tariff solver).

Presentation/adapter layer over the EXISTING canonical authorities; no formula, solver or writer is re-implemented here:

* the solve is ``app.services.goal_seek.solve_tariff_for_metric`` (deterministic bracketed solve, bounded iteration and model-
  evaluation budgets) evaluated by ``make_canonical_evaluator`` (the original ``run_project`` in the bounded model executor) on the
  SAME canonical input construction the Legacy ``/v2/workbook/goal-seek/run`` route performs;
* the apply is the canonical atomic field writer ``WorkbookUpdateService.apply_draft_update`` (composite-hash CAS, project
  authorization, protected-reference refusal), exactly as Legacy ``/v2/workbook/goal-seek/apply``.

Endpoints:

* ``GET  /model-react/analysis/goal-seek/catalog`` — metrics, solve variable, current tariff, budgets and availability.
* ``GET  /model-react/analysis/goal-seek/solve``   — PREVIEW only (read-only, ephemeral): the candidate tariff and its numerical
  evidence.  It never mutates the Working Copy, never writes Run History / Last Run and is never presented as committed.
* ``POST /model-react/analysis/goal-seek/apply``   — the only write; session + signed project-bound CSRF + CAS.  It makes the
  Last Run STALE (the Run is a separate, deliberate action).

The solve spends executor capacity, so it requires the ``X-Finco-React-Request: 1`` header (not sendable cross-site without a CORS
preflight).  Feature flag: ``FINCO_MODEL_REACT_V1``.
"""
from __future__ import annotations

import logging
import math
from dataclasses import replace as dc_replace
from typing import Any, Optional

from fastapi import APIRouter, Request
from fastapi.responses import JSONResponse
from pydantic import BaseModel, ConfigDict, ValidationError

from app.auth import resolve_request_session, validate_csrf_token
from app.v2.react_poc_router import react_poc_enabled
from app.workbook.financing_csrf import extract_bound_token, issue_token

router = APIRouter()
log = logging.getLogger(__name__)

REQUEST_HEADER = "x-finco-react-request"
PURPOSE = "react-goal-seek-apply-v1"
_RUNTIME_KEYS = {"solar": "Solar", "wind": "Wind", "data_center": "Generic Data Center Reference",
                 "datacenter": "Generic Data Center Reference", "data center": "Generic Data Center Reference",
                 "ev_charging": "Generic EV Charging Hub Reference", "ev charging": "Generic EV Charging Hub Reference"}


def _json(payload: dict[str, Any], status: int = 200, headers: Optional[dict[str, str]] = None) -> JSONResponse:
    return JSONResponse(payload, status_code=status, headers={"Cache-Control": "no-store", **(headers or {})})


def _fail(status: int, code: str, message: str, *, changed: bool = False, headers: Optional[dict[str, str]] = None,
          **extra: Any) -> JSONResponse:
    suffix = "" if changed else " Nothing was changed."
    return _json({"ok": False, "code": code, "message": message + suffix, **extra}, status, headers)


def _scope(request: Request, project: str, *, header: bool):
    """(user, record, owner) or a ready JSONResponse — flag, [header], session, project access, protected reference."""
    if not react_poc_enabled():
        return None, None, None, _json({"ok": False, "code": "REACT_POC_DISABLED"}, 404)
    if header and request.headers.get(REQUEST_HEADER) != "1":
        return None, None, None, _fail(400, "REQUEST_HEADER_REQUIRED", "Goal Seek can only be started from the FINCO Model workspace.")
    user = resolve_request_session(request)
    if user is None:
        return None, None, None, _json({"ok": False, "code": "AUTH_REQUIRED"}, 401)
    from app.persistence.projects_repository import resolve_accessible_project
    from app.services.project_library_service import is_protected_reference

    record, owner = resolve_accessible_project(user.user_id, project)
    if record is None:
        return None, None, None, _json({"ok": False, "code": "PROJECT_NOT_FOUND"}, 404)
    if is_protected_reference(record):
        return None, None, None, _fail(409, "PROTECTED_REFERENCE", "This is a protected reference model. Create a working copy to edit it.")
    return user, record, owner, None


def _identity(owner: str, record) -> tuple[str, str]:
    """(composite content hash, workbook version) of the Working Copy as the canonical identity authority reports it."""
    from app.workbook.registry import WORKBOOK
    from app.workbook.workbook_identity import assemble_consistent_for_get

    try:
        identity = assemble_consistent_for_get(user_id=owner, project_id=record.project_id, workbook_version=WORKBOOK.version)
        return identity.composite_hash, WORKBOOK.version
    except Exception:  # noqa: BLE001 - an unreadable identity is reported as empty and Apply then fails closed
        return "", WORKBOOK.version


def _freshness(owner: str, record) -> str:
    """The Last Run freshness state (CURRENT / STALE / NOT_RUN) as the canonical runtime authority reports it now."""
    from app.persistence.workspace_repository import get_workspace_state
    from app.workbook.runtime_authority import resolve_runtime_freshness

    try:
        ws = get_workspace_state(user_id=owner, project_id=record.project_id)
        content_hash, _version = _identity(owner, record)
        return resolve_runtime_freshness(ws, current_composite_hash=content_hash).state.value
    except Exception:  # noqa: BLE001 - never invent a state
        return "UNKNOWN"


def _vertical_json(record) -> dict[str, Any]:
    from app.v2.react_workspace_router import _vertical_scope

    scope = _vertical_scope(record)
    return {k: scope[k] for k in ("key", "public_name", "pilot_tier", "limitations")}


def _metric_json(metric) -> dict[str, Any]:
    return {"key": metric.key, "label": metric.label}


def _metrics() -> list[dict[str, Any]]:
    from app.services.goal_seek import GOAL_SEEK_METRICS

    return [_metric_json(m) for m in GOAL_SEEK_METRICS.values()]


def _current_tariff(record, ws) -> tuple[Optional[float], Any, Any]:
    """(current tariff or None, solve variable, pis_draft) from the same resolver the Legacy route uses."""
    from app.services.goal_seek import resolve_solve_variable
    from app.workbook.service import WorkbookService

    variable = resolve_solve_variable((record.project_type or "").strip().lower())
    if variable is None:
        return None, None, None
    pis_draft = WorkbookService.build_draft_input_set_from_workspace(ws)
    origin = dict(getattr(pis_draft, "snapshot_origin", {}) or {})
    raw = origin.get("rev_ppa_base_tariff")
    if raw is None and variable.fallback_field_id:
        raw = origin.get("tariff_eur_mwh")
    try:
        value = float(str(raw).strip())
        return (value if math.isfinite(value) and value > 0 else None), variable, pis_draft
    except (TypeError, ValueError):
        return None, variable, pis_draft


def _budgets() -> dict[str, Any]:
    from app.services import goal_seek as gs

    return {"max_iterations": gs.DEFAULT_MAX_ITERATIONS, "max_model_evaluations": gs.DEFAULT_MAX_MODEL_EVALUATIONS,
            "target_tolerance": gs.DEFAULT_TARGET_TOLERANCE, "bracket_lower_fraction": gs.BRACKET_LOWER_FRACTION,
            "bracket_upper_multiple": gs.BRACKET_UPPER_MULTIPLE, "bracket_max_expansions": gs.BRACKET_MAX_EXPANSIONS}


@router.get("/model-react/analysis/goal-seek/catalog")
async def react_goal_seek_catalog(request: Request, project: str):
    user, record, owner, refused = _scope(request, project, header=True)
    if refused is not None:
        return refused
    from app.persistence.workspace_repository import get_workspace_state

    ws = get_workspace_state(user_id=owner, project_id=record.project_id)
    if ws is None:
        return _fail(404, "WORKSPACE_NOT_FOUND", "Workspace not found.")
    tariff, variable, _pis = _current_tariff(record, ws)
    available, reason = True, ""
    if variable is None:
        available, reason = False, "This project type has no supported tariff solve variable (supported: Solar and Wind)."
    elif tariff is None:
        available, reason = False, "The Working Copy tariff is missing or not a positive number."
    content_hash, workbook_version = _identity(owner, record)
    return _json({
        "ok": True, "available": available, "reason": reason, "vertical": _vertical_json(record), "metrics": _metrics(),
        "variable": None if variable is None else {"key": variable.key, "label": variable.label, "unit": variable.unit,
                                                   "field_id": variable.field_id},
        "current_tariff": tariff, "budgets": _budgets(),
        "binding": {"content_hash": content_hash, "workbook_version": workbook_version},
        "semantics": {"preview_only": True, "writes_nothing": True, "is_a_run": False,
                      "basis": "The Working Copy as saved on the server (unsaved edits in this browser are not included)."},
    })


def _construct(record, owner: str, ws):
    """Complete typed ProjectInputs — the same construction as Legacy Goal Seek. Returns (override, pis_draft) or (code, message)."""
    from app.capex_profiles.runtime import apply_snapshot_profiles
    from app.persistence.scenarios_repository import get_scenario
    from app.services.capex_sub_lines_integration import apply_user_sub_lines_replacing_base
    from app.services.opex_sub_lines_integration import apply_user_sub_lines_to_opex
    from app.services.sensitivity_service import CONTRACTED_PRICE_SHOCK_REFUSAL
    from app.workbook.bankability_config import SNAPSHOT_KEY, assert_materialized_fee_authority
    from app.workbook.multisenior_config import SNAPSHOT_KEY as F3_KEY, apply_state, scope_for_workspace
    from app.workbook.service import WorkbookService

    pis_draft = WorkbookService.build_draft_input_set_from_workspace(ws)
    try:
        override = WorkbookService.to_projectinputs(pis_draft)
    except Exception as exc:  # noqa: BLE001
        log.exception("react_goal_seek: build_project_inputs failed project=%s", record.project_code)
        return "MODEL_RUN_FAILED", f"Could not build project inputs — {exc}"
    scenario_overrides = None
    if ws.active_scenario_id:
        sc = get_scenario(scenario_id=ws.active_scenario_id, user_id=owner)
        if sc is None or sc.archived or sc.project_id != record.project_id:
            return "INVALID_REQUEST", "Active scenario could not be resolved. Please re-select a scenario and try again."
        scenario_overrides = sc.overrides
    folded = apply_user_sub_lines_replacing_base(override.capex, project_id=record.project_id, scenario_overrides=scenario_overrides)
    if folded is not override.capex:
        override = dc_replace(override, capex=folded)
    folded_opex = apply_user_sub_lines_to_opex(override.opex, project_id=record.project_id, scenario_overrides=scenario_overrides)
    if folded_opex is not override.opex:
        override = dc_replace(override, opex=folded_opex)
    try:
        assert_materialized_fee_authority(override, pis_draft.snapshot_origin.get(SNAPSHOT_KEY))
        override = apply_state(override, pis_draft.snapshot_origin.get(F3_KEY), scope_for_workspace(ws),
                               bankability_raw=pis_draft.snapshot_origin.get(SNAPSHOT_KEY))
        override = apply_snapshot_profiles(override, pis_draft.snapshot_origin, project_id=record.project_id,
                                           scenario_overrides=scenario_overrides)
    except ValueError as exc:
        return "INVALID_REQUEST", str(exc)
    if getattr(override.revenue, "multistream_config_json", "") or (scenario_overrides or {}).get("rev_multistream_config_json"):
        return "INVALID_REQUEST", CONTRACTED_PRICE_SHOCK_REFUSAL
    return override, pis_draft


@router.get("/model-react/analysis/goal-seek/solve")
async def react_goal_seek_solve(request: Request, project: str, target_metric: str = "", target_value: str = ""):
    user, record, owner, refused = _scope(request, project, header=True)
    if refused is not None:
        return refused
    from app.persistence.workspace_repository import get_workspace_state
    from app.runtime.model_execution import ModelExecutionBusy
    from app.services.goal_seek import (
        GoalSeekModelRunError, GoalSeekResult, GoalSeekStatus, make_canonical_evaluator, resolve_metric, solve_tariff_for_metric,
    )

    ws = get_workspace_state(user_id=owner, project_id=record.project_id)
    if ws is None:
        return _fail(404, "WORKSPACE_NOT_FOUND", "Workspace not found.")
    project_type = (record.project_type or "").strip().lower()
    tariff, variable, _pis = _current_tariff(record, ws)
    runtime_key = _RUNTIME_KEYS.get(project_type)
    if variable is None or runtime_key is None:
        return _fail(422, "INVALID_REQUEST", f"Project type {project_type!r} has no supported scalar revenue-price solve variable in V1 (supported: solar, wind).")
    metric = resolve_metric(target_metric)
    if metric is None:
        return _fail(422, "INVALID_REQUEST", "Unknown target metric. Supported: Project IRR, Pure Equity IRR, Total Sponsor IRR.")
    try:
        target_pct = float(str(target_value).strip().replace("%", ""))
        if not math.isfinite(target_pct):
            raise ValueError("not finite")
    except (TypeError, ValueError):
        return _fail(422, "INVALID_REQUEST", f"Target {target_value!r} is not a valid number.")
    built = _construct(record, owner, ws)
    if isinstance(built[0], str):
        return _fail(422, built[0], built[1])
    override, _pis_draft = built
    if tariff is None:
        return _fail(422, "INVALID_REQUEST", "The current tariff on this working copy is missing or not a positive number; Goal Seek cannot derive an adaptive bracket.")

    content_before, workbook_version = _identity(owner, record)
    evaluator = make_canonical_evaluator(runtime_key, override, metric)
    try:
        result = await solve_tariff_for_metric(project_type=project_type, current_tariff=tariff, target_value=target_pct / 100.0,
                                               metric_key=metric.key, evaluate_batch=evaluator)
    except ModelExecutionBusy:
        return _json({"ok": False, "code": "MODEL_BUSY", "message": "The model engine is busy — please retry in a moment. Nothing was changed."},
                     429, {"Retry-After": "5", "X-Finco-Model-Busy": "1"})
    except GoalSeekModelRunError as exc:
        result = GoalSeekResult(
            status=GoalSeekStatus.MODEL_RUN_FAILED.value, solve_variable=variable.key, solve_variable_label=variable.label,
            solve_variable_unit=variable.unit, solve_field_id=variable.field_id, target_metric=metric.key,
            target_metric_label=metric.label, target_value=target_pct / 100.0, solved_input_value=None, achieved_metric_value=None,
            absolute_target_error=None, iterations=0, model_evaluations=0, lower_bound=0.0, upper_bound=0.0, bracket_lower=None,
            bracket_upper=None, started_from_value=tariff, message=f"Canonical model run failed: {exc}")

    content_after, _v = _identity(owner, record)
    if content_before and content_after and content_after != content_before:
        return _fail(409, "CONTEXT_CHANGED", "The Working Copy changed while the solve was running; the result was discarded.")

    solved = result.solved and result.solved_input_value is not None
    delta = (result.solved_input_value - result.started_from_value) if solved else None
    payload: dict[str, Any] = {
        "ok": True, "preview_only": True, "committed": False, "is_a_run": False, "vertical": _vertical_json(record),
        "result": {
            "status": result.status, "solved": bool(result.solved), "message": result.message,
            "target_metric": result.target_metric, "target_metric_label": result.target_metric_label,
            "target_value": result.target_value, "target_display": f"{result.target_value * 100:.2f}%",
            "variable": {"key": result.solve_variable, "label": result.solve_variable_label, "unit": result.solve_variable_unit,
                         "field_id": result.solve_field_id},
            "started_from": result.started_from_value, "started_from_display": f"{result.started_from_value:.2f} {result.solve_variable_unit}",
            "solved_input_value": result.solved_input_value,
            "solved_display": None if result.solved_input_value is None else f"{result.solved_input_value:.2f} {result.solve_variable_unit}",
            "delta_display": None if delta is None else f"{delta:+.2f} {result.solve_variable_unit}",
            "variance_display": (f"{delta / result.started_from_value * 100:+.1f}%" if delta is not None and result.started_from_value > 0 else None),
            "achieved_metric_value": result.achieved_metric_value,
            "achieved_display": None if result.achieved_metric_value is None else f"{result.achieved_metric_value * 100:.4f}%",
            "absolute_target_error": result.absolute_target_error,
            "error_display": None if result.absolute_target_error is None else f"{result.absolute_target_error * 100:.4f} pp",
            "iterations": result.iterations, "model_evaluations": result.model_evaluations, "expansions": result.expansions,
            "lower_bound": result.lower_bound, "upper_bound": result.upper_bound,
            "bracket_lower": result.bracket_lower, "bracket_upper": result.bracket_upper,
        },
        "budgets": _budgets(), "apply": None,
        "provenance": "Every candidate is the original run_project on the saved Working Copy with only the tariff replaced; "
                      "nothing was saved and no Run was recorded.",
    }
    if solved:
        payload["apply"] = {"field_id": result.solve_field_id, "value": repr(float(result.solved_input_value)),
                            "content_hash": content_after or content_before, "workbook_version": workbook_version,
                            "target_metric": metric.key, "target_value": str(target_pct),
                            "csrf_token": issue_token(request, record.project_code, purpose=PURPOSE)}
    return _json(payload)


class ApplyBody(BaseModel):
    model_config = ConfigDict(extra="forbid")

    project: str
    field_id: str
    value: str
    content_hash: str
    workbook_version: str
    csrf_token: str


@router.post("/model-react/analysis/goal-seek/apply")
async def react_goal_seek_apply(request: Request):
    if not react_poc_enabled():
        return _json({"ok": False, "code": "REACT_POC_DISABLED"}, 404)
    user = resolve_request_session(request)
    if user is None:
        return _json({"ok": False, "code": "AUTH_REQUIRED"}, 401)
    try:
        body = ApplyBody.model_validate(await request.json())
    except (ValidationError, ValueError, TypeError):
        return _json({"ok": False, "code": "BODY_INVALID"}, 400)
    if not validate_csrf_token(extract_bound_token(request, body.project, body.csrf_token, purpose=PURPOSE)):
        return _json({"ok": False, "code": "CSRF_INVALID"}, 403)

    from app.persistence.projects_repository import resolve_accessible_project
    from app.persistence.workspace_repository import get_workspace_state
    from app.services.goal_seek import resolve_solve_variable
    from app.services.project_library_service import is_protected_reference
    from app.workbook.update_service import (
        FieldValidationError, NonEditableFieldError, ProtectedReferenceError, StaleContentError, UnknownFieldError,
        VersionMismatchError, WorkbookUpdateService,
    )

    record, owner = resolve_accessible_project(user.user_id, body.project)
    if record is None:
        return _json({"ok": False, "code": "PROJECT_NOT_FOUND"}, 404)
    if is_protected_reference(record):
        return _fail(409, "PROTECTED_REFERENCE", "This is a protected reference model. Create a working copy to edit it.")
    ws = get_workspace_state(user_id=owner, project_id=record.project_id)
    if ws is None:
        return _json({"ok": False, "code": "WORKSPACE_NOT_FOUND"}, 404)
    variable = resolve_solve_variable((record.project_type or "").strip().lower())
    permitted = _current_tariff(record, ws)[1]
    if variable is None or permitted is None or body.field_id != variable.field_id:
        return _fail(422, "FIELD_NOT_PERMITTED", "Submitted field is not the Goal Seek solve variable for this project; nothing was applied.",
                     changed=True)
    try:
        numeric = float(body.value.strip())
        if not math.isfinite(numeric) or numeric <= 0:
            raise ValueError("not a positive finite number")
    except (TypeError, ValueError):
        return _fail(422, "VALUE_INVALID", "Solved value is not a positive finite number; nothing was applied.", changed=True)
    try:
        WorkbookUpdateService.apply_draft_update(ws=ws, field_id=body.field_id, raw_value=body.value, content_hash=body.content_hash,
                                                 workbook_version=body.workbook_version, project_record=record)
    except StaleContentError:
        return _fail(409, "STALE_CONTENT", "The Working Copy changed since the solve — the solved tariff was NOT applied (atomic safety). "
                     "Run Goal Seek again on the current draft.", changed=True)
    except VersionMismatchError:
        return _fail(409, "VERSION_MISMATCH", "The workbook version changed since the solve — nothing was applied. Reload and solve again.", changed=True)
    except ProtectedReferenceError:
        return _fail(409, "PROTECTED_REFERENCE", "This is a protected reference model.", changed=True)
    except (UnknownFieldError, NonEditableFieldError, FieldValidationError) as exc:
        return _fail(422, "APPLY_REJECTED", f"Solved tariff could not be applied: {exc}", changed=True)
    except Exception:  # noqa: BLE001 - the writer may have committed: never claim "not applied"
        log.exception("react_goal_seek: apply outcome unknown project=%s", record.project_code)
        return _json({"ok": False, "code": "APPLY_OUTCOME_UNKNOWN",
                      "message": "Result unknown — reload the workspace to see whether the tariff was applied before solving again."}, 500)
    fresh_hash, fresh_version = _identity(owner, record)
    state = _freshness(owner, record)
    return _json({"ok": True, "applied": True, "field_id": body.field_id, "value": body.value, "content_hash": fresh_hash,
                  "workbook_version": fresh_version, "run_state": state,
                  "message": "Applied to the Working Copy. " + (
                      "The Last Run is now STALE — press Run to make it canonical. " if state == "STALE"
                      else "There is no Last Run yet — press Run when ready. ")
                  + "Goal Seek candidate runs never wrote Run History or Last Run."})
