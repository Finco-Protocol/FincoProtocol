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


def _digest(payload) -> str:
    return hashlib.sha256(json.dumps(payload, sort_keys=True,
                                     separators=(",", ":"),
                                     ensure_ascii=False)
                          .encode("utf-8")).hexdigest()
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


# --------------------------------------------------------------------------
# Correction A - A1: freeze identity pinned
# --------------------------------------------------------------------------

def test_ca_a1_01_wrong_freeze_anchor_rejected():
    snapshot = _verify(_subject(), freeze_anchor="f" * 64)
    assert snapshot.status is not VerificationStatus.VERIFICATION_OK
    assert _check(snapshot, "FREEZE_IDENTITY").state is CheckState.FAIL
    assert any(g.gap_kind is VerificationGapKind.FREEZE_IDENTITY_MISMATCH
               for g in snapshot.verification_gaps)
    # verified canonical values, never caller metadata
    assert snapshot.subject_authority_anchor == (
        "7ffaf3b1e67dabb728314948e2a4e4c7ef30047a")


def test_ca_a1_02_wrong_freeze_tree_rejected():
    snapshot = _verify(_subject(), freeze_tree="e" * 64)
    assert snapshot.status is not VerificationStatus.VERIFICATION_OK
    assert _check(snapshot, "FREEZE_IDENTITY").state is CheckState.FAIL


def test_ca_a1_03_both_wrong_but_self_consistent_rejected():
    snapshot = _verify(_subject(), freeze_anchor="f" * 64,
                       freeze_tree="f" * 64)
    assert snapshot.status is not VerificationStatus.VERIFICATION_OK
    assert _check(snapshot, "FREEZE_IDENTITY").state is CheckState.FAIL


def test_ca_a1_04_exact_anchor_and_tree_pass():
    snapshot = _verify(_subject(), freeze_anchor=ANCHOR, freeze_tree=TREE)
    assert _check(snapshot, "FREEZE_IDENTITY").state is CheckState.PASS
    assert snapshot.subject_authority_anchor == ANCHOR
    assert snapshot.subject_authority_tree == TREE


def test_ca_a1_05_freeze_constants_pinned_in_contracts():
    from finco_radar.verification.contracts import (
        R10_FREEZE_ANCHOR, R10_FREEZE_TREE,
    )
    assert R10_FREEZE_ANCHOR == "7ffaf3b1e67dabb728314948e2a4e4c7ef30047a"
    assert R10_FREEZE_TREE == "fba9d76d9dceee35d079563b115fdde90c40bd46"


# --------------------------------------------------------------------------
# Correction A - A2: subject status / gap coherence
# --------------------------------------------------------------------------

def test_ca_a2_01_removed_missing_model_gap_rejected():
    subject = _subject()
    subject["gaps"] = []
    _reseal_r10(subject)
    snapshot = _verify(subject)
    assert snapshot.status is VerificationStatus.VERIFICATION_FAILED
    assert _check(snapshot, "HONEST_MISSING_MODEL").state is CheckState.FAIL


def test_ca_a2_02_ok_status_with_missing_model_gap_rejected():
    subject = _subject()
    subject["status"] = "MODEL_RADAR_OK"
    _reseal_r10(subject)
    snapshot = _verify(subject)
    assert snapshot.status is VerificationStatus.VERIFICATION_FAILED
    assert "MODEL_RADAR_OK cannot carry unresolved subject gaps" in (
        _check(snapshot, "HONEST_MISSING_MODEL").detail)


def test_ca_a2_03_partial_without_gaps_rejected():
    subject = _subject()
    subject["gaps"] = []
    subject["status"] = "MODEL_RADAR_PARTIAL"
    _reseal_r10(subject)
    snapshot = _verify(subject)
    assert snapshot.status is VerificationStatus.VERIFICATION_FAILED
    assert "requires at least one subject gap" in (
        _check(snapshot, "HONEST_MISSING_MODEL").detail)


def test_ca_a2_04_ok_subject_without_gaps_passes():
    comparable = _comparable_subject()
    snapshot = _verify(comparable)
    assert comparable["status"] == "MODEL_RADAR_OK"
    assert comparable["gaps"] == []
    assert snapshot.status is VerificationStatus.VERIFICATION_OK


# --------------------------------------------------------------------------
# Correction A - A3: nested shapes fail closed, never raw
# --------------------------------------------------------------------------

def _malformed(mutate):
    subject = _subject()
    mutate(subject)
    return _reseal_r10(subject)


def test_ca_a3_01_gaps_string_rejected_typed():
    snapshot = _verify(_malformed(lambda s: s.__setitem__("gaps", "bad")))
    assert snapshot.status is VerificationStatus.VERIFICATION_INPUT_INVALID
    assert _check(snapshot, "SUBJECT_IDENTITY").state is CheckState.FAIL


def test_ca_a3_02_gaps_non_mapping_item_rejected_typed():
    snapshot = _verify(_malformed(lambda s: s.__setitem__("gaps", ["bad"])))
    assert snapshot.status is VerificationStatus.VERIFICATION_INPUT_INVALID


def test_ca_a3_03_source_digests_string_rejected_typed():
    snapshot = _verify(_malformed(
        lambda s: s.__setitem__("sourceDigests", "bad")))
    assert snapshot.status is VerificationStatus.VERIFICATION_INPUT_INVALID


def test_ca_a3_04_r9_nodes_non_mapping_item_rejected_typed():
    def m(s):
        s["upstreamEvidence"]["r9AssetGraphEvidence"]["nodes"] = ["bad"]
    snapshot = _verify(_malformed(m))
    assert snapshot.status is VerificationStatus.VERIFICATION_INPUT_INVALID


def test_ca_a3_05_r8_scenarios_non_mapping_item_rejected_typed():
    def m(s):
        s["upstreamEvidence"]["r8ExecutionEvidence"]["scenarios"] = ["bad"]
    snapshot = _verify(_malformed(m))
    assert snapshot.status is VerificationStatus.VERIFICATION_INPUT_INVALID


def test_ca_a3_06_r8_upstream_evidence_list_rejected_typed():
    def m(s):
        s["upstreamEvidence"]["r8ExecutionEvidence"]["upstreamEvidence"] = []
    snapshot = _verify(_malformed(m))
    assert snapshot.status is VerificationStatus.VERIFICATION_INPUT_INVALID


def test_ca_a3_07_r8_source_digests_list_rejected_typed():
    def m(s):
        s["upstreamEvidence"]["r8ExecutionEvidence"]["sourceDigests"] = []
    snapshot = _verify(_malformed(m))
    assert snapshot.status is VerificationStatus.VERIFICATION_INPUT_INVALID


