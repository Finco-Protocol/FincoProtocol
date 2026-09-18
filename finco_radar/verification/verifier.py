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
    R10_FREEZE_ANCHOR,
    R10_FREEZE_TREE,
    R10_GAP_KINDS,
    R10_PER_UNIT_BASES,
    R10_STATUSES,
    R10_TOTAL_BASES,
    R10_UNIT_BASES,
    R10_VALUE_KINDS,
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

# Frozen typed R10 ModelEngineAuthority vocabulary (mirrored read-only from
# the frozen R10 contract for serialized verification).
FROZEN_ENGINE_AUTHORITIES = {
    "finco_core.sponsor.xnpv",
    "finco_core.sponsor.xirr",
    "financial_engine.orchestrator",
}


def _decimal_seconds(delta):
    micros = (Decimal(delta.days) * Decimal(86400) * Decimal(10 ** 6)
              + Decimal(delta.seconds) * Decimal(10 ** 6)
              + Decimal(delta.microseconds))
    return micros / Decimal(10 ** 6)


class _ShapeError(Exception):
    """Internal typed shape failure; converted to a typed R11 status by the
    verifier boundary - never allowed to escape raw."""


def _required_mapping(container: Any, name: str) -> Mapping:
    """C1: required mapping - absent/null/wrong-type are all typed errors."""
    if not isinstance(container, Mapping):
        raise _ShapeError(f"{name} must be a mapping, got {type(container).__name__}")
    return container


def _optional_mapping(value: Any, name: str) -> "Mapping | None":
    """C1: optional mapping - present null and wrong-type are typed errors;
    only genuine absence returns None."""
    if value is None:
        return None
    if not isinstance(value, Mapping):
        raise _ShapeError(f"{name} must be a mapping or absent, got {type(value).__name__}")
    return value


def _optional_sequence(value: Any, name: str) -> "list | None":
    """C1: optional sequence - present null and wrong-type are typed errors."""
    if value is None:
        return None
    if not isinstance(value, list):
        raise _ShapeError(f"{name} must be a list or absent, got {type(value).__name__}")
    return value


def _safe_str(value: Any, name: str) -> str:
    """C1: typed scalar extraction - non-string is a typed error."""
    if not isinstance(value, str):
        raise _ShapeError(f"{name} must be a string, got {type(value).__name__}")
    return value


def _total_derived_synthetic(evidence: Any) -> bool:
    """C1: total derived synthetic flag - never throws on malformed input.
    Consumes only pre-validated causal structures; defensively inspects
    types without calling methods on unvalidated values."""
    if not isinstance(evidence, Mapping):
        return False
    if evidence.get("synthetic") is True:
        return True
    upstream = evidence.get("upstreamEvidence")
    if not isinstance(upstream, Mapping):
        return False
    r9 = upstream.get("r9AssetGraphEvidence")
    if isinstance(r9, Mapping) and r9.get("synthetic") is True:
        return True
    r8 = upstream.get("r8ExecutionEvidence")
    if not isinstance(r8, Mapping):
        return False
    if r8.get("synthetic") is True:
        return True
    r8_upstream = r8.get("upstreamEvidence")
    if isinstance(r8_upstream, Mapping):
        r7 = r8_upstream.get("r7CrossMarketEvidence")
        if isinstance(r7, Mapping) and r7.get("synthetic") is True:
            return True
    return False


def _mapping_or_fail(value: Any, name: str) -> Mapping:
    if not isinstance(value, Mapping):
        raise _ShapeError(f"{name} must be a mapping, got {type(value).__name__}")
    return value


def _sequence_or_fail(value: Any, name: str) -> list:
    if not isinstance(value, list):
        raise _ShapeError(f"{name} must be a list, got {type(value).__name__}")
    return list(value)

# The exact R10 authority-boundary contract R11 verifies (historical subject
# values - never edited by R11).
EXPECTED_SUBJECT_BOUNDARIES = {
    "modelAuthority": "R10_APPLIED",
    "assetGraphAuthority": "R9_APPLIED",
    "verificationAuthority": "R11_NOT_YET_APPLIED",
    "digitalTwinAuthority": "R12_NOT_YET_APPLIED",
}


def __decimal_seconds(delta):
    micros = (Decimal(delta.days) * Decimal(86400) * Decimal(10 ** 6)
              + Decimal(delta.seconds) * Decimal(10 ** 6)
              + Decimal(delta.microseconds))
    return micros / Decimal(10 ** 6)


def _r11_boundaries():
    from .contracts import R11_BOUNDARIES
    return dict(R11_BOUNDARIES)


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


def _decimal(value: Any, field_name: str = "value") -> Decimal:
    """B2: the single canonical typed numeric parser for every serialized
    value consumed by R11.  Malformed source values ("abc", None, wrong
    types) and non-finite results (NaN / Infinity) raise _ShapeError, which
    the check-level typed handling converts to R11 failures - a raw
    decimal.InvalidOperation / DivisionByZero never escapes."""
    if isinstance(value, bool) or value is None:
        raise _ShapeError(f"{field_name} is not a number: {value!r}")
    if isinstance(value, Decimal):
        if not value.is_finite():
            raise _ShapeError(f"{field_name} must be finite: {value!r}")
        return value
    if isinstance(value, (int, str)):
        try:
            converted = Decimal(value)
        except (decimal.InvalidOperation, ValueError, TypeError) as exc:
            raise _ShapeError(
                f"{field_name} is not a parsable number: {value!r}") from exc
        if not converted.is_finite():
            raise _ShapeError(
                f"{field_name} must be finite (NaN/Infinity rejected)")
        return converted
    if isinstance(value, float):
        if value != value or value in (float("inf"), float("-inf")):
            raise _ShapeError(f"{field_name} must be finite: {value!r}")
        return Decimal(repr(value))
    raise _ShapeError(
        f"{field_name} has unsupported type {type(value).__name__}")


def _mapping_field(container: Mapping, key: str, name: str) -> Mapping:
    value = container.get(key)
    if value is not None and not isinstance(value, Mapping):
        raise _ShapeError(f"{name} must be a mapping")
    return value


