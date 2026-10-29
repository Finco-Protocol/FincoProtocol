"""WS1 read-only, Run-bound Overview supplement. No writes or financial arithmetic.

Inputs come exclusively from last_runtime_snapshot, never the current draft.
Sources & Uses uses the released financing evidence projector. The caller must
match snapshot_id to the statements it displays; validate_current fences races.
"""
from __future__ import annotations

import logging

from fastapi import APIRouter, Request

from app.v2.react_projects import _gate, _json

router = APIRouter()
log = logging.getLogger(__name__)


@router.get("/model-react/overview")
async def react_overview(request: Request, project: str):
    user, refused = _gate(request)
    if refused is not None:
        return refused
    from app.persistence.projects_repository import resolve_accessible_project
    from app.v2.post_run_context import PostRunRequestContext
    from app.v2.react_financing import _sources_uses
    from app.v2.react_projects import _KEY_ASSUMPTIONS, display_value
    from app.v2.react_workspace_router import _jsonable, _vertical_scope
    from app.workbook.input_set import ProjectInputSet
    from app.workbook.registry import WORKBOOK
    from app.workbook.runtime_projection import thaw_runtime_payload

    record, owner = resolve_accessible_project(user.user_id, project)
    if record is None:
        return _json({"ok": False, "code": "PROJECT_NOT_FOUND"}, 404)
    try:
        context = PostRunRequestContext.capture(owner_id=owner, project_id=record.project_id)
        context.require_scope(owner, record.project_id)
        context.require_binding(context.workspace, context.project_record, context.runtime_result)
        runtime = context.runtime_result
        assumptions = []
        if runtime is not None:
            saved = ProjectInputSet.from_snapshot(thaw_runtime_payload(context.workspace.last_runtime_snapshot))
            # Coercion failures must not quietly render a partial approved input set.
            if saved.coercion_errors:
                raise ValueError("Unreadable committed assumptions")
            fields = (("project_setup.technical.capacity_mw", None),
                      ("project_setup.technical.cod_date", None)) + _KEY_ASSUMPTIONS.get(_vertical_scope(record)["key"], ())
            for field_id, label in fields:
                # The input adapter prefers the canonical PPA keys when present.
                # A template catalogue's legacy-only Wind labels cannot override that.
                canonical = {"revenue.ppa.tariff_legacy": "revenue.ppa.base_tariff",
                             "revenue.ppa.ppa_term_legacy": "revenue.ppa.term_years"}.get(field_id)
                if canonical and saved.get(canonical) not in (None, ""):
                    field_id = canonical
                value = saved.get(field_id)
                spec = WORKBOOK.field(field_id)
                assumptions.append({"field_id": field_id, "label": label or spec.label,
                                    "display": display_value(value), "unit": spec.unit or "",
                                    "value": value if isinstance(value, (int, float)) and not isinstance(value, bool) else None,
                                    "available": value is not None and value != ""})
        payload = {"ok": True, "project": {"code": record.project_code},
                   "snapshot_id": runtime.snapshot_id if runtime is not None else None,
                   "content_hash": context.workspace.last_runtime_composite_hash,
                   "scenario_id": context.workspace.last_runtime_scenario_id,
                   "assumptions": assumptions,
                   "sources_uses": _sources_uses(context, owner, record)}
        context.validate_current()
        return _json(_jsonable(payload))
    except Exception:  # fail closed; no stored exception data crosses the response boundary
        log.warning("react_overview: bound evidence unavailable (details withheld)")
        return _json({"ok": False, "code": "OVERVIEW_UNAVAILABLE",
                      "message": "The saved Run summary could not be read consistently. Refresh to retry."}, 503)
