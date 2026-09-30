"""Typed V1 contracts for the Model ↔ Market Bridge.

Identity layers are deliberately separate — MODEL IDENTITY ≠ ECONOMIC ASSET
IDENTITY ≠ MARKET DEPLOYMENT ≠ MARKET OBSERVATION:

- :class:`ModelAssetIdentity` — the Model-side subject (a project instance or
  a canonical reference model).  Never derived from display names.
- :class:`EconomicAssetIdentity` — the canonical economic identity layer
  (``economic_asset_uid``).  Reused from existing authority where present
  (R-LIVE / Verify use the same identifier namespace); the bridge never
  mints competing economic identities.
- :class:`DeploymentIdentity` — one concrete on-chain deployment of an
  economic asset (chain + canonical contract).  One economic asset may have
  many deployments; the economic uid therefore never equals a deployment.
- :class:`MarketEvidenceReference` — a pointer to canonical market evidence
  (authority name + reference + observation time).  The bridge references
  evidence; it never recalculates market prices.

Binding lifecycle and evidence state are orthogonal: a binding may be
ACTIVE while its evidence is STALE (stale evidence stays evidence of past
state and never becomes current identity authority).
"""
from __future__ import annotations

import hashlib
import json
from dataclasses import dataclass, field
from datetime import datetime, timezone
from enum import Enum

BINDING_SCHEMA_VERSION = "MODEL_MARKET_BINDING_V1"
# Stable schema alias (kept short for serialization surfaces).
MODEL_MARKET_BINDING_V1 = "model_market_binding_v1"


class IdentityLayer(str, Enum):
    """The four identity layers the bridge keeps separate."""

    MODEL = "MODEL"
    ECONOMIC_ASSET = "ECONOMIC_ASSET"
    DEPLOYMENT = "DEPLOYMENT"
    MARKET_OBSERVATION = "MARKET_OBSERVATION"


class ModelAssetKind(str, Enum):
    """What exactly a Model-side UID identifies.  Never blurred."""

    PROJECT_INSTANCE = "PROJECT_INSTANCE"      # one user-owned project
    REFERENCE_MODEL = "REFERENCE_MODEL"        # one canonical reference template


class ProvenanceType(str, Enum):
    """Acceptable binding provenance.  Each value is referenceable/auditable.

    Deliberately closed: there is no member for display-metadata resemblance scoring,
    heuristic matching, search-engine claims or machine inference, and none
    may be added without a contract change.
    """

    ISSUER_DOCUMENT = "ISSUER_DOCUMENT"                    # immutable issuer/source document
    CANONICAL_REGISTRY_RECORD = "CANONICAL_REGISTRY_RECORD"  # canonical registry entry
    DEPLOYMENT_RECORD = "DEPLOYMENT_RECORD"                # explicit deployment record
    CONTROLLED_METADATA = "CONTROLLED_METADATA"            # signed/controlled project metadata
    REVIEWED_EVIDENCE_PACKAGE = "REVIEWED_EVIDENCE_PACKAGE"  # reviewed evidence package


class BindingStatus(str, Enum):
    """Evaluation status of a binding candidate (evidence-facing)."""

    UNBOUND = "UNBOUND"                    # no binding exists
    CANDIDATE = "CANDIDATE"                # structurally valid, not yet source-proven
    SOURCE_PROVEN = "SOURCE_PROVEN"        # explicit auditable provenance accepted
    STALE = "STALE"                        # evidence past its freshness window
    REVOKED = "REVOKED"                    # unusable


class BindingLifecycle(str, Enum):
    """Registry lifecycle of a binding record (history-facing).

    Corrections supersede; history is never silently rewritten.
    """

    ACTIVE = "ACTIVE"
    SUPERSEDED = "SUPERSEDED"
    REVOKED = "REVOKED"


class EvidenceState(str, Enum):
    """Freshness state of the referenced market evidence."""

    FRESH = "FRESH"
    STALE = "STALE"
    UNAVAILABLE = "UNAVAILABLE"


class ReasonCode(str, Enum):
    """Typed fail-closed reasons.  Conflicts are never resolved by guess."""

    OK = "OK"
    MODEL_UID_UNKNOWN = "MODEL_UID_UNKNOWN"
    ECONOMIC_ASSET_UNKNOWN = "ECONOMIC_ASSET_UNKNOWN"
    DEPLOYMENT_UNKNOWN = "DEPLOYMENT_UNKNOWN"
    BINDING_NOT_SOURCE_PROVEN = "BINDING_NOT_SOURCE_PROVEN"
    IDENTITY_CONFLICT = "IDENTITY_CONFLICT"
    DEPLOYMENT_CONFLICT = "DEPLOYMENT_CONFLICT"
    EVIDENCE_UNAVAILABLE = "EVIDENCE_UNAVAILABLE"
    EVIDENCE_STALE = "EVIDENCE_STALE"
    BINDING_REVOKED = "BINDING_REVOKED"
    BINDING_SUPERSEDED = "BINDING_SUPERSEDED"
    MALFORMED_BINDING = "MALFORMED_BINDING"


