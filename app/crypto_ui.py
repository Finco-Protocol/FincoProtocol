"""FINCO Crypto — coherent wallet / access / Yield utility surface.

Authorities remain separated:
- wallet/resource access comes from the canonical entitlement evaluator;
- Yield Alerts economics/checkpoints/persistence remain in finco_yield;
- this module is routing/presentation only.

Alert route order is authentication -> canonical yield.alerts access -> CSRF
for mutations -> gateway/domain. GET routes are read-only. Explicit
``POST /crypto/alerts/refresh`` is the only V1 evaluation trigger.

Fail-soft contract (manual-QA runtime correction): the /crypto page composes
OPTIONAL authorities (wallet store, entitlement evaluator, Yield watchlist
and alerts).  Any single authority being unavailable must render a typed
DISCONNECTED / NOT_CONFIGURED / NOT_ACTIVATED / LOCKED / UNAVAILABLE / OFF
presentation state — never HTTP 500 and never a fabricated value
(missing/unavailable is never converted into zero).
"""
from __future__ import annotations

import sqlite3

from fastapi import APIRouter, Request
from fastapi.responses import HTMLResponse, JSONResponse, RedirectResponse
from fastapi.templating import Jinja2Templates

router = APIRouter()
_REPO_ROOT = None

_FORM_CONTENT_TYPES = frozenset({
    "application/x-www-form-urlencoded",
    "multipart/form-data",
})

_ALERTS_NOTICE_MESSAGES = {
    "YIELD_HISTORY_UNAVAILABLE": "Yield history is currently unavailable. Existing alerts remain readable.",
    "YIELD_REGISTRY_UNAVAILABLE": "Yield registry evidence is currently unavailable. No alert evaluation was applied.",
    "ALERT_EVALUATION_UNAVAILABLE": "Alert evaluation is currently unavailable. Please retry after the evidence service recovers.",
}


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


def _fail_soft(resource_description: str, exc: Exception) -> None:
    """Single audit point for optional-authority degradation on /crypto.

    Logs the exact exception (type + message only — never secrets or user
    input) so staging diagnostics can identify the unavailable authority.
    """
    import logging
    logging.getLogger("finco.crypto").warning(
        "CRYPTO_AUTHORITY_UNAVAILABLE authority=%s error=%s:%s",
        resource_description, type(exc).__name__, exc,
    )


def _wallet_state_fail_soft(user_id) -> tuple[str, dict | None]:
    """Wallet presentation state; a wallet-store outage is UNAVAILABLE, not a 500."""
    from app.crypto_access import get_wallet_state
    try:
        return get_wallet_state(user_id)
    except (sqlite3.Error, OSError, ValueError) as exc:
        _fail_soft("wallet_store", exc)
        return "UNAVAILABLE", None


async def _decisions_fail_soft(wallet) -> dict:
    """Entitlement decisions for a resolved wallet context.

    No broad catch: canonical evaluation already fails closed internally for
    expected provider/RPC failures; unexpected programming errors propagate.
    """
    return dict(await _resource_decisions(wallet))


def _watchlist_fail_soft(user_id) -> dict:
    """Watchlist presentation state — unavailable is NEVER zero.

    Contract (manual-QA correction C):
      - successful query, no saved items: AVAILABLE, count 0, items []
      - anonymous session (no user store query, provably nothing saved):
        AVAILABLE, count 0, items []
      - store/query outage: UNAVAILABLE, count None, items [] — the UI
        renders "—", never a fabricated factual zero.
    """
    if not user_id:
        return {"state": "AVAILABLE", "count": 0, "items": []}
    from finco_yield.watchlist import list_watchlist_items
    try:
        items = list_watchlist_items(user_id)
    except (sqlite3.Error, OSError, ValueError) as exc:
        _fail_soft("yield_watchlist", exc)
        return {"state": "UNAVAILABLE", "count": None, "items": []}
    return {"state": "AVAILABLE", "count": len(items), "items": items}


