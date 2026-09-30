"""Bridge registry — fail-closed evaluation of binding candidates.

The registry reuses existing authority instead of replacing it:

- **Pairing authority** (required): proves the exact source-proven tuple
  ``economic_asset_uid ↔ chain_id ↔ canonical contract`` as ONE mapping,
  read-only over existing canonical authority.  The production adapter
  (:func:`r_live_pairing_authority`) checks the existing R-LIVE approved
  policy records verbatim; tests use synthetic pairing sets.  A valid
  economic UID from asset A paired with a valid deployment from asset B is
  PAIRING_MISMATCH — never accepted because both sides exist independently.
- **Evidence state authority** (required): consumes the evidence state AS
  PRODUCED by the canonical market authority.  The bridge operates no
  generic production freshness authority of its own; synthetic/test-local
  freshness remains test-local.
- **Lifecycle**: ACTIVE / SUPERSEDED / REVOKED.  Corrections supersede;
  history is retained.  Two records sharing a binding UID but differing in
  ANY material field fail closed (IDENTITY_CONFLICT) — never a silent
  overwrite.

Conflicts fail closed.  Nothing here resolves a conflict by priority guess.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime
from typing import Callable, Sequence

from .contracts import (
    BindingLifecycle,
    BindingStatus,
    BridgeDecision,
    DeploymentIdentity,
    EvidenceState,
    ModelMarketBindingV1,
    ReasonCode,
    VerifySeamResult,
)

# Pairing authority: proves the exact tuple (economic_asset_uid, deployment)
# as one source-proven mapping.  Returns OK when attested, PAIRING_MISMATCH
# when both sides are individually canonical but not attested together, or
# ECONOMIC_ASSET_UNKNOWN / DEPLOYMENT_UNKNOWN when a side is unknown.
PairingAuthority = Callable[[str, DeploymentIdentity], ReasonCode]

# Evidence-state authority: returns the state the canonical market authority
# produced for this evidence reference (FRESH / STALE / UNAVAILABLE).
EvidenceStateAuthority = Callable[[ModelMarketBindingV1], EvidenceState]


def r_live_pairing_authority() -> PairingAuthority:
    """Read-only adapter over the existing canonical R-LIVE policy records.

    Proves the exact tuple ``economic_asset_uid ↔ chain_id ↔ contract``
    against ``APPROVED_BY_CANONICAL_ID`` verbatim.  The bridge never
    duplicates or alters R-LIVE identity logic, pool selection, freshness
    or pricing.
    """

    def _pairing(economic_asset_uid: str, deployment: DeploymentIdentity) -> ReasonCode:
        from finco_radar.authority.r_live_policy import APPROVED_BY_CANONICAL_ID

        uid_known = False
        deployment_known = False
        paired = False
        for policy in APPROVED_BY_CANONICAL_ID.values():
            key = policy.asset_key
            if policy.economic_asset_uid == economic_asset_uid:
                uid_known = True
            if (key.chain_id == deployment.chain_id
                    and str(key.contract_address).lower() == deployment.contract_address):
                deployment_known = True
            if (policy.economic_asset_uid == economic_asset_uid
                    and key.chain_id == deployment.chain_id
                    and str(key.contract_address).lower() == deployment.contract_address):
                paired = True
        if paired:
            return ReasonCode.OK
        if uid_known and deployment_known:
            # Both sides individually canonical, but the canonical authority
            # does not attest them as one pairing -> fail closed.
            return ReasonCode.PAIRING_MISMATCH
        if not uid_known:
            return ReasonCode.ECONOMIC_ASSET_UNKNOWN
        return ReasonCode.DEPLOYMENT_UNKNOWN

    return _pairing


def constant_evidence_state_authority(state: EvidenceState) -> EvidenceStateAuthority:
    """Test-local evidence-state authority (synthetic freshness stays synthetic)."""
    return lambda binding: state


@dataclass(frozen=True)
class BridgeRegistry:
    """Fail-closed registry over an immutable set of binding records."""

    bindings: Sequence[ModelMarketBindingV1]
    pairing_authority: PairingAuthority
    evidence_state_authority: EvidenceStateAuthority
    _by_uid: dict = field(default_factory=dict, init=False)

    def __post_init__(self) -> None:
        index: dict[str, ModelMarketBindingV1] = {}
        deployments: dict[str, set[str]] = {}
        for binding in self.bindings:
            uid = binding.binding_uid
            existing = index.get(uid)
            if existing is not None:
                # Deterministic identity: the same canonical binding identity
                # must carry the same material payload.  Any material
                # disagreement (identity, evidence, provenance, status or
                # lifecycle) fails closed — never a silent overwrite.
                if existing._material_fields() != binding._material_fields():
                    raise ValueError(
                        f"IDENTITY_CONFLICT: duplicate canonical binding {uid} "
                        "with materially conflicting records"
                    )
                continue
            index[uid] = binding
            deployments.setdefault(binding.deployment.deployment_uid, set()).add(
                binding.economic_asset_uid)
        # A deployment source-proven bound to two different economic assets
        # is a DEPLOYMENT_CONFLICT — fail closed rather than picking a
        # winner.  (Several deployments per economic asset are fine; one
        # deployment silently serving two economic identities is not.)
        for dep_uid, economic_uids in deployments.items():
            active_uids = {
                b.economic_asset_uid
                for b in self.bindings
                if b.deployment.deployment_uid == dep_uid
                and b.lifecycle is BindingLifecycle.ACTIVE
                and b.status is BindingStatus.SOURCE_PROVEN
            }
            if len(active_uids) > 1:
                raise ValueError(
                    f"DEPLOYMENT_CONFLICT: deployment {dep_uid} is source-proven "
                    f"bound to multiple economic assets: {sorted(active_uids)}"
                )
        object.__setattr__(self, "_by_uid", index)

    # ── lookups ───────────────────────────────────────────────────────────

    def get_by_uid(self, binding_uid: str) -> ModelMarketBindingV1 | None:
        return self._by_uid.get(binding_uid)

    def bindings_for_model_asset(self, model_asset_uid: str) -> tuple[ModelMarketBindingV1, ...]:
        return tuple(
            b for b in self.bindings
            if b.model_asset_uid == model_asset_uid
            and b.lifecycle is BindingLifecycle.ACTIVE
        )

    # ── evaluation ────────────────────────────────────────────────────────

    def evaluate(
        self,
        binding: ModelMarketBindingV1,
        *,
        now: datetime | None = None,
    ) -> BridgeDecision:
        """Evaluate one binding candidate.  Fail-closed at every step.

        ``now`` is accepted for interface compatibility; freshness comes
        from the evidence-state authority, not from a local age computation.
        """
        del now  # freshness authority owns evidence state; no local aging
        uid = binding.binding_uid
        record = self._by_uid.get(uid)

        # Registry lifecycle first: revoked/superseded records are unusable
        # or historical-only.
        if record is not None:
            if record.lifecycle is BindingLifecycle.REVOKED:
                return BridgeDecision(
                    status=BindingStatus.REVOKED, reason=ReasonCode.BINDING_REVOKED,
                    binding_uid=uid, lifecycle=record.lifecycle,
                    detail="binding has been revoked",
                )
            if record.lifecycle is BindingLifecycle.SUPERSEDED:
                return BridgeDecision(
                    status=record.status, reason=ReasonCode.BINDING_SUPERSEDED,
                    binding_uid=uid, lifecycle=record.lifecycle,
                    detail="binding has been superseded; historical evidence only",
                )

        if binding.lifecycle is BindingLifecycle.REVOKED:
            return BridgeDecision(
                status=BindingStatus.REVOKED, reason=ReasonCode.BINDING_REVOKED,
                binding_uid=uid, lifecycle=binding.lifecycle,
                detail="binding has been revoked",
            )

        # Evidence availability: an absent reference is UNAVAILABLE even
        # before the market authority's state is consulted.
        if not binding.evidence.ref.strip():
            return BridgeDecision(
                status=BindingStatus.UNBOUND, reason=ReasonCode.EVIDENCE_UNAVAILABLE,
                binding_uid=uid, lifecycle=binding.lifecycle,
                detail="no market evidence reference present",
            )

        # The exact tuple (economic_asset_uid ↔ deployment) must be attested
        # by the canonical pairing authority as ONE source-proven mapping.
        pairing = self.pairing_authority(binding.economic_asset_uid, binding.deployment)
        if pairing is not ReasonCode.OK:
            return BridgeDecision(
                status=BindingStatus.UNBOUND, reason=pairing,
                binding_uid=uid, lifecycle=binding.lifecycle,
                detail="canonical authority does not attest this economic_asset_uid "
                       "↔ deployment pairing",
            )

        # Provenance must be present and source-proven; a CANDIDATE without
        # accepted provenance stays a candidate.
        if binding.status is not BindingStatus.SOURCE_PROVEN:
            return BridgeDecision(
                status=binding.status, reason=ReasonCode.BINDING_NOT_SOURCE_PROVEN,
                binding_uid=uid, lifecycle=binding.lifecycle,
                detail="binding provenance is not yet source-proven",
            )

        # Evidence state: consumed from the canonical market authority.
        state = self.evidence_state_authority(binding)
        if state is EvidenceState.UNAVAILABLE:
            return BridgeDecision(
                status=BindingStatus.UNBOUND, reason=ReasonCode.EVIDENCE_UNAVAILABLE,
                binding_uid=uid, lifecycle=binding.lifecycle,
                evidence_state=state,
                detail="market authority reports the evidence unavailable",
            )
        if state is EvidenceState.STALE:
            return BridgeDecision(
                status=BindingStatus.STALE, reason=ReasonCode.EVIDENCE_STALE,
                binding_uid=uid, lifecycle=binding.lifecycle,
                evidence_state=state,
                detail="market authority reports the evidence stale; "
                       "it remains evidence of past state only",
            )

        return BridgeDecision(
            status=BindingStatus.SOURCE_PROVEN, reason=ReasonCode.OK,
            binding_uid=uid, lifecycle=binding.lifecycle,
            evidence_state=EvidenceState.FRESH,
            detail="source-proven binding with fresh canonical market evidence",
        )

    def evaluate_for_model_asset(
        self, model_asset_uid: str, *, now: datetime | None = None
    ) -> BridgeDecision:
        """Evaluate the active binding(s) of a Model asset.  Fail-closed."""
        del now  # freshness authority owns evidence state; no local aging
        active = self.bindings_for_model_asset(model_asset_uid)
        if not active:
            return BridgeDecision(
                status=BindingStatus.UNBOUND, reason=ReasonCode.MODEL_UID_UNKNOWN,
                detail="no active binding for this model_asset_uid",
            )
        decisions = [self.evaluate(b) for b in active]
        proven = [d for d in decisions if d.ok]
        if len(proven) > 1:
            return BridgeDecision(
                status=BindingStatus.UNBOUND, reason=ReasonCode.IDENTITY_CONFLICT,
                detail="multiple active source-proven bindings for one model asset",
            )
        if len(proven) == 1:
            return proven[0]
        # No proven binding: surface the least-availability decision, with
        # conflicts taking precedence over single failures.
        conflict = next(
            (d for d in decisions if d.reason in (
                ReasonCode.IDENTITY_CONFLICT, ReasonCode.DEPLOYMENT_CONFLICT)),
            None,
        )
        if conflict is not None:
            return conflict
        return decisions[0]

    # ── future FINCO Verify seam (designed, never activated) ─────────────

    def verify_evaluation_seam(
        self, binding: ModelMarketBindingV1, *, now: datetime | None = None
    ) -> VerifySeamResult:
        """Bridge-side preconditions for a *future* FINCO Verify evaluation.

        This is an interface boundary only.  It never calls Verify mutation
        logic, never increments counts, and never creates VERIFIED records.
        """
        decision = self.evaluate(binding, now=now)
        preconditions = {
            "binding_status": decision.status.value,
            "binding_lifecycle": decision.lifecycle.value,
            "reason": decision.reason.value,
            "evidence_state": decision.evidence_state.value,
            "provenance_type": binding.provenance_type.value,
            "provenance_ref": binding.provenance_ref,
        }
        eligible = decision.ok
        return VerifySeamResult(
            eligible_for_verify_evaluation=eligible,
            preconditions=preconditions,
        )


def bridge_registry_from_bindings(
    bindings: Sequence[ModelMarketBindingV1],
    *,
    pairing_authority: PairingAuthority,
    evidence_state_authority: EvidenceStateAuthority,
) -> BridgeRegistry:
    """Convenience constructor."""
    return BridgeRegistry(
        bindings=list(bindings),
        pairing_authority=pairing_authority,
        evidence_state_authority=evidence_state_authority,
    )
