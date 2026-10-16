"""RC-4 / B Institutional Credit Decision V3 — synthetic evidence contracts (no engine, no database).

The synthetic entries carry exactly the persisted payloads the projection reads, so every authority rule is pinned
deterministically: unavailable stays unavailable, convergence is not feasibility, thresholds are classified, a failed
Run is a failure, and Run evidence is never mixed with Working Copy data.  Real canonical Runs are covered by
``tests/test_model_credit_decision_v3_real_runs.py``.
"""
from __future__ import annotations

import re
from pathlib import Path

import pytest

from app.model_quality.evidence import ProjectTerms
from app.persistence.run_history_repository import RunHistoryEntry
from app.v2 import credit_decision_projection as cd
from app.v2.credit_decision_projection import (
    ADVISORY, CONTRACTUAL, HISTORICAL, LAST_CURRENT, LAST_STALE, OBSERVED, UNSUPPORTED, RunInput, build_credit_decision)

ROOT = Path(__file__).resolve().parents[1]
N_PERIODS = 6


def su_block(*, capex=1000.0, idc=50.0, fee=10.0, structuring=15.0, dsra=40.0, senior=700.0, equity=None):
    total = capex + idc + fee + structuring + dsra
    equity = total - senior if equity is None else equity
    return {"base_project_capex_keur": capex, "capitalized_idc_keur": idc, "commitment_fee_keur": fee, "structuring_fee_keur": structuring,
            "other_financing_costs_keur": 0.0, "initial_dsra_funding_keur": dsra, "other_uses_keur": 0.0,
            "development_cost_reimbursement_keur": 0.0, "developer_fee_keur": 0.0, "senior_debt_keur": senior, "junior_or_other_keur": 0.0,
            "share_capital_and_other_equity_keur": equity, "shareholder_loan_cash_keur": 0.0, "total_sources_keur": total,
            "total_uses_keur": total, "difference_keur": 0.0}


def fin_evidence(snapshot, composite, scenario_id, *, binding="GEARING", dscr_capacity=900.0, gearing_capacity=700.0, **su_kwargs):
    su = su_block(**su_kwargs)
    total = su["total_uses_keur"]
    bank = {"dscr_debt_capacity_keur": dscr_capacity, "gearing_debt_capacity_keur": gearing_capacity, "final_senior_commitment_keur": su["senior_debt_keur"],
            "gearing_basis_keur": total, "gearing_ratio": 0.7, "fixed_point_iteration_count": 2, "fixed_point_maximum_difference_keur": 0.0}
    if binding is not None:
        bank["binding_senior_constraint"] = binding
    return {
        "authority": "CANONICAL_PROJECT_FINANCING_RESULT", "schema_version": "FINANCING_F1_V1", "units": "kEUR",
        "run_binding": {"snapshot_id": snapshot, "composite_hash": composite, "scenario_id": scenario_id},
        "sources_uses": su, "bankability": bank,
        "construction_funding": {
            "policy": "TEST_POLICY", "total_audit_uses_keur": total, "total_audit_sources_keur": total, "total_audit_residual_keur": 0.0,
            "periods": [{"period_index": 1, "project_cash_uses_keur": total, "senior_draw_keur": su["senior_debt_keur"],
                         "junior_or_other_main_funding_draw_keur": 0.0, "share_capital_draw_keur": su["share_capital_and_other_equity_keur"],
                         "share_premium_draw_keur": 0.0, "other_committed_equity_draw_keur": 0.0, "additional_equity_draw_keur": 0.0,
                         "shl_cash_draw_keur": 0.0, "sponsor_shl_cash_contribution_keur": 0.0, "total_sources_keur": total,
                         "sources_uses_difference_keur": 0.0, "cumulative_project_cash_uses_keur": total,
                         "cumulative_total_sources_keur": total, "cumulative_sources_uses_difference_keur": 0.0,
                         "period_start": "2030-01-01", "period_end": "2030-06-30", "cashflow_date": None}]}}


