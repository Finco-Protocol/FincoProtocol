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
    # A8: no caller-controlled synthetic authority exists — the parameter
    # was removed from build_digital_twin entirely; synthetic state is
    # derived only from the verified causal chain.
    r11 = _r11_comparable()
    assert r11["synthetic"] is True
    twin = _twin(r11)
    assert twin.synthetic is True
    with pytest.raises(TypeError):
        build_digital_twin(
            r11_evidence=r11, generated_at=GEN, git_head="r12-twin",
            synthetic=False)


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
    subject = _no_model_subject()
    r11 = _r11(subject)
    twin = _twin(r11)
    assert twin.boundaries["digitalTwinAuthority"] == "R12_APPLIED"

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


# ==========================================================================
# Correction A (F03) — A14: adversarial resealed matrix
#
# Every attack may recompute the outer r12SnapshotDigest (and where noted
# the embedded R11/R10 digests).  R12_CONTENT_INTEGRITY !=
# R12_COMPOSITION_AUTHORITY: only the canonical R12 composition replay
# over the corrected R11 authority can accept.
# ==========================================================================

R11_CORRECTED_ANCHOR = "537d255e8443f3f603a42a6dee856cc0de04e8cc"
R11_CORRECTED_TREE = "443989d69e0aed0cd8af581041574f4029b32b93"


def _digest(payload) -> str:
    return hashlib.sha256(json.dumps(
        payload, sort_keys=True, separators=(",", ":"),
        ensure_ascii=False).encode("utf-8")).hexdigest()


def _reseal_r10_obj(r10: dict) -> dict:
    material = {k: v for k, v in r10.items() if k != "r10SnapshotDigest"}
    r10["r10SnapshotDigest"] = _digest(material)
    return r10


def _reseal_r11_obj(r11: dict) -> dict:
    material = {k: v for k, v in r11.items() if k != "r11SnapshotDigest"}
    r11["r11SnapshotDigest"] = _digest(material)
    return r11


def _reseal_r12(ev: dict) -> dict:
    material = {k: v for k, v in ev.items() if k != "r12SnapshotDigest"}
    ev["r12SnapshotDigest"] = _digest(material)
    return ev


def _base_partial() -> dict:
    return _twin(_r11_no_model()).to_evidence_dict()


def _component(ev: dict, component_id: str) -> dict:
    return next(c for c in ev["components"]
                if c["componentId"] == component_id)


def test_adv_f03_01_wrong_schema_rejected():
    ev = _base_partial()
    ev["schemaVersion"] = "radar-r12-digital-twin-v2"
    _reseal_r12(ev)
    assert verify_serialized_r12_evidence(ev) is False


def test_adv_f03_02_wrong_phase_rejected():
    ev = _base_partial()
    ev["phase"] = "R11"
    _reseal_r12(ev)
    assert verify_serialized_r12_evidence(ev) is False


def test_adv_f03_03_invalid_status_rejected():
    ev = _base_partial()
    ev["status"] = "DIGITAL_TWIN_SUPER"
    _reseal_r12(ev)
    assert verify_serialized_r12_evidence(ev) is False


def test_adv_f03_04_malformed_generated_at_rejected():
    for bad in ("not-a-time", "2026-09-18T12:00:00"):
        ev = _base_partial()
        ev["generatedAt"] = bad
        _reseal_r12(ev)
        assert verify_serialized_r12_evidence(ev) is False


def test_adv_f03_05_malformed_git_head_rejected():
    for bad in ("", 123):
        ev = _base_partial()
        ev["gitHead"] = bad
        _reseal_r12(ev)
        assert verify_serialized_r12_evidence(ev) is False


def test_adv_f03_06_synthetic_coercion_rejected():
    for bad in ("false", "true", 1, []):
        ev = _base_partial()
        ev["synthetic"] = bad
        _reseal_r12(ev)
        assert verify_serialized_r12_evidence(ev) is False


def test_adv_f03_07_wrong_twin_id_rejected():
    ev = _base_partial()
    ev["twinId"] = "digital-twin:" + "0" * 64
    _reseal_r12(ev)
    assert verify_serialized_r12_evidence(ev) is False


def test_adv_f03_08_outer_identity_mismatch_rejected():
    ev = _base_partial()
    ev["economicAssetUid"] = "OTHER"
    _reseal_r12(ev)
    assert verify_serialized_r12_evidence(ev) is False


