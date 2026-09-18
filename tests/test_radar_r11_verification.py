"""Focused, fully offline R11 verification-authority tests.

R11 verifies the deterministic contract and lineage of serialized R10
evidence.  It does NOT attest economic truth.  An honest R10
MODEL_RADAR_PARTIAL subject verifies VERIFICATION_OK.
"""
from __future__ import annotations

import copy
import hashlib
import json
from datetime import datetime, timedelta, timezone
from decimal import Decimal

import pytest

from test_radar_r10_model_radar import (
    EXEC_PRICES, FULL, NOW, POLICY, _chain, _live_chain, _model,
)
from finco_radar.model_radar.bridge import build_model_radar_snapshot
from finco_radar.verification.contracts import (
    PHASE,
    SCHEMA_VERSION,
    CheckState,
    VerificationError,
    VerificationGapKind,
    VerificationStatus,
    canonical_sha256,
    verify_serialized_r11_evidence,
    verify_r11_snapshot_digest,
)
from finco_radar.verification.verifier import (
    derived_synthetic_flag,
    verify_r10_evidence,
)

T = timezone.utc
GENERATED = datetime(2026, 9, 18, 12, 0, tzinfo=T)
ANCHOR = "7ffaf3b1e67dabb728314948e2a4e4c7ef30047a"
TREE = "fba9d76d9dceee35d079563b115fdde90c40bd46"


def _subject(**chain_over):
    r9, r8 = _chain(**chain_over)
    return build_model_radar_snapshot(
        r9_evidence=r9, r8_evidence=r8, model_evidence=None,
        timing_policy=POLICY, now=NOW, git_head="r10-subject",
        synthetic=False).to_evidence_dict()


def _comparable_subject():
    r9, r8 = _chain(**FULL)
    return build_model_radar_snapshot(
        r9_evidence=r9, r8_evidence=r8,
        model_evidence=_model(value=Decimal("100")),
        timing_policy=POLICY, now=NOW, git_head="r10-subject",
        synthetic=False).to_evidence_dict()


def _verify(subject, **over):
    kwargs = dict(evidence=subject, generated_at=GENERATED, git_head="r11",
                  freeze_anchor=ANCHOR, freeze_tree=TREE)
    kwargs.update(over)
    return verify_r10_evidence(**kwargs)


def _check(snapshot, check_id):
    return next(c for c in snapshot.checks if c.check_id == check_id)


def _reseal_r10(subject: dict) -> dict:
    subject["r10SnapshotDigest"] = hashlib.sha256(json.dumps(
        {k: v for k, v in subject.items() if k != "r10SnapshotDigest"},
        sort_keys=True, separators=(",", ":"), ensure_ascii=False)
        .encode("utf-8")).hexdigest()
    return subject


def _reseal_chain(subject: dict, *, r9=False, r8=False, r7=False) -> dict:
    """Reseal the embedded lineage after in-place mutations (always innermost
    first), then reseal the R10 snapshot itself."""
    if r7:
        r7e = subject["upstreamEvidence"]["r8ExecutionEvidence"][
            "upstreamEvidence"]["r7CrossMarketEvidence"]
        r7e["r7SnapshotDigest"] = hashlib.sha256(json.dumps(
            {k: v for k, v in r7e.items() if k != "r7SnapshotDigest"},
            sort_keys=True, separators=(",", ":"), ensure_ascii=False)
            .encode("utf-8")).hexdigest()
        r8e = subject["upstreamEvidence"]["r8ExecutionEvidence"]
        r8e["sourceDigests"]["r7CrossMarketDigest"] = hashlib.sha256(
            json.dumps(r7e, sort_keys=True, separators=(",", ":"),
                       ensure_ascii=False).encode("utf-8")).hexdigest()
    if r8:
        r8e = subject["upstreamEvidence"]["r8ExecutionEvidence"]
        r8e["r8SnapshotDigest"] = hashlib.sha256(json.dumps(
            {k: v for k, v in r8e.items() if k != "r8SnapshotDigest"},
            sort_keys=True, separators=(",", ":"), ensure_ascii=False)
            .encode("utf-8")).hexdigest()
    if r9:
        r9e = subject["upstreamEvidence"]["r9AssetGraphEvidence"]
        r9e["r9SnapshotDigest"] = hashlib.sha256(json.dumps(
            {k: v for k, v in r9e.items() if k != "r9SnapshotDigest"},
            sort_keys=True, separators=(",", ":"), ensure_ascii=False)
            .encode("utf-8")).hexdigest()
    return _reseal_r10(subject)


