"""Deterministic content-addressed evidence envelopes for FINCO Protocol.

The envelope is deliberately chain-agnostic. It produces a stable SHA-256
content address for already-produced Model or Radar evidence without claiming
that the digest is currently anchored on-chain. A future anchoring layer can
store the digest while the full financial evidence remains off-chain.
"""
from __future__ import annotations

from dataclasses import dataclass
from datetime import date, datetime
from decimal import Decimal
from enum import Enum
import hashlib
import json
import math
from typing import Any, Mapping, Sequence


EVIDENCE_ENVELOPE_SCHEMA = "finco.evidence-envelope.v1"
CANONICALIZATION = "FINCO_SORTED_JSON_V1"


def _normalize(value: Any) -> Any:
    """Convert supported values to an unambiguous JSON-compatible form.

    Floats are retained as JSON numbers but must be finite. Decimal values are
    serialized as strings so financial precision is never silently coerced to
    binary floating point. Datetimes keep their explicit ISO-8601 offset.
    """

    if value is None or isinstance(value, (str, bool, int)):
        return value
    if isinstance(value, float):
        if not math.isfinite(value):
            raise ValueError("evidence contains a non-finite float")
        return value
    if isinstance(value, Decimal):
        if not value.is_finite():
            raise ValueError("evidence contains a non-finite Decimal")
        return format(value, "f")
    if isinstance(value, datetime):
        if value.tzinfo is None:
            raise ValueError("evidence datetime must be timezone-aware")
        return value.isoformat()
    if isinstance(value, date):
        return value.isoformat()
    if isinstance(value, Enum):
        return _normalize(value.value)
    if isinstance(value, Mapping):
        normalized: dict[str, Any] = {}
        for key, item in value.items():
            if not isinstance(key, str):
                raise TypeError("evidence mapping keys must be strings")
            normalized[key] = _normalize(item)
        return normalized
    if isinstance(value, (list, tuple)):
        return [_normalize(item) for item in value]
    raise TypeError(f"unsupported evidence type: {type(value).__name__}")


def canonical_json_bytes(value: Any) -> bytes:
    """Return the FINCO v1 canonical JSON representation.

    This is a project-defined deterministic encoding, not an RFC 8785 claim.
    The canonicalization identifier is included in every envelope so a future
    version can evolve without changing the meaning of historical digests.
    """

    normalized = _normalize(value)
    return json.dumps(
        normalized,
        ensure_ascii=False,
        allow_nan=False,
        sort_keys=True,
        separators=(",", ":"),
    ).encode("utf-8")


def canonical_sha256(value: Any) -> str:
    """Return lowercase SHA-256 hex for FINCO canonical JSON bytes."""

    return hashlib.sha256(canonical_json_bytes(value)).hexdigest()


def _valid_metadata(
    surface: Any,
    evidence_type: Any,
    authority_refs: Any,
) -> bool:
    if not isinstance(surface, str) or not surface.strip():
        return False
    if not isinstance(evidence_type, str) or not evidence_type.strip():
        return False
    if not isinstance(authority_refs, Sequence) or isinstance(
        authority_refs, (str, bytes, bytearray)
    ):
        return False
    return all(isinstance(ref, str) and bool(ref.strip()) for ref in authority_refs)


@dataclass(frozen=True)
class EvidenceEnvelope:
    """Immutable content-addressed evidence artifact."""

    schema: str
    canonicalization: str
    surface: str
    evidence_type: str
    authority_refs: tuple[str, ...]
    payload_sha256: str
    payload: Any

    @property
    def content_address(self) -> str:
        return f"sha256:{self.payload_sha256}"

    def as_dict(self) -> dict[str, Any]:
        return {
            "schema": self.schema,
            "canonicalization": self.canonicalization,
            "surface": self.surface,
            "evidenceType": self.evidence_type,
            "authorityRefs": list(self.authority_refs),
            "payloadSha256": self.payload_sha256,
            "contentAddress": self.content_address,
            "payload": _normalize(self.payload),
        }


def build_evidence_envelope(
    *,
    surface: str,
    evidence_type: str,
    payload: Any,
    authority_refs: tuple[str, ...] = (),
) -> EvidenceEnvelope:
    """Create an envelope from evidence without mutating the payload."""

    if not surface.strip():
        raise ValueError("surface is required")
    if not evidence_type.strip():
        raise ValueError("evidence_type is required")
    if any(not ref.strip() for ref in authority_refs):
        raise ValueError("authority_refs may not contain empty values")

    normalized_payload = _normalize(payload)
    digest = canonical_sha256(normalized_payload)
    return EvidenceEnvelope(
        schema=EVIDENCE_ENVELOPE_SCHEMA,
        canonicalization=CANONICALIZATION,
        surface=surface,
        evidence_type=evidence_type,
        authority_refs=tuple(authority_refs),
        payload_sha256=digest,
        payload=normalized_payload,
    )


def verify_evidence_envelope(envelope: EvidenceEnvelope | Mapping[str, Any]) -> bool:
    """Recompute payload digest and fail closed on the declared envelope contract.

    ``payloadSha256`` remains intentionally payload-only. Envelope metadata is
    schema-validated here but is not silently folded into that historical digest
    semantics; a future full-envelope digest would require a new versioned contract.
    """

    if isinstance(envelope, EvidenceEnvelope):
        if not _valid_metadata(
            envelope.surface,
            envelope.evidence_type,
            envelope.authority_refs,
        ):
            return False
        try:
            payload_digest = canonical_sha256(envelope.payload)
        except (TypeError, ValueError):
            return False
        return (
            envelope.schema == EVIDENCE_ENVELOPE_SCHEMA
            and envelope.canonicalization == CANONICALIZATION
            and payload_digest == envelope.payload_sha256
        )

    surface = envelope.get("surface")
    evidence_type = envelope.get("evidenceType")
    authority_refs = envelope.get("authorityRefs")
    if not _valid_metadata(surface, evidence_type, authority_refs):
        return False

    schema = envelope.get("schema")
    canonicalization = envelope.get("canonicalization")
    payload = envelope.get("payload")
    digest = envelope.get("payloadSha256")
    content_address = envelope.get("contentAddress")
    if not isinstance(digest, str):
        return False
    try:
        payload_digest = canonical_sha256(payload)
    except (TypeError, ValueError):
        return False
    return (
        schema == EVIDENCE_ENVELOPE_SCHEMA
        and canonicalization == CANONICALIZATION
        and payload_digest == digest
        and content_address == f"sha256:{digest}"
    )
