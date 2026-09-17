"""Focused, fully offline R9 asset-graph tests.

Deterministic synthetic fixtures only.  The graph is derived from frozen
R7/R8 evidence dicts; absent relationships must appear as explicit graph
gaps and never as synthetic edges.
"""
from __future__ import annotations

import copy
import hashlib
import json
from datetime import datetime, timezone
from decimal import Decimal

import pytest

from finco_radar.asset_graph.builder import AssetGraphBuilder
from finco_radar.asset_graph.contracts import (
    PHASE,
    SCHEMA_VERSION,
    AssetGraphError,
    AssetGraphSnapshot,
    AssetGraphStatus,
    GraphGapKind,
    GraphNodeType,
    GraphRelationshipType,
    canonical_evidence_bytes,
    deep_freeze,
    verify_r9_snapshot_digest,
)
from finco_radar.asset_graph.queries import (
    canonical_asset_path,
    deployments_for_economic_asset,
    execution_evidence_for,
    nodes_for_economic_asset,
    reference_sources_for_asset,
    venues_for_deployment,
)
from finco_radar.assets.contracts import AssetKey
from finco_radar.cross_market.contracts import (
    verify_serialized_evidence as verify_r7,
)
from finco_radar.execution_simulator.contracts import (
    verify_serialized_evidence as verify_r8,
)
from finco_radar.execution_simulator.engine import build_execution_simulation
from finco_radar.quotes.contracts import QuoteSide
from finco_radar.r9.live_proof import build_graph_from_upstream

T = timezone.utc
NOW = datetime(2026, 9, 17, 12, 0, tzinfo=T)
UID = "AAPL"
KEY = AssetKey(4663, "0x" + "aa" * 20)
OTHER_KEY = AssetKey(137, "0x" + "bb" * 20)
VENUE = "LIFI_V1_QUOTE"
VENUE_B = "VENUE_B"
R8_DIGEST = "1" * 64
DEFAULT_LABELS = [
    "ORACLE_REFERENCE→VENUE[DEX:BUY:100]",
    "ORACLE_REFERENCE→VENUE[DEX:BUY:1000]",
    "ORACLE_REFERENCE→VENUE[DEX:SELL:100]",
    "ORACLE_REFERENCE→VENUE[DEX:SELL:1000]",
]


def _digest(payload) -> str:
    return hashlib.sha256(
        json.dumps(payload, sort_keys=True, separators=(",", ":"),
                   ensure_ascii=False).encode("utf-8")
    ).hexdigest()


# --------------------------------------------------------------------------
# Synthetic upstream evidence (full R7 shape + real R8 engine output)
# --------------------------------------------------------------------------

def _rich_r7_evidence(
    uid: str = UID,
    key: AssetKey = KEY,
    *,
    labels=None,
    venues=(VENUE,),
    with_settlement: bool = True,
    with_oracle: bool = True,
    underlying_status=None,
) -> dict:
    labels = DEFAULT_LABELS if labels is None else labels
    evidence = {
        "schemaVersion": "radar-r7-cross-market-v1",
        "phase": "R7",
        "status": "CROSS_MARKET_OK",
        "economicAssetUid": uid,
        "canonicalAssetKey": {"chainId": key.chain_id,
                              "contractAddress": key.contract_address},
        "identityBinding": {
            "economicAssetUid": uid,
            "canonicalKeys": [
                {"chainId": key.chain_id, "contractAddress": key.contract_address}
            ],
            "referenceIdentifiers": [uid],
            "source": "SYNTHETIC_TEST_REGISTRY",
        },
        "layers": {
            "underlying": (
                None if underlying_status is None
                else {"status": underlying_status, "source": "X",
                      "price": None, "currency": None, "observedAt": None,
                      "instrument": None, "multiplier": None, "usable": None,
                      "assetUid": None, "assetKey": None}
            ),
            "fx": {"present": False, "sourceCurrency": None,
                   "targetCurrency": None, "rate": None, "source": None,
                   "observedAt": None},
            "oracleReference": (
                {"status": "AVAILABLE", "source": "ROBINHOOD_RHJ",
                 "price": "100", "currency": "USD",
                 "observedAt": NOW.isoformat(), "instrument": uid,
                 "multiplier": "1", "usable": True, "assetUid": uid,
                 "assetKey": f"{key.chain_id}:{key.contract_address}"}
                if with_oracle else None
            ),
            "externalOracle": None,
            "token": {
                "economicAssetUid": uid,
                "chainId": key.chain_id,
                "contractAddress": key.contract_address,
                "symbol": uid,
                "multiplier": "1",
                "representationStatus": "ACTIVE",
                "referenceUsable": True,
                "observedPrice": None,
                "currency": "USD",
                "observedAt": None,
            },
            "venues": [
                {
                    "venue": v,
                    "side": "BUY",
                    "notionalUsd": "100",
                    "price": "101",
                    "currency": "USD",
                    "observedAt": NOW.isoformat(),
                    "source": "R0_EXECUTION_QUOTE_VIA_R3_LIQUIDITY",
                    "chainId": key.chain_id,
                    "contractAddress": key.contract_address,
                    "gapBps": "100",
                    "routeSignature": "SYNTH:ROUTE",
                    "rawEvidence": {},
                }
                for v in venues
            ],
            "settlement": (
                {
                    "settlementAssetSymbol": "USDG",
                    "chainId": 4663,
                    "contractAddress": "0x" + "cc" * 20,
                    "settlementCurrency": "USD",
                    "transferRequired": None,
                    "authorityStatus": "CONTEXT_ONLY",
                    "resolved": True,
                }
                if with_settlement else None
            ),
        },
        "dislocationComponents": [
            {"label": label, "fromLayer": "ORACLE_REFERENCE", "toLayer": "VENUE",
             "deltaBps": "-16.20146584303593196445791843"}
            for label in labels
        ],
        "attributionState": "MULTI_LAYER_DISLOCATION" if labels else "ATTRIBUTION_UNAVAILABLE",
        "boundaries": {"crossMarketAuthority": "R7_APPLIED"},
    }
    evidence["r7SnapshotDigest"] = _digest(evidence)
    return evidence


