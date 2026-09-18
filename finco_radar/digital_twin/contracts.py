"""Typed immutable contracts for FINCO Radar R12 — DIGITAL TWIN AUTHORITY.

Schema ``radar-r12-digital-twin-v1``.  R12 constructs a deterministic,
typed state representation from independently verified R11 evidence.

A verified Digital Twin is a deterministic representation of verified
evidence.  It is NOT a statement that the underlying economic assumptions
or market observations are objectively true.

Deep immutability from initial implementation.
"""
from __future__ import annotations

import hashlib
import json
from dataclasses import dataclass, field
from datetime import datetime
from enum import Enum
from types import MappingProxyType
from typing import Any, Mapping

SCHEMA_VERSION = "radar-r12-digital-twin-v1"
PHASE = "R12"

# What R11 verified against (the R0-R10 freeze anchor)
R11_VERIFIED_ANCHOR = "7ffaf3b1e67dabb728314948e2a4e4c7ef30047a"
R11_VERIFIED_TREE = "fba9d76d9dceee35d079563b115fdde90c40bd46"
# The R0-R11 freeze anchor (the R11 merge commit that R12 builds from)
R11_FREEZE_ANCHOR = "97030e6164b66dc942c9d005a1f2f4ba169ca81b"
R11_FREEZE_TREE = "348fa9bd465bdf0e8c5b2a1b22d0f65ba8cef37a"


class DigitalTwinStatus(str, Enum):
    DIGITAL_TWIN_OK = "DIGITAL_TWIN_OK"
    DIGITAL_TWIN_PARTIAL = "DIGITAL_TWIN_PARTIAL"
    DIGITAL_TWIN_INPUT_INVALID = "DIGITAL_TWIN_INPUT_INVALID"
    DIGITAL_TWIN_EVIDENCE_MISMATCH = "DIGITAL_TWIN_EVIDENCE_MISMATCH"
    DIGITAL_TWIN_VERIFICATION_REJECTED = "DIGITAL_TWIN_VERIFICATION_REJECTED"


class TwinGapKind(str, Enum):
    R11_EVIDENCE_UNAVAILABLE = "R11_EVIDENCE_UNAVAILABLE"
    R11_DIGEST_MISMATCH = "R11_DIGEST_MISMATCH"
    R11_VERIFICATION_NOT_OK = "R11_VERIFICATION_NOT_OK"
    TWIN_IDENTITY_MISMATCH = "TWIN_IDENTITY_MISMATCH"
    FREEZE_IDENTITY_MISMATCH = "FREEZE_IDENTITY_MISMATCH"
    MODEL_COMPONENT_UNAVAILABLE = "MODEL_COMPONENT_UNAVAILABLE"
    REFERENCE_COMPONENT_UNAVAILABLE = "REFERENCE_COMPONENT_UNAVAILABLE"
    EXECUTION_COMPONENT_UNAVAILABLE = "EXECUTION_COMPONENT_UNAVAILABLE"
    DEPLOYMENT_COMPONENT_UNAVAILABLE = "DEPLOYMENT_COMPONENT_UNAVAILABLE"
    TWIN_STATE_INCOMPLETE = "TWIN_STATE_INCOMPLETE"


class ComponentState(str, Enum):
    AVAILABLE = "AVAILABLE"
    UNAVAILABLE = "UNAVAILABLE"
    NOT_APPLICABLE = "NOT_APPLICABLE"


class ComponentId(str, Enum):
    IDENTITY_GRAPH = "IDENTITY_GRAPH"
    DEPLOYMENT_STATE = "DEPLOYMENT_STATE"
    REFERENCE_STATE = "REFERENCE_STATE"
    EXECUTION_STATE = "EXECUTION_STATE"
    MODEL_STATE = "MODEL_STATE"
    VERIFICATION_STATE = "VERIFICATION_STATE"


R12_BOUNDARIES = {
    "modelAuthority": "R10_APPLIED",
    "verificationAuthority": "R11_APPLIED",
    "digitalTwinAuthority": "R12_APPLIED",
}


class TwinError(ValueError):
    def __init__(self, message: str,
                 status: DigitalTwinStatus = DigitalTwinStatus.DIGITAL_TWIN_INPUT_INVALID):
        super().__init__(message)
        self.status = status


def canonical_json_bytes(payload: Any) -> bytes:
    return json.dumps(payload, sort_keys=True, separators=(",", ":"),
                      ensure_ascii=False).encode("utf-8")


def canonical_sha256(payload: Any) -> str:
    return hashlib.sha256(canonical_json_bytes(payload)).hexdigest()


def deep_freeze(value: Any) -> Any:
    if isinstance(value, Mapping):
        return MappingProxyType({k: deep_freeze(v) for k, v in value.items()})
    if isinstance(value, (list, tuple)):
        return tuple(deep_freeze(v) for v in value)
    return value


def plain(value: Any) -> Any:
    if isinstance(value, Mapping):
        return {k: plain(v) for k, v in value.items()}
    if isinstance(value, (list, tuple)):
        return [plain(v) for v in value]
    return value


def stable_twin_id(economic_asset_uid: str, economic_node_id: str) -> str:
    material = {"economicAssetUid": economic_asset_uid,
                "economicNodeId": economic_node_id}
    return "digital-twin:" + canonical_sha256(material)


