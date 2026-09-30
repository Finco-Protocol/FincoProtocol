"""Opus H-4b — Run Integrity Checks on the committed Last Run.

Run Integrity Checks are a separate authority from the Reference Regression Check
(MODEL_VALIDATION). They recompute internal identities from evidence recorded at commit;
they never re-run the model. These tests prove they PASS a real run and that each check
FAILS when the corresponding identity is corrupted (adversarial corruption of evidence).
"""
from __future__ import annotations

import copy
import json
import os
import re
from pathlib import Path
from types import SimpleNamespace

import pytest

from app import project_factories as pf
from app.run_integrity import (
    CheckStatus,
    OverallStatus,
    build_run_integrity_evidence,
    evidence_digest,
    run_integrity_checks,
)
from app.services.production_financial_authority import run_clean_production
from financial_engine.financing.generic_product_policy import (
    DISABLED_GENERIC_FINANCING_POLICY as OFF,
)

REPO = Path(__file__).resolve().parents[1]


def _committed(evidence):
    """What the persistence layer returns: the JSON round-trip of the recorded evidence."""
    return json.loads(json.dumps(evidence))


@pytest.fixture(scope="module")
def evidence_off():
    run = run_clean_production(pf.create_generic_solar_reference(), "Base",
                               project_type="solar", financing_policy=OFF)
    return _committed(build_run_integrity_evidence(run))


@pytest.fixture(scope="module")
def evidence_h1():
    run = run_clean_production(pf.create_generic_ev_charging_reference(), "Base",
                               project_type="ev_charging")
    return _committed(build_run_integrity_evidence(run))


def _reseal(evidence):
    evidence["digest"] = evidence_digest(evidence)
    return evidence


def _status(report, check_id):
    return next(c for c in report.checks if c.check_id == check_id)


# ── Real runs pass every check ──────────────────────────────────────────────

@pytest.mark.parametrize("fixture", ["evidence_off", "evidence_h1"])
def test_real_runs_pass_every_check(request, fixture):
    report = run_integrity_checks(request.getfixturevalue(fixture))
    assert report.overall is OverallStatus.PASS, [c.to_dict() for c in report.checks
                                                  if c.status is not CheckStatus.PASS]
    assert {c.check_id for c in report.checks} == {
        "EVIDENCE_DIGEST", "SOURCES_EQUAL_USES", "BALANCE_SHEET_BALANCES",
        "SENIOR_DEBT_ROLLFORWARD", "INTEREST_DEBT_SERVICE_CONSISTENCY",
        "DSCR_EQUALS_CFADS_OVER_DEBT_SERVICE", "NO_UNFUNDED_CASH_DEFICIT",
        "DSCR_SCULPTING_FEASIBLE", "SPONSOR_RETURN_INPUTS_RECONCILE"}
    assert all(c.evaluated > 0 for c in report.checks)


def test_h1_run_evidence_carries_financing_costs_and_dsra(evidence_h1):
    su = evidence_h1["sources_uses"]["summary"]
    assert su["capitalized_idc_keur"] > 0 and su["initial_dsra_funding_keur"] > 0
    assert su["structuring_fee_keur"] > 0 and su["commitment_fee_keur"] > 0


# ── Adversarial corruption: every check can FAIL ────────────────────────────

def _corrupt(evidence, mutate):
    corrupted = copy.deepcopy(evidence)
    mutate(corrupted)
    return _reseal(corrupted)  # re-seal so only the targeted identity is broken


def _first_operating_bs(ev):
    return next(r for r in ev["balance_sheet"]
                if isinstance(r.get("net_cit_payable"), (int, float))
                and isinstance(r.get("retained_earnings"), (int, float))
                and isinstance(r.get("legal_reserve"), (int, float)))