def make_entry(hid, *, scenario_id=None, dscrs=(1.4, 1.3, 1.25, 1.3, 1.4, 1.5), target=1.2, cfads=200.0, revenue=5000.0, senior=700.0,
               equity_irr=0.15, converged="CONVERGED", typed=True, binding="GEARING", llcr=None, lockups=(), dsra_balance=0.0,
               min_dscr=None, ran_at="2026-10-01T10:00:00+00:00", composite=None, engine="engine-1", **fin_kwargs):
    snapshot = f"snap-{hid}"
    composite = composite or f"composite-{hid}"
    periods, dates = [], {}
    for i, dscr in enumerate(dscrs, start=3):
        ds = cfads / dscr
        periods.append({"period_index": i, "base_cfads": cfads, "bank_cfads": cfads * 0.9, "debt_service": ds, "interest": ds * 0.4, "principal": ds * 0.6,
                        "opening": 1000.0 - i, "closing": 999.0 - i, "reported_dscr": dscr, "target_dscr": target, "annual_rate": 0.05 + i / 1000,
                        "availability": 1.0, "day_fraction": 0.5})
        dates[i] = f"{2031 + i // 2}-{'06-30' if i % 2 else '12-31'}"
    summary_min = min(dscrs) if min_dscr is None else min_dscr
    runtime = {"min_dscr": summary_min, "avg_dscr": sum(dscrs) / len(dscrs), "target_dscr": target, "senior_debt_keur": senior,
               "total_revenue_keur": revenue, "total_ebitda_keur": revenue * 0.8, "total_distributions_keur": 900.0, "actual_gearing_pct": 0.7,
               "gearing_cap_pct": 0.7, "periods_in_lockup": len(lockups), "project_irr": 0.09, "equity_irr": equity_irr,
               "total_senior_ds_keur": 1000.0, "share_capital_irr_status": "OK" if equity_irr is not None else "UNAVAILABLE_FIXED_DEBT_STRESS",
               "min_llcr": llcr}
    if typed:
        runtime["financing_evidence"] = fin_evidence(snapshot, composite, scenario_id, binding=binding, senior=senior, **fin_kwargs)
    return RunHistoryEntry(
        history_id=hid, user_id="u", project_id="p", project_code="proj", runtime_snapshot_id=snapshot, runtime_origin="v2_run", ran_at=ran_at,
        engine_version=engine, workbook_version="2.3.0", active_scenario_id=scenario_id, active_scenario_name=None,
        last_runtime_scenario_id=scenario_id, composite_hash=composite, last_runtime_identity={"engine_version": engine}, runtime_summary=runtime,
        financial_statements={}, debt_schedule={"periods": [{"period": i, "date": dates[i], "dsra_balance_keur": dsra_balance, "senior_ds_keur": 1.0} for i in dates],
                                                 "summary": {"min_llcr": llcr, "target_dscr": target, "total_senior_ds_keur": 1000.0}},
        tax_schedule={}, distribution_schedule={"periods": [{"period": i, "date": dates[i], "distribution_keur": 10.0, "lockup_active": i in lockups,
                                                                 "cash_sweep_keur": None} for i in dates], "summary": {}},
        sponsor_schedule={"summary": {"total_sponsor_contributed_keur": 300.0, "terminal_financial_state": {"senior": {
            "status": "REPAID", "contractual_maturity_date": "2040-12-31", "balance_at_contractual_maturity_keur": 0.0}}}},
        integrity_evidence={"senior_debt": {"day_count": "ACT_360", "diagnostics": {"termination_reason": converged, "converged": converged == "CONVERGED",
                                                                                       "is_authoritative": True, "final_debt_size_keur": senior},
                                            "periods": periods}},
        replay_metadata={}, created_at=ran_at)


def build(*entries, states=None, **kwargs):
    states = states or [LAST_CURRENT] + [HISTORICAL] * (len(entries) - 1)
    inputs = [RunInput(e, st, scenario_label="Base Case") for e, st in zip(entries, states)]
    return build_credit_decision(inputs, project_code="proj")


def finding(data, run_index, fid):
    run = data["runs"][run_index]["identity"]["history_id"]
    found = [f for f in data["findings"] if f["run_history_id"] == run and (f["check_id"] == fid or f["id"].endswith(":" + fid))]
    assert found, (fid, [f["id"] for f in data["findings"]])
    return found[0]


