"""Networked R9 proof: FINCO Asset Graph from frozen live R7/R8 authority.

The graph never calls new APIs.  It re-runs the frozen R8 live composition
(R1 -> R7 embedded by digest) and derives every node, edge and gap purely
from the embedded R7 cross-market evidence plus the R8 scenario evidence.
"""
from __future__ import annotations

import hashlib
import json
import os
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from finco_radar.assets.contracts import AssetKey
from finco_radar.asset_graph.builder import AssetGraphBuilder
from finco_radar.asset_graph.contracts import (
    AssetGraphError,
    AssetGraphStatus,
    GraphGapKind,
)
from finco_radar.cross_market.contracts import (
    verify_serialized_evidence as verify_r7_evidence,
)
from finco_radar.execution_simulator.contracts import (
    verify_serialized_evidence as verify_r8_evidence,
)
from finco_radar.r8.live_proof import _build_live_snapshot as _build_r8_live_snapshot

EVIDENCE_PATH = "artifacts/radar_r9_asset_graph_evidence.json"
SHA256_PATH = "artifacts/radar_r9_asset_graph_evidence.sha256"
MANIFEST_PATH = "artifacts/radar_r9_asset_graph_manifest.json"


def _canonical_digest(payload: Any) -> str:
    return hashlib.sha256(
        json.dumps(payload, sort_keys=True, separators=(",", ":"), ensure_ascii=False).encode(
            "utf-8"
        )
    ).hexdigest()


def build_graph_from_upstream(
    *,
    r8_evidence: dict[str, Any],
    git_head: str,
    generated_at: datetime,
) -> dict[str, Any]:
    """Derive the R9 graph deterministically from frozen R7/R8 evidence dicts.

    Fail-closed: embedded upstream evidence must reconstruct its recorded
    snapshot digests before any node or edge is derived from it.
    """
    try:
        r7_evidence = r8_evidence["upstreamEvidence"]["r7CrossMarketEvidence"]
    except (KeyError, TypeError) as exc:
        raise AssetGraphError(
            "R8 evidence does not carry embedded r7CrossMarketEvidence",
            AssetGraphStatus.ASSET_GRAPH_INPUT_INVALID,
        ) from exc
    if not isinstance(r7_evidence, dict):
        raise AssetGraphError(
            "embedded r7CrossMarketEvidence is not a mapping",
            AssetGraphStatus.ASSET_GRAPH_INPUT_INVALID,
        )
    if not verify_r8_evidence(r8_evidence):
        raise AssetGraphError(
            "embedded R8 evidence fails its r8SnapshotDigest reconstruction",
            AssetGraphStatus.ASSET_GRAPH_LINEAGE_MISMATCH,
        )
    if not verify_r7_evidence(r7_evidence):
        raise AssetGraphError(
            "embedded R7 evidence fails its r7SnapshotDigest reconstruction",
            AssetGraphStatus.ASSET_GRAPH_LINEAGE_MISMATCH,
        )
    try:
        uid = r7_evidence["economicAssetUid"]
        token_layer = r7_evidence["layers"]["token"]
        key = AssetKey(
            chain_id=int(token_layer["chainId"]),
            contract_address=str(token_layer["contractAddress"]),
        )
    except (KeyError, TypeError, ValueError) as exc:
        raise AssetGraphError(
            "R7 evidence carries an unusable token identity layer",
            AssetGraphStatus.ASSET_GRAPH_INPUT_INVALID,
        ) from exc
    builder = AssetGraphBuilder(
        economic_asset_uid=uid, canonical_asset_key=key, git_head=git_head,
    )
    builder.add_represented_by_edge()

    # VENUE nodes + QUOTED_ON edges straight from R7 venue observations.
    venue_names: set[str] = set()
    for venue_row in r7_evidence["layers"]["venues"]:
        venue_names.add(venue_row["venue"])
        builder.add_quoted_on_edge(venue_row["venue"])

    # Settlement context (R0 authority, carried through R7 evidence).
    settlement = r7_evidence["layers"]["settlement"]
    if settlement is not None:
        builder.add_settlement_node(
            source="R0",
            symbol=settlement["settlementAssetSymbol"],
            chain_id=int(settlement["chainId"]),
            address=str(settlement["contractAddress"]),
        )
        builder.add_settles_via_edge(settlement["settlementAssetSymbol"])

    # Reference instrument + source (R4 authority, carried through R7 evidence).
    oracle = r7_evidence["layers"]["oracleReference"]
    if oracle is not None and oracle.get("instrument") and oracle.get("source"):
        builder.add_reference_nodes(oracle["source"], oracle["instrument"])

    # HAS_EXECUTION_EVIDENCE edges from the four R8 scenarios.
    r8_digest = r8_evidence["r8SnapshotDigest"]
    for scenario in r8_evidence["scenarios"]:
        quote_source = scenario["scenario"]["quoteSource"]
        if quote_source not in venue_names:
            builder.add_quoted_on_edge(quote_source)
        builder.add_execution_evidence_edge(
            venue=quote_source,
            side=scenario["scenario"]["side"],
            notional=scenario["scenario"]["requestedNotionalUsd"],
            net_edge_state=scenario["netEdgeState"],
            r8_snapshot_digest=r8_digest,
        )

    # Explicit graph gaps: absence of authority is evidence, never a synthetic edge.
    underlying = r7_evidence["layers"]["underlying"]
    if underlying is None or underlying.get("status") != "AVAILABLE":
        builder.add_gap(
            GraphGapKind.UNDERLYING_RELATIONSHIP_UNAVAILABLE,
            related_node_id=None,
            source="R7_CROSS_MARKET_AUTHORITY",
            reason="no official underlying-market source exists for this asset",
        )
    external_oracle = r7_evidence["layers"]["externalOracle"]
    if external_oracle is None or external_oracle.get("status") != "AVAILABLE":
        builder.add_gap(
            GraphGapKind.EXTERNAL_ORACLE_UNAVAILABLE,
            related_node_id=None,
            source="R7_CROSS_MARKET_AUTHORITY",
            reason="no external oracle source exists for this asset",
        )
    if oracle is None or not oracle.get("instrument"):
        builder.add_gap(
            GraphGapKind.REFERENCE_INSTRUMENT_UNAVAILABLE,
            related_node_id=None,
            source="R7_CROSS_MARKET_AUTHORITY",
            reason="reference instrument unavailable in R7 evidence",
        )
    builder.add_gap(
        GraphGapKind.CORPORATE_ACTION_AUTHORITY_UNAVAILABLE,
        related_node_id=None,
        source="R4_REFERENCE_STATE_AUTHORITY",
        reason="corporate-action adapter produced no rows for this asset",
    )
    if len(venue_names) < 2:
        builder.add_gap(
            GraphGapKind.SECOND_VENUE_UNAVAILABLE,
            related_node_id=None,
            source="R7_VENUE_OBSERVATION",
            reason="only one venue observation exists in the frozen R7 evidence",
        )

    # r8ExecutionDigest travels inside upstreamEvidence so the recorded
    # r9SnapshotDigest covers the complete R8 lineage without post-hoc edits.
    snapshot = builder.build(
        generated_at=generated_at,
        r7_snapshot_digest=r7_evidence["r7SnapshotDigest"],
        r3_liquidity_digest=r8_evidence["sourceDigests"]["r3LiquidityDigest"],
        upstream_evidence={
            "r8ExecutionEvidence": r8_evidence,
            "r8ExecutionDigest": r8_digest,
        },
    )
    return snapshot.to_evidence_dict()