def _r8_policy():
    from finco_radar.execution_simulator.contracts import SimulationTimingPolicy
    return SimulationTimingPolicy(
        max_cost_evidence_age_seconds=Decimal("600"),
        max_settlement_evidence_age_seconds=Decimal("600"),
    )


def _r8_scenario(side, notional, uid=UID, key=KEY, venue=VENUE):
    from finco_radar.execution_simulator.contracts import (
        ExecutionMode, ExecutionScenario,
    )
    return ExecutionScenario(
        economic_asset_uid=uid,
        canonical_asset_key=key,
        side=side,
        requested_notional_usd=Decimal(notional),
        quote_source=venue,
        execution_mode=ExecutionMode.REFERENCE_RELATIVE,
        r7_component_label=f"ORACLE_REFERENCE→VENUE[DEX:{side.value}:{notional}]",
        as_of=NOW,
    )


def _r8_quote_row(side, notional):
    from finco_radar.execution_simulator.contracts import (
        CostTreatmentState, ScenarioQuoteEvidence,
    )
    base = dict(
        side=side,
        requested_notional_usd=Decimal(notional),
        token_amount=Decimal("10") if notional == "1000" else Decimal("1"),
        reference_price_usd_per_token=Decimal("100"),
        quote_observed_at=NOW,
        reference_generated_at=NOW,
        settlement_observed_at=NOW,
        canonical_asset_key=KEY,
        venue=VENUE,
        route_signature="SYNTH:ROUTE",
        route_changed=False,
        provider_fee_usd=Decimal("0.10"),
        provider_gas_usd=None,
        provider_cost_treatment=CostTreatmentState.EVIDENCE_ONLY_INCLUSION_UNRESOLVED,
        r0_quote_evidence={"synthetic": True},
        r2_gap_evidence={"synthetic": True},
    )
    if side is QuoteSide.BUY:
        # BUY handshake: gross (benchmark - settlement) must equal -gap.
        base["r2_gap_bps"] = Decimal("200") if notional == "1000" else Decimal("100")
        base["settlement_amount_usd"] = (
            Decimal("1020") if notional == "1000" else Decimal("101")
        )
    else:
        # SELL handshake: gross (settlement - benchmark) must equal +gap.
        base["r2_gap_bps"] = Decimal("-200") if notional == "1000" else Decimal("-100")
        base["settlement_amount_usd"] = (
            Decimal("980") if notional == "1000" else Decimal("99")
        )
    return ScenarioQuoteEvidence(**base)


