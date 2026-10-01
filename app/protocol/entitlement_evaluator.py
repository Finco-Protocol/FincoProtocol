"""Deterministic resource-access decision: ALLOW / DENY / INACTIVE.

    resource_key + wallet/session verification + canonical deployment + canonical balance observation
    + configured policy  ->  ALLOW | DENY | INACTIVE

Semantics
  ALLOW     the resource is public, or the verified wallet's observed balance meets the policy threshold.
  DENY      the resource is gated and access cannot be PROVEN (fail closed): no/unverified wallet,
            unresolved deployment, unavailable balance, stale or mismatched observation, below threshold,
            invalid configuration, unknown resource.
  INACTIVE  token gating is not active for this resource (global flag off or policy disabled). Nothing is
            granted or denied by the token; the caller applies its existing, ungated product behaviour.
            ``allowed`` is False for INACTIVE: it never *proves* an entitlement.

Access control only: this module reads nothing from, and writes nothing to, the financial engine, Yield
mathematics, Radar, Verify or Signed Run. wallet ownership != signing authority != entitlement != metering.
"""
from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timezone
from decimal import Decimal
from enum import Enum
from typing import Mapping

from app.protocol.balance_observation import (
    BalanceObservation, ObservationStatus, TokenBalanceReader, observe_finco_balance,
)
from app.protocol.entitlement_policy import POLICY_VERSION, AccessMode, EntitlementPolicy, PolicySet
from app.protocol.token_deployments import DeploymentRegistry

MAX_OBSERVATION_AGE_SECONDS = 300      # operational freshness bound, not a tokenomics parameter


class Decision(str, Enum):
    ALLOW = "ALLOW"
    DENY = "DENY"
    INACTIVE = "INACTIVE"


@dataclass(frozen=True)
class WalletContext:
    """Session-level wallet state. ``verified`` must come from the EIP-191 ownership flow."""
    address: str | None
    verified: bool = False


NO_WALLET = WalletContext(None, False)


def wallet_context_for_user(user_id: str) -> WalletContext:
    """Verified-wallet context from the existing wallet/session binding (rows exist only once verified)."""
    from app.protocol.wallet_auth import get_verified_wallet
    row = get_verified_wallet(user_id)
    return WalletContext(row["wallet_address"], True) if row else NO_WALLET


@dataclass(frozen=True)
class AccessEntitlementDecision:
    resource_key: str
    decision: Decision
    reason_code: str
    access_mode: str | None
    wallet_address: str | None
    chain_id: int | None
    contract_address: str | None
    observation_status: str | None
    observed_balance: Decimal | None
    minimum_balance: Decimal | None
    observed_at: datetime | None
    policy_version: str = POLICY_VERSION

    @property
    def allowed(self) -> bool:
        return self.decision is Decision.ALLOW

    @property
    def gate_active(self) -> bool:
        return self.decision is not Decision.INACTIVE


def _decision(resource_key: str, decision: Decision, reason: str, *,
              policy: EntitlementPolicy | None = None, wallet: WalletContext | None = None,
              observation: BalanceObservation | None = None) -> AccessEntitlementDecision:
    return AccessEntitlementDecision(
        resource_key=resource_key, decision=decision, reason_code=reason,
        access_mode=policy.access_mode.value if policy else None,
        wallet_address=wallet.address if wallet else None,
        chain_id=observation.chain_id if observation else None,
        contract_address=observation.contract_address if observation else None,
        observation_status=observation.status.value if observation else None,
        observed_balance=observation.normalized_balance if observation else None,
        minimum_balance=policy.minimum_balance if policy else None,
        observed_at=observation.observed_at if observation else None)


