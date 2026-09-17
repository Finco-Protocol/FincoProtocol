"""Networked R9 proof: FINCO Asset Graph from frozen live R7/R8 authority.

The graph never calls new APIs.  It re-runs the frozen R8 live composition
(R1 -> R7 embedded by digest) and derives every node, edge and gap purely
from the embedded R7 cross-market evidence plus the R8 scenario evidence.

Correction A lineage discipline (F1/F5):
- `sourceDigests["r7CrossMarketDigest"]` is the canonical SHA-256 of the
  COMPLETE embedded r7CrossMarketEvidence and must equal the digest declared
  by the embedded R8 snapshot — a different check from the R7 internal
  `r7SnapshotDigest`, which is independently verified with the frozen R7
  verifier;
- `sourceDigests["r8ExecutionSimulatorDigest"]` binds the embedded R8
  snapshot digest and is independently verified with the frozen R8 verifier;
- semantic identity (economic UID, canonical deployment, scenario bindings)
  must agree across R7/R8/R9 after both digest verifiers pass.
"""
from __future__ import annotations

import hashlib
import json
import os
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from finco_radar.assets.contracts import AssetKey
from finco_radar.asset_graph.builder import AssetGraphBuilder, digest_record
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


def _lineage_failure(detail: str) -> AssetGraphError:
    return AssetGraphError(detail, AssetGraphStatus.ASSET_GRAPH_LINEAGE_MISMATCH)


