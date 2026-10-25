"""UX-02 React Core Integration — authorized JSON projections for the integrated React workbook.

Presentation-only read surface over the EXISTING canonical authorities.  It adds NO
economic or persistence authority:

* ``GET /model-react/library``    — the user's own workspace projects plus the public
  reference models, via the SAME repository reads the legacy Library page uses
  (``list_workspace_projects_paged`` / ``get_reference_projects``).  Working-copy
  creation stays on the existing ``POST /library/clone/{id}``; nothing is cloned here.
* ``GET /model-react/workspace``  — one coherent shell snapshot per project: identity,
  composite workbook identity, scenario, freshness, persisted Last Run identity,
  Run Integrity and the four independent status dimensions (SC-03).
* ``GET /model-react/statements`` — the SIX statement destinations (P&L, Balance Sheet,
  Cash Flow, CFADS, Debt, Sponsor Returns) adapted from the canonical statement
  presentation services into the harvested React ``StatementWorkbookSnapshot`` shape.
  Every cell arrives as a server-formatted display string; unavailable values stay
  ``null``-backed "—" and are never substituted with zeros or demo data.
* ``GET /model-react/inputs``     — the canonical Hybrid Inputs grid projection
  (``app.v2.router._build_input_grid_ctx`` — the SAME builder the legacy grid panel
  renders), serialized to JSON, plus the Save tokens (CSRF, composite hash, workbook
  version, scenario) the existing ``POST /v2/workbook/grid/save`` requires.

All mutations remain on the canonical routes: scalar grid saves on
``POST /v2/workbook/grid/save`` (C0 atomic writer, composite CAS, CSRF), cost lines on
``POST /v2/workbook/grid/cost-lines/save``, working-copy creation on
``POST /library/clone/{id}``, and Run on ``POST /v2/workbook/run`` (deliberately not
exposed here — the thin Run-outcome adapter is still deferred, as documented in
``docs/react_migration/ux01_poc_implementation.md``).

Feature flag: the same ``FINCO_MODEL_REACT_V1`` gate as the UX-01 PoC surface.
"""
from __future__ import annotations

import json
from dataclasses import asdict, is_dataclass
from typing import Any, Mapping, Optional

from app.workbook.financing_csrf import issue_token as _issue_csrf_token
from fastapi import APIRouter, Request
from fastapi.responses import JSONResponse

from app.auth import generate_csrf_token, resolve_request_session
from app.v2.react_poc_router import REACT_ASSET_VERSION, react_poc_enabled

router = APIRouter()

REACT_WORKSPACE_VERSION = "ux02-v1"


def _json(payload: dict[str, Any], status: int = 200) -> JSONResponse:
    return JSONResponse(payload, status_code=status, headers={"Cache-Control": "no-store"})


def _resolve_project(request: Request, project: str):
    """(user, record, owner) or a ready JSONResponse — the canonical authorization order."""
    user = resolve_request_session(request)
    if user is None:
        return None, None, None, _json({"ok": False, "code": "AUTH_REQUIRED"}, 401)
    from app.persistence.projects_repository import resolve_accessible_project

    record, owner = resolve_accessible_project(user.user_id, project)
    if record is None:
        return None, None, None, _json({"ok": False, "code": "PROJECT_NOT_FOUND"}, 404)
    return user, record, owner, None


# ───────────────────────────── library ─────────────────────────────

@router.get("/model-react/library")
async def react_workspace_library(request: Request, search: str = "", page: int = 1):
    """Authorized Library read: the caller's own projects + public reference models."""
    if not react_poc_enabled():
        return _json({"ok": False, "code": "REACT_POC_DISABLED"}, 404)
    user = resolve_request_session(request)
    if user is None:
        return _json({"ok": False, "code": "AUTH_REQUIRED"}, 401)

    import math

    from app.library.router import PAGE_SIZE, _reference_templates
    from app.persistence.projects_repository import list_workspace_projects_paged

    page = max(1, page)
    records, total = list_workspace_projects_paged(
        user_id=user.user_id, page=page, page_size=PAGE_SIZE,
        search=(search or "").strip() or None, role_filter=None)
    references = _reference_templates(search or "", None)

    from app.persistence.workspace_repository import get_workspace_state
    from app.services.project_library_service import is_protected_reference
    from app.workbook.runtime_authority import resolve_runtime_freshness
    from app.workbook.workbook_identity import assemble_consistent_for_get, WorkbookIdentityError
    from app.workbook.registry import WORKBOOK

    def project_entry(record, protected: bool) -> dict[str, Any]:
        entry: dict[str, Any] = {
            "code": record.project_code,
            "project_id": record.project_id,
            "name": getattr(record, "project_name", None) or record.project_code,
            "project_type": getattr(record, "project_type", None) or "",
            "template_source": getattr(record, "template_source", None) or "",
            "protected_reference": protected,
            "reference": protected,
        }
        ws = get_workspace_state(record.user_id, record.project_id)
        last_run: dict[str, Any] | None = None
        if ws is not None:
            try:
                identity = assemble_consistent_for_get(record.user_id, record.project_id, WORKBOOK.version)
                freshness = resolve_runtime_freshness(ws, current_composite_hash=identity.composite_hash)
                last_run = {
                    "available": freshness.has_runtime,
                    "freshness": freshness.state.value,
                    "snapshot_id": (getattr(ws, "last_runtime_snapshot_id", None) or "")[:12],
                    "ran_at": (getattr(ws, "last_runtime_at", None).isoformat()[:19].replace("T", " ")
                               if getattr(ws, "last_runtime_at", None) else ""),
                }
            except WorkbookIdentityError:
                last_run = {"available": False, "freshness": "NOT_RUN",
                            "snapshot_id": "", "ran_at": ""}
        entry["last_run"] = last_run
        return entry

    return _json({
        "ok": True,
        "react_workspace": {"version": REACT_WORKSPACE_VERSION},
        "projects": [project_entry(r, False) for r in records],
        "references": [project_entry(r, True) for r in references],
        "page": page,
        "page_size": PAGE_SIZE,
        "total": total,
        "total_pages": max(1, math.ceil(total / PAGE_SIZE)),
        "clone_url": "/library/clone/{source_project_id}",
        "csrf_token": _issue_csrf_token(request, "", purpose="library-clone-v1"),
    })


# ───────────────────────────── workspace shell ─────────────────────────────