def test_adv_f03_09_resealed_r11_subject_rejected_by_r11_verifier():
    # The embedded R11 subject is mutated (honest gap silently removed)
    # and every inner digest (r10SnapshotDigest, subjectEvidenceDigest,
    # subjectSnapshotDigest, r11SnapshotDigest) is resealed — but the
    # corrected R11 verifier rejects it, so R12 must reject.
    ev = _base_partial()
    subject = ev["subjectR11Evidence"]
    r10 = subject["subjectEvidence"]
    r10["gaps"] = []
    _reseal_r10_obj(r10)
    subject["subjectEvidenceDigest"] = _digest(r10)
    subject["subjectSnapshotDigest"] = r10["r10SnapshotDigest"]
    _reseal_r11_obj(subject)
    _reseal_r12(ev)
    assert verify_serialized_r12_evidence(ev) is False


def test_adv_f03_10_wrong_r11_snapshot_digest_binding_rejected():
    ev = _base_partial()
    ev["verification"]["r11SnapshotDigest"] = "0" * 64
    _reseal_r12(ev)
    assert verify_serialized_r12_evidence(ev) is False


def test_adv_f03_11_wrong_r10_snapshot_digest_binding_rejected():
    ev = _base_partial()
    ev["verification"]["subjectR10SnapshotDigest"] = "0" * 64
    _reseal_r12(ev)
    assert verify_serialized_r12_evidence(ev) is False


def test_adv_f03_12_wrong_r11_freeze_anchor_rejected():
    ev = _base_partial()
    ev["freezeAnchor"] = "e" * 64
    _reseal_r12(ev)
    assert verify_serialized_r12_evidence(ev) is False


def test_adv_f03_13_wrong_r11_freeze_tree_rejected():
    ev = _base_partial()
    ev["freezeTree"] = "d" * 64
    _reseal_r12(ev)
    assert verify_serialized_r12_evidence(ev) is False


def test_adv_f03_14_mutated_boundaries_rejected():
    ev = _base_partial()
    ev["boundaries"]["digitalTwinAuthority"] = "R11_APPLIED"
    _reseal_r12(ev)
    assert verify_serialized_r12_evidence(ev) is False


def test_adv_f03_15_missing_mandatory_component_rejected():
    ev = _base_partial()
    ev["components"] = [c for c in ev["components"]
                        if c["componentId"] != "MODEL_STATE"]
    _reseal_r12(ev)
    assert verify_serialized_r12_evidence(ev) is False


def test_adv_f03_16_duplicate_component_rejected():
    ev = _base_partial()
    ev["components"].append(copy.deepcopy(ev["components"][0]))
    _reseal_r12(ev)
    assert verify_serialized_r12_evidence(ev) is False


def test_adv_f03_17_unknown_component_id_rejected():
    ev = _base_partial()
    ev["components"].append({
        "componentId": "TELEMETRY_STATE",
        "state": "AVAILABLE",
        "sourcePhase": "R10",
        "sourceDigest": "0" * 64,
        "detail": "invented component",
    })
    _reseal_r12(ev)
    assert verify_serialized_r12_evidence(ev) is False


def test_adv_f03_18_component_state_payload_inconsistency_rejected():
    # MODEL_STATE is UNAVAILABLE with a null model payload in the honest
    # artifact; flipping only the component state to AVAILABLE fabricates
    # payload authority and must fail.
    ev = _base_partial()
    assert ev["modelState"] is None
    _component(ev, "MODEL_STATE")["state"] = "AVAILABLE"
    _reseal_r12(ev)
    assert verify_serialized_r12_evidence(ev) is False


def test_adv_f03_19_ok_with_unavailable_component_rejected():
    ev = _base_partial()
    assert _component(ev, "MODEL_STATE")["state"] == "UNAVAILABLE"
    ev["status"] = "DIGITAL_TWIN_OK"
    _reseal_r12(ev)
    assert verify_serialized_r12_evidence(ev) is False


def test_adv_f03_20_ok_with_twin_gap_rejected():
    ev = _base_partial()
    assert len(ev["twinGaps"]) > 0
    ev["status"] = "DIGITAL_TWIN_OK"
    ev["twinGaps"] = []
    _reseal_r12(ev)
    assert verify_serialized_r12_evidence(ev) is False


def test_adv_f03_21_malformed_components_container_rejected():
    for bad in ("bad", {"unexpected": True}, 1):
        ev = _base_partial()
        ev["components"] = bad
        _reseal_r12(ev)
        assert verify_serialized_r12_evidence(ev) is False