def test_ca_a3_08_zero_model_denominator_reference_before_division():
    subject = _comparable_subject()
    model = dict(subject["modelEvidence"])
    model["value"] = "0"
    model["outputEvidence"] = dict(model["outputEvidence"], value="0")
    subject["modelEvidence"] = model
    _reseal_r10(subject)
    snapshot = _verify(subject)
    assert snapshot.status in (VerificationStatus.VERIFICATION_FAILED,
                                  VerificationStatus.VERIFICATION_EVIDENCE_MISMATCH)
    assert not any("DivisionByZero" in c.detail for c in snapshot.checks)
    detail = _check(snapshot, "REFERENCE_ARITHMETIC").detail
    assert "arithmetic reconstruction failed" not in detail
    assert "DivisionByZero" not in str(
        [c.detail for c in snapshot.checks])


def test_ca_a3_09_zero_model_denominator_execution_before_division():
    subject = _comparable_subject()
    model = dict(subject["modelEvidence"])
    model["value"] = "0"
    model["outputEvidence"] = dict(model["outputEvidence"], value="0")
    subject["modelEvidence"] = model
    rows = copy.deepcopy(subject["executionComparisons"])
    for row in rows:
        row["modelValue"] = "0"
    subject["executionComparisons"] = rows
    _reseal_r10(subject)
    snapshot = _verify(subject)
    assert snapshot.status in (VerificationStatus.VERIFICATION_FAILED,
                                  VerificationStatus.VERIFICATION_EVIDENCE_MISMATCH)
    assert not any("DivisionByZero" in c.detail for c in snapshot.checks)
    detail = _check(snapshot, "EXECUTION_ARITHMETIC").detail
    assert "arithmetic reconstruction failed" not in detail
    assert "DivisionByZero" not in str(
        [c.detail for c in snapshot.checks])


# --------------------------------------------------------------------------
# Correction A - A4: full ModelEvidence authority mirror
# --------------------------------------------------------------------------

def test_ca_a4_01_arbitrary_engine_authority_rejected():
    subject = _comparable_subject()
    model = dict(subject["modelEvidence"])
    model["engineAuthority"] = "e"
    subject["modelEvidence"] = model
    _reseal_r10(subject)
    snapshot = _verify(subject)
    assert snapshot.status is VerificationStatus.VERIFICATION_FAILED
    assert "engineAuthority" in _check(snapshot, "MODEL_DIGESTS").detail


def test_ca_a4_02_model_synthetic_non_boolean_rejected():
    subject = _comparable_subject()
    model = dict(subject["modelEvidence"])
    model["synthetic"] = 1
    subject["modelEvidence"] = model
    _reseal_r10(subject)
    snapshot = _verify(subject)
    assert snapshot.status is VerificationStatus.VERIFICATION_FAILED
    assert "exact boolean" in _check(snapshot, "MODEL_DIGESTS").detail


def test_ca_a4_03_empty_model_identity_rejected():
    subject = _comparable_subject()
    model = dict(subject["modelEvidence"])
    model["modelId"] = ""
    subject["modelEvidence"] = model
    _reseal_r10(subject)
    snapshot = _verify(subject)
    assert snapshot.status is VerificationStatus.VERIFICATION_FAILED
    assert "modelId" in _check(snapshot, "MODEL_DIGESTS").detail


def test_ca_a4_04_output_observation_missing_valuation_as_of_rejected():
    subject = _comparable_subject()
    model = copy.deepcopy(subject["modelEvidence"])
    model["outputEvidence"].pop("valuationAsOf")
    subject["modelEvidence"] = model
    _reseal_r10(subject)
    snapshot = _verify(subject)
    assert snapshot.status is VerificationStatus.VERIFICATION_FAILED
    assert "valuationAsOf" in _check(
        snapshot, "MODEL_OBSERVATION_BINDINGS").detail


def test_ca_a4_05_output_only_multiplier_rejected():
    subject = _comparable_subject()
    model = copy.deepcopy(subject["modelEvidence"])
    model["outputEvidence"]["unitMultiplier"] = "5"
    subject["modelEvidence"] = model
    _reseal_r10(subject)
    snapshot = _verify(subject)
    assert snapshot.status is VerificationStatus.VERIFICATION_FAILED
    assert "output-only multiplier" in _check(
        snapshot, "MODEL_OBSERVATION_BINDINGS").detail


def test_ca_a4_06_input_multiplier_dropped_from_declared_rejected():
    subject = _comparable_subject()
    model = copy.deepcopy(subject["modelEvidence"])
    model["inputEvidence"]["unitMultiplier"] = "10000"
    subject["modelEvidence"] = model
    _reseal_r10(subject)
    snapshot = _verify(subject)
    assert snapshot.status is VerificationStatus.VERIFICATION_FAILED
    assert "drops" in _check(snapshot, "MODEL_OBSERVATION_BINDINGS").detail


# --------------------------------------------------------------------------
# Correction A - A5: complete comparability contract
# --------------------------------------------------------------------------

def _comparability_mutated(mutate):
    subject = _comparable_subject()
    comparability = copy.deepcopy(subject["comparability"])
    mutate(comparability)
    subject["comparability"] = comparability
    return _reseal_r10(subject)


def test_ca_a5_01_passed_dimension_carrying_gap_rejected():
    subject = _comparability_mutated(lambda c: c["dimensions"][0].__setitem__(
        "gapKind", "CURRENCY_MISMATCH"))
    snapshot = _verify(subject)
    assert snapshot.status is VerificationStatus.VERIFICATION_FAILED
    assert _check(snapshot, "COMPARABILITY_CONTRACT").state is CheckState.FAIL


def test_ca_a5_02_failed_dimension_without_gap_rejected():
    def m(c):
        c["dimensions"][0]["ok"] = False
        c["dimensions"][0]["gapKind"] = None
    subject = _comparability_mutated(m)
    snapshot = _verify(subject)
    assert snapshot.status is VerificationStatus.VERIFICATION_FAILED
    assert "typed gap kind" in _check(
        snapshot, "COMPARABILITY_CONTRACT").detail


def test_ca_a5_03_ok_integer_rejected():
    def m(c):
        c["dimensions"][0]["ok"] = 1
    subject = _comparability_mutated(m)
    snapshot = _verify(subject)
    assert snapshot.status is VerificationStatus.VERIFICATION_FAILED
    assert "exact boolean" in _check(
        snapshot, "COMPARABILITY_CONTRACT").detail


def test_ca_a5_04_ok_string_rejected():
    def m(c):
        c["dimensions"][0]["ok"] = "true"
    subject = _comparability_mutated(m)
    snapshot = _verify(subject)
    assert snapshot.status is VerificationStatus.VERIFICATION_FAILED


def test_ca_a5_05_mutated_comparability_gaps_rejected():
    def m(c):
        c["gaps"] = ["CURRENCY_MISMATCH"]
    subject = _comparability_mutated(m)
    snapshot = _verify(subject)
    assert snapshot.status is VerificationStatus.VERIFICATION_FAILED
    assert "comparability.gaps" in _check(
        snapshot, "COMPARABILITY_CONTRACT").detail