@router.get("/model-react/workspace")
async def react_workspace_shell(request: Request, project: str):
    """One coherent authorized shell snapshot for the integrated React workspace."""
    if not react_poc_enabled():
        return _json({"ok": False, "code": "REACT_POC_DISABLED"}, 404)
    user, record, owner, failure = _resolve_project(request, project)
    if failure is not None:
        return failure
    assert record is not None and owner is not None

    from app.services.project_library_service import is_protected_reference

    try:
        from app.api.v1_1.institutional import get_run_integrity_checks
        from app.v2.post_run_context import PostRunContextChanged, PostRunRequestContext
        from app.workbook.workbook_identity import WorkbookIdentityError

        context = PostRunRequestContext.capture(owner_id=owner, project_id=record.project_id)
        integrity_state, report = get_run_integrity_checks(owner, record.project_id, context=context)
        from app.persistence.scenario_insight_reads import resolve_last_run_scenario
        last_run_scenario = resolve_last_run_scenario(
            owner, record.project_id, context.workspace.last_runtime_scenario_id).label
        payload = {
            "ok": True,
            "react_workspace": {"version": REACT_WORKSPACE_VERSION},
            "project": {"code": record.project_code,
                        "name": getattr(record, "project_name", None) or record.project_code,
                        "project_type": getattr(record, "project_type", None) or "",
                        "template_source": getattr(record, "template_source", None) or "",
                        "protected_reference": is_protected_reference(record)},
            "workbook": {"version": context.identity.workbook_version,
                         "composite_hash": context.identity.composite_hash,
                         "scenario_id": context.workspace.active_scenario_id,
                         "scenario_name": context.workspace.active_scenario_name},
            "freshness": {"state": context.freshness.state.value,
                          "basis": context.freshness.source,
                          "has_runtime": context.freshness.has_runtime,
                          "is_stale": context.freshness.is_stale},
            "identity": None,
            "integrity": None,
            "integrity_available": integrity_state == "AVAILABLE",
            "status_dimensions": None,
            "engine": {"persisted_version": None, "current_version": None,
                       "currency": None, "treatment": "EVIDENCE_ONLY_D2_PENDING"},
        }
        if context.runtime_result is not None and context.freshness.state.value != "NOT_RUN":
            from app.v2.output_workspace_projection import build_output_workspace_safe

            outputs = build_output_workspace_safe(
                runtime_result=context.runtime_result, workspace=context.workspace,
                freshness=context.freshness, last_run_scenario=last_run_scenario,
                integrity_report=report if integrity_state == "AVAILABLE" else None,
                statement_projection=context.projection.fs)
            payload["identity"] = outputs.get("identity")
            payload["integrity"] = outputs.get("integrity")
            payload["status_dimensions"] = outputs.get("status_dimensions")
            dimensions = outputs.get("status_dimensions") or {}
            payload["engine"] = {"persisted_version": dimensions.get("engine_persisted_version"),
                                 "current_version": dimensions.get("engine_current_version"),
                                 "currency": dimensions.get("engine_currency"),
                                 "treatment": dimensions.get("engine_superseded_treatment")}
        context.validate_current()
        return _json(payload)
    except (PostRunContextChanged, WorkbookIdentityError, PermissionError):
        return _json({"ok": False, "code": "WORKSPACE_UNAVAILABLE",
                      "message": "The workspace changed while the response was assembled. Reload to refresh."}, 503)


# ───────────────────────────── statements (six destinations) ─────────────────────────────

def _column_labels(table: Optional[Mapping[str, Any]]) -> list[str]:
    if not isinstance(table, Mapping):
        return []
    return [str(c.get("label") or "") for c in table.get("columns") or ()]


def _row_texts(row: Mapping[str, Any]) -> list[str]:
    return [str(c.get("text") or "—") if c.get("v") is not None else "—"
            for c in row.get("cells") or ()]


def _sheet_from_tables(table: Any, annual_table: Any, sheet_id: str, label: str) -> dict[str, Any]:
    """Adapt one canonical statement table (+ its annual view) into the harvested
    ``StatementSheet`` shape.  Cells are the server-formatted display strings; a
    missing annual counterpart renders as unavailable dashes, never zeros."""
    if not isinstance(table, Mapping) or not table.get("available"):
        return {"id": sheet_id, "label": label, "title": (table or {}).get("title") or label,
                "unit": "keur", "rows": [], "available": False,
                "note": (table or {}).get("note") or "This Run persisted no such statement.",
                "unavailable": (table or {}).get("unavailable") or []}
    model_periods = _column_labels(table)
    annual_by_key: dict[str, list[str]] = {}
    annual_periods: list[str] = []
    if isinstance(annual_table, Mapping) and annual_table.get("available"):
        annual_periods = _column_labels(annual_table)
        for row in annual_table.get("rows") or ():
            annual_by_key[str(row.get("key"))] = _row_texts(row)
    rows = []
    for row in table.get("rows") or ():
        key = str(row.get("key"))
        rows.append({
            "id": key,
            "label": str(row.get("label") or ""),
            "model": _row_texts(row),
            "annual": annual_by_key.get(key, ["—"] * len(annual_periods)),
            "kind": "metric" if row.get("total") else "detail",
        })
    return {"id": sheet_id, "label": label, "title": table.get("title") or label,
            "unit": (table.get("rows") or [{}])[0].get("unit", "keur") if table.get("rows") else "keur",
            "rows": rows, "available": bool(table.get("rows")),
            "note": table.get("note") or "", "unavailable": table.get("unavailable") or [],
            "_model_periods": model_periods, "_annual_periods": annual_periods}


def _simple_table_sheet(table: Any, sheet_id: str, label: str) -> dict[str, Any]:
    """Same adaptation for the single-view canonical tables (CFADS)."""
    return _sheet_from_tables(table, None, sheet_id, label)


def _period_band(labels: list[str]) -> list[dict[str, Any]]:
    """Canonical period bands: one band per calendar year, in server label order.
    Computed from the canonical column labels only — no client date arithmetic."""
    bands: list[dict[str, Any]] = []
    for label in labels:
        year = label[-4:] if len(label) >= 4 and label[-4:].isdigit() else label
        if bands and bands[-1]["label"] == year:
            bands[-1]["span"] += 1
        else:
            bands.append({"label": year, "span": 1})
    return bands


def _debt_sheet(outputs: Mapping[str, Any]) -> tuple[dict[str, Any], dict[str, Any]]:
    """Debt destination.  Aggregate PF-waterfall Senior lines render as the sheet;
    the Run's own F3 facility schedules render as ``debtRowsByFacility``."""
    debt = outputs.get("debt") or {}
    if not isinstance(debt, Mapping) or debt.get("mode") == "UNAVAILABLE":
        sheet = {"id": "debt", "label": "Debt", "title": "Debt schedules", "unit": "keur",
                 "rows": [], "available": False,
                 "note": (debt or {}).get("note") or "This Run persisted no debt schedule.",
                 "unavailable": []}
        return sheet, {}
    by_facility: dict[str, Any] = {}
    rows: list[dict[str, Any]] = []
    model_periods: list[str] = []
    for facility in debt.get("facilities") or ():
        operating = facility.get("operating") or {}
        if not operating.get("available"):
            continue
        fid = str(facility.get("id") or "senior")
        facility_rows = [{"id": str(r.get("key")), "label": f"{facility.get('label')} — {r.get('label')}",
                          "model": _row_texts(r), "annual": [],
                          "kind": "metric" if r.get("total") else "detail"}
                         for r in operating.get("rows") or ()]
        by_facility[fid] = facility_rows
        if not rows:
            rows = facility_rows
            model_periods = [str(c.get("label") or "") for c in operating.get("columns") or ()]
    if not rows:
        sheet = {"id": "debt", "label": "Debt", "title": "Debt schedules", "unit": "keur",
                 "rows": [], "available": False,
                 "note": debt.get("note") or "No facility schedule persisted.", "unavailable": []}
        return sheet, {}
    sheet = {"id": "debt", "label": "Debt", "title": "Debt schedules", "unit": "keur",
             "rows": rows, "available": True, "note": debt.get("note") or "",
             "unavailable": []}
    return sheet, {"by_facility": by_facility, "model_periods": model_periods}


