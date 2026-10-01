"""Resource-level access decision — a thin layer over the canonical token-entitlement authority.

Authority chain (nothing below the policy layer is reimplemented here):

    verified wallet/session            app.protocol.wallet_auth.get_verified_wallet
      -> approved $FINCO deployment    app.verified.token_entitlement.APPROVED_FINCO_DEPLOYMENTS (zero in prod)
      -> read-only balance evidence    app.protocol.token_balance.read_token_balance
                                       via P4ReadOnlyBalanceProvider -> TokenBalanceEvidence
      -> canonical token entitlement   evaluate_token_entitlement -> VerifiedEntitlement(EntitlementState)
      -> resource policy (NEW)         entitlement_policy.EntitlementPolicy per resource_key
      -> ResourceAccessDecision        ALLOW | DENY | INACTIVE

Mapping of the canonical ``EntitlementState`` to a resource decision (explicit, one meaning each):

    ACTIVE                            -> ALLOW
    INACTIVE  (below threshold)       -> DENY  BALANCE_BELOW_THRESHOLD
    STALE                             -> DENY  BALANCE_STALE
    UNAVAILABLE                       -> DENY  (reason from the canonical result; never treated as zero)
    IDENTITY_UNAVAILABLE              -> DENY  WALLET_IDENTITY_UNAVAILABLE
    TOKEN_CONFIGURATION_UNAVAILABLE   -> DENY  TOKEN_CONFIGURATION_UNAVAILABLE

``Decision.INACTIVE`` is a *resource-layer* state with its own single meaning: token gating is not active for
this resource (global flag off / policy disabled), so NO token entitlement was evaluated. It is unrelated to
``EntitlementState.INACTIVE`` ("evaluated and not held"), which maps to DENY above. ``allowed`` is False for
INACTIVE: it never proves anything; the caller keeps its existing ungated product behaviour.

Access control only. wallet ownership != balance != entitlement != metering/staking/burn/execution. Nothing
here touches the financial engine, Yield mathematics, Radar, Verify or Signed Run, signs, or broadcasts.
"""
from __future__ import annotations

import os
from dataclasses import dataclass
from datetime import datetime, timezone
from decimal import Decimal
from enum import Enum
from typing import Mapping

from app.protocol.entitlement_policy import (
    POLICY_VERSION, AccessMode, EntitlementPolicy, PolicySet, load_policy_set,
)
from app.protocol.token_deployments import DeploymentResolution, resolve_approved_deployment

FRESHNESS_ENV = "FINCO_ENTITLEMENT_MAX_AGE_SECONDS"   # the existing canonical knob (no default invented)


class Decision(str, Enum):
    ALLOW = "ALLOW"
    DENY = "DENY"
    INACTIVE = "INACTIVE"


@dataclass(frozen=True)
class WalletContext:
    """Wallet state from the EIP-191 ownership flow. ``verified`` is True only for a bound, verified wallet."""
    address: str | None
    verified: bool = False
    subject_id: str | None = None


NO_WALLET = WalletContext(None, False)


def wallet_context_for_user(user_id: str) -> WalletContext:
    """Existing wallet/session binding: a row exists only after ownership was verified."""
    from app.protocol.wallet_auth import get_verified_wallet
    row = get_verified_wallet(user_id)
    return WalletContext(row["wallet_address"], True, user_id) if row else WalletContext(None, False, user_id)


def wallet_context_for_session(session) -> WalletContext:
    """Same rules as the canonical request flow: no session or a demo session has no wallet authority."""
    if session is None or getattr(session, "session_type", None) == "demo":
        return NO_WALLET
    return wallet_context_for_user(session.user_id)


@dataclass(frozen=True)
class ResourceAccessDecision:
    resource_key: str
    decision: Decision
    reason_code: str
    access_mode: str | None
    wallet_address: str | None
    chain_id: int | None
    token_address: str | None
    entitlement_state: str | None          # canonical EntitlementState value when one was evaluated
    observed_balance: Decimal | None       # token units; None unless the balance was actually observed
    minimum_balance: Decimal | None
    observed_at: datetime | None
    policy_version: str = POLICY_VERSION

    @property
    def allowed(self) -> bool:
        return self.decision is Decision.ALLOW

    @property
    def gate_active(self) -> bool:
        return self.decision is not Decision.INACTIVE


