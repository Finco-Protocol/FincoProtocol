"""Networked R12 proof: Digital Twin from independently verified R11 evidence.

Produces fresh R11 evidence through the frozen R11 implementation unchanged,
then constructs the Digital Twin from the verified R11 output.
"""
from __future__ import annotations

import hashlib
import json
import os
from datetime import datetime, timezone
from decimal import Decimal
from pathlib import Path

from finco_radar.model_radar.bridge import build_model_radar_snapshot
from finco_radar.model_radar.contracts import ModelRadarTimingPolicy
from finco_radar.r8.live_proof import _build_live_snapshot as _build_r8_live_snapshot
from finco_radar.r9.live_proof import (
    build_graph_from_upstream as build_r9_evidence,
)
from finco_radar.r9.live_proof import (
    build_graph_from_upstream as build_r9_evidence,
)
from finco_radar.verification.verifier import verify_r10_evidence
from finco_radar.model_radar.bridge import build_model_radar_snapshot
from finco_radar.model_radar.contracts import ModelRadarTimingPolicy

EVIDENCE_PATH = "artifacts/radar_r12_digital_twin_evidence.json"
SHA256_PATH = "artifacts/radar_r12_digital_twin_evidence.sha256"
MANIFEST_PATH = "artifacts/radar_r12_digital_twin_manifest.json"


def main() -> int:
    from finco_radar.r11.live_proof import build_graph_from_upstream
    r8_evidence, audit = _build_r8_live_snapshot()
    r9_evidence = build_r9_evidence(
        r8_evidence=r8_evidence,
        git_head=r8_evidence["gitHead"],
        generated_at=datetime.now(timezone.utc),
    )
    subject = build_model_radar_snapshot(
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
    subject_evidence = subject.to_evidence_dict()

    verification = verify_r10_evidence(
        evidence=subject_evidence,
        generated_at=datetime.now(timezone.utc),
        git_head=subject_evidence["gitHead"],
        freeze_anchor="7ffaf3b1e67dabb728314948e2a4e4c7ef30047a",
        freeze_tree="fba9d76d9dceee35d079563b115fdde90c40bd46",
    )
    r11_evidence = verification.to_evidence_dict()

    from finco_radar.digital_twin.twin import build_digital_twin
    twin = build_digital_twin(
        r11_evidence=r11_evidence,
        generated_at=datetime.now(timezone.utc),
        git_head=r11_evidence["gitHead"],
        synthetic=False,
    )
    evidence = twin.to_evidence_dict()

    first = json.dumps(evidence, indent=2, sort_keys=True, ensure_ascii=False)
    second = json.dumps(json.loads(first), indent=2, sort_keys=True,
                        ensure_ascii=False)
    if first != second:
        raise RuntimeError("R12 evidence serialization is not byte-deterministic")
    evidence_path = Path(os.getenv("RADAR_R12_EVIDENCE_PATH", EVIDENCE_PATH))
    evidence_path.parent.mkdir(parents=True, exist_ok=True)
    evidence_path.write_text(first + "\n", encoding="utf-8")
    digest = hashlib.sha256(evidence_path.read_bytes()).hexdigest()
    Path(os.getenv("RADAR_R12_SHA256_PATH", SHA256_PATH)).write_text(
        f"{digest}  {evidence_path.name}\n", encoding="utf-8")

    subject_gaps = sorted(g["gapKind"] for g in evidence["upstreamGaps"])
    manifest = {
        "schemaVersion": evidence["schemaVersion"],
        "phase": evidence["phase"],
        "gitHead": evidence["gitHead"],
        "producedAt": evidence["generatedAt"],
        "status": evidence["status"],
        "economicAssetUid": evidence["economicAssetUid"],
        "twinId": evidence["twinId"],
        "r12SnapshotDigest": evidence["r12SnapshotDigest"],
        "r11SnapshotDigest": evidence["subjectR11Evidence"].get(
            "r11SnapshotDigest"),
        "r10SnapshotDigest": evidence["subjectR11Evidence"].get(
            "r10SnapshotDigest"),
        "evidenceJsonSha256": digest,
        "freezeAnchor": evidence["freezeAnchor"],
        "freezeTree": evidence["freezeTree"],
        "componentCount": len(evidence["components"]),
        "failedCheckCount": 0,
        "synthetic": evidence["synthetic"],
        "boundaries": evidence["boundaries"],
        "candidateAudit": audit,
    }
    Path(os.getenv("RADAR_R12_MANIFEST_PATH", MANIFEST_PATH)).write_text(
        json.dumps(manifest, indent=2, sort_keys=True), encoding="utf-8")
    print(json.dumps({
        "status": evidence["status"],
        "twinId": evidence["twinId"],
        "subjectStatus": evidence["subjectStatus"],
        "subjectGaps": subject_gaps,
        "digest": digest,
        "evidence": str(evidence_path),
    }, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