@router.get("/model-react/statements")
async def react_workspace_statements(request: Request, project: str):
    """The six canonical statement destinations for the harvested React workbook."""
    if not react_poc_enabled():
        return _json({"ok": False, "code": "REACT_POC_DISABLED"}, 404)
    user, record, owner, failure = _resolve_project(request, project)
    if failure is not None:
        return failure
    assert record is not None and owner is not None

    try:
        from app.api.v1_1.institutional import get_run_integrity_checks
        from app.persistence.scenario_insight_reads import resolve_last_run_scenario
        from app.v2.output_workspace_projection import build_output_workspace_safe
        from app.v2.post_run_context import PostRunContextChanged, PostRunRequestContext
        from app.workbook.workbook_identity import WorkbookIdentityError

        context = PostRunRequestContext.capture(owner_id=owner, project_id=record.project_id)
        integrity_state, report = get_run_integrity_checks(owner, record.project_id, context=context)
        state = context.freshness.state.value
        outputs: dict[str, Any] = {"statements": [], "cfads": None, "debt": None, "returns": None,
                                   "identity": None, "integrity": None, "status_dimensions": None,
                                   "state": "NOT_RUN"}
        if context.runtime_result is not None and state != "NOT_RUN":
            from app.persistence.scenario_insight_reads import resolve_last_run_scenario as _rlr
            last_run_scenario = _rlr(
                owner, record.project_id,
                getattr(context.workspace, "last_runtime_scenario_id", None)).label
            outputs = build_output_workspace_safe(
                runtime_result=context.runtime_result, workspace=context.workspace,
                freshness=context.freshness, last_run_scenario=last_run_scenario,
                integrity_report=report if integrity_state == "AVAILABLE" else None,
                statement_projection=context.projection.fs)

        statements = outputs.get("statements") or []
        pl = _sheet_from_tables(statements[0] if len(statements) > 0 else None,
                                statements[0].get("annual") if len(statements) > 0 else None,
                                "pl", "Profit & Loss")
        balance = _sheet_from_tables(statements[1] if len(statements) > 1 else None,
                                     statements[1].get("annual") if len(statements) > 1 else None,
                                     "balance", "Balance Sheet")
        cashflow = _sheet_from_tables(statements[2] if len(statements) > 2 else None,
                                      statements[2].get("annual") if len(statements) > 2 else None,
                                      "cashflow", "Cash Flow (PF waterfall)")
        cfads = _simple_table_sheet(outputs.get("cfads"), "cfads", "CFADS")
        debt_sheet, debt_facilities = _debt_sheet(outputs)
        returns = outputs.get("returns") or {}
        distributions = returns.get("distributions") or {}
        sponsor = _simple_table_sheet(
            distributions if distributions.get("available") else None, "sponsor", "Sponsor Returns")

        def periods_of(sheet: dict[str, Any]) -> tuple[list[str], list[str]]:
            return sheet.pop("_model_periods", []), sheet.pop("_annual_periods", [])

        model_periods, annual_periods = periods_of(pl)
        for sheet in (balance, cashflow, cfads, debt_sheet, sponsor):
            mp, ap = periods_of(sheet)
            model_periods = model_periods or mp
            annual_periods = annual_periods or ap
        debt_periods = debt_facilities.get("model_periods") or []
        if not model_periods:
            model_periods = debt_periods

        identity = outputs.get("identity") or {}
        dimensions = outputs.get("status_dimensions") or {}
        snapshot = {
            "annualPeriods": annual_periods,
            "modelPeriods": model_periods,
            "periodBands": _period_band(model_periods),
            "sheets": [pl, balance, cashflow, cfads, debt_sheet, sponsor],
            "debtRowsByFacility": debt_facilities.get("by_facility") or {},
        }
        # Run Integrity is the Run's own committed verdict: PASS/FAIL/INCOMPLETE when
        # the canonical integrity authority evaluated it, UNAVAILABLE when evidence
        # exists but cannot be read, "not evaluated" only when nothing was evaluated.
        if integrity_state == "AVAILABLE" and isinstance(outputs.get("integrity"), Mapping):
            integrity_value = str(outputs["integrity"].get("status") or "UNAVAILABLE")
        else:
            integrity_value = "UNAVAILABLE" if state != "NOT_RUN" else "not evaluated"
        status = {
            "label": "Last Run",
            "runId": (identity.get("snapshot_id") or "")[:12] or "Not supplied",
            "freshness": state.lower() if state in ("CURRENT", "STALE") else "not run",
            "integrity": integrity_value,
            "engineVersion": (identity.get("engine_version") or None) if isinstance(identity, Mapping) else None,
            "dataOrigin": "caller-provided",
        }
        payload = {
            "ok": True,
            "react_workspace": {"version": REACT_WORKSPACE_VERSION},
            "project": {"code": record.project_code,
                        "name": getattr(record, "project_name", None) or record.project_code,
                        "protected_reference": False},
            "state": outputs.get("state") or ("NOT_RUN" if state == "NOT_RUN" else "UNAVAILABLE"),
            "message": ("" if outputs.get("state") not in (None, "UNAVAILABLE")
                        else "The persisted Run evidence could not be projected; nothing is estimated."),
            "snapshot": snapshot if outputs.get("state") in ("CURRENT", "STALE") else None,
            "status": status,
            "results": {"available": bool(returns.get("available")),
                        "metrics": returns.get("metrics") or [],
                        "distributions": distributions,
                        "sponsor_table": returns.get("sponsor"),
                        "sponsor_source": returns.get("sponsor_source"),
                        "distribution_source": returns.get("distribution_source"),
                        "scenario": identity.get("scenario") if isinstance(identity, Mapping) else None,
                        "ran_at": identity.get("ran_at") if isinstance(identity, Mapping) else None,
                        "engine_version": identity.get("engine_version") if isinstance(identity, Mapping) else None},
            "freshness": {"state": state, "basis": context.freshness.source,
                          "is_stale": context.freshness.is_stale},
            "integrity": outputs.get("integrity"),
            "integrity_available": integrity_state == "AVAILABLE",
            "status_dimensions": dimensions,
            "banner": outputs.get("banner") or "",
        }
        context.validate_current()
        return _json(payload)
    except (PostRunContextChanged, WorkbookIdentityError, PermissionError):
        return _json({"ok": False, "code": "WORKSPACE_UNAVAILABLE",
                      "message": "The workspace changed while the response was assembled. Reload to refresh."}, 503)


