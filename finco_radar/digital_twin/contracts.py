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

# What R11 verified against (the R0-R10 freeze anchor) — HISTORICAL R10
# verification identity; never changes with governance baselines.
R11_VERIFIED_ANCHOR = "7ffaf3b1e67dabb728314948e2a4e4c7ef30047a"
R11_VERIFIED_TREE = "fba9d76d9dceee35d079563b115fdde90c40bd46"
# Historical R10 authority verified by R11 (historical claim inside R11
# evidence) — HISTORICAL identity constants.
R10_FREEZE_ANCHOR = "7ffaf3b1e67dabb728314948e2a4e4c7ef30047a"
R10_FREEZE_TREE = "fba9d76d9dceee35d079563b115fdde90c40bd46"
# R11 authority consumed by R12 (Correction A): the canonical corrected
# R0-R11 main that R12 actually builds from (R11 Correction A merged via
# PR #32).  Governance baseline and historical identity are separate
# concepts; these pins identify the CONSUMED AUTHORITY.
R11_FREEZE_ANCHOR = "537d255e8443f3f603a42a6dee856cc0de04e8cc"
R11_FREEZE_TREE = "443989d69e0aed0cd8af581041574f4029b32b93"


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
    COMPARABILITY_STATE = "COMPARABILITY_STATE"


# A5: closed component vocabulary.  Mandatory components must appear
# exactly once; the optional component at most once; nothing else is
# accepted.
MANDATORY_COMPONENT_IDS = frozenset(c.value for c in ComponentId) - {
    "COMPARABILITY_STATE"}
OPTIONAL_COMPONENT_IDS = frozenset({"COMPARABILITY_STATE"})

# A5: valid source phases for twin components (the verified upstream
# authorities R12 composes from).
SOURCE_PHASES = frozenset({"R7", "R8", "R9", "R10", "R11"})


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
        # A5: closed component vocabulary — a free-form non-empty string is
        # NOT accepted; the id must be a ComponentId member value.
        if self.component_id not in [c.value for c in ComponentId]:
            raise TwinError(
                f"component_id {self.component_id!r} is not a ComponentId "
                "member (closed vocabulary)")
        if not isinstance(self.state, ComponentState):
            raise TwinError(
                f"component {self.component_id} state must be ComponentState")
        if self.source_phase not in SOURCE_PHASES:
            raise TwinError(
                f"component {self.component_id} sourcePhase "
                f"{self.source_phase!r} is not a valid upstream phase")
        # A5/A6: source-digest semantics — AVAILABLE components carry the
        # digest of the verified upstream authority they were derived from;
        # unavailable components carry none.
        if self.state is ComponentState.AVAILABLE and not self.source_digest:
            raise TwinError(
                f"component {self.component_id} is AVAILABLE but carries no "
                "source digest")
        if self.state is not ComponentState.AVAILABLE and self.source_digest:
            raise TwinError(
                f"component {self.component_id} is {self.state.value} but "
                "carries a source digest")

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
        if len(set(component_ids)) != len(component_ids):
            raise TwinError("components must not contain duplicates")
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
    """Fail-closed serialized R12 ingest — Correction A (F03 closure).

    Core rule: ``R12_CONTENT_INTEGRITY != R12_COMPOSITION_AUTHORITY``.

    A serialized R12 artifact is accepted only when BOTH layers hold:

    1. **Serialized/content integrity** — exact schema/phase, valid typed
       status, timezone-aware ``generatedAt``, valid ``gitHead``, exact
       bool ``synthetic``, non-empty identity fields, exact canonical
       ``twinId``, exact R12 boundaries, exact R11 freeze anchor/tree,
       closed component vocabulary (mandatory exactly once, optional at
       most once, no unknown ids, valid states/source phases/source-digest
       semantics), valid gaps/sourceDigests/state payloads, exact
       R11/R10 digest-lineage bindings, and ``r12SnapshotDigest``
       reconstruction.

    2. **Canonical R12 composition replay** — the embedded
       ``subjectR11Evidence`` must first pass the corrected canonical R11
       serialized verifier; the ONE canonical builder
       ``build_digital_twin`` is then replayed from that exact R11 subject
       under the serialized ``generatedAt``/``gitHead`` (no caller
       semantic overrides) and must reproduce the artifact EXACTLY.

    No raw exception escapes this public boundary; every rejection is the
    typed ``False`` result."""
    try:
        return _verify_serialized_r12_evidence_impl(evidence)
    except Exception:
        # A9: fail-closed public boundary — malformed untrusted input must
        # never escape as a raw AttributeError/TypeError/KeyError/
        # ValueError/IndexError; the typed failure result is False.
        return False


