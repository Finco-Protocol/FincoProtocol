"""Deterministic asset-graph builder from frozen R7/R8 authority.

Consumes CrossMarketSnapshot + optional ExecutionSimulationSnapshot and
produces a typed AssetGraphSnapshot with nodes, edges, gaps and paths.

Correction A discipline:
- topology identity (node_id/edge_id) and evidence lineage (evidence_digest)
  are separate concepts; edge evidenceDigest is the canonical digest of the
  exact upstream record proving the relationship, never the edge_id;
- duplicate/conflicting inserts fail closed (no first/last-write-wins);
- canonical paths are real topology paths validated edge-by-edge.
"""
from __future__ import annotations

import hashlib
from datetime import datetime
from typing import Mapping, Sequence

from finco_radar.assets.contracts import AssetKey
from finco_radar.cross_market.contracts import CrossMarketSnapshot  # noqa: F401

from .contracts import (
    SCHEMA_VERSION,
    PHASE,
    AssetGraphEdge,
    AssetGraphNode,
    AssetGraphPath,
    AssetGraphSnapshot,
    AssetGraphStatus,
    AssetGraphError,
    GraphGap,
    GraphGapKind,
    GraphNodeType,
    GraphRelationshipType,
    canonical_evidence_bytes,
)


def _economic_node_id(uid: str) -> str:
    return f"economic:{uid}"


def _deployment_node_id(key: AssetKey) -> str:
    return f"deployment:{key.chain_id}:{key.contract_address}"


def _venue_node_id(venue: str) -> str:
    return f"venue:{venue}"


def _settlement_node_id(source: str, symbol: str) -> str:
    return f"settlement:{source}:{symbol}"


def _reference_instrument_node_id(source: str, instrument: str) -> str:
    return f"reference-instrument:{source}:{instrument}"


def _reference_source_node_id(source: str) -> str:
    return f"reference-source:{source}"


def _underlying_node_id(source: str, instrument: str) -> str:
    return f"underlying:{source}:{instrument}"


def _edge_id(rel: GraphRelationshipType, from_id: str, to_id: str) -> str:
    raw = f"{rel.value}|{from_id}|{to_id}"
    return hashlib.sha256(raw.encode("utf-8")).hexdigest()


def digest_record(record: Mapping) -> str:
    """Canonical SHA-256 of the exact upstream record proving a relationship."""
    return hashlib.sha256(canonical_evidence_bytes(record)).hexdigest()


def _canonical_bytes_key(record: Mapping) -> bytes:
    return canonical_evidence_bytes(record)


def validate_path_structure(
    node_ids: Sequence[str],
    edge_ids: Sequence[str],
    edges_by_id: Mapping[str, AssetGraphEdge],
) -> None:
    """Fail closed on any path whose edges do not exactly chain its nodes."""
    if len(edge_ids) != len(node_ids) - 1:
        raise AssetGraphError(
            f"path has {len(node_ids)} nodes but {len(edge_ids)} edges "
            "(expected exactly len(nodes) - 1 consecutive edges)",
            AssetGraphStatus.ASSET_GRAPH_TOPOLOGY_INVALID,
        )
    for i, edge_id in enumerate(edge_ids):
        edge = edges_by_id.get(edge_id)
        if edge is None:
            raise AssetGraphError(
                f"path references unknown edge {edge_id}",
                AssetGraphStatus.ASSET_GRAPH_TOPOLOGY_INVALID,
            )
        if edge.from_node_id != node_ids[i] or edge.to_node_id != node_ids[i + 1]:
            raise AssetGraphError(
                f"path edge {edge_id} connects {edge.from_node_id}->{edge.to_node_id} "
                f"but the node sequence requires {node_ids[i]}->{node_ids[i + 1]}",
                AssetGraphStatus.ASSET_GRAPH_TOPOLOGY_INVALID,
            )