# ── structure of the payload -----------------------------------------------------------------------------------------
def test_run_count_and_duplicates_are_rejected():
    e = make_entry("a")
    with pytest.raises(ValueError, match="RUN_COUNT"):
        build_credit_decision([], project_code="p")
    with pytest.raises(ValueError, match="RUN_COUNT"):
        build_credit_decision([RunInput(make_entry(str(i))) for i in range(4)], project_code="p")
    with pytest.raises(ValueError, match="DUPLICATE"):
        build_credit_decision([RunInput(e), RunInput(e)], project_code="p")


def test_every_finding_has_one_of_the_four_classes_and_full_provenance():
    data = build(make_entry("a", dscrs=(0.9, 1.3, 1.25, 1.3, 1.4, 1.5)), make_entry("b"))
    keys = {"id", "source", "title", "classification", "status", "severity", "run_history_id", "scenario", "period", "metric", "actual", "threshold",
            "threshold_authority", "headroom", "evidence_source", "links"}
    assert data["findings"]
    for f in data["findings"]:
        assert keys <= set(f)
        assert f["classification"] in (cd.CONTRACTUAL, cd.ADVISORY, cd.OBSERVED, cd.UNSUPPORTED)
        assert {"statements", "diagnostics", "financing"} <= set(f["links"])
    assert sum(data["finding_counts"].values()) == len(data["findings"])


# ── F-1 / sizing evidence: committed, never reconstructed ------------------------------------------------------------
def test_committed_capacity_and_binding_constraint_are_read_from_the_run():
    data = build(make_entry("a", dscr_capacity=900.0, gearing_capacity=700.0))
    cap = data["runs"][0]["capacity"]
    assert cap["dscr_debt_capacity"]["v"] == 900.0 and cap["gearing_debt_capacity"]["v"] == 700.0
    assert cap["binding_constraint"]["v"] == "GEARING"
    assert data["runs"][0]["structure"]["state"] == "AVAILABLE"


def test_missing_binding_constraint_is_unavailable_and_not_inferred_from_gearing_or_capacity():
    # capacities and gearing would both "prove" GEARING, but the Run did not persist the label
    data = build(make_entry("a", binding=None, dscr_capacity=900.0, gearing_capacity=700.0))
    assert data["runs"][0]["capacity"]["binding_constraint"]["v"] is None
    assert data["runs"][0]["capacity"]["binding_constraint"]["d"] == "UNAVAILABLE"
    f = finding(data, 0, "CD-BINDING")
    assert f["classification"] == UNSUPPORTED and f["status"] == "UNAVAILABLE"


def test_legacy_run_without_typed_financing_evidence_stays_unavailable_never_backfilled():
    data = build(make_entry("legacy", typed=False))
    run = data["runs"][0]
    assert run["structure"]["state"] == "LEGACY"
    assert run["capacity"]["dscr_debt_capacity"]["v"] is None and run["capacity"]["gearing_debt_capacity"]["v"] is None
    assert run["structure"]["total_uses"]["v"] is None and run["structure"]["fees"]["capitalized_idc"]["v"] is None
    assert run["structure"]["requested_gearing"]["v"] is None


def test_malformed_financing_evidence_fails_closed_without_numbers():
    entry = make_entry("a")
    entry.runtime_summary["financing_evidence"]["sources_uses"]["difference_keur"] = 5.0     # breaks the persisted identity
    data = build(entry)
    s = data["runs"][0]["structure"]
    assert s["state"] == "INVALID" and "MALFORMED" in s["reason"] or "MISMATCH" in s["reason"]
    assert s["total_uses"]["v"] is None and s["facilities"] == []


def test_run_binding_mismatch_is_rejected():
    entry = make_entry("a")
    entry.runtime_summary["financing_evidence"]["run_binding"]["snapshot_id"] = "another-snapshot"
    assert build(entry)["runs"][0]["structure"]["state"] == "INVALID"