def decide_resource_access(
    resource_key: str,
    wallet: WalletContext,
    policy_set: PolicySet,
    registry: DeploymentRegistry,
    observation: BalanceObservation | None,
    *,
    now: datetime | None = None,
) -> AccessEntitlementDecision:
    """Pure decision given an already-made observation (None = not observed)."""
    now = now or datetime.now(timezone.utc)
    policy = policy_set.get(resource_key)
    if policy is None:
        return _decision(resource_key, Decision.DENY, "UNKNOWN_RESOURCE", wallet=wallet)
    if policy.access_mode is AccessMode.PUBLIC:
        return _decision(resource_key, Decision.ALLOW, "PUBLIC_RESOURCE", policy=policy)

    # ---- gated resource ---------------------------------------------------------------------------
    if policy_set.config_error:
        return _decision(resource_key, Decision.DENY, "POLICY_CONFIG_INVALID", policy=policy, wallet=wallet)
    if not policy_set.gating_enabled or not policy.enabled:
        return _decision(resource_key, Decision.INACTIVE,
                         "TOKEN_GATING_OFF" if not policy_set.gating_enabled else "POLICY_DISABLED",
                         policy=policy, wallet=wallet)
    if policy.minimum_balance is None:
        return _decision(resource_key, Decision.DENY, "POLICY_THRESHOLD_UNSET", policy=policy, wallet=wallet)
    if policy.wallet_verified_required:
        if not wallet.address:
            return _decision(resource_key, Decision.DENY, "WALLET_NOT_CONNECTED", policy=policy, wallet=wallet)
        if not wallet.verified:
            return _decision(resource_key, Decision.DENY, "WALLET_NOT_VERIFIED", policy=policy, wallet=wallet)

    resolution = registry.resolve(policy.chain_id)
    if not resolution.resolved or resolution.deployment is None:
        return _decision(resource_key, Decision.DENY, resolution.reason or resolution.status.value,
                         policy=policy, wallet=wallet)
    deployment = resolution.deployment

    if observation is None:
        return _decision(resource_key, Decision.DENY, "BALANCE_NOT_OBSERVED", policy=policy, wallet=wallet)
    if observation.status is not ObservationStatus.OBSERVED or observation.balance_raw is None \
            or observation.normalized_balance is None:
        return _decision(resource_key, Decision.DENY, observation.status.value, policy=policy,
                         wallet=wallet, observation=observation)
    # Exact identity only: chain + contract + decimals + wallet. Ticker/name never participate.
    if (observation.chain_id != deployment.chain_id
            or observation.contract_address != deployment.contract_address
            or observation.decimals != deployment.decimals
            or (wallet.address or "").lower() != (observation.wallet_address or "")):
        return _decision(resource_key, Decision.DENY, "OBSERVATION_IDENTITY_MISMATCH", policy=policy,
                         wallet=wallet, observation=observation)
    if observation.observed_at is None or not 0 <= (now - observation.observed_at).total_seconds() \
            <= MAX_OBSERVATION_AGE_SECONDS:
        return _decision(resource_key, Decision.DENY, "BALANCE_STALE", policy=policy, wallet=wallet,
                         observation=observation)

    required_raw = policy.minimum_balance.scaleb(deployment.decimals)
    if required_raw != required_raw.to_integral_value():
        return _decision(resource_key, Decision.DENY, "THRESHOLD_EXCEEDS_TOKEN_DECIMALS", policy=policy,
                         wallet=wallet, observation=observation)
    if observation.balance_raw >= int(required_raw):
        return _decision(resource_key, Decision.ALLOW, "BALANCE_AT_OR_ABOVE_THRESHOLD", policy=policy,
                         wallet=wallet, observation=observation)
    return _decision(resource_key, Decision.DENY, "BALANCE_BELOW_THRESHOLD", policy=policy, wallet=wallet,
                     observation=observation)


async def evaluate_resource_access(
    resource_key: str,
    wallet: WalletContext,
    *,
    policy_set: PolicySet,
    registry: DeploymentRegistry,
    reader: TokenBalanceReader,
    now: datetime | None = None,
) -> AccessEntitlementDecision:
    """Observe the balance only when the decision actually needs it, then decide."""
    policy = policy_set.get(resource_key)
    needs_balance = (
        policy is not None and policy.access_mode is AccessMode.FINCO_HOLDER
        and not policy_set.config_error and policy_set.gating_enabled and policy.enabled
        and policy.minimum_balance is not None and bool(wallet.address)
        and (wallet.verified or not policy.wallet_verified_required)
    )
    observation = None
    if needs_balance:
        observation = await observe_finco_balance(wallet.address, registry, reader,
                                                  chain_id=policy.chain_id)  # type: ignore[union-attr]
    return decide_resource_access(resource_key, wallet, policy_set, registry, observation, now=now)


async def evaluate_all_resources(
    wallet: WalletContext, *, policy_set: PolicySet, registry: DeploymentRegistry,
    reader: TokenBalanceReader, now: datetime | None = None,
) -> Mapping[str, AccessEntitlementDecision]:
    return {key: await evaluate_resource_access(key, wallet, policy_set=policy_set, registry=registry,
                                                reader=reader, now=now)
            for key in policy_set.policies}
