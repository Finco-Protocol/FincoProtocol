"""R10 bridge: frozen model authority ⇄ R9 asset graph ⇄ Radar market state.

The bridge consumes exact embedded R9 evidence (verified two ways: the
internal r9SnapshotDigest with the frozen R9 verifier, and a canonical
SHA-256 over the COMPLETE embedded evidence — two distinct lineage checks,
never collapsed), resolves semantic economic-identity binding, and assembles
the immutable ModelRadarSnapshot.
"""
from __future__ import annotations

from datetime import datetime
from decimal import Decimal
from typing import Any, Mapping

from finco_radar.asset_graph.contracts import (
    verify_serialized_r9_evidence,
)
from finco_radar.execution_simulator.contracts import (
    verify_serialized_evidence as verify_r8_evidence,
)

from .comparisons import (
    MarketComparabilityContext,
    compute_execution_comparison,
    compute_reference_comparison,
    model_value_per_unit,
    resolve_comparability,
)
from .contracts import (
    PHASE,
    SCHEMA_VERSION,
    _plain,
    ComparabilityState,
    ModelBinding,
    ModelEvidence,
    ModelRadarError,
    ModelRadarGap,
    ModelRadarGapKind,
    ModelRadarStatus,
    ModelRadarTimingPolicy,
    ModelRadarSnapshot,
    digest_payload,
)

R10_BOUNDARIES = {
    "registryAuthority": "R1_APPLIED",
    "referenceAuthority": "R4_APPLIED",
    "crossMarketAuthority": "R7_APPLIED",
    "executionSimulatorAuthority": "R8_APPLIED",
    "assetGraphAuthority": "R9_APPLIED",
    "modelAuthority": "R10_APPLIED",
    "verificationAuthority": "R11_NOT_YET_APPLIED",
    "digitalTwinAuthority": "R12_NOT_YET_APPLIED",
}

# Frozen model-authority entrypoints inspected for R10 (§3 inventory).  R10
# consumes them; it never reimplements their mathematics.
MODEL_AUTHORITY_INVENTORY = {
    "xnpv": "finco_core.sponsor.xnpv.xnpv",
    "xirr": "finco_core.sponsor.xirr.xirr",
    "engine_operating_model": "financial_engine.orchestrator.run_operating_model",
    "engine_tax_cfads_model": "financial_engine.orchestrator.run_tax_cfads_model",
    "engine_senior_debt_model": "financial_engine.orchestrator.run_senior_debt_model",
}


def _lineage_failure(detail: str) -> ModelRadarError:
    return ModelRadarError(detail, ModelRadarStatus.MODEL_RADAR_LINEAGE_MISMATCH)


def verify_r9_lineage(r9_evidence: Mapping[str, Any]) -> dict[str, Any]:
    """Two distinct R9 checks (never collapsed):

    - internal ``r9SnapshotDigest`` reconstruction via the frozen R9 verifier;
    - canonical SHA-256 over the COMPLETE embedded R9 evidence.

    Then semantic binding: the R9 economic UID and its canonical economic
    node must exist exactly once as an ECONOMIC_ASSET node.
    """
    if not isinstance(r9_evidence, Mapping) or not r9_evidence:
        raise ModelRadarError(
            "embedded r9AssetGraphEvidence is missing or not a mapping",
            ModelRadarStatus.MODEL_RADAR_INPUT_INVALID,
        )
    r9_snapshot_digest = r9_evidence.get("r9SnapshotDigest")
    if not r9_snapshot_digest or not verify_serialized_r9_evidence(r9_evidence):
        raise _lineage_failure(
            "embedded R9 evidence fails its r9SnapshotDigest reconstruction"
        )
    r9_source_digest = digest_payload(r9_evidence)
    uid = r9_evidence.get("economicAssetUid")
    if not uid:
        raise ModelRadarError(
            "embedded R9 evidence carries no economicAssetUid",
            ModelRadarStatus.MODEL_RADAR_INPUT_INVALID,
        )
    economic_nodes = [
        n for n in r9_evidence.get("nodes", [])
        if n.get("nodeType") == "ECONOMIC_ASSET"
        and n.get("nodeId") == f"economic:{uid}"
    ]
    if len(economic_nodes) != 1:
        raise _lineage_failure(
            f"canonical economic node economic:{uid} appears "
            f"{len(economic_nodes)} times in the embedded R9 evidence "
            "(expected exactly once)"
        )
    if r9_evidence.get("economicNodeId") not in (None, f"economic:{uid}"):
        raise _lineage_failure(
            "embedded R9 evidence economicNodeId disagrees with the "
            "canonical economic node"
        )
    return {
        "economic_asset_uid": uid,
        "economic_node_id": f"economic:{uid}",
        "r9_snapshot_digest": r9_snapshot_digest,
        "r9_source_digest": r9_source_digest,
    }


