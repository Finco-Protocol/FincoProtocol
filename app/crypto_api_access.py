"""Crypto read-only API — shared access helper.

The API resolves entitlement through the SAME canonical authority as the UI products (no API-specific
balance, RPC or threshold logic). Typed denial JSON exposes only ``resource``, ``access_state`` and
``reason``; no RPC URL, provider secret, private configuration or protected payload is ever included.

Unlike already-existing Tokenized Markets product surfaces, ``crypto.api`` is a new capability:
canonical INACTIVE means the API is not activated and therefore remains fail-closed. This product-boundary
rule does not change the canonical decision or the shared Tokenized/Yield adapter semantics.
"""
from __future__ import annotations

from dataclasses import replace
from typing import Any

from app.crypto_resource_access import CryptoAccessDecision, resolve_crypto_access
from app.protocol.entitlement_evaluator import Decision
from app.protocol.entitlement_policy import CRYPTO_API


async def resolve_api_access(request: Any, **evaluator_kwargs) -> CryptoAccessDecision:
    decision = await resolve_crypto_access(request, CRYPTO_API, **evaluator_kwargs)
    if decision.upstream is not None and decision.upstream.decision is Decision.INACTIVE:
        return replace(decision, access_allowed=False)
    return decision


def api_denial_payload(decision: CryptoAccessDecision) -> dict:
    return {"error": "CRYPTO_API_ACCESS_REQUIRED", **decision.safe_fields()}