@pytest.mark.parametrize("check_id,reason,mutate", [
    ("SOURCES_EQUAL_USES", "SOURCES_USES_MISMATCH",
     lambda e: e["sources_uses"]["summary"].update(
         total_sources_keur=e["sources_uses"]["summary"]["total_sources_keur"] + 1.0,
         shareholder_loan_cash_keur=e["sources_uses"]["summary"]["shareholder_loan_cash_keur"] + 1.0)),
    ("BALANCE_SHEET_BALANCES", "BALANCE_SHEET_IMBALANCE",
     lambda e: _first_operating_bs(e).update(
         retained_earnings=_first_operating_bs(e)["retained_earnings"] + 5.0)),
    ("SENIOR_DEBT_ROLLFORWARD", "SENIOR_ROLLFORWARD_BREAK",
     lambda e: e["senior_debt"]["periods"][3].update(
         closing=e["senior_debt"]["periods"][3]["closing"] + 2.0)),
    ("SENIOR_DEBT_ROLLFORWARD", "SENIOR_ROLLFORWARD_BREAK",
     lambda e: e["senior_debt"]["periods"][0].update(
         opening=e["senior_debt"]["periods"][0]["opening"] + 10.0,
         closing=e["senior_debt"]["periods"][0]["closing"] + 10.0)),  # opening != commitment
    ("INTEREST_DEBT_SERVICE_CONSISTENCY", "INTEREST_OR_DEBT_SERVICE_MISMATCH",
     lambda e: e["senior_debt"]["periods"][2].update(annual_rate=0.09)),
    ("INTEREST_DEBT_SERVICE_CONSISTENCY", "INTEREST_OR_DEBT_SERVICE_MISMATCH",
     lambda e: e["senior_debt"]["periods"][2].update(
         debt_service=e["senior_debt"]["periods"][2]["debt_service"] + 3.0)),
    ("DSCR_EQUALS_CFADS_OVER_DEBT_SERVICE", "DSCR_MISMATCH",
     lambda e: e["senior_debt"]["periods"][2].update(reported_dscr=9.99)),
    ("NO_UNFUNDED_CASH_DEFICIT", "NEGATIVE_CASH_WITHOUT_FUNDING_SOURCE",
     lambda e: e["cash"][10].update(cash_after_senior_before_reserves=-5.0)),
    ("NO_UNFUNDED_CASH_DEFICIT", "NEGATIVE_CASH_WITHOUT_FUNDING_SOURCE",
     lambda e: _first_operating_bs(e).update(unrestricted_cash=-1.0)),
    ("DSCR_SCULPTING_FEASIBLE", "DSCR_SCULPTING_NOT_AUTHORITATIVE",
     lambda e: e["senior_debt"]["diagnostics"].update(termination_reason="DSCR_SCULPTING_INFEASIBLE",
                                                       is_authoritative=False)),
    ("DSCR_SCULPTING_FEASIBLE", "DSCR_SCULPTING_INFEASIBLE_SCHEDULE",
     lambda e: e["senior_debt"]["periods"][2].update(
         debt_service=e["senior_debt"]["periods"][2]["bank_cfads"])),  # DSCR 1.0 vs target 1.2
    ("SPONSOR_RETURN_INPUTS_RECONCILE", "SPONSOR_FLOW_COMPONENT_MISMATCH",
     lambda e: e["sponsor"]["periods"][0].update(
         share_capital=e["sponsor"]["periods"][0]["share_capital"] + 100.0)),
    ("SPONSOR_RETURN_INPUTS_RECONCILE", "XIRR_RECOMPUTATION_MISMATCH",
     lambda e: e["sponsor"]["reported"].update(total_sponsor_xirr=0.99)),
])
def test_each_check_fails_when_its_identity_is_corrupted(evidence_off, check_id, reason, mutate):
    report = run_integrity_checks(_corrupt(evidence_off, mutate))
    result = _status(report, check_id)
    assert result.status is CheckStatus.FAIL and result.reason_code == reason, result.to_dict()
    assert report.overall is OverallStatus.FAIL


def test_tampering_after_commit_is_detected_by_the_digest(evidence_off):
    tampered = copy.deepcopy(evidence_off)
    tampered["sources_uses"]["summary"]["total_uses_keur"] += 1.0  # not re-sealed
    report = run_integrity_checks(tampered)
    assert _status(report, "EVIDENCE_DIGEST").reason_code == "EVIDENCE_DIGEST_MISMATCH"
    assert report.overall is OverallStatus.FAIL