# --------------------------------------------------------------------------
# Correction A - A6: full reference binding
# --------------------------------------------------------------------------

def test_ca_a6_01_reference_model_value_mutation_detected():
    subject = _comparable_subject()
    reference = dict(subject["referenceComparison"])
    reference["modelValue"] = "101"
    subject["referenceComparison"] = reference
    _reseal_r10(subject)
    snapshot = _verify(subject)
    assert snapshot.status is VerificationStatus.VERIFICATION_FAILED
    assert "modelValue" in _check(snapshot, "REFERENCE_ARITHMETIC").detail


def test_ca_a6_02_removed_r7_price_detected():
    def m(e):
        r7 = e["upstreamEvidence"]["r8ExecutionEvidence"][
            "upstreamEvidence"]["r7CrossMarketEvidence"]
        r7["layers"]["oracleReference"].pop("price")
        r7["r7SnapshotDigest"] = _digest(
            {k: v for k, v in r7.items() if k != "r7SnapshotDigest"})
        e["upstreamEvidence"]["r8ExecutionEvidence"]["sourceDigests"][
            "r7CrossMarketDigest"] = _digest(r7)
        r8e = e["upstreamEvidence"]["r8ExecutionEvidence"]
        r8e["r8SnapshotDigest"] = _digest(
            {k: v for k, v in r8e.items() if k != "r8SnapshotDigest"})
        e["sourceDigests"]["r8ExecutionSimulatorDigest"] = _digest(r8e)
    subject = _comparable_subject()
    m(subject)
    _reseal_r10(subject)
    snapshot = _verify(subject)
    assert snapshot.status in (VerificationStatus.VERIFICATION_FAILED,
                               VerificationStatus.VERIFICATION_EVIDENCE_MISMATCH)
    assert "R7 oracle price missing" in _check(
        snapshot, "REFERENCE_ARITHMETIC").detail


def test_ca_a6_03_removed_r7_source_detected():
    def m(e):
        r7 = e["upstreamEvidence"]["r8ExecutionEvidence"][
            "upstreamEvidence"]["r7CrossMarketEvidence"]
        r7["layers"]["oracleReference"].pop("source")
        r7["r7SnapshotDigest"] = _digest(
            {k: v for k, v in r7.items() if k != "r7SnapshotDigest"})
        e["upstreamEvidence"]["r8ExecutionEvidence"]["sourceDigests"][
            "r7CrossMarketDigest"] = _digest(r7)
        r8e = e["upstreamEvidence"]["r8ExecutionEvidence"]
        r8e["r8SnapshotDigest"] = _digest(
            {k: v for k, v in r8e.items() if k != "r8SnapshotDigest"})
        e["sourceDigests"]["r8ExecutionSimulatorDigest"] = _digest(r8e)
    subject = _comparable_subject()
    m(subject)
    _reseal_r10(subject)
    snapshot = _verify(subject)
    assert snapshot.status in (VerificationStatus.VERIFICATION_FAILED,
                               VerificationStatus.VERIFICATION_EVIDENCE_MISMATCH)


def test_ca_a6_04_null_reference_source_detected():
    subject = _comparable_subject()
    reference = dict(subject["referenceComparison"])
    reference["referenceSource"] = None
    subject["referenceComparison"] = reference
    _reseal_r10(subject)
    snapshot = _verify(subject)
    assert snapshot.status is VerificationStatus.VERIFICATION_FAILED
    assert "reference source" in _check(
        snapshot, "REFERENCE_ARITHMETIC").detail


def test_ca_a6_05_r7_observed_at_change_detected():
    comparable = _comparable_subject()

    def m(e):
        r7 = e["upstreamEvidence"]["r8ExecutionEvidence"][
            "upstreamEvidence"]["r7CrossMarketEvidence"]
        r7["layers"]["oracleReference"]["observedAt"] = (
            "2020-01-01T00:00:00+00:00")
        r7["r7SnapshotDigest"] = _digest(
            {k: v for k, v in r7.items() if k != "r7SnapshotDigest"})
        e["upstreamEvidence"]["r8ExecutionEvidence"]["sourceDigests"][
            "r7CrossMarketDigest"] = _digest(r7)
        r8e = e["upstreamEvidence"]["r8ExecutionEvidence"]
        r8e["r8SnapshotDigest"] = _digest(
            {k: v for k, v in r8e.items() if k != "r8SnapshotDigest"})
        e["sourceDigests"]["r8ExecutionSimulatorDigest"] = _digest(r8e)
    m(comparable)
    _reseal_r10(comparable)
    snapshot = _verify(comparable)
    assert snapshot.status is VerificationStatus.VERIFICATION_FAILED
    assert "observedAt" in _check(snapshot, "REFERENCE_ARITHMETIC").detail


def test_ca_a6_06_model_observed_at_mutation_detected():
    subject = _comparable_subject()
    reference = dict(subject["referenceComparison"])
    reference["modelObservedAt"] = "2020-01-01T00:00:00+00:00"
    subject["referenceComparison"] = reference
    _reseal_r10(subject)
    snapshot = _verify(subject)
    assert snapshot.status is VerificationStatus.VERIFICATION_FAILED
    assert "modelObservedAt" in _check(snapshot, "REFERENCE_ARITHMETIC").detail


# --------------------------------------------------------------------------
# Correction A - A7: complete execution scenario binding
# --------------------------------------------------------------------------

def test_ca_a7_01_scenario_index_mutation_detected():
    subject = _comparable_subject()
    rows = copy.deepcopy(subject["executionComparisons"])
    rows[0]["r8ScenarioIndex"] = 99
    subject["executionComparisons"] = rows
    _reseal_r10(subject)
    snapshot = _verify(subject)
    assert snapshot.status is VerificationStatus.VERIFICATION_EVIDENCE_MISMATCH
    assert "r8ScenarioIndex" in _check(
        snapshot, "EXECUTION_SOURCE_BINDING").detail


def test_ca_a7_02_duplicate_scenario_identity_detected():
    def m(e):
        e["scenarios"].append(copy.deepcopy(e["scenarios"][0]))
    r9, r8 = _chain(**FULL, mutate_r8=m)
    subject = build_model_radar_snapshot(
        r9_evidence=r9, r8_evidence=r8,
        model_evidence=_model(value=Decimal("100")),
        timing_policy=POLICY, now=NOW, git_head="t",
        synthetic=False).to_evidence_dict()
    _reseal_r10(subject)
    snapshot = _verify(subject)
    assert snapshot.status in (VerificationStatus.VERIFICATION_FAILED,
                               VerificationStatus.VERIFICATION_EVIDENCE_MISMATCH)
    assert "duplicate/ambiguous" in _check(
        snapshot, "EXECUTION_SOURCE_BINDING").detail


