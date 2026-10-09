"""Q1 — Model Quality / Lender Readiness evaluator.

Real canonical Run data (Solar, Wind, Data Center, EV) is produced by the production
``run_project`` path; synthetic corruption is applied only to prove detection.  Nothing here
executes the financial engine during evaluation.
"""
from __future__ import annotations

import ast
import copy
import dataclasses
import json
import math
from datetime import date
from pathlib import Path

import pytest

from app import project_factories as pf
from app.api.project_runner import run_project
from app.model_quality import (
    ADVISORY_LABEL,
    CheckStatus,
    QualityCheck,
    evaluate_model_quality,
    project_quality_report,
)
from app.model_quality.contracts import Category, CheckClass, Severity
from app.model_quality.evidence import (
    RESERVE_CASH_FIXED,
    ProjectTerms,
    QualityEvidence,
    terms_from_project_inputs,
)
from app.model_quality.registry import REGISTRY
from app.model_quality.scoring import BLOCKED_SCORE_CAP, MIN_COVERAGE, rank_gaps, rank_issues, score_checks
from app.run_integrity import evidence_digest
from app.ui.runtime_summary import _format_revenue_derivation

REPO = Path(__file__).resolve().parents[1]
HASH = "ab" * 32
SNAP = "20261010T000000.000000+0000"
VERTICALS = {
    "solar": ("Solar", pf.create_generic_solar_reference),
    "wind": ("Wind", pf.create_generic_wind_reference),
    "data_center": ("Data Center", pf.create_generic_data_center_reference),
    "ev_charging": ("EV Charging", pf.create_generic_ev_charging_reference),
}


def persisted_summary(payload, *, snap=SNAP, scenario=None, bound=True):
    """The runtime summary exactly as the V2 Run commit persists it."""
    summary = dict(payload["kpis"])
    summary["revenue_derivation"] = _format_revenue_derivation(payload["derivation_evidence"].get("revenue", {}))
    fe = copy.deepcopy(payload["financing_evidence"])
    if bound:
        fe["run_binding"] = {"snapshot_id": snap, "composite_hash": HASH, "scenario_id": scenario}
    summary["financing_evidence"] = fe
    return summary


def make_evidence(payload, pi=None, *, freshness="CURRENT", terms=None, **over):
    base = dict(
        freshness=freshness, runtime_summary=persisted_summary(payload),
        integrity_evidence=copy.deepcopy(payload["integrity_evidence"]), snapshot_id=SNAP, composite_hash=HASH,
        run_at="2026-10-10T00:00:00+00:00", engine_version="clean_senior_debt_v0", scenario_known=True,
        terms=terms if terms is not None else (terms_from_project_inputs(pi) if pi is not None else ProjectTerms()),
    )
    base.update(over)
    return QualityEvidence(**base)


def redigest(evidence):
    evidence["digest"] = evidence_digest(evidence)
    return evidence


@pytest.fixture(scope="module")
def runs():
    out = {}
    for key, (project_type, factory) in VERTICALS.items():
        pi = factory()
        out[key] = (pi, run_project(project_type, "Base", project_inputs_override=pi))
    return out


@pytest.fixture(scope="module")
def solar(runs):
    return runs["solar"]


def status_of(report, check_id):
    return report.check(check_id).status


# ─────────────────────────────── registry ───────────────────────────────

class TestRegistry:
    def test_between_20_and_30_stable_unique_checks(self):
        ids = [d.check_id for d in REGISTRY]
        assert 20 <= len(ids) <= 30 and len(set(ids)) == len(ids)
        assert ids == sorted(ids, key=lambda i: [d.check_id for d in REGISTRY].index(i))  # order is the registry order

    def test_every_category_and_class_is_used(self):
        assert {d.category for d in REGISTRY} == set(Category)
        assert {d.check_class for d in REGISTRY} == set(CheckClass)

    def test_every_definition_names_its_authority_source_and_navigation(self):
        for d in REGISTRY:
            assert d.threshold_authority and d.evidence_source and d.navigation.startswith("tab-"), d.check_id
            assert d.title and d.description

    def test_stable_identity_snapshot(self):
        # ids are append-only; changing or removing one is a deliberate, reviewed act
        assert [d.check_id for d in REGISTRY][:3] == ["QM-ACC-001", "QM-ACC-002", "QM-ACC-003"]
        assert {"QM-TERM-001", "QM-SU-001", "QM-COV-001", "QM-PRV-001"} <= {d.check_id for d in REGISTRY}

    def test_advisory_ranges_are_never_classified_as_covenants_unless_supplied_terms(self):
        for d in REGISTRY:
            if d.check_class is CheckClass.CONTRACTUAL_COVENANT:
                assert "supplied" in d.threshold_authority or "project" in d.threshold_authority.lower() \
                    or "typed" in d.threshold_authority, d.check_id


