"""R10 bridge: frozen model authority ⇄ R9 asset graph ⇄ Radar market state.

The bridge consumes exact embedded R9 evidence (verified two ways: the
internal r9SnapshotDigest with the frozen R9 verifier, and a canonical
SHA-256 over the COMPLETE embedded evidence — two distinct lineage checks,
never collapsed), resolves semantic economic-identity binding, and assembles
the immutable ModelRadarSnapshot.

Correction A:
- F3: R8 execution evidence is derived from the R9 evidence itself
  (``upstreamEvidence.r8ExecutionEvidence``).  An explicitly supplied R8 is
  accepted only when it is canonically identical to the embedded one; the
  R8 deployment must equal the R9 deployment resolved through that embedded
  authority (never an arbitrary first deployment node), every scenario
  deployment must agree, and every scenario quote source must be a venue
  proven by the R9 QUOTED_ON topology.
- F6: execution comparisons and gaps are canonicalized BEFORE the
  r10SnapshotDigest material is built; the scenario index is assigned after
  canonical scenario ordering, never from caller order.
- F7a: discovery returns model evidence (or a typed gap); binding resolution
  is a separate, explicitly typed step.
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
    ComparabilityDimension,
    ComparabilityState,
    ModelBinding,
    ModelEvidence,
    ModelRadarError,
    ModelRadarGap,
    ModelRadarGapKind,
    ModelRadarStatus,
    ModelRadarTimingPolicy,
    ModelRadarSnapshot,
    ModelUnitBasis,
    TOTAL_BASES,
    _plain,
    decimal_from_evidence,
    digest_payload,
    require_positive_decimal,
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


def discover_model_evidence(
    economic_asset_uid: str,
) -> tuple[ModelEvidence | None, ModelRadarGap | None]:
    """F7a: honest discovery returns MODEL EVIDENCE (or a typed gap).

    The repository contains deterministic project-finance model components
    (XNPV/XIRR/engine orchestrators) but NO source-proven model binding that
    attaches a compatible valuation output to a Radar economic asset.  Until
    such an authority exists this returns the typed MODEL_BINDING_UNAVAILABLE
    gap — successful fail-closed behaviour, never a fabricated valuation.
    Any discovered evidence must still pass resolve_model_binding() before it
    becomes a binding.
    """
    return None, ModelRadarGap(
        gap_kind=ModelRadarGapKind.MODEL_BINDING_UNAVAILABLE,
        source="R10_MODEL_AUTHORITY_DISCOVERY",
        reason=(
            "no frozen FINCO model authority carries a source-proven "
            f"model binding for economic asset {economic_asset_uid}"
        ),
    )


def _embedded_r8(
    r9_evidence: Mapping[str, Any],
    supplied_r8: Mapping[str, Any] | None,
) -> tuple[Mapping[str, Any], dict[str, str]]:
    """F3: derive R8 from the R9 evidence; an explicit argument must be
    canonically identical to the embedded authority."""
    embedded = r9_evidence.get("upstreamEvidence", {}).get("r8ExecutionEvidence")
    if not isinstance(embedded, Mapping) or not embedded:
        raise ModelRadarError(
            "embedded R9 evidence carries no r8ExecutionEvidence",
            ModelRadarStatus.MODEL_RADAR_INPUT_INVALID,
        )
    if supplied_r8 is not None:
        if digest_payload(supplied_r8) != digest_payload(embedded):
            raise _lineage_failure(
                "supplied R8 evidence is not canonically identical to the "
                "R8 embedded inside the R9 evidence; independently valid "
                "but different execution evidence is rejected"
            )
    if not verify_r8_evidence(embedded):
        raise _lineage_failure(
            "embedded R8 evidence fails its r8SnapshotDigest reconstruction"
        )
    digests = {
        "r8ExecutionSimulatorDigest": digest_payload(embedded),
        "r8SnapshotDigest": embedded["r8SnapshotDigest"],
    }
    return embedded, digests


def _resolve_deployment(
    r9_evidence: Mapping[str, Any],
    r8_evidence: Mapping[str, Any],
    uid: str,
) -> dict[str, Any]:
    """F3: the canonical deployment is the one the embedded R8 authority
    actually used — required to appear exactly once among the R9 deployment
    nodes.  An arbitrary first deployment node is never used; ambiguity
    fails closed."""
    r8_key = r8_evidence.get("canonicalAssetKey") or {}
    if r8_key.get("chainId") is None or not r8_key.get("contractAddress"):
        raise _lineage_failure(
            "embedded R8 evidence carries no canonical deployment"
        )
    matches = [
        n for n in r9_evidence.get("nodes", [])
        if n.get("nodeType") == "TOKEN_DEPLOYMENT"
        and (n.get("canonicalAssetKey") or {}).get("chainId") == r8_key.get("chainId")
        and str((n.get("canonicalAssetKey") or {}).get("contractAddress", "")).lower()
        == str(r8_key.get("contractAddress", "")).lower()
    ]
    if len(matches) == 0:
        raise _lineage_failure(
            "the R8 canonical deployment does not exist among the R9 "
            "deployment nodes"
        )
    if len(matches) > 1:
        raise ModelRadarError(
            "ambiguous R9 deployment topology: the R8 canonical deployment "
            "appears more than once",
            ModelRadarStatus.MODEL_RADAR_INPUT_INVALID,
        )
    # Semantic agreement: R8 economic asset and every scenario deployment.
    if r8_evidence.get("economicAssetUid") != uid:
        raise _lineage_failure(
            "embedded R8 economicAssetUid does not equal the R9 economic "
            "asset"
        )
    for scenario in r8_evidence.get("scenarios", []):
        entry = scenario.get("scenario") or {}
        if entry.get("chainId") != r8_key.get("chainId") or str(
            entry.get("contractAddress", "")
        ).lower() != str(r8_key.get("contractAddress", "")).lower():
            raise _lineage_failure(
                "an embedded R8 scenario deployment disagrees with the "
                "canonical deployment"
            )
    # Venue relationship required by frozen R9 authority: every scenario
    # quote source must be a venue connected by a QUOTED_ON edge from the
    # resolved deployment node.
    deployment_node_id = matches[0]["nodeId"]
    venue_nodes = {
        n["nodeId"] for n in r9_evidence.get("nodes", [])
        if n.get("nodeType") == "VENUE"
    }
    quoted_venues = {
        e["toNodeId"] for e in r9_evidence.get("edges", [])
        if e.get("relationshipType") == "QUOTED_ON"
        and e.get("fromNodeId") == deployment_node_id
    }
    for scenario in r8_evidence.get("scenarios", []):
        quote_source = (scenario.get("scenario") or {}).get("quoteSource")
        venue_node_id = f"venue:{quote_source}"
        if venue_node_id not in venue_nodes or venue_node_id not in quoted_venues:
            raise _lineage_failure(
                f"scenario quote source {quote_source!r} is not proven by "
                "the R9 QUOTED_ON topology for the resolved deployment"
            )
    return {
        "chainId": r8_key["chainId"],
        "contractAddress": r8_key["contractAddress"],
    }


def _finite(raw, name: str) -> Decimal:
    """H3: every market-source numeric crosses the canonical typed parser."""
    return decimal_from_evidence(raw, name)


def _positive(raw, name: str) -> Decimal:
    value = decimal_from_evidence(raw, name)
    require_positive_decimal(value, name)
    return value


def _market_context_from_r9(
    r9_evidence: Mapping[str, Any],
) -> tuple[MarketComparabilityContext, ModelRadarGap | None]:
    """Reference context from the R9/R7 oracle-reference layer only.

    F2: the market denominator is explicit (per token claim) and the R7
    oracle/token multipliers are carried verbatim as the only conversion
    authority — never assumed to be 1.
    """
    r7 = (
        r9_evidence.get("upstreamEvidence", {})
        .get("r8ExecutionEvidence", {})
        .get("upstreamEvidence", {})
        .get("r7CrossMarketEvidence", {})
    )
    layers = (r7 or {}).get("layers", {})
    oracle = layers.get("oracleReference")
    token = layers.get("token") or {}
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
            market_unit_basis=None,
            conversion_multiplier=None,
            token_multiplier=None,
        ), ModelRadarGap(
            gap_kind=ModelRadarGapKind.REFERENCE_UNAVAILABLE,
            source="R9_ASSET_GRAPH_AUTHORITY",
            reason="R9 oracle-reference layer is not an available reference",
        )
    from datetime import datetime as _dt
    oracle_multiplier = oracle.get("multiplier")
    token_multiplier = token.get("multiplier")
    reference_price = decimal_from_evidence(
        oracle["price"], "R7 oracle reference price")
    require_positive_decimal(reference_price, "R7 oracle reference price")
    context = MarketComparabilityContext(
        reference_price=reference_price,
        reference_currency=oracle.get("currency"),
        reference_source=oracle.get("source"),
        reference_observed_at=_dt.fromisoformat(oracle["observedAt"]),
        market_unit_basis=ModelUnitBasis.PER_TOKEN_CLAIM,
        conversion_multiplier=(
            _positive(oracle_multiplier, "R7 oracle multiplier")
            if oracle_multiplier is not None else None
        ),
        token_multiplier=(
            _positive(token_multiplier, "R7 token multiplier")
            if token_multiplier is not None else None
        ),
    )
    return context, None


def _execution_comparisons_and_gaps(
    *,
    comparable_value: Decimal,
    r8_evidence: Mapping[str, Any],
) -> tuple[list, list[ModelRadarGap]]:
    """F6: scenarios are ordered canonically before indexing; comparison
    rows therefore never depend on caller order."""
    scenarios = list(r8_evidence.get("scenarios", []))
    for scenario in scenarios:
        notional_raw = (scenario.get("scenario") or {}).get(
            "requestedNotionalUsd")
        require_positive_decimal(
            decimal_from_evidence(notional_raw, "R8 requestedNotionalUsd"),
            "R8 requestedNotionalUsd")
    scenarios.sort(key=lambda s: (
        (s.get("scenario") or {}).get("side", ""),
        decimal_from_evidence(
            (s.get("scenario") or {}).get("requestedNotionalUsd"),
            "R8 requestedNotionalUsd"),
        (s.get("scenario") or {}).get("quoteSource", ""),
    ))
    comparisons = []
    gaps: list[ModelRadarGap] = []
    for index, scenario in enumerate(scenarios):
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
        execution_price = decimal_from_evidence(
            raw_price, "R8 execution price")
        require_positive_decimal(execution_price, "R8 execution price")
        comparisons.append(compute_execution_comparison(
            model_value_per_unit=comparable_value,
            execution_price=execution_price,
            side=entry.get("side", ""),
            requested_notional_usd=str(entry.get("requestedNotionalUsd", "")),
            quote_source=entry.get("quoteSource", ""),
            r8_net_edge_state=scenario.get("netEdgeState", ""),
            r8_scenario_index=index,
        ))
    comparisons.sort(key=lambda c: (
        c.side, Decimal(c.requested_notional_usd), c.quote_source))
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
    r8_evidence, r8_digests = _embedded_r8(r9_evidence, r8_evidence)
    canonical_key = _resolve_deployment(r9_evidence, r8_evidence, uid)

    gaps: list[ModelRadarGap] = []
    binding: ModelBinding | None = None

    if model_evidence is not None and model_evidence.synthetic is not True:
        # G1: a caller-built, digest-valid, non-synthetic model observation
        # is NOT live model authority.  Non-synthetic model evidence may only
        # enter through the discovery/source-authority adapter; since no
        # source-proven live binding exists, non-synthetic comparison stays
        # unavailable.  Fail closed with a typed gap, publish nothing.
        gaps.append(ModelRadarGap(
            gap_kind=ModelRadarGapKind.MODEL_SOURCE_AUTHORITY_UNAVAILABLE,
            source="R10_MODEL_AUTHORITY_DISCOVERY",
            reason=(
                "non-synthetic model evidence was supplied directly by the "
                "caller; it did not come through an allowed frozen FINCO "
                "model-authority path and is therefore not model authority"
            ),
        ))
        gaps.append(ModelRadarGap(
            gap_kind=ModelRadarGapKind.MODEL_BINDING_UNAVAILABLE,
            source="R10_MODEL_AUTHORITY_DISCOVERY",
            reason="no source-proven model binding exists for this asset",
        ))
        model_evidence = None
    if model_evidence is None:
        # F7a: discovery yields evidence (or a typed gap); the binding is a
        # separate resolved step.
        discovered, discovered_gap = discover_model_evidence(uid)
        if discovered is None:
            if not any(g.gap_kind is ModelRadarGapKind.MODEL_BINDING_UNAVAILABLE
                       for g in gaps):
                gaps.append(discovered_gap)
        else:
            model_evidence = discovered

    market_context, reference_gap = _market_context_from_r9(r9_evidence)
    if reference_gap is not None:
        gaps.append(reference_gap)

    comparability = None
    reference_comparison = None
    execution_comparisons: list = []

    if model_evidence is not None:
        binding = resolve_model_binding(
            model_evidence=model_evidence, r9_lineage=lineage)
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
            # F5: FX absence accompanies the single CURRENCY result as a
            # snapshot gap, never as a duplicated dimension row.
            if (
                dimension.dimension is ComparabilityDimension.CURRENCY
                and dimension.gap_kind is ModelRadarGapKind.CURRENCY_MISMATCH
            ):
                gaps.append(ModelRadarGap(
                    gap_kind=ModelRadarGapKind.FX_AUTHORITY_UNAVAILABLE,
                    source="R10_COMPARABILITY",
                    reason="no explicit FX conversion authority exists for "
                           "this currency pair",
                ))
        if comparability.state is ComparabilityState.COMPARABLE:
            per_unit = model_value_per_unit(model_evidence)
            # F2: the frozen R7 conversion multiplier is applied exactly
            # once, and only when the model denominator differs from the
            # market token-claim denominator.
            model_basis = (
                model_evidence.unit_multiplier_basis
                if model_evidence.unit_basis in TOTAL_BASES
                else model_evidence.unit_basis
            )
            if model_basis is market_context.market_unit_basis:
                comparable_value = per_unit
            else:
                comparable_value = per_unit * market_context.conversion_multiplier
            if market_context.reference_price is not None:
                reference_comparison = compute_reference_comparison(
                    model_value_per_unit=comparable_value,
                    reference_price=market_context.reference_price,
                    reference_source=market_context.reference_source or "",
                    model_observed_at=model_evidence.valuation_as_of,
                    reference_observed_at=(
                        market_context.reference_observed_at or now),
                )
            exec_comparisons, exec_gaps = _execution_comparisons_and_gaps(
                comparable_value=comparable_value, r8_evidence=r8_evidence)
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

    # F6: canonical order BEFORE the digest material is built.
    gaps.sort(key=lambda g: (g.gap_kind.value, g.source, g.reason))
    status = (
        ModelRadarStatus.MODEL_RADAR_OK
        if not gaps else ModelRadarStatus.MODEL_RADAR_PARTIAL
    )
    # G2/H2: the published synthetic state is DERIVED from causal evidence
    # using EXACT boolean provenance.  Missing / null / "false" / 0 /
    # malformed flags are never interpreted as live/non-synthetic authority:
    # they are typed input errors.
    def _provenance(value):
        if value is True:
            return "TRUE"
        if value is False:
            return "FALSE"
        return "MALFORMED"

    r7_lineage = (r8_evidence.get("upstreamEvidence") or {}).get(
        "r7CrossMarketEvidence", {})
    provenance = {
        "r9": _provenance(r9_evidence.get("synthetic")),
        "r8": _provenance(r8_evidence.get("synthetic")),
        "r7": _provenance(r7_lineage.get("synthetic")),
    }
    malformed = sorted(k for k, v in provenance.items() if v == "MALFORMED")
    if malformed:
        raise ModelRadarError(
            "causal evidence layers carry missing/malformed synthetic "
            f"provenance for {malformed}; non-synthetic authority requires "
            "the exact boolean false",
            ModelRadarStatus.MODEL_RADAR_INPUT_INVALID,
        )
    derived_synthetic = bool(
        synthetic
        or (model_evidence is not None and model_evidence.synthetic)
        or "TRUE" in provenance.values()
    )
    evidence = {
        "schemaVersion": SCHEMA_VERSION,
        "phase": PHASE,
        "status": status.value,
        "generatedAt": now.isoformat(),
        "gitHead": git_head,
        "economicAssetUid": uid,
        "economicNodeId": node_id,
        "canonicalAssetKey": canonical_key,
        "modelBinding": binding.to_evidence_dict() if binding else None,
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
            "r8ExecutionEvidence": _plain(r8_evidence),
        },
        "boundaries": dict(R10_BOUNDARIES),
        "timingPolicy": timing_policy.to_evidence_dict(),
        "synthetic": derived_synthetic,
    }
    digest = digest_payload(evidence)
    evidence["r10SnapshotDigest"] = digest
    return ModelRadarSnapshot(
        status=status,
        generated_at=now,
        git_head=git_head,
        economic_asset_uid=uid,
        economic_node_id=node_id,
        canonical_asset_key=canonical_key,
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
        synthetic=derived_synthetic,
        r10_snapshot_digest=digest,
    )