def resolve_model_binding(
    *,
    model_evidence: ModelEvidence,
    r9_lineage: Mapping[str, Any],
) -> ModelBinding:
    """Semantic model⇄R9 binding: UID and canonical economic node must be
    identical across model evidence, R10 and R9 — independently valid
    evidence from a different asset is rejected."""
    uid = r9_lineage["economic_asset_uid"]
    node_id = r9_lineage["economic_node_id"]
    if model_evidence.economic_asset_uid != uid:
        raise _lineage_failure(
            f"model evidence economic asset {model_evidence.economic_asset_uid} "
            f"does not equal the R9 economic asset {uid}"
        )
    if model_evidence.economic_node_id != node_id:
        raise _lineage_failure(
            f"model evidence economic node {model_evidence.economic_node_id} "
            f"does not equal the R9 canonical economic node {node_id}"
        )
    return ModelBinding(
        economic_asset_uid=uid,
        economic_node_id=node_id,
        model_id=model_evidence.model_id,
        model_version=model_evidence.model_version,
    )


def discover_model_binding(
    economic_asset_uid: str,
) -> tuple[ModelEvidence | None, ModelRadarGap | None]:
    """Honest binding discovery over the frozen model authority.

    The repository contains deterministic project-finance model components
    (XNPV/XIRR/engine orchestrators) but NO source-proven model binding that
    attaches a compatible valuation output to a Radar economic asset.  Until
    such a binding authority exists this returns the typed
    MODEL_BINDING_UNAVAILABLE gap — successful fail-closed behaviour, never
    a fabricated valuation.
    """
    return None, ModelRadarGap(
        gap_kind=ModelRadarGapKind.MODEL_BINDING_UNAVAILABLE,
        source="R10_MODEL_AUTHORITY_DISCOVERY",
        reason=(
            "no frozen FINCO model authority carries a source-proven "
            f"model binding for economic asset {economic_asset_uid}"
        ),
    )


def _market_context_from_r9(
    r9_evidence: Mapping[str, Any],
) -> tuple[MarketComparabilityContext, ModelRadarGap | None]:
    """Reference context from the R9/R7 oracle-reference layer only."""
    layers = r9_evidence.get("upstreamEvidence", {}).get(
        "r8ExecutionEvidence", {}).get(
        "upstreamEvidence", {}).get("r7CrossMarketEvidence", {}).get(
        "layers", {})
    oracle = layers.get("oracleReference")
    if (
        oracle is None
        or oracle.get("status") != "AVAILABLE"
        or oracle.get("price") is None
    ):
        return MarketComparabilityContext(
            reference_price=None,
            reference_currency=None,
            reference_source=None,
            reference_observed_at=None,
        ), ModelRadarGap(
            gap_kind=ModelRadarGapKind.REFERENCE_UNAVAILABLE,
            source="R9_ASSET_GRAPH_AUTHORITY",
            reason="R9 oracle-reference layer is not an available reference",
        )
    from datetime import datetime as _dt
    observed_at = _dt.fromisoformat(oracle["observedAt"])
    context = MarketComparabilityContext(
        reference_price=Decimal(str(oracle["price"])),
        reference_currency=oracle.get("currency"),
        reference_source=oracle.get("source"),
        reference_observed_at=observed_at,
    )
    return context, None