# ───────────────────────────── inputs grid ─────────────────────────────

def _jsonable(value: Any) -> Any:
    from datetime import date, datetime
    from decimal import Decimal
    from uuid import UUID

    if is_dataclass(value):
        return {k: _jsonable(v) for k, v in asdict(value).items()}
    if isinstance(value, dict):
        return {str(k): _jsonable(v) for k, v in value.items()}
    if isinstance(value, (list, tuple)):
        return [_jsonable(v) for v in value]
    if isinstance(value, (datetime, date)):
        return value.isoformat()
    if isinstance(value, Decimal):
        return str(value)
    if isinstance(value, UUID):
        return str(value)
    return value


@router.get("/model-react/inputs")
async def react_workspace_inputs(request: Request, project: str):
    """The canonical Hybrid Inputs grid projection, serialized for the React grid.

    Same builder the legacy grid panel renders (``_build_input_grid_ctx``); the ONLY
    write path remains the existing ``POST /v2/workbook/grid/save``.
    """
    if not react_poc_enabled():
        return _json({"ok": False, "code": "REACT_POC_DISABLED"}, 404)
    user, record, owner, failure = _resolve_project(request, project)
    if failure is not None:
        return failure
    assert record is not None and owner is not None

    from app.persistence.workspace_repository import get_workspace_state
    from app.services.project_library_service import is_protected_reference

    ws = get_workspace_state(owner, record.project_id)
    if ws is None:
        return _json({"ok": False, "code": "WORKSPACE_NOT_FOUND"}, 404)
    from app.v2.router import _build_input_grid_ctx

    try:
        ctx = _build_input_grid_ctx(record, _pis_with_identity(record, owner, ws), ws, owner,
                                    project_editable=not is_protected_reference(record))
        projection = _jsonable(ctx.get("input_grid"))
    except Exception:  # noqa: BLE001 - presentation adapter fails closed, never fabricates
        return _json({"ok": False, "code": "GRID_PROJECTION_UNAVAILABLE",
                      "message": "The input grid could not be projected. Reload to refresh."}, 503)

    from app.workbook.input_set import ProjectInputSet
    from app.workbook.registry import WORKBOOK
    from app.workbook.workbook_identity import assemble_consistent_for_get, WorkbookIdentityError

    try:
        identity = assemble_consistent_for_get(owner, record.project_id, WORKBOOK.version)
        composite_hash = identity.composite_hash
    except WorkbookIdentityError:
        return _json({"ok": False, "code": "WORKSPACE_UNAVAILABLE",
                      "message": "The workspace identity could not be assembled. Reload to refresh."}, 503)
    return _json({
        "ok": True,
        "react_workspace": {"version": REACT_WORKSPACE_VERSION},
        "project": {"code": record.project_code,
                    "name": getattr(record, "project_name", None) or record.project_code,
                    "protected_reference": is_protected_reference(record)},
        "grid": projection,
        "save": {"url": "/v2/workbook/grid/save",
                 "csrf_token": generate_csrf_token(),
                 "content_hash": composite_hash,
                 "workbook_version": WORKBOOK.version,
                 "scenario_id": ws.active_scenario_id,
                 "max_cells": 50,
                 "max_value_chars": 64},
        "cost_line_boundary": {
            "note": "CAPEX/OPEX line items are NOT saved through the scalar grid writer; "
                    "their canonical batch writer (grid/cost-lines/save) is out of this PR's scope.",
            "capex_opex_editable": False,
        },
    })


def _pis_with_identity(record, owner: str, ws):
    """Same PIS assembly the legacy grid panel uses before rendering."""
    from app.v2.router import _build_pis_with_composite_identity

    return _build_pis_with_composite_identity(ws, record, owner)


# ─────────────────── UX-04/05/06: canonical surface projections ───────────────────
#
# Read-only JSON projections over the SAME canonical authorities the legacy V2
# workbook uses.  Every mutation stays on the existing canonical writer route:
# scalar/financing fields on POST /v2/workbook/update (bound financing CSRF),
# CAPEX/OPEX line batches on POST /v2/workbook/grid/cost-lines/save, revenue
# contracts on POST /v2/workbook/revenue/contracts, Run on POST /v2/workbook/run
# (form contract, 303 on success / ?v2_err=… on failure — no new Run authority).
# Nothing here computes, estimates or fabricates a financial value.

_REACT_FIELD_SHEETS = ("project_setup", "debt", "revenue", "tax")


def _identity_tokens(record, owner: str):
    """Composite CAS identity + the canonical save tokens, or a fail-closed response."""
    from app.workbook.registry import WORKBOOK
    from app.workbook.workbook_identity import WorkbookIdentityError, assemble_consistent_for_get

    try:
        identity = assemble_consistent_for_get(owner, record.project_id, WORKBOOK.version)
    except WorkbookIdentityError:
        return None, _json({"ok": False, "code": "WORKSPACE_UNAVAILABLE",
                            "message": "The workspace identity could not be assembled. Reload to refresh."}, 503)
    return {"csrf_token": generate_csrf_token(),
            "content_hash": identity.composite_hash,
            "workbook_version": WORKBOOK.version}, None


def _workspace_or_404(record, owner: str):
    from app.persistence.workspace_repository import get_workspace_state

    ws = get_workspace_state(owner, record.project_id)
    if ws is None:
        return None, _json({"ok": False, "code": "WORKSPACE_NOT_FOUND"}, 404)
    return ws, None


def _pis_or_503(record, owner: str, ws):
    """The canonical PIS assembly, failing closed as the inputs projection does."""
    try:
        return _pis_with_identity(record, owner, ws), None
    except Exception:  # noqa: BLE001 - presentation adapter fails closed, never fabricates
        return None, _json({"ok": False, "code": "SHEET_PROJECTION_UNAVAILABLE",
                            "message": "The sheet could not be projected. Reload to refresh."}, 503)


def _is_protected(record) -> bool:
    from app.services.project_library_service import is_protected_reference

    return is_protected_reference(record)