def _r8_evidence(uid=UID, key=KEY, *, labels=None, venues=(VENUE,),
                 underlying_status=None) -> dict:
    """Real R8 engine output carrying the rich R7 evidence by digest."""
    labels = DEFAULT_LABELS if labels is None else labels
    r7 = _rich_r7_evidence(uid=uid, key=key, labels=labels, venues=venues,
                           underlying_status=underlying_status)
    combos = (
        (QuoteSide.BUY, "100"), (QuoteSide.BUY, "1000"),
        (QuoteSide.SELL, "100"), (QuoteSide.SELL, "1000"),
    )
    r3_evidence = {
        "status": "PASS",
        "asset": {
            "assetUid": uid,
            "canonicalKey": f"{key.chain_id}:{key.contract_address}",
            "symbol": uid,
            "chainId": key.chain_id,
            "contractAddress": key.contract_address,
        },
    }
    snapshot = build_execution_simulation(
        economic_asset_uid=uid,
        canonical_asset_key=key,
        scenarios=[_r8_scenario(s, n, uid=uid, key=key) for s, n in combos],
        quote_evidence=[_r8_quote_row(s, n) for s, n in combos],
        policy=_r8_policy(),
        upstream_evidence={
            "r7CrossMarketEvidence": r7,
            "r3LiquidityEvidence": r3_evidence,
        },
        source_digests={
            "r7CrossMarketDigest": _digest(r7),
            "r3LiquidityDigest": _digest(r3_evidence),
        },
        synthetic=True,
        generated_at=NOW,
    )
    return snapshot.to_evidence_dict()


# --------------------------------------------------------------------------
# Contracts, deep freeze, digests
# --------------------------------------------------------------------------

def test_c01_deep_freeze_returns_immutable_mapping():
    frozen = deep_freeze({"a": {"b": 1}})
    assert isinstance(frozen, type(__import__("types").MappingProxyType({})))
    with pytest.raises(TypeError):
        frozen["a"]["c"] = 2  # type: ignore[index]


def test_c02_deep_freeze_converts_sequences_to_tuples():
    frozen = deep_freeze({"list": [1, 2], "nested": [{"x": [3]}]})
    assert isinstance(frozen["list"], tuple)
    assert isinstance(frozen["nested"][0]["x"], tuple)


def test_c03_node_frozen_rejects_mutation():
    from finco_radar.asset_graph.contracts import AssetGraphNode
    node = AssetGraphNode(
        node_id="economic:AAPL", node_type=GraphNodeType.ECONOMIC_ASSET,
        source="R7_CROSS_MARKET_AUTHORITY", source_identifier="AAPL",
        economic_asset_uid="AAPL", display_label="AAPL",
    )
    with pytest.raises(Exception):
        node.display_label = "X"  # type: ignore[misc]


def test_c04_edge_frozen_rejects_mutation():
    from finco_radar.asset_graph.contracts import AssetGraphEdge
    edge = AssetGraphEdge(
        edge_id="e", relationship_type=GraphRelationshipType.REPRESENTED_BY,
        from_node_id="a", to_node_id="b", authority_phase="R7",
        source="s", evidence_digest="d",
    )
    with pytest.raises(Exception):
        edge.authority_phase = "R0"  # type: ignore[misc]


def test_c05_canonical_evidence_bytes_is_key_order_independent():
    assert canonical_evidence_bytes({"a": 1, "b": 2}) == canonical_evidence_bytes(
        {"b": 2, "a": 1}
    )


def test_c06_asset_graph_error_carries_status():
    err = AssetGraphError("boom", AssetGraphStatus.ASSET_GRAPH_TOPOLOGY_INVALID)
    assert err.status is AssetGraphStatus.ASSET_GRAPH_TOPOLOGY_INVALID
    assert isinstance(err, ValueError)


def test_c07_snapshot_frozen_rejects_mutation():
    snapshot = _populated_snapshot()
    with pytest.raises(Exception):
        snapshot.status = AssetGraphStatus.ASSET_GRAPH_OK  # type: ignore[misc]


def test_c08_snapshot_upstream_evidence_deep_frozen():
    payload = {"r8": {"inner": [1, 2]}}
    snapshot = _simple_snapshot(upstream=payload)
    payload["r8"]["inner"].append(3)
    assert snapshot.upstream_evidence["r8"]["inner"] == (1, 2)


def _simple_snapshot(upstream=None, gaps=()):
    builder = AssetGraphBuilder(economic_asset_uid=UID, canonical_asset_key=KEY)
    builder.add_represented_by_edge()
    for kind, reason in gaps:
        builder.add_gap(kind, reason=reason)
    return builder.build(
        generated_at=NOW, r7_snapshot_digest="d" * 64, upstream_evidence=upstream,
    )


def _populated_snapshot():
    builder = AssetGraphBuilder(economic_asset_uid=UID, canonical_asset_key=KEY)
    builder.add_represented_by_edge()
    builder.add_quoted_on_edge(VENUE)
    builder.add_settlement_node("R0", "USDG", 4663, "0x" + "cc" * 20)
    builder.add_settles_via_edge("USDG")
    builder.add_reference_nodes("ROBINHOOD_RHJ", UID)
    builder.add_execution_evidence_edge(VENUE, "BUY", "100", "BLOCKED", R8_DIGEST)
    return builder.build(generated_at=NOW, r7_snapshot_digest="d" * 64)