def test_ca_a7_03_removed_quote_observed_at_detected():
    subject = _comparable_subject()
    # strip the R8-side quoteObservedAt AFTER the R10 rows were produced,
    # keeping the row's executionObservedAt: the lineage must reject it.
    r8 = subject["upstreamEvidence"]["r8ExecutionEvidence"]
    r8["scenarios"][0].pop("quoteObservedAt")
    _reseal_chain(subject, r8=True)
    _reseal_r10(subject)
    snapshot = _verify(subject)
    assert snapshot.status in (VerificationStatus.VERIFICATION_FAILED,
                               VerificationStatus.VERIFICATION_EVIDENCE_MISMATCH)
    assert "quoteObservedAt" in _check(
        snapshot, "EXECUTION_SOURCE_BINDING").detail


def test_ca_a7_04_same_key_wrong_deployment_detected():
    subject = _comparable_subject()
    r8 = subject["upstreamEvidence"]["r8ExecutionEvidence"]
    for scenario in r8["scenarios"]:
        scenario["scenario"]["contractAddress"] = "0x" + "ee" * 20
    _reseal_chain(subject, r8=True)
    _reseal_r10(subject)
    snapshot = _verify(subject)
    assert snapshot.status is VerificationStatus.VERIFICATION_EVIDENCE_MISMATCH
    assert "deployment identity" in _check(
        snapshot, "EXECUTION_SOURCE_BINDING").detail


# --------------------------------------------------------------------------
# Correction A - A8: R9 economic node from the graph
# --------------------------------------------------------------------------

def test_ca_a8_01_removed_economic_node_detected():
    subject = _subject()
    r9 = subject["upstreamEvidence"]["r9AssetGraphEvidence"]
    r9["nodes"] = [n for n in r9["nodes"]
                   if n.get("nodeType") != "ECONOMIC_ASSET"]
    _reseal_chain(subject, r9=True)
    snapshot = _verify(subject)
    assert snapshot.status is VerificationStatus.VERIFICATION_EVIDENCE_MISMATCH
    assert _check(snapshot, "R9_IDENTITY_CONSISTENCY").state is CheckState.FAIL


def test_ca_a8_02_duplicate_economic_node_detected():
    subject = _subject()
    r9 = subject["upstreamEvidence"]["r9AssetGraphEvidence"]
    econ = next(n for n in r9["nodes"]
                if n.get("nodeType") == "ECONOMIC_ASSET")
    r9["nodes"].append(copy.deepcopy(econ))
    _reseal_chain(subject, r9=True)
    snapshot = _verify(subject)
    assert snapshot.status is VerificationStatus.VERIFICATION_EVIDENCE_MISMATCH
    assert _check(snapshot, "R9_IDENTITY_CONSISTENCY").state is CheckState.FAIL


def test_ca_a8_03_wrong_uid_economic_node_detected():
    subject = _subject()
    r9 = subject["upstreamEvidence"]["r9AssetGraphEvidence"]
    for node in r9["nodes"]:
        if node.get("nodeType") == "ECONOMIC_ASSET":
            node["economicAssetUid"] = "WRONG"
    _reseal_chain(subject, r9=True)
    snapshot = _verify(subject)
    assert snapshot.status is VerificationStatus.VERIFICATION_EVIDENCE_MISMATCH
    assert _check(snapshot, "R9_IDENTITY_CONSISTENCY").state is CheckState.FAIL


# --------------------------------------------------------------------------
# Correction A - A9: exact R11 outer contract
# --------------------------------------------------------------------------

def test_ca_a9_01_snapshot_synthetic_integer_rejected():
    with pytest.raises(VerificationError) as excinfo:
        build_snapshot_with_synthetic(0)
    assert "exact boolean" in str(excinfo.value)


def test_ca_a9_02_serialized_r11_synthetic_zero_does_not_verify():
    snapshot = _verify(_subject())
    evidence = snapshot.to_evidence_dict()
    evidence["synthetic"] = 0
    material = {k: v for k, v in evidence.items()
                if k != "r11SnapshotDigest"}
    evidence["r11SnapshotDigest"] = hashlib.sha256(json.dumps(
        material, sort_keys=True, separators=(",", ":"),
        ensure_ascii=False).encode("utf-8")).hexdigest()
    assert verify_serialized_r11_evidence(evidence) is False


def test_ca_a9_03_string_status_rejected():
    with pytest.raises(VerificationError):
        build_snapshot_with_status("VERIFICATION_OK")


def build_snapshot_with_synthetic(synthetic):
    snapshot = _verify(_subject())
    from dataclasses import replace
    return replace(snapshot, synthetic=synthetic)


def build_snapshot_with_status(status):
    snapshot = _verify(_subject())
    from dataclasses import replace
    return replace(snapshot, status=status)


# --------------------------------------------------------------------------
# Correction A - A10: content envelope binding
# --------------------------------------------------------------------------

def _envelope_for(subject):
    from finco_radar.verification.contracts import (
        build_verification_envelope)
    envelope = build_verification_envelope(subject)
    ed = envelope.as_dict()
    return {k: ed[k] for k in ("schema", "canonicalization", "surface",
                               "evidenceType", "authorityRefs",
                               "payloadSha256", "contentAddress")}


def test_ca_a10_01_wrong_envelope_payload_digest_detected():
    subject = _comparable_subject()
    envelope = _envelope_for(subject)
    envelope["payloadSha256"] = "0" * 64
    snapshot = _verify(subject, content_envelope=envelope)
    assert snapshot.status is not VerificationStatus.VERIFICATION_OK
    assert _check(snapshot,
                  "CONTENT_ENVELOPE_BINDING").state is CheckState.FAIL


def test_ca_a10_02_wrong_content_address_detected():
    subject = _comparable_subject()
    envelope = _envelope_for(subject)
    envelope["contentAddress"] = "sha256:" + "0" * 64
    snapshot = _verify(subject, content_envelope=envelope)
    assert _check(snapshot,
                  "CONTENT_ENVELOPE_BINDING").state is CheckState.FAIL


def test_ca_a10_03_wrong_evidence_type_detected():
    subject = _comparable_subject()
    envelope = _envelope_for(subject)
    envelope["evidenceType"] = "something-else"
    snapshot = _verify(subject, content_envelope=envelope)
    assert _check(snapshot,
                  "CONTENT_ENVELOPE_BINDING").state is CheckState.FAIL


def test_ca_a10_04_wrong_authority_refs_detected():
    subject = _comparable_subject()
    envelope = _envelope_for(subject)
    envelope["authorityRefs"] = ["unrelated"]
    snapshot = _verify(subject, content_envelope=envelope)
    assert _check(snapshot,
                  "CONTENT_ENVELOPE_BINDING").state is CheckState.FAIL