@router.get("/model-react/fields/{sheet_id}")
async def react_sheet_fields(request: Request, sheet_id: str, project: str):
    """Registry-sheet field grid (project_setup | debt | revenue | tax).

    One entry per canonical FieldSpec with its binding label ("bound" = editable
    through POST /v2/workbook/update, "partial", "display-only", "template-locked")
    and validation metadata.  Financing fields authenticate with the BOUND
    financing CSRF token the legacy financing form uses; everything else uses the
    grid CSRF token.  No values are computed here — they come from the same PIS
    the legacy sheets render.
    """
    if not react_poc_enabled():
        return _json({"ok": False, "code": "REACT_POC_DISABLED"}, 404)
    if sheet_id not in _REACT_FIELD_SHEETS:
        return _json({"ok": False, "code": "SHEET_UNKNOWN"}, 404)
    user, record, owner, failure = _resolve_project(request, project)
    if failure is not None:
        return failure
    assert record is not None and owner is not None
    ws, failure = _workspace_or_404(record, owner)
    if failure is not None:
        return failure
    pis, failure = _pis_or_503(record, owner, ws)
    if failure is not None:
        return failure
    tokens, failure = _identity_tokens(record, owner)
    if failure is not None:
        return failure

    from app.v2.router import _build_sheet_fields
    from app.workbook.financing_csrf import issue_token

    try:
        fields = _jsonable(_build_sheet_fields(sheet_id, pis))
    except Exception:  # noqa: BLE001 - fail closed
        return _json({"ok": False, "code": "SHEET_PROJECTION_UNAVAILABLE",
                      "message": "The sheet could not be projected. Reload to refresh."}, 503)
    return _json({
        "ok": True,
        "react_workspace": {"version": REACT_WORKSPACE_VERSION},
        "sheet": sheet_id,
        "project": {"code": record.project_code,
                    "protected_reference": _is_protected(record)},
        "fields": fields,
        "save": {"url": "/v2/workbook/update",
                 "method": "form",
                 "csrf_token": tokens["csrf_token"],
                 "financing_csrf_token": issue_token(request, project),
                 "content_hash": tokens["content_hash"],
                 "workbook_version": tokens["workbook_version"]},
    })



def _eligible_cost_groups(sheet: str) -> list[dict[str, str]]:
    """Groups that accept a custom row, from the same sets the canonical command
    checks use (rejected and derived groups are excluded; the server still
    re-validates every Add)."""
    if sheet == "capex":
        from app.persistence.capex_sub_lines import ALLOWED_PARENT_CATEGORIES
        from app.v2.capex_commands import _DERIVED_GROUP_CODES
        codes = sorted(set(ALLOWED_PARENT_CATEGORIES) - set(_DERIVED_GROUP_CODES))
    else:
        from app.persistence.opex_sub_lines import ALLOWED_PARENT_GROUPS
        from app.v2.opex_commands import _DERIVED_GROUP_CODES
        codes = sorted(set(ALLOWED_PARENT_GROUPS) - set(_DERIVED_GROUP_CODES))
    labels: dict[str, str] = {}
    if sheet == "capex":
        # Presentation names of the canonical C.NN catalogue (the authority is the code set above).
        labels = {f"C.{i:02d}": f"C.{i:02d} {name}" for i, name in enumerate((
            "Production Units", "EPC Contract", "Grid Connection", "Operations Preparation", "Other EPC Costs",
            "Construction Insurances", "Lease / Construction Taxes", "Audit & Legal", "Construction Management A",
            "Commissioning", "Other Professional Services", "Construction Management B", "Contingency",
            "Construction Taxes", "Project Acquisition / Development", "Project Rights"), start=1)}
    try:
        if sheet == "opex":
            from app.ui.opex_sheet_projection import CANONICAL_OPEX_GROUPS
            labels = {g.code: f"{g.code} {g.name}" for g in CANONICAL_OPEX_GROUPS}
    except Exception:  # noqa: BLE001 - labels are presentation only
        labels = {}
    return [{"code": code, "label": labels.get(code, code)} for code in codes]

@router.get("/model-react/costlines")
async def react_cost_lines(request: Request, sheet: str = "capex", project: str = ""):
    """CAPEX/OPEX line-item projection + the canonical batch Save contract.

    Rows come from the same loaders the atomic batch writer verifies row versions
    against; the only write path remains POST /v2/workbook/grid/cost-lines/save.
    """
    if not react_poc_enabled():
        return _json({"ok": False, "code": "REACT_POC_DISABLED"}, 404)
    if sheet not in ("capex", "opex"):
        return _json({"ok": False, "code": "SHEET_UNKNOWN"}, 404)
    user, record, owner, failure = _resolve_project(request, project)
    if failure is not None:
        return failure
    assert record is not None and owner is not None
    tokens, failure = _identity_tokens(record, owner)
    if failure is not None:
        return failure

    try:
        from app.v2.cost_batch_commands import MAX_BATCH_LINES, _list_capex, _list_opex
        from app.persistence.db import get_connection

        with get_connection() as conn:
            cur = conn.cursor()
            rows = (_list_capex if sheet == "capex" else _list_opex)(cur, record.project_id, include_inactive=True)
        lines = [{"sub_line_id": r.sub_line_id, "label": r.label, "amount_keur": r.amount_keur,
                  "row_version": r.updated_at, "notes": getattr(r, "comments", None),
                  "inflation_pct": getattr(r, "inflation_pct", None), "active": r.is_active,
                  "category": getattr(r, "parent_category_code", None) or getattr(r, "parent_group_code", "")}
                 for r in rows]
        eligible_groups = _eligible_cost_groups(sheet)
    except Exception:  # noqa: BLE001 - fail closed, never fabricate line items
        return _json({"ok": False, "code": "COST_LINES_UNAVAILABLE",
                      "message": "Cost lines could not be projected. Reload to refresh."}, 503)
    return _json({
        "ok": True,
        "react_workspace": {"version": REACT_WORKSPACE_VERSION},
        "sheet": sheet,
        "project": {"code": record.project_code,
                    "protected_reference": _is_protected(record)},
        "lines": lines,
        "save": {"url": "/v2/workbook/grid/cost-lines/save",
                 "method": "form",
                 "csrf_token": tokens["csrf_token"],
                 "content_hash": tokens["content_hash"],
                 "workbook_version": tokens["workbook_version"],
                 "max_batch_lines": MAX_BATCH_LINES},
        # WF-React-2: canonical line-management routes.  Only deactivation
        # (soft delete) exists - there is no hard delete.  These routes carry
        # composite CAS (content_hash + workbook_version, row_version) and are
        # inventoried as having no CSRF token; the projection does not hide that.
        "line_management": {
            "add": {"url": f"/v2/{sheet}/line/add",
                    "group_field": "parent_category_code" if sheet == "capex" else "parent_group_code"},
            "deactivate": {"url": f"/v2/{sheet}/line/deactivate"},
            "reactivate": {"url": f"/v2/{sheet}/line/reactivate"},
            "eligible_groups": eligible_groups,
            "csrf_note": "The canonical line routes validate composite CAS and row versions; they do not "
                         "carry a CSRF token (inventoried gap, unchanged by this workflow).",
        },
    })


