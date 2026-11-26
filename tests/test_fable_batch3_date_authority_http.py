"""FINCO 36 Correction D — HTTP Save -> persist -> Run -> sealed History for the dated grid (mid-month COD, final stub, contract dates inside rows).

Independent per-day oracle (imports no calculator under test).  Asserts periods, final stub, per-row revenue and the immutable
History, not merely HTTP 200 / COMMITTED.
"""
from __future__ import annotations

import calendar
import json
import re
import uuid
from datetime import date, timedelta
from decimal import Decimal, getcontext
from types import SimpleNamespace

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from app.auth import COOKIE_NAME, create_session_token
from app.persistence import db
from app.services.reference_seed_service import create_reference_seeded_project
from app.v2.router import router as v2_router
from app.workbook.financing_csrf import issue_token


@pytest.fixture(autouse=True, scope="module")
def _finco47_legacy_ssr_rollback():
    """Module-scoped so module/session fixtures that seed over HTTP see the legacy SSR
    surface this module still exercises; default production flag stays React ON and the
    environment is restored exactly when the module finishes."""
    patch = pytest.MonkeyPatch()
    patch.setenv("FINCO_MODEL_REACT_V1", "0")
    try:
        yield
    finally:
        patch.undo()

getcontext().prec = 50
COD, HORIZON = date(2031, 3, 1), 25          # seeded Solar default: off-boundary COD, 25-year life -> end exclusive 2056-03-01


def _add_years(d, n):
    y = d.year + n
    return date(y, 2, 28) if (d.month == 2 and d.day == 29 and not calendar.isleap(y)) else date(y, d.month, d.day)


def _book(life_end):
    def ppa(sid, start, end, gwh, price):
        return {"id": sid, "type": "ppa", "start_date": start.isoformat(), "end_date": end.isoformat(), "volume_share": None,
                "annual_quantity": {"mode": "ABSOLUTE_ANNUAL", "amount": str(gwh), "unit": "GWh"},
                "price_eur_mwh": price, "indexation_rate": 0.0, "settlement": "SAME_PERIOD", "source_ref": "HTTP_" + sid}
    return json.dumps({"version": 2, "technology": "solar", "indexation_basis": "OPERATING_YEAR", "streams": [
        ppa("ppa_a", date(2031, 9, 10), date(2041, 2, 20), "4", 72.0),
        ppa("ppa_b", COD, date(2036, 5, 15), "3", 68.0),
        {"id": "merchant", "type": "merchant", "start_date": COD.isoformat(), "end_date": life_end.isoformat(), "volume_share": None,
         "price_eur_mwh": 55.0, "indexation_rate": 0.0, "settlement": "SAME_PERIOD", "source_ref": "HTTP_M", "capture_rate": 1.0}]},
        separators=(",", ":"))


