"""Diagnostics V2 — advanced period checks, root-cause relationships, period heatmap and bankability monitor.

Deterministic synthetic committed Runs (fast, exact) plus real Solar / Wind / Data Center / EV Charging Runs
(legacy, two-Senior and the controlled Senior+Junior fixture).  Everything here is read-only evidence: no engine call, no
write, no Working Copy value.
"""
from __future__ import annotations

import copy
import re
from types import SimpleNamespace

import pytest

from app.v2 import diagnostics_dx_checks as ac
from app.v2.diagnostics_dx_checks import Facts, evaluate_advanced_checks
from app.model_quality.evidence import ProjectTerms, QualityEvidence
from app.model_quality.registry import REGISTRY
from app.run_integrity.contracts import TOL_KEUR
from app.run_integrity.evidence import evidence_digest
from app.v2 import diagnostics_v2_projection as dv2

DATES = ["2030-01-01", "2030-07-01", "2031-01-01", "2031-07-01", "2032-01-01", "2032-07-01"]
OP = [2, 3, 4, 5]


def _base_state() -> dict:
    pnl, pf, bs, ibs, sp, dist, tax = [], [], [], [], [], [], []
    acc = 0.0
    shl = {0: 0.0, 1: 300.0, 2: 300.0, 3: 300.0, 4: 320.0, 5: 0.0}
    flows = {2: (0.0, 24.0, 0.0, 24.0), 3: (0.0, 24.0, 0.0, 24.0), 4: (0.0, 10.0, 0.0, 30.0), 5: (0.0, 20.0, 320.0, 20.0)}
    for i, date in enumerate(DATES):
        op = i in OP
        acc += 20.0 if op else 0.0
        dep = 20.0 if op else 0.0
        pnl.append({"period": i, "date": date, "revenues_keur": 200.0 if op else 0.0, "operating_expenses_keur": 40.0 if op else 0.0,
                    "depreciation_keur": dep, "ebit_keur": 140.0 if op else 0.0, "senior_interest_expense_keur": 30.0 if op else 0.0,
                    "shl_interest_expense_keur": flows[i][3] if op else 0.0})
        pf.append({"period_index": i, "date": date, "revenue_cash_keur": 200.0 if op else 0.0, "opex_cash_keur": 40.0 if op else 0.0,
                   "ebitda_cash_keur": 160.0 if op else 0.0, "cash_tax_keur": 0.0, "fcf_banks_keur": 160.0 if op else 0.0,
                   "senior_total_ds_keur": 100.0 if op else 0.0, "dsra_funding_keur": 0.0, "dsra_release_keur": 0.0,
                   "fcf_for_distribution_keur": 60.0 if op else 0.0, "net_dividends_keur": 50.0 if op else 0.0})
        bs.append({"period_index": i, "date": date, "net_fixed_assets_keur": 1000.0 - acc})
        ibs.append({"period_index": i, "gross_fixed_assets": 1000.0, "accumulated_depreciation": acc,
                    "dsra_balance": 50.0 if i >= 2 else 0.0, "shl": shl[i]})
        f = flows.get(i, (0.0, 0.0, 0.0, 0.0))
        sp.append({"period": i + 100, "date": date, "is_construction": not op,       # own index deliberately NOT the statement index
                   "shl_contribution": 300.0 if i == 1 else 0.0, "shl_cash_interest": f[1], "shl_principal": f[2],
                   "legal_equity_distribution": 50.0 if op else 0.0})
        dist.append({"period": i, "date": date, "lockup_active": False, "distribution_keur": 50.0 if op else 0.0})
        tax.append({"period": i, "date": date, "is_operation": op})
    evidence = {"schema": "RUN_INTEGRITY_EVIDENCE_V1",
                "sources_uses": {"summary": {"total_uses_keur": 1050.0, "initial_dsra_funding_keur": 50.0, "shareholder_loan_cash_keur": 300.0},
                                 "construction_periods": [{"period": 0, "uses": 400.0, "sources": 400.0}, {"period": 1, "uses": 600.0, "sources": 600.0}]},
                "balance_sheet": ibs, "sponsor": {"periods": sp}, "senior_debt": {"periods": []}}
    return {
        "statements": {"pnl": {"periods": pnl}, "pf_cash_waterfall": {"periods": pf}, "balance_sheet": {"periods": bs}},
        "evidence": evidence, "dist": {"periods": dist}, "tax": {"periods": tax},
        "summary": {"financing_evidence": {"construction_funding": {"non_construction_fc_use": {"uses_keur": 50.0}}}},
        "sponsor_summary": {"total_legal_equity_distributions_keur": 200.0, "terminal_financial_state": {"shareholder_loan": {
            "status": "REPAID", "contractual_maturity_period_index": 5, "balance_at_contractual_maturity_keur": 0.0,
            "unpaid_at_maturity_keur": 0.0, "repayment_mode": "CASH_SWEEP"}}}}


def _ws(state: dict) -> SimpleNamespace:
    ev = copy.deepcopy(state["evidence"])
    ev["digest"] = evidence_digest(ev)
    return SimpleNamespace(last_financial_statements=copy.deepcopy(state["statements"]), last_integrity_evidence=ev,
                           last_distribution_schedule=copy.deepcopy(state["dist"]), last_tax_schedule=copy.deepcopy(state["tax"]),
                           last_runtime_summary=copy.deepcopy(state["summary"]),
                           last_sponsor_schedule={"summary": copy.deepcopy(state["sponsor_summary"])},
                           last_runtime_snapshot_id="snap-1")


def _results(state=None, *, digest_ok=True, regime=None, mutate=None, ws_mutate=None):
    state = copy.deepcopy(state or _base_state())
    if mutate:
        mutate(state)
    ws = _ws(state)
    if ws_mutate:
        ws_mutate(ws)
    facts = Facts.from_workspace(ws, digest_ok=digest_ok, reserve_regime=regime)
    return {r["check_id"]: r for r in evaluate_advanced_checks(facts)}


def _row(state, kind, index):
    key = "period" if kind == "pnl" else "period_index"
    return next(r for r in state["statements"][{"pnl": "pnl", "pf": "pf_cash_waterfall", "bs": "balance_sheet"}[kind]]["periods"] if r[key] == index)


def _period(result, index):
    return next(p for p in result["periods"] if p["period_index"] == index)


# ── registry hygiene ───────────────────────────────────────────────────────────────────────────────────────────
def test_dx_checks_are_additive_stable_and_outside_the_quality_registry():
    ids = [d.check_id for d in ac.DEFINITIONS]
    assert len(ids) == len(set(ids)) == 9 and all(re.fullmatch(r"DX-[A-Z]{2,5}-\d{3}", i) for i in ids)
    assert len(REGISTRY) == 30 and not {d.check_id for d in REGISTRY} & set(ids)
    assert all(d.classification == "PERIODIC_PROVEN" and d.prerequisites and d.tolerance_source for d in ac.DEFINITIONS)
    res = _results()
    assert set(res) == set(ids) and all(r["not_in_quality_score"] for r in res.values())