def _alert_automation_configured() -> bool:
    from finco_yield.flags import alert_automation_enabled
    return alert_automation_enabled()


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
    """Canonical yield.alerts access decision -> typed read-only snapshot.

    Fail-soft: an access-resolution outage renders a typed UNAVAILABLE
    snapshot; it never raises into a 500 and never fabricates counts.
    """
    from finco_yield.access import denial_payload, resolve_yield_access, YieldResource

    try:
        if user is None:
            from app.crypto_alerts import auth_required_snapshot
            snapshot = auth_required_snapshot().public_dict()
            snapshot.update({"state": "LOCKED", "access_state": None,
                             "can_refresh": False})
            return snapshot

        decision = await resolve_yield_access(request, YieldResource.ALERTS)
    except Exception as exc:  # noqa: BLE001 — optional authority, fail soft
        _fail_soft("yield_alerts_access", exc)
        return {
            "available": False,
            "state": "UNAVAILABLE",
            "access_state": None,
            "reason": "ALERT_EVALUATION_UNAVAILABLE",
            "unread_count": None,
            "items": [],
            "can_refresh": False,
        }

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
    from app.crypto_access import build_crypto_access_snapshot
    from app.protocol.entitlement_evaluator import wallet_context_for_session

    user = _request_user(request)
    user_id = user.user_id if user else None
    wallet_state, _ = _wallet_state_fail_soft(user_id)
    try:
        wallet = wallet_context_for_session(user)
    except (sqlite3.Error, OSError, ValueError) as exc:
        _fail_soft("wallet_store", exc)
        wallet = None
        wallet_context_unavailable = True
    else:
        wallet_context_unavailable = False
    decisions = await _decisions_fail_soft(wallet)
    access = build_crypto_access_snapshot(wallet_state, resource_decisions=decisions)
    if wallet_context_unavailable:
        access["entitlement_unavailable"] = "WALLET_STORE_UNAVAILABLE"
    watchlist_state = _watchlist_fail_soft(user_id)
    watchlist = watchlist_state["items"]
    watchlist_count = watchlist_state["count"]
    alerts = await _alerts_presentation(request, user)
    notice_reason = request.query_params.get("alerts_notice")
    alerts_notice = _ALERTS_NOTICE_MESSAGES.get(notice_reason)

    return _templates().TemplateResponse(
        request=request,
        name="crypto/overview.html",
        context={
            "wallet_state": wallet_state,
            "access": access,
            "watchlist": watchlist,
            "watchlist_count": watchlist_count,
            "watchlist_state": watchlist_state["state"],
            "alerts": alerts,
            "alerts_notice_reason": notice_reason if alerts_notice else None,
            "alerts_notice": alerts_notice,
            # Configuration only: it does not prove a scheduler is running.
            "alerts_automation_configured": _alert_automation_configured(),
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


def _is_form_request(request: Request) -> bool:
    media_type = (request.headers.get("content-type") or "").split(";", 1)[0].strip().lower()
    return media_type in _FORM_CONTENT_TYPES


async def _mutation_form_and_csrf(request: Request):
    is_form = _is_form_request(request)
    form = await request.form() if is_form else None
    return form, is_form, _csrf_failure(request, form)


def _crypto_redirect(*, notice_reason: str | None = None) -> RedirectResponse:
    if notice_reason in _ALERTS_NOTICE_MESSAGES:
        return RedirectResponse(
            url=f"/crypto?alerts_notice={notice_reason}", status_code=303)
    return RedirectResponse(url="/crypto", status_code=303)


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
    _form, is_form, csrf_failure = await _mutation_form_and_csrf(request)
    if csrf_failure is not None:
        return csrf_failure

    gateway = get_alerts_gateway()
    refresh = getattr(gateway, "refresh", None)
    if refresh is None:
        return JSONResponse(status_code=501, content={
            "state": "UNAVAILABLE", "reason": "ALERTS_REFRESH_NOT_AVAILABLE"})
    result = refresh(user.user_id)
    if result.available and is_form:
        return _crypto_redirect()
    if not result.available and is_form and result.reason in _ALERTS_NOTICE_MESSAGES:
        return _crypto_redirect(notice_reason=result.reason)
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
    _form, is_form, csrf_failure = await _mutation_form_and_csrf(request)
    if csrf_failure is not None:
        return csrf_failure
    gateway = get_alerts_gateway()
    snapshot = gateway.snapshot(user.user_id)
    if not snapshot.available:
        return _alerts_backend_failure(snapshot)
    marked = gateway.mark_read(user.user_id, alert_id)
    if is_form:
        return _crypto_redirect()
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
    _form, is_form, csrf_failure = await _mutation_form_and_csrf(request)
    if csrf_failure is not None:
        return csrf_failure
    gateway = get_alerts_gateway()
    snapshot = gateway.snapshot(user.user_id)
    if not snapshot.available:
        return _alerts_backend_failure(snapshot)
    marked = gateway.mark_all_read(user.user_id)
    if is_form:
        return _crypto_redirect()
    return JSONResponse(content={"state": "MARKED", "count": marked})