@dataclass(frozen=True)
class TwinComponent:
    component_id: str
    state: ComponentState
    source_phase: str
    source_digest: str
    detail: str = ""

    def __post_init__(self) -> None:
        if not isinstance(self.state, ComponentState):
            raise TwinError(
                f"component {self.component_id} state must be ComponentState")
        if not self.component_id.strip():
            raise TwinError("component_id must be non-empty")

    def to_evidence_dict(self) -> dict[str, Any]:
        return {
            "componentId": self.component_id,
            "state": self.state.value,
            "sourcePhase": self.source_phase,
            "sourceDigest": self.source_digest,
            "detail": self.detail,
        }


@dataclass(frozen=True)
class TwinGap:
    gap_kind: TwinGapKind
    source: str
    reason: str

    def __post_init__(self) -> None:
        if not isinstance(self.gap_kind, TwinGapKind):
            raise TwinError("gap_kind must be a TwinGapKind member")

    def to_evidence_dict(self) -> dict[str, str]:
        return {"gapKind": self.gap_kind.value,
                "source": self.source, "reason": self.reason}


@dataclass(frozen=True)
class DigitalTwinSnapshot:
    status: DigitalTwinStatus
    generated_at: datetime
    git_head: str
    twin_id: str
    economic_asset_uid: str
    economic_node_id: str
    components: tuple[TwinComponent, ...]
    deployment_state: Mapping[str, Any] | None
    reference_state: Mapping[str, Any] | None
    execution_state: Mapping[str, Any] | None
    model_state: Mapping[str, Any] | None
    comparability_state: Mapping[str, Any] | None
    verification: Mapping[str, Any]
    upstream_gaps: tuple[Mapping[str, str], ...]
    twin_gaps: tuple[TwinGap, ...]
    source_digests: Mapping[str, str]
    subject_r11_evidence: Mapping[str, Any]
    boundaries: Mapping[str, str]
    freeze_anchor: str
    freeze_tree: str
    synthetic: bool
    r12_snapshot_digest: str

    def __post_init__(self) -> None:
        for name in ("deployment_state", "reference_state", "execution_state",
                     "model_state", "comparability_state", "verification",
                     "source_digests", "subject_r11_evidence", "boundaries"):
            object.__setattr__(self, name,
                               deep_freeze(getattr(self, name)))
        if self.generated_at.tzinfo is None:
            raise TwinError("generated_at must be timezone-aware")
        if type(self.synthetic) is not bool:
            raise TwinError("synthetic must be an exact boolean")
        if not self.r12_snapshot_digest:
            raise TwinError("r12_snapshot_digest is required")
        # canonical ordering validated, never mutated
        component_ids = [c.component_id for c in self.components]
        if component_ids != sorted(component_ids):
            raise TwinError("components must be in canonical order")
        gap_keys = [(g.gap_kind.value, g.source, g.reason)
                    for g in self.twin_gaps]
        if gap_keys != sorted(gap_keys):
            raise TwinError("twin gaps must be in canonical order")
        upstream_keys = [
            (g.get("gapKind", ""), g.get("source", ""), g.get("reason", ""))
            for g in self.upstream_gaps
        ]
        if upstream_keys != sorted(upstream_keys):
            raise TwinError("upstream gaps must be in canonical order")

    def to_evidence_dict(self) -> dict[str, Any]:
        return {
            "schemaVersion": SCHEMA_VERSION,
            "phase": PHASE,
            "status": self.status.value,
            "generatedAt": self.generated_at.isoformat(),
            "gitHead": self.git_head,
            "twinId": self.twin_id,
            "economicAssetUid": self.economic_asset_uid,
            "economicNodeId": self.economic_node_id,
            "components": [c.to_evidence_dict() for c in self.components],
            "deploymentState": plain(self.deployment_state),
            "referenceState": plain(self.reference_state),
            "executionState": plain(self.execution_state),
            "modelState": plain(self.model_state),
            "comparabilityState": plain(self.comparability_state),
            "verification": plain(self.verification),
            "upstreamGaps": [plain(g) for g in self.upstream_gaps],
            "twinGaps": [g.to_evidence_dict() for g in self.twin_gaps],
            "sourceDigests": dict(self.source_digests),
            "subjectR11Evidence": plain(self.subject_r11_evidence),
            "boundaries": dict(self.boundaries),
            "freezeAnchor": self.freeze_anchor,
            "freezeTree": self.freeze_tree,
            "synthetic": self.synthetic,
            "r12SnapshotDigest": self.r12_snapshot_digest,
        }


def compute_twin_digest(snapshot: DigitalTwinSnapshot) -> str:
    evidence = snapshot.to_evidence_dict()
    evidence.pop("r12SnapshotDigest", None)
    return canonical_sha256(evidence)


def verify_serialized_r12_evidence(evidence: Any) -> bool:
    """Fail-closed serialized R12 self-verification."""
    if not isinstance(evidence, Mapping) or "r12SnapshotDigest" not in evidence:
        return False
    if evidence.get("schemaVersion") != SCHEMA_VERSION:
        return False
    if evidence.get("phase") != PHASE:
        return False
    if type(evidence.get("synthetic")) is not bool:
        return False
    material = plain(evidence)
    recorded = material.pop("r12SnapshotDigest")
    return recorded == canonical_sha256(material)
