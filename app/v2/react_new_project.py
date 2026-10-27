"""RC-M Lane A — authenticated JSON adapter for the React New Project wizard.

Presentation/adapter layer over the EXISTING canonical project-creation authority.  It adds NO economic,
default or persistence authority:

* ``GET  /model-react/new-project/options``  — the technology cards, canonical country catalogue and the
  reference timeline defaults, all read from the canonical registries/factories, plus a per-wizard
  ``request_id`` and a signed CSRF token bound to the session and that request id.
* ``GET  /model-react/new-project/preview``  — server-side validation and the *effective* assumptions the
  canonical seed service will persist (scaled CAPEX / OPEX), without writing anything.
* ``POST /model-react/new-project/create``   — creates exactly one user-owned working copy through
  ``create_reference_seeded_project`` (the same service the Legacy ``/projects/create`` uses for the
  Solar/Wind/Data Center/EV Charging references).  CSRF, session, preview acknowledgement and a durable
  request-identity guard are enforced before the writer is called.
* ``GET  /model-react/new-project/status``   — read-only reconciliation of a request id (did that request
  create a project?).

Hard rules: no financial default is hardcoded here (every number comes from the canonical reference
factory); Storage/BESS and any other release-closed vertical is refused; nothing here runs the engine; an
ambiguous Create is never retried by this module — the client reconciles by request id and otherwise
fails closed to "refresh the Library".

Idempotency (documented limit): the request id is stamped into the new project's ``replay_metadata`` with
the canonical ``update_project_record`` AFTER the project exists.  A replay of the same request id then
returns the existing project instead of creating another.  A crash in the window between the two writes
leaves a project without a stamp; that outcome is reported to the client as *unknown* (never as "not
created").  A fully atomic idempotent create needs a change to the protected creation writers and is an
owner-gated item (docs/react_migration/rc_m_integrated/08_OPEN_OWNER_AUTHORIZATIONS.md).

Feature flag: the same ``FINCO_MODEL_REACT_V1`` gate as the rest of the React workspace.
"""
from __future__ import annotations

import math
import re
import threading
from typing import Any, Optional

from fastapi import APIRouter, Request
from fastapi.responses import JSONResponse
from pydantic import BaseModel, ConfigDict, ValidationError

from app.auth import check_demo_rate_limit, resolve_request_session, validate_csrf_token
from app.v2.react_poc_router import react_poc_enabled
from app.workbook.financing_csrf import extract_bound_token, issue_token

router = APIRouter()

PURPOSE = "react-new-project-v1"
REQUEST_STAMP_KEY = "react_new_project"
# Adapter-level sanity bounds.  The lower bound is the canonical registry minimum for
# ``technical.capacity_mw``; the upper bound only rejects absurd input and is NOT an economic limit.
CAPACITY_MIN_MW = 0.1
CAPACITY_MAX_MW = 10_000.0
NAME_MAX_LENGTH = 80
_REQUEST_ID = re.compile(r"^[0-9a-f]{32}$")

# technology key -> (canonical reference template source, default country code for that reference)
_TECHNOLOGIES: dict[str, tuple[str, str]] = {
    "solar": ("generic_solar_reference", "XA"),
    "wind": ("generic_wind_reference", "XB"),
    "data_center": ("generic_data_center_reference", "XD"),
    "ev_charging": ("generic_ev_charging_reference", "XE"),
}
_CAPACITY_LABEL = {
    "solar": "Installed capacity (MW)",
    "wind": "Installed capacity (MW)",
    "data_center": "IT capacity (MW)",
    "ev_charging": "Charging capacity (MW)",
}

_locks_guard = threading.Lock()
_request_locks: dict[str, threading.Lock] = {}


def _json(payload: dict[str, Any], status: int = 200) -> JSONResponse:
    return JSONResponse(payload, status_code=status, headers={"Cache-Control": "no-store"})


def _lock_for(request_id: str) -> threading.Lock:
    with _locks_guard:
        if len(_request_locks) > 512:   # bounded: drop idle locks only
            for key in [k for k, v in _request_locks.items() if not v.locked()]:
                _request_locks.pop(key, None)
        return _request_locks.setdefault(request_id, threading.Lock())


