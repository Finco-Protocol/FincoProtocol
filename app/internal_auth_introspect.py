"""Versioned fail-closed internal auth/entitlement introspection contract (M2-B).

Allows a standalone FincoRadar service to verify opaque session cookies against
the authoritative FincoProtocol Model host over a private service-to-service
channel WITHOUT copying FINCO_SECRET_KEY or directly reading Model databases.

Security properties:
- Disabled (HTTP 503) unless FINCO_INTERNAL_AUTH_INTROSPECT_TOKEN is configured.
- Requires exact X-Finco-Internal-Token match (constant-time hmac.compare_digest).
- Strictly validates audience against ALLOWED_AUDIENCES (fail-closed HTTP 403).
- Returns minimum claims only (user_id, tenant_id, role, entitlements); never
  echoes raw cookies, signing keys, wallet secrets, or client financial data.
- Note: reflects current app.auth stateless signed-token capabilities (no
  server-side revocation store exists in baseline app.auth).
"""
from __future__ import annotations

import hmac
import os
from typing import Literal, Optional

from fastapi import APIRouter, Header, HTTPException
from pydantic import BaseModel, ConfigDict, Field

from app.auth import decode_demo_session_token, decode_session_token


SCHEMA_VERSION = "finco.internal.auth.introspect.v1"
ALLOWED_AUDIENCES = frozenset({"finco-radar-v1"})
INTERNAL_TOKEN_ENV = "FINCO_INTERNAL_AUTH_INTROSPECT_TOKEN"

router = APIRouter(prefix="/internal/v1/auth", tags=["internal-auth"])


class IntrospectRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    audience: str = Field(..., min_length=1, max_length=64)
    session_token: Optional[str] = Field(default=None, max_length=4096)
    demo_session_token: Optional[str] = Field(default=None, max_length=4096)


class IntrospectResponse(BaseModel):
    schema_version: Literal["finco.internal.auth.introspect.v1"] = SCHEMA_VERSION
    authenticated: bool
    audience: str
    session_kind: Literal["admin", "demo", "anonymous"]
    user_id: Optional[str] = None
    tenant_id: Optional[str] = None
    entitlements: list[str] = Field(default_factory=list)


def _configured_internal_token() -> str:
    return (os.environ.get(INTERNAL_TOKEN_ENV) or "").strip()


@router.post("/introspect", response_model=IntrospectResponse)
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

    if body.session_token:
        sess = decode_session_token(body.session_token)
        if sess is not None:
            return IntrospectResponse(
                authenticated=True,
                audience=body.audience,
                session_kind="admin",
                user_id=str(sess.user_id),
                tenant_id=str(sess.user_id),
                entitlements=["radar:read", "crypto:read", "yield:read"],
            )

    if body.demo_session_token:
        demo = decode_demo_session_token(body.demo_session_token)
        if demo is not None:
            return IntrospectResponse(
                authenticated=True,
                audience=body.audience,
                session_kind="demo",
                user_id=str(demo.user_id),
                tenant_id=str(demo.user_id),
                entitlements=["radar:read:public"],
            )

    return IntrospectResponse(
        authenticated=False,
        audience=body.audience,
        session_kind="anonymous",
        user_id=None,
        tenant_id=None,
        entitlements=[],
    )