# --------------------------------------------------------------------------
# Positive baselines
# --------------------------------------------------------------------------

def test_base_live_partial_subject_verifies_ok():
    snapshot = _verify(_subject())
    assert snapshot.status is VerificationStatus.VERIFICATION_OK
    assert snapshot.subject_status == "MODEL_RADAR_PARTIAL"
    assert snapshot.subject_snapshot_digest is not None
    assert [g["gapKind"] for g in snapshot.subject_gaps] == [
        "MODEL_BINDING_UNAVAILABLE"]
    assert snapshot.economic_asset_uid == "AAPL"
    assert snapshot.economic_node_id == "economic:AAPL"
    # the fixture causal chain is synthetic, so derived R11 synthetic is True
    assert snapshot.synthetic is True
    states = {c.check_id: c.state for c in snapshot.checks}
    assert states["HONEST_MISSING_MODEL"] is CheckState.PASS
    assert states["R10_SNAPSHOT_DIGEST"] is CheckState.PASS
    assert not any(s is CheckState.FAIL for s in states.values())


def test_base_fully_comparable_synthetic_subject_verifies_ok():
    snapshot = _verify(_comparable_subject())
    assert snapshot.status is VerificationStatus.VERIFICATION_OK
    assert snapshot.synthetic is True  # derived, never caller-claimed
    assert len(snapshot.execution_comparisons if False else [
        c for c in snapshot.checks
        if c.check_id == "EXECUTION_ARITHMETIC"]) == 1
    ref = _check(snapshot, "REFERENCE_ARITHMETIC")
    assert ref.state is CheckState.PASS
    assert _check(snapshot, "EXECUTION_ARITHMETIC").state is CheckState.PASS
    assert _check(snapshot, "EXECUTION_SOURCE_BINDING").state is CheckState.PASS
    assert _check(snapshot, "COMPARABILITY_CONTRACT").state is CheckState.PASS
    assert _check(snapshot, "MODEL_DIGESTS").state is CheckState.PASS


def test_base_live_chain_derives_synthetic_false():
    r9, r8 = _live_chain(**FULL)
    subject = build_model_radar_snapshot(
        r9_evidence=r9, r8_evidence=r8, model_evidence=None,
        timing_policy=POLICY, now=NOW, git_head="r10-subject",
        synthetic=False).to_evidence_dict()
    snapshot = _verify(subject)
    assert snapshot.synthetic is False
    assert snapshot.status is VerificationStatus.VERIFICATION_OK


def test_base_schema_and_phase():
    snapshot = _verify(_subject())
    evidence = snapshot.to_evidence_dict()
    assert evidence["schemaVersion"] == SCHEMA_VERSION == (
        "radar-r11-verification-v1")
    assert evidence["phase"] == PHASE == "R11"
    assert verify_serialized_r11_evidence(evidence) is True
    assert verify_r11_snapshot_digest(snapshot) is True


def test_base_boundaries():
    b = _verify(_subject()).to_evidence_dict()["boundaries"]
    assert b["modelAuthority"] == "R10_APPLIED"
    assert b["verificationAuthority"] == "R11_APPLIED"
    assert b["digitalTwinAuthority"] == "R12_NOT_YET_APPLIED"


def test_base_subject_boundary_not_mutated():
    subject = _subject()
    before = copy.deepcopy(subject["boundaries"])
    snapshot = _verify(subject)
    assert snapshot.to_evidence_dict()["subjectEvidence"]["boundaries"][
        "verificationAuthority"] == "R11_NOT_YET_APPLIED"
    assert subject["boundaries"] == before


# --------------------------------------------------------------------------
# 1-3: digest integrity
# --------------------------------------------------------------------------