# ─────────────────── four real verticals (cases 1-4) ───────────────────

@pytest.mark.parametrize("key", sorted(VERTICALS))
def test_clean_vertical_has_no_findings_and_honest_gaps(runs, key):
    pi, payload = runs[key]
    report = evaluate_model_quality(make_evidence(payload, pi))
    s = report.summary
    assert s.failed == 0 and s.warnings == 0 and not s.blocked, [(c.check_id, c.reason_code) for c in report.checks if c.status.value in ("FAIL", "WARNING")]
    assert s.registered == 30 and s.evaluated >= 24
    assert s.score_status == "PUBLISHED" and s.score == 100.0
    # evidence gaps are visible, not scored as passes or zeros
    gaps = {c.check_id: c.reason_code for c in report.checks if c.status is CheckStatus.UNAVAILABLE}
    assert gaps.get("QM-COV-001") == "MIN_DSCR_COVENANT_NOT_SUPPLIED"
    assert gaps.get("QM-CASH-002") == "DSRA_TARGET_AUTHORITY_MISSING"
    assert gaps.get("QM-CAP-001") == "CONTINGENCY_POLICY_NOT_SUPPLIED"
    assert s.coverage_weighted < 1.0 and s.coverage_count < 1.0


@pytest.mark.parametrize("key", sorted(VERTICALS))
def test_clean_vertical_checks_read_real_values(runs, key):
    pi, payload = runs[key]
    report = evaluate_model_quality(make_evidence(payload, pi))
    assert report.check("QM-SU-001").status is CheckStatus.PASS
    assert report.check("QM-SD-006").measured_value == pytest.approx(payload["kpis"]["actual_gearing_pct"])
    assert report.check("QM-SD-006").threshold_value == pytest.approx(payload["kpis"]["gearing_cap_pct"])
    assert report.check("QM-TERM-001").measured_value <= 1e-4
    assert report.check("QM-REV-002").status is CheckStatus.PASS
    assert report.check("QM-ACC-003").status is CheckStatus.PASS
    assert report.check("QM-PRV-004").status is CheckStatus.PASS
    assert report.check("QM-COV-002").threshold_value == pytest.approx(pi.financing.lockup_dscr)
    assert report.check("QM-COV-004").status is CheckStatus.PASS


# ───────────────────────── detection cases (5-18) ─────────────────────────

def test_case05_unbalanced_sources_uses_is_blocking_and_not_offset(solar):
    pi, payload = solar
    ev = make_evidence(payload, pi)
    ie = copy.deepcopy(dict(ev.integrity_evidence))
    ie["sources_uses"]["summary"]["total_sources_keur"] += 250.0
    report = evaluate_model_quality(dataclasses.replace(ev, integrity_evidence=redigest(ie)))
    assert status_of(report, "QM-SU-001") is CheckStatus.FAIL
    assert report.summary.blocked and "QM-SU-001" in report.blocking_findings
    assert report.summary.passed >= 20                       # many advisory passes...
    assert report.summary.score is not None and report.summary.score <= BLOCKED_SCORE_CAP   # ...cannot offset it
    assert report.summary.readiness_label.startswith("BLOCKED")


def test_case06_incorrect_senior_rollforward_detected(solar):
    pi, payload = solar
    ev = make_evidence(payload, pi)
    ie = copy.deepcopy(dict(ev.integrity_evidence))
    ie["senior_debt"]["periods"][3]["closing"] += 75.0
    report = evaluate_model_quality(dataclasses.replace(ev, integrity_evidence=redigest(ie)))
    assert status_of(report, "QM-SD-001") is CheckStatus.FAIL
    assert report.summary.blocked