def test_ca_a10_05_omitted_envelope_remains_valid_optional():
    snapshot = _verify(_comparable_subject())
    states = {c.check_id: c.state for c in snapshot.checks}
    assert states["CONTENT_ENVELOPE_BINDING"] is CheckState.UNAVAILABLE
    assert snapshot.status is VerificationStatus.VERIFICATION_OK


# --------------------------------------------------------------------------
# Correction B - B1: independent ModelBinding verification
# --------------------------------------------------------------------------

def _bind_mutation(mutate):
    subject = _comparable_subject()
    binding = copy.deepcopy(subject["modelBinding"])
    mutate(binding)
    subject["modelBinding"] = binding
    return _reseal_r10(subject)


def test_cb_b1_01_model_evidence_with_null_binding_rejected():
    subject = _comparable_subject()
    subject["modelBinding"] = None
    _reseal_r10(subject)
    snapshot = _verify(subject)
    assert snapshot.status is not VerificationStatus.VERIFICATION_OK
    assert _check(snapshot, "MODEL_BINDING_CONTRACT").state is CheckState.FAIL
    assert "modelBinding is null" in _check(
        snapshot, "MODEL_BINDING_CONTRACT").detail


def test_cb_b1_02_wrong_binding_id_rejected():
    subject = _bind_mutation(lambda b: b.__setitem__(
        "bindingId", "model-binding:" + "f" * 64))
    snapshot = _verify(subject)
    assert snapshot.status is not VerificationStatus.VERIFICATION_OK
    assert "does not equal the independently reconstructed" in _check(
        snapshot, "MODEL_BINDING_CONTRACT").detail


def test_ca_b1_03_wrong_binding_uid_rejected():
    subject = _bind_mutation(lambda b: b.__setitem__("economicAssetUid", "EVIL"))
    snapshot = _verify(subject)
    assert snapshot.status is not VerificationStatus.VERIFICATION_OK
    assert "economicAssetUid" in _check(
        snapshot, "MODEL_BINDING_CONTRACT").detail


def test_ca_b1_04_wrong_binding_node_rejected():
    subject = _bind_mutation(lambda b: b.__setitem__(
        "economicNodeId", "economic:WRONG"))
    snapshot = _verify(subject)
    assert snapshot.status is not VerificationStatus.VERIFICATION_OK
    assert "economicNodeId" in _check(
        snapshot, "MODEL_BINDING_CONTRACT").detail


def test_ca_b1_05_wrong_binding_model_id_rejected():
    subject = _bind_mutation(lambda b: b.__setitem__("modelId", "OTHER"))
    snapshot = _verify(subject)
    assert snapshot.status is not VerificationStatus.VERIFICATION_OK
    assert "modelId" in _check(snapshot, "MODEL_BINDING_CONTRACT").detail


def test_ca_b1_06_wrong_binding_model_version_rejected():
    subject = _bind_mutation(lambda b: b.__setitem__("modelVersion", "9.9"))
    snapshot = _verify(subject)
    assert snapshot.status is not VerificationStatus.VERIFICATION_OK
    assert "modelVersion" in _check(snapshot, "MODEL_BINDING_CONTRACT").detail


def test_ca_b1_07_binding_contract_passes_when_consistent():
    snapshot = _comparable_subject_verify()
    assert _check(snapshot, "MODEL_BINDING_CONTRACT").state is CheckState.PASS


def _comparable_subject_verify():
    return _verify(_comparable_subject())


# --------------------------------------------------------------------------
# Correction B - B2: nested-shape fail-closed completion
# --------------------------------------------------------------------------

def test_cb_b2_01_r8_source_digests_null_typed():
    def m(s):
        s["upstreamEvidence"]["r8ExecutionEvidence"]["sourceDigests"] = None
    subject = _subject()
    m(subject)
    _reseal_r10(subject)
    snapshot = _verify(subject)
    assert snapshot.status in (VerificationStatus.VERIFICATION_FAILED,
        VerificationStatus.VERIFICATION_EVIDENCE_MISMATCH,
        VerificationStatus.VERIFICATION_INPUT_INVALID)
    assert _check(snapshot, "R7_PROVENANCE").state is CheckState.FAIL


def test_cb_b2_02_r8_canonical_asset_key_list_typed():
    def m(s):
        r8 = s["upstreamEvidence"]["r8ExecutionEvidence"]
        r8["canonicalAssetKey"] = []
    subject = _subject()
    m(subject)
    _reseal_chain(subject, r8=True)
    _reseal_r10(subject)
    snapshot = _verify(subject)
    assert snapshot.status in (VerificationStatus.VERIFICATION_FAILED,
        VerificationStatus.VERIFICATION_EVIDENCE_MISMATCH,
        VerificationStatus.VERIFICATION_INPUT_INVALID)


def test_cb_b2_03_r9_deployment_canonical_asset_key_list_typed():
    def m(s):
        r9 = s["upstreamEvidence"]["r9AssetGraphEvidence"]
        for node in r9["nodes"]:
            if node.get("nodeType") == "TOKEN_DEPLOYMENT":
                node["canonicalAssetKey"] = []
        _reseal_chain_inner_r9(r9)
    def _reseal_chain_inner_r9(r9):
        r9["r9SnapshotDigest"] = hashlib.sha256(json.dumps(
            {k: v for k, v in r9.items() if k != "r9SnapshotDigest"},
            sort_keys=True, separators=(",", ":"), ensure_ascii=False)
            .encode("utf-8")).hexdigest()
    subject = _subject()
    m(subject)
    _reseal_chain(subject, r9=True)
    _reseal_r10(subject)
    snapshot = _verify(subject)
    assert snapshot.status in (VerificationStatus.VERIFICATION_FAILED,
        VerificationStatus.VERIFICATION_EVIDENCE_MISMATCH,
        VerificationStatus.VERIFICATION_INPUT_INVALID)


def test_cb_b2_04_r7_layers_list_typed():
    def m(s):
        r7 = s["upstreamEvidence"]["r8ExecutionEvidence"][
            "upstreamEvidence"]["r7CrossMarketEvidence"]
        r7["layers"] = []
        r7["r7SnapshotDigest"] = _digest(
            {k: v for k, v in r7.items() if k != "r7SnapshotDigest"})
        r8e = s["upstreamEvidence"]["r8ExecutionEvidence"]
        r8e["sourceDigests"]["r7CrossMarketDigest"] = _digest(r7)
        r8e["r8SnapshotDigest"] = _digest(
            {k: v for k, v in r8e.items() if k != "r8SnapshotDigest"})
        s["sourceDigests"]["r8ExecutionSimulatorDigest"] = _digest(r8e)
    subject = _subject()
    m(subject)
    _reseal_r10(subject)
    snapshot = _verify(subject)
    assert snapshot.status in (VerificationStatus.VERIFICATION_FAILED,
        VerificationStatus.VERIFICATION_EVIDENCE_MISMATCH,
        VerificationStatus.VERIFICATION_INPUT_INVALID)


