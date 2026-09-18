"""Networked R10 proof: FINCO MODEL × RADAR from the frozen R9/R8 chain.

The live proof re-derives the frozen R1→R8 live composition (embedded R9
asset graph) and then honestly discovers whether a legitimate model binding
exists for the live economic asset.  The repository contains no source-proven
model binding for the live asset, so the expected — and PASSING — outcome is:

    status = MODEL_RADAR_PARTIAL
    gaps   = [MODEL_BINDING_UNAVAILABLE, ...honest reference gaps]

R10 never fabricates a valuation to make the artifact appear complete.
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
from finco_radar.r9.live_proof import build_graph_from_upstream as build_r9_evidence
from finco_radar.r8.live_proof import _build_live_snapshot as _build_r8_live_snapshot

EVIDENCE_PATH = "artifacts/radar_r10_model_radar_evidence.json"
SHA256_PATH = "artifacts/radar_r10_model_radar_evidence.sha256"
MANIFEST_PATH = "artifacts/radar_r10_model_radar_manifest.json"

R10_MAX_MODEL_AGE_SECONDS = Decimal("900")
R10_MAX_MODEL_MARKET_SKEW_SECONDS = Decimal("300")


def main() -> int:
    r8_evidence, audit = _build_r8_live_snapshot()
    r9_evidence = build_r9_evidence(
        r8_evidence=r8_evidence,
        git_head=r8_evidence["gitHead"],
        generated_at=datetime.now(timezone.utc),
    )
    snapshot = build_model_radar_snapshot(
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
    evidence = snapshot.to_evidence_dict()
    first = json.dumps(evidence, indent=2, sort_keys=True, ensure_ascii=False)
    second = json.dumps(json.loads(first), indent=2, sort_keys=True, ensure_ascii=False)
    if first != second:
        raise RuntimeError("R10 evidence serialization is not byte-deterministic")
    evidence_path = Path(os.getenv("RADAR_R10_EVIDENCE_PATH", EVIDENCE_PATH))
    evidence_path.parent.mkdir(parents=True, exist_ok=True)
    evidence_path.write_text(first + "\n", encoding="utf-8")
    digest = hashlib.sha256(evidence_path.read_bytes()).hexdigest()
    Path(os.getenv("RADAR_R10_SHA256_PATH", SHA256_PATH)).write_text(
        f"{digest}  {evidence_path.name}\n", encoding="utf-8"
    )
    gap_kinds = sorted(g["gapKind"] for g in evidence["gaps"])
    manifest = {
        "schemaVersion": evidence["schemaVersion"],
        "phase": evidence["phase"],
        "gitHead": evidence["gitHead"],
        "producedAt": evidence["generatedAt"],
        "status": evidence["status"],
        "economicAssetUid": evidence["economicAssetUid"],
        "economicNodeId": evidence["economicNodeId"],
        "modelBinding": evidence["modelBinding"],
        "gapKinds": gap_kinds,
        "r10SnapshotDigest": evidence["r10SnapshotDigest"],
        "evidenceJsonSha256": digest,
        "sourceDigests": evidence["sourceDigests"],
        "candidateAudit": audit,
        "note": (
            "No frozen FINCO model authority carries a source-proven model "
            "binding for the live Radar asset; MODEL_RADAR_PARTIAL with "
            "MODEL_BINDING_UNAVAILABLE is the honest, passing outcome. A "
            "model value is model evidence, not market truth."
        ),
    }
    Path(os.getenv("RADAR_R10_MANIFEST_PATH", MANIFEST_PATH)).write_text(
        json.dumps(manifest, indent=2, sort_keys=True), encoding="utf-8"
    )
    print(json.dumps({
        "status": evidence["status"],
        "economicAssetUid": evidence["economicAssetUid"],
        "gaps": gap_kinds,
        "digest": digest,
        "evidence": str(evidence_path),
    }, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