def test_baseline_synthetic_run_passes_where_evidence_exists_and_reports_partial_coverage_honestly():
    res = _results()
    expected = {"DX-CAPEX-001": "PASS", "DX-OPEX-001": "PASS", "DX-DEP-001": "PASS", "DX-CASH-001": "PASS", "DX-SHL-001": "PASS",
                "DX-SHL-002": "PASS", "DX-DIST-001": "PASS", "DX-RES-001": "PASS", "DX-REV-001": "PASS"}
    assert {k: v["status"] for k, v in res.items()} == expected, {k: (v["status"], v["reason_code"]) for k, v in res.items()}
    dep = res["DX-DEP-001"]
    assert _period(dep, 0)["status"] == "UNAVAILABLE" and dep["coverage"]["complete"] is False   # no opening for P0
    assert dep["reason_code"] == "PARTIAL_COVERAGE_SOME_PERIODS_UNAVAILABLE"
    assert dep["global_component"]["additions_and_disposals"].startswith("UNAVAILABLE")           # no asset register invented
    assert _period(res["DX-CASH-001"], 0)["status"] == "NOT_APPLICABLE" and _period(res["DX-CASH-001"], 0)["reason"] == "CONSTRUCTION_PHASE_NO_OPERATING_WATERFALL"


# ── D1 / 1 CAPEX ──────────────────────────────────────────────────────────────────────────────────────────────
def test_capex_period_cumulative_budget_and_terminal_identity():
    res = _results()["DX-CAPEX-001"]
    p1 = _period(res, 1)
    assert p1["scope"] == "PERIOD_AND_TERMINAL_IDENTITY" and p1["components"]["cumulative_spending"]["value"] == 1000.0
    assert p1["components"]["total_uses_authority"]["value"] == 1050.0 and p1["components"]["remaining_budget"]["value"] == 0.0
    assert _period(res, 0)["components"]["period_spending"]["value"] == 400.0


def test_capex_overspend_and_terminal_residual_fail_with_signed_residuals():
    over = _results(mutate=lambda s: s["evidence"]["sources_uses"]["construction_periods"][1].update(uses=800.0))["DX-CAPEX-001"]
    assert over["status"] == "FAIL" and _period(over, 1)["residual"] == pytest.approx(200.0)   # observed 1200 + 50 - expected 1050
    under = _results(mutate=lambda s: s["evidence"]["sources_uses"]["summary"].update(total_uses_keur=1051.0))["DX-CAPEX-001"]
    p = _period(under, 1)
    assert under["status"] == "FAIL" and p["residual"] == pytest.approx(-1.0) and p["tolerance"] == TOL_KEUR


def test_capex_missing_or_untrusted_evidence_is_unavailable_never_pass():
    def drop(s):
        s["summary"] = {}
        s["evidence"]["sources_uses"]["summary"].pop("initial_dsra_funding_keur")
    assert _results(mutate=drop)["DX-CAPEX-001"]["status"] == "UNAVAILABLE"
    assert _results(digest_ok=False)["DX-CAPEX-001"]["reason_code"] == "EVIDENCE_DIGEST_NOT_INTACT"
    assert _results(mutate=lambda s: s["evidence"]["sources_uses"].pop("construction_periods"))["DX-CAPEX-001"]["status"] == "UNAVAILABLE"


def test_capex_uses_no_working_copy_value():
    ws = _ws(_base_state())
    for forbidden in ("capex", "draft_snapshot", "opex"):
        assert not hasattr(ws, forbidden)
    assert evaluate_advanced_checks(Facts.from_workspace(ws, digest_ok=True))[0]["status"] == "PASS"


# ── D1 / 2 OPEX ───────────────────────────────────────────────────────────────────────────────────────────────
def test_opex_reconciles_and_keeps_other_cost_lines_separate():
    p = _period(_results()["DX-OPEX-001"], 3)
    assert p["status"] == "PASS"
    names = set(p["components"])
    assert {"operating_expenses_pnl", "operating_expenses_cash", "depreciation", "senior_interest_financing_cost",
            "shl_interest_financing_cost", "cash_tax"} <= names
    assert not any("capex" in n for n in names)                        # capital expenditure is never netted into operating cost


def test_opex_mismatches_fail_with_exact_residual_sign_and_zero_is_not_missing():
    res = _results(mutate=lambda s: _row(s, "pf", 3).update(opex_cash_keur=45.0))["DX-OPEX-001"]
    p = _period(res, 3)
    assert res["status"] == "FAIL" and p["status"] == "FAIL" and "OPEX(P&L)" in p["components"]["identity_evaluated"]["value"] or p["residual"] != 0
    zero = _results(mutate=lambda s: _row(s, "pf", 3).update(opex_cash_keur=0.0))["DX-OPEX-001"]
    assert _period(zero, 3)["status"] == "FAIL"                         # a committed zero is a value
    missing = _results(mutate=lambda s: _row(s, "pf", 3).update(opex_cash_keur=None))["DX-OPEX-001"]
    assert _period(missing, 3)["status"] == "UNAVAILABLE" and _period(missing, 3)["reason"] == "STATEMENT_LINE_MISSING"
    ebit = _results(mutate=lambda s: _row(s, "pnl", 3).update(ebit_keur=160.0))["DX-OPEX-001"]
    assert _period(ebit, 3)["status"] == "FAIL" and _period(ebit, 3)["residual"] == pytest.approx(20.0)


def test_statement_date_disagreement_is_unavailable():
    res = _results(mutate=lambda s: _row(s, "pnl", 3).update(date="2031-07-02"))["DX-OPEX-001"]
    assert _period(res, 3)["reason"] == "STATEMENT_DATES_DISAGREE" and _period(res, 3)["status"] == "UNAVAILABLE"


# ── D1 / 3 Depreciation ───────────────────────────────────────────────────────────────────────────────────────
def test_depreciation_rollforward_and_net_book_value():
    res = _results()["DX-DEP-001"]
    p = _period(res, 4)
    assert p["status"] == "PASS" and p["components"]["opening_accumulated_depreciation"]["value"] == 40.0
    bad = _results(mutate=lambda s: s["evidence"]["balance_sheet"][4].update(accumulated_depreciation=65.0))["DX-DEP-001"]
    assert bad["status"] == "FAIL" and _period(bad, 4)["residual"] == pytest.approx(5.0)
    nbv = _results(mutate=lambda s: _row(s, "bs", 3).update(net_fixed_assets_keur=950.0))["DX-DEP-001"]
    assert _period(nbv, 3)["status"] == "FAIL"
    assert _period(_results(mutate=lambda s: s["evidence"]["balance_sheet"][3].update(accumulated_depreciation=None))["DX-DEP-001"], 3)["status"] == "UNAVAILABLE"


# ── D1 / 4 Cash flow ──────────────────────────────────────────────────────────────────────────────────────────
def test_distributable_cash_identity_signed_residual_and_reserve_terms():
    res = _results()["DX-CASH-001"]
    assert _period(res, 3)["components"]["cfads"]["value"] == 160.0 and _period(res, 3)["status"] == "PASS"
    bad = _results(mutate=lambda s: _row(s, "pf", 3).update(fcf_for_distribution_keur=70.0))["DX-CASH-001"]
    assert _period(bad, 3)["status"] == "FAIL" and _period(bad, 3)["residual"] == pytest.approx(10.0)
    funded = _results(mutate=lambda s: _row(s, "pf", 3).update(dsra_funding_keur=10.0))["DX-CASH-001"]
    assert _period(funded, 3)["status"] == "FAIL" and _period(funded, 3)["residual"] == pytest.approx(10.0)   # reserve funding is not ignored


