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

from finco_radar.asset_graph.builder import (
    AssetGraphBuilder,
    digest_record,
    validate_path_structure,
)
from finco_radar.asset_graph.contracts import (
    PHASE,
    SCHEMA_VERSION,
    AssetGraphEdge,
    AssetGraphEdge,
    AssetGraphError,
    AssetGraphNode,
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


IDENTITY_RECORD = {
    "economicAssetUid": UID,
    "canonicalKeys": [{"chainId": KEY.chain_id,
                       "contractAddress": KEY.contract_address}],
    "referenceIdentifiers": [UID],
    "source": "SYNTHETIC_TEST_REGISTRY",
}
VENUE_OBSERVATION = {
    "venue": VENUE,
    "side": "BUY",
    "notionalUsd": "100",
    "price": "101",
    "currency": "USD",
    "observedAt": NOW.isoformat(),
    "source": "R0_EXECUTION_QUOTE_VIA_R3_LIQUIDITY",
    "chainId": KEY.chain_id,
    "contractAddress": KEY.contract_address,
    "gapBps": "100",
    "routeSignature": "SYNTH:ROUTE",
    "rawEvidence": {},
}
VENUE_B_OBSERVATION = dict(VENUE_OBSERVATION, venue=VENUE_B)
SETTLEMENT_RECORD = {
    "settlementAssetSymbol": "USDG",
    "chainId": 4663,
    "contractAddress": "0x" + "cc" * 20,
    "settlementCurrency": "USD",
    "transferRequired": None,
    "authorityStatus": "CONTEXT_ONLY",
    "resolved": True,
}
ORACLE_RECORD = {
    "status": "AVAILABLE",
    "source": "ROBINHOOD_RHJ",
    "price": "100",
    "currency": "USD",
    "observedAt": NOW.isoformat(),
    "instrument": UID,
    "multiplier": "1",
    "usable": True,
    "assetUid": UID,
    "assetKey": f"{KEY.chain_id}:{KEY.contract_address}",
}


def _simple_snapshot(upstream=None, gaps=()):
    builder = AssetGraphBuilder(economic_asset_uid=UID, canonical_asset_key=KEY)
    builder.add_represented_by_edge(IDENTITY_RECORD)
    for kind, reason in gaps:
        builder.add_gap(kind, reason=reason)
    return builder.build(
        generated_at=NOW, r7_cross_market_digest="d" * 64, upstream_evidence=upstream,
    )


def _populated_snapshot():
    builder = AssetGraphBuilder(economic_asset_uid=UID, canonical_asset_key=KEY)
    builder.add_represented_by_edge(IDENTITY_RECORD)
    builder.add_quoted_on_edge(VENUE, [VENUE_OBSERVATION])
    builder.add_settlement_node("R0", "USDG", 4663, "0x" + "cc" * 20)
    builder.add_settles_via_edge("USDG", SETTLEMENT_RECORD)
    builder.add_reference_nodes("ROBINHOOD_RHJ", UID, ORACLE_RECORD)
    builder.add_execution_evidence_edge(VENUE, "BUY", "100", "BLOCKED", R8_DIGEST)
    return builder.build(generated_at=NOW, r7_cross_market_digest="d" * 64)


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
    builder.add_represented_by_edge(IDENTITY_RECORD)
    builder.add_represented_by_edge(IDENTITY_RECORD)
    assert len(builder._edges) == 1


def test_b04_quoted_on_creates_venue_node_and_edge():
    snapshot = _simple_snapshot()
    builder = AssetGraphBuilder(economic_asset_uid=UID, canonical_asset_key=KEY)
    builder.add_quoted_on_edge(VENUE, [VENUE_OBSERVATION])
    venues = [n for n in builder._nodes
              if n.node_type is GraphNodeType.VENUE]
    assert len(venues) == 1 and venues[0].source_identifier == VENUE
    assert any(e.relationship_type is GraphRelationshipType.QUOTED_ON
               for e in builder._edges)
    assert snapshot is not None


def test_b05_quoted_on_idempotent():
    builder = AssetGraphBuilder(economic_asset_uid=UID, canonical_asset_key=KEY)
    builder.add_quoted_on_edge(VENUE, [VENUE_OBSERVATION])
    builder.add_quoted_on_edge(VENUE, [VENUE_OBSERVATION])
    assert len(builder._edges) == 1 and len(builder._nodes) == 3


def test_b06_two_venues_two_edges():
    builder = AssetGraphBuilder(economic_asset_uid=UID, canonical_asset_key=KEY)
    builder.add_quoted_on_edge(VENUE, [VENUE_OBSERVATION])
    builder.add_quoted_on_edge(VENUE_B, [VENUE_B_OBSERVATION])
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
    builder.add_reference_nodes("SRC", "AAPL", ORACLE_RECORD)
    builder.add_reference_nodes("SRC", "AAPL", ORACLE_RECORD)
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
    builder.add_quoted_on_edge(VENUE_B, [VENUE_B_OBSERVATION])
    builder.add_quoted_on_edge(VENUE, [VENUE_OBSERVATION])
    snapshot = builder.build(generated_at=NOW, r7_cross_market_digest="d" * 64)
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
    snapshot = builder.build(generated_at=NOW, r7_cross_market_digest="d" * 64)
    assert snapshot.synthetic is True
    assert snapshot.to_evidence_dict()["synthetic"] is True


def test_e04_source_digests_include_r7_and_r3():
    builder = AssetGraphBuilder(economic_asset_uid=UID, canonical_asset_key=KEY)
    snapshot = builder.build(
        generated_at=NOW, r7_cross_market_digest="r7" * 32,
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
    evidence = _derive(r8)
    # The R8 digest is typed in sourceDigests (not an untyped sibling).
    assert evidence["sourceDigests"]["r8ExecutionSimulatorDigest"] == (
        r8["r8SnapshotDigest"])
    # The R7 source digest is the canonical hash of the COMPLETE embedded R7
    # evidence, not its internal r7SnapshotDigest.
    assert evidence["sourceDigests"]["r7CrossMarketDigest"] == _digest(
        r8["upstreamEvidence"]["r7CrossMarketEvidence"])


def _reseal_r7(r7: dict) -> dict:
    r7["r7SnapshotDigest"] = _digest(
        {k: v for k, v in r7.items() if k != "r7SnapshotDigest"})
    return r7


def _reseal_r8(r8: dict) -> dict:
    r8["r8SnapshotDigest"] = _digest(
        {k: v for k, v in r8.items() if k != "r8SnapshotDigest"})
    return r8


def _rebind_r7_in_r8(r8: dict) -> dict:
    """After mutating embedded R7 evidence: refresh the R8-declared R7 source
    digest and reseal the R8 snapshot, so ONLY the targeted check can fail."""
    r7 = r8["upstreamEvidence"]["r7CrossMarketEvidence"]
    r8["sourceDigests"]["r7CrossMarketDigest"] = _digest(r7)
    return _reseal_r8(r8)


def _derive(r8):
    return build_graph_from_upstream(r8_evidence=r8, git_head="head",
                                     generated_at=NOW)


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


# --------------------------------------------------------------------------
# Correction A - F1: R7/R8 lineage digest semantics
# --------------------------------------------------------------------------

def test_f1_01_correct_source_and_internal_digests_pass():
    r8 = _r8_evidence()
    r7 = r8["upstreamEvidence"]["r7CrossMarketEvidence"]
    evidence = _derive(r8)
    # The R9 SOURCE digest is the canonical hash of the COMPLETE embedded R7
    # evidence - deliberately different from its internal r7SnapshotDigest.
    assert evidence["sourceDigests"]["r7CrossMarketDigest"] == _digest(r7)
    assert evidence["sourceDigests"]["r7CrossMarketDigest"] != (
        r7["r7SnapshotDigest"])


def test_f1_02_wrong_canonical_source_digest_rejected():
    r8 = _r8_evidence()
    r8["sourceDigests"]["r7CrossMarketDigest"] = "0" * 64
    _reseal_r8(r8)  # internal R8 digest consistent; source equality fails
    with pytest.raises(AssetGraphError) as excinfo:
        _derive(r8)
    assert excinfo.value.status is AssetGraphStatus.ASSET_GRAPH_LINEAGE_MISMATCH


def test_f1_03_wrong_internal_snapshot_digest_rejected():
    r8 = _r8_evidence()
    r7 = r8["upstreamEvidence"]["r7CrossMarketEvidence"]
    # Payload changes but the internal r7SnapshotDigest is NOT recomputed:
    # the R7 source digest stays consistent, the internal verifier fails.
    r7["attributionState"] = "TAMPERED"
    _rebind_r7_in_r8(r8)
    with pytest.raises(AssetGraphError) as excinfo:
        _derive(r8)
    assert excinfo.value.status is AssetGraphStatus.ASSET_GRAPH_LINEAGE_MISMATCH


def test_f1_04_r9_source_digest_equals_r8_declared_source_digest():
    r8 = _r8_evidence()
    r7 = r8["upstreamEvidence"]["r7CrossMarketEvidence"]
    evidence = _derive(r8)
    assert evidence["sourceDigests"]["r7CrossMarketDigest"] == (
        r8["sourceDigests"]["r7CrossMarketDigest"])
    assert r8["sourceDigests"]["r7CrossMarketDigest"] == _digest(r7)


def test_f1_05_missing_or_wrong_r8_snapshot_digest_rejected():
    r8 = _r8_evidence()
    r8.pop("r8SnapshotDigest")
    with pytest.raises(AssetGraphError) as excinfo:
        _derive(r8)
    assert excinfo.value.status is AssetGraphStatus.ASSET_GRAPH_LINEAGE_MISMATCH
    r8 = _r8_evidence()
    r8["r8SnapshotDigest"] = "f" * 64
    with pytest.raises(AssetGraphError) as excinfo:
        _derive(r8)
    assert excinfo.value.status is AssetGraphStatus.ASSET_GRAPH_LINEAGE_MISMATCH


def test_f1_06_live_source_digests_reconstruct_independently():
    r8 = _r8_evidence()
    r7 = r8["upstreamEvidence"]["r7CrossMarketEvidence"]
    evidence = _derive(r8)
    # R7 source digest: canonical hash of complete embedded evidence.
    assert _digest(r7) == evidence["sourceDigests"]["r7CrossMarketDigest"]
    # R7 internal snapshot digest: frozen R7 verifier.
    assert verify_r7(r7) is True
    # R8 snapshot digest: frozen R8 verifier + explicit sourceDigests binding.
    assert verify_r8(r8) is True
    assert evidence["sourceDigests"]["r8ExecutionSimulatorDigest"] == (
        r8["r8SnapshotDigest"])


# --------------------------------------------------------------------------
# Correction A - F2: edge evidenceDigest binds actual authority evidence
# --------------------------------------------------------------------------

def test_f2_01_represented_by_digest_is_record_digest_not_edge_id():
    builder = AssetGraphBuilder(economic_asset_uid=UID, canonical_asset_key=KEY)
    builder.add_represented_by_edge(IDENTITY_RECORD)
    edge = builder._edges[0]
    assert edge.evidence_digest == digest_record(IDENTITY_RECORD)
    assert edge.evidence_digest != edge.edge_id


def test_f2_02_quoted_on_digest_covers_exact_observations_order_independent():
    row_a = dict(VENUE_OBSERVATION, notionalUsd="100")
    row_b = dict(VENUE_OBSERVATION, notionalUsd="1000")
    builder_a = AssetGraphBuilder(economic_asset_uid=UID, canonical_asset_key=KEY)
    builder_a.add_quoted_on_edge(VENUE, [row_a, row_b])
    builder_b = AssetGraphBuilder(economic_asset_uid=UID, canonical_asset_key=KEY)
    builder_b.add_quoted_on_edge(VENUE, [row_b, row_a])
    expected = digest_record(
        {"venue": VENUE, "observations": sorted([row_a, row_b],
                                                key=canonical_evidence_bytes)})
    assert builder_a._edges[0].evidence_digest == expected
    assert builder_b._edges[0].evidence_digest == expected


def test_f2_03_settles_via_digest_is_settlement_record_digest():
    builder = AssetGraphBuilder(economic_asset_uid=UID, canonical_asset_key=KEY)
    builder.add_settlement_node("R0", "USDG", 4663, "0x" + "cc" * 20)
    builder.add_settles_via_edge("USDG", SETTLEMENT_RECORD)
    edge = [e for e in builder._edges
            if e.relationship_type is GraphRelationshipType.SETTLES_VIA][0]
    assert edge.evidence_digest == digest_record(SETTLEMENT_RECORD)
    assert edge.evidence_digest != edge.edge_id


def test_f2_04_reference_edges_digest_is_observation_record_digest():
    builder = AssetGraphBuilder(economic_asset_uid=UID, canonical_asset_key=KEY)
    builder.add_reference_nodes("ROBINHOOD_RHJ", UID, ORACLE_RECORD)
    for rel in (GraphRelationshipType.REFERENCED_BY,
                GraphRelationshipType.OBSERVED_BY):
        edge = [e for e in builder._edges if e.relationship_type is rel][0]
        assert edge.evidence_digest == digest_record(ORACLE_RECORD)
        assert edge.evidence_digest != edge.edge_id


def test_f2_05_evidence_change_moves_digests_not_topology():
    snap_a = _populated_snapshot()
    other_identity = dict(IDENTITY_RECORD, source="OTHER_REGISTRY")
    builder = AssetGraphBuilder(economic_asset_uid=UID, canonical_asset_key=KEY)
    builder.add_represented_by_edge(other_identity)
    builder.add_quoted_on_edge(VENUE, [VENUE_OBSERVATION])
    builder.add_settlement_node("R0", "USDG", 4663, "0x" + "cc" * 20)
    builder.add_settles_via_edge("USDG", SETTLEMENT_RECORD)
    builder.add_reference_nodes("ROBINHOOD_RHJ", UID, ORACLE_RECORD)
    builder.add_execution_evidence_edge(VENUE, "BUY", "100", "BLOCKED", R8_DIGEST)
    snap_b = builder.build(generated_at=NOW, r7_cross_market_digest="d" * 64)
    # Topology identity unchanged ...
    assert [n.node_id for n in snap_a.nodes] == [n.node_id for n in snap_b.nodes]
    assert [e.edge_id for e in snap_a.edges] == [e.edge_id for e in snap_b.edges]
    # ... but evidence lineage moved.
    def rep_of(snap):
        return [e for e in snap.edges
                if e.relationship_type is GraphRelationshipType.REPRESENTED_BY][0]
    rep_a, rep_b = rep_of(snap_a), rep_of(snap_b)
    assert rep_a.evidence_digest != rep_b.evidence_digest
    assert snap_a.r9_snapshot_digest != snap_b.r9_snapshot_digest


def test_f2_06_execution_edge_binds_parent_r8_digest_with_scenario_identity():
    snapshot = _populated_snapshot()
    edge = [e for e in snapshot.edges
            if e.relationship_type is GraphRelationshipType.HAS_EXECUTION_EVIDENCE][0]
    assert edge.evidence_digest == R8_DIGEST
    assert edge.metadata["side"] == "BUY"
    assert edge.metadata["notionalUsd"] == "100"


# --------------------------------------------------------------------------
# Correction A - F3: canonical paths are real topology paths
# --------------------------------------------------------------------------

def test_f3_01_one_venue_yields_single_three_node_two_edge_path():
    snapshot = _populated_snapshot()
    assert len(snapshot.paths) == 1
    path = snapshot.paths[0]
    assert len(path.node_ids) == 3 and len(path.edge_ids) == 2
    edges = {e.edge_id: e for e in snapshot.edges}
    validate_path_structure(path.node_ids, path.edge_ids, edges)


def test_f3_02_two_venues_emit_two_deterministic_paths():
    builder = AssetGraphBuilder(economic_asset_uid=UID, canonical_asset_key=KEY)
    builder.add_represented_by_edge(IDENTITY_RECORD)
    builder.add_quoted_on_edge(VENUE_B, [VENUE_B_OBSERVATION])
    builder.add_quoted_on_edge(VENUE, [VENUE_OBSERVATION])
    snapshot = builder.build(generated_at=NOW, r7_cross_market_digest="d" * 64)
    assert len(snapshot.paths) == 2
    ends = [p.node_ids[2] for p in snapshot.paths]
    assert ends == sorted(ends) and len(set(ends)) == 2
    assert [p.path_id for p in snapshot.paths] == sorted(
        p.path_id for p in snapshot.paths)


def test_f3_03_missing_represented_by_yields_no_canonical_path():
    builder = AssetGraphBuilder(economic_asset_uid=UID, canonical_asset_key=KEY)
    builder.add_quoted_on_edge(VENUE, [VENUE_OBSERVATION])
    snapshot = builder.build(generated_at=NOW, r7_cross_market_digest="d" * 64)
    assert snapshot.paths == ()


def test_f3_04_malformed_path_sequences_rejected():
    edge = AssetGraphEdge(
        edge_id="e1", relationship_type=GraphRelationshipType.QUOTED_ON,
        from_node_id="a", to_node_id="b", authority_phase="R7",
        source="s", evidence_digest="d",
    )
    edges = {"e1": edge}
    with pytest.raises(AssetGraphError) as excinfo:
        validate_path_structure(["a", "b"], [], edges)  # length mismatch
    assert excinfo.value.status is AssetGraphStatus.ASSET_GRAPH_TOPOLOGY_INVALID
    with pytest.raises(AssetGraphError) as excinfo:
        validate_path_structure(["a", "x"], ["e1"], edges)  # wrong connectivity
    assert excinfo.value.status is AssetGraphStatus.ASSET_GRAPH_TOPOLOGY_INVALID
    with pytest.raises(AssetGraphError) as excinfo:
        validate_path_structure(["a", "b"], ["missing"], edges)  # unknown edge
    assert excinfo.value.status is AssetGraphStatus.ASSET_GRAPH_TOPOLOGY_INVALID


def test_f3_05_serialized_paths_validate_and_agree_with_query_helper():
    snapshot = _populated_snapshot()
    edges = {e.edge_id: e for e in snapshot.edges}
    for path in snapshot.paths:
        validate_path_structure(path.node_ids, path.edge_ids, edges)
    dep = deployments_for_economic_asset(snapshot, UID)[0]
    for venue in venues_for_deployment(snapshot, dep.node_id):
        queried = canonical_asset_path(snapshot, UID, dep.node_id, venue.node_id)
        serialized = [
            p for p in snapshot.paths if p.node_ids[2] == venue.node_id]
        assert len(serialized) == 1
        assert queried is not None
        assert (queried.node_ids, queried.edge_ids) == (
            serialized[0].node_ids, serialized[0].edge_ids)


# --------------------------------------------------------------------------
# Correction A - F4: duplicate/conflict handling fails closed
# --------------------------------------------------------------------------

def test_f4_01_exact_duplicate_node_idempotent():
    builder = AssetGraphBuilder(economic_asset_uid=UID, canonical_asset_key=KEY)
    builder.add_quoted_on_edge(VENUE, [VENUE_OBSERVATION])
    builder.add_quoted_on_edge(VENUE, [VENUE_OBSERVATION])
    # Seeded economic + deployment + exactly one venue node.
    assert len(builder._nodes) == 3
    assert len(builder._edges) == 1


def test_f4_02_conflicting_node_identity_fails():
    builder = AssetGraphBuilder(economic_asset_uid=UID, canonical_asset_key=KEY)
    existing = builder._node_index[f"economic:{UID}"]
    with pytest.raises(AssetGraphError) as excinfo:
        builder._add_node(AssetGraphNode(
            node_id=existing.node_id,
            node_type=existing.node_type,
            source="ROGUE_AUTHORITY",
            source_identifier=existing.source_identifier,
            economic_asset_uid=existing.economic_asset_uid,
            display_label=existing.display_label,
        ))
    assert excinfo.value.status is AssetGraphStatus.ASSET_GRAPH_IDENTITY_MISMATCH


def test_f4_03_exact_duplicate_edge_idempotent():
    builder = AssetGraphBuilder(economic_asset_uid=UID, canonical_asset_key=KEY)
    builder.add_represented_by_edge(IDENTITY_RECORD)
    builder.add_representated_by_edge = None  # guard against typo-driven pass
    builder2 = AssetGraphBuilder(economic_asset_uid=UID, canonical_asset_key=KEY)
    builder2.add_represented_by_edge(IDENTITY_RECORD)
    builder2.add_represented_by_edge(IDENTITY_RECORD)
    assert len(builder2._edges) == 1


def test_f4_04_conflicting_edge_semantics_fail():
    builder = AssetGraphBuilder(economic_asset_uid=UID, canonical_asset_key=KEY)
    builder.add_represented_by_edge(IDENTITY_RECORD)
    existing = builder._edges[0]
    # Conflicting authority phase on the same deterministic edge id.
    with pytest.raises(AssetGraphError) as excinfo:
        builder._add_edge(AssetGraphEdge(
            edge_id=existing.edge_id,
            relationship_type=existing.relationship_type,
            from_node_id=existing.from_node_id,
            to_node_id=existing.to_node_id,
            authority_phase="R0",
            source=existing.source,
            evidence_digest=existing.evidence_digest,
        ))
    assert excinfo.value.status is AssetGraphStatus.ASSET_GRAPH_TOPOLOGY_INVALID
    # Conflicting evidence lineage through the public API.
    other_record = dict(IDENTITY_RECORD, source="OTHER_REGISTRY")
    with pytest.raises(AssetGraphError) as excinfo:
        builder.add_represented_by_edge(other_record)
    assert excinfo.value.status is AssetGraphStatus.ASSET_GRAPH_TOPOLOGY_INVALID


def test_f4_05_insertion_order_cannot_pick_a_conflict_survivor():
    record_a = IDENTITY_RECORD
    record_b = dict(IDENTITY_RECORD, source="OTHER_REGISTRY")
    for first, second in ((record_a, record_b), (record_b, record_a)):
        builder = AssetGraphBuilder(
            economic_asset_uid=UID, canonical_asset_key=KEY)
        builder.add_represented_by_edge(first)
        with pytest.raises(AssetGraphError) as excinfo:
            builder.add_represented_by_edge(second)
        assert excinfo.value.status is (
            AssetGraphStatus.ASSET_GRAPH_TOPOLOGY_INVALID)


def test_f4_06_conflicting_quoted_on_observations_fail():
    builder = AssetGraphBuilder(economic_asset_uid=UID, canonical_asset_key=KEY)
    builder.add_quoted_on_edge(VENUE, [VENUE_OBSERVATION])
    tampered = dict(VENUE_OBSERVATION, price="999")
    with pytest.raises(AssetGraphError) as excinfo:
        builder.add_quoted_on_edge(VENUE, [tampered])
    assert excinfo.value.status is AssetGraphStatus.ASSET_GRAPH_TOPOLOGY_INVALID


# --------------------------------------------------------------------------
# Correction A - F5: semantic R7/R8 identity binding
# --------------------------------------------------------------------------

def test_f5_01_uid_mismatch_between_r7_and_r8_rejected():
    r8 = _r8_evidence()
    r8["economicAssetUid"] = "EVIL"
    _reseal_r8(r8)  # digest-valid, semantically wrong
    with pytest.raises(AssetGraphError) as excinfo:
        _derive(r8)
    assert excinfo.value.status is AssetGraphStatus.ASSET_GRAPH_LINEAGE_MISMATCH


def test_f5_02_deployment_mismatch_between_r8_and_r9_rejected():
    r8 = _r8_evidence()
    r8["canonicalAssetKey"] = {"chainId": 1, "contractAddress": "0x" + "ee" * 20}
    _reseal_r8(r8)
    with pytest.raises(AssetGraphError) as excinfo:
        _derive(r8)
    assert excinfo.value.status is AssetGraphStatus.ASSET_GRAPH_LINEAGE_MISMATCH


def test_f5_03_token_layer_disagreement_rejected():
    r8 = _r8_evidence()
    r7 = r8["upstreamEvidence"]["r7CrossMarketEvidence"]
    r7["layers"]["token"]["contractAddress"] = "0x" + "ee" * 20
    _rebind_r7_in_r8(r8)
    with pytest.raises(AssetGraphError) as excinfo:
        _derive(r8)
    assert excinfo.value.status is AssetGraphStatus.ASSET_GRAPH_LINEAGE_MISMATCH


def test_f5_04_deployment_not_exactly_once_in_binding_rejected():
    r8 = _r8_evidence()
    r7 = r8["upstreamEvidence"]["r7CrossMarketEvidence"]
    r7["identityBinding"]["canonicalKeys"] = [
        {"chainId": 137, "contractAddress": "0x" + "bb" * 20}]
    _rebind_r7_in_r8(r8)
    with pytest.raises(AssetGraphError) as excinfo:
        _derive(r8)
    assert excinfo.value.status is AssetGraphStatus.ASSET_GRAPH_LINEAGE_MISMATCH


def test_f5_05_scenario_quote_source_unknown_to_r7_rejected():
    r8 = _r8_evidence()
    r8["scenarios"][0]["scenario"]["quoteSource"] = "GHOST_VENUE"
    _reseal_r8(r8)
    with pytest.raises(AssetGraphError) as excinfo:
        _derive(r8)
    assert excinfo.value.status is AssetGraphStatus.ASSET_GRAPH_LINEAGE_MISMATCH


def test_f5_06_scenario_uid_mismatch_rejected():
    r8 = _r8_evidence()
    r8["scenarios"][0]["scenario"]["economicAssetUid"] = "EVIL"
    _reseal_r8(r8)
    with pytest.raises(AssetGraphError) as excinfo:
        _derive(r8)
    assert excinfo.value.status is AssetGraphStatus.ASSET_GRAPH_LINEAGE_MISMATCH


def test_f5_07_scenario_deployment_mismatch_rejected():
    r8 = _r8_evidence()
    r8["scenarios"][0]["scenario"]["contractAddress"] = "0x" + "ee" * 20
    _reseal_r8(r8)
    with pytest.raises(AssetGraphError) as excinfo:
        _derive(r8)
    assert excinfo.value.status is AssetGraphStatus.ASSET_GRAPH_LINEAGE_MISMATCH


def test_f5_08_individually_valid_digests_semantically_incompatible_rejected():
    """The critical case: BOTH frozen verifiers pass - each snapshot
    internally reconstructs - but the pair disagrees on identity. R9 must
    reject the pair semantically."""
    r7_evil = _rich_r7_evidence(uid="EVIL", key=OTHER_KEY)
    assert verify_r7(r7_evil) is True  # internally consistent
    r8 = _r8_evidence()
    r8["upstreamEvidence"]["r7CrossMarketEvidence"] = r7_evil
    r8["sourceDigests"]["r7CrossMarketDigest"] = _digest(r7_evil)
    _reseal_r8(r8)
    assert verify_r8(r8) is True  # internally consistent
    with pytest.raises(AssetGraphError) as excinfo:
        _derive(r8)
    assert excinfo.value.status is AssetGraphStatus.ASSET_GRAPH_LINEAGE_MISMATCH