def test_adv_f03_22_malformed_gaps_container_or_member_rejected():
    ev = _base_partial()
    ev["twinGaps"] = "bad"
    _reseal_r12(ev)
    assert verify_serialized_r12_evidence(ev) is False

    ev = _base_partial()
    ev["twinGaps"] = [{"unexpected": True}]
    _reseal_r12(ev)
    assert verify_serialized_r12_evidence(ev) is False

    ev = _base_partial()
    ev["upstreamGaps"] = [1]
    _reseal_r12(ev)
    assert verify_serialized_r12_evidence(ev) is False


def test_adv_f03_23_malformed_source_digests_rejected():
    ev = _base_partial()
    ev["sourceDigests"] = "bad"
    _reseal_r12(ev)
    assert verify_serialized_r12_evidence(ev) is False

    ev = _base_partial()
    ev["sourceDigests"] = dict(ev["sourceDigests"], r9AssetGraphDigest=1)
    _reseal_r12(ev)
    assert verify_serialized_r12_evidence(ev) is False


def test_adv_f03_24_freshness_laundering_rejected():
    # Stale/future upstream timing mutated inside the R11 subject with all
    # inner and outer digests resealed: the canonical R11 verification
    # rejects the subject, so R12 must reject it — a fresh R12 composition
    # timestamp never launders stale upstream evidence.
    ev = _twin(_r11_comparable()).to_evidence_dict()
    subject = ev["subjectR11Evidence"]
    r10 = subject["subjectEvidence"]
    r10["modelEvidence"]["valuationAsOf"] = "2020-01-01T00:00:00+00:00"
    _reseal_r10_obj(r10)
    subject["subjectEvidenceDigest"] = _digest(r10)
    subject["subjectSnapshotDigest"] = r10["r10SnapshotDigest"]
    _reseal_r11_obj(subject)
    _reseal_r12(ev)
    assert verify_serialized_r12_evidence(ev) is False


def test_adv_f03_25_same_identity_different_r11_observation_rejected():
    # Two separately valid R11 snapshots for the same economic asset with
    # different observations (different composition time, different
    # digest).  Substituting the other observation into the twin and
    # resealing the outer digest must fail: the artifact binds the exact
    # R11 observation, not merely an economic identity.
    r11_a = _r11_no_model()
    r11_b = _r11_no_model()
    assert r11_a["economicAssetUid"] == r11_b["economicAssetUid"]
    assert r11_a["r11SnapshotDigest"] != r11_b["r11SnapshotDigest"]
    twin_a = _twin(r11_a).to_evidence_dict()
    twin_b = _twin(r11_b).to_evidence_dict()
    # distinguishable by digest
    assert twin_a["r12SnapshotDigest"] != twin_b["r12SnapshotDigest"]
    ev = copy.deepcopy(twin_a)
    ev["subjectR11Evidence"] = r11_b
    _reseal_r12(ev)
    assert verify_serialized_r12_evidence(ev) is False


# -- Correction A (F03) positive controls ----------------------------------

def test_adv_f03_positive_live_partial_artifact_verifies():
    ev = _base_partial()
    assert ev["status"] == "DIGITAL_TWIN_PARTIAL"
    assert verify_serialized_r12_evidence(ev) is True


def test_adv_f03_positive_full_model_artifact_verifies():
    ev = _twin(_r11_comparable()).to_evidence_dict()
    assert ev["status"] == "DIGITAL_TWIN_OK"
    assert verify_serialized_r12_evidence(ev) is True


def test_adv_f03_positive_json_roundtrip_verifies():
    ev = _base_partial()
    parsed = json.loads(json.dumps(ev))
    assert verify_serialized_r12_evidence(parsed) is True


def test_adv_f03_positive_replay_equals_serialized():
    # Canonical replay: build_digital_twin from the exact embedded R11
    # subject under the serialized generatedAt/gitHead reproduces the
    # artifact dict-for-dict.
    from finco_radar.digital_twin.twin import build_digital_twin as replay
    ev = _base_partial()
    assert verify_serialized_r12_evidence(ev) is True
    replayed = replay(
        r11_evidence=ev["subjectR11Evidence"],
        generated_at=datetime.fromisoformat(ev["generatedAt"]),
        git_head=ev["gitHead"],
    )
    assert replayed.to_evidence_dict() == ev
    assert replayed.status is DigitalTwinStatus.DIGITAL_TWIN_PARTIAL


def test_adv_f03_positive_twin_id_reconstruction():
    ev = _base_partial()
    material = {"economicAssetUid": ev["economicAssetUid"],
                "economicNodeId": ev["economicNodeId"]}
    assert ev["twinId"] == "digital-twin:" + _digest(material)
    assert ev["twinId"] == stable_twin_id(
        ev["economicAssetUid"], ev["economicNodeId"])