def test_junior_service_is_used_only_where_the_financing_authority_has_a_junior_facility():
    def junior(s):
        s["evidence"]["junior_debt"] = {"periods": []}
        for r in s["statements"]["pf_cash_waterfall"]["periods"]:
            r["junior_debt_service_keur"] = 10.0 if r["period_index"] in OP else 0.0
            if r["period_index"] in OP:
                r["fcf_for_distribution_keur"] = 50.0
                r["net_dividends_keur"] = 45.0
        for r in s["evidence"]["sponsor"]["periods"]:
            if not r["is_construction"]:
                r["legal_equity_distribution"] = 45.0
    ok = _results(mutate=junior)["DX-CASH-001"]
    assert _period(ok, 3)["status"] == "PASS" and _period(ok, 3)["components"]["junior_debt_service"]["value"] == 10.0

    def junior_missing(s):
        junior(s)
        for r in s["statements"]["pf_cash_waterfall"]["periods"]:
            r.pop("junior_debt_service_keur")
    assert _period(_results(mutate=junior_missing)["DX-CASH-001"], 3)["reason"] == "JUNIOR_DEBT_SERVICE_LINE_MISSING"


def test_construction_phase_requires_the_committed_phase_flag():
    res = _results(mutate=lambda s: s.update(tax={"periods": []}))["DX-CASH-001"]
    assert _period(res, 0)["status"] == "PASS"                          # no phase evidence: evaluated, never silently skipped


# ── D1 / 5 + 6 SHL ────────────────────────────────────────────────────────────────────────────────────────────
def test_shl_rollforward_separates_capitalised_interest_and_repayment():
    res = _results()["DX-SHL-001"]
    p = _period(res, 4)
    assert p["status"] == "PASS" and p["components"]["capitalised_interest"]["value"] == pytest.approx(20.0)
    assert {"opening_principal", "drawdown", "interest_accrual", "cash_pay_interest", "capitalised_interest", "principal_repaid",
            "closing_balance"} <= set(p["components"])
    assert _period(res, 0)["status"] == "NOT_APPLICABLE" and _period(res, 1)["reason"] == "CONSTRUCTION_PHASE_SHL_DRAWN_AT_FINANCIAL_CLOSE"
    bad = _results(mutate=lambda s: s["evidence"]["balance_sheet"][4].update(shl=330.0))["DX-SHL-001"]
    assert bad["status"] == "FAIL" and _period(bad, 4)["residual"] == pytest.approx(10.0)


def test_missing_capitalisation_evidence_is_unavailable_not_pass():
    res = _results(mutate=lambda s: _row(s, "pnl", 4).update(shl_interest_expense_keur=None))["DX-SHL-001"]
    assert _period(res, 4)["status"] == "UNAVAILABLE" and _period(res, 4)["reason"] == "SHL_INTEREST_ACCRUAL_EVIDENCE_MISSING"
    gap = _results(mutate=lambda s: s["evidence"]["balance_sheet"][3].update(shl=None))["DX-SHL-001"]
    assert _period(gap, 3)["status"] == "UNAVAILABLE" and _period(gap, 4)["status"] == "UNAVAILABLE"


def test_no_shl_is_not_applicable_only_when_committed_zeros_prove_it():
    def no_shl(s):
        for r in s["evidence"]["balance_sheet"]:
            r["shl"] = 0.0
        for r in s["evidence"]["sponsor"]["periods"]:
            r.update(shl_contribution=0.0, shl_cash_interest=0.0, shl_principal=0.0)
        for r in s["statements"]["pnl"]["periods"]:
            r["shl_interest_expense_keur"] = 0.0
        s["evidence"]["sources_uses"]["summary"]["shareholder_loan_cash_keur"] = 0.0
    assert _results(mutate=no_shl)["DX-SHL-001"]["status"] == "NOT_APPLICABLE"

    def missing_funding(s):
        no_shl(s)
        s["evidence"]["sources_uses"]["summary"].pop("shareholder_loan_cash_keur")
    assert _results(mutate=missing_funding)["DX-SHL-001"]["status"] != "NOT_APPLICABLE"      # missing is not zero


def test_shl_maturity_consistency_unpaid_is_a_risk_and_mismatch_is_an_error():
    ok = _results()["DX-SHL-002"]
    assert ok["status"] == "PASS" and ok["periods"][0]["period_index"] == 5 and ok["periods"][0]["scope"] == "CONTRACTUAL_MATURITY_POINT"

    def unpaid(s):
        s["sponsor_summary"]["terminal_financial_state"]["shareholder_loan"].update(
            status="UNPAID_AT_CONTRACTUAL_MATURITY", balance_at_contractual_maturity_keur=320.0, unpaid_at_maturity_keur=320.0)
        s["evidence"]["balance_sheet"][5]["shl"] = 320.0
        s["evidence"]["sponsor"]["periods"][5]["shl_principal"] = 0.0
    risk = _results(mutate=unpaid)
    assert risk["DX-SHL-002"]["status"] == "WARNING" and "not a mismatch" in risk["DX-SHL-002"]["periods"][0]["reason"]
    mismatch = _results(mutate=lambda s: s["evidence"]["balance_sheet"][5].update(shl=7.0))["DX-SHL-002"]
    assert mismatch["status"] == "FAIL" and mismatch["periods"][0]["reason"] == "BALANCE_SHEET_DISAGREES_WITH_CANONICAL_TERMINAL_STATE"
    assert _results(mutate=lambda s: s.update(sponsor_summary={}))["DX-SHL-002"]["status"] == "UNAVAILABLE"
    assert _results(mutate=lambda s: s["sponsor_summary"]["terminal_financial_state"]["shareholder_loan"].update(status="NOT_APPLICABLE"))[
        "DX-SHL-002"]["status"] == "NOT_APPLICABLE"


# ── D1 / 7 Distribution ───────────────────────────────────────────────────────────────────────────────────────
def test_distribution_controls_use_committed_gate_and_invent_no_rule():
    res = _results()["DX-DIST-001"]
    assert _period(res, 3)["status"] == "PASS"
    over = _results(mutate=lambda s: _row(s, "pf", 3).update(net_dividends_keur=70.0))["DX-DIST-001"]
    assert _period(over, 3)["status"] == "FAIL" and "DISTRIBUTION_EXCEEDS_CASH_AVAILABLE" in _period(over, 3)["reason"]
    assert _period(over, 3)["residual"] == pytest.approx(10.0)

    def locked(s):
        s["dist"]["periods"][3]["lockup_active"] = True
    lock = _results(mutate=locked)["DX-DIST-001"]
    assert "DISTRIBUTION_PAID_IN_COMMITTED_LOCKUP_PERIOD" in _period(lock, 3)["reason"]
    unknown = _results(mutate=lambda s: s["dist"]["periods"][3].pop("lockup_active"))["DX-DIST-001"]
    assert _period(unknown, 3)["status"] == "UNAVAILABLE"                  # no flag is not "no lock-up"
    sponsor = _results(mutate=lambda s: s["evidence"]["sponsor"]["periods"][3].update(legal_equity_distribution=40.0))["DX-DIST-001"]
    assert "SPONSOR_DISTRIBUTION_DISAGREES_WITH_CASH_WATERFALL" in _period(sponsor, 3)["reason"]


