"""Typed immutable contracts for FINCO Radar R11 — verification authority.

Schema ``radar-r11-verification-v1``.  R11 consumes serialized R10 evidence
read-only and produces content-addressed verification evidence.

R11 verification state is INDEPENDENT of the R10 subject state: an honest
``MODEL_RADAR_PARTIAL`` subject with a typed gap can be fully
``VERIFICATION_OK``.

Deep immutability from initial implementation.  Canonical digest order is
established BEFORE hashing; nothing is reordered after the digest.
"""
from __future__ import annotations

import hashlib
import json
import re
from dataclasses import dataclass, field
from datetime import datetime
from enum import Enum
from types import MappingProxyType
from typing import Any, Mapping

SCHEMA_VERSION = "radar-r11-verification-v1"
PHASE = "R11"

# A1: the canonical R0-R10 freeze authority, pinned INSIDE R11 contracts.
# Caller-supplied freeze values are claims to be verified against these
# constants, never proof.
R10_FREEZE_ANCHOR = "7ffaf3b1e67dabb728314948e2a4e4c7ef30047a"
R10_FREEZE_TREE = "fba9d76d9dceee35d079563b115fdde90c40bd46"

_SHA256_RE = re.compile(r"[0-9a-f]{64}")


def require_sha256_shape(value: Any, name: str) -> None:
    if not isinstance(value, str) or not _SHA256_RE.fullmatch(value):
        raise VerificationError(
            f"{name} must be a lowercase 64-hex SHA-256 digest, got {value!r}",
            VerificationStatus.VERIFICATION_INPUT_INVALID,
        )


def require_exact_bool(value: Any, name: str) -> None:
    # A9: bool is an int subclass in Python - `in (True, False)` would
    # accept 0/1.  Exact type identity is required.
    if type(value) is not bool:
        raise VerificationError(
            f"{name} must be an exact boolean, got {value!r}",
            VerificationStatus.VERIFICATION_INPUT_INVALID,
        )


class VerificationStatus(str, Enum):
    VERIFICATION_OK = "VERIFICATION_OK"
    VERIFICATION_PARTIAL = "VERIFICATION_PARTIAL"
    VERIFICATION_FAILED = "VERIFICATION_FAILED"
    VERIFICATION_INPUT_INVALID = "VERIFICATION_INPUT_INVALID"
    VERIFICATION_EVIDENCE_MISMATCH = "VERIFICATION_EVIDENCE_MISMATCH"


class CheckState(str, Enum):
    PASS = "PASS"
    FAIL = "FAIL"
    UNAVAILABLE = "UNAVAILABLE"


class VerificationGapKind(str, Enum):
    """R11-owned gap vocabulary.  R10 gap kinds are never reused here; the
    subject's own gaps are preserved verbatim under subjectGaps."""
    SUBJECT_EVIDENCE_UNAVAILABLE = "SUBJECT_EVIDENCE_UNAVAILABLE"
    UNSUPPORTED_SUBJECT_SCHEMA = "UNSUPPORTED_SUBJECT_SCHEMA"
    SUBJECT_DIGEST_MISMATCH = "SUBJECT_DIGEST_MISMATCH"
    SOURCE_LINEAGE_MISMATCH = "SOURCE_LINEAGE_MISMATCH"
    SUBJECT_CONTRACT_MISMATCH = "SUBJECT_CONTRACT_MISMATCH"
    VERIFICATION_AUTHORITY_UNAVAILABLE = "VERIFICATION_AUTHORITY_UNAVAILABLE"
    FREEZE_IDENTITY_MISMATCH = "FREEZE_IDENTITY_MISMATCH"


# R10 subject statuses R11 understands (closed vocabulary mirror).
R10_STATUSES = {
    "MODEL_RADAR_OK",
    "MODEL_RADAR_PARTIAL",
    "MODEL_RADAR_LINEAGE_MISMATCH",
    "MODEL_RADAR_INPUT_INVALID",
    "MODEL_RADAR_TIMING_INVALID",
    "MODEL_RADAR_EVIDENCE_MISMATCH",
}

# The frozen seven R10 comparability dimensions, in canonical form.
FROZEN_DIMENSIONS = (
    "ECONOMIC_IDENTITY",
    "CURRENCY",
    "MULTIPLIER",
    "REFERENCE_AVAILABILITY",
    "TIMING",
    "UNIT_BASIS",
    "VALUE_KIND",
)