class CreateBody(BaseModel):
    model_config = ConfigDict(extra="forbid")

    request_id: str
    csrf_token: str
    name: str
    technology: str
    country: str
    capacity_mw: float
    acknowledge_preview: bool = False


# ───────────────────────────── canonical readers ─────────────────────────────

def _capability(technology: str) -> dict[str, Any]:
    """Registry capability for a technology key; tier is the Financial Owner's release posture."""
    from app.product_capability import PRODUCT_CAPABILITIES, as_api_dict
    from app.v2.react_workspace_router import _PILOT_TIER

    for cap in PRODUCT_CAPABILITIES:
        if cap.product_area == "model" and cap.key == technology:
            data = as_api_dict(cap)
            return {"key": cap.key, "public_name": cap.public_name, "runnable": bool(cap.runnable),
                    "pilot_tier": _PILOT_TIER.get(cap.key, "UNCLASSIFIED"),
                    "limitations": list(data["limitations"]), "status_note": data["status_note"]}
    return {"key": technology, "public_name": technology, "runnable": False, "pilot_tier": "UNCLASSIFIED",
            "limitations": [], "status_note": ""}


def _reference(technology: str):
    from app.services.reference_seed_service import _reference_inputs

    return _reference_inputs(_TECHNOLOGIES[technology][0])


def _timeline(pi) -> dict[str, Any]:
    info = pi.info
    return {"financial_close": info.financial_close.isoformat(), "construction_months": int(info.construction_months),
            "cod_date": info.cod_date.isoformat(), "horizon_years": int(info.horizon_years)}


def _creatable(technology: str) -> tuple[bool, str]:
    """(creatable, reason).  Only canonical cloneable references with a runnable registry entry qualify."""
    from app.services.reference_seed_service import CLONEABLE_SEED_TEMPLATE_SOURCES

    if technology not in _TECHNOLOGIES:
        return False, "This technology is not released for working copies."
    if _TECHNOLOGIES[technology][0] not in CLONEABLE_SEED_TEMPLATE_SOURCES:
        return False, "This technology has no cloneable canonical reference."
    if not _capability(technology)["runnable"]:
        return False, "This technology is not released for Runs."
    return True, ""


def _fmt(value: float) -> str:
    return f"{value:,.0f}"


def _validate(params: dict[str, Any]) -> tuple[Optional[dict[str, Any]], list[dict[str, str]]]:
    """Field-level validation shared by preview and create.  Returns (normalised, errors)."""
    from app.workbook.country_options import COUNTRY_CODES

    errors: list[dict[str, str]] = []
    name = " ".join(str(params.get("name") or "").split())
    technology = str(params.get("technology") or "")
    country = str(params.get("country") or "").strip().upper()
    capacity = params.get("capacity_mw")
    if not name:
        errors.append({"field": "name", "message": "Enter a project name."})
    elif len(name) > NAME_MAX_LENGTH:
        errors.append({"field": "name", "message": f"Use at most {NAME_MAX_LENGTH} characters."})
    elif any(ord(c) < 32 for c in name):
        errors.append({"field": "name", "message": "The project name contains control characters."})
    if technology not in _TECHNOLOGIES:
        errors.append({"field": "technology", "message": "Select a technology released for working copies."})
    else:
        ok, reason = _creatable(technology)
        if not ok:
            errors.append({"field": "technology", "message": reason})
    if country not in COUNTRY_CODES:
        errors.append({"field": "country", "message": "Select a country or market from the list."})
    try:
        capacity_f = float(capacity)
    except (TypeError, ValueError):
        capacity_f = float("nan")
    if not math.isfinite(capacity_f):
        errors.append({"field": "capacity_mw", "message": "Enter the capacity as a number of MW."})
    elif capacity_f < CAPACITY_MIN_MW or capacity_f > CAPACITY_MAX_MW:
        errors.append({"field": "capacity_mw",
                       "message": f"Capacity must be between {CAPACITY_MIN_MW:g} and {CAPACITY_MAX_MW:,.0f} MW."})
    if errors:
        return None, errors
    return {"name": name, "technology": technology, "country": country, "capacity_mw": capacity_f}, []


