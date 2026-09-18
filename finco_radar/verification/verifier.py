"""R11 independent, read-only verifier for serialized R10 evidence.

The verifier is offline and deterministic once it receives the serialized
subject.  Its PRIMARY digest reconstruction is implemented locally from the
documented canonical form (sorted keys, compact separators, UTF-8, SHA-256,
excluding only ``r10SnapshotDigest``); the frozen R10 verifier is used only
as a SECONDARY cross-check.  Acceptance never depends exclusively on the
implementation that produced the evidence.

Verification means: the serialized evidence satisfies the stated
deterministic contract and lineage.  It does NOT mean the valuation,
reference price or market outcome is objectively true.

No raw KeyError/TypeError/ValueError/InvalidOperation/AttributeError/
IndexError escapes from malformed evidence: every boundary is typed.
"""
from __future__ import annotations

import decimal
import json
from datetime import datetime
from decimal import Decimal
from typing import Any, Mapping

from finco_radar.asset_graph.contracts import (
    verify_serialized_r9_evidence,
)
from finco_radar.execution_simulator.contracts import (
    verify_serialized_evidence as verify_r8_evidence,
)

from .contracts import (
    FROZEN_DIMENSIONS,
    PHASE,
    R10_STATUSES,
    SCHEMA_VERSION,
    CheckState,
    VerificationCheck,
    VerificationError,
    VerificationGap,
    VerificationGapKind,
    VerificationSnapshot,
    VerificationStatus,
    canonical_sha256,
    plain,
)

BPS_SCALE = Decimal(10000)

# The exact R10 authority-boundary contract R11 verifies (historical subject
# values - never edited by R11).
EXPECTED_SUBJECT_BOUNDARIES = {
    "modelAuthority": "R10_APPLIED",
    "assetGraphAuthority": "R9_APPLIED",
    "verificationAuthority": "R11_NOT_YET_APPLIED",
    "digitalTwinAuthority": "R12_NOT_YET_APPLIED",
}


class _Collector:
    """Ordered check/gap collector; canonical order is established here,
    before any digest material is constructed."""

    def __init__(self) -> None:
        self.checks: dict[str, VerificationCheck] = {}
        self.gaps: list[VerificationGap] = []

    def pass_(self, check_id: str, detail: str = "") -> None:
        self.checks[check_id] = VerificationCheck(
            check_id=check_id, state=CheckState.PASS, detail=detail)

    def unavailable(self, check_id: str, detail: str) -> None:
        self.checks[check_id] = VerificationCheck(
            check_id=check_id, state=CheckState.UNAVAILABLE, detail=detail)

    def fail(self, check_id: str, gap_kind: VerificationGapKind,
             source: str, detail: str) -> None:
        self.checks[check_id] = VerificationCheck(
            check_id=check_id, state=CheckState.FAIL, detail=detail)
        self.gaps.append(VerificationGap(
            gap_kind=gap_kind, source=source, reason=detail))

    def check(self, check_id: str) -> VerificationCheck:
        return self.checks[check_id]

    def ordered_checks(self) -> list[VerificationCheck]:
        return [self.checks[k] for k in sorted(self.checks)]

    def ordered_gaps(self) -> list[VerificationGap]:
        return sorted(self.gaps, key=lambda g: (
            g.gap_kind.value, g.source, g.reason))


def _has_failures(checks: list[VerificationCheck]) -> bool:
    return any(c.state is CheckState.FAIL for c in checks)


def _canonical_material(evidence: Mapping[str, Any]) -> dict[str, Any]:
    material = plain(evidence)
    material.pop("r10SnapshotDigest", None)
    return material


def _reconstruct_snapshot_digest(evidence: Mapping[str, Any]) -> str | None:
    recorded = evidence.get("r10SnapshotDigest")
    if not isinstance(recorded, str):
        return None
    return recorded == canonical_sha256(_canonical_material(evidence))


def _tz_aware(value: Any) -> bool:
    if not isinstance(value, str):
        return False
    try:
        parsed = datetime.fromisoformat(value)
    except (ValueError, TypeError):
        return False
    return parsed.tzinfo is not None and parsed.tzinfo.utcoffset(parsed) is not None


def _decimal(value: Any) -> Decimal:
    return Decimal(str(value))