def test_case07_actual_dscr_breach_of_a_supplied_covenant(solar):
    pi, payload = solar
    worst = payload["kpis"]["min_dscr"]
    terms = dataclasses.replace(terms_from_project_inputs(pi), min_dscr_covenant=worst + 0.25)
    report = evaluate_model_quality(make_evidence(payload, pi, terms=terms))
    check = report.check("QM-COV-001")
    assert check.status is CheckStatus.FAIL and check.reason_code == "MIN_DSCR_COVENANT_BREACH"
    assert check.measured_value == pytest.approx(worst) and check.threshold_value == pytest.approx(worst + 0.25)
    assert check.check_class is CheckClass.CONTRACTUAL_COVENANT
    # a covenant breach is high severity but not an integrity identity failure
    assert not report.summary.blocked
    # a covenant the Run satisfies passes
    ok = dataclasses.replace(terms, min_dscr_covenant=1.0)
    assert evaluate_model_quality(make_evidence(payload, pi, terms=ok)).check("QM-COV-001").status is CheckStatus.PASS


def test_case08_dsra_underfunding_when_target_is_proven(solar):
    pi, payload = solar
    funded = payload["integrity_evidence"]["sources_uses"]["summary"]["initial_dsra_funding_keur"]
    terms = ProjectTerms(reserve_regime=RESERVE_CASH_FIXED, dsra_target_keur=funded + 1000.0)
    report = evaluate_model_quality(make_evidence(payload, terms=terms))
    c = report.check("QM-CASH-002")
    assert c.status is CheckStatus.FAIL and c.reason_code == "DSRA_UNDERFUNDED"
    assert c.measured_value == pytest.approx(funded) and c.threshold_value == pytest.approx(funded + 1000.0)
    ok = ProjectTerms(reserve_regime=RESERVE_CASH_FIXED, dsra_target_keur=funded)
    assert evaluate_model_quality(make_evidence(payload, terms=ok)).check("QM-CASH-002").status is CheckStatus.PASS


def test_case09_missing_dsra_target_authority_is_unavailable_never_pass(solar):
    pi, payload = solar
    for terms in (ProjectTerms(), terms_from_project_inputs(pi)):    # none supplied / dynamic automatic reserve
        c = evaluate_model_quality(make_evidence(payload, terms=terms)).check("QM-CASH-002")
        assert c.status is CheckStatus.UNAVAILABLE and c.reason_code == "DSRA_TARGET_AUTHORITY_MISSING"
    none = ProjectTerms(reserve_regime="NONE")
    assert evaluate_model_quality(make_evidence(payload, terms=none)).check("QM-CASH-002").status is CheckStatus.NOT_APPLICABLE


def test_case10_material_terminal_senior_balloon_blocks(solar):
    pi, payload = solar
    ev = make_evidence(payload, pi)
    ie = copy.deepcopy(dict(ev.integrity_evidence))
    ie["senior_debt"]["periods"][-1]["closing"] = 20912.234045226287
    report = evaluate_model_quality(dataclasses.replace(ev, integrity_evidence=redigest(ie)))
    c = report.check("QM-TERM-001")
    assert c.status is CheckStatus.FAIL and c.reason_code == "SENIOR_MATURITY_UNSETTLED_LIABILITY"
    assert c.measured_value == pytest.approx(20912.234045226287) and c.blocking
    assert report.summary.blocked and report.summary.score <= BLOCKED_SCORE_CAP