def _effective(normalised: dict[str, Any]) -> dict[str, Any]:
    """What the canonical seed service will persist for these inputs (read-only; mirrors its scaling)."""
    technology = normalised["technology"]
    pi = _reference(technology)
    reference_capacity = float(pi.technical.capacity_mw)
    ratio = float(normalised["capacity_mw"]) / reference_capacity
    capex = float(pi.capex.total_capex or 0) * ratio
    opex = sum(float(item.y1_amount_keur) for item in pi.opex) * ratio
    from app.workbook.country_options import COUNTRY_CODE_TO_LABEL, GENERIC_TAX_TEMPLATE_LABEL

    return {
        "capacity_mw": normalised["capacity_mw"], "capacity_label": _CAPACITY_LABEL[technology],
        "reference_capacity_mw": reference_capacity, "scale_ratio": ratio,
        "total_capex_keur": capex, "total_capex_display": _fmt(capex),
        "opex_y1_keur": opex, "opex_y1_display": _fmt(opex),
        "country": normalised["country"], "country_label": COUNTRY_CODE_TO_LABEL.get(normalised["country"], normalised["country"]),
        "tax_template": GENERIC_TAX_TEMPLATE_LABEL,
        "timeline": _timeline(pi),
    }


# ───────────────────────────── routes ─────────────────────────────

def _gate(request: Request):
    if not react_poc_enabled():
        return None, _json({"ok": False, "code": "REACT_POC_DISABLED"}, 404)
    user = resolve_request_session(request)
    if user is None:
        return None, _json({"ok": False, "code": "AUTH_REQUIRED"}, 401)
    return user, None


@router.get("/model-react/new-project/options")
async def react_new_project_options(request: Request):
    user, refused = _gate(request)
    if refused is not None:
        return refused
    import uuid

    from app.workbook.country_options import COUNTRY_OPTIONS

    technologies = []
    for key in ("solar", "wind", "data_center", "ev_charging", "storage"):
        cap = _capability(key)
        creatable, reason = _creatable(key)
        entry: dict[str, Any] = {**cap, "creatable": creatable, "reason": reason,
                                 "preview_acknowledgement_required": creatable and cap["pilot_tier"] != "PILOT_CANDIDATE"}
        if creatable:
            pi = _reference(key)
            entry.update({"template_source": _TECHNOLOGIES[key][0], "default_country": _TECHNOLOGIES[key][1],
                          "capacity_label": _CAPACITY_LABEL[key],
                          "default_capacity_mw": float(pi.technical.capacity_mw), "timeline": _timeline(pi)})
        technologies.append(entry)
    request_id = uuid.uuid4().hex
    return _json({
        "ok": True,
        "technologies": technologies,
        "countries": [{"code": code, "label": label} for code, label in COUNTRY_OPTIONS],
        "bounds": {"capacity_min_mw": CAPACITY_MIN_MW, "capacity_max_mw": CAPACITY_MAX_MW, "name_max_length": NAME_MAX_LENGTH},
        "request_id": request_id,
        "csrf_token": issue_token(request, request_id, purpose=PURPOSE),
    })


@router.get("/model-react/new-project/preview")
async def react_new_project_preview(request: Request, name: str = "", technology: str = "", country: str = "",
                                    capacity_mw: str = ""):
    user, refused = _gate(request)
    if refused is not None:
        return refused
    normalised, errors = _validate({"name": name, "technology": technology, "country": country, "capacity_mw": capacity_mw})
    if errors:
        return _json({"ok": False, "code": "VALIDATION_FAILED", "errors": errors}, 422)
    cap = _capability(normalised["technology"])
    return _json({"ok": True, "normalised": normalised, "effective": _effective(normalised),
                  "vertical": cap, "writes_nothing": True})


def _existing_for_request(user_id: str, request_id: str):
    from app.persistence.projects_repository import list_project_records

    for record in list_project_records(user_id=user_id, include_archived=True):
        stamp = (getattr(record, "replay_metadata", None) or {}).get(REQUEST_STAMP_KEY)
        if isinstance(stamp, dict) and stamp.get("request_id") == request_id:
            return record
    return None


