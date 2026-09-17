"""Typed query helpers for the FINCO Asset Graph (R9).

These helpers return immutable deterministic results from a pre-built
AssetGraphSnapshot. They never create new relationships, never perform
external I/O, and never recalculate R7/R8 economics.
"""
from __future__ import annotations

from typing import Sequence

from finco_radar.assets.contracts import AssetKey

from .contracts import (
    AssetGraphEdge,
    AssetGraphNode,
    AssetGraphPath,
    AssetGraphSnapshot,
    GraphNodeType,
    GraphRelationshipType,
)


def nodes_for_economic_asset(
    snapshot: AssetGraphSnapshot, uid: str
) -> tuple[AssetGraphNode, ...]:
    return tuple(
        n for n in snapshot.nodes if n.economic_asset_uid == uid
    )


def deployments_for_economic_asset(
    snapshot: AssetGraphSnapshot, uid: str
) -> tuple[AssetGraphNode, ...]:
    return tuple(
        n for n in snapshot.nodes
        if n.node_type is GraphNodeType.TOKEN_DEPLOYMENT
        and n.economic_asset_uid == uid
    )


def venues_for_deployment(
    snapshot: AssetGraphSnapshot, deployment_node_id: str
) -> tuple[AssetGraphNode, ...]:
    venue_ids = {
        e.to_node_id
        for e in snapshot.edges
        if e.relationship_type is GraphRelationshipType.QUOTED_ON
        and e.from_node_id == deployment_node_id
    }
    return tuple(n for n in snapshot.nodes if n.node_id in venue_ids)


def reference_sources_for_asset(
    snapshot: AssetGraphSnapshot, uid: str
) -> tuple[AssetGraphNode, ...]:
    ri_ids = {
        e.to_node_id
        for e in snapshot.edges
        if e.relationship_type is GraphRelationshipType.REFERENCED_BY
        and e.from_node_id == f"economic:{uid}"
    }
    rs_ids = {
        e.to_node_id
        for e in snapshot.edges
        if e.relationship_type is GraphRelationshipType.OBSERVED_BY
        and e.from_node_id in ri_ids
    }
    return tuple(n for n in snapshot.nodes if n.node_id in rs_ids)


def execution_evidence_for(
    snapshot: AssetGraphSnapshot,
    deployment_node_id: str,
    venue_node_id: str,
) -> tuple[AssetGraphEdge, ...]:
    return tuple(
        e for e in snapshot.edges
        if e.relationship_type is GraphRelationshipType.HAS_EXECUTION_EVIDENCE
        and e.from_node_id == deployment_node_id
        and e.to_node_id == venue_node_id
    )


def canonical_asset_path(
    snapshot: AssetGraphSnapshot,
    uid: str,
    deployment_node_id: str,
    venue_node_id: str,
) -> AssetGraphPath | None:
    """Return the canonical economic→deployment→venue path if it exists."""
    econ_id = f"economic:{uid}"
    rep_edges = [
        e for e in snapshot.edges
        if e.relationship_type is GraphRelationshipType.REPRESENTED_BY
        and e.from_node_id == econ_id and e.to_node_id == deployment_node_id
    ]
    if not rep_edges:
        return None
    quote_edges = [
        e for e in snapshot.edges
        if e.relationship_type is GraphRelationshipType.QUOTED_ON
        and e.from_node_id == deployment_node_id and e.to_node_id == venue_node_id
    ]
    if not quote_edges:
        return None
    return AssetGraphPath(
        path_id=f"canonical:{uid}:{deployment_node_id}:{venue_node_id}",
        path_type="ECONOMIC_ASSET→TOKEN_DEPLOYMENT→VENUE",
        node_ids=(econ_id, deployment_node_id, venue_node_id),
        edge_ids=(rep_edges[0].edge_id, quote_edges[0].edge_id),
    )