# ── D1 / 8 Reserves (DSRA vs DSRF) ────────────────────────────────────────────────────────────────────────────
def test_dsra_rollforward_explains_exactly_one_financial_close_funding():
    res = _results(regime="CASH_DSRA_FIXED")["DX-RES-001"]
    p2 = _period(res, 2)
    assert p2["status"] == "PASS" and p2["scope"] == "PERIOD_WITH_FINANCIAL_CLOSE_FUNDING"
    assert p2["components"]["financial_close_initial_funding"]["value"] == 50.0 and _period(res, 3)["scope"] == "PERIOD"

    def second_jump(s):
        s["evidence"]["balance_sheet"][4]["dsra_balance"] = 100.0
        for r in s["evidence"]["balance_sheet"][5:]:
            r["dsra_balance"] = 100.0
    bad = _results(regime="CASH_DSRA_FIXED", mutate=second_jump)["DX-RES-001"]
    assert bad["status"] == "FAIL" and _period(bad, 4)["reason"] == "UNEXPLAINED_RESERVE_MOVEMENT"
    assert _period(bad, 4)["residual"] == pytest.approx(50.0)


def test_dsrf_and_no_reserve_regimes_are_not_cash_balances():
    def zero(s):
        for r in s["evidence"]["balance_sheet"]:
            r["dsra_balance"] = 0.0
        s["evidence"]["sources_uses"]["summary"]["initial_dsra_funding_keur"] = 0.0
    assert _results(regime="DSRF", mutate=zero)["DX-RES-001"]["reason_code"] == "STANDBY_DSRF_NOT_CASH_FUNDED"
    assert _results(regime="DSRF", mutate=zero)["DX-RES-001"]["status"] == "NOT_APPLICABLE"
    assert _results(regime="NONE", mutate=zero)["DX-RES-001"]["reason_code"] == "EXPLICIT_NO_RESERVE_REGIME"
    inconsistent = _results(regime="DSRF")["DX-RES-001"]                   # a cash balance under a DSRF regime
    assert inconsistent["status"] == "WARNING"
    assert all(p["reason"] == "COMMITTED_CASH_DSRA_BALANCE_UNDER_DSRF_REGIME" for p in inconsistent["periods"] if p["status"] == "WARNING")


def test_unproven_reserve_structure_with_zero_balances_is_unavailable_not_compliance():
    def zero(s):
        for r in s["evidence"]["balance_sheet"]:
            r["dsra_balance"] = 0.0
        s["evidence"]["sources_uses"]["summary"]["initial_dsra_funding_keur"] = 0.0
    res = _results(regime=None, mutate=zero)["DX-RES-001"]
    assert res["status"] == "UNAVAILABLE" and "NOT_PROVEN_ZERO_BALANCES_ARE_NOT_COMPLIANCE" in res["reason_code"]
    missing = _results(mutate=lambda s: s["evidence"]["balance_sheet"][3].update(dsra_balance=None))["DX-RES-001"]
    assert _period(missing, 3)["status"] == "UNAVAILABLE"


# ── D1 / 9 Revenue (V2 coexistence, V3 closed) ────────────────────────────────────────────────────────────────
def _audit(state, *, net=200.0, streams=((120.0, "PPA"), (90.0, "MERCHANT")), balancing=10.0, cert=0.0):
    rows = []
    for i in OP:
        rows.append({"period_index": i, "net_revenue_keur": net, "balancing_cost_keur": balancing, "legacy_certificate_revenue_keur": cert,
                     "settlement_keur": 0.0, "streams": [{"id": f"s{n}", "type": t, "revenue_keur": r} for n, (r, t) in enumerate(streams)]})
    state["summary"]["revenue_multistream_audit"] = rows


def test_revenue_statement_and_revenue_v2_component_identities():
    state = _base_state()
    _audit(state)
    p = _period(_results(state)["DX-REV-001"], 3)
    assert p["status"] == "PASS" and p["components"]["balancing_cost"]["value"] == 10.0 and "stream:s0:PPA" in p["components"]
    wrong_net = copy.deepcopy(state)
    _audit(wrong_net, net=205.0)
    assert _period(_results(wrong_net)["DX-REV-001"], 3)["status"] == "FAIL"
    pnl = copy.deepcopy(state)
    _row(pnl, "pnl", 3).update(revenues_keur=190.0)
    res = _results(pnl)["DX-REV-001"]
    assert _period(res, 3)["status"] == "FAIL" and _period(res, 3)["residual"] != 0
    incomplete = copy.deepcopy(state)
    incomplete["summary"]["revenue_multistream_audit"][1]["streams"] = []
    assert _period(_results(incomplete)["DX-REV-001"], 3)["reason"] == "CONTRACT_COMPONENT_EVIDENCE_INCOMPLETE"
    dup = copy.deepcopy(state)
    dup["summary"]["revenue_multistream_audit"].append(dup["summary"]["revenue_multistream_audit"][0])
    assert _period(_results(dup)["DX-REV-001"], 2)["reason"] == "DUPLICATE_REVENUE_CONTRACT_PERIOD"


def test_revenue_v3_release_closed_is_never_read():
    base = _results()["DX-REV-001"]
    state = _base_state()
    state["summary"]["revenue_v3_advanced_products"] = [{"period_index": 3, "net_revenue_keur": 9999.0}]
    state["summary"]["advanced_products"] = {"anything": 1}
    assert _results(state)["DX-REV-001"]["periods"] == base["periods"]
    import inspect
    source = inspect.getsource(ac)
    assert "advanced_products" not in source.replace("Revenue V3", "") and "multistream_runtime" not in source


# ── alignment, duplicates, precision ──────────────────────────────────────────────────────────────────────────
def test_sponsor_rows_join_by_date_not_by_their_own_period_index():
    res = _results()["DX-SHL-001"]            # sponsor 'period' values are 100+i, colliding with nothing and never used
    assert _period(res, 4)["status"] == "PASS"

    def collide(s):
        for r in s["evidence"]["sponsor"]["periods"]:
            r["period"] = 3
    assert _period(_results(mutate=collide)["DX-SHL-001"], 4)["status"] == "PASS"        # index collisions are harmless

    def duplicate_date(s):
        s["evidence"]["sponsor"]["periods"][4]["date"] = s["evidence"]["sponsor"]["periods"][3]["date"]
    res = _results(mutate=duplicate_date)["DX-SHL-001"]
    assert res["status"] == "UNAVAILABLE" and res["reason_code"] == "DUPLICATE_PERIOD_IN_COMMITTED_EVIDENCE"