def test_case10b_pr233_protection_still_rejects_the_original_balloon_before_any_evidence_exists():
    from dataclasses import replace

    from app.services.production_financial_authority import CleanProductionRunUnavailable, run_clean_production
    from finco_core.inputs import DebtSizingMode, GearingCapRepaymentMethod

    base = pf.create_generic_solar_reference()
    pi = replace(base, financing=replace(
        base.financing, debt_sizing_mode=DebtSizingMode.GEARING_CAP,
        gearing_cap_repayment_method=GearingCapRepaymentMethod.DSCR_SCULPTED, gearing_ratio=0.95, senior_tenor_years=8))
    with pytest.raises(CleanProductionRunUnavailable) as exc:
        run_clean_production(pi, "Base", project_type="Solar")
    assert exc.value.reason_code == "SENIOR_MATURITY_UNSETTLED_LIABILITY"
    # case 18: the unsupported configuration published no Run, so the evaluator has nothing to score
    report = evaluate_model_quality(QualityEvidence(freshness="NOT_RUN"))
    assert all(c.status is CheckStatus.UNAVAILABLE and c.reason_code == "NO_LAST_RUN" for c in report.checks)
    assert report.summary.score is None and report.summary.score_status == "UNAVAILABLE_NO_RUN"
    assert report.summary.evaluated == 0 and not report.summary.blocked


def test_case11_missing_run_identity_fails_provenance(solar):
    pi, payload = solar
    report = evaluate_model_quality(make_evidence(payload, pi, snapshot_id=None, composite_hash=None))
    c = report.check("QM-PRV-002")
    assert c.status is CheckStatus.FAIL and c.reason_code == "RUN_IDENTITY_INCOMPLETE"
    assert "snapshot_id" in c.detail and "composite_hash" in c.detail
    assert report.check("QM-PRV-004").status is CheckStatus.FAIL     # binding no longer matches the (absent) identity
    bad_hash = evaluate_model_quality(make_evidence(payload, pi, composite_hash="not-a-hash"))
    assert bad_hash.check("QM-PRV-002").status is CheckStatus.FAIL


def test_case12_corrupt_evidence_digest_detected(solar):
    pi, payload = solar
    ev = make_evidence(payload, pi)
    ie = copy.deepcopy(dict(ev.integrity_evidence))
    ie["sources_uses"]["summary"]["senior_debt_keur"] += 1.0          # altered without re-digesting
    report = evaluate_model_quality(dataclasses.replace(ev, integrity_evidence=ie))
    c = report.check("QM-PRV-001")
    assert c.status is CheckStatus.FAIL and c.check_class is CheckClass.MATHEMATICAL_INTEGRITY
    assert report.summary.blocked


def test_case13_stale_working_copy_keeps_the_historical_run_evaluable(solar):
    pi, payload = solar
    current = evaluate_model_quality(make_evidence(payload, pi))
    stale = evaluate_model_quality(make_evidence(payload, pi, freshness="STALE"))
    assert stale.check("QM-PRV-003").status is CheckStatus.WARNING
    assert stale.check("QM-PRV-003").reason_code == "WORKING_COPY_CHANGED_SINCE_LAST_RUN"
    assert stale.score_is_current is False and current.score_is_current is True
    # every other check evaluates identically: the prior Run is still the object being assessed
    assert [c.status for c in stale.checks if c.check_id != "QM-PRV-003"] == \
           [c.status for c in current.checks if c.check_id != "QM-PRV-003"]
    assert project_quality_report(stale)["score_is_current"] is False


def test_case14_legacy_run_without_evidence_is_not_scored(solar):
    pi, payload = solar
    legacy_summary = {k: v for k, v in payload["kpis"].items()}            # no revenue / financing evidence
    ev = QualityEvidence(freshness="CURRENT", runtime_summary=legacy_summary, integrity_evidence=None,
                         snapshot_id=SNAP, composite_hash=HASH, run_at="2026-01-01T00:00:00+00:00",
                         engine_version="clean_senior_debt_v0", scenario_known=True)
    report = evaluate_model_quality(ev)
    s = report.summary
    assert report.check("QM-SU-001").reason_code == "INTEGRITY_EVIDENCE_NOT_PERSISTED"
    assert s.passed < s.unavailable                                       # missing data produced no PASS
    assert s.coverage_weighted < MIN_COVERAGE
    assert s.score is None and s.score_status == "UNAVAILABLE_INSUFFICIENT_EVIDENCE"   # not zero
    assert s.readiness_label.startswith("NOT SCORED")


