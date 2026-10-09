"""F0-P1: developer Project Uses in committed Run Integrity (economic outputs unchanged).

Uses real canonical Solar/Wind runs and the same JSON evidence contract as the
committed Last Run. No mock KPI dictionaries and no reference-fixture changes.
"""
from __future__ import annotations

import copy
import json
from dataclasses import asdict, replace
from datetime import date

import pytest

from app.project_factories import create_generic_solar_reference, create_generic_wind_reference
from app.run_integrity import (
    CheckStatus,
    OverallStatus,
    build_run_integrity_evidence,
    evidence_digest,
    run_integrity_checks,
)
from app.run_integrity.checks import check_sources_equal_uses
from app.services.production_financial_authority import run_clean_production
from finco_core.inputs import (
    DevelopmentEconomicsInput,
    DevelopmentSpendEntry,
    hash_inputs_for_cache,
    project_inputs_to_dict,
)
from financial_engine.financing.generic_product_policy import build_sources_and_uses


# These are real synthetic reference inputs. Small developer uses avoid changing
# bankability assumptions merely to exercise the check. Each model is run once.
CASES = (
    ("solar_baseline", "solar", 0.0, 0.0),
    ("wind_baseline", "wind", 0.0, 0.0),
    ("solar_reimbursement", "solar", 120.0, 0.0),
    ("wind_fee", "wind", 0.0, 80.0),
    ("solar_both", "solar", 120.0, 80.0),
)

_LEGACY_USE_KEYS = (
    "base_project_capex_keur",
    "capitalized_idc_keur",
    "commitment_fee_keur",
    "structuring_fee_keur",
    "other_financing_costs_keur",
    "initial_dsra_funding_keur",
    "other_uses_keur",
)
_DEVELOPER_KEYS = ("development_cost_reimbursement_keur", "developer_fee_keur")


def _committed(payload):
    """Round-trip through the persisted JSON representation, retaining the digest."""
    return json.loads(json.dumps(payload))


def _reseal(payload):
    payload["digest"] = evidence_digest(payload)
    return payload


def _check(report):
    return next(c for c in report.checks if c.check_id == "SOURCES_EQUAL_USES")


@pytest.fixture(scope="module")
def canonical_cases():
    results = {}
    for name, kind, reimbursement, fee in CASES:
        inputs = (create_generic_solar_reference() if kind == "solar"
                  else create_generic_wind_reference())
        if reimbursement or fee:
            development = DevelopmentEconomicsInput(
                enabled=True,
                spend_schedule=(DevelopmentSpendEntry(date(2029, 3, 31), 250.0),),
                reimbursed_development_cost_keur=reimbursement,
                developer_fee_value=fee,
            )
            inputs = replace(inputs, development_economics=development)
        input_fingerprint = hash_inputs_for_cache(inputs)
        input_payload = project_inputs_to_dict(inputs)
        run = run_clean_production(inputs, "Base", project_type=kind)
        evidence = _committed(build_run_integrity_evidence(run))
        results[name] = {
            "inputs": inputs,
            "fingerprint": input_fingerprint,
            "input_payload": input_payload,
            "run": run,
            "evidence": evidence,
            "reimbursement": reimbursement,
            "fee": fee,
        }
    return results


@pytest.mark.parametrize("name", [row[0] for row in CASES])
def test_canonical_sources_uses_integrity_and_zero_economic_mutation(canonical_cases, name):
    case = canonical_cases[name]
    run = case["run"]
    financing = run.g2c_result.financing_result
    before_financing = repr(financing)
    before_evidence = copy.deepcopy(case["evidence"])
    su = case["evidence"]["sources_uses"]["summary"]
    canonical_su = asdict(build_sources_and_uses(financing))

    # The same unrounded canonical S&U result is preserved in committed evidence.
    for key in ("total_uses_keur", "total_sources_keur", *_DEVELOPER_KEYS):
        assert su[key] == pytest.approx(canonical_su[key], abs=1e-9)
    assert su["total_uses_keur"] == pytest.approx(
        financing.project_uses.total_project_uses_keur, abs=1e-6)
    assert su["total_sources_keur"] == pytest.approx(su["total_uses_keur"], abs=1e-6)
    assert su[_DEVELOPER_KEYS[0]] == case["reimbursement"]
    assert su[_DEVELOPER_KEYS[1]] == case["fee"]
    assert sum(su[k] for k in (*_LEGACY_USE_KEYS, *_DEVELOPER_KEYS)) == pytest.approx(
        su["total_uses_keur"], abs=1e-6)

    # Independently demonstrate the pre-fix discrepancy on real canonical runs.
    uncorrected_residual = su["total_uses_keur"] - sum(su[k] for k in _LEGACY_USE_KEYS)
    assert uncorrected_residual == pytest.approx(
        case["reimbursement"] + case["fee"], abs=1e-6)

    report = run_integrity_checks(case["evidence"])
    assert _check(report).status is CheckStatus.PASS, _check(report).to_dict()
    assert report.overall is OverallStatus.PASS, [
        c.to_dict() for c in report.checks if c.status is not CheckStatus.PASS]
    assert case["evidence"] == before_evidence
    assert repr(financing) == before_financing
    assert project_inputs_to_dict(case["inputs"]) == case["input_payload"]
    assert hash_inputs_for_cache(case["inputs"]) == case["fingerprint"]