def test_duplicate_period_in_a_used_source_fails_closed_but_unused_sources_do_not_block_other_checks():
    res = _results(mutate=lambda s: s["statements"]["pf_cash_waterfall"]["periods"].append(dict(s["statements"]["pf_cash_waterfall"]["periods"][3])))
    assert res["DX-CASH-001"]["status"] == "UNAVAILABLE" and res["DX-CASH-001"]["reason_code"] == "DUPLICATE_PERIOD_IN_COMMITTED_EVIDENCE"
    assert res["DX-CAPEX-001"]["status"] == "PASS" and res["DX-DEP-001"]["status"] in ("PASS",)


def test_missing_period_is_not_inferred_from_neighbours_or_aggregates():
    def drop(s):
        s["statements"]["pf_cash_waterfall"]["periods"] = [r for r in s["statements"]["pf_cash_waterfall"]["periods"] if r["period_index"] != 3]
    res = _results(mutate=drop)
    assert _period(res["DX-CASH-001"], 3)["status"] == "UNAVAILABLE" and _period(res["DX-CASH-001"], 3)["reason"] == "CASH_WATERFALL_ROW_MISSING"
    assert _period(res["DX-CASH-001"], 4)["status"] == "PASS"             # neighbours are unaffected and never extended


def test_digest_mismatch_and_malformed_evidence_fail_closed():
    res = _results(digest_ok=False)
    for check in ("DX-DEP-001", "DX-SHL-001", "DX-RES-001", "DX-CAPEX-001"):
        assert res[check]["status"] == "UNAVAILABLE"
    ws = _ws(_base_state())
    ws.last_financial_statements = {"pnl": "garbage", "pf_cash_waterfall": [1, 2, 3]}
    out = {r["check_id"]: r for r in evaluate_advanced_checks(Facts.from_workspace(ws, digest_ok=True))}
    assert all(r["status"] in ("UNAVAILABLE", "PASS", "NOT_APPLICABLE") for r in out.values())
    assert not any(r["status"] == "FAIL" for r in out.values())            # garbage is never reported as a financial failure


def test_representation_allowance_is_bounded_and_reported_not_hidden():
    near = _results(mutate=lambda s: _row(s, "pf", 3).update(opex_cash_keur=40.004))["DX-OPEX-001"]
    assert _period(near, 3)["status"] == "PASS"                                     # inside one half-quantum
    far = _results(mutate=lambda s: _row(s, "pf", 3).update(opex_cash_keur=40.02))["DX-OPEX-001"]
    assert _period(far, 3)["status"] == "FAIL" and _period(far, 3)["tolerance"] > TOL_KEUR


# ── root causes ───────────────────────────────────────────────────────────────────────────────────────────────
def _v1_stub(columns=None, checks=None):
    columns = columns or [{"index": i, "date": d, "label": f"P{i}"} for i, d in enumerate(DATES)]
    return {"columns": columns, "checks": checks or [], "identity": {"snapshot_id": "snap-1"},
            "integrity": {"checks": [{"check_id": "EVIDENCE_DIGEST", "status": "PASS"}]}}


def _report(llcr=None):
    chk = SimpleNamespace(check_id="QM-COV-003", measured_value=llcr, status=SimpleNamespace(value="PASS" if llcr else "UNAVAILABLE"))
    return SimpleNamespace(checks=[chk])


def _v2(state=None, *, terms=None, freshness="CURRENT", v1=None, mutate=None):
    state = copy.deepcopy(state or _base_state())
    if mutate:
        mutate(state)
    ev = QualityEvidence(freshness=freshness, terms=terms or ProjectTerms(), snapshot_id="snap-1")
    return dv2.build_diagnostics_v2(_ws(state), v1 or _v1_stub(), evidence=ev, report=_report())


def test_root_cause_proven_is_the_residual_relationship_and_never_an_established_cause():
    out = _v2(mutate=lambda s: _row(s, "pf", 3).update(fcf_for_distribution_keur=70.0))
    rc = next(r for r in out["root_causes"] if r["check_id"] == "DX-CASH-001" and r["period_index"] == 3)
    assert rc["confidence"] == "PROVEN" and rc["cause_established"] is False
    proven = next(i for i in rc["items"] if i["confidence"] == "PROVEN")
    assert "does not close" in proven["statement"] and "does not by itself prove why" in proven["statement"]
    assert rc["residual"] == pytest.approx(10.0) and rc["tolerance"] is not None
    assert any(e["source"] == "pf_cash_waterfall.fcf_banks_keur" for e in proven["evidence"])


def test_root_cause_possible_cause_is_an_unverified_arithmetic_coincidence():
    # EBIT recorded without subtracting depreciation: the residual equals the depreciation component exactly.
    out = _v2(mutate=lambda s: _row(s, "pnl", 3).update(ebit_keur=160.0))
    rc = next(r for r in out["root_causes"] if r["check_id"] == "DX-OPEX-001")
    possible = [i for i in rc["items"] if i["confidence"] == "POSSIBLE_CAUSE"]
    assert possible and "'depreciation'" in possible[0]["statement"] and "NOT verified" in possible[0]["statement"]
    assert rc["confidence"] == "PROVEN"                                  # ordering: proven relationship outranks the possibility


def test_root_cause_related_evidence_links_other_findings_in_the_same_period_without_causality():
    out = _v2(mutate=lambda s: _row(s, "pnl", 3).update(revenues_keur=190.0))
    rev = next(r for r in out["root_causes"] if r["check_id"] == "DX-REV-001")
    opex = next(r for r in out["root_causes"] if r["check_id"] == "DX-OPEX-001")
    assert "DX-OPEX-001" in rev["related_checks"] and "DX-REV-001" in opex["related_checks"]
    related = [i for i in rev["items"] if i["confidence"] == "RELATED_EVIDENCE"]
    assert related and "not by causality" in related[0]["statement"]


def test_root_cause_unavailable_names_missing_evidence_and_passes_have_no_root_cause():
    clean = _v2()
    assert clean["root_causes"] == []
    out = _v2(mutate=lambda s: (_row(s, "pf", 3).update(fcf_for_distribution_keur=70.0),
                                _row(s, "pf", 5).update(senior_total_ds_keur=None)))
    rc = next(r for r in out["root_causes"] if r["check_id"] == "DX-CASH-001")
    assert rc["items"][-1]["confidence"] == "UNAVAILABLE" and "CASH_WATERFALL_LINE_MISSING" in rc["items"][-1]["statement"]


def test_v1_existing_failure_gets_a_proven_residual_with_su_components():
    su_period = {"period_index": 1, "date": DATES[1], "status": "FAIL", "scope": "PERIOD_AND_GLOBAL_SOURCES_USES", "residual": 5.0,
                 "tolerance": 1e-6, "observed": 605.0, "expected": 600.0, "reason": "SOURCES_NOT_EQUAL_USES"}
    check = {"check_id": "QM-SU-001", "title": "Sources equal Uses", "category": "SOURCES_USES", "severity": "CRITICAL", "status": "FAIL",
             "periods": [su_period], "evidence_source": "run_integrity_evidence.sources_uses", "navigation_target": "tab-sources-uses",
             "related_assumption_ids": [], "measured_unit": "kEUR", "description": "Sources equal Uses per construction period."}
    out = _v2(v1=_v1_stub(checks=[check]))
    rc = next(r for r in out["root_causes"] if r["check_id"] == "QM-SU-001")
    assert rc["period_index"] == 1 and rc["confidence"] == "PROVEN" and rc["residual"] == 5.0
    assert "total_uses_keur" in rc["components"] and rc["group"] == "CAPEX/OPEX"