def test_case15_missing_covenant_target_is_unavailable_not_compliance(solar):
    pi, payload = solar
    report = evaluate_model_quality(make_evidence(payload, terms=ProjectTerms()))
    for check_id, reason in (("QM-COV-001", "MIN_DSCR_COVENANT_NOT_SUPPLIED"), ("QM-COV-002", "LOCKUP_DSCR_NOT_SUPPLIED"),
                             ("QM-COV-003", "LLCR_REQUIREMENT_NOT_SUPPLIED"), ("QM-COV-004", "COVENANT_THRESHOLDS_NOT_SUPPLIED")):
        c = report.check(check_id)
        assert c.status is CheckStatus.UNAVAILABLE and c.reason_code == reason
    # the persisted LLCR is absent for this Run: even with a requirement it is not inferred
    with_req = dataclasses.replace(ProjectTerms(), min_llcr=1.15)
    c = evaluate_model_quality(make_evidence(payload, terms=with_req)).check("QM-COV-003")
    assert c.status is CheckStatus.UNAVAILABLE and c.reason_code == "LLCR_NOT_PERSISTED"


def test_case15b_llcr_and_ordering_with_supplied_values(solar):
    pi, payload = solar
    ev = make_evidence(payload, pi)
    summary = dict(ev.runtime_summary)
    summary["min_llcr"] = 1.05
    below = evaluate_model_quality(dataclasses.replace(ev, runtime_summary=summary, terms=dataclasses.replace(ev.terms, min_llcr=1.15)))
    assert below.check("QM-COV-003").status is CheckStatus.FAIL
    inverted = dataclasses.replace(ev.terms, min_dscr_covenant=2.5)      # above lock-up and sizing target
    c = evaluate_model_quality(dataclasses.replace(ev, terms=inverted)).check("QM-COV-004")
    assert c.status is CheckStatus.FAIL and c.reason_code == "COVENANT_ORDER_INVERTED"


def test_case16_actual_zero_versus_missing(solar):
    pi, payload = solar
    ev = make_evidence(payload, pi)
    # a genuine 0.0 return is a published value; a missing one is not
    zero = dict(ev.runtime_summary); zero["project_irr"] = 0.0
    assert evaluate_model_quality(dataclasses.replace(ev, runtime_summary=zero)).check("QM-ACC-004").status is CheckStatus.PASS
    missing = {k: v for k, v in ev.runtime_summary.items() if k != "project_irr"}
    c = evaluate_model_quality(dataclasses.replace(ev, runtime_summary=missing)).check("QM-ACC-004")
    assert c.status is CheckStatus.WARNING and "project_irr" in c.detail
    # developer uses: recorded zero -> NOT_APPLICABLE; absent keys -> UNAVAILABLE (never assumed zero)
    assert evaluate_model_quality(ev).check("QM-SU-003").status is CheckStatus.NOT_APPLICABLE
    ie = copy.deepcopy(dict(ev.integrity_evidence))
    del ie["sources_uses"]["summary"]["developer_fee_keur"]
    c = evaluate_model_quality(dataclasses.replace(ev, integrity_evidence=redigest(ie))).check("QM-SU-003")
    assert c.status is CheckStatus.UNAVAILABLE and c.reason_code == "DEVELOPER_USES_EVIDENCE_MISSING"
    # a reported DSCR of exactly 0.0 is a value (a failure), not a missing reading
    ie = copy.deepcopy(dict(ev.integrity_evidence))
    ie["senior_debt"]["periods"][2]["reported_dscr"] = 0.0
    c = evaluate_model_quality(dataclasses.replace(ev, integrity_evidence=redigest(ie))).check("QM-SD-007")
    assert c.status is CheckStatus.FAIL and c.measured_value == 0.0
    # a missing terminal balance is unavailable, never settled
    ie = copy.deepcopy(dict(ev.integrity_evidence))
    ie["senior_debt"]["periods"][-1]["closing"] = None
    c = evaluate_model_quality(dataclasses.replace(ev, integrity_evidence=redigest(ie))).check("QM-TERM-001")
    assert c.status is CheckStatus.UNAVAILABLE and c.reason_code == "SENIOR_TERMINAL_BALANCE_MISSING"