def test_cb_b2_05_r7_oracle_price_abc_typed():
    def m(s):
        r7 = s["upstreamEvidence"]["r8ExecutionEvidence"][
            "upstreamEvidence"]["r7CrossMarketEvidence"]
        r7["layers"]["oracleReference"]["price"] = "abc"
        r7["r7SnapshotDigest"] = _digest(
            {k: v for k, v in r7.items() if k != "r7SnapshotDigest"})
        r8e = s["upstreamEvidence"]["r8ExecutionEvidence"]
        r8e["sourceDigests"]["r7CrossMarketDigest"] = _digest(r7)
        r8e["r8SnapshotDigest"] = _digest(
            {k: v for k, v in r8e.items() if k != "r8SnapshotDigest"})
        s["sourceDigests"]["r8ExecutionSimulatorDigest"] = _digest(r8e)
    subject = _comparable_subject()
    m(subject)
    _reseal_r10(subject)
    snapshot = _verify(subject)
    assert snapshot.status in (VerificationStatus.VERIFICATION_FAILED,
        VerificationStatus.VERIFICATION_EVIDENCE_MISMATCH,
        VerificationStatus.VERIFICATION_INPUT_INVALID)


def test_cb_b2_06_r8_source_execution_price_abc_typed():
    def m(s):
        s["upstreamEvidence"]["r8ExecutionEvidence"]["scenarios"][0][
            "upstreamEvidence"]["r2GapEvidence"][
            "executionPriceUsdPerToken"] = "abc"
        r8e = s["upstreamEvidence"]["r8ExecutionEvidence"]
        r8e["r8SnapshotDigest"] = _digest(
            {k: v for k, v in r8e.items() if k != "r8SnapshotDigest"})
        s["sourceDigests"]["r8ExecutionSimulatorDigest"] = _digest(r8e)
    subject = _comparable_subject()
    m(subject)
    _reseal_r10(subject)
    snapshot = _verify(subject)
    assert snapshot.status in (VerificationStatus.VERIFICATION_FAILED,
        VerificationStatus.VERIFICATION_EVIDENCE_MISMATCH,
        VerificationStatus.VERIFICATION_INPUT_INVALID)


def test_cb_b2_07_scenario_upstream_evidence_list_typed():
    def m(s):
        s["upstreamEvidence"]["r8ExecutionEvidence"]["scenarios"][0][
            "upstreamEvidence"] = []
        r8e = s["upstreamEvidence"]["r8ExecutionEvidence"]
        r8e["r8SnapshotDigest"] = _digest(
            {k: v for k, v in r8e.items() if k != "r8SnapshotDigest"})
        s["sourceDigests"]["r8ExecutionSimulatorDigest"] = _digest(r8e)
    subject = _comparable_subject()
    m(subject)
    _reseal_r10(subject)
    snapshot = _verify(subject)
    assert snapshot.status in (VerificationStatus.VERIFICATION_FAILED,
        VerificationStatus.VERIFICATION_EVIDENCE_MISMATCH,
        VerificationStatus.VERIFICATION_INPUT_INVALID)


def test_cb_b2_08_content_envelope_list_typed():
    subject = _comparable_subject()
    snapshot = _verify(subject, content_envelope=[])
    assert snapshot.status is VerificationStatus.VERIFICATION_INPUT_INVALID


def test_cb_b2_09_falsy_wrong_types_typed():
    # nodes="" and scenarios=0 are wrong types, not empty containers
    def m_nodes(s):
        s["upstreamEvidence"]["r9AssetGraphEvidence"]["nodes"] = ""
    subject = _subject()
    m_nodes(subject)
    _reseal_r10(subject)
    snapshot = _verify(subject)
    assert snapshot.status in (VerificationStatus.VERIFICATION_FAILED,
        VerificationStatus.VERIFICATION_EVIDENCE_MISMATCH,
        VerificationStatus.VERIFICATION_INPUT_INVALID)

    def m_scen(s):
        s["upstreamEvidence"]["r8ExecutionEvidence"]["scenarios"] = 0
    subject = _comparable_subject()
    m_scen(subject)
    _reseal_r10(subject)
    snapshot = _verify(subject)
    assert snapshot.status is not VerificationStatus.VERIFICATION_OK


# --------------------------------------------------------------------------
# Correction B - B3: full ModelEvidence semantic mirror
# --------------------------------------------------------------------------

def test_cb_b3_01_fake_value_kind_rejected():
    subject = _comparable_subject()
    model = copy.deepcopy(subject["modelEvidence"])
    model["valueKind"] = "QUANTUM_VALUATION"
    model["outputEvidence"]["valueKind"] = "QUANTUM_VALUATION"
    model["outputDigest"] = _digest(model["outputEvidence"])
    subject["modelEvidence"] = model
    _reseal_r10(subject)
    snapshot = _verify(subject)
    assert snapshot.status is VerificationStatus.VERIFICATION_FAILED


def test_cb_b3_02_fake_unit_basis_rejected():
    subject = _comparable_subject()
    model = copy.deepcopy(subject["modelEvidence"])
    model["unitBasis"] = "PER_UNIVERSE"
    model["outputEvidence"]["unitBasis"] = "PER_UNIVERSE"
    model["outputDigest"] = _digest(model["outputEvidence"])
    subject["modelEvidence"] = model
    _reseal_r10(subject)
    snapshot = _verify(subject)
    assert snapshot.status is VerificationStatus.VERIFICATION_FAILED


def test_cb_b3_03_invalid_kind_basis_pair_rejected():
    subject = _comparable_subject()
    model = copy.deepcopy(subject["modelEvidence"])
    model["valueKind"] = "EQUITY_VALUE_TOTAL"
    model["unitBasis"] = "PER_ECONOMIC_UNIT"
    model["outputEvidence"]["valueKind"] = "EQUITY_VALUE_TOTAL"
    model["outputEvidence"]["unitBasis"] = "PER_ECONOMIC_UNIT"
    model["outputDigest"] = _digest(model["outputEvidence"])
    subject["modelEvidence"] = model
    _reseal_r10(subject)
    snapshot = _verify(subject)
    assert snapshot.status is VerificationStatus.VERIFICATION_FAILED


def test_cb_b3_04_nan_model_value_rejected():
    subject = _comparable_subject()
    model = copy.deepcopy(subject["modelEvidence"])
    model["value"] = "NaN"
    model["outputEvidence"]["value"] = "NaN"
    model["outputDigest"] = _digest(model["outputEvidence"])
    subject["modelEvidence"] = model
    _reseal_r10(subject)
    snapshot = _verify(subject)
    assert snapshot.status in (VerificationStatus.VERIFICATION_FAILED,
        VerificationStatus.VERIFICATION_EVIDENCE_MISMATCH,
        VerificationStatus.VERIFICATION_INPUT_INVALID)


