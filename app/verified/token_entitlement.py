"""B2.2 read-only $FINCO access evidence, never verification authority.

Production has no approved $FINCO deployment in this registry. Environment
values alone are not provenance and cannot activate the token capability.
"""
from __future__ import annotations

import os
from dataclasses import dataclass
from datetime import datetime
from decimal import Decimal
from enum import Enum
from typing import Protocol

from app.protocol.token_config import TokenConfig, _validate_hex_address, get_token_config

FINCO_ENTITLEMENT_SCHEMA = "FINCO_TOKEN_ENTITLEMENT_V1"
VERIFIED_ASSET_DETAIL = "verified_asset_detail"


@dataclass(frozen=True)
class ApprovedFincoDeployment:
    chain_id: int
    token_address: str
    standard: str
    decimals: int
    provenance: str

    def __post_init__(self) -> None:
        address = _validate_hex_address(self.token_address)
        if self.chain_id <= 0 or address is None or self.standard != "ERC-20":
            raise ValueError("exact ERC-20 deployment identity required")
        if not 0 <= self.decimals <= 77 or not self.provenance.strip():
            raise ValueError("decimals and provenance required")
        object.__setattr__(self, "token_address", address)


# Deliberately empty until an independently approved production deployment is
# committed with chain, contract, decimals and source provenance.
APPROVED_FINCO_DEPLOYMENTS: tuple[ApprovedFincoDeployment, ...] = ()


@dataclass(frozen=True)
class FincoEntitlementPolicy:
    chain_id: int
    token_address: str
    token_decimals: int
    minimum_balance_raw: int
    freshness_seconds: int
    provenance: str
    capability: str = VERIFIED_ASSET_DETAIL
    standard: str = "ERC-20"
    schema: str = FINCO_ENTITLEMENT_SCHEMA

    def __post_init__(self) -> None:
        address = _validate_hex_address(self.token_address)
        if (self.schema != FINCO_ENTITLEMENT_SCHEMA or self.capability != VERIFIED_ASSET_DETAIL
                or self.standard != "ERC-20" or self.chain_id <= 0 or address is None
                or not 0 <= self.token_decimals <= 77
                or not isinstance(self.minimum_balance_raw, int)
                or isinstance(self.minimum_balance_raw, bool)
                or self.minimum_balance_raw <= 0 or self.freshness_seconds <= 0
                or not self.provenance.strip()):
            raise ValueError("invalid exact $FINCO entitlement policy")
        object.__setattr__(self, "token_address", address)


def get_production_policy() -> tuple[FincoEntitlementPolicy, TokenConfig] | None:
    """Require approved deployment AND explicit P4 RPC/threshold configuration."""
    config = get_token_config()
    if config is None or config.decimals_override is None:
        return None
    matches = [entry for entry in APPROVED_FINCO_DEPLOYMENTS
               if entry.chain_id == config.chain_id
               and entry.token_address == config.token_address
               and entry.decimals == config.decimals_override]
    if len(matches) != 1:
        return None
    try:
        age = int(os.getenv("FINCO_ENTITLEMENT_MAX_AGE_SECONDS", ""))
        raw = config.min_balance * Decimal(10 ** config.decimals_override)
        if age <= 0 or not raw.is_finite() or raw != raw.to_integral_value():
            return None
        policy = FincoEntitlementPolicy(
            chain_id=config.chain_id, token_address=config.token_address,
            token_decimals=config.decimals_override, minimum_balance_raw=int(raw),
            freshness_seconds=age, provenance=matches[0].provenance,
        )
    except (ValueError, ArithmeticError):
        return None
    return policy, config


class BalanceEvidenceState(str, Enum):
    AVAILABLE = "AVAILABLE"
    UNAVAILABLE = "UNAVAILABLE"
    STALE = "STALE"


@dataclass(frozen=True)
class TokenBalanceEvidence:
    chain_id: int
    token_address: str
    wallet_address: str
    token_decimals: int
    balance_raw: int | None
    observed_at: datetime | None
    source: str
    state: BalanceEvidenceState
    reason: str | None = None

    def __post_init__(self) -> None:
        token = _validate_hex_address(self.token_address)
        wallet = _validate_hex_address(self.wallet_address)
        if self.chain_id <= 0 or token is None or wallet is None or not self.source.strip():
            raise ValueError("malformed balance identity or source")
        if not 0 <= self.token_decimals <= 77:
            raise ValueError("invalid token decimals")
        if self.balance_raw is not None and (isinstance(self.balance_raw, bool)
                                              or not isinstance(self.balance_raw, int)
                                              or self.balance_raw < 0):
            raise ValueError("balance must be nonnegative integer base units")
        if self.observed_at is not None and (self.observed_at.tzinfo is None
                                             or self.observed_at.utcoffset() is None):
            raise ValueError("aware observation timestamp required")
        object.__setattr__(self, "token_address", token)
        object.__setattr__(self, "wallet_address", wallet)


