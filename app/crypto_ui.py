"""FINCO Crypto — one coherent wallet / access / utility surface (UX V1).

A single FINCO-native page presenting, from AUTHORITATIVE states only:

    Wallet               DISCONNECTED / UNVERIFIED / VERIFIED
    $FINCO access state  per-resource PUBLIC / NOT_CONFIGURED /
                         NOT_ACTIVATED / LOCKED / UNAVAILABLE / UNLOCKED
    Yield Watchlist      count + canonical saved opportunities
    Alerts state         canonical yield.alerts access + gateway boundary
    Execution state      Yield execution flag (OFF by default)

Authority rules:
  - resource decisions ALWAYS come from the canonical Agent A evaluator —
    anonymous visitors are evaluated through ``wallet_context_for_session``
    (the canonical no-wallet state), never special-cased into guessed states;
  - alerts routes enforce the canonical ``yield.alerts`` server access
    through the merged ``finco_yield.access`` adapter (no duplicate
    evaluator): order = authentication → canonical access decision → CSRF
    for mutations → gateway.  A DENY fails closed BEFORE any gateway/store
    access; INACTIVE and ALLOW proceed;
  - the alerts gateway is NEVER called with an empty/anonymous identity —
    anonymous users get a typed ``ALERTS_AUTH_REQUIRED`` presentation state
    (unknown unread ≠ zero).

Product truth today: no production token deployment, gating not active by
default, watchlist available, in-app alert engine integration pending,
Yield execution OFF.  Read-only page plus CSRF-protected alerts mutation
routes for the gateway boundary.
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


# ── Alerts presentation (canonical yield.alerts access → gateway) ────────────

_ALERTS_STATE_BY_DENIAL = {
    "WALLET_UNAVAILABLE": "LOCKED",
    "WALLET_UNVERIFIED": "LOCKED",
    "ENTITLEMENT_NOT_SATISFIED": "LOCKED",
    "TOKEN_DEPLOYMENT_NOT_CONFIGURED": "NOT_CONFIGURED",
    "ENTITLEMENT_AUTHORITY_UNAVAILABLE": "UNAVAILABLE",
}


async def _alerts_presentation(request: Request, user) -> dict:
    """Canonical yield.alerts access decision → typed alerts presentation.

    - anonymous            → LOCKED / ALERTS_AUTH_REQUIRED, gateway NEVER
                             called (no empty identity ever reaches a
                             persisted backend; unknown unread ≠ zero);
    - canonical DENY       → typed LOCKED/NOT_CONFIGURED/UNAVAILABLE from
                             the existing server denial mapping, gateway
                             NEVER called (fail closed before payload);
    - canonical INACTIVE   → gateway proceeds (gating is not active — this
                             is NOT token entitlement);
    - canonical ALLOW      → gateway proceeds.
    """
    from finco_yield.access import denial_payload, resolve_yield_access
    from finco_yield.access import YieldResource

    if user is None:
        from app.crypto_alerts import auth_required_snapshot
        snapshot = auth_required_snapshot().public_dict()
        snapshot.update({"state": "LOCKED", "access_state": None})
        return snapshot

    decision = await resolve_yield_access(request, YieldResource.ALERTS)
    if decision.gate_active and not decision.access_allowed:
        denial = denial_payload(decision)  # typed sanitized denial body
        return {
            "available": False,
            "state": _ALERTS_STATE_BY_DENIAL.get(
                decision.state.value, "UNAVAILABLE"),
            "access_state": decision.state.value,
            "reason": denial["reason"],
            "unread_count": None,
            "items": [],
        }

    # INACTIVE (gating off — not entitlement) or ALLOW → gateway proceeds.
    from app.crypto_alerts import get_alerts_gateway
    snapshot = get_alerts_gateway().snapshot(user.user_id).public_dict()
    snapshot["state"] = "AVAILABLE" if snapshot["available"] else "NOT_ACTIVATED"
    snapshot["access_state"] = decision.state.value
    return snapshot


@router.get("/crypto", response_class=HTMLResponse)
async def crypto_overview(request: Request):
    """The FINCO Crypto surface: wallet, $FINCO access, watchlist, alerts
    state, premium capability state, execution state."""
    from app.auth import generate_csrf_token
    from app.crypto_access import (
        build_crypto_access_snapshot, get_wallet_state,
    )
    from finco_yield.watchlist import list_watchlist_items
    from app.protocol.entitlement_evaluator import wallet_context_for_session

    user = _request_user(request)
    user_id = user.user_id if user else None

    # Canonical authority for EVERY visitor: the no-wallet context is itself
    # a canonical state (basic PUBLIC, holder resources INACTIVE by default).
    wallet_state, _ = get_wallet_state(user_id)
    wallet = wallet_context_for_session(user)
    decisions = await _resource_decisions(wallet)
    access = build_crypto_access_snapshot(wallet_state,
                                          resource_decisions=decisions)
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


@router.get("/crypto/alerts.json")
async def crypto_alerts_json(request: Request):
    """Alerts consumption boundary: unread count + list via the gateway.

    Order: authentication → canonical yield.alerts access decision →
    gateway.  A DENY fails closed (403 + typed denial body) BEFORE any
    gateway/store access.  GET carries no CSRF requirement.
    """
    from finco_yield.access import denial_payload, resolve_yield_access
    from finco_yield.access import YieldResource
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


@router.post("/crypto/alerts/{alert_id}/read")
async def crypto_alert_mark_read(request: Request, alert_id: str):
    """Mark ONE alert read: auth → canonical access → CSRF → gateway."""
    from finco_yield.access import denial_payload, resolve_yield_access
    from finco_yield.access import YieldResource
    from app.crypto_alerts import get_alerts_gateway
    user, failure = _require_user(request)
    if failure is not None:
        return failure
    decision = await resolve_yield_access(request, YieldResource.ALERTS)
    if decision.gate_active and not decision.access_allowed:
        return JSONResponse(status_code=403, content=denial_payload(decision))
    content_type = request.headers.get("content-type") or ""
    form = await request.form() if "form" in content_type else None
    csrf_failure = _csrf_failure(request, form)
    if csrf_failure is not None:
        return csrf_failure
    gateway = get_alerts_gateway()
    if not gateway.snapshot(user.user_id).available:
        return JSONResponse(status_code=501, content={
            "state": "UNAVAILABLE", "reason": "ALERTS_INTEGRATION_PENDING"})
    marked = gateway.mark_read(user.user_id, alert_id)
    return JSONResponse(content={"state": "MARKED" if marked else "NOT_PRESENT"})


@router.post("/crypto/alerts/read-all")
async def crypto_alert_mark_all_read(request: Request):
    """Mark ALL alerts read: auth → canonical access → CSRF → gateway."""
    from finco_yield.access import denial_payload, resolve_yield_access
    from finco_yield.access import YieldResource
    from app.crypto_alerts import get_alerts_gateway
    user, failure = _require_user(request)
    if failure is not None:
        return failure
    decision = await resolve_yield_access(request, YieldResource.ALERTS)
    if decision.gate_active and not decision.access_allowed:
        return JSONResponse(status_code=403, content=denial_payload(decision))
    content_type = request.headers.get("content-type") or ""
    form = await request.form() if "form" in content_type else None
    csrf_failure = _csrf_failure(request, form)
    if csrf_failure is not None:
        return csrf_failure
    gateway = get_alerts_gateway()
    if not gateway.snapshot(user.user_id).available:
        return JSONResponse(status_code=501, content={
            "state": "UNAVAILABLE", "reason": "ALERTS_INTEGRATION_PENDING"})
    marked = gateway.mark_all_read(user.user_id)
    return JSONResponse(content={"state": "MARKED", "count": marked})
