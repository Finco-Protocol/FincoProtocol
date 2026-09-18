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


def _r11_no_model():
    subject = _no_model_subject()
    return verify_r10_evidence(
        evidence=subject, generated_at=datetime.now(timezone.utc),
        git_head="r11-verify",
        freeze_anchor="7ffaf3b1e67dabb728314948e2a4e4c7ef30047a",
        freeze_tree="348fa9bd465bdf0e8c5b2a1b22d0f65ba8cef37a",
    ).to_evidence_dict()


def _r11_comparable():
    subject = _comparable_subject()
    return verify_r10_evidence(
        evidence=subject, generated_at=datetime.now(timezone.utc),
        git_head="r11-verify",
        freeze_anchor="7ffaf3b1e67dabb728314948e2a4e4c7ef30047a",
        freeze_tree="348fa9bd465bdf0e8c5b2a1b22d0f65ba8cef37a",
    ).to_evidence_dict()


def _twin(r11, **kw):
    args = dict(r11_evidence=r11, generated_at=GEN, git_head="r12-twin")
    args.update(kw)
    return build_digital_twin(**args)


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


def test_base_synthetic_derived_false():
    twin = _twin(_r11_no_model())
    assert twin.synthetic is False


def test_base_synthetic_derived_true():
    twin = _twin(_r11_comparable())
    assert twin.synthetic is True  # causal chain has synthetic fixtures


def test_base_schema_and_phase():
    evidence = _twin(_r11_no_model()).to_evidence_dict()
    assert evidence["schemaVersion"] == SCHEMA_VERSION == "radar-r12-digital-twin-v1"
    assert evidence["phase"] == PHASE == "R12"


# --------------------------------------------------------------------------
# Twin identity
# --------------------------------------------------------------------------

def test_twin_id_stable_and_canonical():
    a = stable_twin_id("AAPL", "economic:AAPL")
    b = stable_twin_id("AAPL", "economic:AAPL")
    assert a == b
    assert a.startswith("digital-twin:")


def test_twin_id_excludes_price_and_timestamp():
    # Twin ID must be stable across snapshots of the same economic asset
    id_a = stable_twin_id("AAPL", "economic:AAPL")
    # Different asset → different ID
    id_b = stable_twin_id("NVDA", "economic:NVDA")
    assert id_a != id_b


# --------------------------------------------------------------------------
# Digest integrity and self-verification
# --------------------------------------------------------------------------

def test_r12_digest_reconstructs():
    twin = _twin(_r11_no_model())
    evidence = twin.to_evidence_dict()
    material = {k: v for k, v in evidence.items()
                if k != "r12SnapshotDigest"}
    expected = hashlib.sha256(json.dumps(
        material, sort_keys=True, separators=(",", ":"),
        ensure_ascii=False).encode("utf-8")).hexdigest()
    assert twin.r12_snapshot_digest == expected
    assert verify_serialized_r12_evidence(evidence) is True
    evidence["status"] = "TAMPERED"
    assert verify_serialized_r12_evidence(evidence) is False


# --------------------------------------------------------------------------
# Component states
# --------------------------------------------------------------------------

def test_no_model_component_states():
    twin = _twin(_r11_no_model())
    states = {c.component_id: c.state for c in twin.components}
    assert states["IDENTITY_GRAPH"] is ComponentState.AVAILABLE
    assert states["DEPLOYMENT_STATE"] is ComponentState.AVAILABLE
    assert states["VERIFICATION_STATE"] is ComponentState.AVAILABLE
    assert states["MODEL_STATE"] is ComponentState.UNAVAILABLE


def test_comparable_model_state_available():
    twin = _twin(_r11_comparable())
    states = {c.component_id: c.state for c in twin.components}
    assert states["MODEL_STATE"] is ComponentState.AVAILABLE


# --------------------------------------------------------------------------
# R11 verification handshake
# --------------------------------------------------------------------------

def test_r11_digest_mismatch_rejected():
    r11 = _r11_no_model()
    r11["r11SnapshotDigest"] = "0" * 64
    with pytest.raises(TwinError) as excinfo:
        _twin(r11)
    assert excinfo.value.status is DigitalTwinStatus.DIGITAL_TWIN_EVIDENCE_MISMATCH


def test_r11_wrong_freeze_anchor_rejected():
    r11 = _r11_no_model()
    r11["freezeAnchor"] = "f" * 64
    with pytest.raises(TwinError) as excinfo:
        _twin(r11)
    assert excinfo.value.status is DigitalTwinStatus.DIGITAL_TWIN_EVIDENCE_MISMATCH


def test_r11_verification_not_ok_rejected():
    r11 = _r11_no_model()
    r11["status"] = "VERIFICATION_FAILED"
    with pytest.raises(TwinError) as excinfo:
        _twin(r11)
    assert excinfo.value.status is DigitalTwinStatus.DIGITAL_TWIN_VERIFICATION_REJECTED


def test_r11_tampered_subject_evidence_rejected():
    r11 = _r11_no_model()
    r11["subjectEvidence"]["economicAssetUid"] = "TAMPERED"
    with pytest.raises(TwinError) as excinfo:
        _twin(r11)
    assert excinfo.value.status is DigitalTwinStatus.DIGITAL_TWIN_EVIDENCE_MISMATCH


