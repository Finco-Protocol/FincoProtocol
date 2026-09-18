"""R12 Digital Twin builder: constructs a deterministic, typed state
representation from independently verified R11 evidence.

R12 consumes only serialized R11 evidence that passes the R11 authority
contract.  It does NOT independently redo R10/R9/R8/R7 verification.
"""
from __future__ import annotations

from datetime import datetime
from typing import Any, Mapping

from finco_radar.verification.contracts import (
    R11_BOUNDARIES,
    R10_FREEZE_ANCHOR,
    R10_FREEZE_TREE,
    verify_serialized_r11_evidence,
)

from .contracts import (
    ComponentId,
    ComponentState,
    DigitalTwinSnapshot,
    DigitalTwinStatus,
    PHASE,
    R11_FREEZE_ANCHOR,
    R11_FREEZE_TREE,
    R12_BOUNDARIES,
    SCHEMA_VERSION,
    TwinComponent,
    TwinError,
    TwinGap,
    TwinGapKind,
    canonical_sha256,
    deep_freeze,
    plain,
    stable_twin_id,
)


def _mapping_or_none(value: Any) -> "Mapping | None":
    if value is None:
        return None
    if isinstance(value, Mapping):
        return value
    raise TwinError(f"expected Mapping, got {type(value).__name__}",
                     DigitalTwinStatus.DIGITAL_TWIN_INPUT_INVALID)


def _extract_component(
    component_id: str,
    state: ComponentState,
    source_phase: str,
    source_digest: str,
    detail: str = "",
) -> TwinComponent:
    return TwinComponent(
        component_id=component_id,
        state=state,
        source_phase=source_phase,
        source_digest=source_digest,
        detail=detail,
    )


