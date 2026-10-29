"""RC-UX Addendum B — read-only JSON adapters for the React "My Projects" Library and the Template catalogue.

Presentation/adapter layer over the EXISTING canonical authorities.  It adds NO economic, default or persistence authority and writes nothing:

* ``GET /model-react/my-projects`` — ONLY the caller's own, editable, saved projects (the same predicate as the canonical
  ``list_workspace_projects_paged``: not archived, not protected, not read-only, not a ``reference``), with their real saved activity time,
  last Run and Run freshness (the canonical ``resolve_runtime_freshness``).  System reference models are never returned.  Filtering and
  ordering are presentation over those records; nothing is estimated and a missing value is ``null``, never a placeholder.
* ``GET /model-react/templates`` — the Project Templates: the approved, read-only reference configurations, discovered from the product
  capability registry.  The starting assumptions are read from the system template's own saved snapshot through the workbook registry
  (labels and units are the registry's); the template itself is never modified.  Creation stays on the existing request-keyed creator.

Honest limits: the library records no "last opened" time, so there is no "recently opened" filter (``edited`` filters on the last saved
activity); "Last updated" is the latest saved change or Run, because the canonical record keeps one activity time.

Feature flag: ``FINCO_MODEL_REACT_V1`` (the same gate as the rest of the React workspace).
"""
from __future__ import annotations

import math
import json
from datetime import datetime, timedelta, timezone
from typing import Any, Optional

from fastapi import APIRouter, Request
from fastapi.responses import JSONResponse

from app.auth import resolve_request_session
from app.v2.react_poc_router import react_poc_enabled

router = APIRouter()

PAGE_SIZE = 12
MAX_PROJECTS_CONSIDERED = 1000
STATUS_FILTERS = ("not_run", "current", "outdated")
EDITED_FILTERS = {"7": 7, "30": 30, "90": 90}
SORTS = ("recent", "name", "last_run")
#: Presentation copy per technology (what the starting configuration describes).  No number is stated here: every figure shown for a
#: template is read from the approved template itself.
_DESCRIPTIONS = {
    "solar": "Utility-scale solar PV with a power purchase agreement, senior project-finance debt and a shareholder loan.",
    "wind": "Onshore wind farm with a power purchase agreement, senior project-finance debt and a shareholder loan.",
    "data_center": "Data center financed on contracted service revenue, with an occupancy ramp-up and senior debt.",
    "ev_charging": "EV charging hub financed on charging revenue, with energy procurement costs and senior debt.",
}
_TECHNOLOGY_NAME = {"solar": "Solar PV", "wind": "Onshore Wind", "data_center": "Data Center", "ev_charging": "EV Charging"}
#: (field id, label override or None to use the registry label) shown as "key starting assumptions"; absent values are omitted.
_COMMON = (("project_setup.technical.construction_months", None), ("project_setup.technical.horizon_years", None),
           ("debt.senior.gearing_pct", None), ("debt.senior.target_dscr", None), ("debt.senior.tenor_years", None),
           ("debt.senior.interest_rate_pct", None))
_KEY_ASSUMPTIONS = {
    "solar": (("revenue.ppa.base_tariff", "PPA tariff"), ("revenue.ppa.term_years", "PPA term"),
              ("project_setup.technical.p50_hours", "Yield (P50 operating hours)")) + _COMMON,
    "wind": (("revenue.ppa.tariff_legacy", "PPA tariff"), ("revenue.ppa.ppa_term_legacy", "PPA term"),
             ("project_setup.technical.p50_hours", "Yield (P50 operating hours)")) + _COMMON,
    "data_center": (("revenue.data_center.service_price", None), ("revenue.data_center.occupancy_stabilized", None),
                    ("revenue.data_center.pue", None), ("revenue.data_center.contract_term", None)) + _COMMON,
    "ev_charging": (("project_setup.technical.p50_hours", "Charging utilisation (full-load hours)"),) + _COMMON,
}


def _json(payload: dict[str, Any], status: int = 200) -> JSONResponse:
    return JSONResponse(payload, status_code=status, headers={"Cache-Control": "private, no-store"})