def _utcnow() -> datetime:
    return datetime.now(timezone.utc)


def _require_tzaware(name: str, value: datetime) -> None:
    if value.tzinfo is None or value.utcoffset() is None:
        raise ValueError(f"{name} must be timezone-aware")


def model_asset_uid_for_project(project_id: str) -> str:
    """Stable Model-side UID for one user-owned project instance."""
    pid = (project_id or "").strip()
    if not pid:
        raise ValueError("project_id is required")
    return f"project:{pid}"


def model_asset_uid_for_reference(template_source: str) -> str:
    """Stable Model-side UID for one canonical reference model template."""
    src = (template_source or "").strip().lower()
    if not src:
        raise ValueError("template_source is required")
    return f"reference:{src}"


@dataclass(frozen=True)
class ModelAssetIdentity:
    """Model-side subject of a binding.

    ``model_asset_uid`` is an immutable/stable identifier (see the
    ``model_asset_uid_for_*`` helpers); display names are metadata only and
    are never part of binding identity.
    """

    model_asset_uid: str
    kind: ModelAssetKind
    display_name: str = ""  # metadata only — never used to establish identity

    def __post_init__(self) -> None:
        if not self.model_asset_uid or ":" not in self.model_asset_uid:
            raise ValueError("model_asset_uid must be a stable '<kind-scope>:<id>' identifier")
        if not isinstance(self.kind, ModelAssetKind):
            raise ValueError("kind must be a ModelAssetKind")


@dataclass(frozen=True)
class EconomicAssetIdentity:
    """Canonical economic identity layer.

    ``economic_asset_uid`` must come from existing authority (for example the
    reviewed R-LIVE / Verify namespace).  The bridge reuses it verbatim and
    never mints competing economic identities.
    """

    economic_asset_uid: str

    def __post_init__(self) -> None:
        uid = (self.economic_asset_uid or "").strip()
        if not uid:
            raise ValueError("economic_asset_uid is required")
        object.__setattr__(self, "economic_asset_uid", uid)


def _canonical_address(value: str) -> str:
    addr = (value or "").strip()
    if not addr.startswith("0x") or any(c not in "0123456789abcdefABCDEF" for c in addr[2:]):
        raise ValueError("contract address must be a hex 0x address")
    return addr.lower()


@dataclass(frozen=True)
class DeploymentIdentity:
    """One concrete deployment of an economic asset.

    ``deployment_uid`` is deterministic from chain + canonical contract; the
    same deployment always yields the same UID, a different deployment a
    different UID.
    """

    chain_id: int
    contract_address: str
    deployment_type: str = "TOKEN"           # TOKEN / POOL / WRAPPER / ...
    venue: str = ""                          # protocol/venue where relevant
    source_authority: str = ""               # which authority attests this deployment

    def __post_init__(self) -> None:
        if not isinstance(self.chain_id, int) or self.chain_id <= 0:
            raise ValueError("chain_id must be a positive integer")
        object.__setattr__(self, "contract_address", _canonical_address(self.contract_address))
        if not self.deployment_type.strip():
            raise ValueError("deployment_type is required")

    @property
    def deployment_uid(self) -> str:
        return deployment_uid_for(self.chain_id, self.contract_address)


def deployment_uid_for(chain_id: int, contract_address: str) -> str:
    """Deterministic deployment UID from canonical immutable identity fields."""
    canonical = f"{int(chain_id)}:{_canonical_address(contract_address)}"
    return "dep_" + hashlib.sha256(canonical.encode("utf-8")).hexdigest()[:32]


@dataclass(frozen=True)
class MarketEvidenceReference:
    """Reference to canonical market evidence — never a recalculation."""

    authority: str                    # e.g. the canonical market authority name
    ref: str                          # authority-specific reference/digest
    observed_at: datetime

    def __post_init__(self) -> None:
        if not self.authority.strip():
            raise ValueError("evidence authority is required")
        if not self.ref.strip():
            raise ValueError("evidence ref is required")
        _require_tzaware("observed_at", self.observed_at)


