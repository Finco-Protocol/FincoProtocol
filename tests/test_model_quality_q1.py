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
        integrity_evidence=copy.deepcopy(payload["integrity_evidence"]),
        sponsor_summary=copy.deepcopy(payload["sponsor_schedule"]["summary"]), snapshot_id=SNAP, composite_hash=HASH,
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
        # Q3 integration: exactly these two read-only presentation adapters may consume the evaluator.
        # Every other production module (and the whole engine / core) still may not.
        q3_adapters = {REPO / "app/v2/insight_quality_projection.py", REPO / "app/v2/insight_scenario_projection.py"}
        for root in ("app", "financial_engine", "finco_core"):
            for path in (REPO / root).rglob("*.py"):
                if "model_quality" in path.parts or path in q3_adapters:
                    continue
                text = path.read_text(encoding="utf-8-sig")
                assert "app.model_quality" not in text, str(path)
        for path in q3_adapters:
            text = path.read_text(encoding="utf-8-sig")
            assert "financial_engine" not in text and "run_model" not in text and "run_project" not in text, str(path)

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


# ─────────────── Correction A: SHL maturity evidence authority (QM-TERM-002) ───────────────
from app.model_quality.evaluators import Context, shl_terminal
from app.model_quality.evidence import SHL_TERMINAL_TOLERANCE_KEUR


def shl_ev(payload, pi, *, terminal=None, rows=None, sponsor_reported=None, drop_rows_key=False, **over):
    """Real Run evidence with targeted, digest-consistent mutation of the SHL authorities."""
    ev = make_evidence(payload, pi, **over)
    summary = copy.deepcopy(dict(ev.sponsor_summary)) if ev.sponsor_summary is not None else None
    if terminal is not None and summary is not None:
        summary["terminal_financial_state"]["shareholder_loan"].update(terminal)
    ie = copy.deepcopy(dict(ev.integrity_evidence))
    if rows is not None:
        rows(ie["balance_sheet"])
    if sponsor_reported is not None:
        ie["sponsor"]["reported"].update(sponsor_reported)
    if drop_rows_key:
        del ie["balance_sheet"]
    return dataclasses.replace(ev, sponsor_summary=summary, integrity_evidence=redigest(ie))


def outcome(ev):
    return shl_terminal(Context(ev))     # the check itself, independent of every other check


def row_for(table, period):
    return next(r for r in table if r["period_index"] == period)


@pytest.fixture(scope="module")
def maturity(solar):
    pi, payload = solar
    return payload["sponsor_schedule"]["summary"]["terminal_financial_state"]["shareholder_loan"]["contractual_maturity_period_index"]


