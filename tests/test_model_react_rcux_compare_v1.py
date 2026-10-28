"""RC-UX B2 — Run / scenario compare adapter over REAL committed canonical Runs.

No ideal fixtures: every assertion is against Run History rows produced by the canonical Run.  The adapter is read-only: a full logical
DB dump is identical before and after, and model execution is monkeypatched to fail.
"""
from __future__ import annotations

import json
import sqlite3
from dataclasses import asdict

import pytest

from tests.model_mutation_csrf import post_valid_mutation
from tests.test_model_credit_decision_v3_real_runs import history, last
from tests.test_model_decision_workspace_v2 import env  # noqa: F401  (fixture)
from tests.test_model_financing_f2 import run

USER = "decision-user"
PATH = "/v2/model-react/compare"


@pytest.fixture
def compare(env, monkeypatch):  # noqa: F811
    from app.v2.react_compare import router
    monkeypatch.setenv("FINCO_MODEL_REACT_V1", "1")
    env.client.app.include_router(router, prefix="/v2")
    return env


def get(env, record, *entries, **extra):
    params = [("project", record.project_code)] + [("run", e.history_id) for e in entries] + list(extra.items())
    return env.client.get(PATH, params=params)


def db_snapshot():
    from app.persistence import db
    with sqlite3.connect(db.DB_PATH) as conn:
        return "\n".join(conn.iterdump())


def two_runs(env, kind="solar", tariff="40"):
    """Base Run and a revenue-downside scenario Run, both committed."""
    from app.persistence.scenarios_repository import list_scenarios
    record = env.create(kind)
    run(env, record)
    base = last(record)
    assert post_valid_mutation(env.client, "/v2/workbook/scenarios/create", headers={"HX-Request": "true"},
                               data={"project": record.project_code, "scenario_name": "Revenue downside"}).status_code == 200
    scenario = next(s for s in list_scenarios(user_id=USER, project_id=record.project_id) if s.scenario_name == "Revenue downside")
    assert post_valid_mutation(env.client, "/v2/workbook/scenarios/update-overrides", headers={"HX-Request": "true"},
                               data={"project": record.project_code, "scenario_id": scenario.scenario_id,
                                     "tariff_eur_mwh": tariff}).status_code == 200
    run(env, record)
    down = last(record)
    assert down.last_runtime_scenario_id == scenario.scenario_id
    return record, base, down, scenario


def test_router_is_mounted_before_the_project_catch_all():
    from app.v2.router import router
    paths = [getattr(route, "path", "") for route in router.routes]
    assert paths.count("/model-react/compare") == 1
    assert paths.index("/model-react/compare") < paths.index("/model-react/{project_code}")


def test_compare_rows_equal_persisted_run_evidence_with_exact_deltas(compare):
    record, base, down, scenario = two_runs(compare)
    response = get(compare, record, base, down)
    assert response.status_code == 200, response.text[:800]
    assert response.headers["cache-control"] == "private, no-store"
    data = response.json()
    assert data["schema"] == "rc-ux-compare-v1" and data["reference_history_id"] == base.history_id
    assert [c["history_id"] for c in data["columns"]] == [base.history_id, down.history_id]
    assert [c["scenario_id"] for c in data["columns"]] == [None, scenario.scenario_id]
    for column, entry in zip(data["columns"], (base, down)):
        assert column["snapshot_id"] == entry.runtime_snapshot_id and column["composite_hash"] == entry.composite_hash
        assert column["engine_version"] == entry.engine_version
    rows = {r["key"]: r for r in data["rows"]}
    revenue = rows["total_revenue_keur"]
    b, d = base.runtime_summary["total_revenue_keur"], down.runtime_summary["total_revenue_keur"]
    assert revenue["raw_values"] == [b, d] and b != d
    assert revenue["pct_raw"][0] is None and revenue["pct_raw"][1] == pytest.approx((d - b) / abs(b) * 100)
    assert revenue["pct_deltas"][1] == f"{(d - b) / abs(b) * 100:+.1f}%"
    assert revenue["abs_deltas"][1] == f"{d - b:+,.0f} kEUR"
    assert rows["project_irr"]["raw_values"] == [base.runtime_summary["project_irr"], down.runtime_summary["project_irr"]]
    assert rows["sponsor_irr"]["raw_values"][0] == base.sponsor_schedule["summary"].get("total_sponsor_xirr")
    assert rows["senior_debt_keur"]["raw_values"][0] == base.runtime_summary["senior_debt_keur"]