@router.get("/model-react/revenue")
async def react_revenue_contracts(request: Request, project: str):
    """Revenue/PPA contract editor projection + the canonical Save contract.

    The editor state is the SAME builder the legacy revenue contract form renders;
    the only write path remains POST /v2/workbook/revenue/contracts (composite CAS,
    bound CSRF, 409 on conflict).  No price or allocation is calculated here.
    """
    if not react_poc_enabled():
        return _json({"ok": False, "code": "REACT_POC_DISABLED"}, 404)
    user, record, owner, failure = _resolve_project(request, project)
    if failure is not None:
        return failure
    assert record is not None and owner is not None
    ws, failure = _workspace_or_404(record, owner)
    if failure is not None:
        return failure
    pis, failure = _pis_or_503(record, owner, ws)
    if failure is not None:
        return failure
    tokens, failure = _identity_tokens(record, owner)
    if failure is not None:
        return failure

    from app.v2.router import _build_revenue_contract_editor
    from app.workbook.financing_csrf import issue_token

    try:
        editor = _jsonable(_build_revenue_contract_editor(pis, ws))
    except Exception:  # noqa: BLE001 - fail closed
        return _json({"ok": False, "code": "REVENUE_PROJECTION_UNAVAILABLE",
                      "message": "Revenue contracts could not be projected. Reload to refresh."}, 503)
    return _json({
        "ok": True,
        "react_workspace": {"version": REACT_WORKSPACE_VERSION},
        "project": {"code": record.project_code,
                    "protected_reference": _is_protected(record)},
        "contracts": editor,
        "save": {"url": "/v2/workbook/revenue/contracts",
                 "method": "form",
                 # the canonical writer validates the PLAIN grid CSRF token
                 # (validate_csrf_token); no bound financing token here
                 "csrf_token": tokens["csrf_token"],
                 "content_hash": tokens["content_hash"],
                 "workbook_version": tokens["workbook_version"]},
    })



def _last_run_export_availability(record, owner) -> tuple[bool, str]:
    """Whether the canonical Last Run export would succeed for the ACTIVE scenario.

    Uses the same single-read resolver the export route uses (no engine, no
    write), so the React client never offers a download the server will refuse -
    for example right after selecting a scenario that has no committed Run.
    """
    if (getattr(record, "project_origin", "") or "") != "user_created":
        return False, "Only Working Copies created by a user can be exported."
    try:
        from app.persistence.workspace_repository import get_workspace_state
        from app.services.export_service import resolve_canonical_last_run_from_workspace

        resolve_canonical_last_run_from_workspace(record, owner, get_workspace_state(owner, record.project_id))
    except ValueError:
        return False, "No committed Run exists for the active scenario."
    except Exception:  # noqa: BLE001 - fail closed; the route itself re-validates
        return False, "The Last Run could not be read."
    return True, ""

@router.get("/model-react/runs")
async def react_run_history(request: Request, project: str):
    """Persisted Run History + the committed Last Run identity.

    Every entry comes from the canonical run-history repository (immutable
    committed evidence); unavailable fields stay null and are never substituted.
    """
    if not react_poc_enabled():
        return _json({"ok": False, "code": "REACT_POC_DISABLED"}, 404)
    user, record, owner, failure = _resolve_project(request, project)
    if failure is not None:
        return failure
    assert record is not None and owner is not None

    from app.persistence.run_history_repository import get_run_history

    try:
        history = get_run_history(owner, record.project_id)
    except Exception:  # noqa: BLE001 - fail closed
        return _json({"ok": False, "code": "RUN_HISTORY_UNAVAILABLE",
                      "message": "Run history could not be read. Reload to refresh."}, 503)
    entries = []
    for entry in history:
        data = entry.to_dict() if hasattr(entry, "to_dict") else dict(entry)
        # Summary is an allowlist over immutable ledger identity, not the full
        # financial payload or actor identifiers. Detail/export keep their own
        # canonical authorization and persisted evidence surfaces.
        entries.append(_jsonable({key: data.get(key) for key in (
            "history_id", "project_code", "runtime_snapshot_id", "runtime_origin",
            "ran_at", "engine_version", "workbook_version", "active_scenario_id",
            "active_scenario_name", "last_runtime_scenario_id", "composite_hash",
        )}))
    export_available, export_reason = _last_run_export_availability(record, owner)
    return _json({
        "ok": True,
        "react_workspace": {"version": REACT_WORKSPACE_VERSION},
        "project": {"code": record.project_code,
                    "protected_reference": _is_protected(record)},
        "runs": entries,
        # WF-React-2: read-only canonical export entry points.  The Last Run
        # export always reflects the last COMMITTED Run, never unsaved or newer
        # Working Copy edits; the historical export is bound to one immutable row.
        "exports": {
            "last_run": {"url": "/v2/workbook/export", "method": "form-download",
                         "authority": "CANONICAL_LAST_RUN",
                         "available": export_available,
                         "unavailable_reason": export_reason,
                         "note": "Exports the inputs and results of the last committed Run, "
                                 "not the current Working Copy edits."},
            "historical": {"url": "/v2/workbook/run-history/export", "query": ["project", "history_id"],
                           "note": "One immutable committed Run; no engine execution."},
        },
        "run_contract": {"url": "/v2/workbook/run",
                         "csrf_token": _issue_csrf_token(request, project, purpose="workbook-run-v1"),
                         "method": "form",
                         "note": "Run initiation stays on the canonical route; success redirects "
                                 "(303) to the workbook, failures redirect with ?v2_err=. "
                                 "Save NEVER triggers a Run."},
    })


@router.get("/model-react/diagnostics")
async def react_diagnostics(request: Request, project: str):
    """Model Quality / diagnostics projection over the committed Last Run.

    ``build_quality_insight_safe`` is the canonical fail-closed evaluator: every
    check is evaluated from persisted evidence only; NOT RUN stays NOT RUN and a
    stale Working Copy is reported as STALE, never as current.
    """
    if not react_poc_enabled():
        return _json({"ok": False, "code": "REACT_POC_DISABLED"}, 404)
    user, record, owner, failure = _resolve_project(request, project)
    if failure is not None:
        return failure
    assert record is not None and owner is not None
    from app.v2.diagnostics_client import diagnostics_client_payload
    from app.v2.insight_quality_projection import build_quality_insight_safe
    from app.v2.post_run_context import PostRunContextChanged, PostRunRequestContext
    from app.workbook.workbook_identity import WorkbookIdentityError

    try:
        context = PostRunRequestContext.capture(owner_id=owner, project_id=record.project_id)
        effective_inputs = None
        if context.freshness.state.value == "CURRENT":
            try:
                effective_inputs = context.inputs.to_projectinputs()
            except Exception:  # thresholds stay unbound without valid effective inputs
                pass
        from app.persistence.scenario_insight_reads import resolve_last_run_scenario
        scenario_name = resolve_last_run_scenario(
            owner, record.project_id, context.workspace.last_runtime_scenario_id).label
        projection = build_quality_insight_safe(
            context.workspace, run_state=context.freshness.state.value,
            project_inputs=effective_inputs,
            active_scenario_id=context.workspace.active_scenario_id,
            scenario_name=scenario_name or "",
            include_diagnostics=True)
        diagnostics = projection.get("diagnostics")
        from app.api.v1_1.institutional import get_run_integrity_checks
        integrity_state, integrity = get_run_integrity_checks(owner, record.project_id, context=context)
        context.validate_current()
        return _json({
            "ok": True,
            "react_workspace": {"version": REACT_WORKSPACE_VERSION},
            "project": {"code": record.project_code,
                        "protected_reference": _is_protected(record)},
            "run_state": context.freshness.state.value,
            "integrity": integrity if integrity_state == "AVAILABLE" else None,
            "insight": {k: v for k, v in projection.items() if k != "diagnostics"},
            "diagnostics": (diagnostics_client_payload(diagnostics) if isinstance(diagnostics, dict)
                            else {"state": "UNAVAILABLE", "available": False}),
        })
    except (PostRunContextChanged, WorkbookIdentityError, PermissionError):
        return _json({"ok": False, "code": "DIAGNOSTICS_UNAVAILABLE",
                      "message": "The workspace changed while diagnostics were assembled. Reload to refresh."}, 503)