class TestShlMaturityAuthority:
    def test_A_original_false_pass_reproducer(self, solar, maturity):
        pi, payload = solar
        def inject(table):
            for r in table:
                if r["period_index"] >= maturity - 2:
                    r["shl"] = 9000.0
        ev = shl_ev(payload, pi, rows=inject, sponsor_reported={"pure_equity_xirr_status": "NO_POSITIVE_CASHFLOW"})
        result = outcome(ev)
        assert result.status is CheckStatus.FAIL and result.reason == "UNPAID_SHL_AT_CONTRACTUAL_MATURITY"
        assert result.value == 9000.0 and result.threshold == SHL_TERMINAL_TOLERANCE_KEUR
        assert f"maturity period {maturity}" in result.detail and "terminal_financial_state" in result.detail
        # the corrupt balance sheet ALSO trips the accounting check, but TERM-002 does not depend on it
        report = evaluate_model_quality(ev)
        assert report.check("QM-TERM-002").status is CheckStatus.FAIL
        assert report.check("QM-ACC-001").status is CheckStatus.FAIL
        assert report.summary.blocked and "QM-TERM-002" in report.blocking_findings

    def test_B_repaid_at_contractual_maturity_passes_on_all_four_real_runs(self, runs):
        for key, (pi, payload) in runs.items():
            ev = make_evidence(payload, pi)
            shl = payload["sponsor_schedule"]["summary"]["terminal_financial_state"]["shareholder_loan"]
            c = evaluate_model_quality(ev).check("QM-TERM-002")
            assert c.status is CheckStatus.PASS, (key, c.reason_code, c.detail)
            assert c.measured_value == 0.0 and c.threshold_value == SHL_TERMINAL_TOLERANCE_KEUR
            assert f"maturity period {shl['contractual_maturity_period_index']}" in c.detail

    def test_C_material_unpaid_balance_at_maturity_fails(self, solar, maturity):
        pi, payload = solar
        ev = shl_ev(payload, pi, rows=lambda t: row_for(t, maturity).update(shl=500.0))
        r = outcome(ev)
        assert r.status is CheckStatus.FAIL and r.value == 500.0

    def test_D_material_liability_remaining_after_maturity_fails(self, solar, maturity):
        pi, payload = solar
        early = maturity - 2
        ev = shl_ev(payload, pi, terminal={"contractual_maturity_period_index": early,
                                             "balance_at_contractual_maturity_keur": 0.0},
                    rows=lambda t: row_for(t, maturity).update(shl=300.0))
        r = outcome(ev)
        assert r.status is CheckStatus.FAIL and r.reason == "UNPAID_SHL_AT_CONTRACTUAL_MATURITY"
        assert r.value == 300.0 and "after maturity" in r.detail and f"period {maturity}" in r.detail

    @pytest.mark.parametrize("terminal,reason", [
        ({"contractual_maturity_period_index": None}, "SHL_MATURITY_AUTHORITY_MISSING"),
        ({"contractual_maturity_period_index": True}, "SHL_MATURITY_AUTHORITY_MISSING"),
        ({"contractual_maturity_period_index": -1}, "SHL_MATURITY_AUTHORITY_MISSING"),
        ({"contractual_maturity_period_index": 52.0}, "SHL_MATURITY_AUTHORITY_MISSING"),
    ])
    def test_E_missing_or_malformed_maturity_authority_is_unavailable(self, solar, terminal, reason):
        pi, payload = solar
        r = outcome(shl_ev(payload, pi, terminal=terminal))
        assert r.status is CheckStatus.UNAVAILABLE and r.reason == reason

    def test_E2_no_persisted_terminal_state_is_unavailable_never_pass(self, solar):
        pi, payload = solar
        for sponsor_summary in (None, {}, {"terminal_financial_state": {}}):
            ev = dataclasses.replace(make_evidence(payload, pi), sponsor_summary=sponsor_summary)
            r = outcome(ev)
            assert r.status is CheckStatus.UNAVAILABLE and r.reason == "SHL_TERMINAL_AUTHORITY_NOT_PERSISTED"
        # the last visible balance-sheet period is never used as the maturity
        assert evaluate_model_quality(dataclasses.replace(make_evidence(payload, pi), sponsor_summary=None)
                                      ).check("QM-TERM-002").status is CheckStatus.UNAVAILABLE

    def test_F_missing_balance_sheet_evidence(self, solar):
        pi, payload = solar
        assert outcome(shl_ev(payload, pi, drop_rows_key=True)).reason == "SHL_BALANCE_EVIDENCE_MISSING"
        assert outcome(shl_ev(payload, pi, rows=lambda t: t.clear())).reason == "SHL_BALANCE_EVIDENCE_MISSING"
        r = outcome(dataclasses.replace(make_evidence(payload, pi), integrity_evidence=None))
        assert r.status is CheckStatus.UNAVAILABLE

    def test_G_missing_maturity_period_row(self, solar, maturity):
        pi, payload = solar
        ev = shl_ev(payload, pi, terminal={"contractual_maturity_period_index": maturity - 1},
                    rows=lambda t: t.remove(row_for(t, maturity - 1)))
        r = outcome(ev)
        assert r.status is CheckStatus.UNAVAILABLE and r.reason == "SHL_MATURITY_PERIOD_NOT_EVIDENCED"

    @pytest.mark.parametrize("bad", [float("nan"), float("inf"), float("-inf"), "9000", None, True])
    def test_H_non_finite_or_malformed_balance_is_unavailable(self, solar, maturity, bad):
        pi, payload = solar
        ev = shl_ev(payload, pi, rows=lambda t: row_for(t, maturity).update(shl=bad))
        r = outcome(ev)
        assert r.status is CheckStatus.UNAVAILABLE and r.reason == "SHL_BALANCE_EVIDENCE_INCOMPLETE"

    def test_I_actual_zero_is_a_value_missing_is_not(self, solar, maturity):
        pi, payload = solar
        assert outcome(shl_ev(payload, pi, rows=lambda t: row_for(t, maturity).update(shl=0.0))).status is CheckStatus.PASS
        r = outcome(shl_ev(payload, pi, rows=lambda t: row_for(t, maturity).pop("shl")))
        assert r.status is CheckStatus.UNAVAILABLE and r.reason == "SHL_BALANCE_EVIDENCE_INCOMPLETE"

    @pytest.mark.parametrize("index", [10_000, 999])
    def test_J_maturity_beyond_the_evidenced_horizon(self, solar, index):
        pi, payload = solar
        r = outcome(shl_ev(payload, pi, terminal={"contractual_maturity_period_index": index}))
        assert r.status is CheckStatus.UNAVAILABLE and r.reason == "SHL_MATURITY_BEYOND_EVIDENCED_HORIZON"

    def test_K_unrelated_return_status_is_not_evidence_either_way(self, solar):
        pi, payload = solar
        # repaid SHL stays PASS whatever unrelated status the sponsor returns carry
        ev = shl_ev(payload, pi, sponsor_reported={"pure_equity_xirr_status": "NO_POSITIVE_CASHFLOW",
                                                    "total_sponsor_xirr_status": "NON_CONVERGENT"})
        assert outcome(ev).status is CheckStatus.PASS

    def test_L_missing_statuses_are_not_required_and_unpaid_status_corroborates(self, solar, maturity):
        pi, payload = solar
        def strip(ie_rows): pass
        ev = make_evidence(payload, pi)
        ie = copy.deepcopy(dict(ev.integrity_evidence)); ie["sponsor"]["reported"] = {}
        assert outcome(dataclasses.replace(ev, integrity_evidence=redigest(ie))).status is CheckStatus.PASS   # balance proves it
        # the engine's own unpaid signal is sufficient to fail even if the (digest-bound) balance shows zero
        flagged = shl_ev(payload, pi, sponsor_reported={"total_sponsor_xirr_status": "UNPAID_SHL_AT_CONTRACTUAL_MATURITY"})
        assert outcome(flagged).status is CheckStatus.FAIL
        terminal_unpaid = shl_ev(payload, pi, terminal={"status": "UNPAID_AT_CONTRACTUAL_MATURITY"})
        assert outcome(terminal_unpaid).status is CheckStatus.FAIL

    def test_M_proven_no_shl_is_not_applicable_but_a_zero_balance_alone_is_not_proof(self):
        from finco_core.inputs import SponsorFundingMode
        base = pf.create_generic_solar_reference()
        pi = dataclasses.replace(base, financing=dataclasses.replace(
            base.financing, sponsor_funding_mode=SponsorFundingMode.EQUITY_ONLY, clean_shl_repayment_method=None))
        payload = run_project("Solar", "Base", project_inputs_override=pi)
        terminal = payload["sponsor_schedule"]["summary"]["terminal_financial_state"]["shareholder_loan"]
        assert terminal["status"] == "NOT_APPLICABLE"
        # Correction B: NOT_APPLICABLE needs COMPLETE corroborating balances.  The real committed balance sheet has
        # one period without an SHL value, so the real Run is UNAVAILABLE (see TestCorrectionB); the positive
        # branch is exercised on the same real evidence with that single gap synthetically completed.
        ev = shl_ev(payload, pi, rows=complete_shl_rows)
        r = outcome(ev)
        assert r.status is CheckStatus.NOT_APPLICABLE and r.reason == "NO_SHL_PER_CANONICAL_TERMINAL_STATE"
        # contradictory evidence (canonical says no SHL, balance sheet shows one) is never N/A
        def contradict_rows(t):
            complete_shl_rows(t)
            t[-1].update(shl=250.0)
        contradict = shl_ev(payload, pi, rows=contradict_rows)
        assert outcome(contradict).reason == "SHL_EVIDENCE_INCONSISTENT"
        # no canonical terminal state: a visible zero balance does NOT become NOT_APPLICABLE
        no_authority = dataclasses.replace(ev, sponsor_summary=None)
        assert outcome(no_authority).status is CheckStatus.UNAVAILABLE

    def test_N_stale_working_copy_is_evaluated_against_the_committed_run_only(self, solar, maturity):
        pi, payload = solar
        from app.model_quality import evaluate_workspace

        class Ws:
            last_runtime_summary = persisted_summary(payload)
            last_integrity_evidence = copy.deepcopy(payload["integrity_evidence"])
            last_sponsor_schedule = copy.deepcopy(payload["sponsor_schedule"])
            last_runtime_snapshot_id = SNAP
            last_runtime_composite_hash = HASH
            last_runtime_identity = {"engine_version": "clean_senior_debt_v0"}
            last_runtime_at = None
            last_runtime_scenario_id = None
            any_run_committed = True
            last_runtime_snapshot = {"shl_maturity_period_index": 3, "shl_amount_keur": "123456"}   # edited assumptions
            draft_snapshot = {"shl_maturity_period_index": 3}
            saved_snapshot = {"shl_maturity_period_index": 3}

        terms = terms_from_project_inputs(pi)
        current = evaluate_workspace(Ws(), current_composite_hash=HASH, terms=terms)
        stale = evaluate_workspace(Ws(), current_composite_hash="f" * 64, terms=terms)
        assert stale.freshness == "STALE" and current.freshness == "CURRENT"
        for report in (current, stale):
            c = report.check("QM-TERM-002")
            assert c.status is CheckStatus.PASS and f"maturity period {maturity}" in c.detail   # not period 3
        assert stale.score_is_current is False

    def test_O_duplicate_or_inconsistent_period_evidence(self, solar, maturity):
        pi, payload = solar
        dup = shl_ev(payload, pi, rows=lambda t: t.append(dict(row_for(t, maturity))))
        assert outcome(dup).reason == "SHL_BALANCE_EVIDENCE_INCONSISTENT"
        bad_index = shl_ev(payload, pi, rows=lambda t: row_for(t, maturity).update(period_index="52"))
        assert outcome(bad_index).status is CheckStatus.UNAVAILABLE
        mismatch = shl_ev(payload, pi, terminal={"balance_at_contractual_maturity_keur": 5.0})
        r = outcome(mismatch)
        assert r.status is CheckStatus.UNAVAILABLE and r.reason == "SHL_EVIDENCE_INCONSISTENT"

    def test_precision_is_the_shl_terminal_contract_not_the_senior_tolerance(self, solar, maturity):
        from financial_engine.project_returns.model import _TOL as engine_precision
        assert SHL_TERMINAL_TOLERANCE_KEUR == engine_precision == 1e-7
        pi, payload = solar
        assert outcome(shl_ev(payload, pi, rows=lambda t: row_for(t, maturity).update(shl=5e-8))
                       ).status is CheckStatus.PASS
        # 1e-6 kEUR passes the Senior tolerance (1e-4) but is a material SHL residual under the SHL contract
        assert outcome(shl_ev(payload, pi, rows=lambda t: row_for(t, maturity).update(shl=1e-6))
                       ).status is CheckStatus.FAIL

    def test_check_identity_and_classification_are_preserved(self):
        d = next(x for x in REGISTRY if x.check_id == "QM-TERM-002")
        assert d.category is Category.TERMINAL_LIABILITY and d.check_class is CheckClass.MATHEMATICAL_INTEGRITY
        assert d.severity is Severity.HIGH and len(REGISTRY) == 30


