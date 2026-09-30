"""FINCO Model ↔ Market Bridge V1 — typed identity and evidence-binding contract.

Establishes the deterministic, source-proven identity bridge:

    MODEL ASSET  →  economic_asset_uid  →  deployment identity
                 →  canonical market evidence

This is identity/evidence infrastructure ONLY.  It never changes financial
calculations, never creates a second market-price authority, and never
promotes anything to FINCO Verify.  ``PRODUCTION_VERIFIED_ASSET_COUNT``
stays untouched: a SOURCE_PROVEN binding is a *candidate* for future Verify
evaluation, never a VERIFIED asset.

Hard identity rule: a binding must be explicit and source-proven.  Display
metadata (tickers, symbols, labels) is never binding authority, no heuristic
or approximate resolution exists, and UNKNOWN stays UNKNOWN.  Conflicts
fail closed.

Schema (frozen for V1): ``MODEL_MARKET_BINDING_V1``.
"""
from __future__ import annotations

from .contracts import (
    BINDING_SCHEMA_VERSION,
    MODEL_MARKET_BINDING_V1,
    BindingLifecycle,
    BindingStatus,
    BridgeDecision,
    DeploymentIdentity,
    EconomicAssetIdentity,
    EvidenceState,
    IdentityLayer,
    MarketEvidenceReference,
    ModelAssetIdentity,
    ModelAssetKind,
    ModelMarketBindingV1,
    ProvenanceType,
    ReasonCode,
    VerifySeamResult,
    binding_uid_for,
    deployment_uid_for,
    model_asset_uid_for_project,
    model_asset_uid_for_reference,
)
from .registry import (
    BridgeRegistry,
    DeploymentAuthority,
    bridge_registry_from_bindings,
    r_live_deployment_authority,
)

__all__ = [
    "BINDING_SCHEMA_VERSION",
    "MODEL_MARKET_BINDING_V1",
    "BindingLifecycle",
    "BindingStatus",
    "BridgeDecision",
    "BridgeRegistry",
    "DeploymentAuthority",
    "DeploymentIdentity",
    "EconomicAssetIdentity",
    "EvidenceState",
    "IdentityLayer",
    "MarketEvidenceReference",
    "ModelAssetIdentity",
    "ModelAssetKind",
    "ModelMarketBindingV1",
    "ProvenanceType",
    "ReasonCode",
    "VerifySeamResult",
    "binding_uid_for",
    "bridge_registry_from_bindings",
    "deployment_uid_for",
    "model_asset_uid_for_project",
    "model_asset_uid_for_reference",
    "r_live_deployment_authority",
]
