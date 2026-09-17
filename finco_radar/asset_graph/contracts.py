"""Typed contracts for FINCO Radar R9 — FINCO ASSET GRAPH.

Records source-proven relationships between financial and market authorities
already established by R0–R8. Every relationship must have explicit source
authority; a missing relationship is an explicit graph gap, never a synthetic
edge. Deep immutability from initial implementation.
"""
from __future__ import annotations

import hashlib
import json
from dataclasses import dataclass, field
from datetime import datetime
from enum import Enum
from types import MappingProxyType
from typing import Any, Mapping

from finco_radar.assets.contracts import AssetKey

SCHEMA_VERSION = "radar-r9-asset-graph-v1"
PHASE = "R9"


class GraphNodeType(str, Enum):
    ECONOMIC_ASSET = "ECONOMIC_ASSET"
    TOKEN_DEPLOYMENT = "TOKEN_DEPLOYMENT"
    UNDERLYING_INSTRUMENT = "UNDERLYING_INSTRUMENT"
    REFERENCE_INSTRUMENT = "REFERENCE_INSTRUMENT"
    REFERENCE_SOURCE = "REFERENCE_SOURCE"
    VENUE = "VENUE"
    SETTLEMENT_CONTEXT = "SETTLEMENT_CONTEXT"


class GraphRelationshipType(str, Enum):
    REPRESENTED_BY = "REPRESENTED_BY"
    HAS_UNDERLYING = "HAS_UNDERLYING"
    REFERENCED_BY = "REFERENCED_BY"
    OBSERVED_BY = "OBSERVED_BY"
    QUOTED_ON = "QUOTED_ON"
    SETTLES_VIA = "SETTLES_VIA"
    HAS_EXECUTION_EVIDENCE = "HAS_EXECUTION_EVIDENCE"


class GraphGapKind(str, Enum):
    UNDERLYING_RELATIONSHIP_UNAVAILABLE = "UNDERLYING_RELATIONSHIP_UNAVAILABLE"
    REFERENCE_INSTRUMENT_UNAVAILABLE = "REFERENCE_INSTRUMENT_UNAVAILABLE"
    REFERENCE_SOURCE_UNAVAILABLE = "REFERENCE_SOURCE_UNAVAILABLE"
    SETTLEMENT_IDENTITY_UNRESOLVED = "SETTLEMENT_IDENTITY_UNRESOLVED"
    SECOND_VENUE_UNAVAILABLE = "SECOND_VENUE_UNAVAILABLE"
    EXTERNAL_ORACLE_UNAVAILABLE = "EXTERNAL_ORACLE_UNAVAILABLE"
    CORPORATE_ACTION_AUTHORITY_UNAVAILABLE = "CORPORATE_ACTION_AUTHORITY_UNAVAILABLE"
    UPSTREAM_EVIDENCE_UNAVAILABLE = "UPSTREAM_EVIDENCE_UNAVAILABLE"


class AssetGraphStatus(str, Enum):
    ASSET_GRAPH_OK = "ASSET_GRAPH_OK"
    ASSET_GRAPH_PARTIAL = "ASSET_GRAPH_PARTIAL"
    ASSET_GRAPH_IDENTITY_MISMATCH = "ASSET_GRAPH_IDENTITY_MISMATCH"
    ASSET_GRAPH_LINEAGE_MISMATCH = "ASSET_GRAPH_LINEAGE_MISMATCH"
    ASSET_GRAPH_TOPOLOGY_INVALID = "ASSET_GRAPH_TOPOLOGY_INVALID"
    ASSET_GRAPH_EVIDENCE_MISMATCH = "ASSET_GRAPH_EVIDENCE_MISMATCH"
    ASSET_GRAPH_INPUT_INVALID = "ASSET_GRAPH_INPUT_INVALID"


class AssetGraphError(ValueError):
    def __init__(
        self,
        message: str,
        status: AssetGraphStatus = AssetGraphStatus.ASSET_GRAPH_INPUT_INVALID,
    ) -> None:
        super().__init__(message)
        self.status = status