class VerificationError(ValueError):
    """Typed R11 verification error (contract-level, not check-level)."""

    def __init__(self, message: str,
                 status: VerificationStatus = VerificationStatus.VERIFICATION_FAILED):
        super().__init__(message)
        self.status = status


def canonical_json_bytes(payload: Any) -> bytes:
    """R11's INDEPENDENT implementation of the documented R10/R11 canonical
    form: sorted keys, compact separators, UTF-8.  Deliberately local - the
    verifier does not borrow the frozen producer's serialization code for
    its primary reconstruction."""
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


@dataclass(frozen=True)
class VerificationCheck:
    check_id: str
    state: CheckState
    detail: str = ""

    def __post_init__(self) -> None:
        if not isinstance(self.state, CheckState):
            raise VerificationError(
                f"check {self.check_id!r} state must be a CheckState member")
        if not self.check_id.strip():
            raise VerificationError(
                "check_id must be non-empty for PASS, FAIL and UNAVAILABLE")

    def to_evidence_dict(self) -> dict[str, Any]:
        return {
            "checkId": self.check_id,
            "state": self.state.value,
            "detail": self.detail,
        }


@dataclass(frozen=True)
class VerificationGap:
    gap_kind: VerificationGapKind
    source: str
    reason: str

    def __post_init__(self) -> None:
        if not isinstance(self.gap_kind, VerificationGapKind):
            raise VerificationError(
                "verification gap_kind must be a VerificationGapKind member")

    def to_evidence_dict(self) -> dict[str, str]:
        return {
            "gapKind": self.gap_kind.value,
            "source": self.source,
            "reason": self.reason,
        }


@dataclass(frozen=True)
class VerificationSnapshot:
    status: VerificationStatus
    generated_at: datetime
    git_head: str
    subject_phase: str
    subject_status: str
    subject_git_head: str
    subject_snapshot_digest: str | None
    subject_evidence_digest: str
    subject_authority_anchor: str
    subject_authority_tree: str
    economic_asset_uid: str | None
    economic_node_id: str | None
    subject_gaps: tuple[Mapping[str, str], ...]
    checks: tuple[VerificationCheck, ...]
    verification_gaps: tuple[VerificationGap, ...]
    source_digests: Mapping[str, str]
    subject_evidence: Mapping[str, Any]
    boundaries: Mapping[str, str]
    synthetic: bool
    freeze_anchor: str
    content_envelope: Mapping[str, Any] | None = None
    r11_snapshot_digest: str = ""

    def __post_init__(self) -> None:
        object.__setattr__(self, "source_digests", deep_freeze(self.source_digests))
        object.__setattr__(self, "subject_evidence", deep_freeze(self.subject_evidence))
        object.__setattr__(self, "boundaries", deep_freeze(self.boundaries))
        if not isinstance(self.status, VerificationStatus):
            raise VerificationError(
                f"status must be a VerificationStatus member, got "
                f"{self.status!r}")
        if self.generated_at.tzinfo is None or self.generated_at.tzinfo.utcoffset(
            self.generated_at
        ) is None:
            raise VerificationError("generated_at must be timezone-aware")
        require_exact_bool(self.synthetic, "synthetic")
        if not isinstance(self.git_head, str) or not self.git_head.strip():
            raise VerificationError("git_head must be non-empty")
        require_sha256_shape(self.r11_snapshot_digest, "r11_snapshot_digest")
        if self.subject_snapshot_digest is not None:
            require_sha256_shape(self.subject_snapshot_digest,
                                 "subject_snapshot_digest")
        # Canonical order was established by the builder BEFORE the digest;
        # here it is only validated, never mutated.
        check_ids = [c.check_id for c in self.checks]
        if check_ids != sorted(check_ids):
            raise VerificationError("checks must be supplied in canonical order")
        gap_keys = [(g.gap_kind.value, g.source, g.reason)
                    for g in self.verification_gaps]
        if gap_keys != sorted(gap_keys):
            raise VerificationError("verification gaps must be supplied in canonical order")
        subject_gap_keys = [
            (g.get("gapKind", ""), g.get("source", ""), g.get("reason", ""))
            for g in self.subject_gaps
        ]
        if subject_gap_keys != sorted(subject_gap_keys):
            raise VerificationError("subject gaps must be supplied in canonical order")

    def to_evidence_dict(self) -> dict[str, Any]:
        return {
            "schemaVersion": SCHEMA_VERSION,
            "phase": PHASE,
            "status": self.status.value,
            "generatedAt": self.generated_at.isoformat(),
            "gitHead": self.git_head,
            "subjectPhase": self.subject_phase,
            "subjectStatus": self.subject_status,
            "subjectGitHead": self.subject_git_head,
            "subjectSnapshotDigest": self.subject_snapshot_digest,
            "subjectEvidenceDigest": self.subject_evidence_digest,
            "subjectAuthorityAnchor": self.subject_authority_anchor,
            "subjectAuthorityTree": self.subject_authority_tree,
            "economicAssetUid": self.economic_asset_uid,
            "economicNodeId": self.economic_node_id,
            "subjectGaps": [plain(g) for g in self.subject_gaps],
            "checks": [c.to_evidence_dict() for c in self.checks],
            "verificationGaps": [g.to_evidence_dict() for g in self.verification_gaps],
            "sourceDigests": dict(self.source_digests),
            "subjectEvidence": plain(self.subject_evidence),
            "boundaries": dict(self.boundaries),
            "synthetic": self.synthetic,
            "freezeAnchor": self.freeze_anchor,
            "contentEnvelope": (
                plain(self.content_envelope)
                if self.content_envelope is not None else None
            ),
            "r11SnapshotDigest": self.r11_snapshot_digest,
        }


