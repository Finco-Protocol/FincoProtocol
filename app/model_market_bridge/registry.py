"""Bridge registry — fail-closed evaluation of binding candidates.

The registry reuses existing authority instead of replacing it:

- Deployment knowledge is pluggable (:class:`DeploymentAuthority`).  The
  production adapter (:func:`r_live_deployment_authority`) reads the existing
  canonical R-LIVE approved registry read-only; tests use synthetic
  authorities.  A deployment the authority does not know is DEPLOYMENT_UNKNOWN
  — never guessed.
- Economic-asset knowledge is the same: the caller supplies the canonical
  economic identity namespace (for example the reviewed R-LIVE uid set); an
  unknown uid is ECONOMIC_ASSET_UNKNOWN.

Conflicts fail closed.  Two authoritative-looking records that disagree
about an identity mapping produce typed conflicts (IDENTITY_CONFLICT /
DEPLOYMENT_CONFLICT), never a priority guess.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime, timedelta
from typing import Callable, Mapping, Sequence

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

# A deployment authority answers: is this exact deployment known/attested?
# Read-only lookup only — it must never derive identity from display data.
DeploymentAuthority = Callable[[DeploymentIdentity], bool]

# An economic-asset authority answers: is this exact economic_asset_uid known?
EconomicAssetAuthority = Callable[[str], bool]


def r_live_deployment_authority() -> DeploymentAuthority:
    """Read-only adapter over the existing canonical R-LIVE approved registry.

    Reuses ``finco_radar.authority.r_live_policy.APPROVED_BY_CANONICAL_ID``
    verbatim — the bridge never duplicates or alters R-LIVE identity logic,
    pool selection, freshness or pricing.  Deployment knowledge here means
    "this exact (chain, contract) deployment is reviewed", nothing more.
    """

    def _known(deployment: DeploymentIdentity) -> bool:
        from finco_radar.authority.r_live_policy import APPROVED_BY_CANONICAL_ID

        for policy in APPROVED_BY_CANONICAL_ID.values():
            key = policy.asset_key
            if key.chain_id == deployment.chain_id and (
                str(key.contract_address).lower() == deployment.contract_address
            ):
                return True
        return False

    return _known


@dataclass(frozen=True)
class BridgeRegistry:
    """Fail-closed registry over an immutable set of binding records."""

    bindings: Sequence[ModelMarketBindingV1]
    deployment_known: DeploymentAuthority
    economic_asset_known: EconomicAssetAuthority
    max_evidence_age_seconds: int = 3600
    _by_uid: dict = field(default_factory=dict, init=False)

    def __post_init__(self) -> None:
        index: dict[str, ModelMarketBindingV1] = {}
        deployments: dict[tuple[str, str], set[str]] = {}
        for binding in self.bindings:
            uid = binding.binding_uid
            existing = index.get(uid)
            if existing is not None:
                # Deterministic identity: the same canonical binding identity
                # must carry the same payload.  Any disagreement on the
                # identity fields is an IDENTITY_CONFLICT.
                if (
                    existing.economic_asset_uid != binding.economic_asset_uid
                    or existing.model_asset_uid != binding.model_asset_uid
                    or existing.deployment.deployment_uid != binding.deployment.deployment_uid
                ):
                    raise ValueError(
                        f"IDENTITY_CONFLICT: duplicate canonical binding {uid} "
                        "with differing identity fields"
                    )
                continue
            index[uid] = binding
            dep_key = (binding.economic_asset_uid, binding.deployment.deployment_uid)
            deployments.setdefault(dep_key, set()).add(binding.model_asset_uid)
        # A deployment attested to two different model assets under two
        # different economic assets is a DEPLOYMENT_CONFLICT — fail closed
        # rather than picking a winner.  (Several deployments per economic
        # asset are fine; one deployment silently serving two economic
        # identities is not.)
        for (_uid, _dep), models in deployments.items():
            economic_uids = {
                b.economic_asset_uid
                for b in self.bindings
                if b.deployment.deployment_uid == _dep
                and b.lifecycle is BindingLifecycle.ACTIVE
                and b.status is BindingStatus.SOURCE_PROVEN
            }
            if len(economic_uids) > 1:
                raise ValueError(
                    f"DEPLOYMENT_CONFLICT: deployment {_dep} is source-proven "
                    f"bound to multiple economic assets: {sorted(economic_uids)}"
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
        now: datetime,
    ) -> BridgeDecision:
        """Evaluate one binding candidate.  Fail-closed at every step."""
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
        # before freshness is considered.
        if not binding.evidence.ref.strip():
            return BridgeDecision(
                status=BindingStatus.UNBOUND, reason=ReasonCode.EVIDENCE_UNAVAILABLE,
                binding_uid=uid, lifecycle=binding.lifecycle,
                detail="no market evidence reference present",
            )

        # Deployment must be known to the canonical deployment authority.
        if not self.deployment_known(binding.deployment):
            return BridgeDecision(
                status=BindingStatus.UNBOUND, reason=ReasonCode.DEPLOYMENT_UNKNOWN,
                binding_uid=uid, lifecycle=binding.lifecycle,
                detail="deployment is not attested by the canonical deployment authority",
            )

        # Economic asset must exist in the canonical economic namespace.
        if not self.economic_asset_known(binding.economic_asset_uid):
            return BridgeDecision(
                status=BindingStatus.UNBOUND, reason=ReasonCode.ECONOMIC_ASSET_UNKNOWN,
                binding_uid=uid, lifecycle=binding.lifecycle,
                detail="economic_asset_uid is not present in the canonical economic namespace",
            )

        # Provenance must be present and source-proven; a CANDIDATE without
        # accepted provenance stays a candidate.
        if binding.status is not BindingStatus.SOURCE_PROVEN:
            return BridgeDecision(
                status=binding.status, reason=ReasonCode.BINDING_NOT_SOURCE_PROVEN,
                binding_uid=uid, lifecycle=binding.lifecycle,
                detail="binding provenance is not yet source-proven",
            )

        # Freshness last: stale evidence remains evidence of past state and is
        # typed as STALE — it never silently becomes current authority.
        age = (now - binding.evidence.observed_at).total_seconds()
        if age < 0:
            return BridgeDecision(
                status=BindingStatus.UNBOUND, reason=ReasonCode.MALFORMED_BINDING,
                binding_uid=uid, lifecycle=binding.lifecycle,
                detail="evidence observed_at is in the future",
            )
        if age > self.max_evidence_age_seconds:
            return BridgeDecision(
                status=BindingStatus.STALE, reason=ReasonCode.EVIDENCE_STALE,
                binding_uid=uid, lifecycle=binding.lifecycle,
                evidence_state=EvidenceState.STALE,
                detail="evidence is past the configured freshness window",
            )

        return BridgeDecision(
            status=BindingStatus.SOURCE_PROVEN, reason=ReasonCode.OK,
            binding_uid=uid, lifecycle=binding.lifecycle,
            evidence_state=EvidenceState.FRESH,
            detail="source-proven binding with fresh canonical market evidence",
        )

    def evaluate_for_model_asset(
        self, model_asset_uid: str, *, now: datetime
    ) -> BridgeDecision:
        """Evaluate the active binding(s) of a Model asset.  Fail-closed."""
        active = self.bindings_for_model_asset(model_asset_uid)
        if not active:
            return BridgeDecision(
                status=BindingStatus.UNBOUND, reason=ReasonCode.MODEL_UID_UNKNOWN,
                detail="no active binding for this model_asset_uid",
            )
        decisions = [self.evaluate(b, now=now) for b in active]
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
        self, binding: ModelMarketBindingV1, *, now: datetime
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
    deployment_known: DeploymentAuthority,
    economic_asset_known: EconomicAssetAuthority,
    max_evidence_age_seconds: int = 3600,
) -> BridgeRegistry:
    """Convenience constructor."""
    return BridgeRegistry(
        bindings=list(bindings),
        deployment_known=deployment_known,
        economic_asset_known=economic_asset_known,
        max_evidence_age_seconds=max_evidence_age_seconds,
    )