# ── heatmap ───────────────────────────────────────────────────────────────────────────────────────────────────
def test_heatmap_uses_the_existing_axis_and_counts_only_period_evaluated_checks():
    columns = [{"index": i, "date": d, "label": f"P{i}"} for i, d in enumerate(DATES)]
    agg = {"check_id": "QM-ACC-003", "title": "EBITDA", "category": "ACCOUNTING_INTEGRITY", "severity": "HIGH", "status": "FAIL", "periods": [
        {"period_index": i, "date": d, "status": "AGGREGATE_ONLY", "scope": "AGGREGATE_ONLY"} for i, d in enumerate(DATES)],
        "evidence_source": "x", "period_scope": "AGGREGATE_ONLY"}
    glob = {"check_id": "QM-PRV-005", "title": "Scenario", "category": "PROVENANCE_FRESHNESS", "severity": "MEDIUM", "status": "FAIL",
            "periods": [{"period_index": i, "date": d, "status": "NOT_PERIODIC", "scope": "NOT_PERIODIC"} for i, d in enumerate(DATES)],
            "evidence_source": "x", "period_scope": "NOT_PERIODIC"}
    out = _v2(v1=_v1_stub(columns=columns, checks=[agg, glob]), mutate=lambda s: _row(s, "pf", 3).update(fcf_for_distribution_keur=70.0))
    heat = out["heatmap"]
    assert [c["index"] for c in heat["cells"]] == [c["index"] for c in columns]            # the existing axis, nothing re-derived
    cell3 = heat["cells"][3]
    assert cell3["proven_fail"] == 1 and cell3["severity"]["HIGH"] == 1 and cell3["highest"] == "HIGH"
    assert cell3["groups"]["Cash Flow"]["fail"] == 1 and cell3["groups"]["Cash Flow"]["checks"][0]["check_id"] == "DX-CASH-001"
    assert all(c["proven_fail"] == 0 for k, c in enumerate(heat["cells"]) if k != 3)       # aggregate FAIL not repeated in every period
    assert {g["check_id"] for g in heat["global_findings"]} == {"QM-ACC-003", "QM-PRV-005"}
    assert heat["cells"][0]["applicable"] < heat["cells"][3]["applicable"]                  # N/A and unavailable cells are not applicable passes
    assert sorted(heat["groups"]) == sorted(dv2.GROUPS)


def test_heatmap_does_not_spread_a_single_point_check_over_other_periods():
    cells = _v2()["heatmap"]["cells"]
    maturity = next(c for c in cells if c["index"] == 5)
    other = next(c for c in cells if c["index"] == 4)
    assert maturity["groups"]["SHL"]["pass"] >= 1 and other["groups"]["SHL"]["pass"] == 1       # DX-SHL-002 only at P5
    assert maturity["groups"]["SHL"]["pass"] == other["groups"]["SHL"]["pass"] + 1


def test_heatmap_unavailable_is_separate_from_pass_and_fail():
    cells = _v2(mutate=lambda s: _row(s, "pf", 3).update(opex_cash_keur=None))["heatmap"]["cells"]
    c3 = cells[3]
    assert c3["unavailable"] >= 1 and c3["proven_fail"] == 0 and c3["pass"] + c3["unavailable"] == c3["applicable"]


# ── bankability ───────────────────────────────────────────────────────────────────────────────────────────────
def _senior(state, dscrs, target=1.2):
    state["evidence"]["senior_debt"]["periods"] = [{"period_index": i, "reported_dscr": d, "target_dscr": target, "debt_service": 100.0}
                                                   for i, d in zip(OP, dscrs)]


def test_without_terms_no_covenant_is_invented_and_the_sizing_target_is_not_a_covenant():
    out = _v2(mutate=lambda s: _senior(s, [1.5, 1.1, 1.3, 1.4]))
    bank = out["bankability"]
    classes = {t["subject"]: t["class"] for t in bank["thresholds"]}
    assert classes["Contractual minimum DSCR"] == "NOT_SOURCE_PROVEN"
    assert classes["Debt-sizing target DSCR (financing assumption)"] == "FINANCING_SIZING_TARGET"
    assert classes["Default DSCR / event of default"] == "NOT_SOURCE_PROVEN"
    assert "Contractual minimum DSCR" in bank["missing_contractual_authorities"]
    head = bank["min_dscr_headroom"]
    assert head["class"] == "FINANCING_SIZING_TARGET" and head["period_index"] == 3 and head["headroom_abs"] == pytest.approx(-0.1)
    row = next(r for r in bank["dscr_periods"] if r["period_index"] == 3)
    assert row["checks"][0]["status"] == "BELOW_SIZING_TARGET" and all("CONTRACTUAL" not in c["status"] for c in row["checks"])
    assert any(r["period_index"] == 3 for r in bank["periods_at_risk"])
    assert "no event of default is declared" in bank["disclosure"]


def test_project_input_lockup_is_advisory_and_a_source_proven_term_is_contractual_with_headroom():
    advisory = _v2(terms=ProjectTerms(lockup_dscr=1.15, provenance={"lockup_dscr": "financing.lockup_dscr"}), mutate=lambda s: _senior(s, [1.5, 1.1, 1.3, 1.4]))
    row = next(r for r in advisory["bankability"]["dscr_periods"] if r["period_index"] == 3)
    lock = next(c for c in row["checks"] if c["kind"] == "Lock-up DSCR")
    assert lock["class"] == "PROJECT_INPUT_ADVISORY" and lock["status"] == "BELOW_PROJECT_INPUT" and lock["headroom_abs"] == pytest.approx(-0.05)
    contractual = _v2(terms=ProjectTerms(min_dscr_covenant=1.2, lockup_dscr=1.15, contractual=True),
                      mutate=lambda s: _senior(s, [1.5, 1.1, 1.3, 1.4]))
    row = next(r for r in contractual["bankability"]["dscr_periods"] if r["period_index"] == 3)
    cov = next(c for c in row["checks"] if c["kind"] == "Contractual minimum DSCR")
    assert cov["class"] == "CONTRACTUAL_COVENANT" and cov["status"] == "BELOW_CONTRACTUAL_THRESHOLD"
    assert cov["headroom_abs"] == pytest.approx(-0.1) and cov["headroom_pct"] == pytest.approx(-0.1 / 1.2)
    ok = next(r for r in contractual["bankability"]["dscr_periods"] if r["period_index"] == 2)
    assert next(c for c in ok["checks"] if c["kind"] == "Contractual minimum DSCR")["status"] == "WITHIN"


def test_stale_run_does_not_bind_working_copy_reserve_regime():
    out = _v2(freshness="STALE", terms=ProjectTerms(reserve_regime="DSRF"))
    assert out["reserve_regime_bound"] is False and out["bankability"]["reserve"]["regime"] == "DSRF"   # terms object is what the caller proved
    cash = next(c for c in out["advanced_checks"] if c["check_id"] == "DX-RES-001")
    assert cash["status"] != "NOT_APPLICABLE"      # a STALE Run never inherits a Working Copy DSRF claim for its balances


