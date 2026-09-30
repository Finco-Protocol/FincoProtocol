"""Synthetic, clearly non-production fixtures for the Model ↔ Market Bridge.

Nothing in this module represents a production binding, a production
deployment, or a VERIFIED asset.  UIDs/addresses are SYNTHETIC values used
to prove the fail-closed contract (and to back the experimental read-only
API spike).
"""
from __future__ import annotations

from datetime import datetime, timedelta, timezone

from app.model_market_bridge import (
    BindingLifecycle,
    EvidenceState,
    BindingStatus,
    BridgeRegistry,
    DeploymentIdentity,
    MarketEvidenceReference,
    ModelAssetKind,
    ModelMarketBindingV1,
    ProvenanceType,
    ReasonCode,
    BridgeDecision,
)

_CHAIN = 4663
_TOKEN = "0x" + "ab" * 20
_TOKEN_B = "0x" + "cd" * 20
_UID = "0x00000000000000000000000000000000" + "aa" * 16
_UID_B = "0x00000000000000000000000000000000" + "bb" * 16
_MODEL = "project:11111111-1111-1111-1111-111111111111"
_NOW = datetime(2026, 10, 1, 12, 0, 0, tzinfo=timezone.utc)


def _deployment(token: str = _TOKEN) -> DeploymentIdentity:
    return DeploymentIdentity(
        chain_id=_CHAIN, contract_address=token, deployment_type="TOKEN",
        venue="SYNTHETIC_VENUE", source_authority="SYNTHETIC_DEPLOYMENT_RECORD",
    )


def _binding(**overrides) -> ModelMarketBindingV1:
    fields = dict(
        model_asset_uid=_MODEL,
        model_asset_kind=ModelAssetKind.PROJECT_INSTANCE,
        economic_asset_uid=_UID,
        deployment=_deployment(),
        evidence=MarketEvidenceReference(
            authority="SYNTHETIC_MARKET_AUTHORITY",
            ref="SYNTHETIC_EVIDENCE_DIGEST_0001", observed_at=_NOW, state=EvidenceState.FRESH),
        provenance_type=ProvenanceType.CANONICAL_REGISTRY_RECORD,
        provenance_ref="synthetic-registry-entry-0001",
        status=BindingStatus.SOURCE_PROVEN,
        lifecycle=BindingLifecycle.ACTIVE,
    )
    fields.update(overrides)
    return ModelMarketBindingV1(**fields)


def build_fixture_registry() -> BridgeRegistry:
    """Fixture registry over one attested (uid, deployment) pairing.

    The pairing authority proves the exact tuple; a different economic uid
    with this deployment (or vice versa) is PAIRING_MISMATCH even though a
    second canonical uid/deployment exists in the fixture universe.
    """
    attested = {(_UID, _deployment().deployment_uid)}
    known_uids = {_UID, _UID_B}
    known_deps = {_deployment().deployment_uid, _deployment(_TOKEN_B).deployment_uid}

    def _pairing(economic_uid: str, deployment) -> ReasonCode:
        if (economic_uid, deployment.deployment_uid) in attested:
            return ReasonCode.OK
        if economic_uid in known_uids and deployment.deployment_uid in known_deps:
            return ReasonCode.PAIRING_MISMATCH
        if economic_uid not in known_uids:
            return ReasonCode.ECONOMIC_ASSET_UNKNOWN
        return ReasonCode.DEPLOYMENT_UNKNOWN

    return BridgeRegistry(
        bindings=[_binding()],
        pairing_authority=_pairing,
        evidence_state_authority=lambda binding: EvidenceState.FRESH,
    )


def evaluate_model_asset(model_asset_uid: str, *, now: datetime | None = None) -> BridgeDecision:
    """Evaluate a model asset against the fixture registry (read-only).

    The evaluation clock defaults to a fixed point just after the fixture
    evidence timestamp so the fixture decision is deterministic regardless
    of the real wall clock.
    """
    if now is None:
        now = _NOW + timedelta(seconds=30)
    registry = build_fixture_registry()
    decision = registry.evaluate_for_model_asset(model_asset_uid, now=now)
    if decision.reason is ReasonCode.MODEL_UID_UNKNOWN and model_asset_uid != _MODEL:
        return BridgeDecision(
            status=BindingStatus.UNBOUND, reason=ReasonCode.MODEL_UID_UNKNOWN,
            detail="no active binding for this model_asset_uid",
        )
    return decision