# ── F-2 convergence is not credit feasibility -----------------------------------------------------------------------
def test_dscr_below_one_with_converged_solver_is_surfaced_as_distinct_facts():
    data = build(make_entry("a", dscrs=(1.3, 0.8, 1.25, 1.3, 1.4, 1.5)))
    cap = data["runs"][0]["capacity"]
    assert cap["convergence"]["termination_reason"]["v"] == "CONVERGED" and cap["convergence"]["converged"] is True
    assert cap["min_dscr"]["v"] == pytest.approx(0.8)
    f = finding(data, 0, "CD-F2")
    assert f["classification"] == OBSERVED and f["status"] == "FAIL" and "CONVERGED" in f["title"]
    assert f["threshold"]["v"] == 1.0 and f["headroom"]["v"] == pytest.approx(-0.2)
    assert "not a lender covenant" in f["threshold_authority"]
    shortfall = finding(data, 0, "CD-SHORTFALL")
    assert shortfall["actual"]["v"] == 1 and "P4" in shortfall["period"]


def test_no_f2_finding_when_dscr_is_at_or_above_one():
    data = build(make_entry("a"))
    assert not [f for f in data["findings"] if f["id"].endswith("CD-F2") or f["id"].endswith("CD-SHORTFALL")]


# ── threshold authority: missing vs breach; never a covenant without a contractual term -----------------------------
def test_missing_thresholds_are_unsupported_not_pass_or_breach():
    data = build(make_entry("a"))
    for cid in ("QM-COV-001", "QM-COV-002", "QM-COV-003"):
        f = finding(data, 0, cid)
        assert f["classification"] == UNSUPPORTED and f["status"] == "UNAVAILABLE", (cid, f["status"])


def test_project_input_lockup_breach_is_advisory_with_computed_headroom_never_a_default():
    terms = ProjectTerms(lockup_dscr=1.5, provenance={"lockup_dscr": "financing.lockup_dscr"})
    data = build_credit_decision([RunInput(make_entry("a"), LAST_CURRENT, "Base Case", terms=terms)], project_code="p")
    f = finding(data, 0, "QM-COV-002")
    assert f["classification"] == ADVISORY and f["status"] == "WARNING"
    assert f["threshold"]["v"] == 1.5 and f["headroom"]["v"] == pytest.approx(1.25 - 1.5)
    assert "not verified as contractual" in f["threshold_authority"] and "CONTRACTUAL term" not in f["threshold_authority"]
    assert not any("DEFAULT" in str(f["title"]).upper() and f["status"] == "FAIL" for f in data["findings"])
    eod = finding(data, 0, "CD-EOD")
    assert eod["classification"] == UNSUPPORTED and eod["status"] == "UNAVAILABLE"


def test_genuine_breach_is_contractual_only_when_the_term_is_supplied_as_contractual():
    contractual = ProjectTerms(min_dscr_covenant=1.3, lockup_dscr=1.35, contractual=True,
                               provenance={"lockup_dscr": "financing.lockup_dscr"})
    data = build_credit_decision([RunInput(make_entry("a"), LAST_CURRENT, "Base Case", terms=contractual)], project_code="p")
    cov = finding(data, 0, "QM-COV-001")
    assert cov["classification"] == CONTRACTUAL and cov["status"] == "FAIL" and "CONTRACTUAL term" in cov["threshold_authority"]
    assert cov["headroom"]["v"] == pytest.approx(1.25 - 1.3)
    lock = finding(data, 0, "QM-COV-002")
    assert lock["classification"] == CONTRACTUAL
    advisory = ProjectTerms(min_dscr_covenant=1.3, contractual=False)
    data2 = build_credit_decision([RunInput(make_entry("b"), LAST_CURRENT, "Base Case", terms=advisory)], project_code="p")
    soft = finding(data2, 0, "QM-COV-001")
    # the same shortfall against a non-contractual threshold is never presented as a covenant breach
    assert soft["classification"] == ADVISORY and soft["status"] == "BELOW_PROJECT_INPUT_THRESHOLD"
    assert "not verified as contractual" in soft["threshold_authority"] and soft["headroom"]["v"] == pytest.approx(1.25 - 1.3)


