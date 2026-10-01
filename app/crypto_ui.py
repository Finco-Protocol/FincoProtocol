"""FINCO Crypto — one coherent wallet / access / utility surface (UX V1).

A single FINCO-native page presenting, from AUTHORITATIVE states only:

    Wallet               DISCONNECTED / UNVERIFIED / VERIFIED
    $FINCO access state  per-resource PUBLIC / NOT_CONFIGURED /
                         NOT_ACTIVATED / LOCKED / UNAVAILABLE / UNLOCKED
    Yield Watchlist      count + canonical saved opportunities
    Alerts state         integration-pending consumption boundary
    Execution state      Yield execution flag (OFF by default)

It consumes the existing authorities (wallet/session store, entitlement
evaluator via the same wiring as the Yield surface, watchlist store,
alerts gateway boundary) and NEVER invents access from frontend state.
Read-only page plus CSRF-protected alerts mutation routes for the gateway
boundary.  Product truth today: no production token deployment, gating
not active by default, watchlist available, in-app alert engine pending,
Yield execution OFF.
"""
from __future__ import annotations

from fastapi import APIRouter, Request
from fastapi.responses import HTMLResponse, JSONResponse
from fastapi.templating import Jinja2Templates

router = APIRouter()

_REPO_ROOT = None  # resolved lazily so imports stay cheap at module load


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
    """Same canonical wiring as the Yield surface: wallet → all decisions."""
    from app.protocol.entitlement_evaluator import evaluate_all_resources
    return await evaluate_all_resources(wallet)


def _execution_state() -> str:
    from finco_yield.flags import execution_enabled
    return "ON" if execution_enabled() else "OFF"


@router.get("/crypto", response_class=HTMLResponse)
async def crypto_overview(request: Request):
    """The FINCO Crypto surface: wallet, $FINCO access, watchlist, alerts
    state, premium capability state, execution state."""
    from app.auth import generate_csrf_token
    from app.crypto_access import (
        build_crypto_access_snapshot, get_wallet_state,
    )
    from app.crypto_alerts import get_alerts_gateway
    from finco_yield.watchlist import list_watchlist_items
    from app.protocol.entitlement_evaluator import wallet_context_for_session

    user = _request_user(request)
    user_id = user.user_id if user else None

    wallet_state, _ = get_wallet_state(user_id)
    decisions = await _resource_decisions(
        wallet_context_for_session(user)) if user else {}
    access = build_crypto_access_snapshot(wallet_state,
                                          resource_decisions=decisions)
    watchlist = list_watchlist_items(user_id) if user_id else []
    alerts = get_alerts_gateway().snapshot(user_id or "").public_dict()
    alerts_state = "AVAILABLE" if alerts["available"] else "NOT_ACTIVATED"

    return _templates().TemplateResponse(
        request=request,
        name="crypto/overview.html",
        context={
            "wallet_state": wallet_state,
            "access": access,
            "watchlist": watchlist,
            "watchlist_count": len(watchlist),
            "alerts": alerts,
            "alerts_state": alerts_state,
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


@router.get("/crypto/alerts.json")
async def crypto_alerts_json(request: Request):
    """Alerts consumption boundary: unread count + list via the gateway."""
    from app.crypto_alerts import get_alerts_gateway
    user, failure = _require_user(request)
    if failure is not None:
        return failure
    return JSONResponse(
        content=get_alerts_gateway().snapshot(user.user_id).public_dict(),
        headers={"Cache-Control": "no-store"},
    )


@router.post("/crypto/alerts/{alert_id}/read")
async def crypto_alert_mark_read(request: Request, alert_id: str):
    """Mark ONE alert read via the gateway (CSRF-protected)."""
    from app.auth import validate_csrf_token
    from app.crypto_alerts import get_alerts_gateway
    user, failure = _require_user(request)
    if failure is not None:
        return failure
    content_type = request.headers.get("content-type") or ""
    form = await request.form() if "form" in content_type else None
    token = (form.get("csrf_token") if form is not None else None) \
        or request.headers.get("x-csrf-token")
    if not validate_csrf_token(token or ""):
        return JSONResponse(status_code=403, content={
            "state": "UNAVAILABLE", "reason": "CSRF_TOKEN_INVALID"})
    gateway = get_alerts_gateway()
    if not gateway.snapshot(user.user_id).available:
        return JSONResponse(status_code=501, content={
            "state": "UNAVAILABLE", "reason": "ALERTS_INTEGRATION_PENDING"})
    marked = gateway.mark_read(user.user_id, alert_id)
    return JSONResponse(content={"state": "MARKED" if marked else "NOT_PRESENT"})


@router.post("/crypto/alerts/read-all")
async def crypto_alert_mark_all_read(request: Request):
    """Mark ALL alerts read via the gateway (CSRF-protected)."""
    from app.auth import validate_csrf_token
    from app.crypto_alerts import get_alerts_gateway
    user, failure = _require_user(request)
    if failure is not None:
        return failure
    content_type = request.headers.get("content-type") or ""
    form = await request.form() if "form" in content_type else None
    token = (form.get("csrf_token") if form is not None else None) \
        or request.headers.get("x-csrf-token")
    if not validate_csrf_token(token or ""):
        return JSONResponse(status_code=403, content={
            "state": "UNAVAILABLE", "reason": "CSRF_TOKEN_INVALID"})
    gateway = get_alerts_gateway()
    if not gateway.snapshot(user.user_id).available:
        return JSONResponse(status_code=501, content={
            "state": "UNAVAILABLE", "reason": "ALERTS_INTEGRATION_PENDING"})
    marked = gateway.mark_all_read(user.user_id)
    return JSONResponse(content={"state": "MARKED", "count": marked})
