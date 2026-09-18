"""Networked R11 proof: independent verification of the frozen R10 subject.

Produces fresh R10 subject evidence through the frozen R10 implementation
UNCHANGED (re-running the frozen R1→R9 composition plus the R10 bridge),
then independently verifies the serialized output through the R11
verifier.  The verifier itself is offline and read-only once it receives
the serialized subject.

Expected live output:
    R11     = VERIFICATION_OK
    subject = MODEL_RADAR_PARTIAL + MODEL_BINDING_UNAVAILABLE
"""
from __future__ import annotations

import hashlib
import json
import os
from datetime import datetime, timezone
from decimal import Decimal
from pathlib import Path
from typing import Any

from finco_radar.model_radar.bridge import build_model_radar_snapshot
from finco_radar.model_radar.contracts import ModelRadarTimingPolicy
from finco_radar.r8.live_proof import _build_live_snapshot as _build_r8_live_snapshot
from finco_radar.r9.live_proof import (
    build_graph_from_upstream as build_r9_evidence,
)
from finco_radar.verification.contracts import (
    R11_BOUNDARIES,
    VerificationStatus,
    build_verification_envelope,
)
from finco_radar.verification.verifier import verify_r10_evidence

EVIDENCE_PATH = "artifacts/radar_r11_verification_evidence.json"
SHA256_PATH = "artifacts/radar_r11_verification_evidence.sha256"
MANIFEST_PATH = "artifacts/radar_r11_verification_manifest.json"

R10_MAX_MODEL_AGE_SECONDS = Decimal("900")
R10_MAX_MODEL_MARKET_SKEW_SECONDS = Decimal("300")


def main() -> int:
    r8_evidence, audit = _build_r8_live_snapshot()
    r9_evidence = build_r9_evidence(
        r8_evidence=r8_evidence,
        git_head=r8_evidence["gitHead"],
        generated_at=datetime.now(timezone.utc),
    )
    subject_snapshot = build_model_radar_snapshot(
        r9_evidence=r9_evidence,
        r8_evidence=r8_evidence,
        model_evidence=None,
        timing_policy=ModelRadarTimingPolicy(
            max_model_age_seconds=R10_MAX_MODEL_AGE_SECONDS,
            max_model_market_skew_seconds=R10_MAX_MODEL_MARKET_SKEW_SECONDS,
        ),
        now=datetime.now(timezone.utc),
        git_head=r8_evidence["gitHead"],
        synthetic=False,
    )
    subject_evidence = subject_snapshot.to_evidence_dict()

    verification = verify_r10_evidence(
        evidence=subject_evidence,
        generated_at=datetime.now(timezone.utc),
        git_head=subject_evidence["gitHead"],
        freeze_anchor="7ffaf3b1e67dabb728314948e2a4e4c7ef30047a",
        freeze_tree="fba9d76d9dceee35d079563b115fdde90c40bd46",
    )
    evidence = verification.to_evidence_dict()
    subject_evidence = evidence["subjectEvidence"]
    # Optional content-addressed envelope over the verified SUBJECT payload
    # (frozen infrastructure, consumed read-only; NOT an on-chain claim and
    # not the primary R11 authority).
    envelope = build_verification_envelope(subject_evidence)
    envelope_dict = envelope.as_dict()
    if envelope_dict["payloadSha256"] != evidence["subjectEvidenceDigest"]:
        raise RuntimeError("envelope payload binding inconsistent")
    evidence["contentEnvelope"] = {
        "schema": envelope_dict["schema"],
        "canonicalization": envelope_dict["canonicalization"],
        "surface": envelope_dict["surface"],
        "evidenceType": envelope_dict["evidenceType"],
        "authorityRefs": envelope_dict["authorityRefs"],
        "payloadSha256": envelope_dict["payloadSha256"],
        "contentAddress": envelope_dict["contentAddress"],
        "note": ("frozen finco_protocol.verification.EvidenceEnvelope v1; "
                 "content-addressed only, NOT on-chain anchoring and NOT "
                 "the primary R11 authority"),
    }

    first = json.dumps(evidence, indent=2, sort_keys=True, ensure_ascii=False)
    second = json.dumps(json.loads(first), indent=2, sort_keys=True,
                        ensure_ascii=False)
    if first != second:
        raise RuntimeError("R11 evidence serialization is not byte-deterministic")
    evidence_path = Path(os.getenv("RADAR_R11_EVIDENCE_PATH", EVIDENCE_PATH))
    evidence_path.parent.mkdir(parents=True, exist_ok=True)
    evidence_path.write_text(first + "\n", encoding="utf-8")
    digest = hashlib.sha256(evidence_path.read_bytes()).hexdigest()
    Path(os.getenv("RADAR_R11_SHA256_PATH", SHA256_PATH)).write_text(
        f"{digest}  {evidence_path.name}\n", encoding="utf-8")

    subject_gaps = sorted(g["gapKind"] for g in evidence["subjectGaps"])
    failed = sum(1 for c in evidence["checks"] if c["state"] == "FAIL")
    unavailable = sum(1 for c in evidence["checks"]
                      if c["state"] == "UNAVAILABLE")
    manifest = {
        "schemaVersion": evidence["schemaVersion"],
        "phase": evidence["phase"],
        "gitHead": evidence["gitHead"],
        "producedAt": evidence["generatedAt"],
        "status": evidence["status"],
        "subjectPhase": evidence["subjectPhase"],
        "subjectStatus": evidence["subjectStatus"],
        "economicAssetUid": evidence["economicAssetUid"],
        "subjectSnapshotDigest": evidence["subjectSnapshotDigest"],
        "subjectEvidenceSha256": hashlib.sha256(
            json.dumps(subject_evidence, indent=2, sort_keys=True,
                       ensure_ascii=False).encode("utf-8")
            + b"\n").hexdigest(),
        "freezeAnchor": evidence["freezeAnchor"],
        "freezeTree": evidence["subjectAuthorityTree"],
        "r11SnapshotDigest": evidence["r11SnapshotDigest"],
        "evidenceJsonSha256": digest,
        "checkCount": len(evidence["checks"]),
        "failedCheckCount": failed,
        "unavailableCheckCount": unavailable,
        "synthetic": evidence["synthetic"],
        "boundaries": evidence["boundaries"],
        "candidateAudit": audit,
        "note": ("R11 verifies the deterministic contract and lineage of "
                 "the serialized R10 evidence; it does not attest economic "
                 "truth. The subject remains honestly MODEL_RADAR_PARTIAL "
                 "+ MODEL_BINDING_UNAVAILABLE."),
    }
    Path(os.getenv("RADAR_R11_MANIFEST_PATH", MANIFEST_PATH)).write_text(
        json.dumps(manifest, indent=2, sort_keys=True), encoding="utf-8")
    print(json.dumps({
        "status": evidence["status"],
        "subjectStatus": evidence["subjectStatus"],
        "subjectGaps": subject_gaps,
        "checks": len(evidence["checks"]),
        "failed": failed,
        "unavailable": unavailable,
        "synthetic": evidence["synthetic"],
        "digest": digest,
        "evidence": str(evidence_path),
    }, sort_keys=True))
    if evidence["status"] != VerificationStatus.VERIFICATION_OK.value:
        raise RuntimeError("live R11 verification is not VERIFICATION_OK")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
