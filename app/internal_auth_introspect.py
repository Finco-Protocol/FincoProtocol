"""Versioned fail-closed internal auth/entitlement introspection contract (M2-B/B3).

Allows the standalone Finco-Protocol/Radar service to verify opaque session cookies
(`finco_session` and `finco_demo`, matching app/auth.py) against the authoritative
FincoProtocol Model host over a private service-to-service channel WITHOUT copying
FINCO_SECRET_KEY or directly reading Model databases.

Security properties:
- Disabled (HTTP 503) unless FINCO_INTERNAL_AUTH_INTROSPECT_TOKEN is configured (>= 16 chars).
- Requires exact X-Finco-Internal-Token match (constant-time hmac.compare_digest).
- Strictly validates audience against ALLOWED_AUDIENCES (fail-closed HTTP 403).
- Returns minimum typed claims only (schema, audience, authenticated, session_kind,
  user_id, tenant_id, entitlements, wallet_verified, wallet_address).
- Never echoes raw cookies, signing keys, wallet secrets, or client financial data.
"""
from __future__ import annotations

import hmac
import os
from typing import Literal, Optional

from fastapi import APIRouter, Header, HTTPException
from pydantic import BaseModel, ConfigDict, Field

from app.auth import COOKIE_NAME, DEMO_COOKIE_NAME, decode_demo_session_token, decode_session_token


SCHEMA_VERSION = "finco.internal.auth.introspect.v1"
ALLOWED_AUDIENCES = frozenset({"radar", "finco-radar-v1"})
INTERNAL_TOKEN_ENV = "FINCO_INTERNAL_AUTH_INTROSPECT_TOKEN"

router = APIRouter(prefix="/internal/v1/auth", tags=["internal-auth"])


class IntrospectRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    audience: str = Field(..., min_length=1, max_length=64)
    session_cookie: Optional[str] = Field(default=None, max_length=4096)
    demo_cookie: Optional[str] = Field(default=None, max_length=4096)


class IntrospectResponse(BaseModel):
    schema_: Literal["finco.internal.auth.introspect.v1"] = Field(default=SCHEMA_VERSION, alias="schema")
    authenticated: bool
    audience: str
    session_kind: Literal["user", "demo", "anonymous"]
    user_id: Optional[str] = None
    tenant_id: Optional[str] = None
    entitlements: list[str] = Field(default_factory=list)
    wallet_verified: bool = False
    wallet_address: Optional[str] = None

    model_config = ConfigDict(populate_by_name=True)


def _configured_internal_token() -> str:
    return (os.environ.get(INTERNAL_TOKEN_ENV) or "").strip()


@router.post("/introspect", response_model=IntrospectResponse, response_model_by_alias=True)
def introspect_session(
    body: IntrospectRequest,
    x_finco_internal_token: Optional[str] = Header(default=None, alias="X-Finco-Internal-Token"),
) -> IntrospectResponse:
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
            return IntrospectResponse(
                authenticated=True,
                audience=body.audience,
                session_kind="user",
                user_id=str(sess.user_id),
                tenant_id=str(sess.user_id),
                entitlements=["radar:read", "crypto:read", "yield:read"],
                wallet_verified=False,
                wallet_address=None,
            )

    if body.demo_cookie:
        demo = decode_demo_session_token(body.demo_cookie)
        if demo is not None:
            return IntrospectResponse(
                authenticated=True,
                audience=body.audience,
                session_kind="demo",
                user_id=str(demo.user_id),
                tenant_id=str(demo.user_id),
                entitlements=["radar:read:public"],
                wallet_verified=False,
                wallet_address=None,
            )

    return IntrospectResponse(
        authenticated=False,
        audience=body.audience,
        session_kind="anonymous",
        user_id=None,
        tenant_id=None,
        entitlements=[],
        wallet_verified=False,
        wallet_address=None,
    )
