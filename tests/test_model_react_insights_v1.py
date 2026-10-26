"""WF-REACT-3 independent acceptance over actual isolated, committed Solar/Wind Runs.

No ideal KPI fixtures, financial recomputation, tolerance changes or golden edits.
Canonical existing Run/Save fixtures create private SQLite histories for each test.
"""
from __future__ import annotations

from tests.model_mutation_csrf import post_valid_mutation

from dataclasses import asdict
import json
import sqlite3

import pytest

from tests.test_model_decision_workspace_v2 import env  # noqa: F401
from tests.test_model_credit_decision_v3_real_runs import history, last, set_field
from tests.test_model_financing_f2 import config, run, save

USER = "decision-user"
DETAIL = "/v2/model-react/insights"
INDEX = DETAIL + "/history"


def test_served_react_router_composition_preserves_literal_route_order():
    from app.v2.router import router
    paths = [getattr(route, "path", "") for route in router.routes]
    for path in (DETAIL.removeprefix("/v2"), INDEX.removeprefix("/v2")):
        assert paths.count(path) == 1
        assert paths.index(path) < paths.index("/model-react/{project_code}")


@pytest.fixture
def insights(env, monkeypatch):
    from app.v2.react_insights_router import router
    from app.v2.credit_decision_router import router as credit_router
    monkeypatch.setenv("FINCO_MODEL_REACT_V1", "1")
    env.client.app.include_router(router, prefix="/v2")
    env.client.app.include_router(credit_router, prefix="/v2")
    return env


def get(insights, record, *entries, **extra):
    params = [("project", record.project_code)] + [("run", e.history_id) for e in entries]
    params += list(extra.items())
    response = insights.client.get(DETAIL, params=params)
    assert response.status_code == 200, response.text[:1500]
    assert response.headers["cache-control"] == "private, no-store"
    return response.json()


def metric_map(run_view):
    return {m["key"]: m for m in run_view["metrics"]}


def frozen_history(record):
    return json.dumps([asdict(e) for e in history(record)], sort_keys=True, default=str)


def db_snapshot():
    """Exact logical snapshot of every persisted table, including session/workbook state."""
    from app.persistence import db
    with sqlite3.connect(db.DB_PATH) as conn:
        return "\n".join(conn.iterdump())


@pytest.mark.parametrize("kind", ["solar", "wind"])
def test_actual_committed_kpis_units_source_and_periods_are_exact(insights, kind):
    from app.v2.run_history_projection import _enriched_kpis
    from app.v2.scenario_kpi_projection import build_scenario_projection
    record = insights.create(kind)
    run(insights, record)
    entry = last(record)
    data = get(insights, record, entry)
    actual = data["runs"][0]
    metrics = metric_map(actual)
    ident = actual["identity"]
    assert ident["history_id"] == entry.history_id
    assert ident["snapshot_id"] == entry.runtime_snapshot_id
    assert ident["composite_hash"] == entry.composite_hash
    assert ident["scenario_id"] == entry.last_runtime_scenario_id
    assert ident["engine_version"] == entry.engine_version
    assert ident["workbook_version"] == entry.workbook_version
    expected = build_scenario_projection("Base Case", _enriched_kpis(entry), entry.ran_at, False)
    for key, metric in expected.metrics.items():
        out = metrics[key]
        assert out["raw_value"] == metric.raw_value, key
        assert out["display_value"] == metric.display_value, key
        assert out["unit"] == metric.unit, key
        from app.v2.output_metric_projection import SPONSOR_SUMMARY_SOURCE_KEYS
        source = metric.source
        if key in ("min_llcr", "target_dscr") and entry.runtime_summary.get(key) is not None:
            source = "runtime_summary"
        assert out["source"] == source + "." + SPONSOR_SUMMARY_SOURCE_KEYS.get(key, key), key
        assert out["history_id"] == entry.history_id
        assert out["snapshot_id"] == entry.runtime_snapshot_id
        assert out["scenario_id"] == entry.last_runtime_scenario_id
        assert out["period"] == "AGGREGATE"
    for key in ("min_dscr", "avg_dscr", "min_llcr", "target_dscr"):
        assert metrics[key]["unit"] == "x"
    assert metrics["min_dscr"]["raw_value"] == entry.runtime_summary["min_dscr"]
    assert metrics["min_llcr"]["raw_value"] == entry.debt_schedule["summary"].get("min_llcr")
    credit = actual["credit"]
    persisted = entry.integrity_evidence["senior_debt"]["periods"]
    assert [c["index"] for c in credit["timeline"]["columns"]] == [p["period_index"] for p in persisted]
    by_key = {r["key"]: r for r in credit["timeline"]["rows"]}
    for key, source in (("dscr", "reported_dscr"), ("debt_service", "debt_service"),
                        ("base_cfads", "base_cfads"), ("interest", "interest"), ("principal", "principal")):
        assert [c["v"] for c in by_key[key]["cells"]] == [p.get(source) for p in persisted]
    # The established Credit Decision route is an independent projection oracle.
    from tests.test_model_credit_decision_v3_real_runs import payload
    canonical = payload(insights.client.get("/v2/credit-decision", params={"project": record.project_code, "run": entry.history_id}))
    assert credit["timeline"] == canonical["runs"][0]["timeline"]
    assert credit["capacity"] == canonical["runs"][0]["capacity"]