def _project_payload(record) -> dict[str, Any]:
    return {"code": record.project_code, "project_id": record.project_id,
            "name": getattr(record, "project_name", None) or record.project_code,
            "template_source": getattr(record, "template_source", None) or "",
            "workspace_url": f"/v2/model-react/{record.project_code}", "freshness": "NOT_RUN"}


@router.get("/model-react/new-project/status")
async def react_new_project_status(request: Request, request_id: str = ""):
    user, refused = _gate(request)
    if refused is not None:
        return refused
    if not _REQUEST_ID.match(request_id or ""):
        return _json({"ok": False, "code": "REQUEST_ID_INVALID"}, 422)
    record = _existing_for_request(user.user_id, request_id)
    if record is None:
        # Absence is NOT proof that no project will appear (an in-flight request may still commit).
        return _json({"ok": True, "created": False, "conclusive": False})
    return _json({"ok": True, "created": True, "conclusive": True, "project": _project_payload(record)})


@router.post("/model-react/new-project/create")
async def react_new_project_create(request: Request):
    user, refused = _gate(request)
    if refused is not None:
        return refused
    try:
        raw = await request.json()
    except Exception:  # noqa: BLE001 - malformed body is a client error, nothing was written
        return _json({"ok": False, "code": "BODY_INVALID"}, 400)
    try:
        body = CreateBody.model_validate(raw)
    except ValidationError:
        return _json({"ok": False, "code": "BODY_INVALID"}, 400)

    if not _REQUEST_ID.match(body.request_id) or not validate_csrf_token(
            extract_bound_token(request, body.request_id, body.csrf_token, purpose=PURPOSE)):
        return _json({"ok": False, "code": "CSRF_INVALID"}, 403)

    if getattr(user, "is_demo", False):
        allowed, retry_after = check_demo_rate_limit(user.user_id, "project_create")
        if not allowed:
            return _json({"ok": False, "code": "RATE_LIMITED", "retry_after": retry_after}, 429)

    with _lock_for(body.request_id):
        replay = _existing_for_request(user.user_id, body.request_id)
        if replay is not None:
            return _json({"ok": True, "replayed": True, "project": _project_payload(replay)})

        normalised, errors = _validate(body.model_dump())
        if errors:
            return _json({"ok": False, "code": "VALIDATION_FAILED", "errors": errors}, 422)
        cap = _capability(normalised["technology"])
        if cap["pilot_tier"] != "PILOT_CANDIDATE" and not body.acknowledge_preview:
            return _json({"ok": False, "code": "PREVIEW_ACKNOWLEDGEMENT_REQUIRED",
                          "message": "This technology is a PREVIEW with narrower validation. Acknowledge the limitations to continue."}, 409)

        from app.services.reference_seed_service import create_reference_seeded_project

        try:
            record = create_reference_seeded_project(
                user_id=user.user_id, template_source=_TECHNOLOGIES[normalised["technology"]][0],
                requested_name=normalised["name"], capacity_mw=normalised["capacity_mw"],
                country_market=normalised["country"])
        except ValueError as exc:
            return _json({"ok": False, "code": "CREATE_REFUSED", "message": str(exc)}, 400)
        except Exception:  # noqa: BLE001 - partial writes are possible: never claim "not created"
            return _json({"ok": False, "code": "CREATE_OUTCOME_UNKNOWN",
                          "message": "Result unknown — refresh the Library before trying again."}, 500)

        stamped = True
        try:
            from app.persistence.projects_repository import update_project_record

            replay_metadata = dict(getattr(record, "replay_metadata", None) or {})
            replay_metadata[REQUEST_STAMP_KEY] = {"request_id": body.request_id, "adapter": PURPOSE}
            stamped = update_project_record(user_id=user.user_id, project_code=record.project_code,
                                            replay_metadata=replay_metadata) is not None
        except Exception:  # noqa: BLE001 - the project exists; only its idempotency stamp is missing
            stamped = False
        return _json({"ok": True, "replayed": False, "idempotency_recorded": stamped, "project": _project_payload(record)})