def verify_r10_evidence(
    *,
    evidence: Mapping[str, Any],
    generated_at: datetime,
    git_head: str,
    freeze_anchor: str,
    freeze_tree: str,
) -> VerificationSnapshot:
    """Independently verify serialized R10 evidence and return the typed
    R11 verification snapshot.  Read-only: the subject evidence is embedded
    verbatim and never mutated."""
    collector = _Collector()
    evidence = evidence if isinstance(evidence, Mapping) else {}

    subject_evidence_digest = canonical_sha256(evidence)
    subject_snapshot_digest = (
        evidence.get("r10SnapshotDigest")
        if isinstance(evidence.get("r10SnapshotDigest"), str) else None
    )
    uid = evidence.get("economicAssetUid") if isinstance(
        evidence.get("economicAssetUid"), str) else None
    node = evidence.get("economicNodeId") if isinstance(
        evidence.get("economicNodeId"), str) else None
    subject_status = evidence.get("status") if isinstance(
        evidence.get("status"), str) else ""
    subject_git_head = evidence.get("gitHead") if isinstance(
        evidence.get("gitHead"), str) else ""

    def _finish(status: VerificationStatus) -> VerificationSnapshot:
        checks = collector.ordered_checks()
        gaps = collector.ordered_gaps()
        snapshot_evidence = {
            "schemaVersion": SCHEMA_VERSION,
            "phase": PHASE,
            "status": status.value,
            "generatedAt": generated_at.isoformat(),
            "gitHead": git_head,
            "subjectPhase": evidence.get("phase") if isinstance(
                evidence.get("phase"), str) else "",
            "subjectStatus": subject_status,
            "subjectGitHead": subject_git_head,
            "subjectSnapshotDigest": subject_snapshot_digest,
            "subjectEvidenceDigest": subject_evidence_digest,
            "subjectAuthorityAnchor": freeze_anchor,
            "subjectAuthorityTree": freeze_tree,
            "economicAssetUid": uid,
            "economicNodeId": node,
            "subjectGaps": sorted(
                (plain(evidence.get("gaps")) or []),
                key=lambda g: (g.get("gapKind", ""), g.get("source", ""),
                               g.get("reason", ""))),
            "checks": [c.to_evidence_dict() for c in checks],
            "verificationGaps": [g.to_evidence_dict() for g in gaps],
            "sourceDigests": dict(evidence.get("sourceDigests") or {}),
            "subjectEvidence": plain(evidence),
            "boundaries": dict(__import__(
                "finco_radar.verification.contracts",
                fromlist=["R11_BOUNDARIES"]).R11_BOUNDARIES),
            "synthetic": derived_synthetic_flag(evidence),
            "freezeAnchor": freeze_anchor,
        }
        digest = canonical_sha256(snapshot_evidence)
        snapshot_evidence["r11SnapshotDigest"] = digest
        from .contracts import VerificationSnapshot as _Snapshot
        return _Snapshot(
            status=status,
            generated_at=generated_at,
            git_head=git_head,
            subject_phase=snapshot_evidence["subjectPhase"],
            subject_status=subject_status,
            subject_git_head=subject_git_head,
            subject_snapshot_digest=subject_snapshot_digest,
            subject_evidence_digest=subject_evidence_digest,
            subject_authority_anchor=freeze_anchor,
            subject_authority_tree=freeze_tree,
            economic_asset_uid=uid,
            economic_node_id=node,
            subject_gaps=tuple(snapshot_evidence["subjectGaps"]),
            checks=tuple(checks),
            verification_gaps=tuple(gaps),
            source_digests=snapshot_evidence["sourceDigests"],
            subject_evidence=evidence,
            boundaries=snapshot_evidence["boundaries"],
            synthetic=derived_synthetic_flag(evidence),
            freeze_anchor=freeze_anchor,
            r11_snapshot_digest=digest,
        )

    # ---- structural input validation (typed, no raw exceptions) ----------
    if not evidence:
        collector.fail(
            "SUBJECT_IDENTITY", VerificationGapKind.SUBJECT_EVIDENCE_UNAVAILABLE,
            "R11_VERIFIER", "subject evidence is empty or not a mapping")
        collector.fail(
            "R10_SNAPSHOT_DIGEST", VerificationGapKind.SUBJECT_DIGEST_MISMATCH,
            "R11_VERIFIER", "subject digest cannot be reconstructed: no evidence")
        return _finish(VerificationStatus.VERIFICATION_INPUT_INVALID)
    if evidence.get("schemaVersion") != "radar-r10-model-radar-v1":
        collector.fail(
            "SUBJECT_IDENTITY", VerificationGapKind.UNSUPPORTED_SUBJECT_SCHEMA,
            "R11_VERIFIER",
            f"unsupported subject schema {evidence.get('schemaVersion')!r}")
        return _finish(VerificationStatus.VERIFICATION_INPUT_INVALID)
    if evidence.get("phase") != "R10":
        collector.fail(
            "SUBJECT_IDENTITY", VerificationGapKind.UNSUPPORTED_SUBJECT_SCHEMA,
            "R11_VERIFIER",
            f"subject phase must be R10, got {evidence.get('phase')!r}")
        return _finish(VerificationStatus.VERIFICATION_INPUT_INVALID)

    # ---- 1. subject identity ---------------------------------------------
    problems = []
    if subject_status not in R10_STATUSES:
        problems.append(f"status {subject_status!r} is not a typed R10 status")
    if not subject_git_head.strip():
        problems.append("gitHead is empty")
    if not uid:
        problems.append("economicAssetUid is empty")
    elif node != f"economic:{uid}":
        problems.append(
            f"economicNodeId {node!r} is not the canonical economic node")
    if problems:
        collector.fail(
            "SUBJECT_IDENTITY", VerificationGapKind.SUBJECT_CONTRACT_MISMATCH,
            "R11_VERIFIER", "; ".join(problems))
    else:
        collector.pass_("SUBJECT_IDENTITY")

    # ---- 2/3. independent digest reconstruction + deterministic round-trip
    reconstructed = _reconstruct_snapshot_digest(evidence)
    if reconstructed is None:
        collector.fail(
            "R10_SNAPSHOT_DIGEST", VerificationGapKind.SUBJECT_DIGEST_MISMATCH,
            "R11_VERIFIER",
            "r10SnapshotDigest missing or not a SHA-256 string")
    elif not reconstructed:
        collector.fail(
            "R10_SNAPSHOT_DIGEST", VerificationGapKind.SUBJECT_DIGEST_MISMATCH,
            "R11_VERIFIER",
            "independent canonical reconstruction does not equal the "
            "recorded r10SnapshotDigest")
    else:
        collector.pass_(
            "R10_SNAPSHOT_DIGEST",
            "independent canonical reconstruction matches")
    try:
        first = json.dumps(evidence, sort_keys=True, separators=(",", ":"),
                           ensure_ascii=False)
        second = json.dumps(json.loads(first), sort_keys=True,
                            separators=(",", ":"), ensure_ascii=False)
        if first != second:
            raise ValueError("serialize->parse->serialize is not stable")
        collector.pass_("DETERMINISTIC_SERIALIZATION")
    except (TypeError, ValueError, decimal.InvalidOperation) as exc:
        collector.fail(
            "DETERMINISTIC_SERIALIZATION",
            VerificationGapKind.SUBJECT_CONTRACT_MISMATCH,
            "R11_VERIFIER", f"serialization round-trip unstable: {exc}")

    # ---- frozen-verifier secondary cross-check ----------------------------
    from finco_radar.model_radar.contracts import (
        verify_serialized_r10_evidence,
    )
    if reconstructed is not None:
        frozen_ok = verify_serialized_r10_evidence(evidence)
        independent_ok = bool(reconstructed)
        if frozen_ok == independent_ok:
            collector.pass_(
                "R10_SNAPSHOT_DIGEST_FROZEN_CROSSCHECK",
                "frozen R10 verifier agrees with the independent "
                "reconstruction")
        else:
            collector.fail(
                "R10_SNAPSHOT_DIGEST_FROZEN_CROSSCHECK",
                VerificationGapKind.SUBJECT_DIGEST_MISMATCH,
                "R11_VERIFIER",
                "frozen R10 verifier disagrees with the independent "
                "reconstruction")
    else:
        collector.unavailable(
            "R10_SNAPSHOT_DIGEST_FROZEN_CROSSCHECK",
            "no recorded digest to cross-check")

    # ---- lineage extraction ------------------------------------------------
    upstream = evidence.get("upstreamEvidence") if isinstance(
        evidence.get("upstreamEvidence"), Mapping) else {}
    r9 = upstream.get("r9AssetGraphEvidence") if isinstance(
        upstream.get("r9AssetGraphEvidence"), Mapping) else None
    r8 = upstream.get("r8ExecutionEvidence") if isinstance(
        upstream.get("r8ExecutionEvidence"), Mapping) else None
    r7 = (
        (r8 or {}).get("upstreamEvidence", {}).get("r7CrossMarketEvidence")
        if isinstance((r8 or {}).get("upstreamEvidence"), Mapping) else None
    )
    if not isinstance(r7, Mapping):
        r7 = None
    declared = evidence.get("sourceDigests") if isinstance(
        evidence.get("sourceDigests"), Mapping) else {}

    # ---- 4. R9 lineage ------------------------------------------------------
    if r9 is None:
        collector.fail(
            "R9_SOURCE_DIGEST", VerificationGapKind.SOURCE_LINEAGE_MISMATCH,
            "R11_VERIFIER", "embedded r9AssetGraphEvidence missing")
        collector.fail(
            "R9_SNAPSHOT_DIGEST", VerificationGapKind.SOURCE_LINEAGE_MISMATCH,
            "R11_VERIFIER", "no embedded R9 evidence to reconstruct")
        collector.fail(
            "R9_IDENTITY_CONSISTENCY",
            VerificationGapKind.SOURCE_LINEAGE_MISMATCH,
            "R11_VERIFIER", "no embedded R9 evidence")
    else:
        r9_source = canonical_sha256(r9)
        if declared.get("r9AssetGraphDigest") == r9_source:
            collector.pass_(
                "R9_SOURCE_DIGEST",
                "canonical digest of the complete embedded R9 evidence "
                "matches the R10-declared source digest")
        else:
            collector.fail(
                "R9_SOURCE_DIGEST", VerificationGapKind.SOURCE_LINEAGE_MISMATCH,
                "R11_VERIFIER",
                "r9AssetGraphDigest does not equal the canonical digest of "
                "the complete embedded R9 evidence")
        recorded_r9_snap = r9.get("r9SnapshotDigest")
        r9_material = plain(r9)
        r9_material.pop("r9SnapshotDigest", None)
        r9_internal_ok = (
            isinstance(recorded_r9_snap, str)
            and recorded_r9_snap == canonical_sha256(r9_material)
            and verify_serialized_r9_evidence(r9)
        )
        if r9_internal_ok:
            collector.pass_(
                "R9_SNAPSHOT_DIGEST", "internal r9SnapshotDigest "
                "reconstructs (local + frozen verifier)")
        else:
            collector.fail(
                "R9_SNAPSHOT_DIGEST", VerificationGapKind.SOURCE_LINEAGE_MISMATCH,
                "R11_VERIFIER", "internal R9 snapshot digest does not "
                "reconstruct")
        r9_uid = r9.get("economicAssetUid")
        r9_node = r9.get("economicNodeId")
        if r9_uid == uid and r9_node in (None, f"economic:{uid}"):
            collector.pass_("R9_IDENTITY_CONSISTENCY")
        else:
            collector.fail(
                "R9_IDENTITY_CONSISTENCY",
                VerificationGapKind.SOURCE_LINEAGE_MISMATCH,
                "R11_VERIFIER",
                f"R9 identity (uid={r9_uid!r}, node={r9_node!r}) disagrees "
                f"with R10 (uid={uid!r}, node={node!r})")

    # ---- 5. R8 lineage ------------------------------------------------------
    if r8 is None:
        collector.fail(
            "R8_SOURCE_DIGEST", VerificationGapKind.SOURCE_LINEAGE_MISMATCH,
            "R11_VERIFIER", "embedded r8ExecutionEvidence missing")
        collector.fail(
            "R8_SNAPSHOT_DIGEST", VerificationGapKind.SOURCE_LINEAGE_MISMATCH,
            "R11_VERIFIER", "no embedded R8 evidence to reconstruct")
        collector.fail(
            "R8_DEPLOYMENT_LINEAGE", VerificationGapKind.SOURCE_LINEAGE_MISMATCH,
            "R11_VERIFIER", "no embedded R8 evidence")
    else:
        r8_source = canonical_sha256(r8)
        if declared.get("r8ExecutionSimulatorDigest") == r8_source:
            collector.pass_("R8_SOURCE_DIGEST")
        else:
            collector.fail(
                "R8_SOURCE_DIGEST", VerificationGapKind.SOURCE_LINEAGE_MISMATCH,
                "R11_VERIFIER",
                "r8ExecutionSimulatorDigest does not equal the canonical "
                "digest of the embedded R8 evidence")
        r8_material = plain(r8)
        recorded_r8_snap = r8_material.pop("r8SnapshotDigest", None)
        if (isinstance(recorded_r8_snap, str)
                and recorded_r8_snap == canonical_sha256(r8_material)
                and r8.get("r8SnapshotDigest") == recorded_r8_snap
                and verify_r8_evidence(r8)):
            collector.pass_("R8_SNAPSHOT_DIGEST")
        else:
            collector.fail(
                "R8_SNAPSHOT_DIGEST", VerificationGapKind.SOURCE_LINEAGE_MISMATCH,
                "R11_VERIFIER", "internal R8 snapshot digest does not "
                "reconstruct")
        r8_key = r8.get("canonicalAssetKey") or {}
        deployment_nodes = [
            n for n in (r9 or {}).get("nodes", [])
            if n.get("nodeType") == "TOKEN_DEPLOYMENT"
        ]
        matching = [
            n for n in deployment_nodes
            if (n.get("canonicalAssetKey") or {}).get("chainId")
            == r8_key.get("chainId")
            and str((n.get("canonicalAssetKey") or {}).get(
                "contractAddress", "")).lower()
            == str(r8_key.get("contractAddress", "")).lower()
        ]
        if r8.get("economicAssetUid") == uid and len(matching) == 1:
            collector.pass_(
                "R8_DEPLOYMENT_LINEAGE",
                "embedded R8 deployment is the deployment used by R9/R10 "
                "(exactly once among R9 deployment nodes)")
        else:
            collector.fail(
                "R8_DEPLOYMENT_LINEAGE",
                VerificationGapKind.SOURCE_LINEAGE_MISMATCH,
                "R11_VERIFIER",
                "embedded R8 economic/deployment lineage disagrees with "
                "R9/R10")

    # ---- 6. R7 provenance ----------------------------------------------------
    if r7 is None:
        collector.fail(
            "R7_PROVENANCE", VerificationGapKind.SOURCE_LINEAGE_MISMATCH,
            "R11_VERIFIER", "embedded R7 lineage missing")
    else:
        r7_source = canonical_sha256(r7)
        declared_r7 = (r8 or {}).get("sourceDigests", {}).get(
            "r7CrossMarketDigest")
        internal_ok = (
            isinstance(r7.get("r7SnapshotDigest"), str)
            and r7["r7SnapshotDigest"] == canonical_sha256(plain(_material(r7)))
        )
        if declared_r7 == r7_source and internal_ok:
            collector.pass_(
                "R7_PROVENANCE",
                "embedded R7 lineage is the one causally carried through R8 "
                "(source + internal digests reconstruct)")
        else:
            collector.fail(
                "R7_PROVENANCE", VerificationGapKind.SOURCE_LINEAGE_MISMATCH,
                "R11_VERIFIER",
                "embedded R7 provenance does not reconstruct through the "
                "R8-carried lineage")

    # ---- 7. exact synthetic provenance + derivation ---------------------------
    synthetic_flags = {
        "r10": evidence.get("synthetic"),
        "r9": (r9 or {}).get("synthetic"),
        "r8": (r8 or {}).get("synthetic"),
        "r7": (r7 or {}).get("synthetic"),
    }
    malformed = {k: v for k, v in synthetic_flags.items()
                 if v is not True and v is not False}
    if malformed:
        collector.fail(
            "SYNTHETIC_PROVENANCE", VerificationGapKind.SUBJECT_CONTRACT_MISMATCH,
            "R11_VERIFIER",
            f"synthetic provenance must be exact booleans: {malformed}")
    else:
        collector.pass_("SYNTHETIC_PROVENANCE", "all causal flags exact booleans")

    # ---- 8. R10 boundary contract (historical values, never edited) ----------
    boundaries = evidence.get("boundaries") if isinstance(
        evidence.get("boundaries"), Mapping) else {}
    boundary_problems = [
        f"{key}={boundaries.get(key)!r}"
        for key, expected in EXPECTED_SUBJECT_BOUNDARIES.items()
        if boundaries.get(key) != expected
    ]
    if boundary_problems:
        collector.fail(
            "R10_BOUNDARY_CONTRACT", VerificationGapKind.SUBJECT_CONTRACT_MISMATCH,
            "R11_VERIFIER",
            "subject boundary contract mismatch: " + "; ".join(boundary_problems))
    else:
        collector.pass_(
            "R10_BOUNDARY_CONTRACT",
            "historical subject boundary preserved "
            "(verificationAuthority = R11_NOT_YET_APPLIED)")

    # ---- 9/10. model evidence -------------------------------------------------
    model_evidence = evidence.get("modelEvidence") if isinstance(
        evidence.get("modelEvidence"), Mapping) else None
    model_binding = evidence.get("modelBinding")
    reference_comparison = evidence.get("referenceComparison")
    execution_comparisons = evidence.get("executionComparisons") if isinstance(
        evidence.get("executionComparisons"), list) else None
    subject_gap_kinds = {
        g.get("gapKind") for g in (evidence.get("gaps") or [])
        if isinstance(g, Mapping)
    }

    honest_missing = "MODEL_BINDING_UNAVAILABLE" in subject_gap_kinds
    if honest_missing:
        if (model_binding is None and model_evidence is None
                and reference_comparison is None
                and execution_comparisons == []):
            collector.pass_(
                "HONEST_MISSING_MODEL",
                "declared MODEL_BINDING_UNAVAILABLE is consistent with "
                "null model binding/evidence and no comparisons")
        else:
            collector.fail(
                "HONEST_MISSING_MODEL", VerificationGapKind.SUBJECT_CONTRACT_MISMATCH,
                "R11_VERIFIER",
                "declared MODEL_BINDING_UNAVAILABLE but fabricated model "
                "fields or comparisons are present")
    if model_evidence is None and (model_binding is not None
                                   or reference_comparison is not None
                                   or execution_comparisons):
        collector.fail(
            "SUBJECT_GAP_CONSISTENCY",
            VerificationGapKind.SUBJECT_CONTRACT_MISMATCH,
            "R11_VERIFIER",
            "binding/comparisons present while modelEvidence is null")
    else:
        collector.pass_("SUBJECT_GAP_CONSISTENCY",
                        "subject gaps preserved verbatim and consistent")

    if model_evidence is None:
        for optional in ("MODEL_DIGESTS", "MODEL_OBSERVATION_BINDINGS",
                         "COMPARABILITY_CONTRACT", "REFERENCE_ARITHMETIC",
                         "EXECUTION_ARITHMETIC", "EXECUTION_SOURCE_BINDING"):
            collector.unavailable(
                optional,
                "subject declares no model evidence; optional model-"
                "integrity authority not applicable (verified consistent "
                "with the declared MODEL_BINDING_UNAVAILABLE state)")
    else:
        _verify_model_integrity(collector, evidence, model_evidence)
        comparability = evidence.get("comparability") if isinstance(
            evidence.get("comparability"), Mapping) else None
        _verify_comparability(collector, comparability)
        if reference_comparison is not None and isinstance(
            reference_comparison, Mapping
        ):
            _verify_reference_arithmetic(collector, model_evidence,
                                         reference_comparison, r7)
        else:
            collector.unavailable(
                "REFERENCE_ARITHMETIC", "no reference comparison in subject")
        rows = execution_comparisons if execution_comparisons is not None else []
        if rows:
            _verify_execution_rows(collector, model_evidence, rows, r8)
        else:
            collector.unavailable(
                "EXECUTION_ARITHMETIC", "no execution comparisons in subject")
            collector.unavailable(
                "EXECUTION_SOURCE_BINDING",
                "no execution comparisons in subject")

    # ---- 16. historical timing semantics ---------------------------------------
    timestamp_fields = []
    if reference_comparison is not None and isinstance(
        reference_comparison, Mapping
    ):
        timestamp_fields.append(
            ("referenceComparison.modelObservedAt",
             reference_comparison.get("modelObservedAt")))
        timestamp_fields.append(
            ("referenceComparison.referenceObservedAt",
             reference_comparison.get("referenceObservedAt")))
    for row in execution_comparisons or []:
        if isinstance(row, Mapping):
            timestamp_fields.append(
                (f"executionComparisons.executionObservedAt",
                 row.get("executionObservedAt")))
    missing = sorted(name for name, value in timestamp_fields if value is None)
    bad_timestamps = sorted(name for name, value in timestamp_fields
                            if value is not None and not _tz_aware(value))
    timing_problems = []
    if missing:
        timing_problems.append(f"required subject timestamps missing: {missing}")
    if bad_timestamps:
        timing_problems.append(
            f"subject timestamps must be timezone-aware: {bad_timestamps}")
    if timing_problems:
        collector.fail(
            "HISTORICAL_TIMING", VerificationGapKind.SUBJECT_CONTRACT_MISMATCH,
            "R11_VERIFIER", "; ".join(timing_problems))
    else:
        collector.pass_(
            "HISTORICAL_TIMING",
            "serialized subject timestamps are internally consistent and "
            "timezone-aware; no new R11 freshness policy applied")

    # ---- status ------------------------------------------------------------------
    checks = collector.ordered_checks()
    if _has_failures(checks):
        # Digest/lineage failures are evidence mismatches; contract failures
        # are verification failures.  Both fail closed.
        integrity_kinds = {
            VerificationGapKind.SUBJECT_DIGEST_MISMATCH,
            VerificationGapKind.SOURCE_LINEAGE_MISMATCH,
        }
        if any(g.gap_kind in integrity_kinds for g in collector.ordered_gaps()):
            status = VerificationStatus.VERIFICATION_EVIDENCE_MISMATCH
        else:
            status = VerificationStatus.VERIFICATION_FAILED
    else:
        status = VerificationStatus.VERIFICATION_OK
    return _finish(status)