def _result(key: str, decision: Decision, reason: str, *, policy: EntitlementPolicy | None = None,
            wallet: WalletContext | None = None, deployment=None, entitlement=None,
            evidence=None) -> ResourceAccessDecision:
    balance = None
    if evidence is not None and getattr(evidence, "balance_raw", None) is not None:
        balance = Decimal(evidence.balance_raw).scaleb(-evidence.token_decimals)
    return ResourceAccessDecision(
        resource_key=key, decision=decision, reason_code=reason,
        access_mode=policy.access_mode.value if policy else None,
        wallet_address=wallet.address if wallet else None,
        chain_id=deployment.chain_id if deployment else None,
        token_address=deployment.token_address if deployment else None,
        entitlement_state=entitlement.state.value if entitlement is not None else None,
        observed_balance=balance,
        minimum_balance=policy.minimum_balance if policy else None,
        observed_at=getattr(evidence, "observed_at", None))


def _freshness_seconds(environ: Mapping[str, str]) -> int | None:
    try:
        value = int((environ.get(FRESHNESS_ENV) or "").strip())
    except ValueError:
        return None
    return value if value > 0 else None


def _token_policy(deployment, policy: EntitlementPolicy, freshness_seconds: int):
    """Canonical FincoEntitlementPolicy for (approved deployment, resource threshold), or None if the
    threshold is finer than the token's decimals (misconfiguration, never rounded)."""
    from app.verified.token_entitlement import FincoEntitlementPolicy
    required_raw = policy.minimum_balance.scaleb(deployment.decimals)
    if required_raw != required_raw.to_integral_value():
        return None
    return FincoEntitlementPolicy(
        chain_id=deployment.chain_id, token_address=deployment.token_address,
        token_decimals=deployment.decimals, minimum_balance_raw=int(required_raw),
        freshness_seconds=freshness_seconds, provenance=deployment.provenance)


def decide_resource_access(
    resource_key: str,
    wallet: WalletContext,
    policy_set: PolicySet,
    resolution: DeploymentResolution,
    evidence,
    *,
    freshness_seconds: int | None,
    now: datetime | None = None,
) -> ResourceAccessDecision:
    """Pure decision from already-assembled inputs; the token truth comes from the canonical evaluator."""
    from app.verified.entitlement import EntitlementState
    from app.verified.token_entitlement import evaluate_token_entitlement

    now = now or datetime.now(timezone.utc)
    policy = policy_set.get(resource_key)
    if policy is None:
        return _result(resource_key, Decision.DENY, "UNKNOWN_RESOURCE", wallet=wallet)
    if policy.access_mode is AccessMode.PUBLIC:
        return _result(resource_key, Decision.ALLOW, "PUBLIC_RESOURCE", policy=policy)

    # ---- holder-gated resource ---------------------------------------------------------------------
    if policy_set.config_error:
        return _result(resource_key, Decision.DENY, "POLICY_CONFIG_INVALID", policy=policy, wallet=wallet)
    if not policy_set.gating_enabled or not policy.enabled:
        return _result(resource_key, Decision.INACTIVE,
                       "TOKEN_GATING_OFF" if not policy_set.gating_enabled else "POLICY_DISABLED",
                       policy=policy, wallet=wallet)
    if policy.minimum_balance is None:
        return _result(resource_key, Decision.DENY, "POLICY_THRESHOLD_UNSET", policy=policy, wallet=wallet)
    if policy.wallet_verified_required:
        if not wallet.address:
            return _result(resource_key, Decision.DENY, "WALLET_NOT_CONNECTED", policy=policy, wallet=wallet)
        if not wallet.verified:
            return _result(resource_key, Decision.DENY, "WALLET_NOT_VERIFIED", policy=policy, wallet=wallet)
    if not resolution.resolved:
        return _result(resource_key, Decision.DENY, resolution.reason or resolution.status.value,
                       policy=policy, wallet=wallet)
    deployment = resolution.deployment
    if freshness_seconds is None:
        return _result(resource_key, Decision.DENY, "TOKEN_CONFIGURATION_UNAVAILABLE", policy=policy,
                       wallet=wallet, deployment=deployment)
    token_policy = _token_policy(deployment, policy, freshness_seconds)
    if token_policy is None:
        return _result(resource_key, Decision.DENY, "THRESHOLD_EXCEEDS_TOKEN_DECIMALS", policy=policy,
                       wallet=wallet, deployment=deployment)

    # The canonical authority makes the token decision: exact identity, evidence state, freshness, threshold.
    entitlement = evaluate_token_entitlement(
        subject_id=wallet.subject_id or wallet.address or "", wallet_address=wallet.address,
        policy=token_policy, evidence=evidence, as_of=now)
    state = entitlement.state
    if state is EntitlementState.ACTIVE:
        decision, reason = Decision.ALLOW, "BALANCE_AT_OR_ABOVE_THRESHOLD"
    elif state is EntitlementState.INACTIVE:
        decision, reason = Decision.DENY, "BALANCE_BELOW_THRESHOLD"
    elif state is EntitlementState.STALE:
        decision, reason = Decision.DENY, "BALANCE_STALE"
    else:   # UNAVAILABLE / IDENTITY_UNAVAILABLE / TOKEN_CONFIGURATION_UNAVAILABLE: fail closed, never zero
        decision, reason = Decision.DENY, entitlement.reason or state.value
    return _result(resource_key, decision, reason, policy=policy, wallet=wallet, deployment=deployment,
                   entitlement=entitlement, evidence=evidence)


