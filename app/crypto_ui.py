"""FINCO Crypto — coherent wallet / access / Yield utility surface.

Authorities remain separated:
- wallet/resource access comes from the canonical entitlement evaluator;
- Yield Alerts economics/checkpoints/persistence remain in finco_yield;
- this module is routing/presentation only.

Alert route order is authentication -> canonical yield.alerts access -> CSRF
for mutations -> gateway/domain. GET routes are read-only. Explicit
``POST /crypto/alerts/refresh`` is the only V1 evaluation trigger.
"""
from __future__ import annotations

from fastapi import APIRouter, Request
from fastapi.responses import HTMLResponse, JSONResponse
from fastapi.templating import Jinja2Templates

router = APIRouter()
_REPO_ROOT = None


def _templates() -> Jinja2Templates:
    from pathlib import Path
    global _REPO_ROOT
    if _REPO_ROOT is None:
        _REPO_ROOT = Path(__file__).resolve().parents[1]
    templates = Jinja2Templates(directory=str(_REPO_ROOT / "app" / "templates"))
    templates.env.autoescape = True
    return templates


def _request_user(request: Request):
    from app.auth import resolve_request_session
    return resolve_request_session(request)


async def _resource_decisions(wallet):
    from app.protocol.entitlement_evaluator import evaluate_all_resources
    return await evaluate_all_resources(wallet)


def _execution_state() -> str:
    from finco_yield.flags import execution_enabled
    return "ON" if execution_enabled() else "OFF"


_ALERTS_STATE_BY_DENIAL = {
    "WALLET_UNAVAILABLE": "LOCKED",
    "WALLET_UNVERIFIED": "LOCKED",
    "ENTITLEMENT_NOT_SATISFIED": "LOCKED",
    "TOKEN_DEPLOYMENT_NOT_CONFIGURED": "NOT_CONFIGURED",
    "ENTITLEMENT_AUTHORITY_UNAVAILABLE": "UNAVAILABLE",
}


async def _alerts_presentation(request: Request, user) -> dict:
    """Canonical yield.alerts access decision -> typed read-only snapshot."""
    from finco_yield.access import denial_payload, resolve_yield_access, YieldResource

    if user is None:
        from app.crypto_alerts import auth_required_snapshot
        snapshot = auth_required_snapshot().public_dict()
        snapshot.update({"state": "LOCKED", "access_state": None,
                         "can_refresh": False})
        return snapshot

    decision = await resolve_yield_access(request, YieldResource.ALERTS)
    if decision.gate_active and not decision.access_allowed:
        denial = denial_payload(decision)
        return {
            "available": False,
            "state": _ALERTS_STATE_BY_DENIAL.get(decision.state.value, "UNAVAILABLE"),
            "access_state": decision.state.value,
            "reason": denial["reason"],
            "unread_count": None,
            "items": [],
            "can_refresh": False,
        }

    # Gating inactive or canonical allow: service availability is independent
    # from token entitlement and the user-scoped backend may be read.
    from app.crypto_alerts import get_alerts_gateway
    snapshot = get_alerts_gateway().snapshot(user.user_id).public_dict()
    snapshot["state"] = "AVAILABLE" if snapshot["available"] else "UNAVAILABLE"
    snapshot["access_state"] = decision.state.value
    snapshot["can_refresh"] = bool(snapshot["available"])
    return snapshot


@router.get("/crypto", response_class=HTMLResponse)
async def crypto_overview(request: Request):
    from app.auth import generate_csrf_token
    from app.crypto_access import build_crypto_access_snapshot, get_wallet_state
    from finco_yield.watchlist import list_watchlist_items
    from app.protocol.entitlement_evaluator import wallet_context_for_session

    user = _request_user(request)
    user_id = user.user_id if user else None
    wallet_state, _ = get_wallet_state(user_id)
    wallet = wallet_context_for_session(user)
    decisions = await _resource_decisions(wallet)
    access = build_crypto_access_snapshot(wallet_state, resource_decisions=decisions)
    watchlist = list_watchlist_items(user_id) if user_id else []
    alerts = await _alerts_presentation(request, user)

    return _templates().TemplateResponse(
        request=request,
        name="crypto/overview.html",
        context={
            "wallet_state": wallet_state,
            "access": access,
            "watchlist": watchlist,
            "watchlist_count": len(watchlist),
            "alerts": alerts,
            "execution_state": _execution_state(),
            "csrf_token": generate_csrf_token(),
            "user": user,
        },
    )


def _require_user(request: Request):
    user = _request_user(request)
    if not user:
        return None, JSONResponse(status_code=401, content={
            "state": "UNAVAILABLE", "reason": "AUTH_REQUIRED"})
    return user, None