def test_case17_developer_reimbursement_and_fee_are_itemised_and_balanced():
    pi = pf.create_generic_solar_reference()
    fc = pi.info.financial_close
    from finco_core.inputs import DevelopmentEconomicsInput, DevelopmentSpendEntry
    pi = dataclasses.replace(pi, development_economics=DevelopmentEconomicsInput(
        enabled=True, spend_schedule=(DevelopmentSpendEntry(date(fc.year - 1, 3, 31), 1000.0),),
        reimbursed_development_cost_keur=800.0, developer_fee_value=250.0))
    payload = run_project("Solar", "Base", project_inputs_override=pi)
    report = evaluate_model_quality(make_evidence(payload, pi))
    c = report.check("QM-SU-003")
    assert c.status is CheckStatus.PASS and c.measured_value == pytest.approx(1050.0)
    assert report.check("QM-SU-001").status is CheckStatus.PASS      # uses reconcile with developer uses (F0-P1)
    assert not report.summary.blocked


def test_case18_unsupported_or_unavailable_configuration_never_scores_as_success():
    # No Last Run (e.g. fail-closed configuration): every check UNAVAILABLE, score unavailable (not 0)
    report = evaluate_model_quality(QualityEvidence())
    assert {c.status for c in report.checks} == {CheckStatus.UNAVAILABLE}
    assert report.summary.score is None and report.summary.score_status == "UNAVAILABLE_NO_RUN"
    assert report.summary.coverage_weighted == 0.0 and report.summary.evaluated == 0


# ─────────────────────────────── scoring ───────────────────────────────

def mk(check_id, status, severity=Severity.MEDIUM, klass=CheckClass.ADVISORY_RISK):
    return QualityCheck(check_id=check_id, category=Category.SENIOR_DEBT, check_class=klass, title="t", description="d",
                        status=status, severity=severity, measured_value=None, measured_unit="x", threshold_value=None,
                        threshold_authority="a", evidence_source="e",
                        reason_code="R" if status is CheckStatus.UNAVAILABLE else None,
                        related_assumption_ids=(), related_output_keys=(), navigation_target="tab-debt")