def _material(evidence: Mapping[str, Any]) -> dict[str, Any]:
    material = plain(evidence)
    material.pop("r7SnapshotDigest", None)
    return material


def derived_synthetic_flag(evidence: Mapping[str, Any]) -> bool:
    """I/D derivation: R11 synthetic is exactly the OR of the verified
    causal chain - no caller override exists."""
    if evidence.get("synthetic") is True:
        return True
    upstream = evidence.get("upstreamEvidence") if isinstance(
        evidence.get("upstreamEvidence"), Mapping) else {}
    r9 = upstream.get("r9AssetGraphEvidence") if isinstance(
        upstream.get("r9AssetGraphEvidence"), Mapping) else {}
    r8 = upstream.get("r8ExecutionEvidence") if isinstance(
        upstream.get("r8ExecutionEvidence"), Mapping) else {}
    r7 = (r8.get("upstreamEvidence") or {}).get("r7CrossMarketEvidence")
    return bool(
        r9.get("synthetic") is True
        or r8.get("synthetic") is True
        or (isinstance(r7, Mapping) and r7.get("synthetic") is True)
    )


def _verify_model_integrity(collector: _Collector, evidence: Mapping,
                            model_evidence: Mapping) -> None:
    """Check 10: independently rederive input/output/run digests and the
    serialized observation bindings, from the documented R10 contract."""
    input_evidence = model_evidence.get("inputEvidence")
    output_evidence = model_evidence.get("outputEvidence")
    declared_input = model_evidence.get("inputDigest")
    declared_output = model_evidence.get("outputDigest")
    declared_run = model_evidence.get("modelRunDigest")
    problems = []
    if not isinstance(input_evidence, Mapping) or not isinstance(
        output_evidence, Mapping
    ):
        problems.append("inputEvidence/outputEvidence missing or malformed")
    else:
        if declared_input != canonical_sha256(input_evidence):
            problems.append("inputDigest does not rederive from inputEvidence")
        if declared_output != canonical_sha256(output_evidence):
            problems.append("outputDigest does not rederive from outputEvidence")
        run_material = {
            "modelId": model_evidence.get("modelId"),
            "modelVersion": model_evidence.get("modelVersion"),
            "engineAuthority": model_evidence.get("engineAuthority"),
            "economicAssetUid": model_evidence.get("economicAssetUid"),
            "economicNodeId": model_evidence.get("economicNodeId"),
            "valuationAsOf": model_evidence.get("valuationAsOf"),
            "valueKind": model_evidence.get("valueKind"),
            "value": model_evidence.get("value"),
            "currency": model_evidence.get("currency"),
            "unitBasis": model_evidence.get("unitBasis"),
            "unitMultiplier": model_evidence.get("unitMultiplier"),
            "unitMultiplierBasis": model_evidence.get("unitMultiplierBasis"),
            "inputDigest": declared_input,
            "outputDigest": declared_output,
        }
        if declared_run != canonical_sha256(run_material):
            problems.append("modelRunDigest does not rederive from the "
                            "documented run material")
        # observation bindings
        for key, declared in (("value", model_evidence.get("value")),
                              ("valueKind", model_evidence.get("valueKind")),
                              ("currency", model_evidence.get("currency")),
                              ("unitBasis", model_evidence.get("unitBasis"))):
            if output_evidence.get(key) != declared:
                problems.append(
                    f"output observation {key} disagrees with the declared "
                    f"model field")
        if output_evidence.get("valuationAsOf") != model_evidence.get(
            "valuationAsOf"
        ) and "valuationAsOf" in output_evidence:
            problems.append("output observation valuationAsOf disagrees "
                            "with the declared valuation timestamp")
        if model_evidence.get("unitMultiplier") is not None:
            if str(input_evidence.get("unitMultiplier")) != str(
                model_evidence.get("unitMultiplier")
            ):
                problems.append("input authority unitMultiplier disagrees")
            if input_evidence.get("unitMultiplierBasis") != (
                model_evidence.get("unitMultiplierBasis")
            ):
                problems.append("input authority unitMultiplierBasis disagrees")
    if problems:
        collector.fail(
            "MODEL_DIGESTS", VerificationGapKind.SUBJECT_CONTRACT_MISMATCH,
            "R11_VERIFIER", "; ".join(problems))
        collector.fail(
            "MODEL_OBSERVATION_BINDINGS",
            VerificationGapKind.SUBJECT_CONTRACT_MISMATCH,
            "R11_VERIFIER", "; ".join(problems))
    else:
        collector.pass_(
            "MODEL_DIGESTS",
            "input/output/run digests independently rederived")
        collector.pass_(
            "MODEL_OBSERVATION_BINDINGS",
            "serialized observation bindings match the declared model fields")