def test_unpaid_terminal_balance_fails_only_when_balloons_are_not_permitted():
    from app.run_integrity.checks import check_senior_rollforward

    def evidence(permit):
        return {"sources_uses": {"summary": {"senior_debt_keur": 100.0}},
                "senior_debt": {"permit_terminal_balloon": permit,
                                "periods": [{"opening": 100.0, "principal": 50.0, "closing": 50.0}]}}

    assert check_senior_rollforward(evidence(True)).status is CheckStatus.PASS
    result = check_senior_rollforward(evidence(False))
    assert result.status is CheckStatus.FAIL and result.reason_code == "SENIOR_TERMINAL_BALANCE_UNREPAID"


# ── Missing evidence is never PASS ──────────────────────────────────────────

@pytest.mark.parametrize("evidence", [None, {}, {"schema": "SOMETHING_ELSE"}])
def test_missing_or_foreign_evidence_is_incomplete_never_pass(evidence):
    report = run_integrity_checks(evidence)
    assert report.overall is OverallStatus.INCOMPLETE
    assert all(c.status is CheckStatus.UNAVAILABLE for c in report.checks)


@pytest.mark.parametrize("section", ["sources_uses", "senior_debt", "balance_sheet", "cash", "sponsor"])
def test_removing_a_section_makes_dependent_checks_unavailable(evidence_off, section):
    stripped = copy.deepcopy(evidence_off)
    del stripped[section]
    report = run_integrity_checks(_reseal(stripped))
    assert report.overall is not OverallStatus.PASS
    assert any(c.status is CheckStatus.UNAVAILABLE for c in report.checks)
    assert not any(c.status is CheckStatus.FAIL for c in report.checks)


def test_malformed_evidence_does_not_crash_or_pass(evidence_off):
    broken = copy.deepcopy(evidence_off)
    broken["senior_debt"]["periods"][0]["opening"] = "not-a-number"
    report = run_integrity_checks(_reseal(broken))
    assert report.overall is not OverallStatus.PASS


# ── Read-only, no model, separate authority ─────────────────────────────────

def test_checks_are_pure_and_never_run_the_model(evidence_off, monkeypatch):
    import app.services.production_financial_authority as authority

    def forbidden(*args, **kwargs):
        raise AssertionError("Run Integrity Checks must not run the model")

    monkeypatch.setattr(authority, "run_clean_production", forbidden)
    before = copy.deepcopy(evidence_off)
    report = run_integrity_checks(evidence_off)
    assert report.overall is OverallStatus.PASS
    assert evidence_off == before  # evidence is not mutated


def test_checks_module_has_no_engine_or_market_dependency():
    source = (REPO / "app/run_integrity/checks.py").read_text(encoding="utf-8")
    for forbidden in ("financial_engine", "run_clean_production", "run_project", "httpx",
                      "requests", "finco_radar", "app.verified", "app.model_validation",
                      "run_certificate"):
        assert forbidden not in source, forbidden


def test_authority_is_distinct_from_reference_regression_check():
    from app.run_integrity.contracts import AUTHORITY

    assert AUTHORITY == "RUN_INTEGRITY_CHECKS" and AUTHORITY != "MODEL_VALIDATION"
    router = (REPO / "app/api/v1_1/router.py").read_text(encoding="utf-8")
    assert '@router.get("/projects/{project_id}/validation")' in router
    assert '@router.get("/projects/{project_id}/integrity")' in router


# ── End to end: commit a real run, read integrity back over the API ─────────

@pytest.fixture(scope="module")
def committed_project(tmp_path_factory):
    from fastapi.testclient import TestClient

    from app.auth import COOKIE_NAME, create_session_token
    from app.persistence import db
    from app.services.reference_seed_service import create_reference_seeded_project
    import main_api
    import main_web

    db.DB_PATH = str(tmp_path_factory.mktemp("h4b") / "h4b.db")
    db.init_db()
    user = "h4b-user"
    record = create_reference_seeded_project(
        user_id=user, template_source="generic_solar_reference",
        requested_name="H4b Integrity", capacity_mw=64.0)
    cookies = {COOKIE_NAME: create_session_token(user_id=user, username="admin")}
    client = TestClient(main_web.app, raise_server_exceptions=True)
    api = TestClient(main_api.app, raise_server_exceptions=False)

    page = client.get(f"/v2/workbook?project={record.project_code}", cookies=cookies)
    content_hash = re.search(r'name="content_hash" value="([^"]+)"', page.text).group(1)
    version = re.search(r'name="workbook_version" value="([^"]+)"', page.text).group(1)
    before = api.get(f"/api/v1.1/projects/{record.project_id}/integrity", cookies=cookies)
    run = client.post("/v2/workbook/run",
                      data={"project": record.project_code, "content_hash": content_hash,
                            "workbook_version": version},
                      cookies=cookies, headers={"HX-Request": "true"})
    assert run.status_code == 200
    return SimpleNamespace(client=client, api=api, cookies=cookies, record=record, before=before, user=user)