def test_adv_01_one_character_digest_mutation_detected():
    subject = _subject()
    subject["r10SnapshotDigest"] = (
        "0" + subject["r10SnapshotDigest"][1:])
    snapshot = _verify(subject)
    assert snapshot.status is VerificationStatus.VERIFICATION_EVIDENCE_MISMATCH
    digest_check = _check(snapshot, "R10_SNAPSHOT_DIGEST")
    assert digest_check.state is CheckState.FAIL
    # The frozen-verifier crosscheck verifies AGREEMENT between the two
    # implementations; both reject the mutation, so agreement still holds.
    assert _check(snapshot,
                  "R10_SNAPSHOT_DIGEST_FROZEN_CROSSCHECK").state is CheckState.PASS


def test_adv_02_payload_mutation_with_stale_digest_detected():
    subject = _subject()
    subject["economicAssetUid"] = "MUT"
    snapshot = _verify(subject)
    assert snapshot.status is VerificationStatus.VERIFICATION_EVIDENCE_MISMATCH
    assert _check(snapshot, "R10_SNAPSHOT_DIGEST").state is CheckState.FAIL


def test_adv_03_resealed_wrong_uid_rejected():
    subject = _subject()
    subject["economicAssetUid"] = "EVIL"
    subject["economicNodeId"] = "economic:EVIL"
    _reseal_r10(subject)
    snapshot = _verify(subject)
    # digest reconstructs, but the R9 lineage no longer agrees: mismatch.
    assert snapshot.status is VerificationStatus.VERIFICATION_EVIDENCE_MISMATCH
    assert _check(snapshot, "R9_IDENTITY_CONSISTENCY").state is CheckState.FAIL


def test_adv_04_economic_node_mismatch_rejected():
    subject = _subject()
    subject["economicNodeId"] = "economic:WRONG"
    _reseal_r10(subject)
    snapshot = _verify(subject)
    assert snapshot.status is VerificationStatus.VERIFICATION_FAILED
    assert _check(snapshot, "SUBJECT_IDENTITY").state is CheckState.FAIL


# --------------------------------------------------------------------------
# 4-9: lineage and provenance
# --------------------------------------------------------------------------

def test_adv_05_wrong_embedded_r9_source_digest_detected():
    subject = _subject()
    subject["sourceDigests"]["r9AssetGraphDigest"] = "0" * 64
    _reseal_r10(subject)
    snapshot = _verify(subject)
    assert snapshot.status is VerificationStatus.VERIFICATION_EVIDENCE_MISMATCH
    assert _check(snapshot, "R9_SOURCE_DIGEST").state is CheckState.FAIL


def test_adv_06_r9_internal_snapshot_mutation_detected():
    subject = _subject()
    r9 = subject["upstreamEvidence"]["r9AssetGraphEvidence"]
    r9["economicAssetUid"] = "MUT"
    _reseal_chain(subject, r9=True)
    snapshot = _verify(subject)
    assert snapshot.status is VerificationStatus.VERIFICATION_EVIDENCE_MISMATCH
    # The internal digest was correctly resealed, so the mutation is caught
    # by the enclosing lineage: the R10-declared R9 source digest is stale.
    assert _check(snapshot, "R9_SNAPSHOT_DIGEST").state is CheckState.PASS
    assert _check(snapshot, "R9_SOURCE_DIGEST").state is CheckState.FAIL


def test_adv_07_unrelated_valid_r8_substituted_detected():
    subject = _subject()
    _, other_r8 = _chain(oracle_price="106", exec_prices=EXEC_PRICES)
    subject["upstreamEvidence"]["r8ExecutionEvidence"] = other_r8
    _reseal_chain(subject, r9=True)
    snapshot = _verify(subject)
    assert snapshot.status is VerificationStatus.VERIFICATION_EVIDENCE_MISMATCH
    assert _check(snapshot, "R8_SOURCE_DIGEST").state is CheckState.FAIL


def test_adv_08_missing_r8_detected():
    subject = _subject()
    subject["upstreamEvidence"].pop("r8ExecutionEvidence")
    _reseal_r10(subject)
    snapshot = _verify(subject)
    assert snapshot.status is VerificationStatus.VERIFICATION_EVIDENCE_MISMATCH
    assert _check(snapshot, "R8_SOURCE_DIGEST").state is CheckState.FAIL
    assert _check(snapshot, "R7_PROVENANCE").state is CheckState.FAIL