def test_reference_scoring_unchanged_and_earned(runs):
    for key, (pi, payload) in runs.items():
        s = evaluate_model_quality(make_evidence(payload, pi)).summary
        assert (s.registered, s.passed, s.not_applicable, s.unavailable) == (30, 25, 1, 4), key
        assert s.score == 100.0 and s.coverage_weighted == pytest.approx(0.876106, abs=1e-6)


@pytest.fixture
def seeded_db(tmp_path, monkeypatch):
    from app.persistence import db
    monkeypatch.setattr(db, "DB_PATH", str(tmp_path / "q1-shl.db"))
    db.init_db()
    yield


def test_maturity_authority_is_bound_to_the_committed_run_and_history(seeded_db):
    """V2 Run commit persists the SHL terminal state atomically with the Last Run and in Run History."""
    import re
    from fastapi.testclient import TestClient
    import main_web
    from app.auth import COOKIE_NAME, create_session_token
    from app.persistence.run_history_repository import get_run_history
    from app.persistence.workspace_repository import get_workspace_state
    from app.services.reference_seed_service import create_reference_seeded_project
    from app.model_quality import evaluate_workspace

    user = "q1-shl-user"
    record = create_reference_seeded_project(user_id=user, template_source="generic_solar_reference",
                                             requested_name="Q1 SHL", capacity_mw=40.0)
    cookies = {COOKIE_NAME: create_session_token(user_id=user, username="admin")}
    client = TestClient(main_web.app)
    page = client.get(f"/v2/workbook?project={record.project_code}", cookies=cookies)
    h = re.search(r'name="content_hash" value="([^"]+)"', page.text).group(1)
    v = re.search(r'name="workbook_version" value="([^"]+)"', page.text).group(1)
    resp = client.post("/v2/workbook/run", data={"project": record.project_code, "content_hash": h, "workbook_version": v},
                       cookies=cookies, headers={"HX-Request": "true"})
    assert resp.status_code == 200
    ws = get_workspace_state(user, record.project_id)
    assert ws.last_runtime_snapshot_id and ws.last_runtime_composite_hash == h
    terminal = ws.last_sponsor_schedule["summary"]["terminal_financial_state"]["shareholder_loan"]
    assert isinstance(terminal["contractual_maturity_period_index"], int)
    history = get_run_history(user, record.project_id, limit=5)
    assert history and history[0].sponsor_schedule["summary"]["terminal_financial_state"]["shareholder_loan"] == terminal
    report = evaluate_workspace(ws, current_composite_hash=h)
    c = report.check("QM-TERM-002")
    assert c.status is CheckStatus.PASS and f"maturity period {terminal['contractual_maturity_period_index']}" in c.detail
    assert report.freshness == "CURRENT"