def test_c09_verify_r9_snapshot_digest_accepts_valid_snapshot():
    assert verify_r9_snapshot_digest(_populated_snapshot()) is True


def test_c10_verify_r9_snapshot_digest_rejects_tampered_evidence():
    snapshot = _populated_snapshot()
    evidence = snapshot.to_evidence_dict()
    evidence["economicAssetUid"] = "TAMPERED"
    material = dict(evidence)
    recorded = material.pop("r9SnapshotDigest")
    recomputed = hashlib.sha256(canonical_evidence_bytes(material)).hexdigest()
    assert recorded != recomputed


# --------------------------------------------------------------------------
# Deterministic identity
# --------------------------------------------------------------------------

def test_d01_economic_node_id_derived_from_uid():
    snapshot = _simple_snapshot()
    econ = [n for n in snapshot.nodes
            if n.node_type is GraphNodeType.ECONOMIC_ASSET]
    assert [n.node_id for n in econ] == [f"economic:{UID}"]


def test_d02_deployment_node_id_derived_from_chain_and_address():
    snapshot = _simple_snapshot()
    dep = deployments_for_economic_asset(snapshot, UID)
    assert [n.node_id for n in dep] == [
        f"deployment:{KEY.chain_id}:{KEY.contract_address}"
    ]


def test_d03_different_uid_produces_different_node_ids():
    a = AssetGraphBuilder(economic_asset_uid="AAPL", canonical_asset_key=KEY)
    b = AssetGraphBuilder(economic_asset_uid="NVDA", canonical_asset_key=KEY)
    assert a._nodes[0].node_id != b._nodes[0].node_id


def test_d04_different_key_produces_different_deployment_node():
    a = AssetGraphBuilder(economic_asset_uid=UID, canonical_asset_key=KEY)
    b = AssetGraphBuilder(economic_asset_uid=UID, canonical_asset_key=OTHER_KEY)
    assert a._nodes[1].node_id != b._nodes[1].node_id


def test_d05_edge_id_is_stable_hash_of_rel_from_to():
    raw = f"{GraphRelationshipType.REPRESENTED_BY.value}|economic:{UID}|dep"
    assert hashlib.sha256(raw.encode("utf-8")).hexdigest() == getattr(
        __import__("finco_radar.asset_graph.builder", fromlist=["_edge_id"]),
        "_edge_id",
    )(GraphRelationshipType.REPRESENTED_BY, f"economic:{UID}", "dep")


def test_d06_same_graph_built_twice_has_identical_digest():
    a = _populated_snapshot()
    b = _populated_snapshot()
    assert a.r9_snapshot_digest == b.r9_snapshot_digest


def test_d07_gap_order_does_not_change_digest():
    kinds = [GraphGapKind.UNDERLYING_RELATIONSHIP_UNAVAILABLE,
             GraphGapKind.EXTERNAL_ORACLE_UNAVAILABLE]
    s1 = _simple_snapshot(gaps=[(kinds[0], "a"), (kinds[1], "b")])
    s2 = _simple_snapshot(gaps=[(kinds[1], "b"), (kinds[0], "a")])
    assert s1.r9_snapshot_digest == s2.r9_snapshot_digest


# --------------------------------------------------------------------------
# Builder topology
# --------------------------------------------------------------------------

def test_b01_builder_seeds_economic_and_deployment_nodes():
    snapshot = _simple_snapshot()
    kinds = {n.node_type for n in snapshot.nodes}
    assert kinds == {GraphNodeType.ECONOMIC_ASSET, GraphNodeType.TOKEN_DEPLOYMENT}


def test_b02_represented_by_edge_authority_r7():
    snapshot = _simple_snapshot()
    edge = [e for e in snapshot.edges
            if e.relationship_type is GraphRelationshipType.REPRESENTED_BY]
    assert len(edge) == 1
    assert edge[0].authority_phase == "R7"
    assert edge[0].source == "R7_ECONOMIC_IDENTITY_BINDING"


def test_b03_represented_by_idempotent():
    builder = AssetGraphBuilder(economic_asset_uid=UID, canonical_asset_key=KEY)
    builder.add_represented_by_edge()
    builder.add_represented_by_edge()
    assert len(builder._edges) == 1