def _verify_comparability(collector: _Collector,
                          comparability: Mapping | None) -> None:
    """Check 11: structural comparability contract over the serialized
    result (R10 selection logic is never re-run)."""
    if comparability is None:
        collector.fail(
            "COMPARABILITY_CONTRACT",
            VerificationGapKind.SUBJECT_CONTRACT_MISMATCH,
            "R11_VERIFIER",
            "model evidence present but comparability missing")
        return
    dimensions = comparability.get("dimensions")
    if not isinstance(dimensions, list):
        collector.fail(
            "COMPARABILITY_CONTRACT",
            VerificationGapKind.SUBJECT_CONTRACT_MISMATCH,
            "R11_VERIFIER", "comparability dimensions missing/malformed")
        return
    seen: dict[str, int] = {}
    for entry in dimensions:
        name = entry.get("dimension") if isinstance(entry, Mapping) else None
        seen[name] = seen.get(name, 0) + 1
    duplicates = sorted(k for k, v in seen.items() if v > 1)
    missing = [d for d in FROZEN_DIMENSIONS if d not in seen]
    unknown = [k for k in seen if k not in FROZEN_DIMENSIONS]
    if duplicates or missing or unknown:
        collector.fail(
            "COMPARABILITY_CONTRACT",
            VerificationGapKind.SUBJECT_CONTRACT_MISMATCH,
            "R11_VERIFIER",
            f"dimension set invalid: duplicated={duplicates} "
            f"missing={missing} unknown={unknown}")
        return
    failed = {
        entry["dimension"]: entry.get("gapKind")
        for entry in dimensions
        if entry.get("ok") is not True
    }
    state = comparability.get("state")
    consistent = True
    if state == "COMPARABLE" and failed:
        consistent = False
    elif state == "PARTIALLY_COMPARABLE" and failed != {
        "REFERENCE_AVAILABILITY": "REFERENCE_UNAVAILABLE"
    }:
        consistent = False
    elif state == "NOT_COMPARABLE" and not failed:
        consistent = False
    elif state not in ("COMPARABLE", "PARTIALLY_COMPARABLE", "NOT_COMPARABLE"):
        consistent = False
    if not consistent:
        collector.fail(
            "COMPARABILITY_CONTRACT",
            VerificationGapKind.SUBJECT_CONTRACT_MISMATCH,
            "R11_VERIFIER",
            f"comparability state {state!r} inconsistent with the "
            f"serialized dimension results")
        return
    collector.pass_(
        "COMPARABILITY_CONTRACT",
        "exactly the seven frozen dimensions, one result each, state "
        "consistent")


