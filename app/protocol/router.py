"""FINCO Protocol Router — /protocol/* surfaces.

Routes:
  GET  /protocol/finco                     — HTML browser surface
  GET  /protocol/finco/access.json         — JSON access API (authenticated)
  POST /protocol/finco/wallet/challenge    — issue wallet challenge (authenticated)
  POST /protocol/finco/wallet/verify       — verify wallet signature (authenticated)

Security:
  - All routes require an authenticated session (non-demo preferred; demo allowed for HTML surface)
  - /protocol/finco and /protocol/finco/access.json return 401 (not demo-provisioned) because
    /protocol/finco is added to _DEMO_PROVISION_SKIP_PREFIXES in main_web.py
  - RPC URL is never included in any response
  - Internal user IDs and DB PKs are never included in any response
"""
from __future__ import annotations

import logging
import os
from datetime import datetime, timezone

from fastapi import APIRouter, Request
from fastapi.responses import HTMLResponse, JSONResponse
from fastapi.templating import Jinja2Templates

from app.protocol.utility_registry import UTILITY_REGISTRY

logger = logging.getLogger(__name__)
router = APIRouter()

_APP_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
_templates = Jinja2Templates(directory=os.path.join(_APP_DIR, "templates"))


def _unauthorized() -> JSONResponse:
    return JSONResponse(
        {"error": "Authentication required.", "code": "UNAUTHENTICATED"},
        status_code=401,
    )


def _get_request_domain(request: Request) -> str:
    host = request.headers.get("host", "fincoprotocol.com")
    return host.split(":")[0] or "fincoprotocol.com"


# ── HTML Surface ──────────────────────────────────────────────────────────────

@router.get("/protocol/finco", response_class=HTMLResponse)
async def finco_protocol_surface(request: Request):
    """$FINCO protocol access surface."""
    from app.auth import resolve_request_session
    user = resolve_request_session(request)
    if not user:
        from fastapi.responses import RedirectResponse
        return RedirectResponse(url="/login", status_code=302)

    from app.protocol.token_config import get_token_config
    from app.protocol.wallet_auth import get_verified_wallet
    from app.protocol.access_decision import get_all_access_decisions

    config = get_token_config()
    wallet_info = get_verified_wallet(user.user_id)
    wallet_address = wallet_info["wallet_address"] if wallet_info else None

    observation, decisions = await get_all_access_decisions(wallet_address, config)

    return _templates.TemplateResponse(
        request=request,
        name="protocol/finco.html",
        context={
            "user": user,
            "proto_active_page": "finco",
            "utilities": UTILITY_REGISTRY,
            "wallet_address": wallet_address,
            "wallet_verified_at": wallet_info["verified_at"] if wallet_info else None,
            "observation": observation,
            "decisions": decisions,
            "config_available": config is not None,
            "chain_id": config.chain_id if config else None,
            "token_address": config.token_address if config else None,
        },
    )


# ── JSON Access API ───────────────────────────────────────────────────────────

@router.get("/protocol/finco/access.json")
async def finco_access_json(request: Request):
    """Machine-readable access state for all FINCO utilities.

    Returns 401 if not authenticated.
    Never includes RPC URL, internal user IDs, or DB PKs.
    """
    from app.auth import resolve_request_session
    user = resolve_request_session(request)
    if not user:
        return _unauthorized()

    from app.protocol.token_config import get_token_config
    from app.protocol.wallet_auth import get_verified_wallet
    from app.protocol.access_decision import get_all_access_decisions

    config = get_token_config()
    wallet_info = get_verified_wallet(user.user_id)
    wallet_address = wallet_info["wallet_address"] if wallet_info else None

    observation, decisions = await get_all_access_decisions(wallet_address, config)

    # Build response — never include RPC URL
    utilities_payload = {}
    for uid, dec in decisions.items():
        utilities_payload[uid] = {
            "status": dec.status,
            "allowed": dec.allowed,
            "reason_code": dec.reason_code,
        }

    token_obs_payload: dict = {
        "chain_id": None,
        "token_address": None,
        "normalized_balance": None,
        "block_number": None,
        "observed_at": None,
        "status": "NOT_CONFIGURED",
    }
    if config is not None:
        token_obs_payload["chain_id"] = config.chain_id
        token_obs_payload["token_address"] = config.token_address
        if observation is not None:
            token_obs_payload["normalized_balance"] = (
                str(observation.normalized_balance)
                if observation.normalized_balance is not None
                else None
            )
            token_obs_payload["block_number"] = observation.block_number
            token_obs_payload["observed_at"] = (
                observation.observed_at.isoformat()
                if observation.observed_at
                else None
            )
            token_obs_payload["status"] = observation.status
        else:
            token_obs_payload["status"] = "NOT_CONFIGURED" if config is None else "OBSERVATION_UNAVAILABLE"

    return JSONResponse({
        "schema": "FINCO_PROTOCOL_ACCESS_V1",
        "wallet": {
            "address": wallet_address,
            "connected": wallet_address is not None,
            "verified_at": wallet_info["verified_at"] if wallet_info else None,
        },
        "token_observation": token_obs_payload,
        "utilities": utilities_payload,
    })