def deep_freeze(value: Any) -> Any:
    """Recursively convert mutable evidence into owned immutable structures."""
    if isinstance(value, Mapping):
        return MappingProxyType({k: deep_freeze(v) for k, v in value.items()})
    if isinstance(value, (list, tuple)):
        return tuple(deep_freeze(v) for v in value)
    if isinstance(value, (set, frozenset)):
        return tuple(sorted((repr(deep_freeze(v)) for v in value)))
    return value


def _plain(value: Any) -> Any:
    if isinstance(value, Mapping):
        return {k: _plain(v) for k, v in value.items()}
    if isinstance(value, (list, tuple)):
        return [_plain(v) for v in value]
    return value


def canonical_bytes(payload: Any) -> bytes:
    return json.dumps(payload, sort_keys=True, separators=(",", ":"), ensure_ascii=False).encode(
        "utf-8"
    )


@dataclass(frozen=True)
class AssetGraphNode:
    node_id: str
    node_type: GraphNodeType
    source: str
    source_identifier: str
    economic_asset_uid: str | None = None
    canonical_asset_key: AssetKey | None = None
    display_label: str | None = None
    metadata: Mapping[str, Any] = field(default_factory=dict)
    evidence_refs: tuple[str, ...] = ()

    def __post_init__(self) -> None:
        object.__setattr__(self, "metadata", deep_freeze(self.metadata))
        object.__setattr__(self, "evidence_refs", deep_freeze(self.evidence_refs))
        if not self.node_id.strip():
            raise AssetGraphError(
                "node_id must be non-empty", AssetGraphStatus.ASSET_GRAPH_INPUT_INVALID
            )
        if not self.source.strip():
            raise AssetGraphError(
                "node source must be non-empty", AssetGraphStatus.ASSET_GRAPH_INPUT_INVALID
            )

    def to_evidence_dict(self) -> dict[str, Any]:
        return {
            "nodeId": self.node_id,
            "nodeType": self.node_type.value,
            "economicAssetUid": self.economic_asset_uid,
            "canonicalAssetKey": (
                {
                    "chainId": self.canonical_asset_key.chain_id,
                    "contractAddress": self.canonical_asset_key.contract_address,
                }
                if self.canonical_asset_key is not None
                else None
            ),
            "source": self.source,
            "sourceIdentifier": self.source_identifier,
            "displayLabel": self.display_label,
            "metadata": _plain(self.metadata),
            "evidenceRefs": list(self.evidence_refs),
        }


@dataclass(frozen=True)
class AssetGraphEdge:
    edge_id: str
    relationship_type: GraphRelationshipType
    from_node_id: str
    to_node_id: str
    authority_phase: str
    source: str
    evidence_digest: str
    observed_at: datetime | None = None
    metadata: Mapping[str, Any] = field(default_factory=dict)

    def __post_init__(self) -> None:
        object.__setattr__(self, "metadata", deep_freeze(self.metadata))
        if not self.edge_id.strip():
            raise AssetGraphError(
                "edge_id must be non-empty", AssetGraphStatus.ASSET_GRAPH_INPUT_INVALID
            )
        if not self.source.strip():
            raise AssetGraphError(
                "edge source must be non-empty", AssetGraphStatus.ASSET_GRAPH_INPUT_INVALID
            )
        if not self.evidence_digest.strip():
            raise AssetGraphError(
                "edge evidence_digest must be non-empty",
                AssetGraphStatus.ASSET_GRAPH_INPUT_INVALID,
            )

    def to_evidence_dict(self) -> dict[str, Any]:
        return {
            "edgeId": self.edge_id,
            "relationshipType": self.relationship_type.value,
            "fromNodeId": self.from_node_id,
            "toNodeId": self.to_node_id,
            "authorityPhase": self.authority_phase,
            "source": self.source,
            "evidenceDigest": self.evidence_digest,
            "observedAt": (
                self.observed_at.isoformat() if self.observed_at is not None else None
            ),
            "metadata": _plain(self.metadata),
        }