class TestScoring:
    def test_weights_credits_and_denominator(self):
        checks = (mk("QM-SD-001", CheckStatus.PASS, Severity.CRITICAL), mk("QM-SD-002", CheckStatus.WARNING, Severity.HIGH),
                  mk("QM-SD-003", CheckStatus.PASS, Severity.MEDIUM), mk("QM-SD-004", CheckStatus.PASS, Severity.LOW))
        s = score_checks(checks)
        assert s.score == pytest.approx(100 * (8 + 4 * 0.5 + 2 + 1) / (8 + 4 + 2 + 1), abs=0.01)
        assert (s.passed, s.warnings, s.failed) == (3, 1, 0) and s.coverage_weighted == 1.0

    def test_fail_scores_zero_credit_and_warning_half(self):
        s = score_checks((mk("QM-SD-001", CheckStatus.FAIL), mk("QM-SD-002", CheckStatus.WARNING)))
        assert s.score == pytest.approx(25.0)

    def test_unavailable_lowers_coverage_and_is_not_scored_as_a_pass_or_fail(self):
        checks = [mk(f"QM-SD-00{i}", CheckStatus.PASS) for i in range(1, 9)] + [mk("QM-SD-009", CheckStatus.UNAVAILABLE),
                                                                                 mk("QM-SD-010", CheckStatus.UNAVAILABLE)]
        s = score_checks(tuple(checks))
        assert s.coverage_count == pytest.approx(0.8) and s.score == 100.0 and s.unavailable == 2

    def test_below_minimum_coverage_score_is_unavailable_not_zero(self):
        checks = [mk("QM-SD-001", CheckStatus.PASS)] + [mk(f"QM-SD-00{i}", CheckStatus.UNAVAILABLE) for i in range(2, 5)]
        s = score_checks(tuple(checks))
        assert s.coverage_weighted < MIN_COVERAGE and s.score is None
        assert s.score_status == "UNAVAILABLE_INSUFFICIENT_EVIDENCE"

    def test_not_applicable_is_excluded_from_the_denominator_and_coverage(self):
        checks = (mk("QM-SD-001", CheckStatus.PASS), mk("QM-SD-002", CheckStatus.NOT_APPLICABLE), mk("QM-SD-003", CheckStatus.PASS))
        s = score_checks(checks)
        assert s.applicable == 2 and s.not_applicable == 1 and s.coverage_count == 1.0

    def test_integrity_failure_cannot_be_offset_by_many_passes(self):
        passes = [mk(f"QM-SD-0{i:02d}", CheckStatus.PASS, Severity.LOW) for i in range(1, 25)]
        fail = mk("QM-ACC-001", CheckStatus.FAIL, Severity.MEDIUM, CheckClass.MATHEMATICAL_INTEGRITY)
        s = score_checks(tuple(passes) + (fail,))
        assert s.blocked and s.score <= BLOCKED_SCORE_CAP and s.readiness_label.startswith("BLOCKED")

    def test_critical_failure_blocks_even_when_advisory(self):
        s = score_checks((mk("QM-SD-001", CheckStatus.FAIL, Severity.CRITICAL), mk("QM-SD-002", CheckStatus.PASS)))
        assert s.blocked

    def test_blocking_is_reported_even_when_the_score_is_unavailable(self):
        checks = (mk("QM-ACC-001", CheckStatus.FAIL, Severity.CRITICAL, CheckClass.MATHEMATICAL_INTEGRITY),) + \
                 tuple(mk(f"QM-SD-00{i}", CheckStatus.UNAVAILABLE) for i in range(2, 6))
        s = score_checks(checks)
        assert s.blocked and s.score is None

    def test_advisory_failure_alone_does_not_block(self):
        s = score_checks((mk("QM-SD-001", CheckStatus.FAIL, Severity.HIGH), mk("QM-SD-002", CheckStatus.PASS)))
        assert not s.blocked

    def test_sorting_rules(self):
        checks = (mk("QM-SD-005", CheckStatus.WARNING, Severity.HIGH), mk("QM-SD-002", CheckStatus.FAIL, Severity.HIGH),
                  mk("QM-SD-001", CheckStatus.FAIL, Severity.CRITICAL), mk("QM-SD-003", CheckStatus.WARNING, Severity.LOW),
                  mk("QM-SD-004", CheckStatus.UNAVAILABLE, Severity.LOW), mk("QM-SD-006", CheckStatus.UNAVAILABLE, Severity.HIGH))
        assert rank_issues(checks) == ("QM-SD-001", "QM-SD-002", "QM-SD-005", "QM-SD-003")
        assert rank_gaps(checks) == ("QM-SD-006", "QM-SD-004")

    def test_severity_breakdown_counts(self):
        s = score_checks((mk("QM-SD-001", CheckStatus.PASS, Severity.HIGH), mk("QM-SD-002", CheckStatus.FAIL, Severity.HIGH)))
        assert s.severity_breakdown["HIGH"]["PASS"] == 1 and s.severity_breakdown["HIGH"]["FAIL"] == 1


# ────────────────────────── contracts / determinism ──────────────────────────

class TestContracts:
    @pytest.mark.parametrize("bad", [float("nan"), float("inf"), "1.0", True])
    def test_non_finite_or_non_numeric_values_are_rejected(self, bad):
        with pytest.raises(ValueError, match="QM_NON_FINITE_VALUE"):
            dataclasses.replace(mk("QM-SD-001", CheckStatus.PASS), measured_value=bad)

    def test_invalid_ids_and_enums_rejected(self):
        with pytest.raises(ValueError, match="QM_INVALID_CHECK_ID"):
            dataclasses.replace(mk("QM-SD-001", CheckStatus.PASS), check_id="bad")
        with pytest.raises(ValueError, match="QM_INVALID_ENUM"):
            dataclasses.replace(mk("QM-SD-001", CheckStatus.PASS), status="PASS")

    def test_unavailable_requires_a_reason(self):
        with pytest.raises(ValueError, match="QM_UNAVAILABLE_NEEDS_REASON"):
            dataclasses.replace(mk("QM-SD-001", CheckStatus.UNAVAILABLE), reason_code=None)

    def test_serialization_is_deterministic_and_strict_json(self, solar):
        pi, payload = solar
        a = evaluate_model_quality(make_evidence(payload, pi)).to_json()
        b = evaluate_model_quality(make_evidence(copy.deepcopy(payload), pi)).to_json()
        assert a == b
        parsed = json.loads(a)
        assert parsed["label"] == ADVISORY_LABEL and [c["check_id"] for c in parsed["checks"]] == [d.check_id for d in REGISTRY]
        assert "NaN" not in a and "Infinity" not in a

    def test_label_never_claims_approval_certification_or_verification(self, solar):
        pi, payload = solar
        report = evaluate_model_quality(make_evidence(payload, pi))
        text = report.to_json().lower()
        assert report.label == "MODEL QUALITY / LENDER READINESS ADVISORY"
        assert set(report.not_claims) == {"Not bank approval", "Not certification", "Not verification"}
        for forbidden in ("bank approved", "certified by", "verified by", "bankable"):
            assert forbidden not in text

    def test_projection_shape(self, solar):
        pi, payload = solar
        view = project_quality_report(evaluate_model_quality(make_evidence(payload, pi)), top_n=3)
        assert view["counts"]["registered"] == 30 and len(view["evidence_gaps"]) <= 3
        assert json.loads(json.dumps(view)) == view