def test_http_save_run_history_dated_grid_final_stub_and_row_revenue(tmp_path):
    user = "date-authority-user"
    db.DB_PATH = str(tmp_path / "da.db")
    db.init_db()
    app = FastAPI()
    app.include_router(v2_router, prefix="/v2")
    life_end = _add_years(COD, HORIZON)
    with TestClient(app) as client:
        client.cookies.set(COOKIE_NAME, create_session_token(user_id=user, username="admin"))
        rec = create_reference_seeded_project(user_id=user, requested_name="DA Solar", template_source="generic_solar_reference", capacity_mw=16)
        html = client.get("/v2/workbook", params={"project": rec.project_code}).text
        tokens = {k: re.search(r'name="' + k + r'" value="([^"]*)"', html).group(1) for k in ("content_hash", "workbook_version")}
        from app.workbook.mutation_csrf import mutation_token
        req = SimpleNamespace(cookies=client.cookies, state=SimpleNamespace())
        save = client.post("/v2/workbook/update", headers={"Accept": "application/json"}, data={
            "project": rec.project_code, "field_id": "revenue.multistream.contracts", "value": _book(life_end), **tokens,
            "csrf_token": mutation_token(req, rec.project_code, "workbook-update")})
        assert save.status_code == 200, save.text[:400]
        # reload: the canonical contract is persisted
        from app.persistence.workspace_repository import get_workspace_state
        assert json.loads(get_workspace_state(user, rec.project_id).draft_snapshot["rev_multistream_config_json"])["streams"][0]["id"] == "ppa_a"
        html = client.get("/v2/workbook", params={"project": rec.project_code}).text
        tokens = {k: re.search(r'name="' + k + r'" value="([^"]*)"', html).group(1) for k in ("content_hash", "workbook_version")}
        run = client.post("/v2/workbook/run", headers={"Accept": "application/json"}, data={
            "project": rec.project_code, **tokens, "csrf_token": issue_token(req, rec.project_code, purpose="workbook-run-v1"),
            "run_intent_id": str(uuid.uuid4())}, follow_redirects=False)
        assert run.status_code == 200 and run.json()["outcome"] == "COMMITTED", run.text[:500]

        from app.persistence.run_history_repository import get_run_history
        hist = get_run_history(user, rec.project_id)
        assert len(hist) == 1
        allp = hist[0].financial_statements["pnl"]["periods"]
        rows = [p for p in allp if p["date"] >= "2031-06-30"]            # operating rows (the first ends on the first Jun 30 after COD)
        # final stub: the sealed axis ends exactly at the contractual end (exclusive 2056-03-01 -> last label 2056-02-29), no phantom row
        assert rows[-1]["date"] == (life_end - timedelta(days=1)).isoformat()
        assert rows[-2]["date"] == "2055-12-31"
        assert len(rows) == 2 * HORIZON + 1
        dates = [p["date"] for p in rows]
        assert dates == sorted(set(dates))                                  # strictly increasing, no duplicate boundary / terminal event
        # STRICT per-period revenue: independent per-day Decimal oracle from the persisted typed facts (no production calculator imported).
        from app.input_adapter import build_projectinputs_from_snapshot
        facts = build_projectinputs_from_snapshot(dict(get_workspace_state(user, rec.project_id).draft_snapshot))
        t, rv = facts.technical, facts.revenue
        assert rv.balancing_cost_pv == 0.0 and rv.balancing_cost_eur_per_mwh == 0.0 and rv.balancing_cost_wind_eur_mwh == 0.0 and not rv.co2_enabled
        annual = Decimal(repr(t.capacity_mw)) * Decimal(repr(t.operating_hours_p50)) * Decimal(repr(t.combined_availability))
        contracts = [("ppa_a", date(2031, 9, 10), date(2041, 2, 20), Decimal(4000), Decimal("72.0")),
                     ("ppa_b", COD, date(2036, 5, 15), Decimal(3000), Decimal("68.0"))]
        total_oracle = total_actual = Decimal(0)
        prev_label = None
        for row in rows:
            start_incl = COD if prev_label is None else date.fromisoformat(prev_label) + timedelta(days=1)
            end_excl = date.fromisoformat(row["date"]) + timedelta(days=1)
            keur, day = Decimal(0), start_incl
            while day < end_excl:
                k = 0
                while _add_years(COD, k + 1) <= day:
                    k += 1
                ydays = Decimal(366 if calendar.isleap(day.year) else 365)
                gen = annual * (Decimal(1) - Decimal(repr(t.pv_degradation))) ** k / ydays
                used = Decimal(0)
                for _cid, c0, c1, mwh_year, price in contracts:
                    if c0 <= day < c1:
                        q = mwh_year / ydays
                        keur += q * price / 1000
                        used += q
                assert used <= gen
                keur += (gen - used) * Decimal("55.0") / 1000
                day += timedelta(days=1)
            assert abs(float(keur) - row["revenues_keur"]) <= 0.01, (row["date"], float(keur), row["revenues_keur"])   # per period, <= 0.01 kEUR
            total_oracle += keur
            total_actual += Decimal(repr(row["revenues_keur"]))
            prev_label = row["date"]
        assert abs(float(total_oracle - total_actual)) <= 0.01 * len(rows)        # totals cannot hide opposite per-period errors (checked above)
        stub, prev = rows[-1], rows[-2]
        assert stub["revenues_keur"] > 0 and stub["operating_expenses_keur"] > 0 and stub["depreciation_keur"] > 0
        # stub OPEX/depreciation are positive; exact OPEX/depreciation per-day oracles live in the schedule-level tests
        # no scheduled debt service or reserve resurrected on the stub
        bs_last = hist[0].financial_statements["balance_sheet"]["periods"][-1]
        assert bs_last["senior_balance_keur"] == 0.0 and bs_last["shl_balance_keur"] == 0.0 and bs_last["dsra_balance_keur"] == 0.0
        assert stub["senior_interest_expense_keur"] == 0.0 and stub["shl_interest_expense_keur"] == 0.0
        # the Run did not create a second history entry and the balance sheet balances on the stub
        bs = hist[0].financial_statements["balance_sheet"]["periods"]
        assert max(abs(r.get("balance_check_keur") or 0.0) for r in bs) < 0.01