def test_historical_and_stale_runs_never_inherit_working_copy_terms():
    terms = ProjectTerms(lockup_dscr=1.5, min_llcr=1.4)
    for state in (HISTORICAL, LAST_STALE):
        data = build_credit_decision([RunInput(make_entry("a"), state, "Base Case", terms=terms, working={"lender_case": "P90-10y", "sizing_mode": "gearing_cap"})],
                                     project_code="p")
        f = finding(data, 0, "QM-COV-002")
        assert f["classification"] == UNSUPPORTED and f["status"] == "UNAVAILABLE"
        # the request layer decides binding; the projection labels whatever working values it is handed as bound Working Copy terms
    data = build_credit_decision([RunInput(make_entry("a"), HISTORICAL, "Base Case")], project_code="p")
    lender = data["runs"][0]["structure"]["lender_case"]
    assert lender["value"]["v"] is None and "not persisted" in lender["value"]["reason"]
    assert data["runs"][0]["structure"]["sizing_mode"]["value"]["v"] is None


def test_lender_case_is_labelled_separately_from_the_operating_case_when_bound():
    data = build_credit_decision([RunInput(make_entry("a"), LAST_CURRENT, "Base Case", working={"lender_case": "P90-10y", "sizing_mode": "flat_dscr_sculpted"})],
                                 project_code="p")
    lc = data["runs"][0]["structure"]["lender_case"]
    assert lc["value"]["v"] == "P90-10y" and "bound Working Copy" in lc["credit_case"] and "Operational generation case" in lc["operating_case"]
    assert "gearing cap" in data["runs"][0]["structure"]["sizing_mode"]["note"]


# ── F-5 / F-6 unavailable metrics -----------------------------------------------------------------------------------
def test_unavailable_equity_irr_is_never_zero_or_estimated():
    data = build(make_entry("a", equity_irr=None), make_entry("b"))
    f = finding(data, 0, "CD-F5")
    assert f["classification"] == UNSUPPORTED and f["actual"]["v"] is None and f["actual"]["d"] == "UNAVAILABLE"
    row = next(r for g in data["comparison"]["groups"] for r in g["rows"] if r["key"] == "equity_irr")
    assert row["cells"][0]["v"] is None and row["cells"][0]["d"] == "UNAVAILABLE" and row["deltas"][1]["d"] == "—"


def test_llcr_plcr_eod_cash_sweep_are_unavailable_with_exact_gaps():
    data = build(make_entry("a", llcr=None))
    for fid in ("CD-LLCR", "CD-PLCR", "CD-EOD", "CD-SWEEP"):
        f = finding(data, 0, fid)
        assert f["classification"] == UNSUPPORTED and f["status"] == "UNAVAILABLE", fid
        assert f["detail"]
    assert data["runs"][0]["capacity"]["min_llcr"]["v"] is None
    with_llcr = build(make_entry("b", llcr=1.42))
    f = finding(with_llcr, 0, "CD-LLCR")
    assert f["classification"] == OBSERVED and f["actual"]["v"] == pytest.approx(1.42)


def test_persisted_cash_sweep_is_inventoried_as_an_observed_value():
    entry = make_entry("a")
    entry.distribution_schedule["periods"][0]["cash_sweep_keur"] = 12.5
    f = finding(build(entry), 0, "CD-SWEEP")
    assert f["classification"] == OBSERVED and f["actual"]["v"] == pytest.approx(12.5)


# ── F-8 failure is failure ------------------------------------------------------------------------------------------
def test_committed_run_with_failed_integrity_is_labelled_a_failure_not_a_bankable_scenario(monkeypatch):
    class Report:
        def to_dict(self):
            return {"overall": "FAIL", "counts": {"FAIL": 1}, "checks": [{"check_id": "QM-SD-004", "title": "x", "status": "FAIL", "reason_code": "DS_EXCEEDS"}]}
    monkeypatch.setattr("app.run_integrity.run_integrity_checks", lambda evidence: Report())
    data = build(make_entry("a"))
    run = data["runs"][0]
    assert run["identity"]["integrity"] == "FAIL" and run["identity"]["committed_with_integrity_failure"] is True
    f = finding(data, 0, "CD-INTEGRITY")
    assert f["status"] == "FAIL" and "not a bankable scenario" in f["detail"] and f["classification"] == OBSERVED
    assert "never recorded" not in f["detail"] and "failed or fail-closed" in data["policy"]["failed_runs"].lower()


