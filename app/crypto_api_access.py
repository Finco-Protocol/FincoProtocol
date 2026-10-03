"""Crypto read-only API — shared access helper.

The API resolves entitlement through the SAME canonical authority as the UI products (no API-specific
balance, RPC or threshold logic). Typed denial JSON exposes only ``resource``, ``access_state`` and
``reason``; no RPC URL, provider secret, private configuration or protected payload is ever included.
"""
from __future__ import annotations

from typing import Any

from app.crypto_resource_access import CryptoAccessDecision, resolve_crypto_access
from app.protocol.entitlement_policy import CRYPTO_API


async def resolve_api_access(request: Any, **evaluator_kwargs) -> CryptoAccessDecision:
    return await resolve_crypto_access(request, CRYPTO_API, **evaluator_kwargs)


def api_denial_payload(decision: CryptoAccessDecision) -> dict:
    return {"error": "CRYPTO_API_ACCESS_REQUIRED", **decision.safe_fields()}
