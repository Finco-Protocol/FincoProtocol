"""Access to an enhanced Verified dossier, separate from verification truth."""
from __future__ import annotations

import os
from dataclasses import dataclass
from datetime import datetime, timezone
from enum import Enum


class EntitlementState(str, Enum):
    ACTIVE = "ACTIVE"
    INACTIVE = "INACTIVE"
    UNAVAILABLE = "UNAVAILABLE"
    STALE = "STALE"
    IDENTITY_UNAVAILABLE = "IDENTITY_UNAVAILABLE"
    TOKEN_CONFIGURATION_UNAVAILABLE = "TOKEN_CONFIGURATION_UNAVAILABLE"


@dataclass(frozen=True)
class VerifiedEntitlement:
    subject_id: str | None
    entitlement: str
    state: EntitlementState
    source: str
    reason: str | None = None
    observed_at: datetime | None = None


VERIFIED_ASSET_DETAIL = "verified_asset_detail"


def resolve_verified_entitlement(
    session, *, allowed_subject_ids: frozenset[str] | None = None,
) -> VerifiedEntitlement:
    """Legacy administrative override, never evidence of token ownership."""
    if session is None:
        return VerifiedEntitlement(None, VERIFIED_ASSET_DETAIL, EntitlementState.UNAVAILABLE,
                                   "SESSION", "AUTHENTICATION_REQUIRED")
    if allowed_subject_ids is None:
        allowed_subject_ids = frozenset(
            part.strip() for part in os.getenv("FINCO_VERIFIED_DETAIL_SUBJECT_IDS", "").split(",")
            if part.strip()
        )
    active = session.session_type == "admin" and session.user_id in allowed_subject_ids
    return VerifiedEntitlement(
        session.user_id, VERIFIED_ASSET_DETAIL,
        EntitlementState.ACTIVE if active else EntitlementState.INACTIVE,
        "ADMIN_OVERRIDE", "ADMIN_OVERRIDE_ACTIVE" if active else "ADMIN_OVERRIDE_NOT_GRANTED",
    )


def entitlement_public_view(entitlement: VerifiedEntitlement) -> dict[str, str | None]:
    return {"capability": entitlement.entitlement, "state": entitlement.state.value,
            "source": entitlement.source, "reason": entitlement.reason}


async def resolve_verified_entitlement_for_request(session) -> VerifiedEntitlement:
    """Resolve access from server-bound wallet, or explicit admin override.

    B2_2_TOKEN_AUTHORITY_FIREWALL: called only by presentation/router code,
    never by certificate construction or B2.1 eligibility.
    """
    override = resolve_verified_entitlement(session)
    if override.state is EntitlementState.ACTIVE:
        return override
    from app.verified.token_entitlement import (
        P4ReadOnlyBalanceProvider, evaluate_token_entitlement, get_production_policy,
    )
    context = get_production_policy()
    if context is None:
        return evaluate_token_entitlement(
            subject_id=session.user_id, wallet_address=None, policy=None,
            evidence=None, as_of=datetime.now(timezone.utc),
        )
    policy, config = context
    if session.session_type == "demo":
        return evaluate_token_entitlement(
            subject_id=session.user_id, wallet_address=None, policy=policy,
            evidence=None, as_of=datetime.now(timezone.utc),
        )
    from app.protocol.wallet_auth import get_verified_wallet
    wallet_link = get_verified_wallet(session.user_id)
    wallet = wallet_link["wallet_address"] if wallet_link else None
    if wallet is None:
        return evaluate_token_entitlement(
            subject_id=session.user_id, wallet_address=None, policy=policy,
            evidence=None, as_of=datetime.now(timezone.utc),
        )
    try:
        evidence = await P4ReadOnlyBalanceProvider(config).balance_of(policy, wallet)
    except Exception:
        evidence = None
    return evaluate_token_entitlement(
        subject_id=session.user_id, wallet_address=wallet, policy=policy,
        evidence=evidence, as_of=datetime.now(timezone.utc),
    )
