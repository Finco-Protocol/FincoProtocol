"""Resource entitlement policy for token-gated FINCO resources (access control only).

``$FINCO`` NEVER touches the math and never decides whether evidence is true: a policy only answers
whether a verified wallet may reach a *resource_key*. Nothing here selects production amounts; every
holder-gated policy ships DISABLED with ``minimum_balance = None``.

Operator configuration (all optional; absent means everything stays inactive):
  FINCO_TOKEN_GATING_ENABLED         "1"/"true" to allow any gate to become active (default OFF)
  FINCO_ENTITLEMENT_POLICIES_JSON    {"yield.history": {"enabled": true, "minimum_balance": "...",
                                      "chain_id": 1}, ...}  (enabled / minimum_balance / chain_id only)
"""
from __future__ import annotations

import json
import os
from dataclasses import dataclass, replace
from decimal import Decimal, InvalidOperation
from enum import Enum
from typing import Mapping

POLICY_VERSION = "FINCO_ENTITLEMENT_V0"
GATING_ENABLED_ENV = "FINCO_TOKEN_GATING_ENABLED"
POLICIES_ENV = "FINCO_ENTITLEMENT_POLICIES_JSON"

# Canonical resource keys.
YIELD_BASIC = "yield.basic"
YIELD_HISTORY = "yield.history"
YIELD_ADVANCED_COMPARE = "yield.advanced_compare"
YIELD_ALERTS = "yield.alerts"
YIELD_EXECUTION_PREFLIGHT = "yield.execution_preflight"

RESOURCE_KEYS = (YIELD_BASIC, YIELD_HISTORY, YIELD_ADVANCED_COMPARE, YIELD_ALERTS,
                 YIELD_EXECUTION_PREFLIGHT)


class AccessMode(str, Enum):
    PUBLIC = "PUBLIC"
    FINCO_HOLDER = "FINCO_HOLDER"


@dataclass(frozen=True)
class EntitlementPolicy:
    resource_key: str
    access_mode: AccessMode
    minimum_balance: Decimal | None        # token units (not base units); None until tokenomics are decided
    wallet_verified_required: bool
    enabled: bool
    chain_id: int | None = None            # optional explicit deployment selector (multi-chain future)

    def __post_init__(self) -> None:
        if self.minimum_balance is not None and (
                not isinstance(self.minimum_balance, Decimal) or not self.minimum_balance.is_finite()
                or self.minimum_balance <= 0):
            raise ValueError("minimum_balance must be a positive finite Decimal or None")
        if self.access_mode is AccessMode.FINCO_HOLDER and not self.wallet_verified_required:
            # A balance belongs to a wallet; an unverified wallet proves nothing about its owner.
            raise ValueError("FINCO_HOLDER resources always require a verified wallet")
        if self.chain_id is not None and (isinstance(self.chain_id, bool) or self.chain_id <= 0):
            raise ValueError("chain_id must be a positive integer")


def default_policies() -> dict[str, EntitlementPolicy]:
    """Production defaults: yield.basic is public; every holder resource is DISABLED and unthresholded."""
    def holder(key: str) -> EntitlementPolicy:
        return EntitlementPolicy(key, AccessMode.FINCO_HOLDER, None, True, False)
    return {
        YIELD_BASIC: EntitlementPolicy(YIELD_BASIC, AccessMode.PUBLIC, None, False, True),
        YIELD_HISTORY: holder(YIELD_HISTORY),
        YIELD_ADVANCED_COMPARE: holder(YIELD_ADVANCED_COMPARE),
        YIELD_ALERTS: holder(YIELD_ALERTS),
        YIELD_EXECUTION_PREFLIGHT: holder(YIELD_EXECUTION_PREFLIGHT),   # verified wallet always required
    }


@dataclass(frozen=True)
class PolicySet:
    policies: Mapping[str, EntitlementPolicy]
    gating_enabled: bool = False
    config_error: bool = False             # operator overrides were invalid: gated resources fail closed

    def get(self, resource_key: str) -> EntitlementPolicy | None:
        return self.policies.get(resource_key)


def load_policy_set(environ: Mapping[str, str] | None = None) -> PolicySet:
    env = os.environ if environ is None else environ
    policies = default_policies()
    gating = (env.get(GATING_ENABLED_ENV) or "").strip().lower() in ("1", "true", "yes", "on")
    raw = (env.get(POLICIES_ENV) or "").strip()
    if not raw:
        return PolicySet(policies, gating)
    try:
        data = json.loads(raw)
        if not isinstance(data, dict):
            raise ValueError
        updated = dict(policies)
        for key, override in data.items():
            base = updated.get(key)
            if base is None or base.access_mode is AccessMode.PUBLIC or not isinstance(override, dict):
                raise ValueError                       # unknown key, public resource, or bad shape
            if set(override) - {"enabled", "minimum_balance", "chain_id"}:
                raise ValueError                       # only these fields are operator-configurable
            minimum = base.minimum_balance
            if override.get("minimum_balance") is not None:
                minimum = Decimal(str(override["minimum_balance"]))
            enabled = override.get("enabled", base.enabled)
            if not isinstance(enabled, bool):
                raise ValueError
            updated[key] = replace(base, enabled=enabled, minimum_balance=minimum,
                                   chain_id=override.get("chain_id", base.chain_id))
        return PolicySet(updated, gating)
    except (ValueError, InvalidOperation, TypeError):
        return PolicySet(policies, gating, config_error=True)