def test_b04_quoted_on_creates_venue_node_and_edge():
    snapshot = _simple_snapshot()
    builder = AssetGraphBuilder(economic_asset_uid=UID, canonical_asset_key=KEY)
    builder.add_quoted_on_edge(VENUE)
    venues = [n for n in builder._nodes
              if n.node_type is GraphNodeType.VENUE]
    assert len(venues) == 1 and venues[0].source_identifier == VENUE
    assert any(e.relationship_type is GraphRelationshipType.QUOTED_ON
               for e in builder._edges)
    assert snapshot is not None


def test_b05_quoted_on_idempotent():
    builder = AssetGraphBuilder(economic_asset_uid=UID, canonical_asset_key=KEY)
    builder.add_quoted_on_edge(VENUE)
    builder.add_quoted_on_edge(VENUE)
    assert len(builder._edges) == 1 and len(builder._nodes) == 3


def test_b06_two_venues_two_edges():
    builder = AssetGraphBuilder(economic_asset_uid=UID, canonical_asset_key=KEY)
    builder.add_quoted_on_edge(VENUE)
    builder.add_quoted_on_edge(VENUE_B)
    assert len(builder._edges) == 2
    assert {e.to_node_id for e in builder._edges} != {builder._edges[0].to_node_id}


def test_b07_settlement_node_and_settles_via_edge():
    snapshot = _populated_snapshot()
    settle = [n for n in snapshot.nodes
              if n.node_type is GraphNodeType.SETTLEMENT_CONTEXT]
    assert len(settle) == 1
    assert settle[0].metadata["chainId"] == 4663
    assert any(e.relationship_type is GraphRelationshipType.SETTLES_VIA
               for e in snapshot.edges)


def test_b08_reference_nodes_create_edges():
    snapshot = _populated_snapshot()
    rels = {e.relationship_type for e in snapshot.edges}
    assert GraphRelationshipType.REFERENCED_BY in rels
    assert GraphRelationshipType.OBSERVED_BY in rels
    kinds = {n.node_type for n in snapshot.nodes}
    assert GraphNodeType.REFERENCE_INSTRUMENT in kinds
    assert GraphNodeType.REFERENCE_SOURCE in kinds


def test_b09_reference_nodes_idempotent():
    builder = AssetGraphBuilder(economic_asset_uid=UID, canonical_asset_key=KEY)
    builder.add_reference_nodes("SRC", "AAPL")
    builder.add_reference_nodes("SRC", "AAPL")
    assert len(builder._nodes) == 4  # economic + deployment + RI + RS
    assert len(builder._edges) == 2


def test_b10_execution_edge_carries_r8_digest_and_metadata():
    snapshot = _populated_snapshot()
    edge = [e for e in snapshot.edges
            if e.relationship_type is GraphRelationshipType.HAS_EXECUTION_EVIDENCE]
    assert len(edge) == 1
    assert edge[0].authority_phase == "R8"
    assert edge[0].evidence_digest == R8_DIGEST
    assert edge[0].metadata["side"] == "BUY"
    assert edge[0].metadata["notionalUsd"] == "100"


def test_b11_execution_edge_unknown_venue_raises_topology():
    builder = AssetGraphBuilder(economic_asset_uid=UID, canonical_asset_key=KEY)
    with pytest.raises(AssetGraphError) as excinfo:
        builder.add_execution_evidence_edge(
            "UNKNOWN_VENUE", "BUY", "100", "BLOCKED", R8_DIGEST,
        )
    assert excinfo.value.status is AssetGraphStatus.ASSET_GRAPH_TOPOLOGY_INVALID


def test_b12_status_ok_without_gaps():
    assert _simple_snapshot().status is AssetGraphStatus.ASSET_GRAPH_OK


def test_b13_status_partial_with_gaps():
    snapshot = _simple_snapshot(gaps=[(
        GraphGapKind.UNDERLYING_RELATIONSHIP_UNAVAILABLE, "no authority")])
    assert snapshot.status is AssetGraphStatus.ASSET_GRAPH_PARTIAL
    assert snapshot.gaps[0].gap_kind is (
        GraphGapKind.UNDERLYING_RELATIONSHIP_UNAVAILABLE)
    assert snapshot.gaps[0].reason == "no authority"


def test_b14_boundaries_record_r9_and_later_phases():
    snapshot = _simple_snapshot()
    assert snapshot.boundaries["assetGraphAuthority"] == "R9_APPLIED"
    assert snapshot.boundaries["modelAuthority"] == "R10_NOT_YET_APPLIED"
    assert snapshot.boundaries["verificationAuthority"] == "R11_NOT_YET_APPLIED"
    assert snapshot.boundaries["digitalTwinAuthority"] == "R12_NOT_YET_APPLIED"