@dataclass(frozen=True)
class GraphGap:
    gap_kind: GraphGapKind
    related_node_id: str | None
    source: str
    reason: str

    def to_evidence_dict(self) -> dict[str, str]:
        return {
            "gapKind": self.gap_kind.value,
            "relatedNodeId": self.related_node_id,
            "source": self.source,
            "reason": self.reason,
        }


@dataclass(frozen=True)
class AssetGraphPath:
    path_id: str
    path_type: str
    node_ids: tuple[str, ...]
    edge_ids: tuple[str, ...]

    def to_evidence_dict(self) -> dict[str, Any]:
        return {
            "pathId": self.path_id,
            "pathType": self.path_type,
            "nodeIds": list(self.node_ids),
            "edgeIds": list(self.edge_ids),
        }


@dataclass(frozen=True)
class AssetGraphSnapshot:
    status: AssetGraphStatus
    generated_at: datetime
    git_head: str
    economic_asset_uid: str
    nodes: tuple[AssetGraphNode, ...]
    edges: tuple[AssetGraphEdge, ...]
    gaps: tuple[GraphGap, ...]
    paths: tuple[AssetGraphPath, ...]
    source_digests: Mapping[str, str]
    upstream_evidence: Mapping[str, Any]
    boundaries: Mapping[str, str]
    synthetic: bool
    r9_snapshot_digest: str

    def __post_init__(self) -> None:
        object.__setattr__(self, "source_digests", deep_freeze(self.source_digests))
        object.__setattr__(self, "upstream_evidence", deep_freeze(self.upstream_evidence))
        object.__setattr__(self, "boundaries", deep_freeze(self.boundaries))
        if not self.r9_snapshot_digest:
            raise AssetGraphError(
                "r9_snapshot_digest is required",
                AssetGraphStatus.ASSET_GRAPH_EVIDENCE_MISMATCH,
            )

    def to_evidence_dict(self) -> dict[str, Any]:
        return {
            "schemaVersion": SCHEMA_VERSION,
            "phase": PHASE,
            "status": self.status.value,
            "generatedAt": self.generated_at.isoformat(),
            "gitHead": self.git_head,
            "economicAssetUid": self.economic_asset_uid,
            "nodes": sorted(
                [n.to_evidence_dict() for n in self.nodes],
                key=lambda n: (n["nodeType"], n["nodeId"]),
            ),
            "edges": sorted(
                [e.to_evidence_dict() for e in self.edges],
                key=lambda e: (
                    e["relationshipType"], e["fromNodeId"], e["toNodeId"], e["edgeId"]
                ),
            ),
            "gaps": sorted(
                [g.to_evidence_dict() for g in self.gaps],
                key=lambda g: (g["gapKind"], g.get("relatedNodeId") or "", g["source"]),
            ),
            "paths": [p.to_evidence_dict() for p in self.paths],
            "sourceDigests": dict(self.source_digests),
            "upstreamEvidence": _plain(self.upstream_evidence),
            "boundaries": dict(self.boundaries),
            "synthetic": self.synthetic,
            "r9SnapshotDigest": self.r9_snapshot_digest,
        }


def canonical_evidence_bytes(evidence: Any) -> bytes:
    return json.dumps(evidence, sort_keys=True, separators=(",", ":"), ensure_ascii=False).encode(
        "utf-8"
    )


def verify_r9_snapshot_digest(snapshot: "AssetGraphSnapshot") -> bool:
    evidence = snapshot.to_evidence_dict()
    recorded = evidence.pop("r9SnapshotDigest")
    recomputed = hashlib.sha256(canonical_evidence_bytes(evidence)).hexdigest()
    return recorded == recomputed


def verify_serialized_r9_evidence(evidence: Any) -> bool:
    """Fail-closed tamper detection over serialized R9 evidence dicts."""
    if not isinstance(evidence, Mapping) or "r9SnapshotDigest" not in evidence:
        return False
    material = _plain(evidence)
    recorded = material.pop("r9SnapshotDigest")
    recomputed = hashlib.sha256(canonical_evidence_bytes(material)).hexdigest()
    return recorded == recomputed