def test_adv_09_missing_r7_detected():
    subject = _subject()
    r8 = subject["upstreamEvidence"]["r8ExecutionEvidence"]
    r8["upstreamEvidence"].pop("r7CrossMarketEvidence")
    r8["sourceDigests"].pop("r7CrossMarketDigest", None)
    _reseal_chain(subject, r8=True)
    snapshot = _verify(subject)
    assert snapshot.status is VerificationStatus.VERIFICATION_EVIDENCE_MISMATCH
    assert _check(snapshot, "R7_PROVENANCE").state is CheckState.FAIL


def test_adv_10_malformed_synthetic_provenance_detected():
    for bad in (None, "false", 0):
        subject = _subject()
        subject["synthetic"] = bad
        _reseal_r10(subject)
        snapshot = _verify(subject)
        assert snapshot.status is VerificationStatus.VERIFICATION_FAILED
        assert _check(snapshot,
                      "SYNTHETIC_PROVENANCE").state is CheckState.FAIL


def test_adv_11_synthetic_laundering_blocked():
    subject = _comparable_subject()  # causal chain is synthetic
    assert derived_synthetic_flag(subject) is True
    snapshot = _verify(subject)
    assert snapshot.synthetic is True  # cannot be relabeled non-synthetic


def test_adv_12_subject_claiming_r11_applied_rejected():
    subject = _subject()
    subject["boundaries"]["verificationAuthority"] = "R11_APPLIED"
    _reseal_r10(subject)
    snapshot = _verify(subject)
    assert snapshot.status is VerificationStatus.VERIFICATION_FAILED
    assert _check(snapshot, "R10_BOUNDARY_CONTRACT").state is CheckState.FAIL


def test_adv_13_subject_claiming_r12_authority_rejected():
    subject = _subject()
    subject["boundaries"]["digitalTwinAuthority"] = "R12_APPLIED"
    _reseal_r10(subject)
    snapshot = _verify(subject)
    assert snapshot.status is VerificationStatus.VERIFICATION_FAILED
    assert _check(snapshot, "R10_BOUNDARY_CONTRACT").state is CheckState.FAIL


# --------------------------------------------------------------------------
# 14-21: model evidence integrity
# --------------------------------------------------------------------------

def _comparable_model_evidence(subject):
    return subject["modelEvidence"]


def test_adv_14_model_input_digest_mismatch_detected():
    subject = _comparable_subject()
    model = dict(subject["modelEvidence"])
    model["inputEvidence"] = dict(model["inputEvidence"], tampered="1")
    subject["modelEvidence"] = model
    _reseal_r10(subject)
    snapshot = _verify(subject)
    assert snapshot.status is VerificationStatus.VERIFICATION_FAILED
    assert _check(snapshot, "MODEL_DIGESTS").state is CheckState.FAIL


def test_adv_15_model_output_digest_mismatch_detected():
    subject = _comparable_subject()
    model = copy.deepcopy(subject["modelEvidence"])
    model["outputEvidence"] = dict(model["outputEvidence"], value="999")
    subject["modelEvidence"] = model
    _reseal_r10(subject)
    snapshot = _verify(subject)
    assert snapshot.status is VerificationStatus.VERIFICATION_FAILED
    assert _check(snapshot, "MODEL_DIGESTS").state is CheckState.FAIL
    assert _check(snapshot,
                  "MODEL_OBSERVATION_BINDINGS").state is CheckState.FAIL


def test_adv_16_model_run_digest_mismatch_detected():
    subject = _comparable_subject()
    model = dict(subject["modelEvidence"])
    model["modelRunDigest"] = "f" * 64
    subject["modelEvidence"] = model
    _reseal_r10(subject)
    snapshot = _verify(subject)
    assert snapshot.status is VerificationStatus.VERIFICATION_FAILED
    assert _check(snapshot, "MODEL_DIGESTS").state is CheckState.FAIL


def test_adv_17_malformed_decimal_field_detected():
    subject = _comparable_subject()
    model = dict(subject["modelEvidence"])
    model["value"] = "not-a-number"
    subject["modelEvidence"] = model
    _reseal_r10(subject)
    snapshot = _verify(subject)
    assert snapshot.status in (VerificationStatus.VERIFICATION_FAILED,
                                  VerificationStatus.VERIFICATION_EVIDENCE_MISMATCH)