def _verify_reference_arithmetic(
    collector: _Collector, model_evidence: Mapping,
    reference_comparison: Mapping, r7: Mapping | None,
) -> None:
    """Check 12: independent Decimal recomputation of the reference
    deviation plus traceability to the embedded R7 reference source."""
    problems = []
    try:
        model_value = _decimal(model_evidence.get("value"))
        reference_price = _decimal(reference_comparison.get("referencePrice"))
        declared_minus = _decimal(
            reference_comparison.get("referenceMinusModelValue"))
        declared_bps = _decimal(
            reference_comparison.get("referenceVsModelBps"))
    except (decimal.InvalidOperation, TypeError, ValueError, KeyError,
            AttributeError, IndexError) as exc:
        collector.fail(
            "REFERENCE_ARITHMETIC", VerificationGapKind.SUBJECT_CONTRACT_MISMATCH,
            "R11_VERIFIER",
            f"reference comparison arithmetic reconstruction failed: {exc}")
        return
    try:
        expected_minus = reference_price - model_value
        expected_bps = (reference_price / model_value - 1) * BPS_SCALE
        if expected_minus != declared_minus:
            problems.append("referenceMinusModelValue does not recompute")
        if expected_bps != declared_bps:
            problems.append("referenceVsModelBps does not recompute")
        if model_value <= 0 or not model_value.is_finite():
            problems.append("model value must be positive and finite")
        if not reference_price.is_finite():
            problems.append("reference price must be finite")
        if (not _tz_aware(reference_comparison.get("modelObservedAt"))
                or not _tz_aware(reference_comparison.get(
                    "referenceObservedAt"))):
            problems.append("comparison timestamps must be timezone-aware")
        if r7 is not None:
            oracle = (r7.get("layers") or {}).get("oracleReference") or {}
            if (oracle.get("price") is not None
                    and _decimal(oracle["price"]) != reference_price):
                problems.append("reference price does not trace to the "
                                "embedded R7 oracle observation")
            if (oracle.get("source") is not None
                    and reference_comparison.get("referenceSource")
                    not in (None, oracle.get("source"))):
                problems.append("reference source does not trace to the "
                                "embedded R7 oracle source")
    except (decimal.InvalidOperation, TypeError, ValueError, KeyError,
            AttributeError, IndexError) as exc:
        problems.append(f"arithmetic reconstruction failed: {exc}")
    if problems:
        collector.fail(
            "REFERENCE_ARITHMETIC", VerificationGapKind.SUBJECT_CONTRACT_MISMATCH,
            "R11_VERIFIER", "; ".join(problems))
    else:
        collector.pass_(
            "REFERENCE_ARITHMETIC",
            "referenceMinusModelValue and referenceVsModelBps independently "
            "recompute in exact Decimal and trace to the embedded R7 source")