def test_kpi_rows_equal_the_legacy_compare_machinery_for_the_same_runs(compare):
    """Audit A GAP-R13 acceptance: the React matrix equals the compare values the Legacy Run History page builds."""
    from app.v2.run_history_projection import _enriched_kpis
    from app.v2.scenario_kpi_projection import build_compare_rows, build_scenario_projection
    record, base, down, _ = two_runs(compare)
    rows = {r["key"]: r for r in get(compare, record, base, down).json()["rows"]}
    sponsor = {"sponsor_irr": "total_sponsor_xirr", "sponsor_moic": "total_sponsor_moic", "pure_equity_moic": "pure_equity_moic"}

    def projection(entry):
        kpis = _enriched_kpis(entry)
        for key, field in sponsor.items():
            kpis[key] = (entry.sponsor_schedule or {}).get("summary", {}).get(field)
        return build_scenario_projection("", kpis, entry.ran_at, False)

    for expected in build_compare_rows([projection(base), projection(down)]):
        assert rows[expected.key]["values"] == expected.values, expected.key
        assert rows[expected.key]["raw_values"] == expected.raw_values, expected.key
        assert rows[expected.key]["abs_deltas"] == expected.deltas, expected.key


def test_unavailable_metrics_are_identified_never_zero(compare):
    record, base, down, _ = two_runs(compare)
    rows = {r["key"]: r for r in get(compare, record, base, down).json()["rows"]}
    plcr = rows["plcr"]
    assert plcr["availability"] == ["not_available", "not_available"] and plcr["raw_values"] == [None, None]
    assert all(v not in ("0", "0.00x", "0%") for v in plcr["values"] + plcr["pct_deltas"] + plcr["abs_deltas"])
    for row in rows.values():
        for raw, availability, display in zip(row["raw_values"], row["availability"], row["values"]):
            if raw is None and row["fmt"] != "date":
                assert availability == "not_available" and display == "—", row["key"]


def test_supplementary_evidence_is_read_from_the_persisted_paths(compare):
    record, base, down, _ = two_runs(compare)
    rows = {r["key"]: r for r in get(compare, record, base, down).json()["rows"]}
    sponsor, dist = base.sponsor_schedule["summary"], base.distribution_schedule["summary"]
    assert rows["shl_cash_contributed_keur"]["raw_values"][0] == sponsor["total_shl_cash_contributed_keur"]
    assert rows["legal_equity_distributions_keur"]["raw_values"][0] == sponsor["total_legal_equity_distributions_keur"]
    assert rows["total_distribution_keur"]["raw_values"][0] == dist["total_distribution_keur"]
    repayment = base.runtime_summary["financing_evidence"]["senior_debt_evidence"]["repayment"]
    assert rows["senior_actual_payoff"]["values"][0] == repayment["actual_payoff_date"]
    assert rows["senior_contractual_maturity"]["values"][0] == repayment["contractual_maturity_date"]
    assert rows["senior_actual_payoff"]["source"].endswith("repayment.actual_payoff_date")


def test_cashflow_series_are_period_aligned_pass_through_with_plain_sum_totals(compare):
    record, base, down, _ = two_runs(compare)
    cash = get(compare, record, base, down).json()["cashflow"]
    series = {s["key"]: s for s in cash["series"]}
    periods = base.financial_statements["pf_cash_waterfall"]["periods"]
    revenue = series["revenue_cash_keur"]
    assert revenue["periods"] == [p["period_index"] for p in periods]
    assert revenue["runs"][0]["values"] == [p["revenue_cash_keur"] for p in periods]
    assert revenue["runs"][0]["total"] == pytest.approx(sum(p["revenue_cash_keur"] for p in periods))
    other = down.financial_statements["pf_cash_waterfall"]["periods"]
    assert revenue["runs"][1]["values"] == [p["revenue_cash_keur"] for p in other]
    assert revenue["runs"][0]["total"] != revenue["runs"][1]["total"]
    dscr = series["dscr"]
    assert dscr["unit"] == "x" and all(r["total"] is None for r in dscr["runs"])     # a ratio is never summed
    assert [v for v in dscr["runs"][0]["values"]] == [p["dscr"] for p in base.debt_schedule["periods"]]
    assert "never zero" in cash["note"]