def _gate(request: Request):
    if not react_poc_enabled():
        return None, _json({"ok": False, "code": "REACT_POC_DISABLED"}, 404)
    user = resolve_request_session(request)
    if user is None:
        return None, _json({"ok": False, "code": "AUTH_REQUIRED"}, 401)
    return user, None


def country_label(code: Optional[str]) -> Optional[str]:
    """Display name of a project's market; the catalogue's trailing technical code is not shown.  ``None`` when never set."""
    import re

    from app.workbook.country_options import COUNTRY_CODE_TO_LABEL

    if not code:
        return None
    label = COUNTRY_CODE_TO_LABEL.get(code, code)
    return re.sub(r"\s*\([A-Z]{2}\)$", "", label)


def _number(value: Any) -> Optional[float]:
    if isinstance(value, bool) or not isinstance(value, (int, float)) or not math.isfinite(float(value)):
        return None
    return float(value)


def display_value(value: Any) -> str:
    n = _number(value)
    if n is None:
        return str(value) if value not in (None, "") else "—"
    return f"{n:,.0f}" if abs(n) >= 1000 or n == int(n) else f"{n:,.2f}".rstrip("0").rstrip(".")


STATUS_LABEL = {"NOT_RUN": "Not run yet", "CURRENT": "Results up to date", "STALE": "Results outdated"}


def _entry(record, ws, request=None) -> dict[str, Any]:
    from urllib.parse import quote

    from app.v2.react_workspace_router import _vertical_scope
    from app.workbook.input_set import ProjectInputSet
    from app.workbook.registry import WORKBOOK
    from app.workbook.runtime_authority import resolve_runtime_freshness
    from app.workbook.workbook_identity import WorkbookIdentityError, assemble_consistent_for_get

    scope = _vertical_scope(record)
    snapshot = (ws.draft_snapshot if ws is not None else None) or {}
    capacity = None
    try:
        capacity = _number(ProjectInputSet.from_snapshot(snapshot).get("project_setup.technical.capacity_mw"))
    except Exception:  # noqa: BLE001 - an unreadable snapshot shows no capacity rather than a guess
        capacity = None
    has_run = bool(ws is not None and (ws.last_runtime_snapshot_id or getattr(ws, "any_run_committed", False)))
    freshness = "NOT_RUN"
    if ws is not None and has_run:
        try:
            from app.persistence.db import get_cursor
            from app.workbook.workbook_identity import assemble_transactional
            with get_cursor() as cursor:
                if not cursor.connection.in_transaction:
                    cursor.execute("BEGIN DEFERRED")
                identity = assemble_transactional(
                    draft_snapshot_json=json.dumps(ws.draft_snapshot or {}), project_id=record.project_id,
                    user_id=record.user_id, active_scenario_id=ws.active_scenario_id,
                    active_scenario_name=ws.active_scenario_name, cursor=cursor, workbook_version=WORKBOOK.version)
            freshness = resolve_runtime_freshness(ws, current_composite_hash=identity.composite_hash).state.value
        except (WorkbookIdentityError, ValueError):
            freshness = "UNKNOWN"
    updated = max([d for d in (getattr(ws, "updated_at", None), getattr(record, "updated_at", None)) if d is not None], default=None)
    last_run_at = getattr(ws, "last_runtime_at", None) if ws is not None else None
    base = f"/v2/model-react/{quote(record.project_code, safe='')}"
    from app.services.project_lifecycle_service import project_capability
    return {
        "lifecycle": project_capability(request, record.user_id, record.project_id) if request is not None else None,
        "_project_id": record.project_id,
        "code": record.project_code, "name": record.project_name or record.project_code,
        "technology": {"key": scope["key"], "label": _TECHNOLOGY_NAME.get(scope["key"], scope["public_name"]), "pilot_tier": scope["pilot_tier"]},
        "country": {"code": snapshot.get("country_market") or None, "label": country_label(snapshot.get("country_market"))},
        "capacity_mw": capacity,
        "capacity_label": "IT capacity" if scope["key"] == "data_center" else "Capacity",
        "last_updated": updated.isoformat() if updated else None,
        "last_run": {"available": bool(has_run and last_run_at), "at": last_run_at.isoformat() if last_run_at else None,
                     "snapshot_id": (getattr(ws, "last_runtime_snapshot_id", None) or None) if has_run else None},
        "has_runs": bool(has_run),
        "freshness": freshness, "status": STATUS_LABEL.get(freshness, "Status unavailable"),
        "archived": bool(getattr(record, "archived", False)),
        "links": {"open": base, "scenarios": f"{base}#scenarios", "run_history": f"{base}?analysis=runs#analysis"},
    }