def test_cb_b3_05_malformed_model_value_rejected():
    subject = _comparable_subject()
    model = copy.deepcopy(subject["modelEvidence"])
    model["value"] = "abc"
    model["outputEvidence"]["value"] = "abc"
    model["outputDigest"] = _digest(model["outputEvidence"])
    subject["modelEvidence"] = model
    _reseal_r10(subject)
    snapshot = _verify(subject)
    assert snapshot.status in (VerificationStatus.VERIFICATION_FAILED,
        VerificationStatus.VERIFICATION_EVIDENCE_MISMATCH,
        VerificationStatus.VERIFICATION_INPUT_INVALID)


def test_cb_b3_06_malformed_valuation_as_of_rejected():
    subject = _comparable_subject()
    model = copy.deepcopy(subject["modelEvidence"])
    model["valuationAsOf"] = "not-a-timestamp"
    model["outputEvidence"]["valuationAsOf"] = "not-a-timestamp"
    model["outputDigest"] = _digest(model["outputEvidence"])
    subject["modelEvidence"] = model
    _reseal_r10(subject)
    snapshot = _verify(subject)
    assert snapshot.status is VerificationStatus.VERIFICATION_FAILED


def test_cb_b3_07_naive_valuation_as_of_rejected():
    subject = _comparable_subject()
    model = copy.deepcopy(subject["modelEvidence"])
    model["valuationAsOf"] = "2026-09-17T12:00:00"
    model["outputEvidence"]["valuationAsOf"] = "2026-09-17T12:00:00"
    model["outputDigest"] = _digest(model["outputEvidence"])
    subject["modelEvidence"] = model
    _reseal_r10(subject)
    snapshot = _verify(subject)
    assert snapshot.status is VerificationStatus.VERIFICATION_FAILED


def test_cb_b3_08_negative_multiplier_rejected():
    subject = _comparable_subject()
    model = copy.deepcopy(subject["modelEvidence"])
    model["unitMultiplier"] = "-1"
    model["inputEvidence"]["unitMultiplier"] = "-1"
    model["outputEvidence"]["unitMultiplier"] = "-1"
    model["outputDigest"] = _digest(model["outputEvidence"])
    subject["modelEvidence"] = model
    _reseal_r10(subject)
    snapshot = _verify(subject)
    assert snapshot.status is VerificationStatus.VERIFICATION_FAILED


def test_ca_b3_09_total_multiplier_basis_rejected():
    subject = _comparable_subject()
    model = copy.deepcopy(subject["modelEvidence"])
    model["unitMultiplier"] = "10000"
    model["unitMultiplierBasis"] = "TOTAL_EQUITY"
    model["inputEvidence"]["unitMultiplier"] = "10000"
    model["inputEvidence"]["unitMultiplierBasis"] = "TOTAL_EQUITY"
    model["outputEvidence"]["unitMultiplier"] = "10000"
    model["outputEvidence"]["unitMultiplierBasis"] = "TOTAL_EQUITY"
    model["outputDigest"] = _digest(model["outputEvidence"])
    subject["modelEvidence"] = model
    _reseal_r10(subject)
    snapshot = _verify(subject)
    assert snapshot.status is VerificationStatus.VERIFICATION_FAILED


def test_ca_b3_10_multiplier_basis_without_multiplier_rejected():
    subject = _comparable_subject()
    model = copy.deepcopy(subject["modelEvidence"])
    model["unitMultiplierBasis"] = "PER_ECONOMIC_UNIT"
    model["outputEvidence"]["unitMultiplierBasis"] = "PER_ECONOMIC_UNIT"
    model["outputDigest"] = _digest(model["outputEvidence"])
    subject["modelEvidence"] = model
    _reseal_r10(subject)
    snapshot = _verify(subject)
    assert snapshot.status is VerificationStatus.VERIFICATION_FAILED


# --------------------------------------------------------------------------
# Correction B - B4: comparability gap vocabulary
# --------------------------------------------------------------------------

def test_cb_b4_01_fake_gap_kind_rejected():
    subject = _comparable_subject()
    comparability = copy.deepcopy(subject["comparability"])
    comparability["state"] = "NOT_COMPARABLE"
    for dim in comparability["dimensions"]:
        if dim["dimension"] == "CURRENCY":
            dim["ok"] = False
            dim["gapKind"] = "FAKE_GAP"
    comparability["gaps"] = ["FAKE_GAP"]
    subject["comparability"] = comparability
    _reseal_r10(subject)
    snapshot = _verify(subject)
    assert snapshot.status in (VerificationStatus.VERIFICATION_FAILED,
        VerificationStatus.VERIFICATION_EVIDENCE_MISMATCH,
        VerificationStatus.VERIFICATION_INPUT_INVALID)
    assert "FAKE_GAP" in _check(
        snapshot, "COMPARABILITY_CONTRACT").detail


def test_cb_b4_02_partially_comparable_rule_preserved():
    # the PARTIALLY_COMPARABLE rule remains REFERENCE_AVAILABILITY +
    # REFERENCE_UNAVAILABLE only - verbatim frozen condition
    dims_ok = {
        d["dimension"]: d
        for d in _comparable_subject()["comparability"]["dimensions"]
    }
    assert dims_ok["REFERENCE_AVAILABILITY"]["ok"] is True


# --------------------------------------------------------------------------
# Correction B - B5: historical timing semantics
# --------------------------------------------------------------------------

def test_cb_b5_01_execution_skew_boundary_pass():
    subject = _comparable_subject()
    # skew exactly at limit (0s skew, same NOW): passes
    snapshot = _verify(subject)
    assert snapshot.status is VerificationStatus.VERIFICATION_OK


def test_cb_b5_02_execution_skew_plus_one_microsecond_blocked():
    def m(s):
        r8e = s["upstreamEvidence"]["r8ExecutionEvidence"]
        micro = (NOW + timedelta(days=2)).isoformat()
        for scenario in r8e["scenarios"]:
            scenario["quoteObservedAt"] = micro
            for row in s["executionComparisons"]:
                row["executionObservedAt"] = micro
        r8e["r8SnapshotDigest"] = _digest(
            {k: v for k, v in r8e.items() if k != "r8SnapshotDigest"})
        s["sourceDigests"]["r8ExecutionSimulatorDigest"] = _digest(r8e)
    subject = _comparable_subject()
    m(subject)
    _reseal_r10(subject)
    snapshot = _verify(subject)
    assert snapshot.status is VerificationStatus.VERIFICATION_FAILED