def compute_verification_digest(snapshot: VerificationSnapshot) -> str:
    evidence = snapshot.to_evidence_dict()
    evidence.pop("r11SnapshotDigest", None)
    return canonical_sha256(evidence)


def verify_r11_snapshot_digest(snapshot: VerificationSnapshot) -> bool:
    return compute_verification_digest(snapshot) == snapshot.r11_snapshot_digest


def verify_serialized_r11_evidence(evidence: Any) -> bool:
    """Fail-closed tamper detection over serialized R11 evidence.

    A9: essential outer structural invariants are validated BEFORE the
    digest comparison, so correctly re-hashing malformed R11 JSON never
    verifies as valid serialized R11 evidence."""
    if not isinstance(evidence, Mapping):
        return False
    if evidence.get("schemaVersion") != SCHEMA_VERSION:
        return False
    if evidence.get("phase") != PHASE:
        return False
    if evidence.get("status") not in {s.value for s in VerificationStatus}:
        return False
    if type(evidence.get("synthetic")) is not bool:
        return False
    if not isinstance(evidence.get("checks"), list) or not evidence["checks"]:
        return False
    if not isinstance(evidence.get("gitHead"), str) or not evidence["gitHead"]:
        return False
    if not isinstance(evidence.get("r11SnapshotDigest"), str):
        return False
    material = plain(evidence)
    recorded = material.pop("r11SnapshotDigest")
    return recorded == canonical_sha256(material)


def build_verification_envelope(evidence: Mapping[str, Any]) -> Any:
    """Optional content-addressed envelope over the verified subject,
    produced with the FROZEN finco_protocol verification infrastructure
    read-only.  Content-addressed only: NOT on-chain anchoring, NOT the
    primary R11 authority (the R11 snapshot digest is)."""
    from finco_protocol.verification.envelope import build_evidence_envelope
    return build_evidence_envelope(
        surface="finco_radar.r11.verification",
        evidence_type="radar-r10-subject-evidence",
        payload=plain(evidence),
        authority_refs=(
            "finco_radar.model_radar",
            "finco_radar.r10",
        ),
    )


R11_BOUNDARIES = {
    "registryAuthority": "R1_APPLIED",
    "referenceAuthority": "R4_APPLIED",
    "crossMarketAuthority": "R7_APPLIED",
    "executionSimulatorAuthority": "R8_APPLIED",
    "assetGraphAuthority": "R9_APPLIED",
    "modelAuthority": "R10_APPLIED",
    "verificationAuthority": "R11_APPLIED",
    "digitalTwinAuthority": "R12_NOT_YET_APPLIED",
}