def _own_records(user_id: str, *, archived: bool):
    from app.persistence.db import get_cursor
    from app.persistence.records import ProjectRecord

    where = ("user_id=? AND archived=? AND is_protected=0 AND is_readonly=0 AND project_role!='reference' "
             "AND (json_extract(replay_metadata_json,'$.create_request.state') IS NULL "
             "OR json_extract(replay_metadata_json,'$.create_request.state')='COMPLETE') "
             "AND (archived=0 OR lifecycle_archive_origin='USER_ACTION')")
    with get_cursor() as cur:
        cur.execute(f"SELECT * FROM projects WHERE {where} ORDER BY project_id DESC",
                    (user_id, 1 if archived else 0))
        return [ProjectRecord.from_row(row) for row in cur.fetchall()]


@router.get("/model-react/my-projects")
async def react_my_projects(request: Request, search: str = "", technology: str = "", country: str = "", status: str = "",
                            has_runs: str = "", edited: str = "", sort: str = "recent", archived: str = "", page: int = 1):
    user, refused = _gate(request)
    if refused is not None:
        return refused
    if (status and status not in STATUS_FILTERS) or (edited and edited not in EDITED_FILTERS) or sort not in SORTS or len(search) > 120:
        return _json({"ok": False, "code": "INVALID_QUERY", "message": "One of the filters is not valid."}, 422)
    from app.persistence.workspace_repository import get_workspace_state

    from app.persistence.db import lifecycle_transaction
    with lifecycle_transaction(readonly=True):
        show_archived = archived in ("1", "true")
        records = _own_records(user.user_id, archived=show_archived)
        needle = search.strip().casefold()
        cutoff = datetime.now(timezone.utc) - timedelta(days=EDITED_FILTERS[edited]) if edited else None
        entries = []
        for record in records:
            ws = get_workspace_state(user_id=record.user_id, project_id=record.project_id)
            entries.append(_entry(record, ws, request))
        facets_t: dict[str, dict[str, Any]] = {}
        facets_c: dict[str, dict[str, Any]] = {}
        for e in entries:
            t = facets_t.setdefault(e["technology"]["key"], {"key": e["technology"]["key"], "label": e["technology"]["label"], "count": 0})
            t["count"] += 1
            if e["country"]["code"]:
                c = facets_c.setdefault(e["country"]["code"], {"code": e["country"]["code"], "label": e["country"]["label"], "count": 0})
                c["count"] += 1

        def keep(e: dict[str, Any]) -> bool:
            # `total_all` and the facets describe ALL of the account's projects; the search narrows only what is listed.
            if needle and needle not in e["name"].casefold():
                return False
            if technology and e["technology"]["key"] != technology:
                return False
            if country and e["country"]["code"] != country:
                return False
            if status and {"not_run": "NOT_RUN", "current": "CURRENT", "outdated": "STALE"}[status] != e["freshness"]:
                return False
            if has_runs in ("1", "true") and not e["has_runs"]:
                return False
            if cutoff is not None:
                stamp = datetime.fromisoformat(e["last_updated"]) if e["last_updated"] else None
                if stamp is None or (stamp if stamp.tzinfo else stamp.replace(tzinfo=timezone.utc)) < cutoff:
                    return False
            return True

        kept = [e for e in entries if keep(e)]
        if sort == "name":
            kept.sort(key=lambda e: (e["name"].casefold(), e["_project_id"]))
        elif sort == "last_run":
            kept.sort(key=lambda e: (e["last_run"]["at"] or "", e["_project_id"]), reverse=True)
        else:
            kept.sort(key=lambda e: (e["last_updated"] or "", e["_project_id"]), reverse=True)
        total = len(kept)
        pages = max(1, math.ceil(total / PAGE_SIZE))
        page = min(max(1, page), pages)
        return _json({
            "ok": True, "projects": kept[(page - 1) * PAGE_SIZE: page * PAGE_SIZE], "total": total, "total_all": len(entries),
            "page": page, "page_size": PAGE_SIZE, "total_pages": pages, "sort": sort, "archived": show_archived,
            "facets": {"technologies": sorted(facets_t.values(), key=lambda f: f["label"]),
                       "countries": sorted(facets_c.values(), key=lambda f: f["label"] or "")},
            "limits": {"considered": len(records), "capped": False},
            "notes": {"last_updated": "The latest saved change or Run.", "recently_opened": "Opening a project is not recorded, so it cannot be filtered on."},
        })