# ── Wallet Challenge ──────────────────────────────────────────────────────────

@router.post("/protocol/finco/wallet/challenge")
async def finco_wallet_challenge(request: Request):
    """Issue an EIP-191 ownership challenge for the submitted wallet address."""
    from app.auth import resolve_request_session
    user = resolve_request_session(request)
    if not user:
        return _unauthorized()

    try:
        body = await request.json()
    except Exception:
        return JSONResponse(
            {"error": "Invalid JSON body.", "code": "BAD_REQUEST"},
            status_code=400,
        )

    wallet_address = (body.get("wallet_address") or "").strip()
    if not wallet_address:
        return JSONResponse(
            {"error": "wallet_address is required.", "code": "MISSING_WALLET"},
            status_code=400,
        )

    # Validate hex address format
    from app.protocol.token_config import _validate_hex_address
    validated = _validate_hex_address(wallet_address)
    if validated is None:
        return JSONResponse(
            {"error": "Invalid wallet address format.", "code": "INVALID_ADDRESS"},
            status_code=400,
        )

    from app.protocol.token_config import get_token_config
    config = get_token_config()
    chain_id = config.chain_id if config else 1  # default chain_id for challenge

    from app.protocol.wallet_auth import issue_challenge
    challenge_info = issue_challenge(
        user_id=user.user_id,
        wallet_address=validated,
        chain_id=chain_id,
        domain=_get_request_domain(request),
    )

    return JSONResponse({
        "nonce": challenge_info["nonce"],
        "challenge_text": challenge_info["challenge_text"],
        "expires_at": challenge_info["expires_at"],
    })


# ── Wallet Verify ─────────────────────────────────────────────────────────────

@router.post("/protocol/finco/wallet/verify")
async def finco_wallet_verify(request: Request):
    """Verify an EIP-191 wallet signature and bind wallet to user."""
    from app.auth import resolve_request_session
    user = resolve_request_session(request)
    if not user:
        return _unauthorized()

    try:
        body = await request.json()
    except Exception:
        return JSONResponse(
            {"error": "Invalid JSON body.", "code": "BAD_REQUEST"},
            status_code=400,
        )

    wallet_address = (body.get("wallet_address") or "").strip()
    signature = (body.get("signature") or "").strip()
    nonce = (body.get("nonce") or "").strip()

    if not wallet_address or not signature or not nonce:
        return JSONResponse(
            {"error": "wallet_address, signature, and nonce are required.", "code": "MISSING_FIELDS"},
            status_code=400,
        )

    from app.protocol.wallet_auth import verify_challenge, WalletVerifyError
    try:
        verified_address = verify_challenge(
            user_id=user.user_id,
            wallet_address=wallet_address,
            nonce=nonce,
            signature=signature,
        )
    except WalletVerifyError as exc:
        return JSONResponse(
            {"error": str(exc), "code": exc.reason_code},
            status_code=400,
        )
    except Exception as exc:
        logger.exception("Unexpected error in wallet verify: %s", exc)
        return JSONResponse(
            {"error": "Verification failed.", "code": "INTERNAL_ERROR"},
            status_code=500,
        )

    return JSONResponse({
        "status": "VERIFIED",
        "wallet_address": verified_address,
    })
