"""Cross-surface verification tests for FINCO Protocol.

All evidence is deterministic and synthetic.  No network access is used.
"""
from __future__ import annotations

from copy import deepcopy
from decimal import Decimal

from finco_protocol.verification.envelope import (
    build_evidence_envelope,
    canonical_sha256,
    verify_evidence_envelope,
)
from finco_protocol.verification.public_corpus import (
    build_public_validation_corpus,
    verify_public_validation_corpus,
)
from finco_protocol.verification.radar_r3 import validate_radar_r3_evidence


def test_canonical_digest_is_order_independent_and_decimal_exact():
    left = {
        "z": Decimal("1.2300"),
        "a": {"beta": 2, "alpha": True},
    }
    right = {
        "a": {"alpha": True, "beta": 2},
        "z": Decimal("1.2300"),
    }
    assert canonical_sha256(left) == canonical_sha256(right)


def test_evidence_envelope_detects_payload_tampering():
    envelope = build_evidence_envelope(
        surface="TEST_SURFACE",
        evidence_type="TEST_EVIDENCE",
        payload={"metric": "12.345", "state": "SOURCE_PROVEN"},
        authority_refs=("synthetic.authority",),
    )
    assert verify_evidence_envelope(envelope)

    tampered = envelope.as_dict()
    tampered["payload"]["metric"] = "12.346"
    assert not verify_evidence_envelope(tampered)


def test_public_validation_corpus_is_cross_surface_and_self_verifying():
    corpus = build_public_validation_corpus()
    assert verify_public_validation_corpus(corpus)
    assert [case["caseId"] for case in corpus["cases"]] == [
        "model-solar-base",
        "model-wind-base",
        "radar-r3-synthetic-liquidity",
    ]
    assert [case["surface"] for case in corpus["cases"]] == [
        "FINCO_MODEL",
        "FINCO_MODEL",
        "FINCO_RADAR_R3",
    ]
    assert all(case["synthetic"] is True for case in corpus["cases"])
    assert all(
        case["envelope"]["contentAddress"].startswith("sha256:")
        for case in corpus["cases"]
    )


def test_public_validation_corpus_is_reproducible():
    first = build_public_validation_corpus()
    second = build_public_validation_corpus()
    assert first == second
    assert first["corpusSha256"] == second["corpusSha256"]


def test_public_validation_corpus_detects_nested_tampering():
    corpus = build_public_validation_corpus()
    tampered = deepcopy(corpus)
    tampered["cases"][0]["envelope"]["payload"]["kpis"]["project_irr"] = 999
    assert not verify_public_validation_corpus(tampered)


def test_radar_r3_verifier_detects_spread_delta_tampering():
    corpus = build_public_validation_corpus()
    radar_claim = corpus["cases"][2]["envelope"]["payload"]
    evidence = deepcopy(radar_claim["r3Evidence"])
    evidence["spreadEvidence"]["executionSpreadDeltaBps"] = "999"

    report = validate_radar_r3_evidence(evidence)
    assert not report.passed
    assert "R3_SPREAD_DELTA_IDENTITY" in {
        failure.invariant_id for failure in report.failures
    }