# ─────────────── Correction B: final SHL evidence hardening ───────────────
import itertools

NO_SHL_STATUS = "NOT_APPLICABLE"


@pytest.fixture(scope="module")
def no_shl_run():
    from finco_core.inputs import SponsorFundingMode
    base = pf.create_generic_solar_reference()
    pi = dataclasses.replace(base, financing=dataclasses.replace(
        base.financing, sponsor_funding_mode=SponsorFundingMode.EQUITY_ONLY, clean_shl_repayment_method=None))
    return pi, run_project("Solar", "Base", project_inputs_override=pi)


def complete_shl_rows(table):
    """Synthetic completion of the one real evidence gap so the positive NOT_APPLICABLE branch can be exercised."""
    for r in table:
        if r.get("shl") is None:
            r["shl"] = 0.0


class TestCorrectionB:
    # A. terminal-balance consistency uses the SHL precision (1e-7), not 1e-6
    def test_A_terminal_balance_5e7_vs_balance_sheet_zero_is_inconsistent(self, solar):
        pi, payload = solar
        r = outcome(shl_ev(payload, pi, terminal={"balance_at_contractual_maturity_keur": 5e-7}))
        assert r.status is CheckStatus.UNAVAILABLE and r.reason == "SHL_EVIDENCE_INCONSISTENT"

    def test_A_matching_balances_inside_the_shl_precision_pass(self, solar, maturity):
        pi, payload = solar
        ev = shl_ev(payload, pi, terminal={"balance_at_contractual_maturity_keur": 5e-8},
                    rows=lambda t: row_for(t, maturity).update(shl=0.0))
        assert outcome(ev).status is CheckStatus.PASS
        ev = shl_ev(payload, pi, terminal={"balance_at_contractual_maturity_keur": 6e-8},
                    rows=lambda t: row_for(t, maturity).update(shl=1e-8))
        assert outcome(ev).status is CheckStatus.PASS                      # |diff| 5e-8 <= 1e-7
        ev = shl_ev(payload, pi, terminal={"balance_at_contractual_maturity_keur": 2e-7},
                    rows=lambda t: row_for(t, maturity).update(shl=5e-8))
        assert outcome(ev).status is CheckStatus.UNAVAILABLE               # |diff| 1.5e-7 > 1e-7

    # B. NOT_APPLICABLE requires complete, finite corroborating balances across the persisted balance sheet
    def test_B_real_no_shl_run_is_unavailable_because_the_committed_balance_sheet_has_a_real_gap(self, no_shl_run):
        pi, payload = no_shl_run
        rows = payload["integrity_evidence"]["balance_sheet"]
        gaps = [r["period_index"] for r in rows if r.get("shl") is None]
        assert gaps, "the real evidence carries a period with no SHL balance"
        r = outcome(make_evidence(payload, pi))
        assert r.status is CheckStatus.UNAVAILABLE and r.reason == "SHL_BALANCE_EVIDENCE_INCOMPLETE"

    def test_B_complete_corroboration_retains_not_applicable(self, no_shl_run):
        pi, payload = no_shl_run
        r = outcome(shl_ev(payload, pi, rows=complete_shl_rows))
        assert r.status is CheckStatus.NOT_APPLICABLE and r.reason == "NO_SHL_PER_CANONICAL_TERMINAL_STATE"

    @pytest.mark.parametrize("bad", [None, float("nan"), float("inf"), "0", True])
    def test_B_missing_or_non_finite_row_next_to_valid_zero_is_not_ignored(self, no_shl_run, bad):
        pi, payload = no_shl_run
        def mutate(table):
            complete_shl_rows(table)
            table[10]["shl"] = bad
        r = outcome(shl_ev(payload, pi, rows=mutate))
        assert r.status is CheckStatus.UNAVAILABLE and r.reason == "SHL_BALANCE_EVIDENCE_INCOMPLETE"

    def test_B_removed_shl_key_is_not_ignored(self, no_shl_run):
        pi, payload = no_shl_run
        def mutate(table):
            complete_shl_rows(table)
            table[10].pop("shl")
        assert outcome(shl_ev(payload, pi, rows=mutate)).reason == "SHL_BALANCE_EVIDENCE_INCOMPLETE"

    def test_B_contradiction_still_not_applicable_blocking(self, no_shl_run):
        pi, payload = no_shl_run
        def mutate(table):
            complete_shl_rows(table)
            table[-1]["shl"] = 250.0
        assert outcome(shl_ev(payload, pi, rows=mutate)).reason == "SHL_EVIDENCE_INCONSISTENT"

    # C. the canonical terminal status is validated against the typed enum
    @pytest.mark.parametrize("status", [None, "", "repaid", "SETTLED", "PAID", 7, True, ["REPAID"]])
    def test_C_unknown_or_malformed_status_never_passes_on_a_zero_balance(self, solar, status):
        pi, payload = solar
        r = outcome(shl_ev(payload, pi, terminal={"status": status}))
        assert r.status is CheckStatus.UNAVAILABLE and r.reason == "SHL_TERMINAL_STATUS_INVALID"

    def test_C_missing_status_key_is_unavailable(self, solar):
        pi, payload = solar
        ev = shl_ev(payload, pi)
        summary = copy.deepcopy(dict(ev.sponsor_summary))
        del summary["terminal_financial_state"]["shareholder_loan"]["status"]
        r = outcome(dataclasses.replace(ev, sponsor_summary=summary))
        assert r.status is CheckStatus.UNAVAILABLE and r.reason == "SHL_TERMINAL_STATUS_INVALID"

    def test_C_status_enum_mirrors_the_engine_enum(self):
        from app.model_quality.evidence import SHL_TERMINAL_STATUSES
        from financial_engine.project_returns.contracts import ShlTerminalStatus
        assert set(SHL_TERMINAL_STATUSES) == {s.value for s in ShlTerminalStatus}

    def test_C_contradictory_status_and_maturity_evidence(self, solar, maturity, no_shl_run):
        pi, payload = solar
        # outstanding-within-term cannot coexist with a reached, fully settled maturity
        r = outcome(shl_ev(payload, pi, terminal={"status": "OUTSTANDING_WITHIN_CONTRACTUAL_TERM"}))
        assert r.status is CheckStatus.UNAVAILABLE and r.reason == "SHL_TERMINAL_STATUS_CONTRADICTORY"
        # REPAID with a non-zero canonical unpaid / horizon balance
        for field in ("unpaid_at_maturity_keur", "terminal_model_horizon_balance_keur"):
            r = outcome(shl_ev(payload, pi, terminal={field: 3.0}))
            assert r.status in (CheckStatus.UNAVAILABLE, CheckStatus.FAIL)
            assert r.status is not CheckStatus.PASS
        # NOT_APPLICABLE while still carrying a maturity
        npi, npayload = no_shl_run
        r = outcome(shl_ev(npayload, npi, terminal={"contractual_maturity_period_index": 52}, rows=complete_shl_rows))
        assert r.status is CheckStatus.UNAVAILABLE and r.reason == "SHL_TERMINAL_STATUS_CONTRADICTORY"

    def test_C_unpaid_status_remains_a_failure(self, solar):
        pi, payload = solar
        r = outcome(shl_ev(payload, pi, terminal={"status": "UNPAID_AT_CONTRACTUAL_MATURITY",
                                                   "unpaid_at_maturity_keur": 4000.0}))
        assert r.status is CheckStatus.FAIL and r.reason == "UNPAID_SHL_AT_CONTRACTUAL_MATURITY"

    # regression anchors
    def test_correctly_repaid_and_material_unpaid_and_original_false_pass(self, solar, maturity):
        pi, payload = solar
        assert outcome(make_evidence(payload, pi)).status is CheckStatus.PASS
        assert outcome(shl_ev(payload, pi, rows=lambda t: row_for(t, maturity).update(shl=500.0))).status is CheckStatus.FAIL
        def inject(table):
            for r in table:
                if r["period_index"] >= maturity - 2:
                    r["shl"] = 9000.0
        r = outcome(shl_ev(payload, pi, rows=inject, sponsor_reported={"pure_equity_xirr_status": "NO_POSITIVE_CASHFLOW"}))
        assert r.status is CheckStatus.FAIL and r.value == 9000.0

    def test_four_real_references_unchanged(self, runs):
        for key, (pi, payload) in runs.items():
            c = evaluate_model_quality(make_evidence(payload, pi)).check("QM-TERM-002")
            assert c.status is CheckStatus.PASS and c.measured_value == 0.0, key
            s = evaluate_model_quality(make_evidence(payload, pi)).summary
            assert (s.passed, s.unavailable, s.not_applicable, s.score) == (25, 4, 1, 100.0), key

    def test_no_historical_evidence_is_unavailable(self):
        r = shl_terminal(Context(QualityEvidence(freshness="STALE")))
        assert r.status is CheckStatus.UNAVAILABLE and r.reason == "SHL_TERMINAL_AUTHORITY_NOT_PERSISTED"