@pytest.mark.parametrize("kind", ["solar", "wind"])
def test_missing_evidence_and_sponsor_equity_definitions_stay_separate(insights, kind):
    record = insights.create(kind)
    run(insights, record)
    entry = last(record)
    out = get(insights, record, entry)["runs"][0]
    metrics = metric_map(out)
    assert metrics["plcr"]["raw_value"] is None
    assert metrics["plcr"]["availability"] != "available"
    assert metrics["plcr"]["display_value"] not in ("0", "0.00x")
    sponsor = entry.sponsor_schedule["summary"]
    assert metrics["sponsor_irr"]["raw_value"] == sponsor.get("total_sponsor_xirr")
    assert metrics["equity_irr"]["raw_value"] == entry.runtime_summary.get("equity_irr")
    # Released reference Runs contain shareholder loans, so these actual returns differ.
    assert sponsor["total_shl_cash_contributed_keur"] > 0
    assert metrics["sponsor_irr"]["raw_value"] != metrics["equity_irr"]["raw_value"]
    assert metrics["sponsor_irr"]["source"] != metrics["equity_irr"]["source"]
    for key, metric in metrics.items():
        if metric["raw_value"] is None:
            assert metric["availability"] != "available", key
            assert metric["display_value"] not in ("0", "0%", "0.00%", "0 kEUR", "0.00x"), key
    sponsor_metrics = {m["key"]: m for m in out["sponsor"]["metrics"]}
    assert sponsor_metrics["sponsor_net_cash_flow"]["value"] is None
    assert sponsor_metrics["total_sponsor_distributions"]["value"] == sponsor.get("total_legal_equity_distributions_keur")


@pytest.mark.parametrize("kind,gearing", [("solar", 90), ("wind", 95)])
def test_converged_actual_run_is_not_automatically_credit_feasible(insights, kind, gearing):
    record = insights.create(kind)
    assert "field-error-banner" not in save(insights, record, config(sizing_mode="gearing_cap")).text
    set_field(insights, record, "debt.senior.gearing_pct", gearing)
    run(insights, record)
    data = get(insights, record, last(record))
    cap = data["runs"][0]["credit"]["capacity"]
    assert cap["convergence"]["termination_reason"]["v"] == "CONVERGED"
    assert cap["min_dscr"]["v"] < 1
    findings = [f for f in data["credit"]["findings"] if f["check_id"] == "CD-F2" or f["id"].endswith(":CD-F2")]
    assert len(findings) == 1 and findings[0]["status"] == "FAIL"
    assert findings[0]["classification"] == "OBSERVED_FINANCIAL_RESULT"


def test_stale_working_copy_and_later_run_preserve_exact_historical_evidence(insights):
    record = insights.create("solar")
    run(insights, record)
    first = last(record)
    before = get(insights, record, first)["runs"][0]
    frozen = frozen_history(record)
    assert "field-error-banner" not in save(insights, record, config(lender_case="P90-10y")).text
    stale = get(insights, record, first)["runs"][0]
    assert "STALE" in stale["identity"]["state"]
    assert stale["metrics"] == before["metrics"]
    assert frozen_history(record) == frozen
    run(insights, record)
    old = get(insights, record, first)["runs"][0]
    assert old["identity"]["state"] == "HISTORICAL"
    assert old["metrics"] == before["metrics"]
    for field in ("history_id", "snapshot_id", "scenario_id", "composite_hash", "engine_version", "workbook_version", "ran_at"):
        assert old["identity"][field] == before["identity"][field]
    assert first == next(e for e in history(record) if e.history_id == first.history_id)