def build_digital_twin(
    *,
    r11_evidence: Mapping[str, Any],
    generated_at: datetime,
    git_head: str,
    synthetic: bool = False,
) -> DigitalTwinSnapshot:
    """Build a deterministic Digital Twin from verified R11 evidence.

    R12 consumes only R11 evidence whose status is VERIFICATION_OK.
    The caller must NOT fabricate model authority.
    """
    if not isinstance(r11_evidence, Mapping) or not r11_evidence:
        raise TwinError(
            "R11 evidence is empty or not a mapping",
            DigitalTwinStatus.DIGITAL_TWIN_INPUT_INVALID)

    # Independent R11 digest reconstruction
    recorded_digest = r11_evidence.get("r11SnapshotDigest")
    if not isinstance(recorded_digest, str) or not recorded_digest:
        raise TwinError(
            "r11SnapshotDigest missing or malformed",
            DigitalTwinStatus.DIGITAL_TWIN_EVIDENCE_MISMATCH)
    material = plain(r11_evidence)
    material.pop("r11SnapshotDigest", None)
    reconstructed = canonical_sha256(material)
    if reconstructed != recorded_digest:
        raise TwinError(
            f"R11 snapshot digest does not reconstruct "
            f"({reconstructed[:16]} != {recorded_digest[:16]})",
            DigitalTwinStatus.DIGITAL_TWIN_EVIDENCE_MISMATCH)

    # Freeze authority handshake
    from finco_radar.verification.contracts import (
        R10_FREEZE_ANCHOR, R10_FREEZE_TREE,
    )
    if r11_evidence.get("freezeAnchor") != R10_FREEZE_ANCHOR:
        raise TwinError(
            "R11 evidence freezeAnchor does not match the R0-R10 freeze "
            "authority",
            DigitalTwinStatus.DIGITAL_TWIN_EVIDENCE_MISMATCH)
    if r11_evidence.get("subjectAuthorityTree") != R10_FREEZE_TREE:
        raise TwinError(
            "R11 evidence subjectAuthorityTree does not match the R0-R10 "
            "freeze tree",
            DigitalTwinStatus.DIGITAL_TWIN_EVIDENCE_MISMATCH)

    # R11 status must be VERIFICATION_OK (checked before frozen verifier
    # cross-check so a resealed status mutation produces the specific
    # VERIFICATION_REJECTED status, not a generic EVIDENCE_MISMATCH)
    r11_status = r11_evidence.get("status")
    if r11_status != "VERIFICATION_OK":
        raise TwinError(
            f"R11 status is {r11_status!r}, not VERIFICATION_OK; R12 "
            "cannot construct an authoritative twin",
            DigitalTwinStatus.DIGITAL_TWIN_VERIFICATION_REJECTED)

    # Frozen R11 serialized verifier as secondary cross-check
    from finco_radar.verification.contracts import (
        verify_serialized_r11_evidence,
    )
    if not verify_serialized_r11_evidence(r11_evidence):
        raise TwinError(
            "frozen R11 verifier cross-check failed",
            DigitalTwinStatus.DIGITAL_TWIN_EVIDENCE_MISMATCH)

    # Economic identity
    uid = r11_evidence.get("economicAssetUid")
    node = r11_evidence.get("economicNodeId")
    if not uid or not node:
        raise TwinError(
            "R11 evidence carries no economic identity",
            DigitalTwinStatus.DIGITAL_TWIN_INPUT_INVALID)

    twin_id = stable_twin_id(uid, node)

    # Extract upstream R10 subject evidence
    r10 = r11_evidence.get("subjectEvidence") if isinstance(
        r11_evidence.get("subjectEvidence"), Mapping) else {}

    # Component states
    components: list[TwinComponent] = []
    twin_gaps: list[TwinGap] = []
    upstream_gaps: list[dict] = []

    # Preserve upstream R10 gaps verbatim
    for gap in r10.get("gaps") or []:
        if isinstance(gap, Mapping):
            upstream_gaps.append(dict(gap))

    # IDENTITY_GRAPH — always available from verified R11/R9
    components.append(TwinComponent(
        component_id="IDENTITY_GRAPH", state=ComponentState.AVAILABLE,
        source_phase="R9", source_digest=r11_evidence.get(
            "sourceDigests", {}).get("r9AssetGraphDigest", ""),
        detail="verified R9 asset graph identity"))

    # DEPLOYMENT_STATE — available if canonical deployment exists
    r10_key = r10.get("canonicalAssetKey") if isinstance(
        r10.get("canonicalAssetKey"), Mapping) else None
    deployment_state = r10_key
    if r10_key:
        components.append(TwinComponent(
            component_id="DEPLOYMENT_STATE", state=ComponentState.AVAILABLE,
            source_phase="R10",
            source_digest=r11_evidence.get("sourceDigests", {}).get(
                "r8ExecutionSimulatorDigest", ""),
            detail="canonical deployment from verified R8/R9 lineage"))
    else:
        components.append(TwinComponent(
            component_id="DEPLOYMENT_STATE", state=ComponentState.UNAVAILABLE,
            source_phase="R10", source_digest="",
            detail="no canonical deployment in verified lineage"))
        twin_gaps.append(TwinGap(
            gap_kind=TwinGapKind.DEPLOYMENT_COMPONENT_UNAVAILABLE,
            source="R12_DIGITAL_TWIN", reason="no canonical deployment"))

    # VERIFICATION_STATE — always available from verified R11
    components.append(TwinComponent(
        component_id="VERIFICATION_STATE", state=ComponentState.AVAILABLE,
        source_phase="R11",
        source_digest=recorded_digest,
        detail="R11 verification authority"))

    # REFERENCE_STATE — from R7 oracle in the verified chain
    r7 = (r10.get("upstreamEvidence") or {}).get(
        "r8ExecutionEvidence", {}).get(
        "upstreamEvidence", {}).get("r7CrossMarketEvidence", {})
    oracle = (r7.get("layers") or {}).get("oracleReference") or {}
    if oracle.get("status") == "AVAILABLE" and oracle.get("price"):
        reference_state = {
            "source": oracle.get("source"),
            "observedAt": oracle.get("observedAt"),
            "currency": oracle.get("currency"),
            "price": oracle.get("price"),
            "sourceDigest": r11_evidence.get("sourceDigests", {}).get(
                "r7CrossMarketDigest", ""),
        }
        components.append(TwinComponent(
            component_id="REFERENCE_STATE", state=ComponentState.AVAILABLE,
            source_phase="R7",
            source_digest=r11_evidence.get("sourceDigests", {}).get(
                "r7CrossMarketDigest", ""),
            detail="verified R7 oracle reference"))
    else:
        reference_state = None
        components.append(TwinComponent(
            component_id="REFERENCE_STATE", state=ComponentState.UNAVAILABLE,
            source_phase="R7", source_digest="",
            detail="R7 oracle reference not available"))
        twin_gaps.append(TwinGap(
            gap_kind=TwinGapKind.REFERENCE_COMPONENT_UNAVAILABLE,
            source="R12_DIGITAL_TWIN", reason="no R7 oracle reference"))

    # EXECUTION_STATE — from verified R8 scenarios
    r8_scenarios = (r10.get("upstreamEvidence") or {}).get(
        "r8ExecutionEvidence", {}).get("scenarios") or []
    if r8_scenarios:
        execution_state = {
            "scenarioCount": len(r8_scenarios),
            "sourceDigest": r11_evidence.get("sourceDigests", {}).get(
                "r8ExecutionSimulatorDigest", ""),
        }
        components.append(TwinComponent(
            component_id="EXECUTION_STATE", state=ComponentState.AVAILABLE,
            source_phase="R8",
            source_digest=r11_evidence.get("sourceDigests", {}).get(
                "r8ExecutionSimulatorDigest", ""),
            detail=f"{len(r8_scenarios)} verified R8 scenarios"))
    else:
        execution_state = None
        components.append(TwinComponent(
            component_id="EXECUTION_STATE", state=ComponentState.UNAVAILABLE,
            source_phase="R8", source_digest="",
            detail="no verified R8 execution scenarios"))
        twin_gaps.append(TwinGap(
            gap_kind=TwinGapKind.EXECUTION_COMPONENT_UNAVAILABLE,
            source="R12_DIGITAL_TWIN", reason="no R8 execution evidence"))

    # MODEL_STATE — from verified R10 model evidence only
    model_evidence = r10.get("modelEvidence")
    model_binding = r10.get("modelBinding")
    if model_evidence is not None:
        model_state = {
            "modelId": model_evidence.get("modelId"),
            "modelVersion": model_evidence.get("modelVersion"),
            "valueKind": model_evidence.get("valueKind"),
            "value": model_evidence.get("value"),
            "currency": model_evidence.get("currency"),
            "unitBasis": model_evidence.get("unitBasis"),
            "sourceDigest": r11_evidence.get("sourceDigests", {}).get(
                "modelRunDigest", ""),
        }
        components.append(TwinComponent(
            component_id="MODEL_STATE", state=ComponentState.AVAILABLE,
            source_phase="R10",
            source_digest=r11_evidence.get("sourceDigests", {}).get(
                "modelRunDigest", ""),
            detail="verified R10 model evidence"))
    else:
        model_state = None
        components.append(TwinComponent(
            component_id="MODEL_STATE", state=ComponentState.UNAVAILABLE,
            source_phase="R10", source_digest="",
            detail="no model binding in verified R10 evidence"))
        twin_gaps.append(TwinGap(
            gap_kind=TwinGapKind.MODEL_COMPONENT_UNAVAILABLE,
            source="R12_DIGITAL_TWIN",
            reason="no model binding in the verified R10 subject"))

    # COMPARABILITY_STATE — optional
    comparability = r10.get("comparability")
    if comparability is not None:
        components.append(TwinComponent(
            component_id="COMPARABILITY_STATE",
            state=ComponentState.AVAILABLE,
            source_phase="R10", source_digest="",
            detail="serialized comparability state"))

    # Synthetic derivation
    derived_synthetic = bool(
        synthetic
        or r11_evidence.get("synthetic") is True
        or r10.get("synthetic") is True
        or r9.get("synthetic") is True
        or (r8.get("synthetic") is True)
        or (r7.get("synthetic") is True)
    )

    # Source digests (from R11)
    source_digests = dict(r11_evidence.get("sourceDigests") or {})

    # Boundaries
    boundaries = dict(R12_BOUNDARIES)

    # Sort canonical orderings
    components.sort(key=lambda c: c.component_id)
    twin_gaps.sort(key=lambda g: (g.gap_kind.value, g.source, g.reason))
    upstream_gaps.sort(key=lambda g: (g.get("gapKind", ""),
                                      g.get("source", ""),
                                      g.get("reason", "")))

    # Determine status
    if not twin_gaps:
        status = DigitalTwinStatus.DIGITAL_TWIN_OK
    else:
        status = DigitalTwinStatus.DIGITAL_TWIN_PARTIAL

    # Build evidence and digest
    verification_block = {
        "status": r11_status,
        "r11SnapshotDigest": recorded_digest,
        "subjectR10SnapshotDigest": r10.get("r10SnapshotDigest", ""),
        "freezeAnchor": R11_FREEZE_ANCHOR,
        "failedCheckCount": sum(
            1 for c in r11_evidence.get("checks", [])
            if isinstance(c, Mapping) and c.get("state") == "FAIL"),
        "unavailableCheckCount": sum(
            1 for c in r11_evidence.get("checks", [])
            if isinstance(c, Mapping) and c.get("state") == "UNAVAILABLE"),
    }

    evidence = {
        "schemaVersion": SCHEMA_VERSION,
        "phase": PHASE,
        "status": status.value,
        "generatedAt": generated_at.isoformat(),
        "gitHead": git_head,
        "twinId": twin_id,
        "economicAssetUid": uid,
        "economicNodeId": node,
        "components": [c.to_evidence_dict() for c in components],
        "deploymentState": deployment_state,
        "referenceState": reference_state,
        "executionState": execution_state,
        "modelState": model_state,
        "comparabilityState": r10.get("comparability"),
        "verification": verification_block,
        "upstreamGaps": upstream_gaps,
        "twinGaps": [g.to_evidence_dict() for g in twin_gaps],
        "sourceDigests": source_digests,
        "subjectR11Evidence": plain(r11_evidence),
        "boundaries": boundaries,
        "freezeAnchor": R11_FREEZE_ANCHOR,
        "freezeTree": R11_FREEZE_TREE,
        "synthetic": derived_synthetic,
    }
    digest = canonical_sha256(evidence)
    evidence["r12SnapshotDigest"] = digest

    return DigitalTwinSnapshot(
        status=status,
        generated_at=generated_at,
        git_head=git_head,
        twin_id=twin_id,
        economic_asset_uid=uid,
        economic_node_id=node,
        components=tuple(sorted(components, key=lambda c: c.component_id)),
        deployment_state=deployment_state,
        reference_state=reference_state,
        execution_state=execution_state,
        model_state=model_state,
        comparability_state=r10.get("comparability"),
        verification=verification_block,
        upstream_gaps=tuple(upstream_gaps),
        twin_gaps=tuple(twin_gaps),
        source_digests=source_digests,
        subject_r11_evidence=r11_evidence,
        boundaries=boundaries,
        freeze_anchor=R11_FREEZE_ANCHOR,
        freeze_tree=R11_FREEZE_TREE,
        synthetic=derived_synthetic,
        r12_snapshot_digest=digest,
    )