def _verify_serialized_r12_evidence_impl(evidence: Any) -> bool:
    # ---------------- Layer 1: serialized/content integrity ---------------
    if not isinstance(evidence, Mapping) or "r12SnapshotDigest" not in evidence:
        return False
    if evidence.get("schemaVersion") != SCHEMA_VERSION:
        return False
    if evidence.get("phase") != PHASE:
        return False
    if evidence.get("status") not in {s.value for s in DigitalTwinStatus}:
        return False
    generated_at = evidence.get("generatedAt")
    if not isinstance(generated_at, str):
        return False
    try:
        parsed = datetime.fromisoformat(generated_at)
    except (ValueError, TypeError):
        return False
    if parsed.tzinfo is None or parsed.tzinfo.utcoffset(parsed) is None:
        return False
    git_head = evidence.get("gitHead")
    if not isinstance(git_head, str) or not git_head.strip():
        return False
    if type(evidence.get("synthetic")) is not bool:
        return False
    uid = evidence.get("economicAssetUid")
    node = evidence.get("economicNodeId")
    if not isinstance(uid, str) or not uid.strip():
        return False
    if not isinstance(node, str) or not node.strip():
        return False
    # A3: exact canonical twin identity
    if evidence.get("twinId") != stable_twin_id(uid, node):
        return False
    boundaries = evidence.get("boundaries")
    if not isinstance(boundaries, Mapping) or dict(boundaries) != dict(
        R12_BOUNDARIES
    ):
        return False
    # A1: exact R11 freeze authority consumed by R12
    if evidence.get("freezeAnchor") != R11_FREEZE_ANCHOR:
        return False
    if evidence.get("freezeTree") != R11_FREEZE_TREE:
        return False
    subject = evidence.get("subjectR11Evidence")
    if not isinstance(subject, Mapping):
        return False
    # A3/A4: outer identity must exactly match the embedded verified R11
    if uid != subject.get("economicAssetUid") or node != subject.get(
        "economicNodeId"
    ):
        return False
    verification = evidence.get("verification")
    if not isinstance(verification, Mapping):
        return False
    # A4: exact R11/R10 digest lineage bindings
    r11_digest = subject.get("r11SnapshotDigest")
    r10_digest = subject.get("subjectSnapshotDigest")
    if not isinstance(r11_digest, str) or not r11_digest:
        return False
    if not isinstance(r10_digest, str) or not r10_digest:
        return False
    subject_r10 = subject.get("subjectEvidence")
    if not isinstance(subject_r10, Mapping):
        return False
    if subject_r10.get("r10SnapshotDigest") != r10_digest:
        return False
    if verification.get("r11SnapshotDigest") != r11_digest:
        return False
    if verification.get("subjectR10SnapshotDigest") != r10_digest:
        return False
    if verification.get("status") != subject.get("status"):
        return False
    # A10: recomputed check counts, never trusted from the artifact
    checks = subject.get("checks")
    if not isinstance(checks, list):
        return False
    failed = 0
    unavailable = 0
    for check in checks:
        if not isinstance(check, Mapping):
            return False
        state = check.get("state")
        if state == "FAIL":
            failed += 1
        elif state == "UNAVAILABLE":
            unavailable += 1
    if verification.get("failedCheckCount") != failed:
        return False
    if verification.get("unavailableCheckCount") != unavailable:
        return False
    # A5: closed component vocabulary
    components = evidence.get("components")
    if not isinstance(components, list) or not components:
        return False
    seen: set[str] = set()
    for component in components:
        if not isinstance(component, Mapping):
            return False
        cid = component.get("componentId")
        if not isinstance(cid, str) or cid not in (
            [c.value for c in ComponentId]
        ):
            return False
        if cid in seen:
            return False
        seen.add(cid)
        if component.get("state") not in {
            s.value for s in ComponentState
        }:
            return False
        if component.get("sourcePhase") not in SOURCE_PHASES:
            return False
        source_digest = component.get("sourceDigest")
        if not isinstance(source_digest, str):
            return False
        if component.get("state") == "AVAILABLE" and not source_digest:
            return False
        if component.get("state") in ("UNAVAILABLE", "NOT_APPLICABLE") and (
            source_digest
        ):
            return False
        if not isinstance(component.get("detail"), str):
            return False
    if not MANDATORY_COMPONENT_IDS.issubset(seen):
        return False
    # A9: gaps/sourceDigests/state payload containers, explicit types
    for gap_list in ("twinGaps", "upstreamGaps"):
        gaps = evidence.get(gap_list)
        if not isinstance(gaps, list):
            return False
        for gap in gaps:
            if not isinstance(gap, Mapping):
                return False
    for gap in evidence.get("twinGaps"):
        if gap.get("gapKind") not in {g.value for g in TwinGapKind}:
            return False
    source_digests = evidence.get("sourceDigests")
    if not isinstance(source_digests, Mapping):
        return False
    if any(not isinstance(v, str) for v in source_digests.values()):
        return False
    for payload in ("deploymentState", "referenceState", "executionState",
                    "modelState", "comparabilityState"):
        value = evidence.get(payload)
        if value is not None and not isinstance(value, Mapping):
            return False
    if not isinstance(evidence.get("r12SnapshotDigest"), str):
        return False
    material = plain(evidence)
    recorded = material.pop("r12SnapshotDigest")
    if recorded != canonical_sha256(material):
        return False

    # ---------------- Layer 2: canonical R12 composition replay -----------
    # The embedded R11 subject must pass the corrected canonical R11
    # serialized verifier (PR #32 authority), then the ONE canonical
    # builder must reproduce this exact artifact from it.
    from finco_radar.verification.contracts import (
        verify_serialized_r11_evidence,
    )
    if not verify_serialized_r11_evidence(subject):
        return False
    from .twin import build_digital_twin
    replay = build_digital_twin(
        r11_evidence=subject,
        generated_at=parsed,
        git_head=git_head,
    )
    return replay.to_evidence_dict() == plain(evidence)