def test_adv_18_nan_infinity_detected():
    for bad in ("NaN", "Infinity"):
        subject = _comparable_subject()
        model = dict(subject["modelEvidence"])
        model["value"] = bad
        subject["modelEvidence"] = model
        _reseal_r10(subject)
        snapshot = _verify(subject)
        assert snapshot.status in (VerificationStatus.VERIFICATION_FAILED,
                                  VerificationStatus.VERIFICATION_EVIDENCE_MISMATCH)


def test_adv_19_malformed_timestamp_detected():
    subject = _comparable_subject()
    reference = dict(subject["referenceComparison"])
    reference["referenceObservedAt"] = "abc"
    subject["referenceComparison"] = reference
    _reseal_r10(subject)
    snapshot = _verify(subject)
    assert snapshot.status is VerificationStatus.VERIFICATION_FAILED
    assert _check(snapshot, "HISTORICAL_TIMING").state is CheckState.FAIL


def test_adv_20_missing_timestamp_key_detected():
    subject = _comparable_subject()
    reference = dict(subject["referenceComparison"])
    reference.pop("referenceObservedAt")
    subject["referenceComparison"] = reference
    _reseal_r10(subject)
    snapshot = _verify(subject)
    assert snapshot.status is VerificationStatus.VERIFICATION_FAILED
    assert _check(snapshot, "HISTORICAL_TIMING").state is CheckState.FAIL


def test_ca_i3_positive_timestamps_still_verified():
    snapshot = _verify(_comparable_subject())
    assert _check(snapshot, "HISTORICAL_TIMING").state is CheckState.PASS


# --------------------------------------------------------------------------
# 22-25: arithmetic and source binding
# --------------------------------------------------------------------------

def test_adv_22_reference_arithmetic_smallest_unit_alteration_detected():
    subject = _comparable_subject()
    reference = dict(subject["referenceComparison"])
    reference["referenceVsModelBps"] = str(
        Decimal(reference["referenceVsModelBps"]) + Decimal("0.0001"))
    subject["referenceComparison"] = reference
    _reseal_r10(subject)
    snapshot = _verify(subject)
    assert snapshot.status is VerificationStatus.VERIFICATION_FAILED
    assert _check(snapshot, "REFERENCE_ARITHMETIC").state is CheckState.FAIL


def test_adv_23_execution_arithmetic_alteration_detected():
    subject = _comparable_subject()
    rows = copy.deepcopy(subject["executionComparisons"])
    rows[0]["executionVsModelBps"] = str(
        Decimal(rows[0]["executionVsModelBps"]) + Decimal("0.0001"))
    subject["executionComparisons"] = rows
    _reseal_r10(subject)
    snapshot = _verify(subject)
    assert snapshot.status in (VerificationStatus.VERIFICATION_FAILED,
                               VerificationStatus.VERIFICATION_EVIDENCE_MISMATCH)
    assert _check(snapshot, "EXECUTION_ARITHMETIC").state is CheckState.FAIL


def test_adv_24_execution_row_wrong_scenario_detected():
    subject = _comparable_subject()
    rows = copy.deepcopy(subject["executionComparisons"])
    rows[0]["requestedNotionalUsd"] = "555"
    subject["executionComparisons"] = rows
    _reseal_r10(subject)
    snapshot = _verify(subject)
    assert snapshot.status is VerificationStatus.VERIFICATION_EVIDENCE_MISMATCH
    assert _check(snapshot,
                  "EXECUTION_SOURCE_BINDING").state is CheckState.FAIL


def test_adv_25_usd_execution_row_relabeled_eur_detected():
    subject = _comparable_subject()
    rows = copy.deepcopy(subject["executionComparisons"])
    rows[0]["executionCurrency"] = "EUR"
    subject["executionComparisons"] = rows
    _reseal_r10(subject)
    snapshot = _verify(subject)
    assert snapshot.status is VerificationStatus.VERIFICATION_EVIDENCE_MISMATCH
    assert _check(snapshot,
                  "EXECUTION_SOURCE_BINDING").state is CheckState.FAIL


# --------------------------------------------------------------------------
# 26-30: comparability and null-model contracts
# --------------------------------------------------------------------------

def test_adv_26_duplicate_comparability_dimension_detected():
    subject = _comparable_subject()
    comparability = copy.deepcopy(subject["comparability"])
    comparability["dimensions"].append(
        copy.deepcopy(comparability["dimensions"][0]))
    subject["comparability"] = comparability
    _reseal_r10(subject)
    snapshot = _verify(subject)
    assert snapshot.status is VerificationStatus.VERIFICATION_FAILED
    assert _check(snapshot, "COMPARABILITY_CONTRACT").state is CheckState.FAIL