@router.get("/model-react/trust")
async def react_trust(request: Request, project: str):
    """Read persisted Run integrity only; never run a regression or sign on GET.

    Reference regression and certificate issuance are separate explicit actions
    on the existing authorized canonical routes, not validation of this project.
    """
    if not react_poc_enabled():
        return _json({"ok": False, "code": "REACT_POC_DISABLED"}, 404)
    user, record, owner, failure = _resolve_project(request, project)
    if failure is not None:
        return failure
    assert record is not None and owner is not None

    from urllib.parse import urlencode
    from app.api.v1_1.institutional import get_run_integrity_checks, get_run_identity
    from app.v2.post_run_context import PostRunContextChanged, PostRunRequestContext
    from app.workbook.workbook_identity import WorkbookIdentityError

    try:
        context = PostRunRequestContext.capture(owner_id=owner, project_id=record.project_id)
        identity_state, identity = get_run_identity(owner, record.project_id, context=context)
        integrity_state, integrity = get_run_integrity_checks(owner, record.project_id, context=context)
        has_run = identity_state == "AVAILABLE" and context.freshness.has_runtime
        query = urlencode({"project": record.project_code})
        validation = {
            "state": "DEFERRED" if has_run else "UNAVAILABLE",
            "reason": "EXPLICIT_REFERENCE_REGRESSION_REQUIRED" if has_run else "COMMITTED_LAST_RUN_REQUIRED",
            "authority": "REFERENCE_REGRESSION_CHECK",
            "scope": "Pinned canonical reference regression only; not validation of this Working Copy or its Run.",
            "load_url": f"/v2/workbook/trust/validation?{query}" if has_run else None,
            "not_verify": True,
        }
        certificate = {
            "state": "DEFERRED" if has_run else "UNAVAILABLE",
            "reason": "EXPLICIT_CERTIFICATE_REQUEST_REQUIRED" if has_run else "COMMITTED_LAST_RUN_REQUIRED",
            "authority": "SIGNED_RUN_CERTIFICATE",
            "scope": "Provenance only; availability and signing-key readiness are not established by this read.",
            "load_url": f"/v2/workbook/trust/certificate?{query}" if has_run else None,
            "not_verify": True,
        }
        context.validate_current()
        return _json({
            "ok": True,
            "react_workspace": {"version": REACT_WORKSPACE_VERSION},
            "project": {"code": record.project_code,
                        "protected_reference": _is_protected(record)},
            "run_state": context.freshness.state.value,
            "identity": identity if identity_state == "AVAILABLE" else None,
            "integrity": integrity if integrity_state == "AVAILABLE" else None,
            "certificate": certificate,
            "validation": validation,
        })
    except (PostRunContextChanged, WorkbookIdentityError, PermissionError):
        return _json({"ok": False, "code": "TRUST_UNAVAILABLE",
                      "message": "The workspace changed while trust evidence was assembled. Reload to refresh."}, 503)


# ───────────────────── UX-07: scenario management & compare ─────────────────────
#
# Scenario management projects the canonical scenario records; every mutation
# (create/select/rename/archive) stays on the existing canonical form routes.
# The compare projection lists ASSUMPTION-LEVEL differences (override keys and
# values) and the persisted Run identity of each side; financial KPI deltas are
# NOT computed here — statements/results come from the persisted evidence
# projections, and a missing comparable side is reported unavailable, never zero.

_REACT_SCENARIO_SHEET = "debt"  # kept for reference; scenarios are not registry fields


@router.get("/model-react/scenarios")
async def react_scenarios(request: Request, project: str):
    """Scenario records + the active scenario, projected from the canonical
    scenario repository.  Mutations remain on the canonical form routes:
    POST /v2/workbook/scenarios/{create,select,rename,archive}."""
    if not react_poc_enabled():
        return _json({"ok": False, "code": "REACT_POC_DISABLED"}, 404)
    user, record, owner, failure = _resolve_project(request, project)
    if failure is not None:
        return failure
    assert record is not None and owner is not None
    ws, failure = _workspace_or_404(record, owner)
    if failure is not None:
        return failure

    from app.persistence.scenarios_repository import list_scenarios

    try:
        records = list_scenarios(owner, record.project_id, include_archived=True)
    except Exception:  # noqa: BLE001 - fail closed
        return _json({"ok": False, "code": "SCENARIOS_UNAVAILABLE",
                      "message": "Scenarios could not be read. Reload to refresh."}, 503)
    scenarios = [{
        "scenario_id": r.scenario_id,
        "name": r.scenario_name,
        "is_base_case": bool(r.is_base_case),
        "archived": bool(r.archived),
        "override_count": len(r.overrides or {}),
        "updated_at": _jsonable(getattr(r, "updated_at", None)),
        "active": r.scenario_id == ws.active_scenario_id,
    } for r in records]
    return _json({
        "ok": True,
        "react_workspace": {"version": REACT_WORKSPACE_VERSION},
        "project": {"code": record.project_code,
                    "protected_reference": _is_protected(record)},
        "active_scenario_id": ws.active_scenario_id,
        "active_scenario_name": ws.active_scenario_name,
        "scenarios": scenarios,
        "mutations": {
            "create": {"url": "/v2/workbook/scenarios/create", "fields": ["project", "scenario_name"]},
            "select": {"url": "/v2/workbook/scenarios/select", "fields": ["project", "scenario_id"]},
            "rename": {"url": "/v2/workbook/scenarios/rename", "fields": ["project", "scenario_id", "new_name"]},
            "archive": {"url": "/v2/workbook/scenarios/archive", "fields": ["project", "scenario_id"]},
            "note": "Form routes of the canonical scenario authority. Creating or selecting a "
                    "scenario NEVER starts a Run.",
        },
    })


