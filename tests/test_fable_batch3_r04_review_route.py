"""FINCO 36 Correction G — the read-only R04 cap review route behind the React editor (POST /v2/model-react/revenue/review).

The route must be strictly non-mutating, owner/project bound, CSRF bound and revision-aware; its table must equal an independent exact
(Fraction-free Decimal) per-day calculation from the persisted typed technical facts, with partial-year proration, exact boundary and
P90 independence.  Reuses the WF-React-2 real-route environment.
"""
from __future__ import annotations

import calendar
import json
from datetime import date, timedelta
from decimal import Decimal, getcontext

import pytest

from tests.test_model_react_wf2_projections_v1 import OWNER, STRANGER, env  # noqa: F401

getcontext().prec = 50
COD = date(2031, 3, 1)


def _ppa(sid, start, end, amount, unit="MWh", price=70.0):
    return {"id": sid, "type": "ppa", "start_date": start, "end_date": end, "volume_share": None,
            "annual_quantity": {"mode": "ABSOLUTE_ANNUAL", "amount": str(amount), "unit": unit}, "price_eur_mwh": price,
            "indexation_rate": 0.0, "settlement": "SAME_PERIOD", "source_ref": "REVIEW_" + sid}


MERCHANT = {"id": "merchant", "type": "merchant", "start_date": "2031-03-01", "end_date": "2056-03-01", "volume_share": None,
            "price_eur_mwh": 55.0, "indexation_rate": 0.0, "settlement": "SAME_PERIOD", "source_ref": "REVIEW_M", "capture_rate": 1.0}


def book(streams):
    return json.dumps({"version": 2, "technology": "solar", "indexation_basis": "OPERATING_YEAR", "streams": streams}, separators=(",", ":"))


def tokens(env, record):
    payload = env.client.get("/v2/model-react/revenue", params={"project": record.project_code}).json()
    return payload["save"]


def review(env, record, raw, *, client=None, csrf=None, content_hash=None):
    t = tokens(env, record)
    return (client or env.client).post("/v2/model-react/revenue/review", data={
        "project": record.project_code, "csrf_token": csrf if csrf is not None else t["csrf_token"],
        "content_hash": content_hash if content_hash is not None else t["content_hash"], "contracts": raw})


def _facts(record):
    from app.input_adapter import build_projectinputs_from_snapshot
    from app.persistence.workspace_repository import get_workspace_state
    return build_projectinputs_from_snapshot(dict(get_workspace_state(OWNER, record.project_id).draft_snapshot)).technical


def _oracle_year(t, year, contracts, hours):
    """Per-day independent oracle for one calendar year: (available MWh, committed MWh) inside [COD, COD+25y)."""
    life_end = date(COD.year + 25, COD.month, COD.day)
    annual = Decimal(repr(t.capacity_mw)) * Decimal(repr(hours)) * Decimal(repr(t.combined_availability))
    avail = committed = Decimal(0)
    day = max(date(year, 1, 1), COD)
    stop = min(date(year + 1, 1, 1), life_end)
    while day < stop:
        k = 0
        while date(COD.year + k + 1, COD.month, COD.day) <= day:
            k += 1
        yd = Decimal(366 if calendar.isleap(day.year) else 365)
        avail += annual * (Decimal(1) - Decimal(repr(t.pv_degradation))) ** k / yd
        for start, end, qty in contracts:
            if start <= day < end:
                committed += qty / yd
        day += timedelta(days=1)
    return avail, committed


def test_review_table_equals_independent_per_day_oracle_including_partial_years_and_units(env):
    record = env.create("solar")
    env.client.get("/v2/workbook", params={"project": record.project_code})
    t = _facts(record)
    two = book([_ppa("a", "2031-03-01", "2036-09-15", 5, "GWh"), _ppa("b", "2032-07-01", "2040-02-29", "3000.5", "MWh"), MERCHANT])
    body = review(env, record, two).json()
    assert body["ok"] is True and body["applicable"] is True and body["stale"] is False
    rows = {r["year"]: r for r in body["review"]["years"]}
    contracts = [(date(2031, 3, 1), date(2036, 9, 15), Decimal(5000)), (date(2032, 7, 1), date(2040, 2, 29), Decimal("3000.5"))]
    for year in (2031, 2032, 2036, 2040, 2041):                                   # partial COD year, mid-year start, expiry years, no contract
        avail, committed = _oracle_year(t, year, contracts, t.operating_hours_p50)
        assert abs(rows[year]["available_p50_mwh"] - float(avail)) <= 0.001, year
        assert abs(rows[year]["committed_mwh"] - float(committed)) <= 0.001, year
        assert abs(rows[year]["remaining_p50_mwh"] - float(avail - committed)) <= 0.001, year
    assert body["review"]["cap_envelope_basis"] == "P50" and body["review"]["blocked"] is False