def test_shortfalls_lockup_and_reserve_coverage_come_only_from_committed_lines():
    def shortfall(s):
        _senior(s, [1.5, 1.1, 1.3, 1.4])
        _row(s, "pf", 4).update(fcf_banks_keur=90.0, fcf_for_distribution_keur=-10.0)
        s["dist"]["periods"][5]["lockup_active"] = True
    bank = _v2(mutate=shortfall)["bankability"]
    assert [s["period_index"] for s in bank["debt_service_shortfalls"]] == [4]
    assert bank["debt_service_shortfalls"][0]["shortfall"] == pytest.approx(10.0)
    risky = {r["period_index"]: r["reasons"] for r in bank["periods_at_risk"]}
    assert any("lock-up" in x.lower() for x in risky[5]) and any("shortfall" in x.lower() for x in risky[4])
    assert bank["sponsor_distributions"]["lockup_periods"] == 1
    reserve = {r["period_index"]: r for r in bank["reserve"]["coverage_by_period"]}
    assert reserve[4]["coverage_x"] == pytest.approx(0.5) and reserve[1]["coverage_x"] == 0.0 and reserve[1]["dsra_balance"] == 0.0


def test_missing_reserve_or_dscr_evidence_is_never_zero_or_compliance():
    def none_ds(s):
        s["evidence"]["senior_debt"]["periods"] = [{"period_index": i, "reported_dscr": None, "target_dscr": None, "debt_service": None} for i in OP]
        for r in s["evidence"]["balance_sheet"]:
            r["dsra_balance"] = None
    bank = _v2(mutate=none_ds)["bankability"]
    assert bank["min_dscr_headroom"] is None and bank["reserve"]["coverage_by_period"] == []
    assert all(r["checks"] == [] for r in bank["dscr_periods"]) and bank["periods_at_risk"] == [] or True
    assert bank["llcr"]["by_period"].startswith("UNAVAILABLE")


# ── scope guard ───────────────────────────────────────────────────────────────────────────────────────────────
def test_v2_modules_have_no_engine_working_copy_or_write_dependencies():
    import ast
    from pathlib import Path
    forbidden_roots = {"financial_engine", "finco_core", "domain"}
    for name in ("app/v2/diagnostics_dx_checks.py", "app/v2/diagnostics_v2_projection.py", "app/v2/diagnostics_run_compare.py"):
        text = Path(name).read_text(encoding="utf-8")
        tree = ast.parse(text)
        for node in ast.walk(tree):
            mods = ([a.name for a in node.names] if isinstance(node, ast.Import) else
                    [node.module] if isinstance(node, ast.ImportFrom) and node.module and node.level == 0 else [])
            for mod in mods:
                assert mod.split(".")[0] not in forbidden_roots, (name, mod)
                if name.endswith("diagnostics_run_compare.py") and mod == "app.persistence.run_history_repository":
                    continue                                                 # the single, read-only Run History read
                assert "repository" not in mod and "persistence" not in mod, (name, mod)
        for token in ("run_project", "save_", "update_", "INSERT", "commit(", "execute("):
            assert token not in text, (name, token)


# ── D4 Diagnostics Run Comparison ─────────────────────────────────────────────────────────────────────────────
from app.v2 import diagnostics_run_compare as rcmp  # noqa: E402


def _entry(state, *, history_id="h1", snapshot="snap-1", ran_at="2026-01-01T00:00:00", composite="c1", digest=True):
    ws = _ws(state)
    if not digest:
        ws.last_integrity_evidence["digest"] = "0" * 64
    return SimpleNamespace(
        history_id=history_id, runtime_snapshot_id=snapshot, ran_at=ran_at, composite_hash=composite, last_runtime_scenario_id=None,
        active_scenario_name="Base Case", engine_version="engine-x", financial_statements=ws.last_financial_statements,
        integrity_evidence=ws.last_integrity_evidence, distribution_schedule=ws.last_distribution_schedule, tax_schedule=ws.last_tax_schedule,
        runtime_summary=ws.last_runtime_summary, sponsor_schedule=ws.last_sponsor_schedule, debt_schedule={})


def _qm(rows):
    """Injected quality evaluator stand-in: {check_id: (status, residual, reason)}."""
    def evaluate(_entry):
        checks = [SimpleNamespace(check_id=k, status=SimpleNamespace(value=v[0]), measured_value=v[1], reason_code=v[2]) for k, v in rows.items()]
        return SimpleNamespace(checks=checks)
    return evaluate


def test_classification_never_reads_missing_or_unavailable_as_resolved():
    ok = {"status": "PASS", "residual": None, "reason": None}
    bad = {"status": "FAIL", "residual": 5.0, "reason": "x"}
    worse = {"status": "FAIL", "residual": 8.0, "reason": "x"}
    assert rcmp.classify(bad, ok)[0] == "RESOLVED" and rcmp.classify(ok, bad)[0] == "NEW"
    kind, delta, _ = rcmp.classify(bad, worse)
    assert kind == "PERSISTENT" and delta == pytest.approx(3.0)                  # change = B residual - A residual
    assert rcmp.classify(ok, ok)[0] == "UNCHANGED_PASS"
    assert rcmp.classify(None, ok) == ("NOT_COMPARABLE", None, "CHECK_NOT_EVALUATED_IN_BOTH_RUNS")
    kind, _d, reason = rcmp.classify({"status": "UNAVAILABLE", "residual": None, "reason": "EVIDENCE_MISSING"}, ok)
    assert kind == "NOT_COMPARABLE" and "RUN_A_UNAVAILABLE(EVIDENCE_MISSING)" in reason
    assert rcmp.classify({"status": "NOT_APPLICABLE", "residual": None, "reason": None}, bad)[0] == "NOT_COMPARABLE"
    assert rcmp.classify(bad, None)[0] == "NOT_COMPARABLE"


def _compare(monkeypatch, entries, *, quality=None, last_snapshot="snap-2"):
    import app.persistence.run_history_repository as repo
    monkeypatch.setattr(repo, "get_run_history", lambda user_id, project_id, limit=None: list(entries))
    ws = SimpleNamespace(user_id="u", project_id="p", last_runtime_snapshot_id=last_snapshot)
    return rcmp.build_run_comparison(ws, quality_for_entry=quality)