def _verify_r8_lineage(
    r8_evidence: Mapping[str, Any] | None,
) -> dict[str, str]:
    if r8_evidence is None:
        return {}
    if not verify_r8_evidence(r8_evidence):
        raise _lineage_failure(
            "embedded R8 evidence fails its r8SnapshotDigest reconstruction"
        )
    return {
        "r8ExecutionSimulatorDigest": digest_payload(r8_evidence),
        "r8SnapshotDigest": r8_evidence["r8SnapshotDigest"],
    }


def _execution_comparisons_and_gaps(
    *,
    per_unit_value: Decimal,
    r8_evidence: Mapping[str, Any] | None,
) -> tuple[list, list[ModelRadarGap]]:
    comparisons = []
    gaps: list[ModelRadarGap] = []
    if r8_evidence is None:
        gaps.append(ModelRadarGap(
            gap_kind=ModelRadarGapKind.EXECUTION_EVIDENCE_UNAVAILABLE,
            source="R8_EXECUTION_SIMULATOR_AUTHORITY",
            reason="no R8 execution evidence embedded",
        ))
        return comparisons, gaps
    for index, scenario in enumerate(r8_evidence.get("scenarios", [])):
        entry = scenario.get("scenario") or {}
        r2_evidence = (scenario.get("upstreamEvidence") or {}).get(
            "r2GapEvidence") or {}
        raw_price = r2_evidence.get("executionPriceUsdPerToken")
        if raw_price is None:
            gaps.append(ModelRadarGap(
                gap_kind=ModelRadarGapKind.EXECUTION_EVIDENCE_UNAVAILABLE,
                source="R8_EXECUTION_SIMULATOR_AUTHORITY",
                reason=(
                    "R8 scenario "
                    f"{entry.get('side')}/{entry.get('requestedNotionalUsd')} "
                    "carries no exact execution price per token; R10 never "
                    "re-derives R8 economics"
                ),
            ))
            continue
        comparisons.append(compute_execution_comparison(
            model_value_per_unit=per_unit_value,
            execution_price=Decimal(str(raw_price)),
            side=entry.get("side", ""),
            requested_notional_usd=str(entry.get("requestedNotionalUsd", "")),
            quote_source=entry.get("quoteSource", ""),
            r8_net_edge_state=scenario.get("netEdgeState", ""),
            r8_scenario_index=index,
        ))
    return comparisons, gaps


