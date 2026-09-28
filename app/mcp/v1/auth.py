"""FINCO MCP V1 — Auth adapter.

Identity comes from FINCO_SESSION_TOKEN (set by the operator at server startup,
never from tool arguments). This enforces the contract:
  - No trusted user_id in tool args.
  - Signed-session semantics are preserved across the MCP boundary.
  - Spoofed identity is impossible: the session token is verified server-side.

Supports both admin (finco_session) and demo (finco_demo) session tokens.
"""
from __future__ import annotations

import os
from typing import Optional


class AuthenticationRequired(Exception):
    """Raised when no valid session token is configured."""


def resolve_mcp_session_token() -> Optional[str]:
    """Return the raw FINCO_SESSION_TOKEN from the environment, or None."""
    return os.environ.get("FINCO_SESSION_TOKEN", "").strip() or None


def resolve_mcp_user_id() -> Optional[str]:
    """Resolve user_id from FINCO_SESSION_TOKEN environment variable.

    Tries admin session first, then demo session. Returns None if the token
    is absent, expired, or invalid.
    """
    token = resolve_mcp_session_token()
    if not token:
        return None

    from app.auth import decode_session_token, decode_demo_session_token

    session = decode_session_token(token)
    if session is not None:
        return session.user_id

    session = decode_demo_session_token(token)
    if session is not None:
        return session.user_id

    return None


def require_mcp_user_id() -> str:
    """Return user_id or raise AuthenticationRequired.

    Call this from every tool that requires an authenticated session.
    """
    user_id = resolve_mcp_user_id()
    if user_id is None:
        raise AuthenticationRequired(
            "FINCO_SESSION_TOKEN is missing, expired, or invalid. "
            "Set a valid signed session token in the environment before starting the MCP server."
        )
    return user_id