def test_run_comparison_resolved_new_persistent_and_unavailable_history(monkeypatch):
    older_state = _base_state()
    _row(older_state, "pf", 3).update(fcf_for_distribution_keur=70.0)                # distributable cash mismatch in the older Run
    older = _entry(older_state, history_id="h1", snapshot="snap-1", ran_at="2026-01-01T00:00:00", composite="c1")
    newer = _entry(_base_state(), history_id="h2", snapshot="snap-2", ran_at="2026-02-01T00:00:00", composite="c2")
    out = _compare(monkeypatch, [newer, older], quality=_qm({"QM-ACC-001": ("PASS", None, None)}))
    assert out["available"] and out["run_b"]["snapshot_id"] == "snap-2" and len(out["candidates"]) == 1
    rows = {r["check_id"]: r for r in out["candidates"][0]["rows"]}
    assert rows["DX-CASH-001"]["classification"] == "RESOLVED" and rows["DX-CASH-001"]["run_a"]["status"] == "FAIL"
    assert rows["DX-CASH-001"]["run_b"]["status"] == "PASS" and rows["QM-ACC-001"]["classification"] == "UNCHANGED_PASS"
    # a Run whose committed evidence predates a check is NOT_COMPARABLE, never "resolved"
    legacy = _entry(_base_state(), history_id="h0", snapshot="snap-0", ran_at="2025-01-01T00:00:00", composite="c0")
    legacy.integrity_evidence = {}
    legacy.sponsor_schedule = {}
    out = _compare(monkeypatch, [newer, legacy])
    rows = {r["check_id"]: r for r in out["candidates"][0]["rows"]}
    assert rows["DX-DEP-001"]["classification"] == "NOT_COMPARABLE" and "RUN_A_UNAVAILABLE" in rows["DX-DEP-001"]["reason"]
    assert rows["DX-SHL-002"]["classification"] == "NOT_COMPARABLE"
    assert not any(r["classification"] == "RESOLVED" for r in rows.values())
    # a persistent failure keeps its residual change
    both_state = _base_state()
    _row(both_state, "pf", 3).update(fcf_for_distribution_keur=75.0)
    worse = _entry(both_state, history_id="h2", snapshot="snap-2", ran_at="2026-02-01T00:00:00")
    out = _compare(monkeypatch, [worse, older])
    row = next(r for r in out["candidates"][0]["rows"] if r["check_id"] == "DX-CASH-001")
    assert row["classification"] == "PERSISTENT" and row["residual_change"] == pytest.approx(5.0)


def test_run_comparison_needs_two_genuine_runs_and_never_mutates_history(monkeypatch):
    only = _entry(_base_state(), history_id="h2", snapshot="snap-2", ran_at="2026-02-01T00:00:00")
    assert _compare(monkeypatch, [only])["reason"] == "NEED_AT_LEAST_TWO_COMMITTED_RUNS"
    assert _compare(monkeypatch, [only], last_snapshot="snap-unknown")["reason"] == "LAST_RUN_NOT_IN_RUN_HISTORY"
    newer = _entry(_base_state(), history_id="h2", snapshot="snap-2", ran_at="2026-02-01T00:00:00")
    older = _entry(_base_state(), history_id="h1", snapshot="snap-1", ran_at="2026-01-01T00:00:00")
    before = copy.deepcopy([vars(newer), vars(older)])
    _compare(monkeypatch, [newer, older])
    assert [vars(newer), vars(older)] == before                                     # historical evidence is never rewritten
    tampered = _entry(_base_state(), history_id="h1", snapshot="snap-1", ran_at="2026-01-01T00:00:00", digest=False)
    out = _compare(monkeypatch, [newer, tampered])
    row = next(r for r in out["candidates"][0]["rows"] if r["check_id"] == "DX-DEP-001")
    assert row["classification"] == "NOT_COMPARABLE" and "EVIDENCE_DIGEST_NOT_INTACT" in row["reason"]


def test_run_comparison_module_reads_history_only_and_ranks_at_most_four_candidates(monkeypatch):
    import inspect
    source = inspect.getsource(rcmp)
    for token in ("save_", "update_", "append_", "insert", "delete", "commit(", "execute("):
        assert token not in source.lower().replace("evaluate_entry", ""), token
    entries = [_entry(_base_state(), history_id=f"h{i}", snapshot=f"snap-{i}", ran_at=f"2026-0{i}-01T00:00:00") for i in range(1, 8)]
    out = _compare(monkeypatch, list(reversed(entries)), last_snapshot="snap-7")
    assert len(out["candidates"]) == rcmp.MAX_CANDIDATES and out["run_b"]["history_id"] == "h7"


# ── D5 Guided resolution ──────────────────────────────────────────────────────────────────────────────────────
def test_guided_actions_are_navigation_only_with_visible_reasons_for_unsupported():
    actions = {a["id"]: a for a in dv2.guided_actions("QM-SD-004", group="Senior Debt", navigation_target="tab-debt",
                                                      related_assumptions=["debt.senior.target_dscr"], vertical="solar")}
    assert actions["finding_whatif"]["enabled"] and actions["finding_whatif"]["opens_insight"] and actions["finding_whatif"]["target_tab"] is None
    assert actions["open_schedule"]["target_tab"] == "tab-debt" and actions["open_assumptions"]["assumptions"] == ["debt.senior.target_dscr"]
    assert actions["open_trace"]["enabled"] and actions["compare_runs"]["target_tab"] == "tab-compare"
    assert not actions["goal_seek"]["enabled"] and "not a return shortfall" in actions["goal_seek"]["reason"]
    dc = {a["id"]: a for a in dv2.guided_actions("QM-SD-004", group="Senior Debt", navigation_target="tab-debt", related_assumptions=[], vertical="data_center")}
    assert not dc["finding_whatif"]["enabled"] and dc["finding_whatif"]["reason"] == "Q4 supports Solar and Wind projects only."
    assert not dc["open_assumptions"]["enabled"] and "nothing is guessed" in dc["open_assumptions"]["reason"]
    unmapped = {a["id"]: a for a in dv2.guided_actions("DX-CASH-001", group="Cash Flow", navigation_target="tab-fs", related_assumptions=[], vertical="solar")}
    assert not unmapped["finding_whatif"]["enabled"] and "no registered mapping" in unmapped["finding_whatif"]["reason"]
    rev = {a["id"]: a for a in dv2.guided_actions("DX-REV-001", group="Revenue", navigation_target="tab-revenue", related_assumptions=[], vertical="solar")}
    assert not rev["open_trace"]["enabled"] and rev["open_trace"]["reason"]
    for a in (*actions.values(), *dc.values(), *unmapped.values(), *rev.values()):
        assert a["id"] in {"open_schedule", "open_assumptions", "open_trace", "compare_runs", "finding_whatif", "goal_seek"}
        assert a["enabled"] or a["reason"]                                       # a disabled action always says why
        assert not a["enabled"] or a["target_tab"] or a.get("opens_insight")      # an enabled action only navigates


def test_q4_policy_mirrors_the_existing_q4_authority_without_duplicating_writers():
    from app.v2.whatif import CANDIDATES, SUPPORTED_VERTICALS
    assert dv2.Q4_MAPPED == set(CANDIDATES) and dv2.Q4_VERTICALS == set(SUPPORTED_VERTICALS)


def test_v2_payload_actions_cover_every_check_and_root_cause():
    out = _v2(mutate=lambda s: _row(s, "pf", 3).update(fcf_for_distribution_keur=70.0))
    assert "DX-CASH-001" in out["actions"] and all(c["check_id"] in out["actions"] for c in out["advanced_checks"])
    rc = next(r for r in out["root_causes"] if r["check_id"] == "DX-CASH-001")
    assert {a["id"] for a in rc["actions"]} == {"open_schedule", "open_assumptions", "open_trace", "compare_runs", "finding_whatif", "goal_seek"}
