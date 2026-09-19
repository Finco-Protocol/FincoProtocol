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
    MANDATORY_COMPONENT_IDS,
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


def _require_mapping(container: Any, name: str) -> Mapping:
    """A9: authority-bearing structures must be Mappings — absent/null and
    wrong types are typed failures, never falsy-swapped defaults."""
    if not isinstance(container, Mapping):
        raise TwinError(
            f"{name} must be a mapping, got {type(container).__name__}",
            DigitalTwinStatus.DIGITAL_TWIN_INPUT_INVALID)
    return container


def _require_sequence(container: Any, name: str) -> list:
    if not isinstance(container, list):
        raise TwinError(
            f"{name} must be a list, got {type(container).__name__}",
            DigitalTwinStatus.DIGITAL_TWIN_INPUT_INVALID)
    return container


def _optional_mapping(container: Any, name: str) -> "Mapping | None":
    if container is None:
        return None
    if not isinstance(container, Mapping):
        raise TwinError(
            f"{name} must be a mapping or absent, got "
            f"{type(container).__name__}",
            DigitalTwinStatus.DIGITAL_TWIN_INPUT_INVALID)
    return container


def _require_str(value: Any, name: str) -> str:
    if not isinstance(value, str) or not value.strip():
        raise TwinError(
            f"{name} must be a non-empty string, got {value!r}",
            DigitalTwinStatus.DIGITAL_TWIN_INPUT_INVALID)
    return value


def _exact_bool(value: Any, name: str) -> None:
    """A8: upstream synthetic flags are contract-required exact booleans;
    truthy coercion (bool(value)) would launder \"false\"/1/[]/{} into
    authority and is rejected."""
    if type(value) is not bool:
        raise TwinError(
            f"{name} must be an exact boolean, got {value!r}",
            DigitalTwinStatus.DIGITAL_TWIN_INPUT_INVALID)


