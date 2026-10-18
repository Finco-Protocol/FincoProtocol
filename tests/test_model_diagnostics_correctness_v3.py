"""RC-6 / WF-04 Diagnostics Correctness V3: defect reproductions (each failed before the correction) and regression pins.

Read-only committed-Run evidence only. No engine, no Working Copy value, no tolerance or Quality-registry change.
"""
from __future__ import annotations

import math
from types import SimpleNamespace

import pytest

from app.v2 import diagnostics_run_compare as rc
from app.v2.diagnostics_dx_checks import FAIL, NOT_APPLICABLE, PASS, UNAVAILABLE, WARNING
from tests.test_model_diagnostics_v2 import _base_state, _results, _row, _v2


def _status(result, check_id):
    return [(p["period_index"], p["status"], p["reason"]) for p in result[check_id]["periods"]]


# ── DX-CAPEX-001: cumulative identity ───────────────────────────────────────────────────────────────────────────────────
def test_a_missing_construction_period_makes_every_later_cumulative_value_unavailable_never_a_nan_pass():
    result = _results(mutate=lambda s: s["evidence"]["sources_uses"]["construction_periods"][0].pop("uses"))
    check = result["DX-CAPEX-001"]
    assert [p["status"] for p in check["periods"]] == [UNAVAILABLE, UNAVAILABLE]
    assert check["status"] == UNAVAILABLE
    for p in check["periods"]:
        assert p["observed"] is None or not math.isnan(p["observed"])
        assert all(not (isinstance(c["value"], float) and math.isnan(c["value"])) for c in p["components"].values())
    assert check["periods"][1]["reason"] == "CUMULATIVE_BASE_UNAVAILABLE_AFTER_MISSING_PERIOD"


def test_an_explicit_zero_construction_period_is_evaluated_and_is_not_confused_with_missing():
    def zero_first(s):
        s["evidence"]["sources_uses"]["construction_periods"][0]["uses"] = 0.0
        s["evidence"]["sources_uses"]["construction_periods"][1]["uses"] = 1000.0
    check = _results(mutate=zero_first)["DX-CAPEX-001"]
    assert [p["status"] for p in check["periods"]] == [PASS, PASS]


def test_a_duplicate_committed_construction_period_is_an_evidence_defect_not_a_financial_residual():
    def dup(s):
        s["evidence"]["sources_uses"]["construction_periods"].append({"period": 1, "uses": 600.0, "sources": 600.0})
    check = _results(mutate=dup)["DX-CAPEX-001"]
    assert check["status"] == UNAVAILABLE and {p["reason"] for p in check["periods"]} == {"DUPLICATE_PERIOD_IN_COMMITTED_EVIDENCE"}
    assert not [p for p in check["periods"] if p["status"] == FAIL]


def test_an_invalid_digest_never_passes_the_capex_identity():
    check = _results(digest_ok=False)["DX-CAPEX-001"]
    assert {p["status"] for p in check["periods"]} == {UNAVAILABLE}


# ── incompatible dates: rows are joined by index AND equal dates ──────────────────────────────────────────────────────────
def test_a_distribution_schedule_with_incompatible_dates_is_unavailable_not_pass():
    def shift(s):
        for p in s["dist"]["periods"]:
            p["date"] = "1999-01-01"
    check = _results(mutate=shift)["DX-DIST-001"]
    operating = [p for p in check["periods"] if p["status"] != NOT_APPLICABLE]
    assert operating and {p["status"] for p in operating} == {UNAVAILABLE}
    assert {p["reason"] for p in operating} == {"DISTRIBUTION_DATES_DISAGREE"}


def test_a_balance_sheet_row_dated_differently_from_its_statement_period_is_unavailable_for_reserve_depreciation_and_shl():
    def shift(s):
        for row in s["evidence"]["balance_sheet"]:
            row["date"] = "1999-01-01"
    result = _results(mutate=shift, regime="CASH_DSRA_FIXED")
    for check_id in ("DX-RES-001", "DX-DEP-001", "DX-SHL-001"):
        statuses = {p["status"] for p in result[check_id]["periods"] if p["status"] != NOT_APPLICABLE}
        assert PASS not in statuses and FAIL not in statuses, (check_id, statuses)


def test_matching_dates_still_evaluate_normally():
    result = _results()
    assert result["DX-DIST-001"]["status"] == PASS and result["DX-CASH-001"]["status"] == PASS


# ── DX-RES-001: a numerical match is not proof of the Financial Close funding ────────────────────────────────────────────
def test_initial_funding_explains_only_the_first_operating_period():
    result = _results(regime="CASH_DSRA_FIXED")
    assert result["DX-RES-001"]["status"] == PASS                                   # base: the 50 appears at the first operating period

    def late(s):                                                                     # the same 50 appears later: a coincidence
        for row in s["evidence"]["balance_sheet"]:
            row["dsra_balance"] = 0.0 if row["period_index"] < 4 else 50.0
    check = _results(mutate=late, regime="CASH_DSRA_FIXED")["DX-RES-001"]
    by_period = {p["period_index"]: p for p in check["periods"]}
    assert by_period[4]["status"] == FAIL and by_period[4]["reason"] == "UNEXPLAINED_RESERVE_MOVEMENT"
    assert by_period[4]["residual"] == pytest.approx(50.0)