def verify_r10_evidence(
    *,
    evidence: Mapping[str, Any],
    generated_at: datetime,
    git_head: str,
    freeze_anchor: str,
    freeze_tree: str,
    content_envelope: Mapping[str, Any] | None = None,
) -> VerificationSnapshot:
    """Independently verify serialized R10 evidence and return the typed
    R11 verification snapshot.  Read-only: the subject evidence is embedded
    verbatim and never mutated.

    A1: ``freeze_anchor``/``freeze_tree`` are CALLER CLAIMS.  R11
    independently knows the canonical R0-R10 freeze authority through the
    pinned contract constants; the FREEZE_IDENTITY check requires exact
    equality, and a mismatch prevents VERIFICATION_OK.  The R11 evidence
    records the verified canonical values, never caller metadata."""
    collector = _Collector()
    if freeze_anchor != R10_FREEZE_ANCHOR or freeze_tree != R10_FREEZE_TREE:
        collector.fail(
            "FREEZE_IDENTITY", VerificationGapKind.FREEZE_IDENTITY_MISMATCH,
            "R11_VERIFIER",
            f"claimed freeze authority (anchor={freeze_anchor!r}, "
            f"tree={freeze_tree!r}) does not equal the pinned R0-R10 "
            "freeze constants")
    else:
        collector.pass_(
            "FREEZE_IDENTITY",
            "claimed freeze authority matches the pinned R0-R10 freeze "
            "constants")
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
            "subjectAuthorityAnchor": R10_FREEZE_ANCHOR,
            "subjectAuthorityTree": R10_FREEZE_TREE,
            "economicAssetUid": uid,
            "economicNodeId": node,
            "subjectGaps": sorted(
                [plain(g) for g in (
                    evidence.get("gaps") if isinstance(
                        evidence.get("gaps"), list) else [])
                 if isinstance(g, Mapping)],
                key=lambda g: (str(g.get("gapKind") or ""),
                               str(g.get("source") or ""),
                               str(g.get("reason") or ""))) if any(
                    isinstance(g, Mapping) for g in (
                        evidence.get("gaps") or []
                        if isinstance(evidence.get("gaps"), list) else [])) else [],
            "checks": [c.to_evidence_dict() for c in checks],
            "verificationGaps": [g.to_evidence_dict() for g in gaps],
            "sourceDigests": (
                dict(evidence["sourceDigests"]) if isinstance(
                    evidence.get("sourceDigests"), Mapping) else {}),
            "subjectEvidence": plain(evidence),
            "boundaries": dict(_r11_boundaries()),
            "synthetic": _total_derived_synthetic(evidence),
            "freezeAnchor": R10_FREEZE_ANCHOR,
            "contentEnvelope": plain(content_envelope) if content_envelope is not None else None,
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
            subject_authority_anchor=R10_FREEZE_ANCHOR,
            subject_authority_tree=R10_FREEZE_TREE,
            economic_asset_uid=uid,
            economic_node_id=node,
            subject_gaps=tuple(snapshot_evidence["subjectGaps"]),
            checks=tuple(checks),
            verification_gaps=tuple(gaps),
            source_digests=snapshot_evidence["sourceDigests"],
            subject_evidence=evidence,
            boundaries=snapshot_evidence["boundaries"],
            synthetic=_total_derived_synthetic(evidence),
            freeze_anchor=R10_FREEZE_ANCHOR,
            content_envelope=content_envelope,
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

    # ---- A3: strict nested-shape validation (typed, before any use) -------
    def _mapping_field(container, key, name):
        value = container.get(key)
        if value is not None and not isinstance(value, Mapping):
            raise _ShapeError(f"{name} must be a mapping, got {type(value).__name__}")
        return value

    def _sequence_field(container, key, name):
        value = container.get(key)
        if value is not None and not isinstance(value, list):
            raise _ShapeError(f"{name} must be a list, got {type(value).__name__}")
        return value if value is not None else []

    try:
        _sequence_or_fail(evidence.get("gaps"), "gaps")
        for gap in (evidence.get("gaps") or []):
            _mapping_or_fail(gap, "gaps item")
            for key in ("gapKind", "source", "reason"):
                if key not in gap:
                    raise _ShapeError(f"gaps item missing {key!r}")
        _mapping_field(evidence, "sourceDigests", "sourceDigests")
        upstream_shape = _mapping_field(evidence, "upstreamEvidence",
                                        "upstreamEvidence")
        if upstream_shape is None:
            upstream_shape = {}
        r9_shape = _mapping_field(upstream_shape, "r9AssetGraphEvidence",
                                  "r9AssetGraphEvidence")
        if r9_shape is not None:
            _sequence_field(r9_shape, "nodes", "R9 nodes")
            for node_item in r9_shape.get("nodes") or []:
                _mapping_or_fail(node_item, "R9 node")
        r8_shape = _mapping_field(upstream_shape, "r8ExecutionEvidence",
                                  "r8ExecutionEvidence")
        if r8_shape is not None:
            _mapping_field(r8_shape, "sourceDigests", "R8 sourceDigests")
            _sequence_field(r8_shape, "scenarios", "R8 scenarios")
            for scenario in r8_shape.get("scenarios") or []:
                _mapping_or_fail(scenario, "R8 scenario")
                _mapping_or_fail(scenario.get("scenario") or {},
                                 "R8 scenario entry")
            r8_upstream = _mapping_field(r8_shape, "upstreamEvidence",
                                         "R8 upstreamEvidence")
            if r8_upstream is not None:
                _mapping_field(r8_upstream, "r7CrossMarketEvidence",
                               "r7CrossMarketEvidence")
    except _ShapeError as exc:
        collector.fail(
            "SUBJECT_IDENTITY", VerificationGapKind.SUBJECT_CONTRACT_MISMATCH,
            "R11_VERIFIER", f"malformed nested evidence shape: {exc}")
        return _finish(VerificationStatus.VERIFICATION_INPUT_INVALID)

    # ---- C2: subject generatedAt must be valid and tz-aware ----------------
    raw_generated = evidence.get("generatedAt")
    generated_at_problems = []
    if not isinstance(raw_generated, str) or not raw_generated.strip():
        generated_at_problems.append(
            f"subject generatedAt must be a non-empty string, got {raw_generated!r}")
    else:
        try:
            gen_parsed = datetime.fromisoformat(raw_generated)
        except (ValueError, TypeError):
            gen_parsed = None
        if gen_parsed is None:
            generated_at_problems.append(
                f"subject generatedAt is not a parsable ISO timestamp: {raw_generated!r}")
        elif gen_parsed.tzinfo is None or gen_parsed.tzinfo.utcoffset(gen_parsed) is None:
            generated_at_problems.append(
                "subject generatedAt must be timezone-aware")
    if generated_at_problems:
        collector.fail(
            "SUBJECT_IDENTITY", VerificationGapKind.SUBJECT_CONTRACT_MISMATCH,
            "R11_VERIFIER", "; ".join(generated_at_problems))

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
    upstream = _optional_mapping(evidence.get("upstreamEvidence"),
                                 "upstreamEvidence") or {}
    r9 = _optional_mapping(upstream.get("r9AssetGraphEvidence"),
                           "r9AssetGraphEvidence")
    r8 = _optional_mapping(upstream.get("r8ExecutionEvidence"),
                           "r8ExecutionEvidence")
    r8_upstream = _optional_mapping(
        r8.get("upstreamEvidence") if isinstance(r8, Mapping) else None,
        "R8 upstreamEvidence") or {}
    r7 = _optional_mapping(r8_upstream.get("r7CrossMarketEvidence"),
                           "r7CrossMarketEvidence")
    declared = _optional_mapping(evidence.get("sourceDigests"),
                                 "sourceDigests") or {}

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
        # A8: identity is proven from the actual R9 GRAPH - exactly one
        # ECONOMIC_ASSET node with the canonical node id and UID; a missing
        # or non-canonical top-level economicNodeId is not sufficient proof.
        economic_nodes = [
            n for n in r9.get("nodes", [])
            if isinstance(n, Mapping)
            and n.get("nodeType") == "ECONOMIC_ASSET"
            and n.get("nodeId") == f"economic:{uid}"
            and n.get("economicAssetUid") == uid
        ]
        if len(economic_nodes) == 1:
            collector.pass_(
                "R9_IDENTITY_CONSISTENCY",
                "exactly one canonical ECONOMIC_ASSET node in the R9 graph")
        else:
            collector.fail(
                "R9_IDENTITY_CONSISTENCY",
                VerificationGapKind.SOURCE_LINEAGE_MISMATCH,
                "R11_VERIFIER",
                f"canonical R9 economic node appears "
                f"{len(economic_nodes)} times (expected exactly once)")

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
        # C4: R10 top-level canonicalAssetKey must be a valid mapping with
        # exact chainId/contractAddress and must agree with the R8/R9
        # deployment lineage.
        r10_key = evidence.get("canonicalAssetKey") if isinstance(
            evidence.get("canonicalAssetKey"), Mapping) else None
        r8_key = r8.get("canonicalAssetKey") if isinstance(
            r8.get("canonicalAssetKey"), Mapping) else None
        if r10_key is None or r8_key is None:
            collector.fail(
                "R8_DEPLOYMENT_LINEAGE",
                VerificationGapKind.SUBJECT_CONTRACT_MISMATCH,
                "R11_VERIFIER",
                "R10 canonicalAssetKey or R8 canonicalAssetKey is missing "
                "or not a mapping")
        elif r10_key.get("chainId") != r8_key.get("chainId") or str(
            r10_key.get("contractAddress", "")
        ).lower() != str(r8_key.get("contractAddress", "")).lower():
            collector.fail(
                "R8_DEPLOYMENT_LINEAGE",
                VerificationGapKind.SUBJECT_CONTRACT_MISMATCH,
                "R11_VERIFIER",
                "R10 canonicalAssetKey disagrees with the embedded R8 "
                "canonical deployment")
        else:
            deployment_nodes = [
                n for n in (r9 or {}).get("nodes", [])
                if isinstance(n, Mapping)
                and n.get("nodeType") == "TOKEN_DEPLOYMENT"
                and isinstance(n.get("canonicalAssetKey"), Mapping)
            ]
            matching = [
                n for n in deployment_nodes
                if n["canonicalAssetKey"].get("chainId") == r8_key.get("chainId")
                and str(n["canonicalAssetKey"].get("contractAddress", "")).lower()
                == str(r8_key.get("contractAddress", "")).lower()
            ]
            if r8.get("economicAssetUid") == uid and len(matching) == 1:
                collector.pass_(
                    "R8_DEPLOYMENT_LINEAGE",
                    "R10 canonicalAssetKey, embedded R8 deployment and R9 "
                    "deployment node all agree (exactly once)")
            else:
                collector.fail(
                    "R8_DEPLOYMENT_LINEAGE",
                    VerificationGapKind.SOURCE_LINEAGE_MISMATCH,
                    "R11_VERIFIER",
                    "embedded R8 economic/deployment lineage disagrees "
                    "with R9/R10")

    # ---- 6. R7 provenance ----------------------------------------------------
    if r7 is None:
        collector.fail(
            "R7_PROVENANCE", VerificationGapKind.SOURCE_LINEAGE_MISMATCH,
            "R11_VERIFIER", "embedded R7 lineage missing")
    else:
        r7_source = canonical_sha256(r7)
        r8_declared = r8.get("sourceDigests") if isinstance(
            r8.get("sourceDigests"), Mapping) else {}
        declared_r7 = r8_declared.get("r7CrossMarketDigest")
        internal_ok = (
            isinstance(r7.get("r7SnapshotDigest"), str)
            and isinstance(r7.get("layers"), Mapping)
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

    # ---- A10/B7: optional content-envelope binding (secondary authority) ---
    if content_envelope is not None and not isinstance(
        content_envelope, Mapping
    ):
        # B7: non-mapping envelope is a typed public-boundary failure
        collector.fail(
            "CONTENT_ENVELOPE_BINDING",
            VerificationGapKind.SUBJECT_CONTRACT_MISMATCH,
            "R11_VERIFIER",
            f"content envelope must be a mapping, got "
            f"{type(content_envelope).__name__}")
        return _finish(VerificationStatus.VERIFICATION_INPUT_INVALID)
    if content_envelope is not None:
        envelope_problems = []
        if content_envelope.get("schema") != "finco.evidence-envelope.v1":
            envelope_problems.append(
                f"envelope schema {content_envelope.get('schema')!r} is not "
                "the frozen envelope schema")
        if content_envelope.get("canonicalization") != "FINCO_SORTED_JSON_V1":
            envelope_problems.append("envelope canonicalization missing")
        if content_envelope.get("surface") != "finco_radar.r11.verification":
            envelope_problems.append(
                f"envelope surface {content_envelope.get('surface')!r} is "
                "not the frozen R11 verification surface")
        if content_envelope.get("evidenceType") != (
            "radar-r10-subject-evidence"
        ):
            envelope_problems.append(
                f"envelope evidenceType {content_envelope.get('evidenceType')!r} "
                "is not the expected subject evidence type")
        refs = content_envelope.get("authorityRefs")
        if refs != ["finco_radar.model_radar", "finco_radar.r10"]:
            envelope_problems.append(
                f"envelope authorityRefs {refs!r} do not match the frozen "
                "R10 authority refs")
        if content_envelope.get("payloadSha256") != subject_evidence_digest:
            envelope_problems.append(
                "envelope payloadSha256 does not equal the "
                "subjectEvidenceDigest")
        content_address = content_envelope.get("contentAddress")
        if content_address != ("sha256:"
                               + str(content_envelope.get("payloadSha256"))):
            envelope_problems.append(
                "envelope contentAddress is not sha256:<payloadSha256>")
        if envelope_problems:
            collector.fail(
                "CONTENT_ENVELOPE_BINDING",
                VerificationGapKind.SUBJECT_CONTRACT_MISMATCH,
                "R11_VERIFIER", "; ".join(envelope_problems))
        else:
            collector.pass_(
                "CONTENT_ENVELOPE_BINDING",
                "optional content envelope binds exactly to the verified "
                "subject payload")
    else:
        collector.unavailable(
            "CONTENT_ENVELOPE_BINDING",
            "no content envelope supplied (optional, secondary; the R11 "
            "snapshot digest remains the primary authority)")

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

    # A2: evaluated on EVERY valid subject - the no-model state MUST declare
    # MODEL_BINDING_UNAVAILABLE with the exact null/empty fields, and the
    # frozen R10 status/gap coherence rules must hold.
    no_model = model_evidence is None
    coherence_problems = []
    if no_model:
        if "MODEL_BINDING_UNAVAILABLE" not in subject_gap_kinds:
            coherence_problems.append(
                "no-model state must declare MODEL_BINDING_UNAVAILABLE")
        if (model_binding is not None or reference_comparison is not None
                or execution_comparisons != []):
            coherence_problems.append(
                "no-model state must carry null binding/reference and no "
                "execution comparisons")
    else:
        if "MODEL_BINDING_UNAVAILABLE" in subject_gap_kinds:
            coherence_problems.append(
                "MODEL_BINDING_UNAVAILABLE declared while model evidence "
                "is present")
    if subject_status == "MODEL_RADAR_OK" and evidence.get("gaps"):
        coherence_problems.append(
            "MODEL_RADAR_OK cannot carry unresolved subject gaps")
    if subject_status == "MODEL_RADAR_PARTIAL" and not evidence.get("gaps"):
        coherence_problems.append(
            "MODEL_RADAR_PARTIAL requires at least one subject gap")
    if honest_missing:
        if (model_binding is None and model_evidence is None
                and reference_comparison is None
                and execution_comparisons == []):
            pass  # consistent; also enforced above when no_model
        else:
            coherence_problems.append(
                "declared MODEL_BINDING_UNAVAILABLE but fabricated model "
                "fields or comparisons are present")
    if coherence_problems:
        collector.fail(
            "HONEST_MISSING_MODEL", VerificationGapKind.SUBJECT_CONTRACT_MISMATCH,
            "R11_VERIFIER", "; ".join(coherence_problems))
    else:
        collector.pass_(
            "HONEST_MISSING_MODEL",
            "subject status/gap coherence verified")
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
        for optional in ("MODEL_BINDING_CONTRACT", "MODEL_DIGESTS",
                         "MODEL_OBSERVATION_BINDINGS",
                         "COMPARABILITY_CONTRACT", "REFERENCE_ARITHMETIC",
                         "EXECUTION_ARITHMETIC", "EXECUTION_SOURCE_BINDING"):
            collector.unavailable(
                optional,
                "subject declares no model evidence; optional model-"
                "integrity authority not applicable (verified consistent "
                "with the declared MODEL_BINDING_UNAVAILABLE state)")
    else:
        # B1: independent ModelBinding verification.  The frozen R10
        # binding identity is reconstructed locally from the documented
        # canonical material; the frozen ModelBinding constructor is NOT
        # the primary proof.
        binding = model_binding if isinstance(model_binding, Mapping) else None
        binding_problems = []
        if binding is None:
            binding_problems.append(
                "modelEvidence present but modelBinding is null")
        else:
            if binding.get("economicAssetUid") != uid:
                binding_problems.append(
                    f"binding economicAssetUid {binding.get('economicAssetUid')!r} "
                    f"!= subject {uid!r}")
            if binding.get("economicNodeId") != f"economic:{uid}":
                binding_problems.append(
                    f"binding economicNodeId "
                    f"{binding.get('economicNodeId')!r} is not canonical")
            if binding.get("modelId") != model_evidence.get("modelId"):
                binding_problems.append(
                    "binding modelId differs from modelEvidence modelId")
            if binding.get("modelVersion") != (
                model_evidence.get("modelVersion")
            ):
                binding_problems.append(
                    "binding modelVersion differs from modelEvidence "
                    "modelVersion")
            binding_material = {
                "economicAssetUid": uid,
                "economicNodeId": f"economic:{uid}",
                "modelId": model_evidence.get("modelId"),
                "modelVersion": model_evidence.get("modelVersion"),
            }
            expected_binding_id = "model-binding:" + canonical_sha256(
                binding_material)
            if binding.get("bindingId") != expected_binding_id:
                binding_problems.append(
                    f"bindingId {binding.get('bindingId')!r} does not "
                    f"equal the independently reconstructed "
                    f"{expected_binding_id!r}")
        if binding_problems:
            collector.fail(
                "MODEL_BINDING_CONTRACT",
                VerificationGapKind.SUBJECT_CONTRACT_MISMATCH,
                "R11_VERIFIER", "; ".join(binding_problems))
        else:
            collector.pass_(
                "MODEL_BINDING_CONTRACT",
                "binding identity independently reconstructed "
                "(model-binding:<sha256>) and exactly bound to the subject "
                "economic identity and model evidence")
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

    # B5: historical timing semantics, using ONLY subject production-time
    # authority (no R11 wall clock).
    policy = evidence.get("timingPolicy") if isinstance(
        evidence.get("timingPolicy"), Mapping) else {}
    max_age_raw = policy.get("maxModelAgeSeconds")
    max_skew_raw = policy.get("maxModelMarketSkewSeconds")
    for name, raw in (("maxModelAgeSeconds", max_age_raw),
                      ("maxModelMarketSkewSeconds", max_skew_raw)):
        try:
            value = _decimal(raw, f"timingPolicy.{name}")
            if value <= 0:
                timing_problems.append(
                    f"timingPolicy.{name} must be strictly positive")
        except _ShapeError as exc:
            timing_problems.append(str(exc))

    generated_at_subject = None
    raw_generated = evidence.get("generatedAt")
    if isinstance(raw_generated, str):
        try:
            generated_at_subject = datetime.fromisoformat(raw_generated)
        except (ValueError, TypeError):
            pass
    model_evidence_hist = evidence.get("modelEvidence") if isinstance(
        evidence.get("modelEvidence"), Mapping) else None

    def _timing_dimension_entry():
        comparability = evidence.get("comparability") if isinstance(
            evidence.get("comparability"), Mapping) else None
        if comparability is None:
            return None
        dims = comparability.get("dimensions") if isinstance(
            comparability.get("dimensions"), list) else []
        for entry in dims:
            if isinstance(entry, Mapping) and entry.get(
                "dimension"
            ) == "TIMING":
                return entry
        return None

    max_age = None
    max_skew = None
    try:
        if max_age_raw is not None:
            max_age = _decimal(max_age_raw, "maxModelAgeSeconds")
        if max_skew_raw is not None:
            max_skew = _decimal(max_skew_raw, "maxModelMarketSkewSeconds")
    except _ShapeError:
        pass

    if model_evidence_hist is not None and generated_at_subject is not None:
        raw_valuation = model_evidence_hist.get("valuationAsOf")
        if isinstance(raw_valuation, str):
            try:
                valuation = datetime.fromisoformat(raw_valuation)
            except (ValueError, TypeError):
                valuation = None
            if valuation is not None and valuation.tzinfo is not None:
                if valuation > generated_at_subject:
                    timing_problems.append(
                        "model valuationAsOf is future relative to subject "
                        "production authority")
                elif max_age is not None:
                    age = _decimal_seconds(generated_at_subject - valuation)
                    timing_dim = _timing_dimension_entry()
                    timing_ok = (timing_dim is not None
                                 and timing_dim.get("ok") is True)
                    if age > max_age and timing_ok:
                        timing_problems.append(
                            f"model age {age}s exceeds policy {max_age}s "
                            "but the serialized TIMING dimension is marked "
                            "ok (stale model relabeled)")

    if (model_evidence_hist is not None and reference_comparison is not None
            and generated_at_subject is not None):
        raw_valuation = model_evidence_hist.get("valuationAsOf")
        raw_ref_at = reference_comparison.get("referenceObservedAt")
        if isinstance(raw_valuation, str) and isinstance(raw_ref_at, str):
            try:
                valuation = datetime.fromisoformat(raw_valuation)
                ref_at = datetime.fromisoformat(raw_ref_at)
            except (ValueError, TypeError):
                valuation = ref_at = None
            if (valuation is not None and ref_at is not None
                    and valuation.tzinfo is not None
                    and ref_at.tzinfo is not None and max_skew is not None):
                skew = _decimal_seconds(abs(valuation - ref_at))
                timing_dim = _timing_dimension_entry()
                timing_ok = (timing_dim is not None
                             and timing_dim.get("ok") is True)
                if skew > max_skew and timing_ok:
                    timing_problems.append(
                        f"model/reference skew {skew}s exceeds "
                        f"maxModelMarketSkewSeconds {max_skew}s but the "
                        "serialized TIMING dimension is marked ok")

    for row in execution_comparisons or []:
        if not isinstance(row, Mapping):
            continue
        raw_exec_at = row.get("executionObservedAt")
        if (model_evidence_hist is not None and isinstance(raw_exec_at, str)
                and isinstance(
                    model_evidence_hist.get("valuationAsOf"), str)
                and max_skew is not None):
            try:
                exec_at = datetime.fromisoformat(raw_exec_at)
                valuation = datetime.fromisoformat(
                    model_evidence_hist["valuationAsOf"])
            except (ValueError, TypeError):
                continue
            if exec_at.tzinfo is None or valuation.tzinfo is None:
                continue
            skew = _decimal_seconds(abs(valuation - exec_at))
            if skew > max_skew:
                timing_problems.append(
                    f"execution row {row.get('side')}/"
                    f"{row.get('requestedNotionalUsd')} retained outside "
                    f"skew policy (skew {skew}s > {max_skew}s)")

    if timing_problems:
        collector.fail(
            "HISTORICAL_TIMING", VerificationGapKind.SUBJECT_CONTRACT_MISMATCH,
            "R11_VERIFIER", "; ".join(timing_problems))
        return

    # C2: bidirectional verification of the serialized TIMING dimension
    model_hist = evidence.get("modelEvidence") if isinstance(
        evidence.get("modelEvidence"), Mapping) else None
    if model_hist is not None:
        expected_ok = True
        expected_gap = None
        raw_val = model_hist.get("valuationAsOf")
        raw_gen = evidence.get("generatedAt")
        if isinstance(raw_val, str) and isinstance(raw_gen, str):
            try:
                val_dt = datetime.fromisoformat(raw_val)
                gen_dt = datetime.fromisoformat(raw_gen)
            except (ValueError, TypeError):
                val_dt = gen_dt = None
            if (val_dt is not None and gen_dt is not None
                    and max_age is not None):
                age = _decimal_seconds(gen_dt - val_dt)
                if age > max_age:
                    expected_ok = False
                    expected_gap = "MODEL_STALE"
                elif (reference_comparison is not None
                      and isinstance(reference_comparison, Mapping)
                      and max_skew is not None):
                    raw_ref = reference_comparison.get("referenceObservedAt")
                    if isinstance(raw_ref, str):
                        try:
                            ref_dt = datetime.fromisoformat(raw_ref)
                        except (ValueError, TypeError):
                            ref_dt = None
                        if ref_dt is not None and ref_dt.tzinfo is not None:
                            skew = _decimal_seconds(abs(val_dt - ref_dt))
                            if skew > max_skew:
                                expected_ok = False
                                expected_gap = "TIMING_SKEW_INVALID"
        comparability = evidence.get("comparability") if isinstance(
            evidence.get("comparability"), Mapping) else None
        timing_dim = None
        if isinstance(comparability, Mapping):
            dims = comparability.get("dimensions") if isinstance(
                comparability.get("dimensions"), list) else []
            for entry in dims:
                if isinstance(entry, Mapping) and entry.get(
                    "dimension"
                ) == "TIMING":
                    timing_dim = entry
                    break
        if timing_dim is not None:
            serialized_ok = timing_dim.get("ok")
            serialized_gap = timing_dim.get("gapKind")
            if serialized_ok != expected_ok or serialized_gap != expected_gap:
                collector.fail(
                    "HISTORICAL_TIMING",
                    VerificationGapKind.SUBJECT_CONTRACT_MISMATCH,
                    "R11_VERIFIER",
                    f"serialized TIMING dimension (ok={serialized_ok!r}, "
                    f"gapKind={serialized_gap!r}) does not match the "
                    f"independently reconstructed result "
                    f"(ok={expected_ok!r}, gapKind={expected_gap!r})")
                return
        if not expected_ok:
            collector.fail(
                "HISTORICAL_TIMING",
                VerificationGapKind.SUBJECT_CONTRACT_MISMATCH,
                "R11_VERIFIER",
                f"independently reconstructed timing gap: {expected_gap}")
            return
        # Per-execution-row skew
        for row in execution_comparisons or []:
            if not isinstance(row, Mapping):
                continue
            raw_exec = row.get("executionObservedAt")
            if not isinstance(raw_exec, str) or not isinstance(
                model_hist.get("valuationAsOf"), str
            ):
                continue
            try:
                exec_dt = datetime.fromisoformat(raw_exec)
                val_dt = datetime.fromisoformat(model_hist["valuationAsOf"])
            except (ValueError, TypeError):
                continue
            if exec_dt.tzinfo is None or val_dt.tzinfo is None:
                continue
            if max_skew is not None:
                skew = _decimal_seconds(abs(val_dt - exec_dt))
                if skew > max_skew:
                    collector.fail(
                        "HISTORICAL_TIMING",
                        VerificationGapKind.SUBJECT_CONTRACT_MISMATCH,
                        "R11_VERIFIER",
                        f"execution row skew {skew}s exceeds policy "
                        f"{max_skew}s")
                    return

    # C3: no-model subjects get HISTORICAL_TIMING as UNAVAILABLE
    if "HISTORICAL_TIMING" not in collector.checks:
        if model_evidence is None:
            collector.unavailable(
                "HISTORICAL_TIMING",
                "no model timing authority to verify; HISTORICAL_TIMING is "
                "explicitly not applicable for this subject")
        else:
            collector.pass_(
                "HISTORICAL_TIMING",
                "historical timing semantics verified against subject "
                "production-time authority; no R11 wall-clock freshness "
                "applied")

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


# C1: derived_synthetic_flag is now the total _total_derived_synthetic
derived_synthetic_flag = _total_derived_synthetic


def _verify_model_integrity(collector: "_Collector", evidence: Mapping,
                            model_evidence: Mapping) -> None:
    """Check 10 (A4): independently verify the complete frozen serialized
    ModelEvidence authority contract and rederive all digests."""
    problems: list[str] = []
    input_evidence = model_evidence.get("inputEvidence")
    output_evidence = model_evidence.get("outputEvidence")
    declared_input = model_evidence.get("inputDigest")
    declared_output = model_evidence.get("outputDigest")
    declared_run = model_evidence.get("modelRunDigest")

    if model_evidence.get("engineAuthority") not in FROZEN_ENGINE_AUTHORITIES:
        problems.append(
            f"engineAuthority {model_evidence.get('engineAuthority')!r} is "
            "not in the frozen typed authority vocabulary")
    if type(model_evidence.get("synthetic")) is not bool:
        problems.append("modelEvidence synthetic must be an exact boolean")
    for field_name in ("modelId", "modelVersion", "economicAssetUid",
                       "economicNodeId"):
        value = model_evidence.get(field_name)
        if not isinstance(value, str) or not value.strip():
            problems.append(f"{field_name} must be a non-empty string")
    uid = evidence.get("economicAssetUid")
    if model_evidence.get("economicAssetUid") != uid:
        problems.append("model economicAssetUid differs from the subject")
    if model_evidence.get("economicNodeId") != f"economic:{uid}":
        problems.append("model economicNodeId is not the canonical node")

    if not isinstance(input_evidence, Mapping) or not isinstance(
        output_evidence, Mapping
    ):
        problems.append("inputEvidence/outputEvidence missing or malformed")
        collector.fail("MODEL_DIGESTS",
                       VerificationGapKind.SUBJECT_CONTRACT_MISMATCH,
                       "R11_VERIFIER", "; ".join(problems))
        collector.fail("MODEL_OBSERVATION_BINDINGS",
                       VerificationGapKind.SUBJECT_CONTRACT_MISMATCH,
                       "R11_VERIFIER", "; ".join(problems))
        return

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

    for key, declared in (("value", str(model_evidence.get("value"))),
                          ("valueKind", model_evidence.get("valueKind")),
                          ("currency", model_evidence.get("currency")),
                          ("unitBasis", model_evidence.get("unitBasis")),
                          ("valuationAsOf",
                           model_evidence.get("valuationAsOf"))):
        if key not in output_evidence:
            problems.append(f"output observation missing required key {key!r}")
        elif output_evidence[key] != declared:
            problems.append(
                f"output observation {key} disagrees with the declared "
                f"model field")
    declared_multiplier = model_evidence.get("unitMultiplier")
    declared_basis = model_evidence.get("unitMultiplierBasis")
    if declared_multiplier is not None:
        if str(input_evidence.get("unitMultiplier")) != str(
            declared_multiplier
        ):
            problems.append(
                "input authority unitMultiplier disagrees or is missing")
        if input_evidence.get("unitMultiplierBasis") != declared_basis:
            problems.append(
                "input authority unitMultiplierBasis disagrees or is "
                "missing")
        for source_name, source in (("output", output_evidence),
                                    ("input", input_evidence)):
            if source.get("unitMultiplier") is not None and str(
                source["unitMultiplier"]) != str(declared_multiplier):
                problems.append(
                    f"{source_name} unitMultiplier conflicts with the "
                    "declared multiplier")
            if source.get("unitMultiplierBasis") is not None and (
                source["unitMultiplierBasis"] != declared_basis
            ):
                problems.append(
                    f"{source_name} unitMultiplierBasis conflicts with the "
                    "declared basis")
    else:
        if "unitMultiplier" in input_evidence or "unitMultiplierBasis" in (
            input_evidence
        ):
            problems.append(
                "input record carries multiplier authority that the "
                "declared model evidence drops")
        if "unitMultiplier" in output_evidence or "unitMultiplierBasis" in (
            output_evidence
        ):
            problems.append(
                "output-only multiplier claim without input authority")

    if problems:
        collector.fail("MODEL_DIGESTS",
                       VerificationGapKind.SUBJECT_CONTRACT_MISMATCH,
                       "R11_VERIFIER", "; ".join(problems))
        collector.fail("MODEL_OBSERVATION_BINDINGS",
                       VerificationGapKind.SUBJECT_CONTRACT_MISMATCH,
                       "R11_VERIFIER", "; ".join(problems))
    else:
        collector.pass_(
            "MODEL_DIGESTS", "input/output/run digests independently "
            "rederived from the serialized contract")
        collector.pass_(
            "MODEL_OBSERVATION_BINDINGS",
            "serialized observation authority fully bound (value, kind, "
            "currency, basis, valuationAsOf, multiplier policy)")


def _verify_comparability(collector: "_Collector",
                          comparability: Mapping | None) -> None:
    """Check 11 (A5): complete serialized comparability contract."""
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
    problems: list[str] = []
    seen: dict[Any, int] = {}
    failed: dict[Any, Any] = {}
    for entry in dimensions:
        if not isinstance(entry, Mapping):
            problems.append("non-mapping dimension result")
            continue
        name = entry.get("dimension")
        seen[name] = seen.get(name, 0) + 1
        ok = entry.get("ok")
        if type(ok) is not bool:
            problems.append(f"dimension {name!r} ok is not an exact boolean")
            continue
        gap_kind = entry.get("gapKind")
        if ok and gap_kind is not None:
            problems.append(f"dimension {name!r} is ok but carries a gap")
        if not ok and (gap_kind is None or not isinstance(gap_kind, str)):
            problems.append(
                f"dimension {name!r} failed without a typed gap kind")
        elif not ok and isinstance(gap_kind, str):
            if gap_kind not in R10_GAP_KINDS:
                problems.append(
                    f"dimension {name!r} gapKind {gap_kind!r} is not in the "
                    "frozen R10 gap-kind vocabulary")
            else:
                failed[name] = gap_kind
    duplicates = sorted(str(k) for k, v in seen.items() if v > 1)
    missing = [d for d in FROZEN_DIMENSIONS if d not in seen]
    unknown = [k for k in seen if k not in FROZEN_DIMENSIONS]
    if duplicates or missing or unknown:
        problems.append(
            f"dimension set invalid: duplicated={duplicates} "
            f"missing={missing} unknown={unknown}")
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
        problems.append(
            f"comparability state {state!r} inconsistent with the "
            f"serialized dimension results")
    declared_gaps = comparability.get("gaps")
    expected_gaps = sorted(failed.values())
    if declared_gaps != expected_gaps:
        problems.append(
            f"serialized comparability.gaps {declared_gaps!r} does not "
            f"equal the failed dimensions' gap kinds {expected_gaps!r}")
    if problems:
        collector.fail(
            "COMPARABILITY_CONTRACT",
            VerificationGapKind.SUBJECT_CONTRACT_MISMATCH,
            "R11_VERIFIER", "; ".join(problems))
        return
    collector.pass_(
        "COMPARABILITY_CONTRACT",
        "exactly the seven frozen dimensions, one exact-boolean result "
        "each, state consistent, serialized gaps mirror failed dimensions")


def _verify_reference_arithmetic(
    collector: "_Collector", model_evidence: Mapping,
    reference_comparison: Mapping, r7: Mapping | None,
) -> None:
    """Check 12 (A6): independent Decimal recomputation with full binding
    of every serialized reference field to the embedded R7 authority."""
    problems: list[str] = []
    oracle = {}
    if r7 is not None:
        oracle = (r7.get("layers") or {}).get("oracleReference") or {}
    try:
        declared_bound_value = _decimal(
            reference_comparison.get("modelValue"))
        model_value = _decimal(model_evidence.get("value"),
                               "modelEvidence.value")
        if declared_bound_value != model_value:
            problems.append(
                "referenceComparison.modelValue does not equal "
                "modelEvidence.value")
            model_value = declared_bound_value
        reference_price = _decimal(reference_comparison.get("referencePrice"))
        declared_minus = _decimal(
            reference_comparison.get("referenceMinusModelValue"))
        declared_bps = _decimal(
            reference_comparison.get("referenceVsModelBps"))
    except (_ShapeError, decimal.InvalidOperation, TypeError, ValueError,
            KeyError, AttributeError, IndexError) as exc:
        collector.fail(
            "REFERENCE_ARITHMETIC", VerificationGapKind.SUBJECT_CONTRACT_MISMATCH,
            "R11_VERIFIER",
            f"reference comparison arithmetic reconstruction failed: {exc}")
        return
    if not model_value.is_finite():
        problems.append("model denominator must be finite")
        collector.fail(
            "REFERENCE_ARITHMETIC",
            VerificationGapKind.SUBJECT_CONTRACT_MISMATCH,
            "R11_VERIFIER", "; ".join(problems))
        return
    if model_value <= 0:
        problems.append("model denominator must be positive and finite "
                        "(checked before division)")
        collector.fail(
            "REFERENCE_ARITHMETIC",
            VerificationGapKind.SUBJECT_CONTRACT_MISMATCH,
            "R11_VERIFIER", "; ".join(problems))
        return
    if not reference_price.is_finite() or reference_price <= 0:
        problems.append("reference price must be positive and finite")
        collector.fail(
            "REFERENCE_ARITHMETIC",
            VerificationGapKind.SUBJECT_CONTRACT_MISMATCH,
            "R11_VERIFIER", "; ".join(problems))
        return
    expected_minus = reference_price - model_value
    expected_bps = (reference_price / model_value - 1) * BPS_SCALE
    if expected_minus != declared_minus:
        problems.append("referenceMinusModelValue does not recompute")
    if expected_bps != declared_bps:
        problems.append("referenceVsModelBps does not recompute")
    if (not _tz_aware(reference_comparison.get("modelObservedAt"))
            or not _tz_aware(reference_comparison.get("referenceObservedAt"))):
        problems.append("comparison timestamps must be timezone-aware")
    if not oracle:
        problems.append("no embedded R7 oracle reference exists")
    else:
        try:
            if oracle.get("price") is None:
                problems.append("embedded R7 oracle price missing")
            elif _decimal(oracle["price"],
                          "R7 oracle price") != reference_price:
                problems.append(
                    "reference price does not trace to the embedded R7 "
                    "oracle price")
            if not oracle.get("source"):
                problems.append("embedded R7 oracle source missing")
            elif reference_comparison.get("referenceSource") != oracle.get(
                "source"
            ):
                problems.append(
                    "reference source does not trace to the embedded R7 "
                    "oracle source")
            if not oracle.get("observedAt"):
                problems.append("embedded R7 oracle observedAt missing")
            elif reference_comparison.get("referenceObservedAt") != oracle.get(
                "observedAt"
            ):
                problems.append(
                    "reference observed timestamp does not equal the "
                    "embedded R7 oracle observedAt")
        except _ShapeError as exc:
            problems.append(f"oracle binding reconstruction failed: {exc}")
    declared_model_at = reference_comparison.get("modelObservedAt")
    if declared_model_at != model_evidence.get("valuationAsOf"):
        problems.append(
            "modelObservedAt does not equal the model valuation timestamp")
    if problems:
        collector.fail(
            "REFERENCE_ARITHMETIC", VerificationGapKind.SUBJECT_CONTRACT_MISMATCH,
            "R11_VERIFIER", "; ".join(problems))
    else:
        collector.pass_(
            "REFERENCE_ARITHMETIC",
            "referenceMinusModelValue and referenceVsModelBps independently "
            "recompute in exact Decimal and bind exactly to the embedded "
            "R7 oracle authority")


def _verify_execution_rows(
    collector: "_Collector", model_evidence: Mapping, rows: list,
    r8: Mapping | None,
) -> None:
    """Checks 13/14 (A7): independent per-row arithmetic plus full
    canonical scenario binding including r8ScenarioIndex, duplicate
    detection, USD currency authority and scenario deployment identity."""
    problems: list[str] = []
    scenarios = _sequence_or_fail(
        (r8 or {}).get("scenarios"), "R8 scenarios") if isinstance(
        (r8 or {}).get("scenarios"), list) else []
    canonical: list[tuple[tuple, Mapping]] = []
    seen_keys: dict[tuple, int] = {}
    for scenario in scenarios:
        if not isinstance(scenario, Mapping):
            problems.append("non-mapping R8 scenario")
            continue
        entry = scenario.get("scenario")
        if not isinstance(entry, Mapping):
            problems.append("non-mapping R8 scenario entry")
            continue
        # C1: typed scalar extraction for sort/hash safety
        raw_side = entry.get("side")
        raw_notional = entry.get("requestedNotionalUsd")
        raw_venue = entry.get("quoteSource")
        if not isinstance(raw_side, str) or not raw_side.strip():
            problems.append(f"R8 scenario side must be a non-empty string")
            continue
        if not isinstance(raw_venue, str) or not raw_venue.strip():
            problems.append(f"R8 scenario quoteSource must be non-empty")
            continue
        try:
            notional = _decimal(raw_notional, "requestedNotionalUsd")
            if notional <= 0 or not notional.is_finite():
                problems.append(
                    f"R8 scenario requestedNotionalUsd must be positive "
                    f"and finite")
                continue
        except _ShapeError as exc:
            problems.append(f"R8 scenario notional: {exc}")
            continue
        key = (raw_side, str(notional), raw_venue)
        if key in seen_keys:
            problems.append(
                "duplicate/ambiguous R8 scenario identity "
                f"(side={key[0]!r}, notional={key[1]!r}, "
                f"venue={key[2]!r})")
        seen_keys[key] = seen_keys.get(key, 0) + 1
        canonical.append((key, scenario))
    canonical.sort(key=lambda item: (item[0][0], item[0][1], item[0][2]))
    canonical_index = {item[0]: i for i, item in enumerate(canonical)}
    r8_key = (r8 or {}).get("canonicalAssetKey") or {}
    model_value = None
    for position, row in enumerate(rows):
        label = f"row[{position}]"
        if not isinstance(row, Mapping):
            problems.append(f"{label}: not a mapping")
            continue
        key = (row.get("side"), str(row.get("requestedNotionalUsd")),
               row.get("quoteSource"))
        scenario = None
        if seen_keys.get(key, 0) == 1:
            scenario = seen_lookup(canonical, key)
        try:
            if model_value is None:
                model_value = _decimal(model_evidence.get("value"),
                                       "modelEvidence.value")
            model_value_row = _decimal(row.get("modelValue"),
                                       "comparison modelValue")
            execution_price = _decimal(row.get("executionPrice"),
                                       "comparison executionPrice")
            declared_minus = _decimal(row.get("executionMinusModelValue"),
                                      "executionMinusModelValue")
            declared_bps = _decimal(row.get("executionVsModelBps"),
                                    "executionVsModelBps")
        except (_ShapeError, decimal.InvalidOperation, TypeError, ValueError,
                KeyError, AttributeError, IndexError) as exc:
            problems.append(
                f"{label}: arithmetic reconstruction failed: {exc}")
            continue
        if model_value_row != model_value:
            problems.append(
                f"{label}: comparison model value differs from the "
                "declared model value")
            model_value_row = model_value
        if not model_value_row.is_finite():
            problems.append(
                f"{label}: model denominator must be finite")
            continue
        if model_value_row <= 0:
            problems.append(
                f"{label}: model denominator must be positive and finite "
                "(checked before division)")
            continue
        if not execution_price.is_finite():
            problems.append(
                f"{label}: execution price must be finite")
            continue
        if execution_price <= 0:
            problems.append(
                f"{label}: execution price must be positive and finite")
            continue
        expected_minus = execution_price - model_value_row
        expected_bps = (execution_price / model_value_row - 1) * BPS_SCALE
        if expected_minus != declared_minus:
            problems.append(f"{label}: executionMinusModelValue does not "
                            "recompute")
        if expected_bps != declared_bps:
            problems.append(f"{label}: executionVsModelBps does not "
                            "recompute")
        if row.get("executionCurrency") != "USD":
            problems.append(
                f"{label}: execution currency must be USD per frozen R8 "
                "executionPriceUsdPerToken semantics")
        if scenario is None:
            problems.append(
                f"{label}: no unique embedded R8 scenario matches "
                f"(side={key[0]!r}, notional={key[1]!r}, "
                f"venue={key[2]!r})")
            continue
        entry = scenario.get("scenario") or {}
        scenario_upstream = scenario.get("upstreamEvidence")
        if scenario_upstream is not None and not isinstance(
            scenario_upstream, Mapping
        ):
            problems.append(
                f"{label}: R8 scenario upstreamEvidence must be a mapping")
            continue
        r2 = scenario_upstream.get("r2GapEvidence") if (
            isinstance(scenario_upstream, Mapping)) else None
        if r2 is not None and not isinstance(r2, Mapping):
            problems.append(
                f"{label}: R8 scenario r2GapEvidence must be a mapping")
            continue
        source_price = r2.get("executionPriceUsdPerToken") if (
            isinstance(r2, Mapping)) else None
        try:
            if source_price is None:
                problems.append(
                    f"{label}: R8 scenario carries no "
                    "executionPriceUsdPerToken source value")
                continue
            if _decimal(source_price, "R8 executionPriceUsdPerToken") != (
                execution_price
            ):
                problems.append(
                    f"{label}: execution price does not trace to the "
                    "embedded R8 scenario executionPriceUsdPerToken")
                continue
        except _ShapeError as exc:
            problems.append(f"{label}: {exc}")
            continue
        if row.get("r8NetEdgeState") != scenario.get("netEdgeState"):
            problems.append(
                f"{label}: R8 net-edge state not carried verbatim")
        declared_index = row.get("r8ScenarioIndex")
        expected_index = canonical_index.get(key)
        if declared_index != expected_index:
            problems.append(
                f"{label}: r8ScenarioIndex {declared_index!r} does not "
                f"identify the canonically ordered scenario "
                f"(expected {expected_index!r})")
        quote_at = scenario.get("quoteObservedAt")
        if quote_at is None:
            problems.append(
                f"{label}: embedded R8 scenario carries no quoteObservedAt")
        elif row.get("executionObservedAt") != quote_at:
            problems.append(
                f"{label}: execution timestamp does not equal the R8 "
                "scenario quoteObservedAt")
        if (entry.get("chainId") != r8_key.get("chainId")
                or str(entry.get("contractAddress", "")).lower()
                != str(r8_key.get("contractAddress", "")).lower()):
            problems.append(
                f"{label}: scenario deployment identity disagrees with the "
                "canonical R8 deployment")
    if problems:
        arithmetic = [p for p in problems if "recompute" in p]
        binding = [p for p in problems if "recompute" not in p]
        if arithmetic:
            collector.fail(
                "EXECUTION_ARITHMETIC",
                VerificationGapKind.SUBJECT_CONTRACT_MISMATCH,
                "R11_VERIFIER", "; ".join(arithmetic))
        else:
            collector.pass_(
                "EXECUTION_ARITHMETIC",
                "every present execution row recomputes independently in "
                "exact Decimal")
        if binding:
            collector.fail(
                "EXECUTION_SOURCE_BINDING",
                VerificationGapKind.SOURCE_LINEAGE_MISMATCH,
                "R11_VERIFIER", "; ".join(binding))
        else:
            collector.pass_(
                "EXECUTION_SOURCE_BINDING",
                "every execution row binds to its canonical embedded R8 "
                "scenario")
    else:
        collector.pass_(
            "EXECUTION_ARITHMETIC",
            "every execution row recomputes independently in exact Decimal "
            "with identical BUY/SELL sign semantics and no R8 cost "
            "deduction")
        collector.pass_(
            "EXECUTION_SOURCE_BINDING",
            "every execution row binds to its canonical embedded R8 "
            "scenario (identity, index, price, timestamp, USD currency, "
            "net-edge state, deployment)")


def _safe_notional(raw: str) -> Decimal:
    try:
        return _decimal(raw)
    except (decimal.InvalidOperation, TypeError, ValueError):
        return Decimal(0)


def seen_lookup(canonical, key):
    for k, scenario in canonical:
        if k == key:
            return scenario
    return None


# C1: derived_synthetic_flag is now the total _total_derived_synthetic
derived_synthetic_flag = _total_derived_synthetic


