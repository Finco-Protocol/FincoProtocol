"""WF-04 Period Status Matrix: every cell is a status of an already-persisted number, evaluated on the server from THAT Run's own evidence and recorded terms.

The expectations below are derived independently from the Run's sealed evidence (not from the projection under test); gray never reads as green.
"""
import dataclasses
import json
import math

import pytest

from tests.test_model_decision_workspace_v2 import env  # noqa: F401  (fixture used by cenv)
from tests.test_wf04_credit_debt_metrics import COV, EOD, cenv, credit, history, run, update, view_of, weak_wind  # noqa: F401

ROWS = ["LOCKUP", "MIN_DSCR", "CONTRACTUAL_DSCR", "COVERAGE_1X", "CASH_SHORTFALL"]


def matrix(view):
    m = view["period_matrix"]
    return m, {r["id"]: r for r in m["rows"]}


def resealed(entry, mutate):
    from app.run_integrity.evidence import evidence_digest
    evidence = json.loads(json.dumps(entry.integrity_evidence))
    mutate(evidence)
    evidence["digest"] = evidence_digest(evidence)                      # re-sealed: the tamper guard passes, the PARTIAL evidence is what is under test
    return dataclasses.replace(entry, integrity_evidence=evidence)


def test_weak_run_cells_equal_an_independent_reading_of_the_sealed_evidence(cenv):
    record = weak_wind(cenv)
    update(cenv, record, EOD, "1.05")
    update(cenv, record, COV, "1.2")
    run(cenv, record)
    entry = history(record)[0]
    view = view_of(credit(cenv, record))
    m, rows = matrix(view)
    assert m["available"] and [r["id"] for r in m["rows"]] == ROWS and m["periods"] == len(view["periods"]) == 54
    service = {p["period_index"]: p for p in entry.integrity_evidence["senior_debt"]["periods"] if p["debt_service"] > 1e-6}
    cash = {c["period_index"]: c["cash_after_senior_before_reserves"] for c in entry.integrity_evidence["cash"]}
    flags = {p["period"]: p.get("lockup_active") for p in entry.distribution_schedule["periods"]}
    for column, period in enumerate(view["periods"]):
        i = period["period_index"]
        for row_id in ROWS:
            status, text = rows[row_id]["cells"][column]
            assert text.startswith(period["label"])
            if row_id == "LOCKUP":
                want = "NA" if not isinstance(flags.get(i), bool) else "WARN" if flags[i] else "OK"
            elif row_id == "CASH_SHORTFALL":
                want = "NA" if i not in cash else "ALERT" if cash[i] < -1e-6 else "OK"
            elif i not in service:
                want = "NA"
            else:
                d = service[i]["reported_dscr"]
                want = {"MIN_DSCR": "ALERT" if d < 1.05 else "OK", "CONTRACTUAL_DSCR": "ALERT" if d < 1.2 else "OK", "COVERAGE_1X": "ALERT" if d < 1.0 else "OK"}[row_id]
            assert status == want, (period["label"], row_id, status, want)
    statuses = {c[0] for r in m["rows"] for c in r["cells"]}
    assert {"OK", "ALERT"} <= statuses
    mx = {s["id"]: s for s in m["summary"]}
    assert mx["MIN_DSCR"]["alerts"] == sum(1 for p in service.values() if p["reported_dscr"] < 1.05)
    assert mx["COVERAGE_1X"]["alerts"] == sum(1 for p in service.values() if p["reported_dscr"] < 1.0) >= 1
    assert mx["CASH_SHORTFALL"]["alerts"] == sum(1 for v in cash.values() if v < -1e-6)
    assert any("model-evaluated condition" in t for _, t in rows["MIN_DSCR"]["cells"] if _ == "ALERT")       # the legal distinction travels with every breach text


def test_cells_without_service_or_without_a_recorded_term_are_gray_never_green(cenv):
    record = weak_wind(cenv)                                            # no term configured
    run(cenv, record)
    view = view_of(credit(cenv, record))
    m, rows = matrix(view)
    for row_id in ("MIN_DSCR", "CONTRACTUAL_DSCR"):
        assert {c[0] for c in rows[row_id]["cells"]} == {"NA"} and all("configured" in c[1] for c in rows[row_id]["cells"])
    assert "ALERT" in {c[0] for c in rows["COVERAGE_1X"]["cells"]}      # coverage needs no configured term
    idle = [i for i, p in enumerate(view["periods"]) if not p["has_debt_service"]]
    assert idle                                                         # the Wind Run has periods without scheduled service
    for i in idle:
        assert [rows[r]["cells"][i][0] for r in ("MIN_DSCR", "CONTRACTUAL_DSCR", "COVERAGE_1X")] == ["NA"] * 3
        assert "No scheduled Senior debt service" in rows["COVERAGE_1X"]["cells"][i][1]


