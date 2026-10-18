"""Standalone V4 committed-credit evidence, missing-data and provenance regression."""
from copy import deepcopy

import pytest

from app.v2.credit_v4_evidence import build_credit_v4


def run(name, dscr=1.2, debt=20.0, dt=("2030-06-30", "2030-12-31"), credit="PASS", first_start="2029-12-31", starts="derive"):
    keys = {
        "dscr": [dscr, dscr], "debt_service": [debt, debt],
        "base_cfads": [50.0, 45.0], "closing": [90.0, 80.0],
        "bank_cfads": [40.0, 38.0], "dsra_balance": [10.0, 10.0],
        "distribution": [5.0, 8.0],
    }
    return {
        "identity": {"history_id": name, "scenario": "P50", "state": "HISTORICAL", "integrity": credit},
        "timeline": {
            "available": True,
            # Committed period start = the previous committed period end (RC-7B Correction B); ``starts=None`` models a Run that
            # did not persist the previous period.
            "columns": [{"index": i + 1, "date": d,
                         "start": (None if starts is None else (first_start if i == 0 else dt[i - 1]))} for i, d in enumerate(dt)],
            "rows": [{"key": k, "cells": [{"v": v} for v in vals]} for k, vals in keys.items()],
        },
        "capacity": {"min_dscr": {"v": dscr}, "convergence": {"converged": True}},
        "links": {"statements": "/v2/statements"},
    }


def test_converged_solver_with_dscr_below_one_never_approved():
    x = build_credit_v4([run("x", dscr=0.75)])
    assert x["run_risks"][0]["status"] == "REVIEW_REQUIRED"
    assert "OBSERVED_DSCR_BELOW_ONE" in x["run_risks"][0]["reasons"]


def test_clean_observation_is_not_credit_pass():
    x = build_credit_v4([run("x")])
    assert x["run_risks"][0]["status"] == "OBSERVED_ONLY_NO_SHORTFALL_IDENTIFIED"
    assert not x["period_comparison"]["available"]


def test_date_join_does_not_match_by_period_index():
    r = run("a")
    q = run("b", dt=("2030-12-31", "2031-06-30"), first_start="2030-06-30")
    q["timeline"]["rows"][1]["cells"][0]["v"] = 25.0
    x = build_credit_v4([r, q])["period_comparison"]
    assert x["available"] and x["common_periods"] == 1
    assert x["excluded_dates"] == [1, 1] and x["changed"] >= 1


@pytest.mark.parametrize("dates", [
    ("2030-02-30", "2030-12-31"),
    ("2030-12-31", "2030-12-31"),
    ("2031-12-31", "2030-12-31"),
    (None, "2030-12-31"),
])
def test_bad_or_duplicate_dates_fail_closed(dates):
    x = build_credit_v4([run("a"), run("b", dt=dates)])
    assert not x["period_comparison"]["available"]
    assert x["run_risks"][1]["status"] == "REVIEW_REQUIRED"


def test_missing_debt_or_dscr_is_not_zero():
    r = run("x")
    r["timeline"]["rows"][0]["cells"][0]["v"] = None
    x = build_credit_v4([r])
    assert x["run_risks"][0]["missing_count"] == 1
    y = build_credit_v4([run("base"), r])
    assert y["period_comparison"]["unavailable"] > 0


@pytest.mark.parametrize("invalid", [float("nan"), float("inf"), True])
def test_nan_inf_and_boolean_not_numeric(invalid):
    r = run("b")
    r["timeline"]["rows"][0]["cells"][0]["v"] = invalid
    assert build_credit_v4([run("a"), r])["period_comparison"]["unavailable"] > 0


def test_duplicate_ids_rejected():
    with pytest.raises(ValueError, match="CREDIT_V4_RUN_ID_INVALID"):
        build_credit_v4([run("x"), run("x")])


