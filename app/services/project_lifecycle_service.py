"""HTTP lifecycle adapter; existing signed CSRF primitives remain unchanged."""
from __future__ import annotations

import json
from fastapi.responses import JSONResponse

from app.auth import resolve_request_session, validate_csrf_token
from app.persistence.project_lifecycle_repository import LifecycleError, eligible, status, transition
from app.workbook.financing_csrf import extract_bound_token, issue_token


def capability(request, row):
    import hashlib
    complete = bool(row["_wf03_complete"]) if "_wf03_complete" in row.keys() else False
    return {"archived": bool(row["archived"]), "lifecycle_version": row["lifecycle_version"],
            "scope": hashlib.sha256((row["user_id"]+":"+row["project_id"]).encode()).hexdigest(),
            "archive_origin": row["lifecycle_archive_origin"],
            "can_archive": complete and not bool(row["archived"]) and eligible(row),
            "can_restore": complete and bool(row["archived"]) and eligible(row, restoring=True),
            "tokens": {action.lower(): issue_token(request, row["project_code"], purpose="wf03-lifecycle:"+action)
                       for action in ("ARCHIVE", "UNARCHIVE")}}


def project_capability(request, owner, project_id):
    from app.persistence.db import get_cursor
    with get_cursor() as cur:
        row = cur.execute("""SELECT p.*, EXISTS(SELECT 1 FROM workspace_states w
            WHERE w.user_id=p.user_id AND w.project_id=p.project_id) AS _wf03_complete
            FROM projects p WHERE p.user_id=? AND p.project_id=?""", (owner, project_id)).fetchone()
        return capability(request, row) if row else None


def response(payload, code=200):
    return JSONResponse(payload, status_code=code, headers={"Cache-Control": "no-store"})


async def handle_transition(request, code, action):
    user = resolve_request_session(request)
    if user is None:
        return response({"ok": False, "code": "AUTH_REQUIRED"}, 401)
    from app.persistence.projects_repository import get_project_by_code
    if get_project_by_code(user.user_id, code) is None:
        return response({"ok": False, "code": "PROJECT_NOT_FOUND"}, 404)
    origin = request.headers.get("origin")
    if (origin and origin.rstrip("/") != str(request.base_url).rstrip("/")) or request.headers.get("sec-fetch-site") == "cross-site":
        return response({"ok": False, "code": "CSRF_INVALID"}, 403)
    supplied = request.headers.get("x-csrf-token", "")
    if not validate_csrf_token(extract_bound_token(request, code, supplied, purpose="wf03-lifecycle:"+action)):
        return response({"ok": False, "code": "CSRF_INVALID"}, 403)
    try:
        if request.headers.get("content-type", "").split(";")[0].strip() != "application/json":
            raise LifecycleError("INVALID_LIFECYCLE_BODY", 422)
        raw = b""
        async for chunk in request.stream():
            raw += chunk
            if len(raw) > 4096:
                raise LifecycleError("LIFECYCLE_BODY_TOO_LARGE", 422)
        data = json.loads(raw)
        return response(transition(user.user_id, code, action, data))
    except (json.JSONDecodeError, UnicodeDecodeError):
        return response({"ok": False, "code": "INVALID_LIFECYCLE_BODY"}, 422)
    except LifecycleError as exc:
        return response({"ok": False, "code": exc.code}, exc.status)


def handle_status(request, code, request_id):
    user = resolve_request_session(request)
    if user is None:
        return response({"ok": False, "code": "AUTH_REQUIRED"}, 401)
    try:
        return response(status(user.user_id, code, request_id))
    except LifecycleError as exc:
        return response({"ok": False, "code": exc.code}, exc.status)