# --------------------------------------------------------------------------
# Build output and evidence shape
# --------------------------------------------------------------------------

def test_e01_nodes_and_edges_sorted_deterministically():
    builder = AssetGraphBuilder(economic_asset_uid=UID, canonical_asset_key=KEY)
    builder.add_quoted_on_edge(VENUE_B)
    builder.add_quoted_on_edge(VENUE)
    snapshot = builder.build(generated_at=NOW, r7_snapshot_digest="d" * 64)
    node_keys = [(n.node_type.value, n.node_id) for n in snapshot.nodes]
    edge_keys = [(e.relationship_type.value, e.from_node_id, e.to_node_id,
                  e.edge_id) for e in snapshot.edges]
    assert node_keys == sorted(node_keys)
    assert edge_keys == sorted(edge_keys)


def test_e02_digest_stable_across_serialization_roundtrip():
    snapshot = _populated_snapshot()
    evidence = json.loads(json.dumps(snapshot.to_evidence_dict()))
    material = dict(evidence)
    material.pop("r9SnapshotDigest")
    assert snapshot.r9_snapshot_digest == _digest(material)


def test_e03_synthetic_flag_carried():
    builder = AssetGraphBuilder(economic_asset_uid=UID, canonical_asset_key=KEY,
                                synthetic=True)
    snapshot = builder.build(generated_at=NOW, r7_snapshot_digest="d" * 64)
    assert snapshot.synthetic is True
    assert snapshot.to_evidence_dict()["synthetic"] is True


def test_e04_source_digests_include_r7_and_r3():
    builder = AssetGraphBuilder(economic_asset_uid=UID, canonical_asset_key=KEY)
    snapshot = builder.build(
        generated_at=NOW, r7_snapshot_digest="r7" * 32,
        r3_liquidity_digest="r3" * 32,
    )
    assert snapshot.source_digests["r7CrossMarketDigest"] == "r7" * 32
    assert snapshot.source_digests["r3LiquidityDigest"] == "r3" * 32


def test_e05_upstream_evidence_round_trips():
    payload = {"r8ExecutionEvidence": {"a": 1}, "r8ExecutionDigest": "x"}
    snapshot = _simple_snapshot(upstream=payload)
    evidence = snapshot.to_evidence_dict()
    assert evidence["upstreamEvidence"]["r8ExecutionDigest"] == "x"


def test_e06_paths_include_canonical_path():
    snapshot = _populated_snapshot()
    assert any(p.path_type == "ECONOMIC_ASSET→TOKEN_DEPLOYMENT→VENUE"
               for p in snapshot.paths)


def test_e07_node_evidence_dict_shape():
    snapshot = _simple_snapshot()
    node = snapshot.to_evidence_dict()["nodes"][0]
    for key in ("nodeId", "nodeType", "source", "sourceIdentifier",
                "displayLabel"):
        assert key in node


def test_e08_edge_evidence_dict_shape():
    snapshot = _simple_snapshot()
    edge = snapshot.to_evidence_dict()["edges"][0]
    for key in ("edgeId", "relationshipType", "fromNodeId", "toNodeId",
                "authorityPhase", "evidenceDigest"):
        assert key in edge


def test_e09_schema_version_and_phase():
    snapshot = _simple_snapshot()
    evidence = snapshot.to_evidence_dict()
    assert evidence["schemaVersion"] == SCHEMA_VERSION
    assert evidence["phase"] == PHASE == "R9"


# --------------------------------------------------------------------------
# Live-proof derivation from frozen R7/R8 evidence
# --------------------------------------------------------------------------

def test_l01_derives_expected_node_kinds():
    evidence = build_graph_from_upstream(
        r8_evidence=_r8_evidence(), git_head="head", generated_at=NOW)
    kinds = {n["nodeType"] for n in evidence["nodes"]}
    assert kinds == {
        "ECONOMIC_ASSET", "TOKEN_DEPLOYMENT", "VENUE",
        "SETTLEMENT_CONTEXT", "REFERENCE_INSTRUMENT", "REFERENCE_SOURCE",
    }


def test_l02_represented_by_edge_present():
    evidence = build_graph_from_upstream(
        r8_evidence=_r8_evidence(), git_head="head", generated_at=NOW)
    assert any(e["relationshipType"] == "REPRESENTED_BY"
               for e in evidence["edges"])


def test_l03_quoted_on_edges_from_r7_venues():
    evidence = build_graph_from_upstream(
        r8_evidence=_r8_evidence(), git_head="head", generated_at=NOW)
    quoted = [e for e in evidence["edges"]
              if e["relationshipType"] == "QUOTED_ON"]
    assert len(quoted) == 1