def test_no_contractual_definition_invented():
    x = build_credit_v4([run("a")])
    assert len(x["unavailable"]) >= 4
    assert all("reason" in r for r in x["unavailable"])


def test_projection_pure_and_historical_data_unchanged():
    r = run("a")
    before = deepcopy(r)
    build_credit_v4([r])
    assert r == before


def test_required_period_metric_absence_fails_closed():
    r = run("a")
    r["timeline"]["rows"] = [z for z in r["timeline"]["rows"] if z["key"] != "closing"]
    x = build_credit_v4([r, run("b")])
    assert x["run_risks"][0]["status"] == "REVIEW_REQUIRED"
    assert not x["period_comparison"]["available"]


def test_three_authorised_runs_supported():
    x = build_credit_v4([run("a"), run("b", dscr=0.9), run("c", debt=21)])
    assert x["period_comparison"]["available"]
    assert len(x["run_risks"]) == 3


def _comparison(a, b):
    return build_credit_v4([a, b])["period_comparison"]


def test_equal_period_end_with_a_different_committed_start_is_not_comparable():
    """A quarterly COD stub and a full quarter can end on the same date over different intervals: the end date alone is no proof."""
    full = run("full", dt=("2031-06-30", "2031-09-30"), first_start="2031-03-31")
    stub = run("stub", dt=("2031-06-30", "2031-09-30"), first_start="2031-05-15")
    x = _comparison(full, stub)
    # 2031-06-30: starts differ (stub). 2031-09-30: both start at the committed previous end 2031-06-30 and join.
    assert x["available"] and x["common_periods"] == 1 and x["not_comparable_count"] == 1
    assert x["not_comparable"][0] == {"date": "2031-06-30", "reason": "PERIOD_INTERVAL_DIFFERS", "starts": ["2031-03-31", "2031-05-15"]}
    assert all(r["date"] == "2031-09-30" for r in x["rows"])


def test_all_shared_dates_with_differing_starts_return_not_comparable_without_inventing_a_start():
    a = run("a", dt=("2031-06-30",), first_start="2031-03-31")
    b = run("b", dt=("2031-06-30",), first_start="2031-05-15")
    for key in ("dscr", "debt_service", "base_cfads", "closing", "bank_cfads", "dsra_balance", "distribution"):
        pass
    a["timeline"]["rows"] = [{"key": r["key"], "cells": r["cells"][:1]} for r in a["timeline"]["rows"]]
    b["timeline"]["rows"] = [{"key": r["key"], "cells": r["cells"][:1]} for r in b["timeline"]["rows"]]
    x = _comparison(a, b)
    assert not x["available"] and x["state"] == "NOT_COMPARABLE" and x["rows"] == []
    assert x["not_comparable"][0]["reason"] == "PERIOD_INTERVAL_DIFFERS"


@pytest.mark.parametrize("missing_in", ["a", "b"])
def test_an_uncommitted_period_start_is_not_comparable_never_assumed(missing_in):
    a = run("a", starts=None if missing_in == "a" else "derive")
    b = run("b", starts=None if missing_in == "b" else "derive")
    x = _comparison(a, b)
    assert not x["available"] and x["state"] == "NOT_COMPARABLE" and x["rows"] == []
    assert {n["reason"] for n in x["not_comparable"]} == {"PERIOD_START_NOT_COMMITTED"}


def test_identical_committed_intervals_still_compare_as_before_including_historical_six_month_runs():
    a, b = run("a"), run("b")
    b["timeline"]["rows"][1]["cells"][0]["v"] = 25.0
    x = _comparison(a, b)
    assert x["available"] and x["common_periods"] == 2 and x["not_comparable_count"] == 0 and x["changed"] >= 1


def test_different_operating_frequency_is_state_not_comparable():
    a, b = run("a"), run("b")
    b["operating_frequency"] = "3/3"
    x = _comparison(a, b)
    assert not x["available"] and x["state"] == "NOT_COMPARABLE"
