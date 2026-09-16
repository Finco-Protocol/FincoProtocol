"""Cross-surface verification tests for FINCO Protocol.

All evidence is deterministic and synthetic. No network access is used.
"""
from __future__ import annotations

from copy import deepcopy
from decimal import Decimal
from functools import lru_cache

from app.api.project_runner import run_project
from app.project_factories import create_generic_solar_reference
from finco_protocol.verification.envelope import (
    build_evidence_envelope,
    canonical_sha256,
    verify_evidence_envelope,
)
from finco_protocol.verification.model import validate_model_run
from finco_protocol.verification.public_corpus import (
    build_public_validation_corpus,
    verify_public_validation_corpus,
)
from finco_protocol.verification.radar_r3 import validate_radar_r3_evidence
from finco_radar.liquidity.engine import BUY_SIZE_PAIR


@lru_cache(maxsize=1)
def _cached_public_corpus() -> dict:
    return build_public_validation_corpus()


@lru_cache(maxsize=1)
def _cached_model_payload() -> dict:
    return run_project(
        "Solar",
        "Base",
        project_inputs_override=create_generic_solar_reference(),
    )


def _radar_evidence() -> dict:
    corpus = _cached_public_corpus()
    return deepcopy(corpus["cases"][2]["envelope"]["payload"]["r3Evidence"])


def _corpus_body(corpus: dict) -> dict:
    return {
        "schema": corpus.get("schema"),
        "sanitization": corpus.get("sanitization"),
        "cases": corpus.get("cases"),
    }


def _failure_ids(report) -> set[str]:
    return {failure.invariant_id for failure in report.failures}


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


def test_evidence_envelope_fails_closed_on_invalid_metadata():
    envelope = build_evidence_envelope(
        surface="TEST_SURFACE",
        evidence_type="TEST_EVIDENCE",
        payload={"metric": "12.345"},
        authority_refs=("synthetic.authority",),
    ).as_dict()

    mutations = []
    missing_surface = deepcopy(envelope)
    missing_surface.pop("surface")
    mutations.append(missing_surface)

    blank_type = deepcopy(envelope)
    blank_type["evidenceType"] = "   "
    mutations.append(blank_type)

    wrong_refs_type = deepcopy(envelope)
    wrong_refs_type["authorityRefs"] = "synthetic.authority"
    mutations.append(wrong_refs_type)

    blank_ref = deepcopy(envelope)
    blank_ref["authorityRefs"] = ["synthetic.authority", ""]
    mutations.append(blank_ref)

    assert all(not verify_evidence_envelope(candidate) for candidate in mutations)


def test_model_verifier_fails_closed_on_missing_debt_period_field():
    payload = deepcopy(_cached_model_payload())
    assert validate_model_run(payload).passed

    fields = (
        "senior_principal_keur",
        "senior_interest_keur",
        "senior_ds_keur",
    )
    period = next(
        row
        for row in payload["debt_schedule"]["periods"]
        if row.get("is_operation") is True
        and all(row.get(field) is not None for field in fields)
    )
    period["senior_interest_keur"] = None

    report = validate_model_run(payload)
    assert not report.passed
    assert "MODEL_DEBT_SERVICE_IDENTITY" in _failure_ids(report)


def test_model_verifier_rejects_all_debt_service_fields_removed_from_active_debt_period():
    payload = deepcopy(_cached_model_payload())
    assert validate_model_run(payload).passed

    fields = (
        "senior_principal_keur",
        "senior_interest_keur",
        "senior_ds_keur",
    )
    period = next(
        row
        for row in payload["debt_schedule"]["periods"]
        if row.get("is_operation") is True
        and row.get("senior_balance_keur") is not None
        and Decimal(str(row["senior_balance_keur"])) > 0
        and all(row.get(field) is not None for field in fields)
    )
    for field in fields:
        period[field] = None

    report = validate_model_run(payload)
    assert not report.passed
    assert "MODEL_DEBT_SERVICE_IDENTITY" in _failure_ids(report)


def test_model_verifier_fails_closed_on_missing_balance_check():
    payload = deepcopy(_cached_model_payload())
    assert validate_model_run(payload).passed

    operation_dates = {
        row.get("date")
        for row in payload["debt_schedule"]["periods"]
        if row.get("is_operation") is True and row.get("date")
    }
    period = next(
        row
        for row in payload["financial_statements"]["balance_sheet"]["periods"]
        if row.get("date") in operation_dates
        and row.get("balance_check_keur") is not None
    )
    period["balance_check_keur"] = None

    report = validate_model_run(payload)
    assert not report.passed
    assert "MODEL_BALANCE_SHEET_BALANCES" in _failure_ids(report)


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


def test_public_validation_corpus_rejects_rehashed_duplicate_case():
    corpus = deepcopy(_cached_public_corpus())
    corpus["cases"][1] = deepcopy(corpus["cases"][0])
    corpus["corpusSha256"] = canonical_sha256(_corpus_body(corpus))

    assert not verify_public_validation_corpus(corpus)


def test_public_validation_corpus_rejects_outer_nested_surface_mismatch():
    corpus = deepcopy(_cached_public_corpus())
    corpus["cases"][0]["surface"] = "FINCO_RADAR_R3"
    corpus["corpusSha256"] = canonical_sha256(_corpus_body(corpus))

    assert not verify_public_validation_corpus(corpus)


def test_radar_r3_verifier_detects_spread_delta_tampering():
    evidence = _radar_evidence()
    evidence["spreadEvidence"]["executionSpreadDeltaBps"] = "999"

    report = validate_radar_r3_evidence(evidence)
    assert not report.passed
    assert "R3_SPREAD_DELTA_IDENTITY" in _failure_ids(report)


def test_radar_r3_verifier_requires_exact_temporal_pair_identities():
    evidence = _radar_evidence()
    observed = evidence["temporalEvidence"]["observedPairSkews"]
    preserved_value = observed.pop(BUY_SIZE_PAIR)
    observed["ARBITRARY_PAIR"] = preserved_value

    report = validate_radar_r3_evidence(evidence)
    assert not report.passed
    assert "R3_TEMPORAL_COHERENCE" in _failure_ids(report)


def test_radar_r3_verifier_rejects_quote_slot_side_mismatch():
    evidence = _radar_evidence()
    evidence["quoteMatrixEvidence"][0]["side"] = "SELL"

    report = validate_radar_r3_evidence(evidence)
    assert not report.passed
    assert "R3_EXACT_QUOTE_MATRIX" in _failure_ids(report)


def test_radar_r3_verifier_rejects_quote_slot_notional_mismatch():
    evidence = _radar_evidence()
    evidence["quoteMatrixEvidence"][0]["requestedNotionalUsd"] = "1000"

    report = validate_radar_r3_evidence(evidence)
    assert not report.passed
    assert "R3_EXACT_QUOTE_MATRIX" in _failure_ids(report)


def test_radar_r3_verifier_rejects_duplicated_cost_slot():
    evidence = _radar_evidence()
    evidence["costEvidence"][1] = deepcopy(evidence["costEvidence"][0])

    report = validate_radar_r3_evidence(evidence)
    assert not report.passed
    assert "R3_COST_EVIDENCE_FOUR_SLOTS" in _failure_ids(report)