# ─────────────────────── isolation: read-only, no engine ───────────────────────

class TestIsolation:
    def test_evaluation_never_executes_the_engine_and_never_mutates_evidence(self, solar, monkeypatch):
        import app.api.project_runner as runner
        import app.services.production_financial_authority as authority
        pi, payload = solar
        ev = make_evidence(payload, pi)
        before = copy.deepcopy((dict(ev.runtime_summary), dict(ev.integrity_evidence)))

        def boom(*a, **k):
            raise AssertionError("the financial engine must not run during evaluation")

        monkeypatch.setattr(runner, "run_project", boom)
        monkeypatch.setattr(authority, "run_clean_production", boom)
        evaluate_model_quality(ev)
        evaluate_model_quality(ev)
        assert (dict(ev.runtime_summary), dict(ev.integrity_evidence)) == before

    def test_package_imports_no_engine_persistence_or_web_modules(self):
        forbidden = ("financial_engine", "app.persistence", "app.v2", "app.templates", "fastapi", "sqlite3", "main_web")
        for path in (REPO / "app/model_quality").glob("*.py"):
            tree = ast.parse(path.read_text(encoding="utf-8-sig"))
            for node in ast.walk(tree):
                mods = ([a.name for a in node.names] if isinstance(node, ast.Import)
                        else [node.module or ""] if isinstance(node, ast.ImportFrom) else [])
                assert not any(m.startswith(forbidden) for m in mods), (path.name, mods)

    def test_no_production_module_imports_the_evaluator_yet_and_no_route_exists(self):
        import main_web
        assert not [r for r in main_web.app.routes if "quality" in getattr(r, "path", "").lower()]
        for root in ("app", "financial_engine", "finco_core"):
            for path in (REPO / root).rglob("*.py"):
                if "model_quality" in path.parts:
                    continue
                text = path.read_text(encoding="utf-8-sig")
                assert "app.model_quality" not in text, str(path)

    def test_evaluate_workspace_reads_a_persisted_record_without_writing(self, solar):
        pi, payload = solar

        class Ws:
            last_runtime_summary = persisted_summary(payload)
            last_integrity_evidence = copy.deepcopy(payload["integrity_evidence"])
            last_runtime_snapshot_id = SNAP
            last_runtime_composite_hash = HASH
            last_runtime_identity = {"engine_version": "clean_senior_debt_v0"}
            last_runtime_at = None
            last_runtime_scenario_id = None
            any_run_committed = True
            last_runtime_snapshot = {"x": 1}

        from app.model_quality import evaluate_workspace
        ws = Ws()
        current = evaluate_workspace(ws, current_composite_hash=HASH, terms=terms_from_project_inputs(pi))
        stale = evaluate_workspace(ws, current_composite_hash="f" * 64, terms=terms_from_project_inputs(pi))
        assert current.freshness == "CURRENT" and stale.freshness == "STALE"
        assert current.check("QM-PRV-002").status is CheckStatus.FAIL            # run_at missing in this fake record