# ── F-3 debt capacity moving against revenue ------------------------------------------------------------------------
def test_debt_up_revenue_down_lists_committed_uses_lines_when_gearing_binds_in_both_runs():
    base = make_entry("base", revenue=5000.0, senior=700.0, idc=50.0, dsra=40.0)
    down = make_entry("down", revenue=4000.0, senior=712.0, idc=70.0, dsra=60.0, ran_at="2026-10-02T10:00:00+00:00")
    data = build(base, down)
    f3 = data["comparison"]["f3"]
    assert len(f3) == 1 and f3[0]["attribution"] == "COMMITTED_USES_LINES"
    assert f3[0]["revenue_change"]["v"] == pytest.approx(-1000.0) and f3[0]["commitment_change"]["v"] > 0
    assert f3[0]["uses_changes"]["idc"]["v"] == pytest.approx(20.0) and f3[0]["uses_changes"]["initial_dsra"]["v"] == pytest.approx(20.0)
    assert "not a causal proof" in f3[0]["statement"]


def test_debt_up_revenue_down_is_not_attributed_when_the_binding_constraint_is_missing():
    base = make_entry("base", revenue=5000.0, senior=700.0, binding=None)
    down = make_entry("down", revenue=4000.0, senior=712.0, idc=70.0, binding=None)
    f3 = build(base, down)["comparison"]["f3"]
    assert f3[0]["attribution"] == "UNAVAILABLE" and "causal decomposition UNAVAILABLE" in f3[0]["statement"]


def test_no_f3_note_when_debt_does_not_rise_with_revenue_falling():
    assert build(make_entry("a", revenue=5000.0, senior=700.0), make_entry("b", revenue=4000.0, senior=650.0))["comparison"]["f3"] == []
    assert build(make_entry("a", revenue=5000.0, senior=700.0), make_entry("b", revenue=6000.0, senior=720.0))["comparison"]["f3"] == []


# ── comparison semantics --------------------------------------------------------------------------------------------
def test_comparison_deltas_are_plain_differences_against_the_first_run_and_flags_are_exact():
    data = build(make_entry("a", revenue=5000.0, senior=700.0), make_entry("b", revenue=4500.0, senior=690.0, composite="composite-a", engine="engine-2"))
    rows = {r["key"]: r for g in data["comparison"]["groups"] for r in g["rows"]}
    assert rows["total_revenue"]["deltas"][1]["v"] == pytest.approx(-500.0) and rows["total_revenue"]["deltas"][0] is None
    assert rows["final_commitment"]["deltas"][1]["v"] == pytest.approx(-10.0)
    notes = " ".join(data["comparison"]["notes"])
    assert "same composite input identity" in notes and "different engine versions" in notes


def test_single_run_has_no_comparison_and_says_so():
    comparison = build(make_entry("a"))["comparison"]
    assert comparison["available"] is False and "two or three" in comparison["reason"]


def test_period_matrix_uses_committed_period_identities_and_flags_below_target():
    data = build(make_entry("a", dscrs=(1.19, 1.3, 1.25, 1.3, 1.4, 1.5), target=1.2, lockups=(4,)))
    tl = data["runs"][0]["timeline"]
    assert [c["index"] for c in tl["columns"]] == [3, 4, 5, 6, 7, 8] and all(c["date"] for c in tl["columns"])
    by = {r["key"]: r for r in tl["rows"]}
    assert by["below_target"]["cells"][0]["v"] is True and by["below_target"]["cells"][1]["v"] is False
    assert by["below_one"]["cells"][0]["v"] is False
    assert by["lockup"]["cells"][1]["v"] is True and by["lockup"]["cells"][0]["v"] is False
    assert all(len(r["cells"]) == len(tl["columns"]) for r in tl["rows"])
    tight = data["runs"][0]["capacity"]["tightest"][0]
    assert tight["period_index"] == 3 and tight["dscr"]["v"] == pytest.approx(1.19)