class AssetGraphBuilder:
    """Deterministic graph builder from frozen R7/R8 authority."""

    def __init__(
        self,
        *,
        economic_asset_uid: str,
        canonical_asset_key: AssetKey,
        git_head: str = "UNKNOWN",
        synthetic: bool = False,
    ) -> None:
        self._uid = economic_asset_uid
        self._key = canonical_asset_key
        self._git_head = git_head
        self._synthetic = synthetic
        self._nodes: list[AssetGraphNode] = []
        self._edges: list[AssetGraphEdge] = []
        self._gaps: list[GraphGap] = []
        self._node_index: dict[str, AssetGraphNode] = {}
        self._edge_index: dict[str, AssetGraphEdge] = {}
        self._add_economic_node()
        self._add_deployment_node()

    # ------------------------------------------------------------------
    # Fail-closed insert primitives (Correction A, F4)
    # ------------------------------------------------------------------
    def _add_node(self, node: AssetGraphNode) -> None:
        existing = self._node_index.get(node.node_id)
        if existing is not None:
            if (
                existing.node_type is not node.node_type
                or existing.economic_asset_uid != node.economic_asset_uid
                or existing.canonical_asset_key != node.canonical_asset_key
                or existing.source != node.source
                or existing.source_identifier != node.source_identifier
                or existing.display_label != node.display_label
                or dict(existing.metadata) != dict(node.metadata)
            ):
                raise AssetGraphError(
                    f"conflicting node semantics for {node.node_id}",
                    AssetGraphStatus.ASSET_GRAPH_IDENTITY_MISMATCH,
                )
            merged = tuple(sorted(set(existing.evidence_refs) | set(node.evidence_refs)))
            if merged != tuple(existing.evidence_refs):
                object.__setattr__(existing, "evidence_refs", merged)
            return
        self._nodes.append(node)
        self._node_index[node.node_id] = node

    def _add_edge(self, edge: AssetGraphEdge) -> None:
        existing = self._edge_index.get(edge.edge_id)
        if existing is not None:
            if (
                existing.relationship_type is not edge.relationship_type
                or existing.from_node_id != edge.from_node_id
                or existing.to_node_id != edge.to_node_id
                or existing.authority_phase != edge.authority_phase
                or existing.source != edge.source
                or existing.evidence_digest != edge.evidence_digest
                or dict(existing.metadata) != dict(edge.metadata)
                or existing.observed_at != edge.observed_at
            ):
                raise AssetGraphError(
                    f"conflicting edge semantics for {edge.edge_id}",
                    AssetGraphStatus.ASSET_GRAPH_TOPOLOGY_INVALID,
                )
            return
        if edge.from_node_id not in self._node_index:
            raise AssetGraphError(
                f"orphan edge from_node_id {edge.from_node_id}",
                AssetGraphStatus.ASSET_GRAPH_TOPOLOGY_INVALID,
            )
        if edge.to_node_id not in self._node_index:
            raise AssetGraphError(
                f"orphan edge to_node_id {edge.to_node_id}",
                AssetGraphStatus.ASSET_GRAPH_TOPOLOGY_INVALID,
            )
        self._edges.append(edge)
        self._edge_index[edge.edge_id] = edge

    # ------------------------------------------------------------------
    # Seeded identity nodes
    # ------------------------------------------------------------------
    def _add_economic_node(self) -> None:
        node_id = _economic_node_id(self._uid)
        self._add_node(AssetGraphNode(
            node_id=node_id,
            node_type=GraphNodeType.ECONOMIC_ASSET,
            source="R7_CROSS_MARKET_AUTHORITY",
            source_identifier=self._uid,
            economic_asset_uid=self._uid,
            display_label=self._uid,
        ))

    def _add_deployment_node(self) -> None:
        node_id = _deployment_node_id(self._key)
        self._add_node(AssetGraphNode(
            node_id=node_id,
            node_type=GraphNodeType.TOKEN_DEPLOYMENT,
            source="R1_CANONICAL_AUTHORITY",
            source_identifier=self._key.canonical_id,
            economic_asset_uid=self._uid,
            canonical_asset_key=self._key,
            display_label=f"{self._uid} on {self._key.chain_id}",
        ))

    # ------------------------------------------------------------------
    # Source-proven relationship edges (Correction A, F2)
    # ------------------------------------------------------------------
    def add_represented_by_edge(self, identity_evidence: Mapping) -> None:
        econ = _economic_node_id(self._uid)
        dep = _deployment_node_id(self._key)
        eid = _edge_id(GraphRelationshipType.REPRESENTED_BY, econ, dep)
        self._add_edge(AssetGraphEdge(
            edge_id=eid,
            relationship_type=GraphRelationshipType.REPRESENTED_BY,
            from_node_id=econ,
            to_node_id=dep,
            authority_phase="R7",
            source="R7_ECONOMIC_IDENTITY_BINDING",
            evidence_digest=digest_record(identity_evidence),
        ))

    def add_quoted_on_edge(
        self, venue: str, observations: Sequence[Mapping],
    ) -> None:
        if not observations:
            raise AssetGraphError(
                f"QUOTED_ON edge for {venue} requires at least one venue "
                "observation record",
                AssetGraphStatus.ASSET_GRAPH_INPUT_INVALID,
            )
        venue_node_id = _venue_node_id(venue)
        dep = _deployment_node_id(self._key)
        eid = _edge_id(GraphRelationshipType.QUOTED_ON, dep, venue_node_id)
        if venue_node_id not in self._node_index:
            self._add_node(AssetGraphNode(
                node_id=venue_node_id,
                node_type=GraphNodeType.VENUE,
                source="R7_VENUE_OBSERVATION",
                source_identifier=venue,
                display_label=venue,
            ))
        # Exact source records, in canonical order: the digest covers every
        # observation used, independent of caller iteration order.
        record = {
            "venue": venue,
            "observations": sorted(observations, key=_canonical_bytes_key),
        }
        self._add_edge(AssetGraphEdge(
            edge_id=eid,
            relationship_type=GraphRelationshipType.QUOTED_ON,
            from_node_id=dep,
            to_node_id=venue_node_id,
            authority_phase="R7",
            source="R7_VENUE_OBSERVATION",
            evidence_digest=digest_record(record),
        ))

    def add_settlement_node(self, source: str, symbol: str, chain_id: int, address: str) -> None:
        node_id = _settlement_node_id(source, symbol)
        self._add_node(AssetGraphNode(
            node_id=node_id,
            node_type=GraphNodeType.SETTLEMENT_CONTEXT,
            source=source,
            source_identifier=symbol,
            display_label=symbol,
            metadata={"chainId": chain_id, "contractAddress": address},
        ))

    def add_settles_via_edge(self, symbol: str, settlement_evidence: Mapping) -> None:
        dep = _deployment_node_id(self._key)
        node_id = _settlement_node_id("R0", symbol)
        eid = _edge_id(GraphRelationshipType.SETTLES_VIA, dep, node_id)
        self._add_edge(AssetGraphEdge(
            edge_id=eid,
            relationship_type=GraphRelationshipType.SETTLES_VIA,
            from_node_id=dep,
            to_node_id=node_id,
            authority_phase="R0",
            source="R0_SETTLEMENT_REFERENCE",
            evidence_digest=digest_record(settlement_evidence),
        ))

    def add_reference_nodes(
        self, reference_source: str, instrument: str,
        reference_observation: Mapping,
    ) -> None:
        ri_id = _reference_instrument_node_id(reference_source, instrument)
        self._add_node(AssetGraphNode(
            node_id=ri_id,
            node_type=GraphNodeType.REFERENCE_INSTRUMENT,
            source=reference_source,
            source_identifier=instrument,
            economic_asset_uid=self._uid,
            display_label=instrument,
        ))
        rs_id = _reference_source_node_id(reference_source)
        self._add_node(AssetGraphNode(
            node_id=rs_id,
            node_type=GraphNodeType.REFERENCE_SOURCE,
            source=reference_source,
            source_identifier=reference_source,
            display_label=reference_source,
        ))
        record_digest = digest_record(reference_observation)
        eid = _edge_id(GraphRelationshipType.REFERENCED_BY, _economic_node_id(self._uid), ri_id)
        self._add_edge(AssetGraphEdge(
            edge_id=eid,
            relationship_type=GraphRelationshipType.REFERENCED_BY,
            from_node_id=_economic_node_id(self._uid),
            to_node_id=ri_id,
            authority_phase="R4",
            source=reference_source,
            evidence_digest=record_digest,
        ))
        eid2 = _edge_id(GraphRelationshipType.OBSERVED_BY, ri_id, rs_id)
        self._add_edge(AssetGraphEdge(
            edge_id=eid2,
            relationship_type=GraphRelationshipType.OBSERVED_BY,
            from_node_id=ri_id,
            to_node_id=rs_id,
            authority_phase="R4",
            source=reference_source,
            evidence_digest=record_digest,
        ))

    def add_execution_evidence_edge(
        self, venue: str, side: str, notional: str,
        net_edge_state: str, r8_snapshot_digest: str,
    ) -> None:
        """Parent evidence digest is the R8 snapshot; the scenario identity
        (side x notional) is part of both the edge identity and the metadata,
        so the binding stays deterministic and auditable."""
        dep = _deployment_node_id(self._key)
        venue_node = _venue_node_id(venue)
        eid = hashlib.sha256(
            "|".join((
                GraphRelationshipType.HAS_EXECUTION_EVIDENCE.value,
                dep, venue_node, side, notional,
            )).encode("utf-8")
        ).hexdigest()
        self._add_edge(AssetGraphEdge(
            edge_id=eid,
            relationship_type=GraphRelationshipType.HAS_EXECUTION_EVIDENCE,
            from_node_id=dep,
            to_node_id=venue_node,
            authority_phase="R8",
            source="R8_EXECUTION_SIMULATOR",
            evidence_digest=r8_snapshot_digest,
            metadata={
                "side": side,
                "notionalUsd": notional,
                "netEdgeState": net_edge_state,
            },
        ))

    def add_gap(self, gap_kind: GraphGapKind, related_node_id: str | None = None,
                source: str = "R9_GRAPH_BUILDER", reason: str = "") -> None:
        self._gaps.append(GraphGap(
            gap_kind=gap_kind,
            related_node_id=related_node_id,
            source=source,
            reason=reason,
        ))

    # ------------------------------------------------------------------
    # Snapshot assembly
    # ------------------------------------------------------------------
    def build(
        self,
        *,
        generated_at: datetime,
        r7_cross_market_digest: str,
        r8_execution_simulator_digest: str | None = None,
        r3_liquidity_digest: str | None = None,
        upstream_evidence: dict | None = None,
        synthetic: bool = False,
    ) -> AssetGraphSnapshot:
        self._nodes.sort(key=lambda n: (n.node_type.value, n.node_id))
        self._edges.sort(key=lambda e: (
            e.relationship_type.value, e.from_node_id, e.to_node_id, e.edge_id,
        ))
        self._gaps.sort(key=lambda g: (
            g.gap_kind.value, g.related_node_id or "", g.source, g.reason,
        ))
        status = (
            AssetGraphStatus.ASSET_GRAPH_OK
            if not self._gaps
            else AssetGraphStatus.ASSET_GRAPH_PARTIAL
        )
        boundaries = {
            "registryAuthority": "R1_APPLIED",
            "referenceAuthority": "R4_APPLIED",
            "crossMarketAuthority": "R7_APPLIED",
            "executionSimulatorAuthority": "R8_APPLIED",
            "assetGraphAuthority": "R9_APPLIED",
            "modelAuthority": "R10_NOT_YET_APPLIED",
            "verificationAuthority": "R11_NOT_YET_APPLIED",
            "digitalTwinAuthority": "R12_NOT_YET_APPLIED",
        }
        source_digests = {"r7CrossMarketDigest": r7_cross_market_digest}
        if r8_execution_simulator_digest:
            source_digests["r8ExecutionSimulatorDigest"] = r8_execution_simulator_digest
        if r3_liquidity_digest:
            source_digests["r3LiquidityDigest"] = r3_liquidity_digest
        nodes = tuple(self._nodes)
        edges = tuple(self._edges)
        gaps = tuple(self._gaps)
        econ_id = _economic_node_id(self._uid)
        dep_id = _deployment_node_id(self._key)
        edges_by_id = {e.edge_id: e for e in edges}

        # Canonical paths are real topology paths: economic -> deployment ->
        # venue, backed by the REPRESENTED_BY edge and that venue's QUOTED_ON
        # edge. One deterministic path per source-proven venue.
        rep_edges = [
            e for e in edges
            if e.relationship_type is GraphRelationshipType.REPRESENTED_BY
            and e.from_node_id == econ_id and e.to_node_id == dep_id
        ]
        quoted_edges = [
            e for e in edges
            if e.relationship_type is GraphRelationshipType.QUOTED_ON
            and e.from_node_id == dep_id
        ]
        paths: list[AssetGraphPath] = []
        if rep_edges:
            for quoted in quoted_edges:
                path = AssetGraphPath(
                    path_id=f"canonical:{self._uid}:{quoted.to_node_id}",
                    path_type="ECONOMIC_ASSET→TOKEN_DEPLOYMENT→VENUE",
                    node_ids=(econ_id, dep_id, quoted.to_node_id),
                    edge_ids=(rep_edges[0].edge_id, quoted.edge_id),
                )
                validate_path_structure(path.node_ids, path.edge_ids, edges_by_id)
                paths.append(path)
        evidence = {
            "schemaVersion": SCHEMA_VERSION,
            "phase": PHASE,
            "status": status.value,
            "generatedAt": generated_at.isoformat(),
            "gitHead": self._git_head,
            "economicAssetUid": self._uid,
            "nodes": [n.to_evidence_dict() for n in nodes],
            "edges": [e.to_evidence_dict() for e in edges],
            "gaps": [g.to_evidence_dict() for g in gaps],
            "paths": [p.to_evidence_dict() for p in paths],
            "sourceDigests": source_digests,
            "upstreamEvidence": upstream_evidence or {},
            "boundaries": boundaries,
            "synthetic": self._synthetic or synthetic,
        }
        digest = hashlib.sha256(canonical_evidence_bytes(evidence)).hexdigest()
        evidence["r9SnapshotDigest"] = digest
        return AssetGraphSnapshot(
            status=status,
            generated_at=generated_at,
            git_head=self._git_head,
            economic_asset_uid=self._uid,
            nodes=nodes,
            edges=edges,
            gaps=gaps,
            paths=tuple(paths),
            source_digests=source_digests,
            upstream_evidence=upstream_evidence or {},
            boundaries=boundaries,
            synthetic=self._synthetic or synthetic,
            r9_snapshot_digest=digest,
        )