def _verify_upstream_lineage(
    r8_evidence: dict[str, Any],
) -> tuple[dict[str, Any], str, str, AssetKey]:
    """Digest-level (frozen verifiers) + semantic-level (F5) lineage binding.

    Returns (embedded r7 evidence, canonical R7 source digest, R8 snapshot
    digest, canonical deployment key).
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

    # F1: frozen internal-digest verifiers (independent of each other).
    if not verify_r8_evidence(r8_evidence):
        raise _lineage_failure(
            "embedded R8 evidence fails its r8SnapshotDigest reconstruction"
        )
    if not verify_r7_evidence(r7_evidence):
        raise _lineage_failure(
            "embedded R7 evidence fails its r7SnapshotDigest reconstruction"
        )

    # F1: the R7 SOURCE digest is the canonical hash of the complete embedded
    # R7 evidence and must equal the digest declared by the embedded R8
    # snapshot. Distinct from the internal r7SnapshotDigest verified above.
    r7_source_digest = _canonical_digest(r7_evidence)
    declared_r7_source = (r8_evidence.get("sourceDigests") or {}).get(
        "r7CrossMarketDigest"
    )
    if declared_r7_source != r7_source_digest:
        raise _lineage_failure(
            "canonical digest of embedded r7CrossMarketEvidence "
            f"({r7_source_digest}) does not equal the R8-declared "
            f"r7CrossMarketDigest ({declared_r7_source})"
        )

    # F1: bind the R8 snapshot digest explicitly in R9 sourceDigests.
    r8_snapshot_digest = r8_evidence.get("r8SnapshotDigest")
    if not r8_snapshot_digest:
        raise _lineage_failure("embedded R8 evidence carries no r8SnapshotDigest")

    # F1 (completeness): the R3 source digest declared by R8 must reconstruct
    # over the embedded R3 evidence.
    r3_declared = (r8_evidence.get("sourceDigests") or {}).get("r3LiquidityDigest")
    r3_embedded = (r8_evidence.get("upstreamEvidence") or {}).get("r3LiquidityEvidence")
    if r3_declared is None or r3_embedded is None:
        raise _lineage_failure("embedded R3 lineage pair missing")
    if _canonical_digest(r3_embedded) != r3_declared:
        raise _lineage_failure("r3LiquidityDigest does not reconstruct")

    # ---- F5: semantic R7/R8 identity binding --------------------------
    uid = r7_evidence.get("economicAssetUid")
    if not uid or r8_evidence.get("economicAssetUid") != uid:
        raise _lineage_failure(
            "R8 economicAssetUid does not equal the embedded R7 economicAssetUid"
        )
    try:
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
    r8_key = r8_evidence.get("canonicalAssetKey") or {}
    if (
        r8_key.get("chainId") != key.chain_id
        or str(r8_key.get("contractAddress", "")).lower()
        != key.contract_address.lower()
    ):
        raise _lineage_failure(
            "R8 canonicalAssetKey does not equal the R9/R7 canonical deployment"
        )
    binding_keys = (
        (r7_evidence.get("identityBinding") or {}).get("canonicalKeys") or []
    )
    key_hits = sum(
        1 for k in binding_keys
        if k.get("chainId") == key.chain_id
        and str(k.get("contractAddress", "")).lower() == key.contract_address.lower()
    )
    if key_hits != 1:
        raise _lineage_failure(
            "R9 deployment appears "
            f"{key_hits} times in the embedded R7 identityBinding (expected 1)"
        )
    if (
        token_layer.get("chainId") != key.chain_id
        or str(token_layer.get("contractAddress", "")).lower()
        != key.contract_address.lower()
    ):
        raise _lineage_failure(
            "R7 token layer disagrees with the canonical AssetKey"
        )
    venue_names = {
        row.get("venue")
        for row in (r7_evidence.get("layers") or {}).get("venues") or []
    }
    scenarios = r8_evidence.get("scenarios") or []
    if not scenarios:
        raise _lineage_failure(
            "embedded R8 evidence carries no execution scenarios"
        )
    for scenario in scenarios:
        entry = scenario.get("scenario") or {}
        if entry.get("economicAssetUid") != uid:
            raise _lineage_failure(
                "R8 scenario economicAssetUid does not equal the canonical "
                "economic UID"
            )
        if (
            entry.get("chainId") != key.chain_id
            or str(entry.get("contractAddress", "")).lower()
            != key.contract_address.lower()
        ):
            raise _lineage_failure(
                "R8 scenario canonicalAssetKey does not equal the canonical "
                "deployment"
            )
        if entry.get("quoteSource") not in venue_names:
            raise _lineage_failure(
                f"R8 scenario quoteSource {entry.get('quoteSource')!r} is not "
                "a venue observed in the embedded R7 evidence"
            )
    return r7_evidence, r7_source_digest, r8_snapshot_digest, key


def build_graph_from_upstream(
    *,
    r8_evidence: dict[str, Any],
    git_head: str,
    generated_at: datetime,
) -> dict[str, Any]:
    """Derive the R9 graph deterministically from frozen R7/R8 evidence dicts.

    Fail-closed: upstream evidence must reconstruct its recorded digests AND
    agree semantically before any node or edge is derived from it.
    """
    r7_evidence, r7_source_digest, r8_snapshot_digest, key = (
        _verify_upstream_lineage(r8_evidence)
    )
    uid = r7_evidence["economicAssetUid"]
    builder = AssetGraphBuilder(
        economic_asset_uid=uid, canonical_asset_key=key, git_head=git_head,
    )
    builder.add_represented_by_edge(r7_evidence["identityBinding"])

    # VENUE nodes + QUOTED_ON edges from the exact R7 venue observation
    # records (one edge per venue; the digest covers every observation row).
    venue_rows = (r7_evidence["layers"] or {}).get("venues") or []
    by_venue: dict[str, list[Mapping]] = {}
    for row in venue_rows:
        by_venue.setdefault(row["venue"], []).append(row)
    for venue in sorted(by_venue):
        builder.add_quoted_on_edge(venue, by_venue[venue])

    # Settlement context (R0 authority, carried through R7 evidence).
    settlement = (r7_evidence["layers"] or {}).get("settlement")
    if settlement is not None:
        builder.add_settlement_node(
            source="R0",
            symbol=settlement["settlementAssetSymbol"],
            chain_id=int(settlement["chainId"]),
            address=str(settlement["contractAddress"]),
        )
        builder.add_settles_via_edge(
            settlement["settlementAssetSymbol"], settlement,
        )

    # Reference instrument + source (R4 authority, carried through R7
    # evidence); the oracle observation record binds both edges.
    oracle = (r7_evidence["layers"] or {}).get("oracleReference")
    if oracle is not None and oracle.get("instrument") and oracle.get("source"):
        builder.add_reference_nodes(
            oracle["source"], oracle["instrument"], oracle,
        )

    # HAS_EXECUTION_EVIDENCE edges from the R8 scenarios (parent evidence
    # digest = R8 snapshot; scenario identity retained in metadata).
    for scenario in r8_evidence["scenarios"]:
        entry = scenario["scenario"]
        builder.add_execution_evidence_edge(
            venue=entry["quoteSource"],
            side=entry["side"],
            notional=entry["requestedNotionalUsd"],
            net_edge_state=scenario["netEdgeState"],
            r8_snapshot_digest=r8_snapshot_digest,
        )

    # Explicit graph gaps: absence of authority is evidence, never a synthetic edge.
    underlying = (r7_evidence["layers"] or {}).get("underlying")
    if underlying is None or underlying.get("status") != "AVAILABLE":
        builder.add_gap(
            GraphGapKind.UNDERLYING_RELATIONSHIP_UNAVAILABLE,
            related_node_id=None,
            source="R7_CROSS_MARKET_AUTHORITY",
            reason="no official underlying-market source exists for this asset",
        )
    external_oracle = (r7_evidence["layers"] or {}).get("externalOracle")
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
    if len(by_venue) < 2:
        builder.add_gap(
            GraphGapKind.SECOND_VENUE_UNAVAILABLE,
            related_node_id=None,
            source="R7_VENUE_OBSERVATION",
            reason="only one venue observation exists in the frozen R7 evidence",
        )

    snapshot = builder.build(
        generated_at=generated_at,
        r7_cross_market_digest=r7_source_digest,
        r8_execution_simulator_digest=r8_snapshot_digest,
        r3_liquidity_digest=r8_evidence["sourceDigests"]["r3LiquidityDigest"],
        upstream_evidence={"r8ExecutionEvidence": r8_evidence},
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
            "sourceDigests.r7CrossMarketDigest is the canonical digest of the "
            "complete embedded R7 evidence (equality with the R8-declared "
            "digest is enforced); the R7 internal r7SnapshotDigest and the R8 "
            "snapshot digest are verified independently with the frozen "
            "verifiers. Nodes/edges are derived only from that frozen "
            "evidence; absent relationships are recorded as graph gaps."
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