@dataclass(frozen=True)
class ModelMarketBindingV1:
    """Frozen V1 binding contract (``MODEL_MARKET_BINDING_V1``).

    One binding asserts: *this Model asset is source-proven to correspond to
    this economic asset on this deployment, per this evidence.*  It is never,
    by itself, a FINCO Verify result.
    """

    model_asset_uid: str
    model_asset_kind: ModelAssetKind
    economic_asset_uid: str
    deployment: DeploymentIdentity
    evidence: MarketEvidenceReference
    provenance_type: ProvenanceType
    provenance_ref: str
    status: BindingStatus = BindingStatus.CANDIDATE
    lifecycle: BindingLifecycle = BindingLifecycle.ACTIVE
    supersedes_binding_uid: str = ""
    created_at: datetime = field(default_factory=_utcnow)
    schema_version: str = MODEL_MARKET_BINDING_V1

    def __post_init__(self) -> None:
        if not self.model_asset_uid or ":" not in self.model_asset_uid:
            raise ValueError("model_asset_uid must be a stable '<scope>:<id>' identifier")
        if not isinstance(self.model_asset_kind, ModelAssetKind):
            raise ValueError("model_asset_kind must be a ModelAssetKind")
        if not isinstance(self.provenance_type, ProvenanceType):
            raise ValueError("provenance_type must be a ProvenanceType member")
        if not self.provenance_ref.strip():
            raise ValueError("provenance_ref is required (provenance must be auditable)")
        if not isinstance(self.status, BindingStatus):
            raise ValueError("status must be a BindingStatus")
        if not isinstance(self.lifecycle, BindingLifecycle):
            raise ValueError("lifecycle must be a BindingLifecycle")
        _require_tzaware("created_at", self.created_at)
        # supersedes_binding_uid is carried by a record that REPLACES an
        # earlier one (directional: "this record supersedes <uid>").  A record
        # marked lifecycle=SUPERSEDED is the historical record that was
        # replaced; it is retained for audit and never silently rewritten.

    @property
    def binding_uid(self) -> str:
        """Deterministic UID from canonical immutable identity fields only."""
        return binding_uid_for(
            model_asset_uid=self.model_asset_uid,
            model_asset_kind=self.model_asset_kind,
            economic_asset_uid=self.economic_asset_uid,
            deployment_uid=self.deployment.deployment_uid,
            schema_version=self.schema_version,
        )


def binding_uid_for(
    *,
    model_asset_uid: str,
    model_asset_kind: ModelAssetKind,
    economic_asset_uid: str,
    deployment_uid: str,
    schema_version: str = MODEL_MARKET_BINDING_V1,
) -> str:
    """Deterministic binding UID.

    Canonical JSON serialization of the immutable identity fields only — no
    display metadata, no timestamps, no statuses.  Same canonical identity →
    same UID; different deployment → different UID.
    """
    payload = json.dumps(
        {
            "schema": schema_version,
            "model_asset_uid": model_asset_uid,
            "model_asset_kind": model_asset_kind.value,
            "economic_asset_uid": economic_asset_uid.strip().lower(),
            "deployment_uid": deployment_uid,
        },
        sort_keys=True,
        separators=(",", ":"),
        ensure_ascii=True,
    )
    return "bnd_" + hashlib.sha256(payload.encode("utf-8")).hexdigest()[:40]


@dataclass(frozen=True)
class BridgeDecision:
    """Typed, fail-closed evaluation outcome."""

    status: BindingStatus
    reason: ReasonCode
    binding_uid: str = ""
    lifecycle: BindingLifecycle = BindingLifecycle.ACTIVE
    evidence_state: EvidenceState = EvidenceState.UNAVAILABLE
    detail: str = ""

    @property
    def ok(self) -> bool:
        return self.reason is ReasonCode.OK and self.status is BindingStatus.SOURCE_PROVEN


@dataclass(frozen=True)
class VerifySeamResult:
    """The future FINCO Verify seam — designed, never activated here.

    ``eligible_for_verify_evaluation`` means the binding meets the bridge-side
    preconditions (SOURCE_PROVEN, ACTIVE, FRESH evidence).  Eligibility is
    *not* verification: FINCO Verify may still require additional evidence,
    and this module never calls Verify mutation logic, never increments
    counts, and never creates VERIFIED records.
    """

    eligible_for_verify_evaluation: bool
    preconditions: dict
    note: str = (
        "Eligibility is not verification. FINCO Verify applies its own "
        "source-attested evidence requirements; PRODUCTION_VERIFIED_ASSET_COUNT "
        "is unchanged by this bridge."
    )