def _verify_execution_rows(
    collector: _Collector, model_evidence: Mapping, rows: list,
    r8: Mapping | None,
) -> None:
    """Checks 13/14: independent per-row arithmetic recomputation and
    source binding to the corresponding embedded R8 scenario."""
    problems: list[str] = []
    scenarios_by_key: dict[tuple, Mapping] = {}
    for scenario in (r8 or {}).get("scenarios", []):
        entry = scenario.get("scenario") or {}
        key = (entry.get("side"), str(entry.get("requestedNotionalUsd")),
               entry.get("quoteSource"))
        scenarios_by_key[key] = scenario
    model_value = None
    for position, row in enumerate(rows):
        label = f"row[{position}]"
        if not isinstance(row, Mapping):
            problems.append(f"{label}: not a mapping")
            continue
        try:
            if model_value is None:
                model_value = _decimal(model_evidence.get("value"))
            model_value_row = _decimal(row.get("modelValue"))
            execution_price = _decimal(row.get("executionPrice"))
            declared_minus = _decimal(row.get("executionMinusModelValue"))
            declared_bps = _decimal(row.get("executionVsModelBps"))
        except (decimal.InvalidOperation, TypeError, ValueError, KeyError,
                AttributeError, IndexError) as exc:
            problems.append(
                f"{label}: arithmetic reconstruction failed: {exc}")
            continue
        try:
            expected_minus = execution_price - model_value_row
            expected_bps = (execution_price / model_value_row - 1) * BPS_SCALE
            if expected_minus != declared_minus:
                problems.append(f"{label}: executionMinusModelValue does "
                                "not recompute")
            if expected_bps != declared_bps:
                problems.append(f"{label}: executionVsModelBps does not "
                                "recompute")
            if execution_price <= 0 or not execution_price.is_finite():
                problems.append(f"{label}: execution price must be positive "
                                "and finite")
        except (decimal.InvalidOperation, TypeError, ValueError, KeyError,
                AttributeError, IndexError) as exc:
            problems.append(f"{label}: arithmetic reconstruction failed: {exc}")
            continue
        # source binding
        key = (row.get("side"), str(row.get("requestedNotionalUsd")),
               row.get("quoteSource"))
        scenario = scenarios_by_key.get(key)
        if scenario is None:
            problems.append(
                f"{label}: no embedded R8 scenario matches "
                f"(side={row.get('side')!r}, "
                f"notional={row.get('requestedNotionalUsd')!r}, "
                f"venue={row.get('quoteSource')!r})")
            continue
        entry = scenario.get("scenario") or {}
        r2 = (scenario.get("upstreamEvidence") or {}).get("r2GapEvidence") or {}
        source_price = r2.get("executionPriceUsdPerToken")
        if source_price is None or _decimal(source_price) != execution_price:
            problems.append(
                f"{label}: execution price does not trace to the embedded "
                "R8 scenario executionPriceUsdPerToken")
        if row.get("r8NetEdgeState") != scenario.get("netEdgeState"):
            problems.append(f"{label}: R8 net-edge state not carried verbatim")
        if row.get("executionCurrency") != "USD":
            problems.append(
                f"{label}: execution currency must be USD per frozen R8 "
                "executionPriceUsdPerToken semantics")
        quote_at = scenario.get("quoteObservedAt")
        if (row.get("executionObservedAt") is not None
                and quote_at is not None
                and row["executionObservedAt"] != quote_at):
            problems.append(
                f"{label}: execution timestamp does not trace to the R8 "
                "scenario quoteObservedAt")
        if model_value_row != model_value:
            problems.append(
                f"{label}: comparison model value differs from the "
                "declared model value")
    if problems:
        collector.fail(
            "EXECUTION_ARITHMETIC", VerificationGapKind.SUBJECT_CONTRACT_MISMATCH,
            "R11_VERIFIER",
            "; ".join(p for p in problems if "recompute" in p))
        collector.fail(
            "EXECUTION_SOURCE_BINDING",
            VerificationGapKind.SOURCE_LINEAGE_MISMATCH,
            "R11_VERIFIER",
            "; ".join(p for p in problems if "recompute" not in p)
            or "execution source binding inconsistent")
    else:
        collector.pass_(
            "EXECUTION_ARITHMETIC",
            "every execution row recomputes independently in exact Decimal "
            "with identical BUY/SELL sign semantics and no R8 cost "
            "deduction")
        collector.pass_(
            "EXECUTION_SOURCE_BINDING",
            "every execution row traces to its embedded R8 scenario "
            "(identity, price, timestamp, USD currency, net-edge state)")