def test_missing_period_evidence_is_unavailable_not_zero():
    entry = make_entry("a")
    entry.distribution_schedule["periods"] = []
    entry.debt_schedule["periods"] = []
    tl = build(entry)["runs"][0]["timeline"]
    by = {r["key"]: r for r in tl["rows"]}
    assert all(c["v"] is None and c["d"] == "UNAVAILABLE" for c in by["distribution"]["cells"])
    assert all(c["v"] is None for c in by["lockup"]["cells"]) and all(c["v"] is None for c in by["dsra_balance"]["cells"])
    entry2 = make_entry("b")
    object.__setattr__(entry2, "integrity_evidence", {})
    assert build(entry2)["runs"][0]["timeline"]["available"] is False


def test_dsra_regime_is_only_available_when_bound_and_dsrf_is_not_read_as_a_balance():
    data = build_credit_decision([RunInput(make_entry("a", dsra_balance=0.0), LAST_CURRENT, "Base Case", working={"reserve_regime": "DSRF"}),
                                  RunInput(make_entry("b", dsra_balance=500.0), HISTORICAL, "Base Case")],
                                 project_code="p")
    first, second = data["runs"]
    assert first["structure"]["reserve"]["regime"]["v"] == "DSRF" and "not cash funded" in first["structure"]["reserve"]["dsrf_note"]
    assert second["structure"]["reserve"]["regime"]["v"] is None
    assert first["structure"]["reserve"]["dsra_peak_balance"]["v"] == 0.0           # a persisted zero is a value
    assert second["structure"]["reserve"]["dsra_peak_balance"]["v"] == 500.0


def test_working_copy_proposal_is_carried_separately_and_never_enters_run_columns():
    proposal = {"available": True, "saved_only": True, "active_in_working_copy": False, "has_saved_proposal": True}
    data = build_credit_decision([RunInput(make_entry("a"), LAST_CURRENT, "Base Case")], project_code="p", working_proposal=proposal)
    assert data["working_proposal"]["saved_only"] is True
    assert "working_proposal" not in data["runs"][0] and "saved_only" not in str(data["runs"][0]["structure"])


def test_unproven_scenario_is_unavailable_never_base_case():
    data = build_credit_decision([RunInput(make_entry("a", scenario_id="gone"), HISTORICAL, None)], project_code="p")
    assert data["runs"][0]["identity"]["scenario"] == "UNAVAILABLE"


# ── scope guards -----------------------------------------------------------------------------------------------------
def test_projection_is_pure_no_engine_no_repository_no_writes():
    src = (ROOT / "app/v2/credit_decision_projection.py").read_text(encoding="utf-8")
    for forbidden in ("financial_engine", "finco_core", "run_project", "run_clean_production", "get_cursor", "INSERT", "UPDATE ", "append_run_history",
                      "update_scenario", "save_workspace", "requests.", "httpx"):
        assert forbidden not in src, forbidden


def test_router_has_a_single_get_route_and_no_write_path():
    from app.v2.credit_decision_router import router
    routes = [(r.path, sorted(r.methods)) for r in router.routes]
    assert routes == [("/credit-decision", ["GET"])]
    src = (ROOT / "app/v2/credit_decision_router.py").read_text(encoding="utf-8")
    for forbidden in ("run_project", "run_clean_production", "append_run_history", "update_scenario", "add_scenario", "save_", "commit(", "execute("):
        assert forbidden not in src, forbidden


def test_scoped_javascript_has_no_financial_calculation_and_no_network():
    js = (ROOT / "static/js/model_credit_decision.js").read_text(encoding="utf-8")
    assert not re.search(r"\b(fetch|XMLHttpRequest|sendBeacon|WebSocket)\b|toFixed|parseFloat|Math\.(round|pow|exp|log|sqrt|abs)|eval\(|innerHTML", js)
    assert "textContent" in js


def test_template_never_emits_an_unavailable_value_as_zero():
    html = (ROOT / "app/templates/v2/credit_decision.html").read_text(encoding="utf-8")
    assert "or 0" not in html and "| default(0" not in html and "default(0)" not in html