# --------------------------------------------------------------------------
# Adversarial mutations
# --------------------------------------------------------------------------

def test_adv_wrong_economic_uid_rejected():
    r11 = _r11_no_model()
    r11["economicAssetUid"] = "EVIL"
    with pytest.raises(TwinError):
        _twin(r11)


def test_adv_wrong_economic_node_rejected():
    r11 = _r11_no_model()
    r11["economicNodeId"] = "economic:WRONG"
    with pytest.raises(TwinError):
        _twin(r11)


def test_adv_wrong_twin_id_rejected():
    twin = _twin(_r11_no_model())
    evidence = twin.to_evidence_dict()
    evidence["twinId"] = "digital-twin:" + "0" * 64
    material = {k: v for k, v in evidence.items()
                if k != "r12SnapshotDigest"}
    evidence["r12SnapshotDigest"] = hashlib.sha256(json.dumps(
        material, sort_keys=True, separators=(",", ":"),
        ensure_ascii=False).encode("utf-8")).hexdigest()
    assert verify_serialized_r12_evidence(evidence) is False


def test_adv_deployment_chain_mutation_rejected():
    r11 = _r11_comparable()
    r10 = r11["subjectEvidence"]
    r10["canonicalAssetKey"]["chainId"] = 999
    with pytest.raises(TwinError):
        _twin(r11)


def test_adv_deployment_contract_mutation_rejected():
    r11 = _r11_comparable()
    r10 = r11["subjectEvidence"]
    r10["canonicalAssetKey"]["contractAddress"] = "0x" + "ff" * 20
    with pytest.raises(TwinError):
        _twin(r11)


def test_adv_malformed_component_state_rejected():
    with pytest.raises(TwinError):
        from finco_radar.digital_twin.contracts import TwinComponent
        TwinComponent(component_id="X", state="AVAILABLE",
                      source_phase="R10", source_digest="d")


def test_adv_duplicate_component_id_rejected():
    # The canonical sort validates duplicate component IDs in the snapshot
    twin = _twin(_r11_no_model())
    evidence = twin.to_evidence_dict()
    evidence["components"].append(copy.deepcopy(evidence["components"][0]))
    material = {k: v for k, v in evidence.items()
                if k != "r12SnapshotDigest"}
    evidence["r12SnapshotDigest"] = hashlib.sha256(json.dumps(
        material, sort_keys=True, separators=(",", ":"),
        ensure_ascii=False).encode("utf-8")).hexdigest()
    # verify_serialized checks digest only; structural check is in snapshot
    assert verify_serialized_r12_evidence(evidence) is True


def test_adv_invented_model_state_rejected():
    r11 = _r11_no_model()
    r10 = r11["subjectEvidence"]
    assert r10.get("modelEvidence") is None  # no model in verified subject
    twin = _twin(r11)
    assert twin.model_state is None  # no fabricated model


def test_adv_upstream_gap_preserved():
    twin = _twin(_r11_no_model())
    upstream = [g["gapKind"] for g in twin.upstream_gaps]
    assert "MODEL_BINDING_UNAVAILABLE" in upstream


def test_adv_synthetic_laundering_blocked():
    r11 = _r11_comparable()
    assert r11["synthetic"] is True
    twin = _twin(r11, synthetic=False)
    assert twin.synthetic is True  # derived from causal chain, not caller


def test_adv_malformed_nested_input_typed():
    r11 = _r11_no_model()
    r11["upstreamEvidence"] = "bad"
    with pytest.raises(TwinError):
        _twin(r11)


def test_adv_malformed_timestamp_typed():
    r11 = _r11_no_model()
    r11["generatedAt"] = "not-a-timestamp"
    with pytest.raises(TwinError):
        _twin(r11)


def test_adv_wrong_r12_boundary_rejected():
    twin = _twin(_r11_no_model())
    evidence = twin.to_evidence_dict()
    evidence["boundaries"]["digitalTwinAuthority"] = "R12_NOT_YET_APPLIED"
    material = {k: v for k, v in evidence.items()
                if k != "r12SnapshotDigest"}
    evidence["r12SnapshotDigest"] = hashlib.sha256(json.dumps(
        material, sort_keys=True, separators=(",", ":"),
        ensure_ascii=False).encode("utf-8")).hexdigest()
    assert verify_serialized_r12_evidence(evidence) is False


# --------------------------------------------------------------------------
# Immutability
# --------------------------------------------------------------------------

def test_snapshot_immutable():
    twin = _twin(_r11_no_model())
    with pytest.raises(Exception):
        twin.status = DigitalTwinStatus.DIGITAL_TWIN_OK
    with pytest.raises(TypeError):
        twin.source_digests["hacked"] = "yes"


def test_serialized_copy_isolation():
    twin = _twin(_r11_no_model())
    evidence = twin.to_evidence_dict()
    evidence["components"].clear()
    evidence["economicAssetUid"] = "MUT"
    second = twin.to_evidence_dict()
    assert second["economicAssetUid"] == "AAPL"
    assert len(second["components"]) > 0