def _default_provider(deployment, policy: EntitlementPolicy, environ: Mapping[str, str]):
    """Existing read-only P4 provider for the approved deployment; RPC URL stays server-side env only."""
    from app.protocol.token_config import TokenConfig
    from app.verified.token_entitlement import P4ReadOnlyBalanceProvider
    rpc_url = (environ.get(f"FINCO_TOKEN_RPC_URL_{deployment.chain_id}") or "").strip()
    if not rpc_url:
        return None
    return P4ReadOnlyBalanceProvider(TokenConfig(
        rpc_url=rpc_url, chain_id=deployment.chain_id, token_address=deployment.token_address,
        min_balance=policy.minimum_balance, decimals_override=deployment.decimals))


async def evaluate_resource_access(
    resource_key: str,
    wallet: WalletContext,
    *,
    policy_set: PolicySet | None = None,
    provider=None,
    approved=None,
    environ: Mapping[str, str] | None = None,
    now: datetime | None = None,
) -> ResourceAccessDecision:
    """Stable entry point for Agent B/C: resource_key + wallet context -> authoritative decision.

    Callers never see JSON-RPC, deployment proof or raw evidence. ``provider`` (a canonical
    ``TokenBalanceProvider``) and ``approved`` are injection points for tests; production uses the
    existing P4 read-only provider and the live approved-deployment tuple (empty today).
    """
    env = os.environ if environ is None else environ
    policy_set = policy_set or load_policy_set(env)
    policy = policy_set.get(resource_key)
    resolution = resolve_approved_deployment(policy.chain_id if policy else None, approved)
    evidence = None
    needs_balance = (
        policy is not None and policy.access_mode is AccessMode.FINCO_HOLDER
        and not policy_set.config_error and policy_set.gating_enabled and policy.enabled
        and policy.minimum_balance is not None and bool(wallet.address)
        and (wallet.verified or not policy.wallet_verified_required)
        and resolution.resolved and _freshness_seconds(env) is not None
    )
    if needs_balance:
        deployment = resolution.deployment
        active_provider = provider or _default_provider(deployment, policy, env)
        token_policy = _token_policy(deployment, policy, _freshness_seconds(env) or 1)
        if active_provider is not None and token_policy is not None:
            try:
                evidence = await active_provider.balance_of(token_policy, wallet.address)
            except Exception:
                evidence = None                      # missing evidence is unavailable, never zero
    return decide_resource_access(resource_key, wallet, policy_set, resolution, evidence,
                                  freshness_seconds=_freshness_seconds(env), now=now)


async def evaluate_all_resources(wallet: WalletContext, **kw) -> Mapping[str, ResourceAccessDecision]:
    policy_set = kw.pop("policy_set", None) or load_policy_set(kw.get("environ"))
    return {key: await evaluate_resource_access(key, wallet, policy_set=policy_set, **kw)
            for key in policy_set.policies}
