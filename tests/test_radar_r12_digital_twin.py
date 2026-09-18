"""Focused, fully offline R12 Digital Twin tests."""
from __future__ import annotations

import copy
import hashlib
import json
from datetime import datetime, timedelta, timezone
from decimal import Decimal

import pytest

from test_radar_r10_model_radar import (
    EXEC_PRICES, FULL, NOW, POLICY, _chain, _model,
)
from finco_radar.model_radar.bridge import build_model_radar_snapshot
from finco_radar.verification.verifier import verify_r10_evidence
from finco_radar.digital_twin.contracts import (
    TwinError,
    ComponentState,
    DigitalTwinStatus,
    PHASE,
    SCHEMA_VERSION,
    TwinGapKind,
    stable_twin_id,
    verify_serialized_r12_evidence,
)
from finco_radar.digital_twin.twin import build_digital_twin

T = timezone.utc
GEN = datetime(2026, 9, 18, 12, 0, tzinfo=T)
R10_ANCHOR = "7ffaf3b1e67dabb728314948e2a4e4c7ef30047a"
R10_TREE = "fba9d76d9dceee35d079563b115fdde90c40bd46"


def _comparable_subject():
    r9, r8 = _chain(**FULL)
    return build_model_radar_snapshot(
        r9_evidence=r9, r8_evidence=r8,
        model_evidence=_model(value=Decimal("100")),
        timing_policy=POLICY, now=NOW, git_head="r10-subject",
        synthetic=False).to_evidence_dict()


def _no_model_subject():
    r9, r8 = _chain(**FULL)
    return build_model_radar_snapshot(
        r9_evidence=r9, r8_evidence=r8, model_evidence=None,
        timing_policy=POLICY, now=NOW, git_head="r10-subject",
        synthetic=False).to_evidence_dict()


def _r11(subject):
    return verify_r10_evidence(
        evidence=subject, generated_at=datetime.now(timezone.utc),
        git_head="r11-verify", freeze_anchor=R10_ANCHOR,
        freeze_tree=R10_TREE).to_evidence_dict()


def _r11_comparable():
    return _r11(_comparable_subject())


def _r11_no_model():
    return _r11(_no_model_subject())


def _twin(r11, **kw):
    args = dict(r11_evidence=r11, generated_at=GEN, git_head="r12-twin")
    args.update(kw)
    return build_digital_twin(**args)


# ---- Positive baselines ----

def test_base_no_model_partial():
    twin = _twin(_r11_no_model())
    assert twin.status is DigitalTwinStatus.DIGITAL_TWIN_PARTIAL
    assert twin.twin_id.startswith("digital-twin:")
    assert twin.economic_asset_uid == "AAPL"
    assert twin.economic_node_id == "economic:AAPL"


def test_base_comparable_ok():
    twin = _twin(_r11_comparable())
    assert twin.status is DigitalTwinStatus.DIGITAL_TWIN_OK
    assert twin.twin_id.startswith("digital-twin:")


def test_base_synthetic_false():
    twin = _twin(_r11_no_model())
    assert twin.synthetic is True  # synthetic fixture chain derives true


def test_base_synthetic_true():
    twin = _twin(_r11_comparable())
    assert twin.synthetic is True


def test_base_schema_and_phase():
    ev = _twin(_r11_no_model()).to_evidence_dict()
    assert ev["schemaVersion"] == SCHEMA_VERSION == "radar-r12-digital-twin-v1"
    assert ev["phase"] == PHASE == "R12"


def test_base_boundaries():
    b = _twin(_r11_no_model()).to_evidence_dict()["boundaries"]
    assert b["modelAuthority"] == "R10_APPLIED"
    assert b["verificationAuthority"] == "R11_APPLIED"
    assert b["digitalTwinAuthority"] == "R12_APPLIED"


# ---- Twin identity ----

def test_twin_id_stable():
    assert stable_twin_id("AAPL", "economic:AAPL") == stable_twin_id("AAPL", "economic:AAPL")
    assert stable_twin_id("AAPL", "economic:AAPL").startswith("digital-twin:")
    assert stable_twin_id("AAPL", "economic:AAPL") != stable_twin_id("NVDA", "economic:NVDA")


# ---- Digest integrity ----

def test_r12_digest_reconstructs():
    twin = _twin(_r11_no_model())
    ev = twin.to_evidence_dict()
    mat = {k: v for k, v in ev.items() if k != "r12SnapshotDigest"}
    expected = hashlib.sha256(json.dumps(
        mat, sort_keys=True, separators=(",", ":"),
        ensure_ascii=False).encode("utf-8")).hexdigest()
    assert twin.r12_snapshot_digest == expected
    assert verify_serialized_r12_evidence(ev) is True
    ev["status"] = "TAMPERED"
    assert verify_serialized_r12_evidence(ev) is False