@router.get("/model-react/scenario-compare")
async def react_scenario_compare(request: Request, project: str, scenario_id: str = ""):
    """Assumption-level compare between the canonical Base Case snapshot and the
    EFFECTIVE resolved scenario inputs.

    Resolution goes through ``resolve_scenario_snapshot`` — the established
    canonical authority: an override replaces its Base value only for keys in
    ``SCENARIO_INPUT_FIELDS``; every other key inherits, so a newly created
    scenario with empty overrides reports ZERO differences.  An explicitly
    overridden zero is distinguished from an absent override by the
    ``explicitly_overridden`` flag.  Persisted Run identities are attributed per
    side from the immutable run history (``active_scenario_id``); a side with no
    committed Run is UNAVAILABLE and never borrows the other side's Last Run.
    Financial KPI deltas are not computed in the browser.
    """
    if not react_poc_enabled():
        return _json({"ok": False, "code": "REACT_POC_DISABLED"}, 404)
    user, record, owner, failure = _resolve_project(request, project)
    if failure is not None:
        return failure
    assert record is not None and owner is not None
    ws, failure = _workspace_or_404(record, owner)
    if failure is not None:
        return failure

    from app.persistence._helpers import SCENARIO_INPUT_FIELDS
    from app.persistence.run_history_repository import get_run_history
    from app.persistence.scenarios_repository import get_scenario, resolve_scenario_snapshot

    scenario = get_scenario(scenario_id, owner) if scenario_id else None
    if scenario_id and (scenario is None or scenario.project_id != record.project_id or scenario.archived):
        # Foreign and archived scenarios are denied outright (404: not a
        # comparable case of this project).
        return _json({"ok": False, "code": "SCENARIO_NOT_FOUND"}, 404)

    base_snapshot = dict(ws.draft_snapshot or {})
    overrides = dict(scenario.overrides or {}) if scenario is not None else {}
    effective = resolve_scenario_snapshot(base_snapshot, overrides)

    differences = []
    for key in sorted(SCENARIO_INPUT_FIELDS):
        base_value = base_snapshot.get(key)
        scenario_value = effective.get(key)
        if scenario_value != base_value:
            differences.append({
                "field_id": key,
                "base_value": _jsonable(base_value),
                "scenario_value": _jsonable(scenario_value),
                "explicitly_overridden": key in overrides,
                "scenario_only": base_value is None and key in overrides,
            })

    # Persisted Run identities, attributed per side from the immutable history.
    try:
        history = get_run_history(owner, record.project_id)
        entries = [entry.to_dict() if hasattr(entry, "to_dict") else dict(entry) for entry in history]
    except Exception:  # noqa: BLE001 - evidence read fails closed to UNAVAILABLE
        entries = None
    def _runs_for(sid: Optional[str]) -> list[dict[str, Any]]:
        if entries is None:
            return []
        if sid is None:
            return [e for e in entries if not e.get("active_scenario_id")]
        return [e for e in entries if e.get("active_scenario_id") == sid]

    scenario_side_runs = _runs_for(scenario.scenario_id) if scenario is not None else []
    latest = scenario_side_runs[0] if scenario_side_runs else None
    scenario_run_evidence = (
        {"snapshot_id": latest.get("runtime_snapshot_id"), "ran_at": latest.get("ran_at"),
         "history_id": latest.get("history_id"), "state": "AVAILABLE"} if latest
        else {"state": "UNAVAILABLE", "note": "No committed Run exists for this scenario."}
        if entries is not None
        else {"state": "UNAVAILABLE", "note": "Run history could not be read."}
    )
    return _json({
        "ok": True,
        "react_workspace": {"version": REACT_WORKSPACE_VERSION},
        "project": {"code": record.project_code,
                    "protected_reference": _is_protected(record)},
        "base": {"label": f"Working Copy / {ws.active_scenario_name or 'Base Case'}",
                 "scenario_id": ws.active_scenario_id,
                 "run_evidence": {"state": "UNAVAILABLE",
                                  "note": "Run history is attributed to the scenario it was committed "
                                          "under; the Working Copy side does not borrow another case's "
                                          "Last Run. Use the runs projection for the committed evidence."}},
        "scenario": ({"label": scenario.scenario_name, "scenario_id": scenario.scenario_id,
                      "archived": bool(scenario.archived),
                      "override_count": len(overrides),
                      "run_evidence": scenario_run_evidence} if scenario is not None else None),
        "differences": differences,
        "kpi_compare": {"available": False,
                        "reason": "Financial KPI deltas are not computed in the browser; "
                                  "persisted statements/results projections carry the evidence."},
    })


@router.get("/model-react/scenario-overrides")
async def react_scenario_overrides(request: Request, project: str, scenario_id: str):
    """Override-editor projection for ONE non-base scenario.

    Lists exactly the fields the canonical Run applies (`supported_editor_fields`),
    each with its Working Copy value, the persisted override (if any) and whether
    the effective value is inherited or overridden.  Other overrides stay out of
    the editor.  Read-only: edits go through the canonical
    /v2/workbook/scenarios/{update-overrides,remove-override} routes.
    """
    if not react_poc_enabled():
        return _json({"ok": False, "code": "REACT_POC_DISABLED"}, 404)
    user, record, owner, failure = _resolve_project(request, project)
    if failure is not None:
        return failure
    assert record is not None and owner is not None
    ws, failure = _workspace_or_404(record, owner)
    if failure is not None:
        return failure

    from app.persistence.scenarios_repository import get_scenario
    from app.v2.scenario_presentation import OVERRIDE_EDITOR_FIELDS
    from app.workbook.scenario_override_authority import supported_editor_fields

    scenario = get_scenario(scenario_id, owner)
    if scenario is None or scenario.project_id != record.project_id or scenario.archived:
        return _json({"ok": False, "code": "SCENARIO_NOT_FOUND"}, 404)
    base = dict(ws.draft_snapshot or {})
    overrides = dict(scenario.overrides or {})
    supported = set(supported_editor_fields())
    fields = [{
        "field_id": key, "label": label, "unit": unit,
        "base_value": _jsonable(base.get(key)),
        "override_value": _jsonable(overrides[key]) if key in overrides else None,
        "overridden": key in overrides,
    } for key, label, unit in OVERRIDE_EDITOR_FIELDS if key in supported]
    editable = not scenario.is_base_case and not _is_protected(record)
    return _json({
        "ok": True,
        "react_workspace": {"version": REACT_WORKSPACE_VERSION},
        "project": {"code": record.project_code, "protected_reference": _is_protected(record)},
        "scenario": {"scenario_id": scenario.scenario_id, "name": scenario.scenario_name,
                     "is_base_case": bool(scenario.is_base_case)},
        "editable": editable,
        "fields": fields,
        "unsupported_override_keys": sorted(k for k in overrides if k not in supported),
        "mutations": {
            "update": {"url": "/v2/workbook/scenarios/update-overrides", "fields": ["project", "scenario_id", "<field_id>"]},
            "remove": {"url": "/v2/workbook/scenarios/remove-override", "fields": ["project", "scenario_id", "field"]},
            "note": "The canonical Run applies only the fields listed here; any other override is refused "
                    "(SCENARIO_OVERRIDE_UNBOUND). Saving an override never runs the model.",
        },
    })