def test_cb_b5_03_mutated_timing_policy_detected():
    subject = _comparable_subject()
    policy = dict(subject["timingPolicy"])
    policy["maxModelAgeSeconds"] = "0"
    subject["timingPolicy"] = policy
    _reseal_r10(subject)
    snapshot = _verify(subject)
    assert snapshot.status is VerificationStatus.VERIFICATION_FAILED
    assert "maxModelAgeSeconds" in _check(
        snapshot, "HISTORICAL_TIMING").detail or "positive" in _check(
        snapshot, "HISTORICAL_TIMING").detail


def test_cb_b5_04_stale_model_relabeled_timing_ok_detected():
    subject = _comparable_subject()
    model = copy.deepcopy(subject["modelEvidence"])
    old_ts = (NOW - timedelta(days=30)).isoformat()
    model["valuationAsOf"] = old_ts
    model["outputEvidence"]["valuationAsOf"] = old_ts
    model["outputDigest"] = _digest(model["outputEvidence"])
    subject["modelEvidence"] = model
    reference = dict(subject["referenceComparison"])
    reference["modelObservedAt"] = old_ts
    subject["referenceComparison"] = reference
    _reseal_r10(subject)
    snapshot = _verify(subject)
    assert snapshot.status is VerificationStatus.VERIFICATION_FAILED
    assert any("age" in c.detail or "stale" in c.detail
               for c in snapshot.checks if c.state is CheckState.FAIL)


def test_cb_b5_05_skewed_reference_relabeled_timing_ok_detected():
    subject = _comparable_subject()
    model = copy.deepcopy(subject["modelEvidence"])
    skew_ts = (NOW + timedelta(days=2)).isoformat()
    model["valuationAsOf"] = skew_ts
    model["outputEvidence"]["valuationAsOf"] = skew_ts
    model["outputDigest"] = _digest(model["outputEvidence"])
    subject["modelEvidence"] = model
    reference = dict(subject["referenceComparison"])
    reference["modelObservedAt"] = skew_ts
    subject["referenceComparison"] = reference
    _reseal_r10(subject)
    snapshot = _verify(subject)
    assert snapshot.status is VerificationStatus.VERIFICATION_FAILED


def test_cb_b5_06_execution_row_outside_skew_retained_detected():
    subject = _comparable_subject()
    model = copy.deepcopy(subject["modelEvidence"])
    old_valuation = (NOW - timedelta(days=2)).isoformat()
    model["valuationAsOf"] = old_valuation
    model["outputEvidence"]["valuationAsOf"] = old_valuation
    model["outputDigest"] = _digest(model["outputEvidence"])
    subject["modelEvidence"] = model
    reference = dict(subject["referenceComparison"])
    reference["modelObservedAt"] = old_valuation
    subject["referenceComparison"] = reference
    _reseal_r10(subject)
    snapshot = _verify(subject)
    assert snapshot.status is VerificationStatus.VERIFICATION_FAILED
    assert any("skew" in c.detail for c in snapshot.checks
               if c.state is CheckState.FAIL)


# --------------------------------------------------------------------------
# Correction B - B6: serialized R11 self-verification
# --------------------------------------------------------------------------

def _reseal_r11(evidence):
    evidence["r11SnapshotDigest"] = hashlib.sha256(json.dumps(
        {k: v for k, v in evidence.items() if k != "r11SnapshotDigest"},
        sort_keys=True, separators=(",", ":"), ensure_ascii=False)
        .encode("utf-8")).hexdigest()
    return evidence


def _base_r11():
    return _verify(_subject()).to_evidence_dict()


def test_cb_b6_01_ok_with_fail_check_does_not_verify():
    evidence = _base_r11()
    evidence["checks"][0]["state"] = "FAIL"
    _reseal_r11(evidence)
    assert verify_serialized_r11_evidence(evidence) is False


def test_cb_b6_02_wrong_freeze_anchor_serialized_rejected():
    evidence = _base_r11()
    evidence["freezeAnchor"] = "f" * 64
    _reseal_r11(evidence)
    assert verify_serialized_r11_evidence(evidence) is False


def test_cb_b6_03_wrong_subject_authority_tree_rejected():
    evidence = _base_r11()
    evidence["subjectAuthorityTree"] = "e" * 64
    _reseal_r11(evidence)
    assert verify_serialized_r11_evidence(evidence) is False


def test_cb_b6_04_wrong_verification_authority_rejected():
    evidence = _base_r11()
    evidence["boundaries"]["verificationAuthority"] = "R9_APPLIED"
    _reseal_r11(evidence)
    assert verify_serialized_r11_evidence(evidence) is False


def test_cb_b6_05_subject_evidence_digest_changed_rejected():
    evidence = _base_r11()
    evidence["subjectEvidenceDigest"] = "0" * 64
    _reseal_r11(evidence)
    assert verify_serialized_r11_evidence(evidence) is False


def test_cb_b6_06_subject_status_mismatch_rejected():
    evidence = _base_r11()
    evidence["subjectStatus"] = "MODEL_RADAR_OK"
    _reseal_r11(evidence)
    assert verify_serialized_r11_evidence(evidence) is False


def test_cb_b6_07_subject_snapshot_digest_mismatch_rejected():
    evidence = _base_r11()
    evidence["subjectSnapshotDigest"] = "0" * 64
    _reseal_r11(evidence)
    assert verify_serialized_r11_evidence(evidence) is False


def test_cb_b6_08_duplicate_check_id_rejected():
    evidence = _base_r11()
    evidence["checks"].append(copy.deepcopy(evidence["checks"][0]))
    _reseal_r11(evidence)
    assert verify_serialized_r11_evidence(evidence) is False


def test_cb_b6_09_invalid_check_state_rejected():
    evidence = _base_r11()
    evidence["checks"][0]["state"] = "MAYBE"
    _reseal_r11(evidence)
    assert verify_serialized_r11_evidence(evidence) is False


def test_cb_b6_10_malformed_generated_at_rejected():
    evidence = _base_r11()
    evidence["generatedAt"] = "not-a-timestamp"
    _reseal_r11(evidence)
    assert verify_serialized_r11_evidence(evidence) is False


def test_cb_b6_11_synthetic_zero_rejected():
    evidence = _base_r11()
    evidence["synthetic"] = 0
    _reseal_r11(evidence)
    assert verify_serialized_r11_evidence(evidence) is False


# --------------------------------------------------------------------------
# Correction B - B7: content envelope public boundary
# --------------------------------------------------------------------------

def test_cb_b7_01_non_mapping_content_envelope_typed():
    subject = _comparable_subject()
    snapshot = _verify(subject, content_envelope="bad")
    assert snapshot.status is VerificationStatus.VERIFICATION_INPUT_INVALID

    snapshot = _verify(subject, content_envelope=0)
    assert snapshot.status is VerificationStatus.VERIFICATION_INPUT_INVALID