def test_adv_27_missing_comparability_dimension_detected():
    subject = _comparable_subject()
    comparability = copy.deepcopy(subject["comparability"])
    comparability["dimensions"] = comparability["dimensions"][:-1]
    subject["comparability"] = comparability
    _reseal_r10(subject)
    snapshot = _verify(subject)
    assert snapshot.status is VerificationStatus.VERIFICATION_FAILED
    assert _check(snapshot, "COMPARABILITY_CONTRACT").state is CheckState.FAIL


def test_adv_28_inconsistent_comparability_state_detected():
    subject = _comparable_subject()
    comparability = dict(subject["comparability"])
    comparability["state"] = "NOT_COMPARABLE"
    subject["comparability"] = comparability
    _reseal_r10(subject)
    snapshot = _verify(subject)
    assert snapshot.status is VerificationStatus.VERIFICATION_FAILED
    assert _check(snapshot, "COMPARABILITY_CONTRACT").state is CheckState.FAIL


def test_adv_29_comparison_present_while_model_null_detected():
    subject = _subject()
    comparable = _comparable_subject()
    subject["referenceComparison"] = comparable["referenceComparison"]
    _reseal_r10(subject)
    snapshot = _verify(subject)
    assert snapshot.status is VerificationStatus.VERIFICATION_FAILED
    assert _check(snapshot, "SUBJECT_GAP_CONSISTENCY").state is CheckState.FAIL


def test_adv_30_model_binding_present_while_model_null_detected():
    subject = _subject()
    comparable = _comparable_subject()
    subject["modelBinding"] = comparable["modelBinding"]
    _reseal_r10(subject)
    snapshot = _verify(subject)
    assert snapshot.status is VerificationStatus.VERIFICATION_FAILED
    assert _check(snapshot, "SUBJECT_GAP_CONSISTENCY").state is CheckState.FAIL


# --------------------------------------------------------------------------
# 31-32: canonical ordering invariance and the live-shape positive
# --------------------------------------------------------------------------

def test_adv_31_caller_order_does_not_change_canonical_digest():
    r9, r8 = _chain(**FULL, mutate_r8=lambda e: e.__setitem__(
        "scenarios", list(reversed(e["scenarios"]))))
    reordered = build_model_radar_snapshot(
        r9_evidence=r9, r8_evidence=r8,
        model_evidence=_model(value=Decimal("100")),
        timing_policy=POLICY, now=NOW, git_head="r10-subject",
        synthetic=False).to_evidence_dict()
    a = _verify(_comparable_subject())
    b = _verify(reordered)
    checks_a = [(c.check_id, c.state.value) for c in a.checks]
    checks_b = [(c.check_id, c.state.value) for c in b.checks]
    assert checks_a == checks_b
    assert [c.check_id for c in a.checks] == sorted(
        c.check_id for c in a.checks)
    assert a.status is b.status is VerificationStatus.VERIFICATION_OK


def test_adv_32_verified_partial_subject_produces_verification_ok():
    snapshot = _verify(_subject())
    assert snapshot.subject_status == "MODEL_RADAR_PARTIAL"
    assert snapshot.status is VerificationStatus.VERIFICATION_OK
    assert snapshot.to_evidence_dict()["subjectGaps"] == [{
        "gapKind": "MODEL_BINDING_UNAVAILABLE",
        "source": "R10_MODEL_AUTHORITY_DISCOVERY",
        "reason": ("no frozen FINCO model authority carries a "
                   "source-proven model binding for economic asset AAPL"),
    }]


# --------------------------------------------------------------------------
# Contract hygiene
# --------------------------------------------------------------------------

def test_verification_error_typed():
    err = VerificationError("boom")
    assert err.status is VerificationStatus.VERIFICATION_FAILED


def test_gap_kind_vocabulary_is_r11_owned():
    values = {g.value for g in VerificationGapKind}
    assert "MODEL_BINDING_UNAVAILABLE" not in values
    assert "SUBJECT_DIGEST_MISMATCH" in values
    assert "FREEZE_IDENTITY_MISMATCH" in values