def test_exact_boundary_is_not_blocked_and_one_milli_mwh_over_is(env):
    record = env.create("solar")
    env.client.get("/v2/workbook", params={"project": record.project_code})
    t = _facts(record)
    cap = (Decimal(repr(t.capacity_mw)) * Decimal(repr(t.operating_hours_p50)) * Decimal(repr(t.combined_availability))).quantize(Decimal("0.001"), rounding="ROUND_FLOOR")
    ok = review(env, record, book([_ppa("a", "2031-03-01", "2032-03-01", cap), MERCHANT])).json()["review"]
    assert ok["blocked"] is False and not ok["exceeded_slices"]
    over = review(env, record, book([_ppa("a", "2031-03-01", "2032-03-01", cap + Decimal("0.001")), MERCHANT])).json()["review"]
    assert over["blocked"] is True and over["exceeded_slices"][0]["excess_mwh"] > 0
    gwh = review(env, record, book([_ppa("a", "2031-03-01", "2032-03-01", format((cap / 1000).quantize(Decimal("0.000001"), rounding="ROUND_FLOOR"), "f"), "GWh"), MERCHANT])).json()["review"]
    assert gwh["blocked"] is False


def test_p90_does_not_change_the_p50_cap_and_reports_the_fixed_shortfall_against_independent_oracle(env):
    record = env.create("solar")
    env.client.get("/v2/workbook", params={"project": record.project_code})
    t = _facts(record)
    p50_annual = Decimal(repr(t.capacity_mw)) * Decimal(repr(t.operating_hours_p50)) * Decimal(repr(t.combined_availability))
    cap = p50_annual.quantize(Decimal("0.001"), rounding="ROUND_FLOOR")
    review_ok = review(env, record, book([_ppa("a", "2031-03-01", "2032-03-01", cap), MERCHANT])).json()["review"]
    assert review_ok["blocked"] is False                                           # accepted against P50 although P90 generates less
    assert review_ok["shortfall_slices"] == []                                      # P50 is the selected case: deliverable
    assert review_ok["p90_shortfall_slices"] and review_ok["p90_hours"] == t.operating_hours_p90_10y
    first = review_ok["p90_shortfall_slices"][0]
    # independent oracle for the first slice (COD year 2031: 306 of 365 days): P90 available vs the full fixed commitment prorated
    p90_annual = Decimal(repr(t.capacity_mw)) * Decimal(repr(t.operating_hours_p90_10y)) * Decimal(repr(t.combined_availability))
    days = (date.fromisoformat(first["period_end_exclusive"]) - date.fromisoformat(first["period_start"])).days
    exp_avail = p90_annual * days / 365
    exp_fixed = cap * days / 365
    assert abs(first["p90_available_mwh"] - float(exp_avail)) <= 0.001 and abs(first["fixed_commitment_mwh"] - float(exp_fixed)) <= 0.001
    assert abs(first["shortfall_mwh"] - float(exp_fixed - exp_avail)) <= 0.001
    # the P50 table itself is unchanged by anything about P90
    assert review_ok["years"][0]["available_p50_mwh"] > 0 and review_ok["shortfall_error_code"] is None


def test_review_is_read_only_owner_bound_csrf_bound_and_reports_stale(env):
    record = env.create("solar")
    env.client.get("/v2/workbook", params={"project": record.project_code})
    from app.persistence.run_history_repository import get_run_history
    from app.persistence.workspace_repository import get_workspace_state
    before = (dict(get_workspace_state(OWNER, record.project_id).draft_snapshot), len(get_run_history(OWNER, record.project_id)))
    raw = book([_ppa("a", "2031-03-01", "2032-03-01", 1000), MERCHANT])
    assert review(env, record, raw).status_code == 200
    assert review(env, record, raw, csrf="forged").status_code == 403                  # CSRF
    other = review(env, record, raw, client=env.stranger)                              # other tenant: no facts
    assert other.status_code in (403, 404) and "available_p50_mwh" not in other.text
    stale = review(env, record, raw, content_hash="0" * 64).json()
    assert stale["ok"] is True and stale["stale"] is True
    bad = review(env, record, "{not json")
    assert bad.status_code == 422 and bad.json()["code"] == "REVENUE_REVIEW_BOOK_INVALID"
    assert review(env, record, book([_ppa("a", "2031-03-01", "2032-03-01", -1), MERCHANT])).status_code == 422
    share_only = review(env, record, book([{**_ppa("s", "2031-03-01", "2032-03-01", 1), "annual_quantity": None, "volume_share": 0.5}, MERCHANT])).json()
    assert share_only.get("applicable") is False or share_only.get("ok") is False
    after = (dict(get_workspace_state(OWNER, record.project_id).draft_snapshot), len(get_run_history(OWNER, record.project_id)))
    assert after == before                                                              # never a write, never a History row