def test_l04_settles_via_edge_present():
    evidence = build_graph_from_upstream(
        r8_evidence=_r8_evidence(), git_head="head", generated_at=NOW)
    assert any(e["relationshipType"] == "SETTLES_VIA"
               for e in evidence["edges"])


def test_l05_reference_edges_present():
    evidence = build_graph_from_upstream(
        r8_evidence=_r8_evidence(), git_head="head", generated_at=NOW)
    rels = {e["relationshipType"] for e in evidence["edges"]}
    assert "REFERENCED_BY" in rels and "OBSERVED_BY" in rels


def test_l06_execution_evidence_edge_per_scenario():
    evidence = build_graph_from_upstream(
        r8_evidence=_r8_evidence(), git_head="head", generated_at=NOW)
    exec_edges = [e for e in evidence["edges"]
                  if e["relationshipType"] == "HAS_EXECUTION_EVIDENCE"]
    assert len(exec_edges) == 4
    assert all(e["authorityPhase"] == "R8" for e in exec_edges)
    notionals = {e["metadata"]["notionalUsd"] for e in exec_edges}
    assert notionals == {"100", "1000"}


def test_l07_underlying_gap_recorded():
    evidence = build_graph_from_upstream(
        r8_evidence=_r8_evidence(), git_head="head", generated_at=NOW)
    assert any(g["gapKind"] == "UNDERLYING_RELATIONSHIP_UNAVAILABLE"
               for g in evidence["gaps"])


def test_l08_external_oracle_gap_recorded():
    evidence = build_graph_from_upstream(
        r8_evidence=_r8_evidence(), git_head="head", generated_at=NOW)
    assert any(g["gapKind"] == "EXTERNAL_ORACLE_UNAVAILABLE"
               for g in evidence["gaps"])


def test_l09_second_venue_gap_when_single_venue():
    evidence = build_graph_from_upstream(
        r8_evidence=_r8_evidence(), git_head="head", generated_at=NOW)
    assert any(g["gapKind"] == "SECOND_VENUE_UNAVAILABLE"
               for g in evidence["gaps"])


def test_l10_no_second_venue_gap_when_two_venues():
    evidence = build_graph_from_upstream(
        r8_evidence=_r8_evidence(venues=(VENUE, VENUE_B)),
        git_head="head", generated_at=NOW)
    assert not any(g["gapKind"] == "SECOND_VENUE_UNAVAILABLE"
                   for g in evidence["gaps"])


def test_l11_corporate_action_gap_recorded():
    evidence = build_graph_from_upstream(
        r8_evidence=_r8_evidence(), git_head="head", generated_at=NOW)
    assert any(g["gapKind"] == "CORPORATE_ACTION_AUTHORITY_UNAVAILABLE"
               for g in evidence["gaps"])


def test_l12_status_partial_when_gaps_present():
    evidence = build_graph_from_upstream(
        r8_evidence=_r8_evidence(), git_head="head", generated_at=NOW)
    assert evidence["status"] == "ASSET_GRAPH_PARTIAL"


def test_l13_tampered_r8_evidence_raises_lineage_mismatch():
    r8 = _r8_evidence()
    r8["economicAssetUid"] = "TAMPERED"
    with pytest.raises(AssetGraphError) as excinfo:
        build_graph_from_upstream(r8_evidence=r8, git_head="head",
                                  generated_at=NOW)
    assert excinfo.value.status is AssetGraphStatus.ASSET_GRAPH_LINEAGE_MISMATCH


def test_l14_tampered_r7_evidence_raises_lineage_mismatch():
    r8 = _r8_evidence()
    r8["upstreamEvidence"]["r7CrossMarketEvidence"]["economicAssetUid"] = "X"
    with pytest.raises(AssetGraphError) as excinfo:
        build_graph_from_upstream(r8_evidence=r8, git_head="head",
                                  generated_at=NOW)
    assert excinfo.value.status is AssetGraphStatus.ASSET_GRAPH_LINEAGE_MISMATCH


def test_l15_missing_r7_evidence_raises_input_invalid():
    r8 = _r8_evidence()
    r8["upstreamEvidence"].pop("r7CrossMarketEvidence")
    with pytest.raises(AssetGraphError) as excinfo:
        build_graph_from_upstream(r8_evidence=r8, git_head="head",
                                  generated_at=NOW)
    assert excinfo.value.status is AssetGraphStatus.ASSET_GRAPH_INPUT_INVALID