def test_standby_dsrf_is_not_a_cash_balance_and_zero_balances_are_not_compliance():
    dsrf = _results(regime="DSRF")["DX-RES-001"]
    assert dsrf["status"] in (NOT_APPLICABLE, WARNING)
    unproven = _results(regime=None, mutate=lambda s: [r.update(dsra_balance=0.0) for r in s["evidence"]["balance_sheet"]])["DX-RES-001"]
    assert unproven["status"] == UNAVAILABLE


# ── root-cause reliability ───────────────────────────────────────────────────────────────────────────────────────────────
def _shl_unpaid(s):
    t = s["sponsor_summary"]["terminal_financial_state"]["shareholder_loan"]
    t["status"] = "UNPAID_AT_CONTRACTUAL_MATURITY"
    t["balance_at_contractual_maturity_keur"] = 0.0


def test_a_status_warning_inside_tolerance_is_not_described_as_a_reconciliation_that_does_not_close():
    out = _v2(mutate=_shl_unpaid)
    rc_ = next(r for r in out["root_causes"] if r["check_id"] == "DX-SHL-002")
    assert rc_["status"] == "WARNING" and rc_["cause_established"] is False
    proven = [i for i in rc_["items"] if i["confidence"] == "PROVEN"]
    assert proven and "does not close" not in proven[0]["statement"]
    assert "reconciles within tolerance" in proven[0]["statement"] and "not an arithmetic mismatch" in proven[0]["statement"]
    assert not [i for i in rc_["items"] if i["confidence"] == "POSSIBLE_CAUSE"]      # no coincidence hunting inside tolerance


def test_a_genuine_residual_still_states_the_size_and_location_without_asserting_a_cause():
    out = _v2(mutate=lambda s: _row(s, "pf", 3).update(fcf_for_distribution_keur=70.0))
    rc_ = next(r for r in out["root_causes"] if r["check_id"] == "DX-CASH-001" and r["period_index"] == 3)
    proven = next(i for i in rc_["items"] if i["confidence"] == "PROVEN")
    assert "does not close" in proven["statement"] and "does not by itself prove why" in proven["statement"]
    assert rc_["cause_established"] is False


# ── bankability: duplicated period evidence ──────────────────────────────────────────────────────────────────────────────
def test_duplicate_senior_debt_periods_are_excluded_and_listed_not_silently_used():
    def dup(s):
        s["evidence"]["senior_debt"]["periods"] = [
            {"period_index": 2, "reported_dscr": 1.30, "debt_service": 100.0, "target_dscr": 1.2},
            {"period_index": 2, "reported_dscr": 0.90, "debt_service": 100.0, "target_dscr": 1.2},
            {"period_index": 3, "reported_dscr": 1.30, "debt_service": 100.0, "target_dscr": 1.2}]
    bank = _v2(mutate=dup)["bankability"]
    assert bank["duplicate_debt_periods_excluded"] == [2]
    assert [r["period_index"] for r in bank["dscr_periods"]] == [3]


# ── historical comparison stays visibly qualified ────────────────────────────────────────────────────────────────────────
def _entry(engine, scenario="s1", history_id="h"):
    return SimpleNamespace(engine_version=engine, last_runtime_scenario_id=scenario, history_id=history_id)


def test_comparison_qualifications_state_engine_and_scenario_limits():
    assert rc.qualifications(_entry("1.0"), _entry("1.0")) == []
    codes = lambda a, b: [q["code"] for q in rc.qualifications(a, b)]            # noqa: E731
    assert codes(_entry("1.0"), _entry("1.1")) == ["ENGINE_VERSION_DIFFERS"]
    assert codes(_entry(None), _entry("1.1")) == ["ENGINE_VERSION_UNKNOWN"]
    assert codes(_entry("1.0", "a"), _entry("1.0", "b")) == ["DIFFERENT_SCENARIO_CONTEXT"]
    assert codes(_entry("1.0", "a"), _entry("2.0", "b")) == ["ENGINE_VERSION_DIFFERS", "DIFFERENT_SCENARIO_CONTEXT"]


def test_a_check_missing_or_unavailable_on_one_side_is_never_resolved():
    fail = {"status": "FAIL", "residual": 5.0}
    for other in (None, {"status": "UNAVAILABLE", "residual": None, "reason": "X"}, {"status": "NOT_APPLICABLE", "residual": None}):
        assert rc.classify(fail, other)[0] == "NOT_COMPARABLE" and rc.classify(other, fail)[0] == "NOT_COMPARABLE"
    assert rc.classify(fail, {"status": "PASS", "residual": None})[0] == "RESOLVED"


def test_the_comparison_template_renders_the_qualifications():
    from app.v2.router import _templates
    template = _templates.get_template("partials/sheet_diagnostics.html")
    source = template.filename
    text = open(source, encoding="utf-8").read()
    assert "data-md2-compare-qualifications" in text and "data-qualified" in text