class TokenBalanceProvider(Protocol):
    async def balance_of(self, policy: FincoEntitlementPolicy,
                         wallet_address: str) -> TokenBalanceEvidence: ...


class P4ReadOnlyBalanceProvider:
    """Adapt existing P4 eth_call reader; never issue a transaction."""

    def __init__(self, config: TokenConfig) -> None:
        self.config = config

    async def balance_of(self, policy: FincoEntitlementPolicy,
                         wallet_address: str) -> TokenBalanceEvidence:
        from app.protocol.token_balance import (
            read_token_balance, STATUS_ENTITLED, STATUS_INSUFFICIENT,
        )
        observation = await read_token_balance(wallet_address, self.config)
        available = observation.status in (STATUS_ENTITLED, STATUS_INSUFFICIENT)
        return TokenBalanceEvidence(
            chain_id=observation.chain_id,
            token_address=observation.token_address,
            wallet_address=observation.wallet_address,
            token_decimals=observation.decimals if observation.decimals is not None
            else policy.token_decimals,
            balance_raw=observation.balance_raw if available else None,
            observed_at=observation.observed_at,
            source="P4_READ_ONLY_JSON_RPC",
            state=BalanceEvidenceState.AVAILABLE if available else BalanceEvidenceState.UNAVAILABLE,
            reason=None if available else observation.status,
        )


def evaluate_token_entitlement(
    *, subject_id: str, wallet_address: str | None,
    policy: FincoEntitlementPolicy | None, evidence: TokenBalanceEvidence | None,
    as_of: datetime,
):
    """Pure access decision; never reads or changes model/Verify/Radar state."""
    from app.verified.entitlement import EntitlementState, VerifiedEntitlement

    def result(state: EntitlementState, reason: str):
        return VerifiedEntitlement(subject_id, VERIFIED_ASSET_DETAIL, state,
                                   "FINCO_TOKEN_BALANCE", reason,
                                   evidence.observed_at if evidence is not None else None)

    if as_of.tzinfo is None or as_of.utcoffset() is None:
        raise ValueError("aware evaluation time required")
    if policy is None:
        return result(EntitlementState.TOKEN_CONFIGURATION_UNAVAILABLE,
                      "TOKEN_CONFIGURATION_UNAVAILABLE")
    wallet = _validate_hex_address(wallet_address or "")
    if wallet is None:
        return result(EntitlementState.IDENTITY_UNAVAILABLE, "WALLET_IDENTITY_UNAVAILABLE")
    if not isinstance(evidence, TokenBalanceEvidence):
        return result(EntitlementState.UNAVAILABLE, "BALANCE_EVIDENCE_UNAVAILABLE")
    if (evidence.wallet_address != wallet or evidence.chain_id != policy.chain_id
            or evidence.token_address != policy.token_address
            or evidence.token_decimals != policy.token_decimals):
        return result(EntitlementState.UNAVAILABLE, "BALANCE_IDENTITY_MISMATCH")
    if evidence.state is BalanceEvidenceState.STALE:
        return result(EntitlementState.STALE, "BALANCE_STALE")
    if evidence.state is not BalanceEvidenceState.AVAILABLE or evidence.balance_raw is None:
        return result(EntitlementState.UNAVAILABLE,
                      evidence.reason or "BALANCE_EVIDENCE_UNAVAILABLE")
    if evidence.observed_at is None or not 0 <= (as_of - evidence.observed_at).total_seconds() <= policy.freshness_seconds:
        return result(EntitlementState.STALE, "BALANCE_STALE")
    if evidence.balance_raw < policy.minimum_balance_raw:
        return result(EntitlementState.INACTIVE, "BALANCE_BELOW_THRESHOLD")
    return result(EntitlementState.ACTIVE, "BALANCE_AT_OR_ABOVE_THRESHOLD")