@pytest.mark.parametrize("field", _DEVELOPER_KEYS)
def test_changed_developer_component_without_changed_total_fails(canonical_cases, field):
    evidence = copy.deepcopy(canonical_cases["solar_both"]["evidence"])
    evidence["sources_uses"]["summary"][field] += 1.0
    result = _check(run_integrity_checks(_reseal(evidence)))
    assert result.status is CheckStatus.FAIL
    assert result.reason_code == "SOURCES_USES_MISMATCH"


@pytest.mark.parametrize("field", ("total_uses_keur", "total_sources_keur"))
def test_corrupted_canonical_total_fails(canonical_cases, field):
    evidence = copy.deepcopy(canonical_cases["solar_both"]["evidence"])
    evidence["sources_uses"]["summary"][field] += 1.0
    result = _check(run_integrity_checks(_reseal(evidence)))
    assert result.status is CheckStatus.FAIL
    assert result.reason_code == "SOURCES_USES_MISMATCH"


@pytest.mark.parametrize("field", _DEVELOPER_KEYS)
def test_missing_developer_field_does_not_imply_zero(canonical_cases, field):
    evidence = copy.deepcopy(canonical_cases["solar_both"]["evidence"])
    del evidence["sources_uses"]["summary"][field]
    result = _check(run_integrity_checks(_reseal(evidence)))
    assert result.status is CheckStatus.UNAVAILABLE
    assert result.reason_code == "DEVELOPER_USES_EVIDENCE_MISSING"


@pytest.mark.parametrize("field", _DEVELOPER_KEYS)
@pytest.mark.parametrize("value", (None, "80", True, -1.0, float("nan"), float("inf"), -float("inf")))
def test_malformed_developer_component_never_passes(canonical_cases, field, value):
    evidence = copy.deepcopy(canonical_cases["solar_both"]["evidence"])
    evidence["sources_uses"]["summary"][field] = value
    result = _check(run_integrity_checks(_reseal(evidence)))
    assert result.status is CheckStatus.UNAVAILABLE
    assert result.reason_code == "DEVELOPER_USES_EVIDENCE_INVALID"


def test_historical_v1_evidence_missing_fields_is_preserved_but_unavailable(canonical_cases):
    # Simulate a genuine old persisted V1 shape; its digest was set when the
    # bytes were committed. Never rewrite it, borrow current inputs or assume 0.
    evidence = copy.deepcopy(canonical_cases["solar_baseline"]["evidence"])
    for field in _DEVELOPER_KEYS:
        del evidence["sources_uses"]["summary"][field]
    _reseal(evidence)
    original = copy.deepcopy(evidence)
    digest = evidence["digest"]

    report = run_integrity_checks(evidence)
    assert next(c for c in report.checks if c.check_id == "EVIDENCE_DIGEST").status is CheckStatus.PASS
    assert _check(report).status is CheckStatus.UNAVAILABLE
    assert _check(report).reason_code == "DEVELOPER_USES_EVIDENCE_MISSING"
    assert report.overall is OverallStatus.INCOMPLETE
    assert evidence == original and evidence["digest"] == digest


def test_construction_period_funding_residual_still_fails(canonical_cases):
    evidence = copy.deepcopy(canonical_cases["solar_both"]["evidence"])
    periods = evidence["sources_uses"]["construction_periods"]
    assert periods, "a real financed case must provide construction-period evidence"
    periods[0]["sources"] += 1.0
    result = _check(run_integrity_checks(_reseal(evidence)))
    assert result.status is CheckStatus.FAIL
    assert result.reason_code == "SOURCES_USES_MISMATCH"


def test_current_zero_is_genuine_zero_and_not_missing(canonical_cases):
    for name in ("solar_baseline", "wind_baseline"):
        evidence = canonical_cases[name]["evidence"]
        su = evidence["sources_uses"]["summary"]
        assert all(k in su and su[k] == 0.0 for k in _DEVELOPER_KEYS)
        assert check_sources_equal_uses(evidence).status is CheckStatus.PASS


def test_integrity_check_has_no_engine_execution(canonical_cases, monkeypatch):
    import app.services.production_financial_authority as authority

    def forbidden(*args, **kwargs):
        raise AssertionError("Run Integrity must not re-execute financial models")

    monkeypatch.setattr(authority, "run_clean_production", forbidden)
    committed = canonical_cases["solar_both"]["evidence"]
    before = copy.deepcopy(committed)
    assert _check(run_integrity_checks(committed)).status is CheckStatus.PASS
    assert committed == before