def test_api_before_any_run_is_unavailable(committed_project):
    body = committed_project.before.json()
    assert committed_project.before.status_code == 200
    assert body["state"] == "UNAVAILABLE" and body["evidence"]["reason"] == "NO_COMMITTED_RUN"


def test_api_after_commit_passes_and_is_bound_to_the_last_run(committed_project):
    p = committed_project
    response = p.api.get(f"/api/v1.1/projects/{p.record.project_id}/integrity", cookies=p.cookies)
    assert response.status_code == 200
    body = response.json()
    assert body["state"] == "AVAILABLE"
    evidence = body["evidence"]
    assert evidence["authority"] == "RUN_INTEGRITY_CHECKS"
    assert evidence["overall"] == "PASS", [c for c in evidence["checks"] if c["status"] != "PASS"]
    assert evidence["run_identity"]["composite_hash"]
    assert "does not verify the asset" in evidence["scope"]


def test_api_requires_a_session_and_isolates_users(committed_project):
    from fastapi.testclient import TestClient
    import main_api

    p = committed_project
    anonymous = TestClient(main_api.app).get(f"/api/v1.1/projects/{p.record.project_id}/integrity")
    assert anonymous.status_code == 401
    from app.auth import COOKIE_NAME, create_session_token
    other = {COOKIE_NAME: create_session_token(user_id="someone-else", username="admin")}
    assert p.api.get(f"/api/v1.1/projects/{p.record.project_id}/integrity",
                        cookies=other).status_code == 404


def test_reading_integrity_does_not_mutate_the_last_run(committed_project):
    from app.persistence.workspace_repository import get_workspace_state

    p = committed_project
    before = get_workspace_state(p.user, p.record.project_id)
    for _ in range(2):
        assert p.api.get(f"/api/v1.1/projects/{p.record.project_id}/integrity",
                            cookies=p.cookies).status_code == 200
    after = get_workspace_state(p.user, p.record.project_id)
    assert (after.updated_at, after.last_runtime_composite_hash, after.last_runtime_snapshot_id,
            after.last_integrity_evidence, after.last_debt_schedule, after.dirty) == (
        before.updated_at, before.last_runtime_composite_hash, before.last_runtime_snapshot_id,
        before.last_integrity_evidence, before.last_debt_schedule, before.dirty)
    assert after.last_integrity_evidence["digest"]  # evidence was persisted at commit


def test_trust_pack_shows_the_separate_integrity_section(committed_project):
    p = committed_project
    page = p.client.get(f"/v2/workbook?project={p.record.project_code}", cookies=p.cookies)
    assert page.status_code == 200
    assert "RUN INTEGRITY CHECKS" in page.text
    assert 'data-testid="trust-pack-integrity-SOURCES_EQUAL_USES"' in page.text
    assert 'data-testid="trust-pack-validation"' in page.text  # the other authority is untouched


def test_last_run_committed_without_evidence_reads_as_incomplete_not_pass(monkeypatch):
    """A Last Run committed before evidence was recorded is INCOMPLETE, never PASS."""
    from app.api.v1_1 import institutional

    workspace = SimpleNamespace(
        any_run_committed=True, last_integrity_evidence={}, last_runtime_snapshot_id="s",
        last_runtime_composite_hash="h", last_runtime_identity={}, last_runtime_at=None,
        last_runtime_origin=None, last_runtime_scenario_id=None, draft_snapshot={},
        last_runtime_snapshot={})
    monkeypatch.setattr(institutional, "_load_workspace",
                        lambda user_id, project_id: (SimpleNamespace(project_type="Solar"), workspace))
    state, evidence = institutional.get_run_integrity_checks("u", "p")
    assert state == institutional.STATE_AVAILABLE
    assert evidence["overall"] == "INCOMPLETE"
    assert {c["reason_code"] for c in evidence["checks"]} == {"INTEGRITY_EVIDENCE_NOT_PERSISTED"}