def test_assumption_differences_report_only_what_the_run_identity_persists(compare):
    record, base, down, scenario = two_runs(compare)
    a = get(compare, record, base, down).json()["assumptions"]
    assert a["composite_hash_equal"] is False and a["composite_hashes"] == [base.composite_hash, down.composite_hash]
    overrides = down.last_runtime_identity.get("scenario_overrides") or {}
    assert overrides and {o["key"] for o in a["scenario_overrides"]} == set(overrides)
    for row in a["scenario_overrides"]:
        assert row["values"] == [None, overrides[row["key"]]]
    assert "cannot be itemised" in a["limitation"]
    same = get(compare, record, down, down)
    assert same.status_code == 422                                    # two DISTINCT Runs are required


def test_identical_composite_hash_is_reported_equal(compare):
    record = compare.create("solar")
    run(compare, record)
    first = last(record)
    run(compare, record)
    second = last(record)
    assert first.history_id != second.history_id
    data = get(compare, record, first, second).json()
    assert data["assumptions"]["composite_hash_equal"] == (first.composite_hash == second.composite_hash)
    assert data["assumptions"]["scenario_overrides"] == [] and data["assumptions"]["capex_lines"] == []


def test_selection_limits_and_unknown_runs(compare):
    record, base, down, _ = two_runs(compare)
    assert get(compare, record, base).status_code == 422                       # one Run is not a comparison
    assert compare.client.get(PATH, params=[("project", record.project_code)]).status_code == 422
    params = [("project", record.project_code)] + [("run", str(i)) for i in range(4)]
    assert compare.client.get(PATH, params=params).status_code == 422
    assert compare.client.get(PATH, params=[("project", record.project_code), ("run", base.history_id), ("run", "unknown")]).status_code == 404
    assert compare.client.get(PATH, params={"project": record.project_code, "run": "x" * 200}).status_code == 422
    assert get(compare, record, base, down, extra="1").status_code == 400


def test_get_never_executes_the_model_or_writes(compare, monkeypatch):
    from app.persistence.workspace_repository import get_workspace_state
    record, base, down, _ = two_runs(compare)
    get(compare, record, base, down)                                            # warm schema / caches
    before, ws = db_snapshot(), get_workspace_state(USER, record.project_id)
    frozen = json.dumps([asdict(e) for e in history(record)], sort_keys=True, default=str)

    def forbidden(*args, **kwargs):
        raise AssertionError("compare attempted model execution")

    monkeypatch.setattr("app.api.project_runner.run_project", forbidden)
    monkeypatch.setattr("app.services.production_financial_authority.run_clean_production", forbidden)
    for _ in range(2):
        assert get(compare, record, base, down).status_code == 200
    assert get_workspace_state(USER, record.project_id) == ws
    assert json.dumps([asdict(e) for e in history(record)], sort_keys=True, default=str) == frozen
    assert db_snapshot() == before
    assert compare.client.post(PATH, data={"project": record.project_code}).status_code == 405


def test_security_foreign_user_unauthenticated_protected_and_flag(compare, monkeypatch):
    from app.auth import COOKIE_NAME, create_session_token
    record, base, down, _ = two_runs(compare)
    for who in (None, "foreign-user"):
        with compare.client.__class__(compare.client.app) as client:
            if who:
                client.cookies.set(COOKIE_NAME, create_session_token(user_id=who, username="other"))
            response = client.get(PATH, params=[("project", record.project_code), ("run", base.history_id), ("run", down.history_id)],
                                  follow_redirects=False)
            assert response.status_code == (404 if who else 401)
            assert base.runtime_snapshot_id not in response.text
    with monkeypatch.context() as scoped:
        scoped.setattr("app.services.project_library_service.is_protected_reference", lambda record: True)
        assert get(compare, record, base, down).status_code == 409
    monkeypatch.delenv("FINCO_MODEL_REACT_V1")
    assert get(compare, record, base, down).status_code == 404


def test_historical_run_stays_historical_and_stale_working_copy_is_labelled(compare):
    record, base, down, _ = two_runs(compare)
    states = {c["history_id"]: c["state"] for c in get(compare, record, base, down).json()["columns"]}
    assert states[base.history_id] == "HISTORICAL"                   # an older Run is never CURRENT
    assert states[down.history_id] in ("LAST RUN · CURRENT", "LAST RUN · STALE")


@pytest.mark.parametrize("value,reference,expected", [
    (110.0, 100.0, (10.0, "+10.0%")), (90.0, 100.0, (-10.0, "-10.0%")), (-50.0, -100.0, (50.0, "+50.0%")),
    (5.0, 0.0, (None, "—")), (None, 100.0, (None, "—")), (100.0, None, (None, "—"))])
def test_relative_change_is_undefined_not_zero_for_missing_or_zero_reference(value, reference, expected):
    from app.v2.react_compare import relative_change
    assert relative_change(value, reference) == expected