# ---- Component states ----

def test_no_model_component_states():
    twin = _twin(_r11_no_model())
    states = {c.component_id: c.state for c in twin.components}
    assert states["IDENTITY_GRAPH"] is ComponentState.AVAILABLE
    assert states["DEPLOYMENT_STATE"] is ComponentState.AVAILABLE
    assert states["VERIFICATION_STATE"] is ComponentState.AVAILABLE
    assert states["MODEL_STATE"] is ComponentState.UNAVAILABLE
    assert states["REFERENCE_STATE"] is ComponentState.AVAILABLE
    assert states["EXECUTION_STATE"] is ComponentState.AVAILABLE


def test_comparable_model_state_available():
    twin = _twin(_r11_comparable())
    states = {c.component_id: c.state for c in twin.components}
    assert states["MODEL_STATE"] is ComponentState.AVAILABLE


# ---- R11 verification handshake ----

def test_r11_digest_mismatch_rejected():
    r11 = _r11_no_model()
    r11["r11SnapshotDigest"] = "0" * 64
    with pytest.raises(TwinError) as exc_info:
        _twin(r11)
    assert exc_info.value.status is DigitalTwinStatus.DIGITAL_TWIN_EVIDENCE_MISMATCH


def test_r11_verification_not_ok_rejected():
    r11 = _r11_no_model()
    r11["status"] = "VERIFICATION_FAILED"
    # Reseal the R11 snapshot digest so the digest check passes and the
    # VERIFICATION_REJECTED status check fires instead.
    material = {k: v for k, v in r11.items() if k != "r11SnapshotDigest"}
    r11["r11SnapshotDigest"] = hashlib.sha256(json.dumps(
        material, sort_keys=True, separators=(",", ":"),
        ensure_ascii=False).encode("utf-8")).hexdigest()
    with pytest.raises(TwinError) as exc_info:
        _twin(r11)
    assert exc_info.value.status is DigitalTwinStatus.DIGITAL_TWIN_VERIFICATION_REJECTED


def test_r11_wrong_freeze_anchor_rejected():
    r11 = _r11_no_model()
    r11["freezeAnchor"] = "f" * 64
    with pytest.raises(TwinError) as exc_info:
        _twin(r11)
    assert exc_info.value.status is DigitalTwinStatus.DIGITAL_TWIN_EVIDENCE_MISMATCH


def test_r11_tampered_subject_evidence_rejected():
    r11 = _r11_no_model()
    r11["subjectEvidence"]["economicAssetUid"] = "TAMPERED"
    with pytest.raises(TwinError) as exc_info:
        _twin(r11)
    assert exc_info.value.status is DigitalTwinStatus.DIGITAL_TWIN_EVIDENCE_MISMATCH


# ---- Adversarial ----

def test_adv_wrong_economic_uid():
    r11 = _r11_no_model()
    r11["economicAssetUid"] = "EVIL"
    with pytest.raises(TwinError):
        _twin(r11)


def test_adv_synthetic_laundering_blocked():
    r11 = _r11_comparable()
    assert r11["synthetic"] is True
    twin = _twin(r11, synthetic=False)
    assert twin.synthetic is True


def test_adv_malformed_nested_typed():
    r11 = _r11_no_model()
    r11["upstreamEvidence"] = "bad"
    with pytest.raises(TwinError):
        _twin(r11)


def test_adv_upstream_gap_preserved():
    twin = _twin(_r11_no_model())
    upstream = [g["gapKind"] for g in twin.upstream_gaps]
    assert "MODEL_BINDING_UNAVAILABLE" in upstream


def test_adv_wrong_r12_boundary_rejected():
    twin = _twin(_r11_no_model())
    ev = twin.to_evidence_dict()
    ev["boundaries"]["digitalTwinAuthority"] = "R12_NOT_YET_APPLIED"
    mat = {k: v for k, v in ev.items() if k != "r12SnapshotDigest"}
    ev["r12SnapshotDigest"] = hashlib.sha256(json.dumps(
        mat, sort_keys=True, separators=(",", ":"),
        ensure_ascii=False).encode("utf-8")).hexdigest()
    assert verify_serialized_r12_evidence(ev) is False


# ---- Immutability ----

def test_snapshot_immutable():
    twin = _twin(_r11_no_model())
    with pytest.raises(Exception):
        twin.status = DigitalTwinStatus.DIGITAL_TWIN_OK


def test_serialized_copy_isolation():
    twin = _twin(_r11_no_model())
    ev = twin.to_evidence_dict()
    ev["economicAssetUid"] = "MUT"
    ev2 = twin.to_evidence_dict()
    assert ev2["economicAssetUid"] == "AAPL"