def _starting_assumptions(key: str, snapshot: dict[str, Any]) -> list[dict[str, str]]:
    from app.workbook.input_set import ProjectInputSet
    from app.workbook.registry import WORKBOOK

    try:
        pis = ProjectInputSet.from_snapshot(snapshot)
    except Exception:  # noqa: BLE001 - an unreadable template shows no assumptions rather than guesses
        return []
    out = []
    for field_id, label in _KEY_ASSUMPTIONS.get(key, ()):
        value = pis.get(field_id)
        if value is None or value == "":
            continue
        spec = WORKBOOK.field(field_id)
        out.append({"label": label or spec.label, "value": display_value(value), "unit": spec.unit or ""})
    return out


@router.get("/model-react/templates")
async def react_templates(request: Request):
    user, refused = _gate(request)
    if refused is not None:
        return refused
    from app.persistence.projects_repository import get_reference_by_template_source
    from app.services.project_library_service import ensure_reference_models
    from app.v2.react_new_project import _TECHNOLOGIES, _capability, _creatable, _reference, _timeline
    from app.workbook.country_options import GENERIC_TAX_TEMPLATE_LABEL

    try:
        ensure_reference_models()
    except Exception:  # noqa: BLE001 - the catalogue degrades to "no starting assumptions", never to invented ones
        pass
    templates = []
    for key in ("solar", "wind", "data_center", "ev_charging"):
        creatable, reason = _creatable(key)
        cap = _capability(key)
        card: dict[str, Any] = {
            "key": key, "technology": _TECHNOLOGY_NAME[key], "name": f"{_TECHNOLOGY_NAME[key]} project template",
            "description": _DESCRIPTIONS[key], "creatable": creatable, "reason": reason,
            "pilot_tier": cap["pilot_tier"], "limitations": cap["limitations"][:3],
            "market_note": f"Choose the project's country or market. The {GENERIC_TAX_TEMPLATE_LABEL} applies; the country does not change the assumptions.",
            "preview_acknowledgement_required": creatable and cap["pilot_tier"] != "PILOT_CANDIDATE",
            "starting_assumptions": [], "capacity_mw": None, "capacity_label": "Capacity", "timeline": None,
        }
        if creatable:
            pi = _reference(key)
            card.update(capacity_mw=float(pi.technical.capacity_mw), timeline=_timeline(pi),
                        capacity_label="IT capacity" if key == "data_center" else ("Charging capacity" if key == "ev_charging" else "Installed capacity"))
            record = get_reference_by_template_source(_TECHNOLOGIES[key][0])
            if record is not None:
                card["starting_assumptions"] = _starting_assumptions(key, record.baseline_snapshot or {})
        templates.append(card)
    return _json({"ok": True, "templates": templates,
                  "semantics": {"read_only": True, "template_is_a_project": False,
                                "note": "A template is a starting point. Creating from it makes a new project you own; the template itself never changes."}})