def test_a_run_committed_before_the_terms_were_recorded_reads_not_recorded(cenv):
    from app.v2.debt_metrics_projection import build_debt_metrics
    record = weak_wind(cenv)
    update(cenv, record, EOD, "1.05")
    run(cenv, record)
    entry = history(record)[0]
    old = dataclasses.replace(entry, last_runtime_identity={k: v for k, v in entry.last_runtime_identity.items() if k != "dscr_contract_terms"})
    m, rows = matrix(build_debt_metrics(old))
    assert {c[0] for c in rows["MIN_DSCR"]["cells"]} == {"NA"} and all("Not recorded" in c[1] for c in rows["MIN_DSCR"]["cells"])
    assert "ALERT" in {c[0] for c in rows["COVERAGE_1X"]["cells"]} and "ALERT" in {c[0] for c in rows["CASH_SHORTFALL"]["cells"]}


def test_partial_evidence_is_not_evaluated_and_a_count_is_stated_only_where_it_is_computable(cenv):
    from app.v2.debt_metrics_projection import build_debt_metrics
    record = weak_wind(cenv)
    update(cenv, record, EOD, "1.05")
    run(cenv, record)
    entry = history(record)[0]

    def drop_cash_and_one_ratio(ev):
        ev["cash"] = []
        row = next(p for p in ev["senior_debt"]["periods"] if p["debt_service"] > 1e-6)
        row["reported_dscr"] = None
    m, rows = matrix(build_debt_metrics(resealed(entry, drop_cash_and_one_ratio)))
    assert {c[0] for c in rows["CASH_SHORTFALL"]["cells"]} == {"NA"}
    summary = {s["id"]: s for s in m["summary"]}
    assert summary["CASH_SHORTFALL"]["alerts"] is None                  # nothing recorded -> "Not recorded", never an inferred zero
    first = next(c for c in rows["MIN_DSCR"]["cells"] if "not persisted" in c[1])
    assert first[0] == "NA"
    assert summary["MIN_DSCR"]["evaluated"] < summary["MIN_DSCR"]["applicable"]


def test_a_forged_or_missing_evidence_withholds_the_whole_matrix(cenv):
    from app.v2.debt_metrics_projection import build_debt_metrics
    record = weak_wind(cenv)
    update(cenv, record, EOD, "1.05")
    run(cenv, record)
    entry = history(record)[0]
    forged = json.loads(json.dumps(entry.integrity_evidence))
    forged["senior_debt"]["periods"][5]["reported_dscr"] = 5.0
    assert build_debt_metrics(dataclasses.replace(entry, integrity_evidence=forged))["period_matrix"] is None
    assert build_debt_metrics(dataclasses.replace(entry, integrity_evidence={}))["period_matrix"] is None


def test_raw_0_9951_is_never_displayed_as_a_safe_1_00x_and_equality_with_the_floor_is_no_breach(cenv):
    from app.v2.debt_metrics_projection import build_debt_metrics
    record = weak_wind(cenv)
    update(cenv, record, EOD, "0.9951")
    run(cenv, record)
    entry = history(record)[0]

    def set_ratio(ev):
        rows = [p for p in ev["senior_debt"]["periods"] if p["debt_service"] > 1e-6]
        rows[0]["reported_dscr"] = 0.9951
        rows[1]["reported_dscr"] = 1.0
    m, rows = matrix(build_debt_metrics(resealed(entry, set_ratio)))
    service = [i for i, c in enumerate(rows["COVERAGE_1X"]["cells"]) if "No scheduled" not in c[1] and "not persisted" not in c[1]]
    first, second = service[0], service[1]
    status, text = rows["COVERAGE_1X"]["cells"][first]
    assert status == "ALERT" and "0.995x" in text and "1.00x" not in text.replace("1.00x:", "").replace("meets 1.00x", "").replace("below 1.00x", "")
    assert rows["MIN_DSCR"]["cells"][first][0] == "OK"                   # 0.9951 is not below the floor 0.9951 (equal is not a trigger)
    assert rows["COVERAGE_1X"]["cells"][second][0] == "OK"               # exactly 1.0 is not below 1.0


def test_no_dsra_row_is_invented_and_the_missing_requirement_is_disclosed(cenv):
    record = weak_wind(cenv)
    run(cenv, record)
    m, rows = matrix(view_of(credit(cenv, record)))
    assert "DSRA" not in " ".join(rows) and [g["id"] for g in m["gaps"]] == ["DSRA_REQUIRED"]
    assert m["gaps"][0]["status"] == "UNAVAILABLE" and "required DSRA amount" in m["gaps"][0]["reason"]


def test_the_matrix_is_a_pure_function_of_the_sealed_run_and_the_cash_tolerance_is_the_integrity_tolerance(cenv):
    from app.run_integrity.contracts import TOL_KEUR
    from app.v2.debt_metrics_projection import CASH_TOL_KEUR
    assert CASH_TOL_KEUR == TOL_KEUR
    record = weak_wind(cenv)
    update(cenv, record, EOD, "1.05")
    run(cenv, record)
    a = json.dumps(view_of(credit(cenv, record))["period_matrix"], sort_keys=True)
    b = json.dumps(view_of(credit(cenv, record))["period_matrix"], sort_keys=True)
    assert a == b and all(math.isfinite(len(a)) for _ in [0])