def build_digital_twin(
    *,
    r11_evidence: Mapping[str, Any],
    generated_at: datetime,
    git_head: str,
) -> DigitalTwinSnapshot:
    """Build a deterministic Digital Twin from verified R11 evidence.

    This is the ONE canonical R12 composition authority.  R12 consumes
    only R11 evidence whose status is VERIFICATION_OK and that passes the
    corrected canonical R11 serialized verifier.  Model authority is never
    fabricated: MODEL_STATE is composed exclusively from verified R10
    model evidence.

    A8: synthetic state is DERIVED from the verified causal chain
    (R11/R10/R9/R8/R7); there is NO caller-controlled synthetic override.
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

    # Freeze authority handshake (the historical R10 authority R11
    # verified against — separate from the R11 authority consumed here).
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

    # R11 status must be VERIFICATION_OK (checked before the canonical
    # serialized verifier cross-check so a resealed status mutation
    # produces the specific VERIFICATION_REJECTED status).
    r11_status = r11_evidence.get("status")
    if r11_status != "VERIFICATION_OK":
        raise TwinError(
            f"R11 status is {r11_status!r}, not VERIFICATION_OK; R12 "
            "cannot construct an authoritative twin",
            DigitalTwinStatus.DIGITAL_TWIN_VERIFICATION_REJECTED)

    # The corrected canonical R11 serialized verification authority
    # (R11 Correction A, PR #32) — no local R11 re-implementation.
    if not verify_serialized_r11_evidence(r11_evidence):
        raise TwinError(
            "canonical R11 serialized verification failed",
            DigitalTwinStatus.DIGITAL_TWIN_EVIDENCE_MISMATCH)

    # Economic identity (validated by the R11 verifier; re-checked here
    # as composition inputs).
    uid = _require_str(r11_evidence.get("economicAssetUid"),
                       "economicAssetUid")
    node = _require_str(r11_evidence.get("economicNodeId"),
                        "economicNodeId")
    twin_id = stable_twin_id(uid, node)

    # Exact R11/R10 digest lineage (A4): the R11 observation consumed is
    # bound by digest, not merely by economic identity.
    subject_snapshot_digest = r11_evidence.get("subjectSnapshotDigest")
    if not isinstance(subject_snapshot_digest, str) or (
        not subject_snapshot_digest
    ):
        raise TwinError(
            "R11 evidence carries no subjectSnapshotDigest binding",
            DigitalTwinStatus.DIGITAL_TWIN_EVIDENCE_MISMATCH)

    # ---- A9: explicit fail-closed extraction of every authority-bearing
    # container consumed by composition (no `or {}` / `or []` fallbacks).
    r10 = _require_mapping(r11_evidence.get("subjectEvidence"),
                           "subjectEvidence")
    source_digests = _require_mapping(r11_evidence.get("sourceDigests"),
                                      "sourceDigests")
    for key, value in source_digests.items():
        if not isinstance(value, str):
            raise TwinError(
                f"sourceDigests.{key} must be a string",
                DigitalTwinStatus.DIGITAL_TWIN_INPUT_INVALID)
    upstream = _require_mapping(r10.get("upstreamEvidence"),
                                "subjectEvidence.upstreamEvidence")
    r9 = _require_mapping(upstream.get("r9AssetGraphEvidence"),
                          "r9AssetGraphEvidence")
    r8 = _require_mapping(upstream.get("r8ExecutionEvidence"),
                          "r8ExecutionEvidence")
    r8_source_digests = _require_mapping(r8.get("sourceDigests"),
                                         "r8 sourceDigests")
    r8_upstream = _require_mapping(r8.get("upstreamEvidence"),
                                   "r8 upstreamEvidence")
    r7 = _require_mapping(r8_upstream.get("r7CrossMarketEvidence"),
                          "r7CrossMarketEvidence")
    layers = _require_mapping(r7.get("layers"), "r7 layers")
    oracle = _optional_mapping(layers.get("oracleReference"),
                               "r7 oracleReference")
    scenarios = _require_sequence(r8.get("scenarios"), "r8 scenarios")
    r10_gaps = _require_sequence(r10.get("gaps"), "subject gaps")
    for gap in r10_gaps:
        _require_mapping(gap, "subject gap member")
    r10_key = _require_mapping(r10.get("canonicalAssetKey"),
                               "canonicalAssetKey")
    model_evidence = _optional_mapping(r10.get("modelEvidence"),
                                       "modelEvidence")
    comparability = _optional_mapping(r10.get("comparability"),
                                      "comparability")
    checks = _require_sequence(r11_evidence.get("checks"), "r11 checks")
    for check in checks:
        _require_mapping(check, "r11 check member")

    # ---- A8: synthetic state derived ONLY from the verified causal
    # chain; every upstream flag must be an exact boolean.
    _exact_bool(r11_evidence.get("synthetic"), "r11 synthetic")
    _exact_bool(r10.get("synthetic"), "r10 synthetic")
    _exact_bool(r9.get("synthetic"), "r9 synthetic")
    _exact_bool(r8.get("synthetic"), "r8 synthetic")
    _exact_bool(r7.get("synthetic"), "r7 synthetic")
    derived_synthetic = bool(
        r11_evidence.get("synthetic") is True
        or r10.get("synthetic") is True
        or r9.get("synthetic") is True
        or r8.get("synthetic") is True
        or r7.get("synthetic") is True
    )

    # ---- Composition ------------------------------------------------------
    components: list[TwinComponent] = []
    twin_gaps: list[TwinGap] = []
    upstream_gaps: list[dict] = []

    # Preserve upstream R10 gaps verbatim, separately from R12-owned gaps.
    for gap in r10_gaps:
        upstream_gaps.append(dict(gap))

    r9_digest = source_digests.get("r9AssetGraphDigest")
    r8_digest = source_digests.get("r8ExecutionSimulatorDigest")
    r7_digest = r8_source_digests.get("r7CrossMarketDigest")

    # IDENTITY_GRAPH — always available from the verified R9 graph.
    components.append(TwinComponent(
        component_id=ComponentId.IDENTITY_GRAPH,
        state=ComponentState.AVAILABLE,
        source_phase="R9",
        source_digest=_require_str(r9_digest,
                                   "sourceDigests.r9AssetGraphDigest"),
        detail="verified R9 asset graph identity"))

    # DEPLOYMENT_STATE — canonical deployment from the verified lineage.
    deployment_state = dict(r10_key)
    components.append(TwinComponent(
        component_id=ComponentId.DEPLOYMENT_STATE,
        state=ComponentState.AVAILABLE,
        source_phase="R10",
        source_digest=_require_str(r8_digest,
                                   "sourceDigests.r8ExecutionSimulatorDigest"),
        detail="canonical deployment from verified R8/R9 lineage"))

    # VERIFICATION_STATE — always available from the verified R11
    # observation (bound by its exact snapshot digest, A4).
    components.append(TwinComponent(
        component_id=ComponentId.VERIFICATION_STATE,
        state=ComponentState.AVAILABLE,
        source_phase="R11",
        source_digest=recorded_digest,
        detail="R11 verification authority"))

    # REFERENCE_STATE — from the verified R7 oracle in the causal chain.
    if oracle is not None and oracle.get("status") == "AVAILABLE" and (
        oracle.get("price") is not None
    ):
        reference_state = {
            "source": oracle.get("source"),
            "observedAt": oracle.get("observedAt"),
            "currency": oracle.get("currency"),
            "price": oracle.get("price"),
            "sourceDigest": _require_str(
                r7_digest, "r8 sourceDigests.r7CrossMarketDigest"),
        }
        components.append(TwinComponent(
            component_id=ComponentId.REFERENCE_STATE,
            state=ComponentState.AVAILABLE,
            source_phase="R7",
            source_digest=_require_str(
                r7_digest, "r8 sourceDigests.r7CrossMarketDigest"),
            detail="verified R7 oracle reference"))
    else:
        reference_state = None
        components.append(TwinComponent(
            component_id=ComponentId.REFERENCE_STATE,
            state=ComponentState.UNAVAILABLE,
            source_phase="R7", source_digest="",
            detail="R7 oracle reference not available"))
        twin_gaps.append(TwinGap(
            gap_kind=TwinGapKind.REFERENCE_COMPONENT_UNAVAILABLE,
            source="R12_DIGITAL_TWIN", reason="no R7 oracle reference"))

    # EXECUTION_STATE — from the verified R8 scenarios.
    if len(scenarios) > 0:
        execution_state = {
            "scenarioCount": len(scenarios),
            "sourceDigest": _require_str(
                r8_digest,
                "sourceDigests.r8ExecutionSimulatorDigest"),
        }
        components.append(TwinComponent(
            component_id=ComponentId.EXECUTION_STATE,
            state=ComponentState.AVAILABLE,
            source_phase="R8",
            source_digest=_require_str(
                r8_digest,
                "sourceDigests.r8ExecutionSimulatorDigest"),
            detail=f"{len(scenarios)} verified R8 scenarios"))
    else:
        execution_state = None
        components.append(TwinComponent(
            component_id=ComponentId.EXECUTION_STATE,
            state=ComponentState.UNAVAILABLE,
            source_phase="R8", source_digest="",
            detail="no verified R8 execution scenarios"))
        twin_gaps.append(TwinGap(
            gap_kind=TwinGapKind.EXECUTION_COMPONENT_UNAVAILABLE,
            source="R12_DIGITAL_TWIN", reason="no R8 execution evidence"))

    # MODEL_STATE — composed ONLY from verified R10 model evidence; never
    # fabricated when the model authority is absent.
    if model_evidence is not None:
        model_state = {
            "modelId": model_evidence.get("modelId"),
            "modelVersion": model_evidence.get("modelVersion"),
            "valueKind": model_evidence.get("valueKind"),
            "value": model_evidence.get("value"),
            "currency": model_evidence.get("currency"),
            "unitBasis": model_evidence.get("unitBasis"),
            "sourceDigest": _require_str(
                source_digests.get("modelRunDigest"),
                "sourceDigests.modelRunDigest"),
        }
        components.append(TwinComponent(
            component_id=ComponentId.MODEL_STATE,
            state=ComponentState.AVAILABLE,
            source_phase="R10",
            source_digest=_require_str(
                source_digests.get("modelRunDigest"),
                "sourceDigests.modelRunDigest"),
            detail="verified R10 model evidence"))
    else:
        model_state = None
        components.append(TwinComponent(
            component_id=ComponentId.MODEL_STATE,
            state=ComponentState.UNAVAILABLE,
            source_phase="R10", source_digest="",
            detail="no model binding in verified R10 evidence"))
        twin_gaps.append(TwinGap(
            gap_kind=TwinGapKind.MODEL_COMPONENT_UNAVAILABLE,
            source="R12_DIGITAL_TWIN",
            reason="no model binding in the verified R10 subject"))

    # COMPARABILITY_STATE — optional; present only when the verified R10
    # subject carries canonical comparability authority.
    if comparability is not None:
        components.append(TwinComponent(
            component_id=ComponentId.COMPARABILITY_STATE,
            state=ComponentState.AVAILABLE,
            source_phase="R10",
            source_digest=subject_snapshot_digest,
            detail="serialized comparability state"))

    # ---- Canonical orderings ----------------------------------------------
    components.sort(key=lambda c: c.component_id)
    twin_gaps.sort(key=lambda g: (g.gap_kind.value, g.source, g.reason))
    upstream_gaps.sort(key=lambda g: (g.get("gapKind", ""),
                                      g.get("source", ""),
                                      g.get("reason", "")))

    # ---- A7: status represents COMPOSITION COMPLETENESS only --------------
    # DIGITAL_TWIN_OK requires every mandatory component AVAILABLE and zero
    # R12-owned gaps; otherwise the twin is honestly PARTIAL with typed
    # R12 gaps.  Upstream R10/R11 gaps remain separately preserved.
    mandatory_states = {
        c.component_id: c.state for c in components
        if c.component_id in MANDATORY_COMPONENT_IDS
    }
    if (not twin_gaps
            and all(state is ComponentState.AVAILABLE
                    for state in mandatory_states.values())):
        status = DigitalTwinStatus.DIGITAL_TWIN_OK
    else:
        status = DigitalTwinStatus.DIGITAL_TWIN_PARTIAL

    # ---- A10: verification block recomputed from the exact consumed R11
    # evidence — never trusted from serialized claims, never hardcoded.
    failed_check_count = sum(
        1 for check in checks if check.get("state") == "FAIL")
    unavailable_check_count = sum(
        1 for check in checks if check.get("state") == "UNAVAILABLE")
    verification_block = {
        "status": r11_status,
        "r11SnapshotDigest": recorded_digest,
        "subjectR10SnapshotDigest": subject_snapshot_digest,
        "freezeAnchor": R11_FREEZE_ANCHOR,
        "failedCheckCount": failed_check_count,
        "unavailableCheckCount": unavailable_check_count,
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
        "comparabilityState": comparability,
        "verification": verification_block,
        "upstreamGaps": upstream_gaps,
        "twinGaps": [g.to_evidence_dict() for g in twin_gaps],
        "sourceDigests": dict(source_digests),
        "subjectR11Evidence": plain(r11_evidence),
        "boundaries": dict(R12_BOUNDARIES),
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
        comparability_state=comparability,
        verification=verification_block,
        upstream_gaps=tuple(upstream_gaps),
        twin_gaps=tuple(twin_gaps),
        source_digests=dict(source_digests),
        subject_r11_evidence=r11_evidence,
        boundaries=dict(R12_BOUNDARIES),
        freeze_anchor=R11_FREEZE_ANCHOR,
        freeze_tree=R11_FREEZE_TREE,
        synthetic=derived_synthetic,
        r12_snapshot_digest=digest,
    )