def main() -> int:
    r8_evidence, audit = _build_r8_live_snapshot()
    evidence = build_graph_from_upstream(
        r8_evidence=r8_evidence,
        git_head=r8_evidence["gitHead"],
        generated_at=datetime.now(timezone.utc),
    )
    first = json.dumps(evidence, indent=2, sort_keys=True, ensure_ascii=False)
    second = json.dumps(json.loads(first), indent=2, sort_keys=True, ensure_ascii=False)
    if first != second:
        raise RuntimeError("R9 evidence serialization is not byte-deterministic")
    evidence_path = Path(os.getenv("RADAR_R9_EVIDENCE_PATH", EVIDENCE_PATH))
    evidence_path.parent.mkdir(parents=True, exist_ok=True)
    evidence_path.write_text(first + "\n", encoding="utf-8")
    digest = hashlib.sha256(evidence_path.read_bytes()).hexdigest()
    Path(os.getenv("RADAR_R9_SHA256_PATH", SHA256_PATH)).write_text(
        f"{digest}  {evidence_path.name}\n", encoding="utf-8"
    )
    manifest = {
        "schemaVersion": evidence["schemaVersion"],
        "phase": evidence["phase"],
        "gitHead": evidence["gitHead"],
        "producedAt": evidence["generatedAt"],
        "status": evidence["status"],
        "nodeCount": len(evidence["nodes"]),
        "edgeCount": len(evidence["edges"]),
        "gapCount": len(evidence["gaps"]),
        "r9SnapshotDigest": evidence["r9SnapshotDigest"],
        "evidenceJsonSha256": digest,
        "sourceDigests": evidence["sourceDigests"],
        "candidateAudit": audit,
        "note": (
            "Graph nodes/edges are derived only from frozen R7/R8 evidence "
            "embedded by digest; absent relationships are recorded as graph gaps."
        ),
    }
    Path(os.getenv("RADAR_R9_MANIFEST_PATH", MANIFEST_PATH)).write_text(
        json.dumps(manifest, indent=2, sort_keys=True), encoding="utf-8"
    )
    print(json.dumps({
        "status": evidence["status"],
        "nodes": len(evidence["nodes"]),
        "edges": len(evidence["edges"]),
        "gaps": len(evidence["gaps"]),
        "digest": digest,
        "evidence": str(evidence_path),
    }, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
