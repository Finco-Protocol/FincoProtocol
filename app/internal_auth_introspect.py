"""Versioned fail-closed internal auth & entitlement introspection contract (M2-B/Correction B).

Allows the standalone Finco-Protocol/Radar service to verify opaque session cookies
(`finco_session` and `finco_demo`, matching app/auth.py) AND obtain canonical server-side
per-resource entitlement decisions from `app.protocol.entitlement_evaluator` over a private
loopback/service channel WITHOUT copying FINCO_SECRET_KEY or directly reading Model DBs.

Security properties:
- Hidden from public OpenAPI schema (`include_in_schema=False`).
- Rejects proxied/public-gateway requests (`X-Forwarded-For` / `Forwarded` headers -> HTTP 403).
- Enforces loopback/private peer attestation (`request.client.host` must be in loopback or
  explicit `FINCO_INTERNAL_AUTH_ALLOWED_CLIENTS` allowlist -> HTTP 403).
- Disabled (HTTP 503) unless FINCO_INTERNAL_AUTH_INTROSPECT_TOKEN is configured (>= 16 chars).
- Requires exact X-Finco-Internal-Token match (constant-time hmac.compare_digest -> HTTP 401).
- Strictly validates audience against ALLOWED_AUDIENCES (fail-closed HTTP 403).
- Returns canonical per-resource `entitlement_decisions` from `app.protocol.entitlement_evaluator`
  without hardcoded excess entitlements; never echoes raw cookies, signing keys, or client data.
"""
from __future__ import annotations

import hmac
import ipaddress
import os
from typing import Any, Literal, Optional

from fastapi import APIRouter, Header, HTTPException, Request, Response
from pydantic import BaseModel, ConfigDict, Field

from app.auth import decode_demo_session_token, decode_session_token
from app.protocol.entitlement_evaluator import (
    evaluate_all_resources,
    wallet_context_for_session,
)


SCHEMA_VERSION = "finco.internal.auth.introspect.v1"
ALLOWED_AUDIENCES = frozenset({"radar", "finco-radar-v1"})
INTERNAL_TOKEN_ENV = "FINCO_INTERNAL_AUTH_INTROSPECT_TOKEN"
ALLOWED_CLIENTS_ENV = "FINCO_INTERNAL_AUTH_ALLOWED_CLIENTS"
PRODUCTION_LOOPBACK_CLIENTS = frozenset({"127.0.0.1", "::1"})
NON_PROD_LOOPBACK_CLIENTS = frozenset({"127.0.0.1", "::1", "localhost", "testclient"})

router = APIRouter(prefix="/internal/v1/auth", tags=["internal-auth"], include_in_schema=False)


class IntrospectRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    audience: str = Field(..., min_length=1, max_length=64)
    session_cookie: Optional[str] = Field(default=None, max_length=4096)
    demo_cookie: Optional[str] = Field(default=None, max_length=4096)


class EntitlementDecisionOut(BaseModel):
    decision: Literal["PUBLIC", "ALLOW", "INACTIVE", "DENY"]
    reason: str


class IntrospectResponse(BaseModel):
    schema_: Literal["finco.internal.auth.introspect.v1"] = Field(default=SCHEMA_VERSION, alias="schema")
    authenticated: bool
    audience: str
    session_kind: Literal["user", "demo", "anonymous"]
    user_id: Optional[str] = None
    tenant_id: Optional[str] = None
    entitlements: list[str] = Field(default_factory=list)
    entitlement_decisions: dict[str, EntitlementDecisionOut] = Field(default_factory=dict)
    wallet_verified: bool = False
    wallet_address: Optional[str] = None

    model_config = ConfigDict(populate_by_name=True)


def _is_production_like() -> bool:
    return (os.environ.get("FINCO_ENV") or "").strip().lower() in ("prod", "production", "staging")


def _configured_internal_token() -> str:
    return (os.environ.get(INTERNAL_TOKEN_ENV) or "").strip()


def _parse_validated_private_peers(raw: str) -> frozenset[str]:
    """Accept ONLY explicit private/loopback IP literals; reject wildcards, hostnames, and public IPs."""
    validated: set[str] = set()
    for item in raw.split(","):
        host = item.strip()
        if not host:
            continue
        try:
            ip = ipaddress.ip_address(host)
        except ValueError:
            continue
        if ip.is_loopback or ip.is_private:
            validated.add(str(ip))
    return frozenset(validated)