def test_scenarios_compare_only_their_own_committed_run_and_require_explicit_selection(insights):
    from app.persistence.scenarios_repository import list_scenarios
    from app.v2.scenario_kpi_projection import build_compare_rows, build_scenario_projection
    from app.v2.run_history_projection import _enriched_kpis
    record = insights.create("solar")
    run(insights, record)
    base = last(record)
    assert post_valid_mutation(insights.client, "/v2/workbook/scenarios/create", headers={"HX-Request": "true"},
        data={"project": record.project_code, "scenario_name": "Revenue downside"}).status_code == 200
    scenario = next(s for s in list_scenarios(user_id=USER, project_id=record.project_id) if s.scenario_name == "Revenue downside")
    index = insights.client.get(INDEX, params={"project": record.project_code})
    assert index.status_code == 200
    assert "No committed Run exists for this scenario." in index.text
    assert post_valid_mutation(insights.client, "/v2/workbook/scenarios/update-overrides", headers={"HX-Request": "true"},
        data={"project": record.project_code, "scenario_id": scenario.scenario_id, "tariff_eur_mwh": "40"}).status_code == 200
    run(insights, record)
    down = last(record)
    assert down.last_runtime_scenario_id == scenario.scenario_id
    data = get(insights, record, base, down)
    assert [r["identity"]["scenario_id"] for r in data["runs"]] == [None, scenario.scenario_id]
    assert [metric_map(r)["total_revenue_keur"]["raw_value"] for r in data["runs"]] == [e.runtime_summary["total_revenue_keur"] for e in (base, down)]
    assert base.runtime_summary["total_revenue_keur"] != down.runtime_summary["total_revenue_keur"]
    expected = build_compare_rows([build_scenario_projection("", _enriched_kpis(e), e.ran_at, False) for e in (base, down)])
    rows = {r["key"]: r for r in data["comparison"]["rows"]}
    for row in expected:
        for field in ("raw_values", "values", "deltas", "variances"):
            assert rows[row.key][field] == getattr(row, field)
    response = insights.client.get(DETAIL, params={"project": record.project_code})
    assert response.status_code in (400, 422)
    mismatch = insights.client.get(DETAIL, params={"project": record.project_code, "run": base.history_id, "scenario_id": scenario.scenario_id})
    assert mismatch.status_code in (400, 404, 422)


def test_get_routes_never_execute_or_mutate_any_persisted_state(insights, monkeypatch):
    from app.persistence.workspace_repository import get_workspace_state
    record = insights.create("solar")
    run(insights, record)
    entry = last(record)
    # Warm existing read caches/schema before taking an exact logical DB snapshot.
    get(insights, record, entry)
    insights.client.get(INDEX, params={"project": record.project_code})
    before = db_snapshot()
    ws = get_workspace_state(USER, record.project_id)
    frozen = frozen_history(record)
    def forbidden(*args, **kwargs):
        raise AssertionError("analytics GET attempted model execution")
    monkeypatch.setattr("app.api.project_runner.run_project", forbidden)
    monkeypatch.setattr("app.services.production_financial_authority.run_clean_production", forbidden)
    for _ in range(2):
        get(insights, record, entry)
        response = insights.client.get(INDEX, params={"project": record.project_code})
        assert response.status_code == 200
        assert response.headers["cache-control"] == "private, no-store"
    assert get_workspace_state(USER, record.project_id) == ws
    assert frozen_history(record) == frozen
    assert db_snapshot() == before
    for path in (DETAIL, INDEX):
        assert insights.client.post(path, data={"project": record.project_code}).status_code == 405


def test_security_foreign_project_run_unauthenticated_and_selection_limits(insights):
    from app.auth import COOKIE_NAME, create_session_token
    record = insights.create("solar")
    run(insights, record)
    entry = last(record)
    other_project = insights.create("wind")
    run(insights, other_project)
    foreign = last(other_project)
    for run_id in ("unknown", foreign.history_id):
        response = insights.client.get(DETAIL, params={"project": record.project_code, "run": run_id})
        assert response.status_code == 404
        assert foreign.runtime_snapshot_id not in response.text
    assert insights.client.get(DETAIL, params=[("project", record.project_code)] + [("run", str(i)) for i in range(4)]).status_code == 422
    assert insights.client.get(DETAIL, params={"project": record.project_code, "run": "x" * 200}).status_code == 422
    for who in (None, "foreign-user"):
        with insights.client.__class__(insights.client.app) as client:
            if who:
                client.cookies.set(COOKIE_NAME, create_session_token(user_id=who, username="other"))
            for path in (DETAIL, INDEX):
                response = client.get(path, params={"project": record.project_code, "run": entry.history_id}, follow_redirects=False)
                assert response.status_code == (404 if who else 401)
                assert entry.runtime_snapshot_id not in response.text


