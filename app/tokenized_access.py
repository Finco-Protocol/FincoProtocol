"""Tokenized Markets — product access adapter (presentation/API boundary only).

Thin analogue of ``finco_yield.access`` over the shared crypto adapter. Market-data authority and access
authority stay separate: nothing in ``finco_radar/venues`` or the collector consults this module.

PUBLIC  : tokenized.basic        (basic identity + current market state)
HOLDER  : tokenized.history      (deeper historical ranges)
          tokenized.dislocation  (dislocation intelligence / premium analytics)
Holder resources ship DISABLED and unthresholded; thresholds are operator configuration.
"""
from __future__ import annotations

from enum import Enum
from typing import Any

from app.crypto_resource_access import CryptoAccessDecision, CryptoAccessState, resolve_crypto_access
from app.protocol.entitlement_policy import TOKENIZED_BASIC, TOKENIZED_DISLOCATION, TOKENIZED_HISTORY

TokenizedAccessState = CryptoAccessState
TokenizedAccessDecision = CryptoAccessDecision


class TokenizedResource(str, Enum):
    BASIC = TOKENIZED_BASIC
    HISTORY = TOKENIZED_HISTORY
    DISLOCATION = TOKENIZED_DISLOCATION


async def resolve_tokenized_access(request: Any, resource: TokenizedResource,
                                   **evaluator_kwargs) -> TokenizedAccessDecision:
    return await resolve_crypto_access(request, resource.value, **evaluator_kwargs)


def denial_payload(decision: TokenizedAccessDecision) -> dict:
    """Typed sanitized denial body — never contains protected payload, RPC or configuration."""
    return {"error": "TOKENIZED_PREMIUM_REQUIRED", **decision.safe_fields()}
