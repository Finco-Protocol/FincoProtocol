"""Access to an enhanced Verified dossier, separate from verification truth."""
from __future__ import annotations

import os
from dataclasses import dataclass
from enum import Enum


class EntitlementState(str, Enum):
    ACTIVE = "ACTIVE"
    INACTIVE = "INACTIVE"
    UNAVAILABLE = "UNAVAILABLE"


@dataclass(frozen=True)
class VerifiedEntitlement:
    subject_id: str | None
    entitlement: str
    state: EntitlementState
    source: str


VERIFIED_ASSET_DETAIL = "verified_asset_detail"


def resolve_verified_entitlement(
    session, *, allowed_subject_ids: frozenset[str] | None = None,
) -> VerifiedEntitlement:
    """Signed-session subject allowlist; no token balance or model input."""
    if session is None:
        return VerifiedEntitlement(None, VERIFIED_ASSET_DETAIL, EntitlementState.UNAVAILABLE, "SESSION")
    if allowed_subject_ids is None:
        allowed_subject_ids = frozenset(
            part.strip() for part in os.getenv("FINCO_VERIFIED_DETAIL_SUBJECT_IDS", "").split(",")
            if part.strip()
        )
    active = session.session_type == "admin" and session.user_id in allowed_subject_ids
    return VerifiedEntitlement(
        session.user_id, VERIFIED_ASSET_DETAIL,
        EntitlementState.ACTIVE if active else EntitlementState.INACTIVE,
        "SERVER_SUBJECT_ALLOWLIST",
    )


def entitlement_public_view(entitlement: VerifiedEntitlement) -> dict[str, str]:
    return {"capability": entitlement.entitlement, "state": entitlement.state.value}