def _allowed_clients() -> frozenset[str]:
    base = PRODUCTION_LOOPBACK_CLIENTS if _is_production_like() else NON_PROD_LOOPBACK_CLIENTS
    extra = (os.environ.get(ALLOWED_CLIENTS_ENV) or "").strip()
    if not extra:
        return base
    return base | _parse_validated_private_peers(extra)


def _enforce_private_network_boundary(request: Request) -> None:
    # Reject any request that traversed a public reverse proxy
    if request.headers.get("x-forwarded-for") or request.headers.get("forwarded") or request.headers.get("x-real-ip"):
        raise HTTPException(status_code=403, detail="INTERNAL_AUTH_PROXIED_REQUEST_DENIED")
    peer_host = request.client.host if request.client else ""
    if _is_production_like() and peer_host == "testclient":
        raise HTTPException(status_code=403, detail="INTERNAL_AUTH_NON_LOOPBACK_PEER_DENIED")
    if peer_host not in _allowed_clients():
        raise HTTPException(status_code=403, detail="INTERNAL_AUTH_NON_LOOPBACK_PEER_DENIED")


async def _canonical_entitlement_decisions(session_obj: Any) -> tuple[dict[str, EntitlementDecisionOut], list[str], bool, Optional[str]]:
    wallet_ctx = wallet_context_for_session(session_obj)
    raw_decisions = await evaluate_all_resources(wallet_ctx)
    out: dict[str, EntitlementDecisionOut] = {}
    allowed_resources: list[str] = []
    for res_key, dec in raw_decisions.items():
        dec_str = dec.decision.value if hasattr(dec.decision, "value") else str(dec.decision)
        out[res_key] = EntitlementDecisionOut(
            decision=dec_str,
            reason=str(getattr(dec, "reason_code", "") or ""),
        )
        if dec_str == "ALLOW":
            allowed_resources.append(res_key)
    w_addr = getattr(wallet_ctx, "wallet_address", None)
    w_ver = bool(getattr(wallet_ctx, "verified", False) and w_addr)
    return out, sorted(allowed_resources), w_ver, w_addr


@router.post("/introspect", response_model=IntrospectResponse, response_model_by_alias=True, include_in_schema=False)
async def introspect_session(
    request: Request,
    response: Response,
    body: IntrospectRequest,
    x_finco_internal_token: Optional[str] = Header(default=None, alias="X-Finco-Internal-Token"),
) -> IntrospectResponse:
    response.headers["Cache-Control"] = "no-store"
    _enforce_private_network_boundary(request)
    expected = _configured_internal_token()
    if not expected or len(expected) < 16:
        raise HTTPException(status_code=503, detail="INTERNAL_AUTH_INTROSPECT_DISABLED")
    if not x_finco_internal_token or not hmac.compare_digest(x_finco_internal_token, expected):
        raise HTTPException(status_code=401, detail="INTERNAL_AUTH_TOKEN_INVALID")
    if body.audience not in ALLOWED_AUDIENCES:
        raise HTTPException(status_code=403, detail="INTERNAL_AUTH_AUDIENCE_DENIED")

    if body.session_cookie:
        sess = decode_session_token(body.session_cookie)
        if sess is not None:
            decisions, allowed, w_ver, w_addr = await _canonical_entitlement_decisions(sess)
            return IntrospectResponse(
                authenticated=True,
                audience=body.audience,
                session_kind="user",
                user_id=str(sess.user_id),
                tenant_id=str(sess.user_id),
                entitlements=allowed,
                entitlement_decisions=decisions,
                wallet_verified=w_ver,
                wallet_address=w_addr,
            )

    if body.demo_cookie:
        demo = decode_demo_session_token(body.demo_cookie)
        if demo is not None:
            decisions, allowed, w_ver, w_addr = await _canonical_entitlement_decisions(demo)
            return IntrospectResponse(
                authenticated=True,
                audience=body.audience,
                session_kind="demo",
                user_id=str(demo.user_id),
                tenant_id=str(demo.user_id),
                entitlements=allowed,
                entitlement_decisions=decisions,
                wallet_verified=w_ver,
                wallet_address=w_addr,
            )

    decisions, allowed, _, _ = await _canonical_entitlement_decisions(None)
    return IntrospectResponse(
        authenticated=False,
        audience=body.audience,
        session_kind="anonymous",
        user_id=None,
        tenant_id=None,
        entitlements=allowed,
        entitlement_decisions=decisions,
        wallet_verified=False,
        wallet_address=None,
    )