def _csrf_failure(request: Request, form) -> JSONResponse | None:
    from app.auth import validate_csrf_token
    token = form.get("csrf_token") if form is not None else None
    if not token:
        token = request.headers.get("x-csrf-token")
    if not validate_csrf_token(token or ""):
        return JSONResponse(status_code=403, content={
            "state": "UNAVAILABLE", "reason": "CSRF_TOKEN_INVALID"})
    return None


async def _mutation_form_and_csrf(request: Request):
    content_type = request.headers.get("content-type") or ""
    form = await request.form() if "form" in content_type else None
    return form, _csrf_failure(request, form)


def _alerts_backend_failure(snapshot) -> JSONResponse:
    """Preserve C's typed placeholder while real outages use 503."""
    from app.crypto_alerts import ALERTS_INTEGRATION_PENDING
    pending = snapshot.reason == ALERTS_INTEGRATION_PENDING
    return JSONResponse(
        status_code=501 if pending else 503,
        content={
            "state": "UNAVAILABLE",
            "reason": snapshot.reason or "ALERTS_BACKEND_UNAVAILABLE",
        },
    )


@router.get("/crypto/alerts.json")
async def crypto_alerts_json(request: Request):
    """Read-only list: auth -> access -> gateway. No evaluation side effect."""
    from finco_yield.access import denial_payload, resolve_yield_access, YieldResource
    from app.crypto_alerts import get_alerts_gateway

    user, failure = _require_user(request)
    if failure is not None:
        return failure
    decision = await resolve_yield_access(request, YieldResource.ALERTS)
    if decision.gate_active and not decision.access_allowed:
        return JSONResponse(status_code=403, content=denial_payload(decision))
    return JSONResponse(
        content=get_alerts_gateway().snapshot(user.user_id).public_dict(),
        headers={"Cache-Control": "no-store"},
    )


@router.post("/crypto/alerts/refresh")
async def crypto_alerts_refresh(request: Request):
    """Manual V1 trigger: auth -> access -> CSRF -> canonical evaluator."""
    from finco_yield.access import denial_payload, resolve_yield_access, YieldResource
    from app.crypto_alerts import get_alerts_gateway

    user, failure = _require_user(request)
    if failure is not None:
        return failure
    decision = await resolve_yield_access(request, YieldResource.ALERTS)
    if decision.gate_active and not decision.access_allowed:
        return JSONResponse(status_code=403, content=denial_payload(decision))
    _form, csrf_failure = await _mutation_form_and_csrf(request)
    if csrf_failure is not None:
        return csrf_failure

    gateway = get_alerts_gateway()
    refresh = getattr(gateway, "refresh", None)
    if refresh is None:
        return JSONResponse(status_code=501, content={
            "state": "UNAVAILABLE", "reason": "ALERTS_REFRESH_NOT_AVAILABLE"})
    result = refresh(user.user_id)
    return JSONResponse(
        status_code=200 if result.available else 503,
        content=result.public_dict(),
        headers={"Cache-Control": "no-store"},
    )


@router.post("/crypto/alerts/{alert_id}/read")
async def crypto_alert_mark_read(request: Request, alert_id: str):
    """Mark one read: auth -> access -> CSRF -> gateway."""
    from finco_yield.access import denial_payload, resolve_yield_access, YieldResource
    from app.crypto_alerts import get_alerts_gateway

    user, failure = _require_user(request)
    if failure is not None:
        return failure
    decision = await resolve_yield_access(request, YieldResource.ALERTS)
    if decision.gate_active and not decision.access_allowed:
        return JSONResponse(status_code=403, content=denial_payload(decision))
    _form, csrf_failure = await _mutation_form_and_csrf(request)
    if csrf_failure is not None:
        return csrf_failure
    gateway = get_alerts_gateway()
    snapshot = gateway.snapshot(user.user_id)
    if not snapshot.available:
        return _alerts_backend_failure(snapshot)
    marked = gateway.mark_read(user.user_id, alert_id)
    return JSONResponse(content={"state": "MARKED" if marked else "NOT_PRESENT"})


@router.post("/crypto/alerts/read-all")
async def crypto_alert_mark_all_read(request: Request):
    """Mark all read: auth -> access -> CSRF -> gateway."""
    from finco_yield.access import denial_payload, resolve_yield_access, YieldResource
    from app.crypto_alerts import get_alerts_gateway

    user, failure = _require_user(request)
    if failure is not None:
        return failure
    decision = await resolve_yield_access(request, YieldResource.ALERTS)
    if decision.gate_active and not decision.access_allowed:
        return JSONResponse(status_code=403, content=denial_payload(decision))
    _form, csrf_failure = await _mutation_form_and_csrf(request)
    if csrf_failure is not None:
        return csrf_failure
    gateway = get_alerts_gateway()
    snapshot = gateway.snapshot(user.user_id)
    if not snapshot.available:
        return _alerts_backend_failure(snapshot)
    marked = gateway.mark_all_read(user.user_id)
    return JSONResponse(content={"state": "MARKED", "count": marked})