def build_model_radar_snapshot(
    *,
    r9_evidence: Mapping[str, Any],
    r8_evidence: Mapping[str, Any] | None = None,
    model_evidence: ModelEvidence | None = None,
    timing_policy: ModelRadarTimingPolicy,
    now: datetime,
    git_head: str = "UNKNOWN",
    synthetic: bool = False,
) -> ModelRadarSnapshot:
    """Deterministic R10 snapshot, or typed fail-closed errors."""
    lineage = verify_r9_lineage(r9_evidence)
    uid = lineage["economic_asset_uid"]
    node_id = lineage["economic_node_id"]
    r8_digests = _verify_r8_lineage(r8_evidence)

    gaps: list[ModelRadarGap] = []
    binding: ModelBinding | None = None
    comparability = None
    reference_comparison = None
    execution_comparisons: list = []

    if model_evidence is None:
        # Honest discovery over the frozen model authority; v1 returns the
        # typed MODEL_BINDING_UNAVAILABLE gap unless a binding exists.
        binding, discovered_gap = discover_model_binding(uid)
        if binding is None:
            gaps.append(discovered_gap)
    if model_evidence is not None and binding is None:
        binding = resolve_model_binding(
            model_evidence=model_evidence, r9_lineage=lineage)

    reference_gap: ModelRadarGap | None
    market_context, reference_gap = _market_context_from_r9(r9_evidence)
    if reference_gap is not None:
        gaps.append(reference_gap)

    if binding is not None and model_evidence is not None:
        comparability = resolve_comparability(
            model_evidence=model_evidence,
            market_context=market_context,
            timing_policy=timing_policy,
            now=now,
        )
        for dimension in comparability.dimensions:
            if not dimension.ok and dimension.gap_kind is not None:
                gaps.append(ModelRadarGap(
                    gap_kind=dimension.gap_kind,
                    source="R10_COMPARABILITY",
                    reason=dimension.detail,
                ))
        if comparability.state is ComparabilityState.COMPARABLE:
            per_unit = model_value_per_unit(model_evidence)
            if market_context.reference_price is not None:
                reference_comparison = compute_reference_comparison(
                    model_value_per_unit=per_unit,
                    reference_price=market_context.reference_price,
                    reference_source=market_context.reference_source or "",
                    model_observed_at=model_evidence.valuation_as_of,
                    reference_observed_at=(
                        market_context.reference_observed_at or now),
                )
            exec_comparisons, exec_gaps = _execution_comparisons_and_gaps(
                per_unit_value=per_unit, r8_evidence=r8_evidence)
            execution_comparisons.extend(exec_comparisons)
            gaps.extend(exec_gaps)

    source_digests: dict[str, str] = {
        "r9AssetGraphDigest": lineage["r9_source_digest"],
        "r9SnapshotDigest": lineage["r9_snapshot_digest"],
    }
    source_digests.update(r8_digests)
    if model_evidence is not None:
        source_digests["modelInputDigest"] = model_evidence.input_digest
        source_digests["modelOutputDigest"] = model_evidence.output_digest
        source_digests["modelRunDigest"] = model_evidence.model_run_digest

    if not gaps:
        status = ModelRadarStatus.MODEL_RADAR_OK
    else:
        status = ModelRadarStatus.MODEL_RADAR_PARTIAL

    evidence = {
        "schemaVersion": SCHEMA_VERSION,
        "phase": PHASE,
        "status": status.value,
        "generatedAt": now.isoformat(),
        "gitHead": git_head,
        "economicAssetUid": uid,
        "economicNodeId": node_id,
        "canonicalAssetKey": _canonical_key_from_r9(r9_evidence),
        "modelBinding": (
            binding.to_evidence_dict() if binding else None
        ),
        "modelEvidence": (
            model_evidence.to_evidence_dict() if model_evidence else None
        ),
        "comparability": (
            comparability.to_evidence_dict() if comparability else None
        ),
        "referenceComparison": (
            reference_comparison.to_evidence_dict()
            if reference_comparison else None
        ),
        "executionComparisons": [
            c.to_evidence_dict() for c in execution_comparisons
        ],
        "gaps": [g.to_evidence_dict() for g in gaps],
        "sourceDigests": source_digests,
        "upstreamEvidence": {
            "r9AssetGraphEvidence": _plain(r9_evidence),
            **({"r8ExecutionEvidence": _plain(r8_evidence)}
               if r8_evidence is not None else {}),
        },
        "boundaries": dict(R10_BOUNDARIES),
        "timingPolicy": timing_policy.to_evidence_dict(),
        "synthetic": synthetic,
    }
    digest = digest_payload(evidence)
    evidence["r10SnapshotDigest"] = digest
    return ModelRadarSnapshot(
        status=status,
        generated_at=now,
        git_head=git_head,
        economic_asset_uid=uid,
        economic_node_id=node_id,
        canonical_asset_key=evidence["canonicalAssetKey"],
        model_binding=binding,
        model_evidence=model_evidence,
        comparability=comparability,
        reference_comparison=reference_comparison,
        execution_comparisons=tuple(execution_comparisons),
        gaps=tuple(gaps),
        source_digests=source_digests,
        upstream_evidence=evidence["upstreamEvidence"],
        boundaries=R10_BOUNDARIES,
        timing_policy=timing_policy,
        synthetic=synthetic,
        r10_snapshot_digest=digest,
    )


def _canonical_key_from_r9(r9_evidence: Mapping[str, Any]) -> dict[str, Any]:
    for node in r9_evidence.get("nodes", []):
        if node.get("nodeType") == "TOKEN_DEPLOYMENT":
            key = node.get("canonicalAssetKey") or {}
            if key.get("chainId") is not None:
                return {
                    "chainId": key["chainId"],
                    "contractAddress": key["contractAddress"],
                }
    raise ModelRadarError(
        "embedded R9 evidence carries no token deployment node",
        ModelRadarStatus.MODEL_RADAR_INPUT_INVALID,
    )