def test_exactly_one_two_or_three_selected_committed_runs(insights):
    record = insights.create("solar")
    entries = []
    for _ in range(3):
        run(insights, record)
        entries.append(last(record))
    assert len({e.history_id for e in entries}) == 3
    for count in (1, 2, 3):
        data = get(insights, record, *entries[:count])
        assert [r["identity"]["history_id"] for r in data["runs"]] == [e.history_id for e in entries[:count]]


def test_flag_and_protected_reference_denial(insights, monkeypatch):
    record = insights.create("solar")
    monkeypatch.setattr("app.services.project_library_service.is_protected_reference", lambda record: True)
    for path in (DETAIL, INDEX):
        assert insights.client.get(path, params={"project": record.project_code}).status_code == 409
    monkeypatch.delenv("FINCO_MODEL_REACT_V1")
    for path in (DETAIL, INDEX):
        assert insights.client.get(path, params={"project": record.project_code}).status_code == 404


def test_incoherent_concurrent_working_copy_read_fails_closed(insights, monkeypatch):
    from app.v2.post_run_context import PostRunContextChanged, PostRunRequestContext
    record = insights.create("solar")
    run(insights, record)
    entry = last(record)
    frozen = frozen_history(record)
    def changed(self):
        raise PostRunContextChanged("test concurrent Working Copy revision")
    monkeypatch.setattr(PostRunRequestContext, "validate_current", changed)
    for path in (DETAIL, INDEX):
        params = {"project": record.project_code}
        if path == DETAIL:
            params["run"] = entry.history_id
        response = insights.client.get(path, params=params)
        assert response.status_code == 503
        assert response.json()["code"] == "INSIGHTS_CONTEXT_CHANGED"
        assert "runs" not in response.json()
    assert frozen_history(record) == frozen


def test_persisted_scenario_contradiction_is_rejected_without_pairing_metrics(insights):
    from dataclasses import replace
    from app.services.react_insights_service import InsightsIdentityError, build_insights
    record = insights.create("solar")
    run(insights, record)
    entry = last(record)
    contradictory = replace(entry, active_scenario_id="other-scenario", active_scenario_name="Wrong Case")
    with pytest.raises(InsightsIdentityError, match="scenario binding mismatch"):
        build_insights([contradictory], project_code=record.project_code, project_id=record.project_id)


@pytest.fixture
def committed_identity_entry(insights):
    record = insights.create("solar")
    run(insights, record)
    return record, last(record)


@pytest.mark.parametrize("field", ["snapshot_id", "composite_hash", "scenario_id", "workbook_version", "engine_version"])
def test_explicit_root_run_identity_contradiction_is_rejected(committed_identity_entry, field):
    from dataclasses import replace
    from app.services.react_insights_service import InsightsIdentityError, build_insights
    record, entry = committed_identity_entry
    identity = dict(entry.last_runtime_identity or {})
    identity[field] = "contradictory-" + field
    contradictory = replace(entry, last_runtime_identity=identity)
    frozen = frozen_history(record)
    with pytest.raises(InsightsIdentityError, match="Stored Run identity mismatch"):
        build_insights([contradictory], project_code=record.project_code, project_id=record.project_id)
    assert frozen_history(record) == frozen


@pytest.mark.parametrize("identity_absent", [False, True])
def test_legacy_absent_root_identity_fields_preserve_committed_evidence(committed_identity_entry, identity_absent):
    from dataclasses import replace
    from app.services.react_insights_service import build_insights
    record, entry = committed_identity_entry
    identity = dict(entry.last_runtime_identity or {})
    # Missing optional legacy root fields do not contradict the immutable row.
    # Existing nested Model V2/financing evidence remains intact and validated.
    for field in ("snapshot_id", "composite_hash", "scenario_id", "workbook_version", "engine_version"):
        identity.pop(field, None)
    legacy = replace(entry, last_runtime_identity=None if identity_absent else identity)
    before = build_insights([entry], project_code=record.project_code, project_id=record.project_id)
    after = build_insights([legacy], project_code=record.project_code, project_id=record.project_id)
    assert after == before
    assert after["runs"][0]["identity"]["snapshot_id"] == entry.runtime_snapshot_id
    assert metric_map(after["runs"][0])["min_dscr"]["raw_value"] == entry.runtime_summary["min_dscr"]