def test_l16_derived_digest_changes_when_r8_evidence_changes():
    a = build_graph_from_upstream(
        r8_evidence=_r8_evidence(), git_head="head", generated_at=NOW)
    b = build_graph_from_upstream(
        r8_evidence=_r8_evidence(underlying_status="AVAILABLE"),
        git_head="head", generated_at=NOW)
    assert a["r9SnapshotDigest"] != b["r9SnapshotDigest"]


def test_l17_derived_graph_is_never_ok_while_gaps_exist():
    evidence = build_graph_from_upstream(
        r8_evidence=_r8_evidence(), git_head="head", generated_at=NOW)
    assert evidence["gaps"], "live-derived graph must record explicit gaps"
    assert evidence["status"] != "ASSET_GRAPH_OK"


def test_l18_only_known_relationship_types_present():
    evidence = build_graph_from_upstream(
        r8_evidence=_r8_evidence(), git_head="head", generated_at=NOW)
    allowed = {rt.value for rt in GraphRelationshipType}
    assert {e["relationshipType"] for e in evidence["edges"]} <= allowed


def test_l19_embedded_r8_evidence_digest_recorded():
    r8 = _r8_evidence()
    evidence = build_graph_from_upstream(
        r8_evidence=r8, git_head="head", generated_at=NOW)
    assert evidence["upstreamEvidence"]["r8ExecutionDigest"] == (
        r8["r8SnapshotDigest"])
    assert evidence["sourceDigests"]["r7CrossMarketDigest"] == (
        r8["upstreamEvidence"]["r7CrossMarketEvidence"]["r7SnapshotDigest"])


def test_l20_execution_edge_venue_not_in_r7_venues_is_still_wired():
    r8 = _r8_evidence()
    r7 = r8["upstreamEvidence"]["r7CrossMarketEvidence"]
    r7["layers"]["venues"] = []
    r7["r7SnapshotDigest"] = _digest(
        {k: v for k, v in r7.items() if k != "r7SnapshotDigest"})
    r8["upstreamEvidence"]["r7CrossMarketDigest"] = _digest(r7)
    r8["sourceDigests"]["r7CrossMarketDigest"] = _digest(r7)
    material = {k: v for k, v in r8.items() if k != "r8SnapshotDigest"}
    r8["r8SnapshotDigest"] = _digest(material)
    evidence = build_graph_from_upstream(
        r8_evidence=r8, git_head="head", generated_at=NOW)
    exec_edges = [e for e in evidence["edges"]
                  if e["relationshipType"] == "HAS_EXECUTION_EVIDENCE"]
    assert len(exec_edges) == 4


# --------------------------------------------------------------------------
# Queries
# --------------------------------------------------------------------------

def test_q01_nodes_for_economic_asset():
    snapshot = _populated_snapshot()
    nodes = nodes_for_economic_asset(snapshot, UID)
    assert all(n.economic_asset_uid == UID for n in nodes)
    assert nodes


def test_q02_deployments_for_economic_asset():
    snapshot = _populated_snapshot()
    dep = deployments_for_economic_asset(snapshot, UID)
    assert len(dep) == 1
    assert dep[0].node_type is GraphNodeType.TOKEN_DEPLOYMENT
    assert deployments_for_economic_asset(snapshot, "OTHER") == ()


def test_q03_venues_for_deployment():
    snapshot = _populated_snapshot()
    dep = deployments_for_economic_asset(snapshot, UID)[0]
    venues = venues_for_deployment(snapshot, dep.node_id)
    assert [v.source_identifier for v in venues] == [VENUE]


def test_q04_reference_sources_for_asset():
    snapshot = _populated_snapshot()
    sources = reference_sources_for_asset(snapshot, UID)
    assert [s.source_identifier for s in sources] == ["ROBINHOOD_RHJ"]


def test_q05_execution_evidence_for():
    snapshot = _populated_snapshot()
    dep = deployments_for_economic_asset(snapshot, UID)[0]
    venue = venues_for_deployment(snapshot, dep.node_id)[0]
    edges = execution_evidence_for(snapshot, dep.node_id, venue.node_id)
    assert len(edges) == 1
    assert edges[0].evidence_digest == R8_DIGEST


def test_q06_canonical_asset_path_present_and_absent():
    snapshot = _populated_snapshot()
    dep = deployments_for_economic_asset(snapshot, UID)[0]
    venue = venues_for_deployment(snapshot, dep.node_id)[0]
    path = canonical_asset_path(snapshot, UID, dep.node_id, venue.node_id)
    assert path is not None
    assert path.node_ids == (f"economic:{UID}", dep.node_id, venue.node_id)
    assert canonical_asset_path(snapshot, UID, "deployment:missing",
                                venue.node_id) is None
